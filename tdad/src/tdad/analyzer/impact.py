"""Test impact analyzer: identifies tests impacted by code changes.

Uses 4 Cypher query strategies with weighted scoring and tiered selection.
"""

import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from ..core.graph_db import GraphDB

logger = logging.getLogger(__name__)

STRATEGY_WEIGHTS = {
    "conservative": {
        "direct": 0.95, "transitive": 0.55, "coverage": 0.85, "imports": 0.4,
        "confidence_weight": 0.35, "line_boost_max": 0.15,
    },
    "balanced": {
        "direct": 0.95, "transitive": 0.7, "coverage": 0.8, "imports": 0.5,
        "confidence_weight": 0.3, "line_boost_max": 0.2,
    },
    "aggressive": {
        "direct": 0.95, "transitive": 0.82, "coverage": 0.9, "imports": 0.65,
        "confidence_weight": 0.25, "line_boost_max": 0.25,
    },
}


def get_impacted_tests(
    repo_path: Path,
    db: GraphDB,
    changed_files: List[str],
    strategy: str = "balanced",
    max_tests: int = 50,
) -> List[Dict[str, Any]]:
    """Identify tests impacted by changes to the given files.

    Returns a list of dicts with keys:
        test_id, test_name, test_file, impact_score, impact_reason
    """
    changed_files = _normalize_paths(repo_path, changed_files)
    if not changed_files:
        return []

    weights = STRATEGY_WEIGHTS.get(strategy, STRATEGY_WEIGHTS["balanced"])

    # Run all 4 strategies
    raw: Dict[str, Dict[str, Any]] = {}

    if hasattr(db, "direct_tests"):
        # NetworkX backend — use direct methods
        for test in db.direct_tests(changed_files):
            _update(raw, test, "direct", "Directly tests changed code", weights)
        for test in db.transitive_tests(changed_files):
            _update(raw, test, "transitive", "Transitive call dependency", weights)
        for test in db.coverage_tests(changed_files):
            _update(raw, test, "coverage", "Coverage dependency", weights)
        for test in db.import_tests(changed_files):
            _update(raw, test, "imports", "Imports changed file", weights)
    else:
        # Neo4j backend — use Cypher queries
        for test in _direct_tests(db, changed_files):
            _update(raw, test, "direct", "Directly tests changed code", weights)
        for test in _transitive_tests(db, changed_files):
            _update(raw, test, "transitive", "Transitive call dependency", weights)
        for test in _coverage_tests(db, changed_files):
            _update(raw, test, "coverage", "Coverage dependency", weights)
        for test in _import_tests(db, changed_files):
            _update(raw, test, "imports", "Imports changed file", weights)

    # Sort and select
    all_tests = sorted(raw.values(), key=lambda t: -t["impact_score"])
    return _select_tiered(all_tests, max_tests)


# ------------------------------------------------------------------
# Scoring
# ------------------------------------------------------------------

def _compute_score(base_weight: float, link_confidence: float, weights: dict) -> float:
    cw = weights["confidence_weight"]
    score = (1.0 - cw) * base_weight + cw * link_confidence
    return max(0.0, min(1.0, score))


def _update(
    acc: Dict[str, Dict],
    test: Dict,
    source: str,
    reason: str,
    weights: dict,
) -> None:
    test_id = str(test.get("test_id", ""))
    if not test_id:
        return

    confidence = float(test.get("link_confidence", 0.6))
    confidence = max(0.0, min(1.0, confidence))
    score = _compute_score(float(weights[source]), confidence, weights)

    candidate = {
        "test_id": test_id,
        "test_name": test.get("test_name", ""),
        "test_file": test.get("test_file", ""),
        "impact_score": round(score, 4),
        "impact_reason": reason,
    }

    existing = acc.get(test_id)
    if existing is None or candidate["impact_score"] > existing["impact_score"]:
        acc[test_id] = candidate


def _select_tiered(tests: List[Dict], max_tests: int) -> List[Dict]:
    """Select tests by confidence tiers: high >= 0.8, medium 0.5-0.8, low < 0.5."""
    high = [t for t in tests if t["impact_score"] >= 0.8]
    medium = [t for t in tests if 0.5 <= t["impact_score"] < 0.8]
    low = [t for t in tests if t["impact_score"] < 0.5]

    selected: List[Dict] = []
    for band in (high, medium, low):
        for t in band:
            if len(selected) >= max_tests:
                return selected
            selected.append(t)
    return selected


# ------------------------------------------------------------------
# Path normalization
# ------------------------------------------------------------------

def _normalize_paths(repo_path: Path, changed_files: List[str]) -> List[str]:
    repo_root = repo_path.resolve()
    normalized = []
    seen: Set[str] = set()
    for raw in changed_files:
        if not raw:
            continue
        p = Path(raw)
        if p.is_absolute():
            try:
                rel = str(p.resolve().relative_to(repo_root))
            except ValueError:
                continue
        else:
            rel = str(p)
        if not rel.endswith(".py"):
            continue
        if rel not in seen:
            seen.add(rel)
            normalized.append(rel)
    return normalized


