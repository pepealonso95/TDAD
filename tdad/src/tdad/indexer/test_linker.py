"""Test linker: creates TESTS edges between Test nodes and source symbols.

Three strategies with confidence scoring:
1. Naming conventions (confidence ~0.7)
2. Static analysis — imports + calls (confidence ~0.8)
3. Coverage data — opt-in (confidence ~0.9)

All heavy matching is pre-resolved in Python to avoid cartesian
explosions in Neo4j. Edges are written in UNWIND batches with raw
sessions (no client-side timeout) so large repos like Django work.
"""

import logging
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set

from ..core.graph_db import GraphDB

logger = logging.getLogger(__name__)

BATCH = 500
MAX_IMPORT_EDGES = 100_000  # cap import-based links to keep graph queries fast


def _batched_write(db: GraphDB, query: str, rows: List[dict], label: str = "") -> None:
    """Write rows in batches using raw sessions (no client timeout)."""
    for i in range(0, len(rows), BATCH):
        chunk = rows[i : i + BATCH]
        with db.session() as session:
            session.run(query, rows=chunk).consume()
        if label:
            logger.debug(
                "Wrote %s batch %d-%d / %d", label, i, i + len(chunk), len(rows)
            )


def _fetch_all(db: GraphDB, query: str, **params: Any) -> List[dict]:
    """Fetch all records using a raw session (no client timeout)."""
    with db.session() as session:
        result = session.run(query, **params)
        return [dict(r) for r in result]


def link_tests(repo_path: Path, db: GraphDB) -> Dict:
    """Run all linking strategies and return statistics."""
    stats: Dict[str, int] = {}

    stats["naming"] = _link_by_naming(db)
    stats["static"] = _link_by_static_analysis(db)

    if db.settings.use_coverage:
        try:
            stats["coverage"] = _link_by_coverage(repo_path, db)
        except Exception as exc:
            logger.warning("Coverage linking failed: %s", exc)
            stats["coverage"] = 0
    else:
        stats["coverage"] = 0

    stats["total"] = stats["naming"] + stats["static"] + stats["coverage"]
    logger.info(
        "Test linking complete: %d total (%d naming, %d static, %d coverage)",
        stats["total"],
        stats["naming"],
        stats["static"],
        stats["coverage"],
    )
    return stats


# ------------------------------------------------------------------
# Strategy 1: Naming conventions (pre-resolved in Python)
# ------------------------------------------------------------------


def _link_by_naming(db: GraphDB) -> int:
    """Link test_foo -> foo, TestFoo methods -> Foo methods.

    All matching done in Python to avoid cartesian explosions in Neo4j.
    """
    tests = _fetch_all(
        db,
        "MATCH (t:Test) RETURN t.id AS id, t.name AS name, t.file_path AS file_path",
    )
    functions = _fetch_all(
        db,
        "MATCH (fn:Function) WHERE NOT fn:Test "
        "RETURN fn.id AS id, fn.name AS name, fn.file_path AS file_path, "
        "fn.qualified_name AS qualified_name",
    )
    classes = _fetch_all(
        db, "MATCH (c:Class) RETURN c.id AS id, c.name AS name"
    )

    logger.info(
        "Naming link data: %d tests, %d functions, %d classes",
        len(tests),
        len(functions),
        len(classes),
    )

    # Build lookups
    fn_by_name: Dict[str, List[tuple]] = defaultdict(list)
    fn_by_qname_suffix: Dict[str, List[tuple]] = defaultdict(list)
    for fn in functions:
        fn_by_name[fn["name"]].append((fn["id"], fn["file_path"]))
        qn = fn.get("qualified_name") or ""
        if "." in qn:
            suffix = qn.rsplit(".", 1)[-1]
            if suffix != fn["name"]:
                fn_by_qname_suffix[suffix].append((fn["id"], fn["file_path"]))

    class_by_name: Dict[str, List[str]] = defaultdict(list)
    for cls in classes:
        class_by_name[cls["name"]].append(cls["id"])

    edges: List[dict] = []
    seen: Set[tuple] = set()
    fn_links = qual_links = class_links = 0

    for t in tests:
        tname = t["name"]
        tfp = t["file_path"]
        tid = t["id"]

        # 1a: test_X -> function named X (different file)
        if tname.startswith("test_"):
            target = tname[5:]
            for fn_id, fn_fp in fn_by_name.get(target, []):
                if fn_fp != tfp and (tid, fn_id) not in seen:
                    seen.add((tid, fn_id))
                    edges.append(
                        {
                            "test_id": tid,
                            "target_id": fn_id,
                            "source": "naming",
                            "confidence": 0.7,
                        }
                    )
                    fn_links += 1

            # 1b: test_X -> function with qualified_name ending in .X
            for fn_id, fn_fp in fn_by_qname_suffix.get(target, []):
                if fn_fp != tfp and (tid, fn_id) not in seen:
                    seen.add((tid, fn_id))
                    edges.append(
                        {
                            "test_id": tid,
                            "target_id": fn_id,
                            "source": "naming",
                            "confidence": 0.65,
                        }
                    )
                    qual_links += 1

        # 1c: TestFoo.test_bar -> Class Foo
        if "." in tname:
            class_part = tname.split(".")[0]
            if class_part.startswith("Test") and len(class_part) > 4:
                target_class = class_part[4:]
                for cls_id in class_by_name.get(target_class, []):
                    if (tid, cls_id) not in seen:
                        seen.add((tid, cls_id))
                        edges.append(
                            {
                                "test_id": tid,
                                "target_id": cls_id,
                                "source": "naming",
                                "confidence": 0.7,
                            }
                        )
                        class_links += 1

    if edges:
        _batched_write(
            db,
            """
            UNWIND $rows AS r
            MATCH (t:Test {id: r.test_id})
            MATCH (target {id: r.target_id})
            MERGE (t)-[rel:TESTS]->(target)
            SET rel.link_source = r.source, rel.link_confidence = r.confidence
            """,
            edges,
            "naming-tests",
        )

    logger.info(
        "Naming links: %d (fn=%d, qual=%d, class=%d)",
        len(edges),
        fn_links,
        qual_links,
        class_links,
    )
    return len(edges)


