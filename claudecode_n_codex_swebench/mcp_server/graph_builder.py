"""
AST-based Code Parser and Graph Builder

Parses Python source code using AST, extracts structural information,
and builds the code-test dependency graph in Neo4j.
"""
import ast
import hashlib
import logging
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

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

    def __init__(
        self,
        file_path: str,
        source_code: str,
        test_function_patterns: Optional[List[str]] = None,
    ):
        self.file_path = file_path
        self.source_code = source_code
        self.source_lines = source_code.splitlines()
        self.test_function_patterns = list(
            test_function_patterns or config.analysis.test_function_patterns
        )

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
                    prefix = self._get_call_name(func_node.value)
                    return f"{prefix}.{func_node.attr}" if prefix else func_node.attr
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
        for pattern in self.test_function_patterns:
            if pattern.startswith("*"):
                if func_name.endswith(pattern[1:]):
                    return True
            elif pattern.endswith("*"):
                if func_name.startswith(pattern[:-1]):
                    return True
            elif func_name == pattern:
                return True
        return False


def _matches_glob_pattern(name: str, pattern: str) -> bool:
    """Simple wildcard matcher used for test file/function patterns."""
    if pattern.startswith("*"):
        return name.endswith(pattern[1:])
    if pattern.endswith("*"):
        return name.startswith(pattern[:-1])
    return name == pattern


def _is_test_file_path(file_name: str, test_file_patterns: List[str]) -> bool:
    for pattern in test_file_patterns:
        if _matches_glob_pattern(file_name, pattern):
            return True
    return False


def _parse_file_worker(
    file_path: str,
    repo_root: str,
    test_file_patterns: List[str],
    test_function_patterns: List[str],
) -> FileInfo:
    """Parse file in worker process for parallel indexing."""
    with open(file_path, "r", encoding="utf-8") as f:
        source_code = f.read()

    content_hash = hashlib.md5(source_code.encode()).hexdigest()
    try:
        relative_path = str(Path(file_path).resolve().relative_to(Path(repo_root).resolve()))
    except ValueError:
        relative_path = str(Path(file_path).name)
    file_name = Path(file_path).name

    try:
        tree = ast.parse(source_code, filename=file_path)
    except SyntaxError:
        return FileInfo(
            path=file_path,
            relative_path=relative_path,
            name=file_name,
            content_hash=content_hash,
            imports=[],
            functions=[],
            classes=[],
            is_test_file=False,
        )

    analyzer = ASTAnalyzer(
        file_path,
        source_code,
        test_function_patterns=test_function_patterns,
    )
    analyzer.visit(tree)

    return FileInfo(
        path=file_path,
        relative_path=relative_path,
        name=file_name,
        content_hash=content_hash,
        imports=analyzer.imports,
        functions=analyzer.functions,
        classes=analyzer.classes,
        is_test_file=_is_test_file_path(file_name, test_file_patterns),
    )


