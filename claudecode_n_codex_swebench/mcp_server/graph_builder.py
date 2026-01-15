"""
AST-based Code Parser and Graph Builder

Parses Python source code using AST, extracts structural information,
and builds the code-test dependency graph in Neo4j.
"""
import ast
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import git

from .config import config
from .graph_db import get_db

logger = logging.getLogger(__name__)


@dataclass
class FunctionInfo:
    """Information about a function"""
    name: str
    file_path: str
    start_line: int
    end_line: int
    signature: str
    docstring: Optional[str]
    calls: List[str]  # Function names called
    is_test: bool


@dataclass
class ClassInfo:
    """Information about a class"""
    name: str
    file_path: str
    start_line: int
    end_line: int
    docstring: Optional[str]
    methods: List[FunctionInfo]
    bases: List[str]  # Parent class names


@dataclass
class FileInfo:
    """Information about a Python file"""
    path: str  # Absolute path
    relative_path: str  # Path relative to repo root
    name: str
    content_hash: str
    imports: List[str]  # Imported module names
    functions: List[FunctionInfo]
    classes: List[ClassInfo]
    is_test_file: bool


class ASTAnalyzer(ast.NodeVisitor):
    """AST visitor to extract code structure"""

    def __init__(self, file_path: str, source_code: str):
        self.file_path = file_path
        self.source_code = source_code
        self.source_lines = source_code.splitlines()

        self.imports: List[str] = []
        self.functions: List[FunctionInfo] = []
        self.classes: List[ClassInfo] = []
        self.current_class: Optional[str] = None

    def visit_Import(self, node: ast.Import):
        """Handle 'import module' statements"""
        for alias in node.names:
            self.imports.append(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        """Handle 'from module import name' statements"""
        if node.module:
            self.imports.append(node.module)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        """Handle class definitions"""
        class_name = node.name
        docstring = ast.get_docstring(node)
        bases = [self._get_name(base) for base in node.bases]

        # Save current class context
        prev_class = self.current_class
        self.current_class = class_name

        # Visit class body to collect methods
        methods = []
        for item in node.body:
            if isinstance(item, ast.FunctionDef) or isinstance(item, ast.AsyncFunctionDef):
                method = self._extract_function(item, is_method=True)
                methods.append(method)

        class_info = ClassInfo(
            name=class_name,
            file_path=self.file_path,
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            docstring=docstring,
            methods=methods,
            bases=bases
        )
        self.classes.append(class_info)

        # Restore previous class context
        self.current_class = prev_class

    def visit_FunctionDef(self, node: ast.FunctionDef):
        """Handle function definitions"""
        # Skip methods (handled in visit_ClassDef)
        if self.current_class is None:
            func_info = self._extract_function(node, is_method=False)
            self.functions.append(func_info)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        """Handle async function definitions"""
        if self.current_class is None:
            func_info = self._extract_function(node, is_method=False)
            self.functions.append(func_info)

    def _extract_function(self, node: ast.FunctionDef, is_method: bool) -> FunctionInfo:
        """Extract function information from AST node"""
        func_name = node.name
        docstring = ast.get_docstring(node)

        # Build signature
        args = []
        for arg in node.args.args:
            arg_name = arg.arg
            if arg.annotation:
                arg_name += f": {self._get_name(arg.annotation)}"
            args.append(arg_name)

        signature = f"{func_name}({', '.join(args)})"
        if node.returns:
            signature += f" -> {self._get_name(node.returns)}"

        # Find function calls
        calls = self._find_function_calls(node)

        # Check if it's a test function
        is_test = self._is_test_function(func_name)

        return FunctionInfo(
            name=func_name,
            file_path=self.file_path,
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            signature=signature,
            docstring=docstring,
            calls=calls,
            is_test=is_test
        )

    def _find_function_calls(self, node: ast.AST) -> List[str]:
        """Find all function calls within a node"""
        calls = []

        class CallVisitor(ast.NodeVisitor):
            def visit_Call(self, call_node: ast.Call):
                func_name = self._get_call_name(call_node.func)
                if func_name:
                    calls.append(func_name)
                self.generic_visit(call_node)

            def _get_call_name(self, func_node: ast.AST) -> Optional[str]:
                if isinstance(func_node, ast.Name):
                    return func_node.id
                elif isinstance(func_node, ast.Attribute):
                    return func_node.attr
                return None

        CallVisitor().visit(node)
        return calls

    def _get_name(self, node: ast.AST) -> str:
        """Get name from AST node"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            value = self._get_name(node.value)
            return f"{value}.{node.attr}"
        elif isinstance(node, ast.Subscript):
            value = self._get_name(node.value)
            return f"{value}[...]"
        return str(node)

    def _is_test_function(self, func_name: str) -> bool:
        """Check if function name matches test patterns"""
        for pattern in config.analysis.test_function_patterns:
            if pattern.startswith("*"):
                if func_name.endswith(pattern[1:]):
                    return True
            elif pattern.endswith("*"):
                if func_name.startswith(pattern[:-1]):
                    return True
            elif func_name == pattern:
                return True
        return False


class GraphBuilder:
    """Builds code-test dependency graph"""

    def __init__(self):
        self.db = get_db()
        self.repo_root: Optional[Path] = None

    def _to_relative_path(self, absolute_path: str) -> str:
        """Convert absolute path to relative path from repo root"""
        if not self.repo_root:
            return absolute_path

        try:
            abs_path = Path(absolute_path).resolve()
            rel_path = abs_path.relative_to(self.repo_root.resolve())
            return str(rel_path)
        except ValueError:
            # Path is not relative to repo_root
            logger.warning(f"Path {absolute_path} is not under repo root {self.repo_root}")
            return absolute_path

    def build_graph(self, repo_path: Path, force_rebuild: bool = False) -> Dict:
        """Build complete graph for a repository"""
        logger.info(f"Building graph for repository: {repo_path}")

        # Set repo root for relative path computation
        self.repo_root = Path(repo_path).resolve()
        logger.info(f"Repository root: {self.repo_root}")

        if force_rebuild:
            logger.warning("Force rebuild: clearing existing graph")
            self.db.clear_database()

        # Ensure schema exists
        self.db.create_schema()

        # Find all Python files
        python_files = self._find_python_files(repo_path)
        logger.info(f"Found {len(python_files)} Python files")

        # Parse files
        file_infos = []
        for file_path in python_files:
            try:
                file_info = self._parse_file(file_path, repo_path)
                file_infos.append(file_info)
            except Exception as e:
                logger.error(f"Error parsing {file_path}: {e}")

        # Build graph
        nodes_created = 0
        relationships_created = 0

        for file_info in file_infos:
            # Create file node using RELATIVE path
            self.db.create_file_node(
                path=file_info.relative_path,  # Use relative path!
                name=file_info.name,
                content_hash=file_info.content_hash,
                repo_path=str(repo_path),
                last_modified=datetime.fromtimestamp(Path(file_info.path).stat().st_mtime)
            )
            nodes_created += 1

            # Create function nodes using RELATIVE paths
            for func in file_info.functions:
                func_id = f"{file_info.relative_path}::{func.name}:{func.start_line}"
                self.db.create_function_node(
                    function_id=func_id,
                    name=func.name,
                    file_path=file_info.relative_path,  # Use relative path!
                    start_line=func.start_line,
                    end_line=func.end_line,
                    signature=func.signature,
                    docstring=func.docstring
                )
                nodes_created += 1

                # Link to file using RELATIVE path
                self.db.create_contains_relationship(file_info.relative_path, func_id, "Function")
                relationships_created += 1

                # Create test node if this is a test function
                if func.is_test:
                    test_id = f"test::{func_id}"
                    self.db.create_test_node(
                        test_id=test_id,
                        name=func.name,
                        file_path=file_info.relative_path,  # Use relative path!
                        function_name=func.name
                    )
                    nodes_created += 1

                    # Create CONTAINS relationship from File to Test
                    self.db.create_contains_relationship(file_info.relative_path, test_id, "Test")
                    relationships_created += 1

            # Create class nodes using RELATIVE paths
            for cls in file_info.classes:
                class_id = f"{file_info.relative_path}::{cls.name}:{cls.start_line}"
                self.db.create_class_node(
                    class_id=class_id,
                    name=cls.name,
                    file_path=file_info.relative_path,  # Use relative path!
                    start_line=cls.start_line,
                    end_line=cls.end_line,
                    docstring=cls.docstring
                )
                nodes_created += 1

                # Link to file using RELATIVE path
                self.db.create_contains_relationship(file_info.relative_path, class_id, "Class")
                relationships_created += 1

                # Create method nodes using RELATIVE paths
                for method in cls.methods:
                    method_id = f"{file_info.relative_path}::{cls.name}.{method.name}:{method.start_line}"
                    self.db.create_function_node(
                        function_id=method_id,
                        name=f"{cls.name}.{method.name}",
                        file_path=file_info.relative_path,  # Use relative path!
                        start_line=method.start_line,
                        end_line=method.end_line,
                        signature=method.signature,
                        docstring=method.docstring
                    )
                    nodes_created += 1

                    # Link method to class (using CONTAINS)
                    self.db.create_contains_relationship(class_id, method_id, "Function")
                    relationships_created += 1

        # Create relationships (second pass)
        relationships_created += self._create_relationships(file_infos)

        logger.info(f"Graph built: {nodes_created} nodes, {relationships_created} relationships")

        return {
            "nodes_created": nodes_created,
            "relationships_created": relationships_created,
            "files_processed": len(file_infos)
        }

    def incremental_update(self, repo_path: Path, changed_files: Optional[List[str]] = None, base_commit: str = "HEAD") -> Dict:
        """Incrementally update graph based on changed files"""
        logger.info(f"Incrementally updating graph for: {repo_path}")

        if changed_files is None:
            # Use git diff to find changed files
            changed_files = self._get_changed_files(repo_path, base_commit)

        logger.info(f"Updating {len(changed_files)} changed files")

        nodes_updated = 0
        relationships_updated = 0

        for file_path in changed_files:
            full_path = repo_path / file_path
            if full_path.exists() and full_path.suffix == '.py':
                try:
                    # Re-parse and update
                    file_info = self._parse_file(str(full_path))

                    # Update file node
                    self.db.create_file_node(
                        path=file_info.path,
                        name=file_info.name,
                        content_hash=file_info.content_hash,
                        repo_path=str(repo_path),
                        last_modified=datetime.fromtimestamp(full_path.stat().st_mtime)
                    )
                    nodes_updated += 1

                    # TODO: Update functions and classes
                    # This requires deleting old nodes and creating new ones

                except Exception as e:
                    logger.error(f"Error updating {file_path}: {e}")

        return {
            "nodes_updated": nodes_updated,
            "relationships_updated": relationships_updated
        }

    def _find_python_files(self, repo_path: Path) -> List[str]:
        """Find all Python files in repository"""
        python_files = []

        for file_path in repo_path.rglob("*.py"):
            # Skip common directories
            if any(part.startswith('.') or part in ['__pycache__', 'venv', 'env', 'node_modules'] for part in file_path.parts):
                continue

            python_files.append(str(file_path))

        return python_files

    def _parse_file(self, file_path: str, repo_path: Path) -> FileInfo:
        """Parse a Python file and extract structure"""
        with open(file_path, 'r', encoding='utf-8') as f:
            source_code = f.read()

        # Calculate content hash
        content_hash = hashlib.md5(source_code.encode()).hexdigest()

        # Compute relative path
        relative_path = self._to_relative_path(file_path)

        # Parse AST
        try:
            tree = ast.parse(source_code, filename=file_path)
        except SyntaxError as e:
            logger.warning(f"Syntax error in {file_path}: {e}")
            # Return minimal info for files with syntax errors
            return FileInfo(
                path=file_path,
                relative_path=relative_path,
                name=Path(file_path).name,
                content_hash=content_hash,
                imports=[],
                functions=[],
                classes=[],
                is_test_file=False
            )

        # Analyze AST
        analyzer = ASTAnalyzer(file_path, source_code)
        analyzer.visit(tree)

        # Check if this is a test file
        is_test_file = self._is_test_file(file_path)

        return FileInfo(
            path=file_path,
            relative_path=relative_path,
            name=Path(file_path).name,
            content_hash=content_hash,
            imports=analyzer.imports,
            functions=analyzer.functions,
            classes=analyzer.classes,
            is_test_file=is_test_file
        )

    def _is_test_file(self, file_path: str) -> bool:
        """Check if file is a test file based on name patterns"""
        file_name = Path(file_path).name

        for pattern in config.analysis.test_file_patterns:
            if pattern.startswith("*"):
                if file_name.endswith(pattern[1:]):
                    return True
            elif pattern.endswith("*"):
                if file_name.startswith(pattern[:-1]):
                    return True
            elif file_name == pattern:
                return True

        return False

    def _create_relationships(self, file_infos: List[FileInfo]) -> int:
        """Create relationships between nodes (second pass)"""
        relationships_created = 0

        # Build lookup maps
        function_map = {}  # func_name -> func_id
        file_map = {}  # module_name -> relative_path (for imports)

        for file_info in file_infos:
            # Build function map using relative paths (consistent with node creation)
            for func in file_info.functions:
                func_id = f"{file_info.relative_path}::{func.name}:{func.start_line}"
                function_map[func.name] = func_id

            # Build file map for imports
            # Convert path like "src/utils/helper.py" to module name "src.utils.helper"
            module_name = file_info.relative_path.replace('/', '.').replace('.py', '')
            file_map[module_name] = file_info.relative_path
            # Also map short names for common import patterns (e.g., "helper")
            short_name = Path(file_info.relative_path).stem
            if short_name not in file_map:
                file_map[short_name] = file_info.relative_path

        # Create CALLS relationships
        for file_info in file_infos:
            for func in file_info.functions:
                func_id = f"{file_info.relative_path}::{func.name}:{func.start_line}"

                for called_func_name in func.calls:
                    if called_func_name in function_map:
                        called_func_id = function_map[called_func_name]
                        if func_id != called_func_id:  # Avoid self-loops
                            try:
                                self.db.create_calls_relationship(func_id, called_func_id)
                                relationships_created += 1
                            except Exception as e:
                                logger.debug(f"Could not create CALLS relationship: {e}")

        # Create IMPORTS relationships
        for file_info in file_infos:
            for imported_module in file_info.imports:
                # Try to resolve import to a file in the repo
                target_path = file_map.get(imported_module)

                if not target_path:
                    # Try last components of module path (from x.y.z import w -> try "z", "y", etc.)
                    parts = imported_module.split('.')
                    for part in reversed(parts):
                        if part in file_map:
                            target_path = file_map[part]
                            break

                if target_path and target_path != file_info.relative_path:
                    try:
                        self.db.create_imports_relationship(file_info.relative_path, target_path)
                        relationships_created += 1
                        logger.debug(f"Import: {file_info.relative_path} -> {target_path}")
                    except Exception as e:
                        logger.debug(f"Could not create IMPORTS relationship: {e}")

        # Note: INHERITS relationships would require class hierarchy analysis
        # Note: TESTS relationships are created by TestLinker after graph building

        return relationships_created

    def _get_changed_files(self, repo_path: Path, base_commit: str) -> List[str]:
        """Get list of changed files using git diff"""
        try:
            repo = git.Repo(repo_path)
            diff = repo.git.diff('--name-only', base_commit)
            changed_files = [line.strip() for line in diff.splitlines() if line.strip()]
            return [f for f in changed_files if f.endswith('.py')]
        except Exception as e:
            logger.error(f"Error getting changed files from git: {e}")
            return []
