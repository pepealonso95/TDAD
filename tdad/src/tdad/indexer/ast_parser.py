"""AST-based Python source parser.

Extracts functions, classes, imports, and call relationships from Python files.
Pure functions — no side effects or database access.
"""

import ast
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

TEST_FILE_PATTERNS = ["test_*.py", "*_test.py", "tests.py"]
TEST_FUNCTION_PATTERNS = ["test_*"]
TEST_CLASS_PATTERNS = ["Test*"]


# ------------------------------------------------------------------
# Data classes
# ------------------------------------------------------------------

@dataclass
class FunctionInfo:
    name: str
    file_path: str
    start_line: int
    end_line: int
    signature: str
    docstring: Optional[str]
    calls: List[str] = field(default_factory=list)
    is_test: bool = False


@dataclass
class ClassInfo:
    name: str
    file_path: str
    start_line: int
    end_line: int
    docstring: Optional[str]
    methods: List[FunctionInfo] = field(default_factory=list)
    bases: List[str] = field(default_factory=list)


@dataclass
class FileInfo:
    path: str
    relative_path: str
    name: str
    content_hash: str
    imports: List[str] = field(default_factory=list)
    functions: List[FunctionInfo] = field(default_factory=list)
    classes: List[ClassInfo] = field(default_factory=list)
    is_test_file: bool = False


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _matches_pattern(name: str, pattern: str) -> bool:
    from fnmatch import fnmatch
    return fnmatch(name, pattern)


def is_test_file(filename: str) -> bool:
    return any(_matches_pattern(filename, p) for p in TEST_FILE_PATTERNS)


def is_test_function(name: str) -> bool:
    return any(_matches_pattern(name, p) for p in TEST_FUNCTION_PATTERNS)


def is_test_class(name: str) -> bool:
    return any(_matches_pattern(name, p) for p in TEST_CLASS_PATTERNS)


# ------------------------------------------------------------------
# AST Visitor
# ------------------------------------------------------------------

class _ASTVisitor(ast.NodeVisitor):
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.imports: List[str] = []
        self.functions: List[FunctionInfo] = []
        self.classes: List[ClassInfo] = []
        self._current_class: Optional[str] = None

    # -- imports ----------------------------------------------------

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self.imports.append(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module:
            self.imports.append(node.module)
        self.generic_visit(node)

    # -- classes ----------------------------------------------------

    def visit_ClassDef(self, node: ast.ClassDef):
        prev = self._current_class
        self._current_class = node.name

        methods = []
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append(self._extract_function(item))

        self.classes.append(ClassInfo(
            name=node.name,
            file_path=self.file_path,
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            docstring=ast.get_docstring(node),
            methods=methods,
            bases=[self._get_name(b) for b in node.bases],
        ))
        self._current_class = prev

    # -- functions --------------------------------------------------

    def visit_FunctionDef(self, node: ast.FunctionDef):
        if self._current_class is None:
            self.functions.append(self._extract_function(node))

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        if self._current_class is None:
            self.functions.append(self._extract_function(node))

    # -- extraction helpers -----------------------------------------

    def _extract_function(self, node) -> FunctionInfo:
        args = []
        for arg in node.args.args:
            name = arg.arg
            if arg.annotation:
                name += f": {self._get_name(arg.annotation)}"
            args.append(name)

        sig = f"{node.name}({', '.join(args)})"
        if node.returns:
            sig += f" -> {self._get_name(node.returns)}"

        return FunctionInfo(
            name=node.name,
            file_path=self.file_path,
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            signature=sig,
            docstring=ast.get_docstring(node),
            calls=self._find_calls(node),
            is_test=is_test_function(node.name),
        )

    def _find_calls(self, node: ast.AST) -> List[str]:
        calls: List[str] = []

        class _CallCollector(ast.NodeVisitor):
            def visit_Call(self, call_node: ast.Call):
                name = self._call_name(call_node.func)
                if name:
                    calls.append(name)
                self.generic_visit(call_node)

            def _call_name(self, func_node: ast.AST) -> Optional[str]:
                if isinstance(func_node, ast.Name):
                    return func_node.id
                if isinstance(func_node, ast.Attribute):
                    prefix = self._call_name(func_node.value)
                    return f"{prefix}.{func_node.attr}" if prefix else func_node.attr
                return None

        _CallCollector().visit(node)
        return calls

    def _get_name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{self._get_name(node.value)}.{node.attr}"
        if isinstance(node, ast.Subscript):
            return f"{self._get_name(node.value)}[...]"
        return str(node)


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def parse_file(path: Path, repo_root: Path) -> FileInfo:
    """Parse a single Python file and return extracted information."""
    source = path.read_text(encoding="utf-8")
    content_hash = hashlib.md5(source.encode()).hexdigest()

    try:
        relative_path = str(path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        relative_path = path.name

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return FileInfo(
            path=str(path),
            relative_path=relative_path,
            name=path.name,
            content_hash=content_hash,
            is_test_file=is_test_file(path.name),
        )

    visitor = _ASTVisitor(relative_path)
    visitor.visit(tree)

    return FileInfo(
        path=str(path),
        relative_path=relative_path,
        name=path.name,
        content_hash=content_hash,
        imports=visitor.imports,
        functions=visitor.functions,
        classes=visitor.classes,
        is_test_file=is_test_file(path.name),
    )
