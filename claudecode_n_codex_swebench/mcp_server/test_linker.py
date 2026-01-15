"""
Test Linker - Links unit tests to source code

Uses multiple strategies:
1. Naming conventions (test_function_name -> function_name)
2. Coverage data (coverage.py results)
3. Static analysis (imports and calls from test files)
"""
import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .config import config
from .graph_db import get_db

logger = logging.getLogger(__name__)


class TestLinker:
    """Links tests to source code using multiple strategies"""

    def __init__(self):
        self.db = get_db()

    def link_tests(self, repo_path: Path) -> Dict:
        """Link all tests to source code"""
        logger.info(f"Linking tests to code for: {repo_path}")

        total_links = 0

        # Strategy 1: Naming conventions
        naming_links = self._link_by_naming_convention(repo_path)
        total_links += naming_links
        logger.info(f"Created {naming_links} links via naming conventions")

        # Strategy 2: Coverage data
        if config.analysis.use_coverage:
            coverage_links = self._link_by_coverage(repo_path)
            total_links += coverage_links
            logger.info(f"Created {coverage_links} links via coverage data")

        # Strategy 3: Static analysis
        static_links = self._link_by_static_analysis(repo_path)
        total_links += static_links
        logger.info(f"Created {static_links} links via static analysis")

        return {
            "total_links": total_links,
            "naming_convention": naming_links,
            "coverage": coverage_links if config.analysis.use_coverage else 0,
            "static_analysis": static_links
        }

    def _link_by_naming_convention(self, repo_path: Path) -> int:
        """Link tests to functions based on naming conventions"""
        links_created = 0

        # Get all test functions from graph
        with self.db.driver.session(database=config.neo4j.database) as session:
            result = session.run(
                """
                MATCH (t:Test)
                RETURN t.id as test_id, t.name as test_name, t.file_path as test_file
                """
            )
            tests = result.data()

        for test in tests:
            test_name = test["test_name"]
            test_id = test["test_id"]

            # Try to infer function name from test name
            # Common patterns:
            # test_function_name -> function_name
            # test_class_method -> Class.method
            # TestClass.test_method -> Class.method

            target_names = self._infer_target_names(test_name)

            for target_name in target_names:
                # Find matching functions
                with self.db.driver.session(database=config.neo4j.database) as session:
                    result = session.run(
                        """
                        MATCH (fn:Function)
                        WHERE fn.name = $target_name OR fn.name ENDS WITH '.' + $target_name
                        RETURN fn.id as function_id
                        LIMIT 1
                        """,
                        target_name=target_name
                    )

                    if result.peek():
                        function_id = result.single()["function_id"]
                        try:
                            self.db.create_tests_relationship(test_id, function_id, "Function", coverage=0.5)
                            links_created += 1
                            logger.debug(f"Linked test {test_name} -> {target_name}")
                        except Exception as e:
                            logger.debug(f"Could not create link: {e}")

        return links_created

    def _infer_target_names(self, test_name: str) -> List[str]:
        """Infer possible target function names from test name"""
        target_names = []

        # Pattern 1: test_function_name -> function_name
        if test_name.startswith("test_"):
            target_name = test_name[5:]  # Remove "test_" prefix
            target_names.append(target_name)

        # Pattern 2: test_class_method -> method
        parts = test_name.split("_")
        if len(parts) > 2 and parts[0] == "test":
            # Try each part as potential method name
            for i in range(1, len(parts)):
                target_names.append("_".join(parts[i:]))

        # Pattern 3: TestClass.test_method -> method
        if "." in test_name:
            parts = test_name.split(".")
            if len(parts) == 2:
                method_name = parts[1]
                if method_name.startswith("test_"):
                    target_names.append(method_name[5:])

        return target_names

    def _link_by_coverage(self, repo_path: Path) -> int:
        """Link tests to code using coverage.py data"""
        links_created = 0

        try:
            # Run coverage
            logger.info("Running pytest with coverage...")
            coverage_data = self._run_coverage(repo_path)

            if not coverage_data:
                logger.warning("No coverage data obtained")
                return 0

            # Parse coverage data and create links
            for test_id, covered_files in coverage_data.items():
                for file_path, coverage_pct in covered_files.items():
                    if coverage_pct >= config.analysis.coverage_threshold:
                        try:
                            self.db.create_depends_on_relationship(test_id, file_path, coverage_pct)
                            links_created += 1
                        except Exception as e:
                            logger.debug(f"Could not create coverage link: {e}")

        except Exception as e:
            logger.error(f"Error running coverage: {e}")

        return links_created

    def _run_coverage(self, repo_path: Path) -> Dict[str, Dict[str, float]]:
        """Run pytest with coverage and parse results"""
        coverage_file = repo_path / ".coverage"
        coverage_json = repo_path / "coverage.json"

        try:
            # Run pytest with coverage
            result = subprocess.run(
                [
                    "pytest",
                    "--cov=.",
                    "--cov-report=json",
                    f"--cov-report=json:{coverage_json}",
                    "-v"
                ],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=300
            )

            if result.returncode != 0:
                logger.warning(f"pytest exited with code {result.returncode}")

            # Parse coverage JSON
            if coverage_json.exists():
                with open(coverage_json, 'r') as f:
                    coverage_data = json.load(f)

                # Extract test-to-file coverage mapping
                # This is a simplified approach - real implementation would need
                # to map individual tests to their coverage
                test_coverage = {}

                # TODO: Implement proper per-test coverage mapping
                # For now, return empty dict
                return test_coverage

        except subprocess.TimeoutExpired:
            logger.error("Coverage run timed out")
        except Exception as e:
            logger.error(f"Error running coverage: {e}")

        return {}

    def _link_by_static_analysis(self, repo_path: Path) -> int:
        """Link tests to code by analyzing function calls from test files.

        Strategy: Find Test functions that CALL production Functions.
        Since Test nodes are created alongside Function nodes for test functions,
        we match them by name/file_path and trace CALLS relationships.
        """
        links_created = 0

        with self.db.driver.session(database=config.neo4j.database) as session:
            # Find Test functions that CALL production Functions
            # Test nodes share function_name and file_path with their Function nodes
            result = session.run(
                """
                MATCH (t:Test)
                MATCH (tf:Function)
                WHERE tf.name = t.function_name AND tf.file_path = t.file_path
                MATCH (tf)-[:CALLS]->(pf:Function)
                WHERE NOT pf.file_path CONTAINS 'test'
                RETURN DISTINCT t.id as test_id, pf.id as function_id, pf.name as function_name
                """
            )

            for record in result:
                try:
                    self.db.create_tests_relationship(
                        record["test_id"],
                        record["function_id"],
                        "Function",
                        coverage=0.8  # High confidence for direct calls
                    )
                    links_created += 1
                    logger.debug(f"Static link: {record['test_id']} -> {record['function_name']}")
                except Exception as e:
                    logger.debug(f"Could not create static link: {e}")

        return links_created


