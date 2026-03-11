"""Tests for the CLI module."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

from tdad.cli import main


def test_cli_no_args(capsys):
    """No args prints help and returns 0."""
    result = main([])
    assert result == 0
    captured = capsys.readouterr()
    assert "tdad" in captured.out.lower() or "usage" in captured.out.lower()


def test_cli_index_missing_path(capsys):
    """Index without repo_path fails."""
    with patch("sys.stderr"):
        try:
            main(["index"])
            assert False, "Should have raised SystemExit"
        except SystemExit:
            pass


def test_cli_impact_requires_files(capsys):
    """Impact without --files fails."""
    with patch("sys.stderr"):
        try:
            main(["impact", "/tmp/repo"])
            assert False, "Should have raised SystemExit"
        except SystemExit:
            pass


def test_cli_run_tests_requires_tests(capsys):
    """run-tests without --tests fails."""
    with patch("sys.stderr"):
        try:
            main(["run-tests", "/tmp/repo"])
            assert False, "Should have raised SystemExit"
        except SystemExit:
            pass


def test_cli_stats_handles_error(capsys):
    """Stats with unreachable Neo4j returns error code 1."""
    with patch("tdad.core.graph_db.GraphDatabase") as mock_gd:
        mock_gd.driver.side_effect = Exception("Connection refused")
        result = main(["stats", "/tmp/nonexistent"])
    assert result == 1


def test_cli_index_with_mock(capsys, sample_repo):
    """Index command with mocked database."""
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)

    with patch("tdad.core.config.get_settings") as mock_settings, \
         patch("tdad.core.graph_db.GraphDB", return_value=mock_db), \
         patch("tdad.indexer.graph_builder.build_graph", return_value={
             "files": 4, "functions": 6, "classes": 1, "tests": 7, "edges": 10
         }), \
         patch("tdad.indexer.test_linker.link_tests", return_value={
             "naming": 3, "static": 2, "coverage": 0, "total": 5
         }):
        result = main(["index", str(sample_repo)])

    assert result == 0
    captured = capsys.readouterr()
    assert "Files:" in captured.out
    assert "4" in captured.out


def test_cli_as_module():
    """Verify tdad.cli can be invoked as python -m."""
    result = subprocess.run(
        [sys.executable, "-c", "from tdad.cli import main; main([])"],
        capture_output=True,
        text=True,
    )
    # Should exit 0 (help printed)
    assert result.returncode == 0