# ------------------------------------------------------------------
# Strategy 2: Static analysis (pre-resolved in Python)
# ------------------------------------------------------------------


def _link_by_static_analysis(db: GraphDB) -> int:
    """Link tests to functions they call or whose modules they import.

    All matching done in Python to avoid cartesian explosions in Neo4j.
    """
    # --- Call-based linking (confidence 0.8) ---
    # Use existing CALLS edges: test -> Function -> CALLS -> callee
    tests = _fetch_all(
        db,
        "MATCH (t:Test) RETURN t.id AS id, t.file_path AS file_path",
    )

    # Map test_id -> corresponding Function id (strip "test::" prefix)
    test_fn_ids = set()
    test_id_by_fn = {}
    for t in tests:
        fn_id = t["id"].replace("test::", "", 1)
        test_fn_ids.add(fn_id)
        test_id_by_fn[fn_id] = t["id"]

    # Fetch all CALLS edges and filter to those from test functions
    all_calls = _fetch_all(
        db,
        "MATCH (caller:Function)-[:CALLS]->(callee:Function) "
        "WHERE NOT callee:Test "
        "RETURN caller.id AS caller_id, callee.id AS callee_id",
    )

    # Fetch existing TESTS edges to avoid duplicates
    existing: Set[tuple] = set()
    for e in _fetch_all(
        db, "MATCH (t:Test)-[:TESTS]->(n) RETURN t.id AS tid, n.id AS nid"
    ):
        existing.add((e["tid"], e["nid"]))

    call_edges: List[dict] = []
    for c in all_calls:
        if c["caller_id"] in test_fn_ids:
            tid = test_id_by_fn[c["caller_id"]]
            key = (tid, c["callee_id"])
            if key not in existing:
                existing.add(key)
                call_edges.append(
                    {
                        "test_id": tid,
                        "target_id": c["callee_id"],
                        "source": "static",
                        "confidence": 0.8,
                    }
                )

    if call_edges:
        _batched_write(
            db,
            """
            UNWIND $rows AS r
            MATCH (t:Test {id: r.test_id})
            MATCH (fn:Function {id: r.target_id})
            MERGE (t)-[rel:TESTS]->(fn)
            SET rel.link_source = r.source, rel.link_confidence = r.confidence
            """,
            call_edges,
            "static-call-tests",
        )

    # --- Import-based linking (confidence 0.5) ---
    # Tests in files that import source files -> link to functions in those files
    imports = _fetch_all(
        db,
        "MATCH (tf:File)-[:IMPORTS]->(sf:File) "
        "RETURN tf.path AS test_file, sf.path AS src_file",
    )

    test_by_file: Dict[str, List[str]] = defaultdict(list)
    for t in tests:
        test_by_file[t["file_path"]].append(t["id"])

    fn_by_file: Dict[str, List[str]] = defaultdict(list)
    fns = _fetch_all(
        db,
        "MATCH (fn:Function) WHERE NOT fn:Test "
        "RETURN fn.id AS id, fn.file_path AS file_path",
    )
    for fn in fns:
        fn_by_file[fn["file_path"]].append(fn["id"])

    import_edges: List[dict] = []
    capped = False
    for imp in imports:
        t_ids = test_by_file.get(imp["test_file"], [])
        f_ids = fn_by_file.get(imp["src_file"], [])
        if not t_ids or not f_ids:
            continue
        for tid in t_ids:
            for fid in f_ids:
                key = (tid, fid)
                if key not in existing:
                    existing.add(key)
                    import_edges.append(
                        {
                            "test_id": tid,
                            "target_id": fid,
                            "source": "static_import",
                            "confidence": 0.5,
                        }
                    )
                    if len(import_edges) >= MAX_IMPORT_EDGES:
                        capped = True
                        break
            if capped:
                break
        if capped:
            logger.warning(
                "Import-based linking capped at %d edges (would exceed limit)",
                MAX_IMPORT_EDGES,
            )
            break

    if import_edges:
        _batched_write(
            db,
            """
            UNWIND $rows AS r
            MATCH (t:Test {id: r.test_id})
            MATCH (fn:Function {id: r.target_id})
            MERGE (t)-[rel:TESTS]->(fn)
            SET rel.link_source = r.source, rel.link_confidence = r.confidence
            """,
            import_edges,
            "static-import-tests",
        )

    total = len(call_edges) + len(import_edges)
    logger.info(
        "Static links: %d (call=%d, import=%d)", total, len(call_edges), len(import_edges)
    )
    return total