class TestRunner:
    """Runs tests and tracks results"""

    def __init__(self):
        self.db = get_db()

    def run_tests(
        self,
        repo_path: Path,
        tests: Optional[List[str]] = None,
        pytest_args: Optional[List[str]] = None
    ) -> Dict:
        """Run tests and return results"""
        logger.info(f"Running tests in: {repo_path}")

        if pytest_args is None:
            pytest_args = []

        # Build pytest command
        cmd = ["pytest", "-v", "--tb=short"]
        cmd.extend(pytest_args)

        if tests:
            # Run specific tests
            cmd.extend(tests)
            logger.info(f"Running {len(tests)} specific tests")
        else:
            logger.info("Running all tests")

        # Run tests
        try:
            result = subprocess.run(
                cmd,
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=600
            )

            # Parse results
            test_results = self._parse_pytest_output(result.stdout)

            passed = sum(1 for t in test_results if t["status"] == "passed")
            failed = sum(1 for t in test_results if t["status"] == "failed")
            skipped = sum(1 for t in test_results if t["status"] == "skipped")

            # TODO: Calculate regressions by comparing with previous results

            return {
                "success": result.returncode == 0,
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "regressions": 0,  # TODO: implement
                "test_results": test_results,
                "stdout": result.stdout,
                "stderr": result.stderr
            }

        except subprocess.TimeoutExpired:
            logger.error("Test run timed out")
            return {
                "success": False,
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "regressions": 0,
                "test_results": [],
                "error": "Timeout"
            }
        except Exception as e:
            logger.error(f"Error running tests: {e}")
            return {
                "success": False,
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "regressions": 0,
                "test_results": [],
                "error": str(e)
            }

    def _parse_pytest_output(self, output: str) -> List[Dict]:
        """Parse pytest output to extract test results"""
        test_results = []

        # Simple regex parsing (could be improved with pytest-json-report plugin)
        lines = output.splitlines()
        for line in lines:
            # Match lines like: "tests/test_foo.py::test_bar PASSED"
            match = re.match(r"^(.+?)::(test_\S+)\s+(PASSED|FAILED|SKIPPED)", line)
            if match:
                test_file, test_name, status = match.groups()
                test_results.append({
                    "file": test_file,
                    "name": test_name,
                    "status": status.lower(),
                    "full_name": f"{test_file}::{test_name}"
                })

        return test_results
