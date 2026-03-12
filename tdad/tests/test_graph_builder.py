"""Tests for the graph builder module."""

from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from tdad.indexer.graph_builder import (
    build_graph, _collect_python_files, _module_name,
    _compute_diff, _hash_file,
)


def test_collect_python_files(sample_repo):
    files = _collect_python_files(sample_repo)
    names = [f.name for f in files]

    assert "calculator.py" in names
    assert "utils.py" in names
    assert "test_calculator.py" in names
    assert "test_utils.py" in names


def test_collect_skips_pycache(tmp_path):
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "cached.py").write_text("x = 1")
    (tmp_path / "good.py").write_text("y = 2")

    files = _collect_python_files(tmp_path)
    names = [f.name for f in files]
    assert "good.py" in names
    assert "cached.py" not in names


def test_module_name():
    assert _module_name("src/calculator.py") == "src.calculator"
    assert _module_name("tests/test_utils.py") == "tests.test_utils"
    assert _module_name("foo.py") == "foo"


def _make_builder_mock_db():
    """Create mock db that returns empty indexed hashes, then accepts writes."""
    mock_db = MagicMock()
    mock_db.settings = MagicMock()
    mock_db.settings.index_workers = 1
    mock_db.settings.query_timeout = 20.0
    mock_db.settings.neo4j_database = "neo4j"

    mock_session = MagicMock()
    mock_db.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_db.session.return_value.__exit__ = MagicMock(return_value=False)

    # First run_query call is _get_indexed_hashes → return empty iterator
    hash_result = MagicMock()
    hash_result.__iter__ = MagicMock(return_value=iter([]))
    default_result = MagicMock()

    call_count = {"n": 0}

    def side_effect(session, query, **params):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return hash_result
        return default_result

    mock_db.run_query.side_effect = side_effect
    return mock_db


def test_build_graph_calls_neo4j(sample_repo):
    """Verify build_graph calls the database with UNWIND queries."""
    mock_db = _make_builder_mock_db()

    stats = build_graph(sample_repo, mock_db, force=False)

    assert stats["files"] > 0
    assert stats["functions"] > 0
    assert stats["tests"] > 0
    assert mock_db.ensure_schema.called
    assert mock_db.run_query.called


def test_build_graph_force_clears(sample_repo):
    """Verify --force calls clear_database."""
    mock_db = MagicMock()
    mock_db.settings = MagicMock()
    mock_db.settings.index_workers = 1
    mock_db.settings.query_timeout = 20.0
    mock_db.settings.neo4j_database = "neo4j"

    mock_session = MagicMock()
    mock_db.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_db.session.return_value.__exit__ = MagicMock(return_value=False)
    mock_db.run_query.return_value = MagicMock()

    build_graph(sample_repo, mock_db, force=True)
    assert mock_db.clear_database.called


def test_build_graph_invalid_path(tmp_path):
    mock_db = MagicMock()
    with pytest.raises(ValueError, match="Not a directory"):
        build_graph(tmp_path / "nonexistent", mock_db)


def test_incremental_skips_unchanged(sample_repo):
    """When all hashes match, nothing is re-parsed."""
    python_files = _collect_python_files(sample_repo)
    repo_path = sample_repo.resolve()

    # Build indexed dict with current hashes (simulating a prior full index)
    indexed = {}
    for p in python_files:
        rel = str(p.resolve().relative_to(repo_path))
        indexed[rel] = _hash_file(p)

    new_or_changed, unchanged, deleted = _compute_diff(python_files, repo_path, indexed)
    assert len(new_or_changed) == 0
    assert len(unchanged) == len(python_files)
    assert len(deleted) == 0


def test_incremental_detects_new_file(sample_repo):
    """A file not in the index is marked as new."""
    python_files = _collect_python_files(sample_repo)
    repo_path = sample_repo.resolve()

    # Index is empty → everything is new
    new_or_changed, unchanged, deleted = _compute_diff(python_files, repo_path, {})
    assert len(new_or_changed) == len(python_files)
    assert len(unchanged) == 0


def test_incremental_detects_deleted_file(sample_repo):
    """A file in the index but not on disk is marked as deleted."""
    python_files = _collect_python_files(sample_repo)
    repo_path = sample_repo.resolve()

    indexed = {"gone/old_module.py": "abc123"}
    for p in python_files:
        rel = str(p.resolve().relative_to(repo_path))
        indexed[rel] = _hash_file(p)

    _, _, deleted = _compute_diff(python_files, repo_path, indexed)
    assert "gone/old_module.py" in deleted
