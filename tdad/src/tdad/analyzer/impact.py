"""Test impact analyzer: identifies tests impacted by code changes.

Uses 4 Cypher query strategies with weighted scoring and tiered selection.
"""

import logging
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
