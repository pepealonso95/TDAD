"""Test linker: creates TESTS edges between Test nodes and source symbols.

Three strategies with confidence scoring:
1. Naming conventions (confidence ~0.7)
2. Static analysis — imports + calls (confidence ~0.8)
3. Coverage data — opt-in (confidence ~0.9)
"""

import logging
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

logger = logging.getLogger(__name__)


def link_tests(repo_path: Path, db) -> Dict:
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
        stats["total"], stats["naming"], stats["static"], stats["coverage"],
    )
    return stats


# ------------------------------------------------------------------
# Strategy 1: Naming conventions
# ------------------------------------------------------------------

def _link_by_naming(db) -> int:
    """Link test_foo -> foo, TestFoo methods -> Foo methods."""
    if hasattr(db, "get_all_tests"):
        return _link_by_naming_nx(db)
    return _link_by_naming_neo4j(db)


def _link_by_naming_nx(db) -> int:
    """Naming strategy using NetworkX backend."""
    tests = db.get_all_tests()
    functions = db.get_all_functions()
    classes = db.get_all_classes()

    # Build indexes
    fn_by_name = {}
    fn_by_qsuffix = {}
    for fn in functions:
        fn_by_name.setdefault(fn["name"], []).append(fn)
        qn = fn.get("qualified_name", "")
        if qn:
            parts = qn.split(".")
            for i in range(1, len(parts)):
                suffix = ".".join(parts[i:])
                fn_by_qsuffix.setdefault(suffix, []).append(fn)

    cls_by_name = {}
    for c in classes:
        cls_by_name.setdefault(c["name"], []).append(c)

    fn_links = qual_links = class_links = 0

    for t in tests:
        tname = t["name"]
        tid = t["id"]
        tfile = t["file_path"]

        # test_X -> X (function-level)
        if tname.startswith("test_"):
            target = tname[5:]
            # Also handle TestClass.test_method -> strip class prefix
            if "." in target:
                target = target.split(".")[-1]
                if target.startswith("test_"):
                    target = target[5:]

            for fn in fn_by_name.get(target, []):
                if fn["file_path"] != tfile and not db.tests_edge_exists(tid, fn["id"]):
                    db.create_tests_edge(tid, fn["id"], "Function", "naming", 0.7)
                    fn_links += 1

            # test_X -> X via qualified name suffix
            for fn in fn_by_qsuffix.get(target, []):
                if fn["file_path"] != tfile and not db.tests_edge_exists(tid, fn["id"]):
                    db.create_tests_edge(tid, fn["id"], "Function", "naming", 0.65)
                    qual_links += 1

        # TestFoo.test_bar -> Foo class
        if "." in tname:
            class_part = tname.split(".")[0]
            if class_part.startswith("Test") and len(class_part) > 4:
                target_class = class_part[4:]
                for c in cls_by_name.get(target_class, []):
                    if not db.tests_edge_exists(tid, c["id"]):
                        db.create_tests_edge(tid, c["id"], "Class", "naming", 0.7)
                        class_links += 1

    total = fn_links + qual_links + class_links
    logger.info("Naming links: %d (fn=%d, qual=%d, class=%d)", total, fn_links, qual_links, class_links)
    return total


