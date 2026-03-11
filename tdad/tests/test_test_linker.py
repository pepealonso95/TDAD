"""Tests for the test linker module."""

from unittest.mock import MagicMock, patch
from pathlib import Path

from tdad.indexer.test_linker import link_tests, _link_by_naming, _link_by_static_analysis


def _make_mock_db(query_results=None):
    """Create a mock GraphDB that returns configurable query results."""
    mock_db = MagicMock()
    mock_db.settings = MagicMock()
    mock_db.settings.use_coverage = False
    mock_db.settings.query_timeout = 20.0
    mock_db.settings.neo4j_database = "neo4j"

    mock_session = MagicMock()
    mock_db.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_db.session.return_value.__exit__ = MagicMock(return_value=False)

    # Default: return 0 for all count queries
    mock_result = MagicMock()
    mock_result.single.return_value = {"cnt": query_results or 0}
    mock_db.run_query.return_value = mock_result

    return mock_db


def test_link_tests_calls_all_strategies(sample_repo):
    mock_db = _make_mock_db(0)
    stats = link_tests(sample_repo, mock_db)

    assert "naming" in stats
    assert "static" in stats
    assert "coverage" in stats
    assert "total" in stats
    assert stats["coverage"] == 0  # coverage disabled


def test_link_tests_with_coverage_disabled(sample_repo):
    mock_db = _make_mock_db(0)
    mock_db.settings.use_coverage = False

    stats = link_tests(sample_repo, mock_db)
    assert stats["coverage"] == 0


def test_naming_linker_runs_queries():
    mock_db = _make_mock_db(5)
    count = _link_by_naming(mock_db)

    # Should run 3 queries (fn, qualified, class)
    assert mock_db.run_query.call_count == 3
    # Each returns 5, so total is 15
    assert count == 15


def test_static_linker_runs_queries():
    mock_db = _make_mock_db(3)
    count = _link_by_static_analysis(mock_db)

    # Should run 2 queries (call, import)
    assert mock_db.run_query.call_count == 2
    assert count == 6