# ------------------------------------------------------------------
# Cypher queries (4 strategies)
# ------------------------------------------------------------------

def _direct_tests(db: GraphDB, changed_files: List[str]) -> List[Dict]:
    with db.session() as session:
        result = db.run_query(session, """
            MATCH (t:Test)-[r:TESTS]->(target)
            WHERE (target:Function OR target:Class)
              AND target.file_path IN $changed_files
            RETURN DISTINCT
                t.id AS test_id,
                t.name AS test_name,
                t.file_path AS test_file,
                target.file_path AS target_file,
                coalesce(r.link_confidence, 1.0) AS link_confidence
        """, changed_files=changed_files)
        return result.data()


def _transitive_tests(db: GraphDB, changed_files: List[str]) -> List[Dict]:
    with db.session() as session:
        result = db.run_query(session, """
            MATCH (t:Test)-[r1:TESTS]->(fn1:Function)
            MATCH (fn1)-[:CALLS*1..3]->(fn2:Function)
            WHERE fn2.file_path IN $changed_files
            RETURN DISTINCT
                t.id AS test_id,
                t.name AS test_name,
                t.file_path AS test_file,
                fn2.file_path AS target_file,
                (coalesce(r1.link_confidence, 0.8) * 0.7) AS link_confidence
        """, changed_files=changed_files)
        return result.data()


def _coverage_tests(db: GraphDB, changed_files: List[str]) -> List[Dict]:
    with db.session() as session:
        result = db.run_query(session, """
            MATCH (t:Test)-[r:DEPENDS_ON]->(f:File)
            WHERE f.path IN $changed_files
            RETURN DISTINCT
                t.id AS test_id,
                t.name AS test_name,
                t.file_path AS test_file,
                f.path AS target_file,
                coalesce(r.link_confidence, 0.5) AS link_confidence
        """, changed_files=changed_files)
        return result.data()


def _import_tests(db: GraphDB, changed_files: List[str]) -> List[Dict]:
    with db.session() as session:
        result = db.run_query(session, """
            MATCH (test_file:File)-[:IMPORTS]->(changed_file:File)
            WHERE changed_file.path IN $changed_files
            MATCH (test_file)-[:CONTAINS]->(t:Test)
            RETURN DISTINCT
                t.id AS test_id,
                t.name AS test_name,
                t.file_path AS test_file,
                changed_file.path AS target_file,
                0.45 AS link_confidence
        """, changed_files=changed_files)
        return result.data()


# ------------------------------------------------------------------
# Static test map export
# ------------------------------------------------------------------

def export_test_map(db: GraphDB, repo_dir: Path) -> int:
    """Export source-file to test-file mapping as a static text file.

    Writes to repo_dir/.tdad/test_map.txt so the AI agent can look up
    impacted tests without needing the tdad CLI or Neo4j at runtime.
    Supplements graph-based mappings with filename heuristics.

    Returns the number of source files with mapped tests.
    """
    mapping: Dict[str, Set[str]] = defaultdict(set)
    try:
        if hasattr(db, "get_test_source_mappings"):
            for row in db.get_test_source_mappings():
                mapping[row["source_file"]].add(row["test_file"])
        else:
            with db.session() as session:
                result = db.run_query(session, """
                    MATCH (t:Test)-[:TESTS]->(target)
                    WHERE (target:Function OR target:Class)
                    RETURN DISTINCT target.file_path AS source_file,
                           t.file_path AS test_file
                    ORDER BY source_file, test_file
                """)
                for row in result.data():
                    source = row.get("source_file", "")
                    test = row.get("test_file", "")
                    if source and test and source != test:
                        mapping[source].add(test)
    except Exception as exc:
        logger.warning("Failed to query test mappings: %s", exc)

    # Supplement with filename-convention heuristics
    _add_heuristic_mappings(repo_dir, mapping)

    return _write_test_map(repo_dir, mapping)


def export_test_map_heuristic(repo_dir: Path) -> int:
    """Generate test_map.txt using only filename heuristics (no graph DB).

    Fallback for when Neo4j is unavailable. Uses naming conventions
    like test_foo.py -> foo.py to build the mapping.

    Returns the number of source files with mapped tests.
    """
    mapping: Dict[str, Set[str]] = defaultdict(set)
    _add_heuristic_mappings(repo_dir, mapping)
    return _write_test_map(repo_dir, mapping)


def _write_test_map(repo_dir: Path, mapping: Dict[str, Set[str]]) -> int:
    """Write the test mapping to repo_dir/.tdad/test_map.txt."""
    out_path = repo_dir / ".tdad" / "test_map.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not mapping:
        out_path.write_text("# No test mappings found\n")
        return 0

    lines = []
    for source in sorted(mapping):
        tests = " ".join(sorted(mapping[source]))
        lines.append(f"{source}: {tests}")
    out_path.write_text("\n".join(lines) + "\n")
    return len(lines)