def _link_by_naming_neo4j(db) -> int:
    """Naming strategy using Neo4j Cypher."""
    with db.session() as session:
        result = db.run_query(session, """
            MATCH (t:Test)
            WHERE t.name STARTS WITH 'test_'
            WITH t, substring(t.name, 5) AS target_name
            MATCH (fn:Function)
            WHERE fn.name = target_name
              AND NOT fn.file_path = t.file_path
            MERGE (t)-[r:TESTS]->(fn)
            SET r.link_source = 'naming', r.link_confidence = 0.7
            RETURN count(r) AS cnt
        """)
        fn_links = result.single()["cnt"]

        result = db.run_query(session, """
            MATCH (t:Test)
            WHERE t.name STARTS WITH 'test_'
            WITH t, substring(t.name, 5) AS target_name
            MATCH (fn:Function)
            WHERE fn.qualified_name ENDS WITH ('.' + target_name)
              AND NOT fn.file_path = t.file_path
              AND NOT exists { (t)-[:TESTS]->(fn) }
            MERGE (t)-[r:TESTS]->(fn)
            SET r.link_source = 'naming', r.link_confidence = 0.65
            RETURN count(r) AS cnt
        """)
        qual_links = result.single()["cnt"]

        result = db.run_query(session, """
            MATCH (t:Test)
            WHERE t.name CONTAINS '.'
            WITH t, split(t.name, '.')[0] AS class_part
            WHERE class_part STARTS WITH 'Test'
            WITH t, substring(class_part, 4) AS target_class
            MATCH (c:Class)
            WHERE c.name = target_class
            MERGE (t)-[r:TESTS]->(c)
            SET r.link_source = 'naming', r.link_confidence = 0.7
            RETURN count(r) AS cnt
        """)
        class_links = result.single()["cnt"]

    total = fn_links + qual_links + class_links
    logger.info("Naming links: %d (fn=%d, qual=%d, class=%d)", total, fn_links, qual_links, class_links)
    return total


# ------------------------------------------------------------------
# Strategy 2: Static analysis (imports + calls)
# ------------------------------------------------------------------

def _link_by_static_analysis(db) -> int:
    """Link tests to functions they call or whose modules they import."""
    if hasattr(db, "get_all_tests"):
        return _link_by_static_nx(db)
    return _link_by_static_neo4j(db)


def _link_by_static_nx(db) -> int:
    """Static analysis linking using NetworkX backend."""
    tests = db.get_all_tests()
    functions = db.get_all_functions()
    imports = db.get_file_imports()

    # Build indexes
    fn_by_file: Dict[str, List[Dict]] = {}
    fn_by_id: Dict[str, Dict] = {}
    test_fn_by_id: Dict[str, Dict] = {}

    for fn in functions:
        fn_by_file.setdefault(fn["file_path"], []).append(fn)
        fn_by_id[fn["id"]] = fn

    # Build import map: importer_path -> set of imported_paths
    import_map: Dict[str, Set[str]] = {}
    for imp in imports:
        import_map.setdefault(imp["importer"], set()).add(imp["imported"])

    # Map test_id -> function_id (strip 'test::' prefix)
    for t in tests:
        underlying_fn_id = t["id"].replace("test::", "", 1)
        fn = fn_by_id.get(underlying_fn_id)
        if fn:
            test_fn_by_id[t["id"]] = fn

    call_links = 0
    import_links = 0

    for t in tests:
        tid = t["id"]
        tfile = t["file_path"]

        # What files does the test file import?
        imported_files = import_map.get(tfile, set())
        if not imported_files:
            continue

        # Functions in imported files (non-test)
        target_fns = []
        for imp_file in imported_files:
            for fn in fn_by_file.get(imp_file, []):
                target_fns.append(fn)

        # Strategy 1: test's underlying function calls target function
        t_fn = test_fn_by_id.get(tid)
        if t_fn:
            t_calls = set(t_fn.get("calls", []))
            for fn in target_fns:
                if fn["name"] in t_calls or fn.get("qualified_name", "").endswith("." + fn["name"]):
                    if not db.tests_edge_exists(tid, fn["id"]):
                        db.create_tests_edge(tid, fn["id"], "Function", "static", 0.8)
                        call_links += 1

        # Strategy 2: broader import-based linking
        for fn in target_fns:
            if not db.tests_edge_exists(tid, fn["id"]):
                db.create_tests_edge(tid, fn["id"], "Function", "static_import", 0.5)
                import_links += 1

    total = call_links + import_links
    logger.info("Static links: %d (call=%d, import=%d)", total, call_links, import_links)
    return total


