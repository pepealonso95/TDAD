"""TDAD CLI: tdad index|impact|run-tests|stats"""

import argparse
import sys
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="tdad",
        description="Test-Driven AI Development — GraphRAG test impact analysis",
    )
    sub = parser.add_subparsers(dest="command")

    # -- index --
    p_index = sub.add_parser("index", help="Index a repository into the code-test graph")
    p_index.add_argument("repo_path", type=Path, help="Path to repository")
    p_index.add_argument("--force", action="store_true", help="Force full rebuild")

    # -- impact --
    p_impact = sub.add_parser("impact", help="Find tests impacted by changed files")
    p_impact.add_argument("repo_path", type=Path, help="Path to repository")
    p_impact.add_argument("--files", nargs="+", required=True, help="Changed file paths")
    p_impact.add_argument("--strategy", default="balanced", choices=["conservative", "balanced", "aggressive"])
    p_impact.add_argument("--max-tests", type=int, default=50)

    # -- run-tests --
    p_run = sub.add_parser("run-tests", help="Run specific tests via pytest")
    p_run.add_argument("repo_path", type=Path, help="Path to repository")
    p_run.add_argument("--tests", nargs="+", required=True, help="Pytest node IDs")
    p_run.add_argument("--timeout", type=int, default=300)

    # -- stats --
    p_stats = sub.add_parser("stats", help="Show graph statistics")
    p_stats.add_argument("repo_path", type=Path, help="Path to repository")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    try:
        if args.command == "index":
            return _cmd_index(args)
        elif args.command == "impact":
            return _cmd_impact(args)
        elif args.command == "run-tests":
            return _cmd_run_tests(args)
        elif args.command == "stats":
            return _cmd_stats(args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _cmd_index(args):
    from .core.config import get_settings
    from .core.graph_db import GraphDB
    from .indexer.graph_builder import build_graph
    from .indexer.test_linker import link_tests

    settings = get_settings()
    with GraphDB(settings) as db:
        print(f"Indexing {args.repo_path} ...")
        stats = build_graph(args.repo_path, db, force=args.force)
        print(f"  Files:     {stats['files']}")
        print(f"  Functions: {stats['functions']}")
        print(f"  Classes:   {stats['classes']}")
        print(f"  Tests:     {stats['tests']}")
        print(f"  Edges:     {stats['edges']}")

        print("Linking tests ...")
        link_stats = link_tests(args.repo_path, db)
        print(f"  Naming:  {link_stats['naming']}")
        print(f"  Static:  {link_stats['static']}")
        print(f"  Coverage: {link_stats['coverage']}")
        print(f"  Total:   {link_stats['total']}")

    return 0


def _cmd_impact(args):
    from .core.config import get_settings
    from .core.graph_db import GraphDB
    from .analyzer.impact import get_impacted_tests

    settings = get_settings()
    with GraphDB(settings) as db:
        tests = get_impacted_tests(
            args.repo_path, db, args.files,
            strategy=args.strategy, max_tests=args.max_tests,
        )

    if not tests:
        print("No impacted tests found.")
        return 0

    # Markdown table
    print(f"## Impacted Tests ({len(tests)} found)\n")
    print("| Score | Test | File | Reason |")
    print("|-------|------|------|--------|")
    for t in tests:
        score = f"{t['impact_score']:.2f}"
        print(f"| {score} | {t['test_name']} | {t['test_file']} | {t['impact_reason']} |")

    return 0


def _cmd_run_tests(args):
    from .runner.test_runner import run_tests

    result = run_tests(args.repo_path, args.tests, timeout=args.timeout)
    print(result["output"])
    if result["returncode"] == 0:
        print(f"\nAll tests passed ({result['passed']} passed)")
    else:
        print(f"\n{result['passed']} passed, {result['failed']} failed, {result['errors']} errors")
    return result["returncode"]


def _cmd_stats(args):
    from .core.config import get_settings
    from .core.graph_db import GraphDB

    settings = get_settings()
    with GraphDB(settings) as db:
        with db.session() as session:
            counts = {}
            for label in ["File", "Function", "Class", "Test"]:
                result = db.run_query(session, f"MATCH (n:{label}) RETURN count(n) AS cnt")
                counts[label] = result.single()["cnt"]

            result = db.run_query(session, "MATCH ()-[r]->() RETURN count(r) AS cnt")
            counts["Edges"] = result.single()["cnt"]

            # TESTS edges specifically
            result = db.run_query(session, "MATCH ()-[r:TESTS]->() RETURN count(r) AS cnt")
            counts["TESTS edges"] = result.single()["cnt"]

    print("## Graph Statistics\n")
    for label, count in counts.items():
        print(f"  {label:15s} {count:>6}")

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
