"""Pytest execution wrapper."""

import subprocess
import sys
from pathlib import Path
from typing import Dict, List


def run_tests(
    repo_path: Path,
    test_ids: List[str],
    timeout: int = 300,
) -> Dict:
    """Run specific tests via pytest and return results summary.

    Args:
        repo_path: Root of the repository.
        test_ids: List of pytest node IDs (e.g. "tests/test_foo.py::test_bar").
        timeout: Maximum seconds for the pytest process.

    Returns:
        Dict with keys: passed, failed, errors, output, returncode.
    """
    if not test_ids:
        return {"passed": 0, "failed": 0, "errors": 0, "output": "No tests specified.", "returncode": 0}

    cmd = [sys.executable, "-m", "pytest", "--tb=short", "-q"] + list(test_ids)

    try:
        result = subprocess.run(
            cmd,
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "output": f"pytest timed out after {timeout}s",
            "returncode": -1,
        }

    output = result.stdout + result.stderr
    passed, failed, errors = _parse_summary(output)

    return {
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "output": output,
        "returncode": result.returncode,
    }


def _parse_summary(output: str) -> tuple:
    """Extract pass/fail/error counts from pytest output."""
    passed = failed = errors = 0
    for line in reversed(output.splitlines()):
        line = line.strip()
        if not line:
            continue
        # Pytest summary line: "3 passed, 1 failed, 1 error in 0.5s"
        parts = line.replace(",", " ").split()
        for i, word in enumerate(parts):
            if word == "passed" and i > 0:
                try:
                    passed = int(parts[i - 1])
                except ValueError:
                    pass
            elif word == "failed" and i > 0:
                try:
                    failed = int(parts[i - 1])
                except ValueError:
                    pass
            elif word in ("error", "errors") and i > 0:
                try:
                    errors = int(parts[i - 1])
                except ValueError:
                    pass
        if "passed" in line or "failed" in line or "error" in line:
            break
    return passed, failed, errors