def _link_by_static_neo4j(db) -> int:
    """Static analysis linking using Neo4j Cypher."""
    with db.session() as session:
        result = db.run_query(session, """
            MATCH (t:Test)<-[:CONTAINS]-(tf:File)
            MATCH (tf)-[:IMPORTS]->(sf:File)-[:CONTAINS]->(fn:Function)
            WHERE NOT fn:Test
              AND NOT exists { (t)-[:TESTS]->(fn) }
            WITH t, fn, tf, sf
            MATCH (t_fn:Function {id: replace(t.id, 'test::', '')})
            WHERE any(call IN t_fn.calls WHERE fn.name = call OR fn.qualified_name ENDS WITH ('.' + call))
            MERGE (t)-[r:TESTS]->(fn)
            SET r.link_source = 'static', r.link_confidence = 0.8
            RETURN count(r) AS cnt
        """)
        call_links = result.single()["cnt"]

        result = db.run_query(session, """
            MATCH (tf:File)-[:IMPORTS]->(sf:File)-[:CONTAINS]->(fn:Function)
            WHERE NOT fn:Test
            MATCH (tf)-[:CONTAINS]->(t:Test)
            WHERE NOT exists { (t)-[:TESTS]->(fn) }
            MERGE (t)-[r:TESTS]->(fn)
            SET r.link_source = 'static_import', r.link_confidence = 0.5
            RETURN count(r) AS cnt
        """)
        import_links = result.single()["cnt"]

    total = call_links + import_links
    logger.info("Static links: %d (call=%d, import=%d)", total, call_links, import_links)
    return total


# ------------------------------------------------------------------
# Strategy 3: Coverage (opt-in)
# ------------------------------------------------------------------

def _link_by_coverage(repo_path: Path, db) -> int:
    """Run pytest --cov, parse results, create TESTS edges."""
    try:
        from coverage import CoverageData
    except ImportError:
        logger.warning("coverage package not installed; skipping coverage linking")
        return 0

    cov_file = repo_path / ".coverage"
    if not cov_file.exists():
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--cov", str(repo_path), "-q", "--no-header"],
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

    if hasattr(db, "get_functions_in_file"):
        # NetworkX backend
        all_tests = db.get_all_tests()
        for measured_file in cov_data.measured_files():
            try:
                rel_path = str(Path(measured_file).resolve().relative_to(repo_root))
            except ValueError:
                continue
            executed_lines = cov_data.lines(measured_file)
            if not executed_lines:
                continue
            fn_ids = db.get_functions_in_file(rel_path, min(executed_lines), max(executed_lines))
            if not fn_ids:
                continue
            for t in all_tests:
                for fn_id in fn_ids:
                    if not db.tests_edge_exists(t["id"], fn_id):
                        db.create_tests_edge(t["id"], fn_id, "Function", "coverage", 0.9)
                        links += 1
    else:
        # Neo4j backend
        with db.session() as session:
            for measured_file in cov_data.measured_files():
                try:
                    rel_path = str(Path(measured_file).resolve().relative_to(repo_root))
                except ValueError:
                    continue
                executed_lines = cov_data.lines(measured_file)
                if not executed_lines:
                    continue
                result = db.run_query(session, """
                    MATCH (fn:Function {file_path: $file_path})
                    WHERE fn.start_line <= $max_line AND fn.end_line >= $min_line
                    RETURN fn.id AS fn_id
                """, file_path=rel_path, min_line=min(executed_lines), max_line=max(executed_lines))
                fn_ids = [r["fn_id"] for r in result]
                if not fn_ids:
                    continue
                result = db.run_query(session, """
                    MATCH (t:Test)
                    WHERE any(fn_id IN $fn_ids WHERE NOT exists { MATCH (t)-[:TESTS]->(:Function {id: fn_id}) })
                    MATCH (fn:Function) WHERE fn.id IN $fn_ids
                      AND NOT exists { (t)-[:TESTS]->(fn) }
                    MERGE (t)-[r:TESTS]->(fn)
                    SET r.link_source = 'coverage', r.link_confidence = 0.9
                    RETURN count(r) AS cnt
                """, fn_ids=fn_ids)
                links += result.single()["cnt"]

    logger.info("Coverage links: %d", links)
    return links