def _path_words(path: str) -> Set[str]:
    """Extract meaningful words from a file path's directory components."""
    parts = Path(path).parts[:-1]  # exclude filename
    words: Set[str] = set()
    for p in parts:
        tokens = re.split(r'[_\-]', p.lower())
        words.update(t for t in tokens if t and t not in ('test', 'tests', 'src'))
    return words


def _path_similarity(test_path: str, source_path: str) -> int:
    """Count shared word tokens between directory paths (higher = more similar)."""
    return len(_path_words(test_path) & _path_words(source_path))


def _map_tests_py_by_proximity(
    test_file: str,
    source_by_stem: Dict[str, List[str]],
    mapping: Dict[str, Set[str]],
) -> None:
    """Map a tests.py file to source files using directory proximity.

    For tests.py in a directory like 'tests/auth/' or 'myapp/tests/',
    finds source files whose directory path shares components with the
    test file's directory path.
    """
    test_parts = set(Path(test_file).parts[:-1])  # directory components
    test_parts -= {"test", "tests"}  # exclude generic test dir names

    if not test_parts:
        return

    best_score = 0
    best_sources: List[str] = []

    for sources in source_by_stem.values():
        for src in sources:
            src_parts = set(Path(src).parts[:-1])
            overlap = len(test_parts & src_parts)
            if overlap > best_score:
                best_score = overlap
                best_sources = [src]
            elif overlap == best_score and overlap > 0:
                best_sources.append(src)

    # Only map if there's a meaningful directory overlap
    for src in best_sources:
        mapping[src].add(test_file)


def _find_by_prefix(
    target: str,
    test_file: str,
    source_by_stem: Dict[str, List[str]],
) -> List[str]:
    """Try progressively shorter underscore-delimited prefixes of target.

    For 'query_aggregation', tries 'query' (dropping trailing segments).
    Uses directory proximity to disambiguate when multiple source files match.
    Returns the best matching source file(s), or [] if none found.
    """
    parts = target.split('_')
    # Try longest prefix first, down to single-word (minimum 4 chars)
    for length in range(len(parts) - 1, 0, -1):
        prefix = '_'.join(parts[:length])
        if len(prefix) < 4:
            continue  # Skip very short prefixes to avoid false positives
        candidates = source_by_stem.get(prefix, [])
        if not candidates:
            candidates = source_by_stem.get(f"_{prefix}", [])
        if candidates:
            # Use proximity to pick the best match
            if len(candidates) <= 2:
                return candidates
            scored = [(src, _path_similarity(test_file, src)) for src in candidates]
            scored.sort(key=lambda x: -x[1])
            best_score = scored[0][1]
            return [src for src, score in scored if score >= best_score]
    return []


def _add_heuristic_mappings(repo_dir: Path, mapping: Dict[str, Set[str]]) -> None:
    """Supplement mapping with filename-convention-based test links.

    Matches: test_foo.py <-> foo.py, foo_test.py <-> foo.py
    When a stem is ambiguous (3+ source files), uses directory proximity
    to select the best match instead of mapping all candidates.
    """
    repo = repo_dir.resolve()
    source_by_stem: Dict[str, List[str]] = defaultdict(list)
    test_files: List[str] = []

    for py in repo.rglob("*.py"):
        parts = py.relative_to(repo).parts
        if any(p.startswith('.') or p == '__pycache__' for p in parts):
            continue
        rel = str(py.relative_to(repo))
        stem = py.stem
        if stem.startswith("test_") or stem.endswith("_test") or stem == "tests":
            test_files.append(rel)
        elif stem not in ("__init__", "conftest"):
            source_by_stem[stem].append(rel)

    for tf in test_files:
        stem = Path(tf).stem
        if stem.startswith("test_"):
            target = stem[5:]
        elif stem.endswith("_test"):
            target = stem[:-5]
        elif stem == "tests":
            # tests.py — map to source files in nearest non-test ancestor
            # e.g., tests/auth/tests.py → source files whose path contains "auth"
            _map_tests_py_by_proximity(tf, source_by_stem, mapping)
            continue
        else:
            continue
        candidates = source_by_stem.get(target, [])
        if not candidates:
            # Try underscore-prefixed variant: test_forest.py → _forest.py
            # Common in scikit-learn, matplotlib, and other scientific Python repos
            candidates = source_by_stem.get(f"_{target}", [])
        if not candidates:
            # Prefix fallback: test_query_aggregation.py → query.py
            # Try progressively shorter prefixes by splitting on '_'
            candidates = _find_by_prefix(target, tf, source_by_stem)
        if not candidates:
            continue
        if len(candidates) <= 2:
            # Unambiguous — map all
            for src in candidates:
                mapping[src].add(tf)
        else:
            # Ambiguous stem — use directory proximity to pick best match
            scored = [(src, _path_similarity(tf, src)) for src in candidates]
            scored.sort(key=lambda x: -x[1])
            best_score = scored[0][1]
            for src, score in scored:
                if score >= best_score:
                    mapping[src].add(tf)
                else:
                    break
