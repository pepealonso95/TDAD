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

from ..core.graph_db import GraphDB

logger = logging.getLogger(__name__)


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
        stats["total"], stats["naming"], stats["static"], stats["coverage"],
    )
    return stats


# ------------------------------------------------------------------
# Strategy 1: Naming conventions
# ------------------------------------------------------------------

def _link_by_naming(db: GraphDB) -> int:
    """Link test_foo → foo, TestFoo methods → Foo methods."""
    with db.session() as session:
        # test_X -> X (function-level)
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

        # test_X -> X (via qualified name suffix)
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

        # TestFoo.test_bar -> Foo class
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

def _link_by_static_analysis(db: GraphDB) -> int:
    """Link tests to functions they call or whose modules they import."""
    with db.session() as session:
        # Tests that CALL source functions
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

        # Tests in files that import source files (broader, lower confidence)
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

def _link_by_coverage(repo_path: Path, db: GraphDB) -> int:
    """Run pytest --cov, parse results, create TESTS edges."""
    try:
        from coverage import CoverageData
    except ImportError:
        logger.warning("coverage package not installed; skipping coverage linking")
        return 0

    cov_file = repo_path / ".coverage"
    if not cov_file.exists():
        # Run coverage
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
    with db.session() as session:
        for measured_file in cov_data.measured_files():
            try:
                rel_path = str(Path(measured_file).resolve().relative_to(repo_root))
            except ValueError:
                continue

            executed_lines = cov_data.lines(measured_file)
            if not executed_lines:
                continue

            # Find functions that overlap with executed lines
            result = db.run_query(session, """
                MATCH (fn:Function {file_path: $file_path})
                WHERE fn.start_line <= $max_line AND fn.end_line >= $min_line
                RETURN fn.id AS fn_id
            """, file_path=rel_path, min_line=min(executed_lines), max_line=max(executed_lines))

            fn_ids = [r["fn_id"] for r in result]
            if not fn_ids:
                continue

            # Link all tests in test files to these functions
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
