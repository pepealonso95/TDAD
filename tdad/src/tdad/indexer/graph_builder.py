"""Graph builder: walks a repo, parses Python files, persists to Neo4j."""

import hashlib
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

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


def _hash_file(path: Path) -> str:
    """Compute MD5 content hash without reading entire file into memory."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------
# Incremental diff
# ------------------------------------------------------------------

def _get_indexed_hashes(db: GraphDB) -> Dict[str, str]:
    """Query Neo4j for all File nodes and their content_hash."""
    with db.session() as session:
        result = db.run_query(session, """
            MATCH (f:File)
            RETURN f.path AS path, f.content_hash AS hash
        """)
        return {r["path"]: r["hash"] for r in result}


def _compute_diff(
    python_files: List[Path],
    repo_path: Path,
    indexed: Dict[str, str],
) -> Tuple[List[Path], List[Path], List[str]]:
    """Compare on-disk files against indexed hashes.

    Returns:
        (new_or_changed, unchanged, deleted_paths)
    """
    new_or_changed: List[Path] = []
    unchanged: List[Path] = []
    current_rel_paths: Set[str] = set()

    for p in python_files:
        try:
            rel = str(p.resolve().relative_to(repo_path.resolve()))
        except ValueError:
            rel = p.name
        current_rel_paths.add(rel)

        old_hash = indexed.get(rel)
        if old_hash is None:
            new_or_changed.append(p)
        else:
            current_hash = _hash_file(p)
            if current_hash != old_hash:
                new_or_changed.append(p)
            else:
                unchanged.append(p)

    deleted = [path for path in indexed if path not in current_rel_paths]
    return new_or_changed, unchanged, deleted


def _delete_file_subgraph(db: GraphDB, deleted_paths: List[str]) -> int:
    """Remove nodes and edges for deleted files."""
    if not deleted_paths:
        return 0
    with db.session() as session:
        # Delete all nodes that belong to these files, plus the file nodes themselves
        result = db.run_query(session, """
            UNWIND $paths AS p
            MATCH (f:File {path: p})-[:CONTAINS]->(n)
            DETACH DELETE n
            WITH count(*) AS child_count
            UNWIND $paths AS p
            MATCH (f:File {path: p})
            DETACH DELETE f
            RETURN child_count
        """, paths=deleted_paths)
    logger.info("Deleted subgraphs for %d removed files", len(deleted_paths))
    return len(deleted_paths)


def _delete_stale_nodes(db: GraphDB, changed_rel_paths: List[str]) -> None:
    """Remove old child nodes for files that will be re-indexed."""
    if not changed_rel_paths:
        return
    with db.session() as session:
        db.run_query(session, """
            UNWIND $paths AS p
            MATCH (f:File {path: p})-[:CONTAINS]->(n)
            DETACH DELETE n
        """, paths=changed_rel_paths)


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def build_graph(repo_path: Path, db: GraphDB, force: bool = False) -> Dict[str, Any]:
    """Index a repository into the Neo4j graph.

    Incremental by default: only re-parses new/changed files and removes
    deleted ones. Use force=True for a full rebuild.

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
        return {"files": 0, "functions": 0, "classes": 0, "tests": 0, "edges": 0,
                "incremental": False, "changed": 0, "unchanged": 0, "deleted": 0}

    # Incremental diff (skip when force or empty graph)
    if not force:
        indexed = _get_indexed_hashes(db)
    else:
        indexed = {}

    if indexed:
        to_parse, unchanged, deleted = _compute_diff(python_files, repo_path, indexed)
        _delete_file_subgraph(db, deleted)

        if not to_parse and not deleted:
            logger.info("Graph is up-to-date, nothing to index")
            return {"files": len(unchanged), "functions": 0, "classes": 0, "tests": 0,
                    "edges": 0, "incremental": True, "changed": 0,
                    "unchanged": len(unchanged), "deleted": 0}

        # Remove stale child nodes for changed files before re-inserting
        changed_rel = []
        for p in to_parse:
            try:
                changed_rel.append(str(p.resolve().relative_to(repo_path.resolve())))
            except ValueError:
                pass
        _delete_stale_nodes(db, changed_rel)

        logger.info(
            "Incremental index: %d changed/new, %d unchanged, %d deleted",
            len(to_parse), len(unchanged), len(deleted),
        )
    else:
        to_parse = python_files
        unchanged = []
        deleted = []

    # Parse files (parallel when > 1 worker)
    workers = min(db.settings.index_workers, len(to_parse))
    file_infos = _parse_files(to_parse, repo_path, workers)

    # Persist nodes and edges
    stats = _persist_to_graph(file_infos, repo_path, db)
    stats["incremental"] = bool(indexed)
    stats["changed"] = len(to_parse)
    stats["unchanged"] = len(unchanged)
    stats["deleted"] = len(deleted)

    logger.info(
        "Indexed %d files (%d changed, %d unchanged, %d deleted): "
        "%d functions, %d classes, %d tests, %d edges",
        stats["files"], stats["changed"], stats["unchanged"], stats["deleted"],
        stats["functions"], stats["classes"], stats["tests"], stats["edges"],
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
    BATCH = 500  # rows per transaction to avoid timeouts on large repos

    def _batched_write(db, query, rows, label=""):
        for i in range(0, len(rows), BATCH):
            chunk = rows[i:i + BATCH]
            with db.session() as session:
                # Use raw query (no client timeout) for indexing batches
                session.run(query, rows=chunk).consume()
            if label:
                logger.debug("Wrote %s batch %d-%d / %d", label, i, i + len(chunk), len(rows))

    # Nodes
    if files_data:
        _batched_write(db, """
            UNWIND $rows AS r
            MERGE (f:File {path: r.path})
            SET f.name = r.name, f.content_hash = r.content_hash,
                f.repo_path = r.repo_path, f.updated_at = datetime()
        """, files_data, "files")

    if functions_data:
        _batched_write(db, """
            UNWIND $rows AS r
            MERGE (fn:Function {id: r.id})
            SET fn.name = r.name, fn.file_path = r.file_path,
                fn.start_line = r.start_line, fn.end_line = r.end_line,
                fn.signature = r.signature, fn.docstring = r.docstring,
                fn.qualified_name = r.qualified_name, fn.updated_at = datetime()
        """, functions_data, "functions")

    if classes_data:
        _batched_write(db, """
            UNWIND $rows AS r
            MERGE (c:Class {id: r.id})
            SET c.name = r.name, c.file_path = r.file_path,
                c.start_line = r.start_line, c.end_line = r.end_line,
                c.docstring = r.docstring, c.qualified_name = r.qualified_name,
                c.updated_at = datetime()
        """, classes_data, "classes")

    if tests_data:
        _batched_write(db, """
            UNWIND $rows AS r
            MERGE (t:Test {id: r.id})
            SET t.name = r.name, t.file_path = r.file_path, t.updated_at = datetime()
        """, tests_data, "tests")

    # Edges: CONTAINS
    if contains_data:
        _batched_write(db, """
            UNWIND $rows AS r
            MATCH (f:File {path: r.file_path})
            MATCH (n {id: r.node_id})
            MERGE (f)-[:CONTAINS]->(n)
        """, contains_data, "contains")

    # Edges: CALLS — pre-resolve in Python to avoid expensive cartesian in Neo4j
    MAX_CALLEE_MATCHES = 10  # skip overly-generic names like __init__, get, etc.
    if calls_data:
        # Build lookup: function name -> list of (function_id, file_path)
        from collections import defaultdict
        name_to_ids = defaultdict(list)
        for fd in functions_data:
            name_to_ids[fd["name"]].append((fd["id"], fd["file_path"]))
            qn = fd.get("qualified_name", "")
            if "." in qn:
                short = qn.rsplit(".", 1)[-1]
                if short != fd["name"]:
                    name_to_ids[short].append((fd["id"], fd["file_path"]))

        resolved_calls = []
        for cd in calls_data:
            candidates = name_to_ids.get(cd["callee_name"], [])
            if len(candidates) > MAX_CALLEE_MATCHES:
                # Too ambiguous — prefer same-file matches only
                caller_file = cd["caller_id"].split("::")[0]
                candidates = [(cid, fp) for cid, fp in candidates if fp == caller_file]
            for cid, _ in candidates:
                resolved_calls.append({"caller_id": cd["caller_id"], "callee_id": cid})

        logger.info("Resolved %d call edges from %d raw calls", len(resolved_calls), len(calls_data))
        CALLS_BATCH = 200
        for i in range(0, len(resolved_calls), CALLS_BATCH):
            chunk = resolved_calls[i:i + CALLS_BATCH]
            with db.session() as session:
                session.run("""
                    UNWIND $rows AS r
                    MATCH (caller:Function {id: r.caller_id})
                    MATCH (callee:Function {id: r.callee_id})
                    MERGE (caller)-[:CALLS]->(callee)
                """, rows=chunk).consume()
            logger.debug("Wrote calls batch %d-%d / %d", i, i + len(chunk), len(resolved_calls))

    # Edges: IMPORTS — pre-resolve in Python to avoid ENDS WITH scan
    if imports_data:
        # Build lookup: module suffix -> file path
        file_module_map = {}
        for fd in files_data:
            mod = fd["path"].replace("/", ".").replace(".py", "").strip(".")
            file_module_map[mod] = fd["path"]

        resolved_imports = []
        for imp in imports_data:
            target_module = imp["imported_module"]
            for mod, fpath in file_module_map.items():
                if mod == target_module or mod.endswith("." + target_module):
                    resolved_imports.append({"importer": imp["importer"], "imported": fpath})

        logger.info("Resolved %d import edges from %d raw imports", len(resolved_imports), len(imports_data))
        if resolved_imports:
            _batched_write(db, """
                UNWIND $rows AS r
                MATCH (importer:File {path: r.importer})
                MATCH (imported:File {path: r.imported})
                MERGE (importer)-[:IMPORTS]->(imported)
            """, resolved_imports, "imports")

    # Edges: INHERITS (class → class by name)
    if inherits_data:
        _batched_write(db, """
            UNWIND $rows AS r
            MATCH (child:Class {id: r.class_id})
            MATCH (parent:Class)
            WHERE parent.name = r.base_name
            MERGE (child)-[:INHERITS]->(parent)
        """, inherits_data, "inherits")

    edges = len(contains_data) + len(calls_data) + len(imports_data) + len(inherits_data)
    return {
        "files": len(files_data),
        "functions": len(functions_data),
        "classes": len(classes_data),
        "tests": len(tests_data),
        "edges": edges,
    }
