"""Tests for the impact analyzer module."""

from pathlib import Path
from unittest.mock import MagicMock

from tdad.analyzer.impact import (
    get_impacted_tests,
    _compute_score,
    _select_tiered,
    STRATEGY_WEIGHTS,
)


def _make_mock_db(direct=None, transitive=None, coverage=None, imports=None):
    """Create a mock GraphDB with configurable query results."""
    mock_db = MagicMock()
    mock_db.settings = MagicMock()
    mock_db.settings.query_timeout = 20.0
    mock_db.settings.neo4j_database = "neo4j"

    all_results = {
        0: direct or [],
        1: transitive or [],
        2: coverage or [],
        3: imports or [],
    }
    call_count = {"n": 0}

    def mock_run_query(session, query, **params):
        result = MagicMock()
        idx = call_count["n"]
        call_count["n"] += 1
        result.data.return_value = all_results.get(idx, [])
        return result

    mock_db.run_query.side_effect = mock_run_query

    mock_session = MagicMock()
    mock_db.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_db.session.return_value.__exit__ = MagicMock(return_value=False)

    return mock_db


def test_compute_score():
    weights = STRATEGY_WEIGHTS["balanced"]
    score = _compute_score(0.95, 0.8, weights)
    # (1-0.3)*0.95 + 0.3*0.8 = 0.665 + 0.24 = 0.905
    assert 0.9 <= score <= 0.91


def test_compute_score_clamped():
    weights = STRATEGY_WEIGHTS["aggressive"]
    score = _compute_score(1.0, 1.0, weights)
    assert score <= 1.0


def test_select_tiered():
    tests = [
        {"test_id": "a", "impact_score": 0.9},
        {"test_id": "b", "impact_score": 0.6},
        {"test_id": "c", "impact_score": 0.3},
        {"test_id": "d", "impact_score": 0.85},
    ]
    selected = _select_tiered(tests, max_tests=2)
    # Should pick the 2 highest: a (0.9) and d (0.85)
    ids = [t["test_id"] for t in selected]
    assert "a" in ids
    assert "d" in ids
    assert len(selected) == 2


def test_select_tiered_all():
    tests = [
        {"test_id": "a", "impact_score": 0.9},
        {"test_id": "b", "impact_score": 0.6},
    ]
    selected = _select_tiered(tests, max_tests=10)
    assert len(selected) == 2


def test_get_impacted_tests_empty(tmp_path):
    mock_db = _make_mock_db()
    result = get_impacted_tests(tmp_path, mock_db, [])
    assert result == []


def test_get_impacted_tests_direct(tmp_path):
    direct = [
        {"test_id": "t1", "test_name": "test_add", "test_file": "tests/test_calc.py",
         "target_file": "src/calc.py", "link_confidence": 0.8},
    ]
    mock_db = _make_mock_db(direct=direct)

    # Create a dummy .py file so normalization works
    py_file = tmp_path / "src" / "calc.py"
    py_file.parent.mkdir(parents=True, exist_ok=True)
    py_file.write_text("x = 1")

    result = get_impacted_tests(tmp_path, mock_db, ["src/calc.py"])
    assert len(result) == 1
    assert result[0]["test_id"] == "t1"
    assert result[0]["impact_score"] > 0


def test_get_impacted_tests_deduplicates(tmp_path):
    """Same test from two strategies: highest score wins."""
    direct = [
        {"test_id": "t1", "test_name": "test_add", "test_file": "tests/t.py",
         "target_file": "src/m.py", "link_confidence": 0.9},
    ]
    imports = [
        {"test_id": "t1", "test_name": "test_add", "test_file": "tests/t.py",
         "target_file": "src/m.py", "link_confidence": 0.5},
    ]
    mock_db = _make_mock_db(direct=direct, imports=imports)

    py_file = tmp_path / "src" / "m.py"
    py_file.parent.mkdir(parents=True, exist_ok=True)
    py_file.write_text("")

    result = get_impacted_tests(tmp_path, mock_db, ["src/m.py"])
    assert len(result) == 1
    # Direct score should be higher than imports score
    assert result[0]["impact_reason"] == "Directly tests changed code"
