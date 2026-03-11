"""Graph builder: walks a repo, parses Python files, persists to Neo4j."""

import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List

from ..core.graph_db import GraphDB
from .ast_parser import FileInfo, parse_file

logger = logging.getLogger(__name__)

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".tox", ".eggs", "dist", "build"}


def _collect_python_files(repo_path: Path) -> List[Path]:
    """Walk repo for .py files, skipping common non-source directories."""
    files = []
    for p in repo_path.rglob("*.py"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        files.append(p)
    return sorted(files)


def _parse_file_worker(file_path_str: str, repo_root_str: str) -> FileInfo:
    """Standalone worker function for ProcessPoolExecutor."""
    return parse_file(Path(file_path_str), Path(repo_root_str))


def _module_name(relative_path: str) -> str:
    """Convert repo-relative path to dotted module name."""
    normalized = relative_path.replace("\\", "/")
    if normalized.endswith(".py"):
        normalized = normalized[:-3]
    return normalized.replace("/", ".").strip(".")


def build_graph(repo_path: Path, db: GraphDB, force: bool = False) -> Dict[str, Any]:
    """Index a repository into the Neo4j graph.

    Returns statistics dict with node/edge counts.
    """
    repo_path = repo_path.resolve()
    if not repo_path.is_dir():
        raise ValueError(f"Not a directory: {repo_path}")

    if force:
        db.clear_database()

    db.ensure_schema()

    python_files = _collect_python_files(repo_path)
    if not python_files:
        return {"files": 0, "functions": 0, "classes": 0, "tests": 0, "edges": 0}

    # Parse files (parallel when > 1 worker)
    workers = min(db.settings.index_workers, len(python_files))
    file_infos = _parse_files(python_files, repo_path, workers)

    # Persist nodes and edges
    stats = _persist_to_graph(file_infos, repo_path, db)
    logger.info(
        "Indexed %d files: %d functions, %d classes, %d tests, %d edges",
        stats["files"], stats["functions"], stats["classes"],
        stats["tests"], stats["edges"],
    )
    return stats


def _parse_files(python_files: List[Path], repo_path: Path, workers: int) -> List[FileInfo]:
    if workers <= 1:
        results = []
        for f in python_files:
            try:
                results.append(parse_file(f, repo_path))
            except Exception as exc:
                logger.error("Error parsing %s: %s", f, exc)
        return results

    results = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_parse_file_worker, str(f), str(repo_path)): f
            for f in python_files
        }
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                logger.error("Error parsing %s: %s", futures[future], exc)
    return results