# ------------------------------------------------------------------
# Strategy 3: Coverage (opt-in)
# ------------------------------------------------------------------


def _link_by_coverage(repo_path: Path, db: GraphDB) -> int:
    """Run pytest --cov, parse results, create TESTS edges."""
    try:
        from coverage import CoverageData
    except ImportError:
        logger.warning("coverage package not installed; skipping coverage linking")
        return 0

    cov_file = repo_path / ".coverage"
    if not cov_file.exists():
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "--cov",
                str(repo_path),
                "-q",
                "--no-header",
            ],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            logger.warning("pytest --cov failed: %s", result.stderr[:500])

    if not cov_file.exists():
        logger.warning("No .coverage file found after running pytest")
        return 0

    cov_data = CoverageData(basename=str(cov_file))
    cov_data.read()

    links = 0
    repo_root = repo_path.resolve()
    for measured_file in cov_data.measured_files():
        try:
            rel_path = str(Path(measured_file).resolve().relative_to(repo_root))
        except ValueError:
            continue

        executed_lines = cov_data.lines(measured_file)
        if not executed_lines:
            continue

        # Find functions that overlap with executed lines
        fn_ids = _fetch_all(
            db,
            "MATCH (fn:Function {file_path: $file_path}) "
            "WHERE fn.start_line <= $max_line AND fn.end_line >= $min_line "
            "RETURN fn.id AS fn_id",
            file_path=rel_path,
            min_line=min(executed_lines),
            max_line=max(executed_lines),
        )
        fn_id_list = [r["fn_id"] for r in fn_ids]
        if not fn_id_list:
            continue

        # Fetch tests and create edges
        test_ids = _fetch_all(db, "MATCH (t:Test) RETURN t.id AS id")
        edges = []
        for t in test_ids:
            for fid in fn_id_list:
                edges.append(
                    {
                        "test_id": t["id"],
                        "target_id": fid,
                        "source": "coverage",
                        "confidence": 0.9,
                    }
                )

        if edges:
            _batched_write(
                db,
                """
                UNWIND $rows AS r
                MATCH (t:Test {id: r.test_id})
                MATCH (fn:Function {id: r.target_id})
                WHERE NOT exists { (t)-[:TESTS]->(fn) }
                MERGE (t)-[rel:TESTS]->(fn)
                SET rel.link_source = r.source, rel.link_confidence = r.confidence
                """,
                edges,
                "coverage-tests",
            )
            links += len(edges)

    logger.info("Coverage links: %d", links)
    return links
