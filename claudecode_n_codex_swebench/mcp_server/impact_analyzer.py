"""
Test Impact Analyzer - Identifies tests impacted by code changes

Uses graph traversal to find:
1. Tests directly testing changed functions
2. Tests testing functions that call changed functions
3. Tests with coverage dependencies on changed files
"""
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import git
from unidiff import PatchSet

from .config import config
from .graph_db import get_db

logger = logging.getLogger(__name__)


class ImpactAnalyzer:
    """Analyzes the impact of code changes on tests"""

    def __init__(self):
        self.db = get_db()

    def get_impacted_tests(
        self,
        repo_path: Path,
        changed_files: Optional[List[str]] = None,
        base_commit: str = "HEAD",
        impact_threshold: float = 0.1
    ) -> List[Dict]:
        """
        Get tests impacted by code changes

        Args:
            repo_path: Path to repository
            changed_files: List of changed files (or use git diff)
            base_commit: Git commit to compare against
            impact_threshold: Minimum impact score (0-1) to include

        Returns:
            List of impacted tests with scores
        """
        logger.info(f"Analyzing test impact for: {repo_path}")

        if changed_files is None:
            changed_files = self._get_changed_files(repo_path, base_commit)

        logger.info(f"Analyzing impact of {len(changed_files)} changed files")

        # Get changed lines for each file (for more precise analysis)
        changed_lines = self._get_changed_lines(repo_path, changed_files, base_commit)

        # Find impacted tests using multiple strategies
        impacted_tests = {}

        # Strategy 1: Direct test coverage
        direct_tests = self._find_directly_tested_functions(changed_files)
        for test in direct_tests:
            test_id = test["test_id"]
            if test_id not in impacted_tests or impacted_tests[test_id]["impact_score"] < 1.0:
                impacted_tests[test_id] = {
                    **test,
                    "impact_score": 1.0,
                    "impact_reason": "Directly tests changed code"
                }

        # Strategy 2: Transitive call dependencies
        transitive_tests = self._find_transitive_dependencies(changed_files)
        for test in transitive_tests:
            test_id = test["test_id"]
            if test_id not in impacted_tests or impacted_tests[test_id]["impact_score"] < 0.7:
                impacted_tests[test_id] = {
                    **test,
                    "impact_score": 0.7,
                    "impact_reason": "Tests function calling changed code"
                }

        # Strategy 3: Coverage-based dependencies
        coverage_tests = self._find_coverage_dependencies(changed_files)
        for test in coverage_tests:
            test_id = test["test_id"]
            coverage_score = test.get("coverage_pct", 0.5)
            if test_id not in impacted_tests or impacted_tests[test_id]["impact_score"] < coverage_score:
                impacted_tests[test_id] = {
                    **test,
                    "impact_score": coverage_score,
                    "impact_reason": "Coverage dependency on changed file"
                }

        # Strategy 4: Import dependencies
        import_tests = self._find_import_dependencies(changed_files)
        for test in import_tests:
            test_id = test["test_id"]
            if test_id not in impacted_tests or impacted_tests[test_id]["impact_score"] < 0.5:
                impacted_tests[test_id] = {
                    **test,
                    "impact_score": 0.5,
                    "impact_reason": "Imports changed file"
                }

        # Filter by threshold and sort by impact score
        filtered_tests = [
            test for test in impacted_tests.values()
            if test["impact_score"] >= impact_threshold
        ]

        filtered_tests.sort(key=lambda t: t["impact_score"], reverse=True)

        logger.info(f"Found {len(filtered_tests)} impacted tests (threshold: {impact_threshold})")

        return filtered_tests

    def _get_changed_files(self, repo_path: Path, base_commit: str) -> List[str]:
        """Get list of changed files using git diff"""
        try:
            repo = git.Repo(repo_path)
            diff = repo.git.diff('--name-only', base_commit)
            changed_files = [line.strip() for line in diff.splitlines() if line.strip()]
            # Return full paths
            return [str(repo_path / f) for f in changed_files if f.endswith('.py')]
        except Exception as e:
            logger.error(f"Error getting changed files from git: {e}")
            return []

    def _get_changed_lines(
        self,
        repo_path: Path,
        changed_files: List[str],
        base_commit: str
    ) -> Dict[str, Set[int]]:
        """
        Get specific line numbers that changed in each file

        Returns:
            Dict mapping file_path -> set of changed line numbers
        """
        changed_lines = {}

        try:
            repo = git.Repo(repo_path)
            diff_text = repo.git.diff('-U0', base_commit)  # No context lines

            # Parse unified diff
            patch_set = PatchSet(diff_text)

            for patched_file in patch_set:
                if patched_file.is_added_file or patched_file.is_modified_file:
                    file_path = str(repo_path / patched_file.path)
                    lines = set()

                    for hunk in patched_file:
                        # Get added and modified lines
                        for line in hunk:
                            if line.is_added or line.is_removed:
                                lines.add(line.target_line_no or line.source_line_no)

                    changed_lines[file_path] = lines

        except Exception as e:
            logger.error(f"Error parsing changed lines: {e}")

        return changed_lines

    def _find_directly_tested_functions(self, changed_files: List[str]) -> List[Dict]:
        """Find tests that directly test functions in changed files"""
        with self.db.driver.session(database=config.neo4j.database) as session:
            result = session.run(
                """
                MATCH (t:Test)-[:TESTS]->(fn:Function)
                WHERE fn.file_path IN $changed_files
                RETURN DISTINCT
                    t.id as test_id,
                    t.name as test_name,
                    t.file_path as test_file,
                    fn.name as target_function,
                    fn.file_path as target_file
                """,
                changed_files=changed_files
            )
            return result.data()

    def _find_transitive_dependencies(self, changed_files: List[str]) -> List[Dict]:
        """Find tests that test functions calling changed functions"""
        with self.db.driver.session(database=config.neo4j.database) as session:
            result = session.run(
                """
                MATCH (t:Test)-[:TESTS]->(fn1:Function)-[:CALLS]->(fn2:Function)
                WHERE fn2.file_path IN $changed_files
                RETURN DISTINCT
                    t.id as test_id,
                    t.name as test_name,
                    t.file_path as test_file,
                    fn1.name as calling_function,
                    fn2.name as called_function
                """,
                changed_files=changed_files
            )
            return result.data()

    def _find_coverage_dependencies(self, changed_files: List[str]) -> List[Dict]:
        """Find tests with coverage dependencies on changed files"""
        with self.db.driver.session(database=config.neo4j.database) as session:
            result = session.run(
                """
                MATCH (t:Test)-[r:DEPENDS_ON]->(f:File)
                WHERE f.path IN $changed_files
                RETURN DISTINCT
                    t.id as test_id,
                    t.name as test_name,
                    t.file_path as test_file,
                    r.coverage_pct as coverage_pct,
                    f.path as covered_file
                """,
                changed_files=changed_files
            )
            return result.data()

    def _find_import_dependencies(self, changed_files: List[str]) -> List[Dict]:
        """Find tests in files that import changed files"""
        with self.db.driver.session(database=config.neo4j.database) as session:
            result = session.run(
                """
                MATCH (test_file:File)-[:IMPORTS]->(changed_file:File)
                WHERE changed_file.path IN $changed_files
                MATCH (test_file)-[:CONTAINS]->(t:Test)
                RETURN DISTINCT
                    t.id as test_id,
                    t.name as test_name,
                    t.file_path as test_file,
                    changed_file.path as imported_file
                """,
                changed_files=changed_files
            )
            return result.data()

    def get_impact_summary(self, repo_path: Path, changed_files: List[str]) -> Dict:
        """Get a summary of impact analysis"""
        impacted_tests = self.get_impacted_tests(repo_path, changed_files)

        # Categorize by impact score
        high_impact = [t for t in impacted_tests if t["impact_score"] >= 0.8]
        medium_impact = [t for t in impacted_tests if 0.5 <= t["impact_score"] < 0.8]
        low_impact = [t for t in impacted_tests if t["impact_score"] < 0.5]

        return {
            "total_impacted": len(impacted_tests),
            "high_impact": len(high_impact),
            "medium_impact": len(medium_impact),
            "low_impact": len(low_impact),
            "changed_files": len(changed_files),
            "recommendation": self._get_recommendation(impacted_tests)
        }

    def _get_recommendation(self, impacted_tests: List[Dict]) -> str:
        """Get recommendation based on impact analysis"""
        if not impacted_tests:
            return "No tests impacted. Safe to proceed, but consider adding tests."

        high_impact = [t for t in impacted_tests if t["impact_score"] >= 0.8]

        if len(high_impact) == 0:
            return "Low impact detected. Run all tests to be safe."
        elif len(high_impact) <= 10:
            return f"Run {len(high_impact)} high-impact tests before committing."
        else:
            return f"High impact: {len(high_impact)} tests affected. Run full test suite."

    def get_minimal_test_set(
        self,
        repo_path: Path,
        changed_files: List[str],
        max_tests: int = 50
    ) -> List[str]:
        """
        Get minimal set of tests to run for maximum coverage

        Returns list of test identifiers (file::test_name)
        """
        impacted_tests = self.get_impacted_tests(repo_path, changed_files)

        # Sort by impact score and take top N
        top_tests = sorted(
            impacted_tests,
            key=lambda t: t["impact_score"],
            reverse=True
        )[:max_tests]

        # Format as pytest identifiers
        test_identifiers = [
            f"{t['test_file']}::{t['test_name']}"
            for t in top_tests
        ]

        return test_identifiers