def _persist_to_graph(file_infos: List[FileInfo], repo_path: Path, db: GraphDB) -> Dict[str, int]:
    """Persist parsed file info to Neo4j using UNWIND batches."""
    files_data = []
    functions_data = []
    classes_data = []
    tests_data = []
    contains_data = []
    calls_data = []
    imports_data = []
    inherits_data = []

    for fi in file_infos:
        mod = _module_name(fi.relative_path)
        files_data.append({
            "path": fi.relative_path,
            "name": fi.name,
            "content_hash": fi.content_hash,
            "repo_path": str(repo_path),
        })

        for func in fi.functions:
            func_id = f"{fi.relative_path}::{func.name}:{func.start_line}"
            functions_data.append({
                "id": func_id,
                "name": func.name,
                "file_path": fi.relative_path,
                "start_line": func.start_line,
                "end_line": func.end_line,
                "signature": func.signature,
                "docstring": func.docstring,
                "qualified_name": f"{mod}.{func.name}",
            })
            contains_data.append({"file_path": fi.relative_path, "node_id": func_id, "node_type": "Function"})

            if func.is_test:
                test_id = f"test::{func_id}"
                tests_data.append({
                    "id": test_id,
                    "name": func.name,
                    "file_path": fi.relative_path,
                })
                contains_data.append({"file_path": fi.relative_path, "node_id": test_id, "node_type": "Test"})

            for call in func.calls:
                calls_data.append({"caller_id": func_id, "callee_name": call})

        for cls in fi.classes:
            class_id = f"{fi.relative_path}::{cls.name}:{cls.start_line}"
            classes_data.append({
                "id": class_id,
                "name": cls.name,
                "file_path": fi.relative_path,
                "start_line": cls.start_line,
                "end_line": cls.end_line,
                "docstring": cls.docstring,
                "qualified_name": f"{mod}.{cls.name}",
            })
            contains_data.append({"file_path": fi.relative_path, "node_id": class_id, "node_type": "Class"})

            for base in cls.bases:
                inherits_data.append({"class_id": class_id, "base_name": base})

            for method in cls.methods:
                method_id = f"{fi.relative_path}::{cls.name}.{method.name}:{method.start_line}"
                functions_data.append({
                    "id": method_id,
                    "name": f"{cls.name}.{method.name}",
                    "file_path": fi.relative_path,
                    "start_line": method.start_line,
                    "end_line": method.end_line,
                    "signature": method.signature,
                    "docstring": method.docstring,
                    "qualified_name": f"{mod}.{cls.name}.{method.name}",
                })
                contains_data.append({"file_path": fi.relative_path, "node_id": method_id, "node_type": "Function"})

                if method.is_test:
                    test_id = f"test::{method_id}"
                    tests_data.append({
                        "id": test_id,
                        "name": f"{cls.name}.{method.name}",
                        "file_path": fi.relative_path,
                    })
                    contains_data.append({"file_path": fi.relative_path, "node_id": test_id, "node_type": "Test"})

                for call in method.calls:
                    calls_data.append({"caller_id": method_id, "callee_name": call})

        # File-level import edges
        for imp in fi.imports:
            imports_data.append({"importer": fi.relative_path, "imported_module": imp})

    # -- Write to Neo4j with UNWIND batches --
    with db.session() as session:
        # Nodes
        if files_data:
            db.run_query(session, """
                UNWIND $rows AS r
                MERGE (f:File {path: r.path})
                SET f.name = r.name, f.content_hash = r.content_hash,
                    f.repo_path = r.repo_path, f.updated_at = datetime()
            """, rows=files_data)

        if functions_data:
            db.run_query(session, """
                UNWIND $rows AS r
                MERGE (fn:Function {id: r.id})
                SET fn.name = r.name, fn.file_path = r.file_path,
                    fn.start_line = r.start_line, fn.end_line = r.end_line,
                    fn.signature = r.signature, fn.docstring = r.docstring,
                    fn.qualified_name = r.qualified_name, fn.updated_at = datetime()
            """, rows=functions_data)

        if classes_data:
            db.run_query(session, """
                UNWIND $rows AS r
                MERGE (c:Class {id: r.id})
                SET c.name = r.name, c.file_path = r.file_path,
                    c.start_line = r.start_line, c.end_line = r.end_line,
                    c.docstring = r.docstring, c.qualified_name = r.qualified_name,
                    c.updated_at = datetime()
            """, rows=classes_data)

        if tests_data:
            db.run_query(session, """
                UNWIND $rows AS r
                MERGE (t:Test {id: r.id})
                SET t.name = r.name, t.file_path = r.file_path, t.updated_at = datetime()
            """, rows=tests_data)

        # Edges: CONTAINS
        if contains_data:
            db.run_query(session, """
                UNWIND $rows AS r
                MATCH (f:File {path: r.file_path})
                MATCH (n {id: r.node_id})
                MERGE (f)-[:CONTAINS]->(n)
            """, rows=contains_data)

        # Edges: CALLS (resolve callee by name)
        if calls_data:
            db.run_query(session, """
                UNWIND $rows AS r
                MATCH (caller:Function {id: r.caller_id})
                MATCH (callee:Function)
                WHERE callee.name = r.callee_name OR callee.qualified_name ENDS WITH ('.' + r.callee_name)
                MERGE (caller)-[:CALLS]->(callee)
            """, rows=calls_data)

        # Edges: IMPORTS (file → file via module name)
        if imports_data:
            db.run_query(session, """
                UNWIND $rows AS r
                MATCH (importer:File {path: r.importer})
                MATCH (imported:File)
                WHERE replace(replace(imported.path, '/', '.'), '.py', '') ENDS WITH r.imported_module
                MERGE (importer)-[:IMPORTS]->(imported)
            """, rows=imports_data)

        # Edges: INHERITS (class → class by name)
        if inherits_data:
            db.run_query(session, """
                UNWIND $rows AS r
                MATCH (child:Class {id: r.class_id})
                MATCH (parent:Class)
                WHERE parent.name = r.base_name
                MERGE (child)-[:INHERITS]->(parent)
            """, rows=inherits_data)

    edges = len(contains_data) + len(calls_data) + len(imports_data) + len(inherits_data)
    return {
        "files": len(files_data),
        "functions": len(functions_data),
        "classes": len(classes_data),
        "tests": len(tests_data),
        "edges": edges,
    }