class GraphBuilder:
    """Builds code-test dependency graph"""

    def __init__(self):
        self.db = get_db()
        self.repo_root: Optional[Path] = None
        self._build_warnings: int = 0

    def _emit_progress(
        self,
        callback: Optional[Callable[[Dict[str, Any]], None]],
        *,
        stage: str,
        progress_pct: float,
        files_done: Optional[int] = None,
        files_total: Optional[int] = None,
        nodes_written: Optional[int] = None,
        edges_written: Optional[int] = None,
        message: Optional[str] = None,
    ) -> None:
        """Emit build progress updates to server/job manager."""
        if not callback:
            return
        payload: Dict[str, Any] = {
            "stage": stage,
            "progress_pct": max(0.0, min(100.0, float(progress_pct))),
        }
        if files_done is not None:
            payload["files_done"] = int(files_done)
        if files_total is not None:
            payload["files_total"] = int(files_total)
        if nodes_written is not None:
            payload["nodes_written"] = int(nodes_written)
        if edges_written is not None:
            payload["edges_written"] = int(edges_written)
        if message:
            payload["message"] = message
        try:
            callback(payload)
        except Exception as e:
            logger.debug(f"Progress callback failed: {e}")

    def _index_worker_count(self, file_count: int) -> int:
        """Compute process-pool worker count for parse stage."""
        cpu_count = os.cpu_count() or 4
        dynamic_default = max(4, cpu_count - 1)
        configured = max(1, int(config.graph_index.workers))
        workers = max(dynamic_default, configured)
        return max(1, min(workers, max(1, file_count)))

    def _parse_files_parallel(
        self,
        python_files: List[str],
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> List[FileInfo]:
        """Parse Python files concurrently for faster indexing."""
        if not python_files:
            return []
        if not self.repo_root:
            raise RuntimeError("repo_root must be set before parsing files")

        total = len(python_files)
        parsed: List[FileInfo] = []
        done = 0
        workers = self._index_worker_count(total)
        logger.info(f"Parsing {total} files with {workers} worker(s)")

        if workers <= 1:
            for file_path in python_files:
                try:
                    parsed.append(self._parse_file(file_path, self.repo_root))
                except Exception as e:
                    logger.error(f"Error parsing {file_path}: {e}")
                done += 1
                progress = 10.0 + 45.0 * (done / total)
                self._emit_progress(
                    progress_callback,
                    stage="parse_files",
                    progress_pct=progress,
                    files_done=done,
                    files_total=total,
                )
            return sorted(parsed, key=lambda item: item.relative_path)

        with ProcessPoolExecutor(max_workers=workers) as pool:
            future_to_path = {
                pool.submit(
                    _parse_file_worker,
                    file_path,
                    str(self.repo_root),
                    list(config.analysis.test_file_patterns),
                    list(config.analysis.test_function_patterns),
                ): file_path
                for file_path in python_files
            }
            for future in as_completed(future_to_path):
                file_path = future_to_path[future]
                try:
                    parsed.append(future.result())
                except Exception as e:
                    logger.error(f"Error parsing {file_path}: {e}")
                done += 1
                progress = 10.0 + 45.0 * (done / total)
                self._emit_progress(
                    progress_callback,
                    stage="parse_files",
                    progress_pct=progress,
                    files_done=done,
                    files_total=total,
                )

        return sorted(parsed, key=lambda item: item.relative_path)

    def _build_node_payloads(
        self,
        file_infos: List[FileInfo],
        repo_path: Path,
    ) -> Tuple[Dict[str, List[Dict[str, Any]]], int, int]:
        """Build batched node/contains payloads from parsed file info."""
        payloads: Dict[str, List[Dict[str, Any]]] = {
            "files": [],
            "functions": [],
            "classes": [],
            "tests": [],
            "contains": [],
        }
        nodes_created = 0
        relationships_created = 0

        for file_info in file_infos:
            module_name = self._module_name(file_info.relative_path)
            try:
                mtime = datetime.fromtimestamp(Path(file_info.path).stat().st_mtime).isoformat()
            except Exception:
                mtime = None
            payloads["files"].append(
                {
                    "path": file_info.relative_path,
                    "name": file_info.name,
                    "content_hash": file_info.content_hash,
                    "repo_path": str(repo_path),
                    "last_modified": mtime,
                }
            )
            nodes_created += 1

            for func in file_info.functions:
                func_id = f"{file_info.relative_path}::{func.name}:{func.start_line}"
                payloads["functions"].append(
                    {
                        "function_id": func_id,
                        "name": func.name,
                        "file_path": file_info.relative_path,
                        "start_line": func.start_line,
                        "end_line": func.end_line,
                        "signature": func.signature,
                        "docstring": func.docstring,
                        "embedding": None,
                        "symbol_key": self._function_symbol_key(file_info.relative_path, func.name),
                        "module_name": module_name,
                        "qualified_name": f"{module_name}.{func.name}",
                    }
                )
                payloads["contains"].append(
                    {
                        "parent_type": "File",
                        "parent_id": file_info.relative_path,
                        "node_id": func_id,
                        "node_type": "Function",
                    }
                )
                nodes_created += 1
                relationships_created += 1

                if func.is_test:
                    test_id = f"test::{func_id}"
                    payloads["tests"].append(
                        {
                            "test_id": test_id,
                            "name": func.name,
                            "file_path": file_info.relative_path,
                            "function_name": func.name,
                            "test_type": "pytest",
                        }
                    )
                    payloads["contains"].append(
                        {
                            "parent_type": "File",
                            "parent_id": file_info.relative_path,
                            "node_id": test_id,
                            "node_type": "Test",
                        }
                    )
                    nodes_created += 1
                    relationships_created += 1

            for cls in file_info.classes:
                class_id = f"{file_info.relative_path}::{cls.name}:{cls.start_line}"
                payloads["classes"].append(
                    {
                        "class_id": class_id,
                        "name": cls.name,
                        "file_path": file_info.relative_path,
                        "start_line": cls.start_line,
                        "end_line": cls.end_line,
                        "docstring": cls.docstring,
                        "embedding": None,
                        "symbol_key": self._class_symbol_key(file_info.relative_path, cls.name),
                        "module_name": module_name,
                        "qualified_name": f"{module_name}.{cls.name}",
                    }
                )
                payloads["contains"].append(
                    {
                        "parent_type": "File",
                        "parent_id": file_info.relative_path,
                        "node_id": class_id,
                        "node_type": "Class",
                    }
                )
                nodes_created += 1
                relationships_created += 1

                for method in cls.methods:
                    method_id = f"{file_info.relative_path}::{cls.name}.{method.name}:{method.start_line}"
                    payloads["functions"].append(
                        {
                            "function_id": method_id,
                            "name": f"{cls.name}.{method.name}",
                            "file_path": file_info.relative_path,
                            "start_line": method.start_line,
                            "end_line": method.end_line,
                            "signature": method.signature,
                            "docstring": method.docstring,
                            "embedding": None,
                            "symbol_key": self._function_symbol_key(
                                file_info.relative_path,
                                method.name,
                                class_name=cls.name,
                            ),
                            "module_name": module_name,
                            "qualified_name": f"{module_name}.{cls.name}.{method.name}",
                        }
                    )
                    payloads["contains"].append(
                        {
                            "parent_type": "Class",
                            "parent_id": class_id,
                            "node_id": method_id,
                            "node_type": "Function",
                        }
                    )
                    nodes_created += 1
                    relationships_created += 1

        return payloads, nodes_created, relationships_created

    def _persist_node_payloads(self, payloads: Dict[str, List[Dict[str, Any]]]) -> None:
        """Write node payloads with batched UNWIND queries."""
        self.db.upsert_file_nodes_batch(payloads["files"])
        self.db.upsert_function_nodes_batch(payloads["functions"])
        self.db.upsert_class_nodes_batch(payloads["classes"])
        self.db.upsert_test_nodes_batch(payloads["tests"])
        self.db.create_contains_relationships_batch(payloads["contains"])

    def _module_name(self, relative_path: str) -> str:
        """Convert repository-relative file path to dotted module path."""
        normalized = relative_path.replace("\\", "/")
        if normalized.endswith(".py"):
            normalized = normalized[:-3]
        return normalized.replace("/", ".").strip(".")

    def _class_symbol_key(self, relative_path: str, class_name: str) -> str:
        """Canonical class symbol identity."""
        return f"{self._module_name(relative_path)}::{class_name}"

    def _function_symbol_key(
        self,
        relative_path: str,
        function_name: str,
        class_name: Optional[str] = None,
    ) -> str:
        """Canonical function/method symbol identity."""
        module_name = self._module_name(relative_path)
        if class_name:
            return f"{module_name}::{class_name}::{function_name}"
        return f"{module_name}::{function_name}"

    def _resolve_repo_fingerprint(
        self,
        repo_path: Path,
        commit_sha: Optional[str] = None,
        repo_fingerprint: Optional[str] = None,
    ) -> str:
        """Resolve graph freshness fingerprint from commit + working tree delta."""
        if repo_fingerprint:
            return repo_fingerprint

        resolved_commit = self._resolve_commit_sha(repo_path, commit_sha=commit_sha)
        try:
            repo = git.Repo(repo_path)
            dirty = repo.git.status("--porcelain")
            dirty_hash = hashlib.sha1(dirty.encode("utf-8")).hexdigest()[:12] if dirty else "clean"
            return f"{resolved_commit}:{dirty_hash}"
        except Exception as e:
            logger.debug(f"Failed to resolve repo fingerprint: {e}")
            return f"{resolved_commit}:unknown"

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

    def _normalize_changed_files(self, repo_path: Path, changed_files: List[str]) -> List[str]:
        """Normalize changed file inputs to unique repository-relative Python paths."""
        normalized: List[str] = []
        seen: Set[str] = set()
        repo_root = Path(repo_path).resolve()

        for raw_path in changed_files:
            if not raw_path:
                continue

            candidate = Path(raw_path)
            if candidate.is_absolute():
                try:
                    rel = candidate.resolve().relative_to(repo_root)
                    rel_path = str(rel)
                except ValueError:
                    logger.debug(f"Skipping out-of-repo changed file path: {raw_path}")
                    continue
            else:
                rel_path = str(candidate)

            if not rel_path.endswith(".py"):
                continue

            if rel_path not in seen:
                seen.add(rel_path)
                normalized.append(rel_path)

        return normalized

    def _resolve_repo_slug(self, repo_path: Path, repo_slug: Optional[str] = None) -> str:
        """Resolve repository slug in owner/repo format."""
        if repo_slug:
            return repo_slug

        try:
            repo = git.Repo(repo_path)
            remote_url = next(repo.remote("origin").urls)
            if remote_url.endswith(".git"):
                remote_url = remote_url[:-4]
            if remote_url.startswith("git@"):
                path_part = remote_url.split(":", 1)[-1]
            elif "://" in remote_url:
                host_and_path = remote_url.split("://", 1)[-1]
                path_part = host_and_path.split("/", 1)[-1]
            else:
                path_part = remote_url
            parts = [p for p in path_part.strip("/").split("/") if p]
            if len(parts) >= 2:
                return f"{parts[-2]}/{parts[-1]}"
        except Exception as e:
            logger.debug(f"Failed to resolve repo slug: {e}")

        return Path(repo_path).name

    def _resolve_commit_sha(self, repo_path: Path, commit_sha: Optional[str] = None) -> str:
        """Resolve commit SHA for indexed graph identity."""
        if commit_sha:
            return commit_sha

        try:
            repo = git.Repo(repo_path)
            return repo.head.commit.hexsha
        except Exception as e:
            logger.debug(f"Failed to resolve commit SHA: {e}")
            return "unknown"

    def _iter_function_records(self, file_info: FileInfo) -> List[Dict[str, Optional[str]]]:
        """Iterate module functions and class methods with consistent metadata."""
        records: List[Dict[str, Optional[str]]] = []

        for func in file_info.functions:
            records.append(
                {
                    "id": f"{file_info.relative_path}::{func.name}:{func.start_line}",
                    "function_name": func.name,
                    "display_name": func.name,
                    "class_name": None,
                    "calls": func.calls,
                    "file_path": file_info.relative_path,
                }
            )

        for cls in file_info.classes:
            for method in cls.methods:
                records.append(
                    {
                        "id": f"{file_info.relative_path}::{cls.name}.{method.name}:{method.start_line}",
                        "function_name": method.name,
                        "display_name": f"{cls.name}.{method.name}",
                        "class_name": cls.name,
                        "calls": method.calls,
                        "file_path": file_info.relative_path,
                    }
                )

        return records

    def _build_symbol_maps_from_file_infos(
        self, file_infos: List[FileInfo]
    ) -> Tuple[Dict[str, Dict[str, List[str]]], Dict[str, Dict[str, List[str]]], Dict[str, str]]:
        """Build function/class/file lookup maps from parsed file infos."""
        function_maps: Dict[str, Dict[str, List[str]]] = {
            "by_symbol_key": {},
            "by_qualified_name": {},
            "by_simple_name": {},
        }
        class_maps: Dict[str, Dict[str, List[str]]] = {
            "by_symbol_key": {},
            "by_qualified_name": {},
            "by_simple_name": {},
        }
        file_map: Dict[str, str] = {}

        for file_info in file_infos:
            module_name = self._module_name(file_info.relative_path)
            file_map[module_name] = file_info.relative_path
            file_map.setdefault(Path(file_info.relative_path).stem, file_info.relative_path)

            for record in self._iter_function_records(file_info):
                function_id = str(record["id"])
                function_name = str(record["function_name"])
                class_name = record["class_name"]
                symbol_key = self._function_symbol_key(
                    file_info.relative_path,
                    function_name,
                    class_name=class_name,
                )
                function_maps["by_symbol_key"].setdefault(symbol_key, []).append(function_id)
                function_maps["by_simple_name"].setdefault(function_name, []).append(function_id)
                display_name = str(record["display_name"])
                function_maps["by_simple_name"].setdefault(display_name, []).append(function_id)
                if class_name:
                    function_maps["by_qualified_name"].setdefault(
                        f"{class_name}.{function_name}", []
                    ).append(function_id)
                    function_maps["by_qualified_name"].setdefault(
                        f"{module_name}.{class_name}.{function_name}", []
                    ).append(function_id)
                else:
                    function_maps["by_qualified_name"].setdefault(
                        f"{module_name}.{function_name}", []
                    ).append(function_id)

            for cls in file_info.classes:
                class_id = f"{file_info.relative_path}::{cls.name}:{cls.start_line}"
                class_symbol = self._class_symbol_key(file_info.relative_path, cls.name)
                class_maps["by_symbol_key"].setdefault(class_symbol, []).append(class_id)
                class_maps["by_simple_name"].setdefault(cls.name, []).append(class_id)
                class_maps["by_qualified_name"].setdefault(
                    f"{module_name}.{cls.name}", []
                ).append(class_id)

        return function_maps, class_maps, file_map

    def _build_symbol_maps_from_db_rows(
        self,
        function_rows: List[Dict],
        class_rows: List[Dict],
        file_rows: List[Dict],
    ) -> Tuple[Dict[str, Dict[str, List[str]]], Dict[str, Dict[str, List[str]]], Dict[str, str]]:
        """Build function/class/file lookup maps from persisted graph rows."""
        function_maps: Dict[str, Dict[str, List[str]]] = {
            "by_symbol_key": {},
            "by_qualified_name": {},
            "by_simple_name": {},
        }
        class_maps: Dict[str, Dict[str, List[str]]] = {
            "by_symbol_key": {},
            "by_qualified_name": {},
            "by_simple_name": {},
        }
        file_map: Dict[str, str] = {}

        for row in function_rows:
            function_id = row.get("id")
            name = row.get("name")
            file_path = row.get("file_path")
            symbol_key = row.get("symbol_key")
            qualified_name = row.get("qualified_name")
            if not function_id or not name or not file_path:
                continue

            module_name = self._module_name(str(file_path))
            simple_name = str(name).split(".")[-1]
            display_name = str(name)

            if symbol_key:
                function_maps["by_symbol_key"].setdefault(str(symbol_key), []).append(function_id)
            else:
                if "." in display_name:
                    class_name = display_name.split(".", 1)[0]
                    function_maps["by_symbol_key"].setdefault(
                        f"{module_name}::{class_name}::{simple_name}", []
                    ).append(function_id)
                else:
                    function_maps["by_symbol_key"].setdefault(
                        f"{module_name}::{simple_name}", []
                    ).append(function_id)

            if qualified_name:
                function_maps["by_qualified_name"].setdefault(str(qualified_name), []).append(function_id)
            else:
                if "." in display_name:
                    class_name = display_name.split(".", 1)[0]
                    function_maps["by_qualified_name"].setdefault(
                        f"{module_name}.{class_name}.{simple_name}", []
                    ).append(function_id)
                    function_maps["by_qualified_name"].setdefault(
                        f"{class_name}.{simple_name}", []
                    ).append(function_id)
                else:
                    function_maps["by_qualified_name"].setdefault(
                        f"{module_name}.{simple_name}", []
                    ).append(function_id)

            function_maps["by_simple_name"].setdefault(simple_name, []).append(function_id)
            function_maps["by_simple_name"].setdefault(display_name, []).append(function_id)

        for row in class_rows:
            class_id = row.get("id")
            name = row.get("name")
            file_path = row.get("file_path")
            symbol_key = row.get("symbol_key")
            qualified_name = row.get("qualified_name")
            if not class_id or not name or not file_path:
                continue
            module_name = self._module_name(str(file_path))
            class_maps["by_simple_name"].setdefault(str(name), []).append(class_id)
            if symbol_key:
                class_maps["by_symbol_key"].setdefault(str(symbol_key), []).append(class_id)
            else:
                class_maps["by_symbol_key"].setdefault(f"{module_name}::{name}", []).append(class_id)
            if qualified_name:
                class_maps["by_qualified_name"].setdefault(str(qualified_name), []).append(class_id)
            else:
                class_maps["by_qualified_name"].setdefault(f"{module_name}.{name}", []).append(class_id)

        for row in file_rows:
            path = row.get("path")
            if not path:
                continue
            module_name = self._module_name(path)
            file_map[module_name] = path
            file_map.setdefault(Path(path).stem, path)

        return function_maps, class_maps, file_map

    def _resolve_function_candidates(
        self,
        called_name: str,
        caller_module: str,
        caller_class: Optional[str],
        function_maps: Dict[str, Dict[str, List[str]]],
    ) -> Tuple[List[Tuple[str, str, float]], int]:
        """Resolve function call targets with confidence-scored fallbacks."""
        normalized = (called_name or "").strip()
        if not normalized:
            return [], 0

        candidates: List[Tuple[str, str, float]] = []
        seen: Set[str] = set()
        ambiguity_warnings = 0

        def add(ids: Optional[List[str]], method: str, confidence: float):
            nonlocal ambiguity_warnings
            if not ids:
                return
            unique_ids = list(dict.fromkeys(ids))
            if len(unique_ids) > 1:
                ambiguity_warnings += 1
                confidence = min(confidence, 0.55)
            for candidate_id in unique_ids:
                if candidate_id in seen:
                    continue
                seen.add(candidate_id)
                candidates.append((candidate_id, method, confidence))

        simple_name = normalized.split(".")[-1]

        if normalized.startswith("self.") or normalized.startswith("cls."):
            method_name = normalized.split(".", 1)[1]
            if caller_class:
                add(
                    function_maps["by_symbol_key"].get(
                        f"{caller_module}::{caller_class}::{method_name}"
                    ),
                    "self_symbol_key",
                    0.98,
                )
                add(
                    function_maps["by_qualified_name"].get(f"{caller_class}.{method_name}"),
                    "self_class_method",
                    0.92,
                )
            add(function_maps["by_simple_name"].get(method_name), "method_simple_name", 0.72)
            return candidates, ambiguity_warnings

        if "." in normalized:
            add(
                function_maps["by_qualified_name"].get(normalized),
                "qualified_name",
                0.9,
            )
            add(
                function_maps["by_qualified_name"].get(f"{caller_module}.{normalized}"),
                "module_qualified_name",
                0.95,
            )
            class_method = ".".join(normalized.split(".")[-2:])
            add(
                function_maps["by_qualified_name"].get(class_method),
                "class_method",
                0.88,
            )

        if caller_class:
            add(
                function_maps["by_symbol_key"].get(f"{caller_module}::{caller_class}::{simple_name}"),
                "caller_class_symbol_key",
                0.95,
            )
            add(
                function_maps["by_qualified_name"].get(f"{caller_class}.{simple_name}"),
                "caller_class_method",
                0.86,
            )

        add(
            function_maps["by_symbol_key"].get(f"{caller_module}::{simple_name}"),
            "module_symbol_key",
            0.95,
        )
        add(
            function_maps["by_qualified_name"].get(f"{caller_module}.{simple_name}"),
            "module_qualified_name",
            0.9,
        )
        add(function_maps["by_simple_name"].get(simple_name), "simple_name", 0.7)
        add(function_maps["by_simple_name"].get(normalized), "raw_name", 0.68)

        return candidates, ambiguity_warnings

    def _resolve_class_candidates(
        self,
        base_name: str,
        child_module: str,
        class_maps: Dict[str, Dict[str, List[str]]],
    ) -> Tuple[List[Tuple[str, str, float]], int]:
        """Resolve parent class candidates with confidence-scored fallbacks."""
        normalized = (base_name or "").strip()
        if not normalized:
            return [], 0

        candidates: List[Tuple[str, str, float]] = []
        seen: Set[str] = set()
        ambiguity_warnings = 0

        def add(ids: Optional[List[str]], method: str, confidence: float):
            nonlocal ambiguity_warnings
            if not ids:
                return
            unique_ids = list(dict.fromkeys(ids))
            if len(unique_ids) > 1:
                ambiguity_warnings += 1
                confidence = min(confidence, 0.5)
            for class_id in unique_ids:
                if class_id in seen:
                    continue
                seen.add(class_id)
                candidates.append((class_id, method, confidence))

        simple_name = normalized.split(".")[-1]
        if "." in normalized:
            add(class_maps["by_qualified_name"].get(normalized), "qualified_name", 0.92)
            add(class_maps["by_qualified_name"].get(f"{child_module}.{normalized}"), "module_qualified_name", 0.9)
        add(class_maps["by_symbol_key"].get(f"{child_module}::{simple_name}"), "module_symbol_key", 0.9)
        add(class_maps["by_qualified_name"].get(f"{child_module}.{simple_name}"), "module_qualified_name", 0.86)
        add(class_maps["by_simple_name"].get(simple_name), "simple_name_fallback", 0.66)

        return candidates, ambiguity_warnings

    def build_graph(
        self,
        repo_path: Path,
        force_rebuild: bool = False,
        repo_slug: Optional[str] = None,
        commit_sha: Optional[str] = None,
        repo_fingerprint: Optional[str] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict:
        """Build complete graph for a repository"""
        logger.info(f"Building graph for repository: {repo_path}")
        build_start = time.time()
        timings: Dict[str, float] = {}

        # Set repo root for relative path computation
        self.repo_root = Path(repo_path).resolve()
        logger.info(f"Repository root: {self.repo_root}")
        self._emit_progress(
            progress_callback,
            stage="initializing",
            progress_pct=1.0,
            message="Starting graph build",
        )

        resolved_repo_slug = self._resolve_repo_slug(repo_path, repo_slug=repo_slug)
        resolved_commit_sha = self._resolve_commit_sha(repo_path, commit_sha=commit_sha)
        resolved_repo_fingerprint = self._resolve_repo_fingerprint(
            repo_path,
            commit_sha=resolved_commit_sha,
            repo_fingerprint=repo_fingerprint,
        )
        graph_identity = f"{resolved_repo_slug}@{resolved_commit_sha}"

        if not force_rebuild:
            try:
                active_meta = self.db.get_index_metadata()
            except Exception as e:
                logger.debug(f"Unable to read active graph metadata before build: {e}")
                active_meta = {}
            active_identity = str((active_meta or {}).get("graph_identity") or "")
            if active_identity and active_identity != graph_identity:
                logger.warning(
                    "Graph identity changed (%s -> %s); clearing DB to avoid cross-identity contamination",
                    active_identity,
                    graph_identity,
                )
                t0 = time.time()
                self.db.clear_database()
                timings["clear_database_sec"] = time.time() - t0

        if force_rebuild:
            logger.warning("Force rebuild: clearing existing graph")
            t0 = time.time()
            self.db.clear_database()
            timings["clear_database_sec"] = time.time() - t0

        # Ensure schema exists
        t0 = time.time()
        self.db.create_schema()
        timings["schema_sec"] = time.time() - t0

        # Find all Python files
        t0 = time.time()
        python_files = self._find_python_files(repo_path)
        timings["discover_files_sec"] = time.time() - t0
        logger.info(f"Found {len(python_files)} Python files")
        self._emit_progress(
            progress_callback,
            stage="discover_files",
            progress_pct=8.0,
            files_done=0,
            files_total=len(python_files),
        )

        # Parse files in parallel
        t0 = time.time()
        file_infos = self._parse_files_parallel(python_files, progress_callback=progress_callback)
        timings["parse_files_sec"] = time.time() - t0

        self._build_warnings = 0
        self._emit_progress(
            progress_callback,
            stage="prepare_nodes",
            progress_pct=58.0,
            files_done=len(file_infos),
            files_total=len(python_files),
        )
        t0 = time.time()
        payloads, nodes_created, contains_relationships = self._build_node_payloads(file_infos, repo_path)
        timings["prepare_nodes_sec"] = time.time() - t0

        # Write nodes + CONTAINS edges in batches
        self._emit_progress(
            progress_callback,
            stage="persist_nodes",
            progress_pct=66.0,
            nodes_written=0,
            edges_written=0,
        )
        t0 = time.time()
        self._persist_node_payloads(payloads)
        timings["persist_nodes_sec"] = time.time() - t0
        relationships_created = contains_relationships
        self._emit_progress(
            progress_callback,
            stage="persist_nodes",
            progress_pct=80.0,
            nodes_written=nodes_created,
            edges_written=relationships_created,
        )

        # Create import/call/inheritance relationships (second pass)
        self._emit_progress(
            progress_callback,
            stage="resolve_relationships",
            progress_pct=84.0,
            nodes_written=nodes_created,
            edges_written=relationships_created,
        )
        t0 = time.time()
        rel_count, warning_count = self._create_relationships(file_infos)
        timings["resolve_relationships_sec"] = time.time() - t0
        relationships_created += rel_count
        self._build_warnings += warning_count
        self._emit_progress(
            progress_callback,
            stage="persist_edges",
            progress_pct=94.0,
            nodes_written=nodes_created,
            edges_written=relationships_created,
        )

        self.db.update_index_metadata(
            repo_path=str(self.repo_root),
            path_format="relative",
            repo_slug=resolved_repo_slug,
            commit_sha=resolved_commit_sha,
            graph_identity=graph_identity,
            repo_fingerprint=resolved_repo_fingerprint,
            build_mode="full",
            graph_version="v2",
            symbol_identity_scheme="module::class::function",
            build_warnings_count=self._build_warnings,
        )
        timings["total_sec"] = time.time() - build_start
        self._emit_progress(
            progress_callback,
            stage="completed",
            progress_pct=100.0,
            files_done=len(file_infos),
            files_total=len(python_files),
            nodes_written=nodes_created,
            edges_written=relationships_created,
            message="Graph build completed",
        )

        logger.info(f"Graph built: {nodes_created} nodes, {relationships_created} relationships")

        return {
            "nodes_created": nodes_created,
            "relationships_created": relationships_created,
            "files_processed": len(file_infos),
            "build_warnings_count": self._build_warnings,
            "repo_fingerprint": resolved_repo_fingerprint,
            "index_timing": timings,
        }

    def incremental_update(
        self,
        repo_path: Path,
        changed_files: Optional[List[str]] = None,
        base_commit: str = "HEAD",
        repo_slug: Optional[str] = None,
        commit_sha: Optional[str] = None,
        repo_fingerprint: Optional[str] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict:
        """Incrementally update graph based on changed files"""
        logger.info(f"Incrementally updating graph for: {repo_path}")
        self.repo_root = Path(repo_path).resolve()
        update_start = time.time()
        timings: Dict[str, float] = {}

        if changed_files is None:
            # Use git diff to find changed files
            changed_files = self._get_changed_files(repo_path, base_commit)
        changed_files = self._normalize_changed_files(repo_path, changed_files)

        logger.info(f"Updating {len(changed_files)} changed files")

        self._build_warnings = 0
        nodes_updated = 0
        relationships_updated = 0
        file_infos: List[FileInfo] = []
        files_removed = 0
        files_total = len(changed_files)
        files_done = 0
        self._emit_progress(
            progress_callback,
            stage="incremental_start",
            progress_pct=5.0,
            files_done=0,
            files_total=files_total,
        )

        t0 = time.time()
        for relative_path in changed_files:
            full_path = self.repo_root / relative_path
            if full_path.exists() and full_path.suffix == '.py':
                try:
                    # Re-parse and update
                    file_info = self._parse_file(str(full_path), repo_path)
                    # Preserve the File node for modified files so incoming
                    # IMPORTS relationships from other files are not dropped.
                    self._delete_file_subgraph(file_info.relative_path, drop_file_node=False)
                    file_infos.append(file_info)

                except Exception as e:
                    logger.error(f"Error updating {relative_path}: {e}")
            else:
                try:
                    # Deleted files must remove the File node entirely.
                    self._delete_file_subgraph(relative_path, drop_file_node=True)
                    files_removed += 1
                except Exception as e:
                    logger.error(f"Error removing deleted file graph for {relative_path}: {e}")
            files_done += 1
            progress = 5.0 + (35.0 * (files_done / max(files_total, 1)))
            self._emit_progress(
                progress_callback,
                stage="incremental_parse",
                progress_pct=progress,
                files_done=files_done,
                files_total=files_total,
            )
        timings["incremental_parse_sec"] = time.time() - t0

        # Recreate updated nodes for changed files in batched writes.
        self._emit_progress(
            progress_callback,
            stage="incremental_persist_nodes",
            progress_pct=45.0,
            files_done=files_done,
            files_total=files_total,
        )
        t0 = time.time()
        payloads, nodes_updated, contains_relationships = self._build_node_payloads(file_infos, repo_path)
        self._persist_node_payloads(payloads)
        timings["incremental_persist_nodes_sec"] = time.time() - t0
        relationships_updated += contains_relationships

        # Recreate relationships from changed files to the current graph.
        self._emit_progress(
            progress_callback,
            stage="incremental_persist_edges",
            progress_pct=72.0,
            nodes_written=nodes_updated,
            edges_written=relationships_updated,
        )
        t0 = time.time()
        rel_count, warning_count = self._create_relationships_incremental(file_infos)
        timings["incremental_persist_edges_sec"] = time.time() - t0
        relationships_updated += rel_count
        self._build_warnings += warning_count

        resolved_repo_slug = self._resolve_repo_slug(repo_path, repo_slug=repo_slug)
        resolved_commit_sha = self._resolve_commit_sha(repo_path, commit_sha=commit_sha)
        resolved_repo_fingerprint = self._resolve_repo_fingerprint(
            repo_path,
            commit_sha=resolved_commit_sha,
            repo_fingerprint=repo_fingerprint,
        )
        graph_identity = f"{resolved_repo_slug}@{resolved_commit_sha}"
        self.db.update_index_metadata(
            repo_path=str(self.repo_root),
            path_format="relative",
            repo_slug=resolved_repo_slug,
            commit_sha=resolved_commit_sha,
            graph_identity=graph_identity,
            repo_fingerprint=resolved_repo_fingerprint,
            build_mode="incremental",
            graph_version="v2",
            symbol_identity_scheme="module::class::function",
            build_warnings_count=self._build_warnings,
        )
        timings["total_sec"] = time.time() - update_start
        self._emit_progress(
            progress_callback,
            stage="incremental_completed",
            progress_pct=100.0,
            files_done=files_done,
            files_total=files_total,
            nodes_written=nodes_updated,
            edges_written=relationships_updated,
        )

        return {
            "nodes_updated": nodes_updated,
            "relationships_updated": relationships_updated,
            "files_removed": files_removed,
            "build_warnings_count": self._build_warnings,
            "repo_fingerprint": resolved_repo_fingerprint,
            "index_timing": timings,
        }

    def _delete_file_subgraph(self, relative_path: str, *, drop_file_node: bool = True) -> None:
        """Delete contained nodes for a file, optionally dropping the File node too."""
        with self.db.driver.session(database=config.neo4j.database) as session:
            if drop_file_node:
                session.run(
                    """
                    MATCH (f:File {path: $file_path})
                    OPTIONAL MATCH (f)-[:CONTAINS]->(n)
                    DETACH DELETE n
                    WITH f
                    DETACH DELETE f
                    """,
                    file_path=relative_path,
                )
            else:
                session.run(
                    """
                    MATCH (f:File {path: $file_path})
                    OPTIONAL MATCH (f)-[r:IMPORTS]->()
                    DELETE r
                    WITH f
                    OPTIONAL MATCH (f)-[:CONTAINS]->(n)
                    DETACH DELETE n
                    """,
                    file_path=relative_path,
                )

    def _create_nodes_for_file(self, file_info: FileInfo, repo_path: Path) -> Tuple[int, int]:
        """Create file/function/class/test nodes for a single parsed file."""
        nodes_created = 0
        relationships_created = 0
        module_name = self._module_name(file_info.relative_path)

        self.db.create_file_node(
            path=file_info.relative_path,
            name=file_info.name,
            content_hash=file_info.content_hash,
            repo_path=str(repo_path),
            last_modified=datetime.fromtimestamp(Path(file_info.path).stat().st_mtime),
        )
        nodes_created += 1

        for func in file_info.functions:
            func_id = f"{file_info.relative_path}::{func.name}:{func.start_line}"
            self.db.create_function_node(
                function_id=func_id,
                name=func.name,
                file_path=file_info.relative_path,
                start_line=func.start_line,
                end_line=func.end_line,
                signature=func.signature,
                docstring=func.docstring,
                symbol_key=self._function_symbol_key(file_info.relative_path, func.name),
                module_name=module_name,
                qualified_name=f"{module_name}.{func.name}",
            )
            nodes_created += 1

            self.db.create_contains_relationship(file_info.relative_path, func_id, "Function")
            relationships_created += 1

            if func.is_test:
                test_id = f"test::{func_id}"
                self.db.create_test_node(
                    test_id=test_id,
                    name=func.name,
                    file_path=file_info.relative_path,
                    function_name=func.name,
                )
                nodes_created += 1
                self.db.create_contains_relationship(file_info.relative_path, test_id, "Test")
                relationships_created += 1

        for cls in file_info.classes:
            class_id = f"{file_info.relative_path}::{cls.name}:{cls.start_line}"
            self.db.create_class_node(
                class_id=class_id,
                name=cls.name,
                file_path=file_info.relative_path,
                start_line=cls.start_line,
                end_line=cls.end_line,
                docstring=cls.docstring,
                symbol_key=self._class_symbol_key(file_info.relative_path, cls.name),
                module_name=module_name,
                qualified_name=f"{module_name}.{cls.name}",
            )
            nodes_created += 1
            self.db.create_contains_relationship(file_info.relative_path, class_id, "Class")
            relationships_created += 1

            for method in cls.methods:
                method_id = f"{file_info.relative_path}::{cls.name}.{method.name}:{method.start_line}"
                self.db.create_function_node(
                    function_id=method_id,
                    name=f"{cls.name}.{method.name}",
                    file_path=file_info.relative_path,
                    start_line=method.start_line,
                    end_line=method.end_line,
                    signature=method.signature,
                    docstring=method.docstring,
                    symbol_key=self._function_symbol_key(
                        file_info.relative_path,
                        method.name,
                        class_name=cls.name,
                    ),
                    module_name=module_name,
                    qualified_name=f"{module_name}.{cls.name}.{method.name}",
                )
                nodes_created += 1
                self.db.create_contains_relationship(class_id, method_id, "Function")
                relationships_created += 1

        return nodes_created, relationships_created

    def _create_relationships_incremental(self, file_infos: List[FileInfo]) -> Tuple[int, int]:
        """Recreate import/call/inheritance relationships for changed files against current graph."""
        if not file_infos:
            return 0, 0

        warning_count = 0
        calls_map: Dict[Tuple[str, str], Tuple[str, float]] = {}
        imports_set: Set[Tuple[str, str]] = set()
        inherits_map: Dict[Tuple[str, str], Tuple[str, float]] = {}

        with self.db.driver.session(database=config.neo4j.database) as session:
            function_rows = session.run(
                """
                MATCH (fn:Function)
                RETURN
                    fn.id as id,
                    fn.name as name,
                    fn.file_path as file_path,
                    fn.symbol_key as symbol_key,
                    fn.qualified_name as qualified_name
                """
            ).data()
            class_rows = session.run(
                """
                MATCH (c:Class)
                RETURN
                    c.id as id,
                    c.name as name,
                    c.file_path as file_path,
                    c.symbol_key as symbol_key,
                    c.qualified_name as qualified_name
                """
            ).data()
            file_rows = session.run(
                "MATCH (f:File) RETURN f.path as path"
            ).data()

        function_maps, class_maps, file_map = self._build_symbol_maps_from_db_rows(
            function_rows,
            class_rows,
            file_rows,
        )

        for file_info in file_infos:
            caller_module = self._module_name(file_info.relative_path)

            for record in self._iter_function_records(file_info):
                caller_id = str(record["id"])
                caller_class = record["class_name"]
                for called_name in list(record.get("calls") or []):
                    resolved, ambiguity = self._resolve_function_candidates(
                        called_name,
                        caller_module=caller_module,
                        caller_class=caller_class,
                        function_maps=function_maps,
                    )
                    warning_count += ambiguity
                    for callee_id, method, confidence in resolved:
                        if callee_id == caller_id:
                            continue
                        rel_key = (caller_id, callee_id)
                        previous = calls_map.get(rel_key)
                        if previous is None or confidence >= previous[1]:
                            calls_map[rel_key] = (method, confidence)

            for imported_module in file_info.imports:
                target_path = file_map.get(imported_module)
                if not target_path:
                    for part in reversed(imported_module.split(".")):
                        if part in file_map:
                            target_path = file_map[part]
                            break
                if target_path and target_path != file_info.relative_path:
                    imports_set.add((file_info.relative_path, target_path))

            child_module = self._module_name(file_info.relative_path)
            for cls in file_info.classes:
                child_id = f"{file_info.relative_path}::{cls.name}:{cls.start_line}"
                for base_name in cls.bases:
                    resolved, ambiguity = self._resolve_class_candidates(
                        base_name,
                        child_module=child_module,
                        class_maps=class_maps,
                    )
                    warning_count += ambiguity
                    for parent_id, method, confidence in resolved:
                        if parent_id == child_id:
                            continue
                        rel_key = (child_id, parent_id)
                        previous = inherits_map.get(rel_key)
                        if previous is None or confidence >= previous[1]:
                            inherits_map[rel_key] = (method, confidence)

        calls_rows = [
            {
                "caller_id": caller_id,
                "callee_id": callee_id,
                "resolution_method": method,
                "resolution_confidence": confidence,
            }
            for (caller_id, callee_id), (method, confidence) in calls_map.items()
        ]
        imports_rows = [
            {"from_file": from_file, "to_file": to_file}
            for (from_file, to_file) in imports_set
        ]
        inherits_rows = [
            {
                "child_class_id": child_id,
                "parent_class_id": parent_id,
                "resolution_method": method,
                "resolution_confidence": confidence,
            }
            for (child_id, parent_id), (method, confidence) in inherits_map.items()
        ]

        rel_count = 0
        rel_count += self.db.create_calls_relationships_batch(calls_rows)
        rel_count += self.db.create_imports_relationships_batch(imports_rows)
        rel_count += self.db.create_inherits_relationships_batch(inherits_rows)
        return rel_count, warning_count

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

    def _create_relationships(self, file_infos: List[FileInfo]) -> Tuple[int, int]:
        """Create relationships between nodes (second pass)."""
        warning_count = 0
        calls_map: Dict[Tuple[str, str], Tuple[str, float]] = {}
        imports_set: Set[Tuple[str, str]] = set()
        inherits_map: Dict[Tuple[str, str], Tuple[str, float]] = {}

        function_maps, class_maps, file_map = self._build_symbol_maps_from_file_infos(file_infos)

        for file_info in file_infos:
            caller_module = self._module_name(file_info.relative_path)

            for record in self._iter_function_records(file_info):
                caller_id = str(record["id"])
                caller_class = record["class_name"]
                for called_name in list(record.get("calls") or []):
                    resolved, ambiguity = self._resolve_function_candidates(
                        called_name,
                        caller_module=caller_module,
                        caller_class=caller_class,
                        function_maps=function_maps,
                    )
                    warning_count += ambiguity
                    for callee_id, method, confidence in resolved:
                        if callee_id == caller_id:
                            continue
                        rel_key = (caller_id, callee_id)
                        previous = calls_map.get(rel_key)
                        if previous is None or confidence >= previous[1]:
                            calls_map[rel_key] = (method, confidence)

            for imported_module in file_info.imports:
                target_path = file_map.get(imported_module)
                if not target_path:
                    for part in reversed(imported_module.split(".")):
                        if part in file_map:
                            target_path = file_map[part]
                            break
                if target_path and target_path != file_info.relative_path:
                    imports_set.add((file_info.relative_path, target_path))

            child_module = self._module_name(file_info.relative_path)
            for cls in file_info.classes:
                child_id = f"{file_info.relative_path}::{cls.name}:{cls.start_line}"
                for base_name in cls.bases:
                    resolved, ambiguity = self._resolve_class_candidates(
                        base_name,
                        child_module=child_module,
                        class_maps=class_maps,
                    )
                    warning_count += ambiguity
                    for parent_id, method, confidence in resolved:
                        if parent_id == child_id:
                            continue
                        rel_key = (child_id, parent_id)
                        previous = inherits_map.get(rel_key)
                        if previous is None or confidence >= previous[1]:
                            inherits_map[rel_key] = (method, confidence)

        # TESTS relationships are created by TestLinker after graph build.
        calls_rows = [
            {
                "caller_id": caller_id,
                "callee_id": callee_id,
                "resolution_method": method,
                "resolution_confidence": confidence,
            }
            for (caller_id, callee_id), (method, confidence) in calls_map.items()
        ]
        imports_rows = [
            {"from_file": from_file, "to_file": to_file}
            for (from_file, to_file) in imports_set
        ]
        inherits_rows = [
            {
                "child_class_id": child_id,
                "parent_class_id": parent_id,
                "resolution_method": method,
                "resolution_confidence": confidence,
            }
            for (child_id, parent_id), (method, confidence) in inherits_map.items()
        ]

        rel_count = 0
        rel_count += self.db.create_calls_relationships_batch(calls_rows)
        rel_count += self.db.create_imports_relationships_batch(imports_rows)
        rel_count += self.db.create_inherits_relationships_batch(inherits_rows)
        return rel_count, warning_count

    def _get_changed_files(self, repo_path: Path, base_commit: str) -> List[str]:
        """Get list of changed files using git diff plus untracked files."""
        try:
            repo = git.Repo(repo_path)
            diff = repo.git.diff('--name-only', base_commit)
            changed_files = [line.strip() for line in diff.splitlines() if line.strip()]
            untracked_files = [path for path in repo.untracked_files if path]
            merged: List[str] = []
            seen: Set[str] = set()
            for path in changed_files + untracked_files:
                if path not in seen:
                    seen.add(path)
                    merged.append(path)
            return [f for f in merged if f.endswith('.py')]
        except Exception as e:
            logger.error(f"Error getting changed files from git: {e}")
            return []
