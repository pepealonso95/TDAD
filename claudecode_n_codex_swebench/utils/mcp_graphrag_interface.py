"""
MCP GraphRAG Interface - Client for GraphRAG MCP Server

This interface provides a client to interact with the GraphRAG MCP server
for test impact analysis. It follows the pattern established by claude_interface.py.
"""
import logging
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class GraphRAGMCPInterface:
    """
    Client interface for GraphRAG MCP server

    Manages server lifecycle and provides high-level methods for:
    - Building code-test dependency graphs
    - Analyzing test impact from code changes
    - Running targeted tests
    """

    def __init__(self, server_url: str = "http://localhost:8080"):
        """
        Initialize MCP interface

        Args:
            server_url: URL of the MCP server
        """
        self.server_url = server_url
        self.server_process: Optional[subprocess.Popen] = None
        self._verify_server()

    def _verify_server(self):
        """Check if server is running, start if not"""
        try:
            response = requests.get(f"{self.server_url}/health", timeout=2)
            if response.status_code == 200:
                logger.info(f"GraphRAG MCP server is running at {self.server_url}")
                return
        except requests.RequestException:
            pass

        # Server not running, try to start it
        logger.info("GraphRAG MCP server not running, attempting to start...")
        self._start_server()

    def _start_server(self):
        """Start the MCP server"""
        try:
            # Path to server script
            server_script = Path(__file__).parent.parent / "mcp_server" / "server.py"

            if not server_script.exists():
                raise RuntimeError(f"Server script not found: {server_script}")

            # Start server process
            self.server_process = subprocess.Popen(
                ["python", str(server_script)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            # Wait for server to be ready
            logger.info("Waiting for server to start...")
            for i in range(60):  # Wait up to 60 seconds
                try:
                    response = requests.get(f"{self.server_url}/health", timeout=1)
                    if response.status_code == 200:
                        logger.info("GraphRAG MCP server started successfully")
                        return
                except requests.RequestException:
                    pass

                time.sleep(1)

            raise RuntimeError("Server failed to start within 60 seconds")

        except Exception as e:
            logger.error(f"Failed to start MCP server: {e}")
            raise

    def stop_server(self):
        """Stop the MCP server if it was started by this interface"""
        if self.server_process:
            logger.info("Stopping MCP server...")
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=10)
                logger.info("MCP server stopped")
            except subprocess.TimeoutExpired:
                logger.warning("Server did not stop gracefully, killing...")
                self.server_process.kill()
            self.server_process = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop_server()

    # ========================================================================
    # High-level API Methods
    # ========================================================================

    def build_graph(
        self,
        repo_path: str,
        force_rebuild: bool = False,
        include_tests: bool = True
    ) -> Dict:
        """
        Build code-test dependency graph for a repository

        Args:
            repo_path: Path to repository to index
            force_rebuild: Force full rebuild even if index exists
            include_tests: Include test file analysis

        Returns:
            Dict with build results
        """
        logger.info(f"Building graph for: {repo_path}")

        try:
            response = requests.post(
                f"{self.server_url}/tools/build_code_graph",
                json={
                    "repo_path": repo_path,
                    "force_rebuild": force_rebuild,
                    "include_tests": include_tests
                },
                timeout=600  # 10 minutes
            )

            response.raise_for_status()
            result = response.json()

            if result.get("success"):
                logger.info(f"Graph built: {result.get('nodes_created', 0)} nodes, "
                           f"{result.get('relationships_created', 0)} relationships")
            else:
                logger.error(f"Graph building failed: {result.get('error', 'Unknown error')}")

            return result

        except requests.RequestException as e:
            logger.error(f"Error calling build_graph: {e}")
            return {
                "success": False,
                "error": str(e),
                "nodes_created": 0,
                "relationships_created": 0
            }

    def incremental_update(
        self,
        repo_path: str,
        changed_files: Optional[List[str]] = None,
        base_commit: str = "HEAD"
    ) -> Dict:
        """
        Incrementally update graph based on changed files

        Args:
            repo_path: Path to repository
            changed_files: List of changed files (or use git diff)
            base_commit: Git commit to compare against

        Returns:
            Dict with update results
        """
        logger.info(f"Updating graph for: {repo_path}")

        try:
            response = requests.post(
                f"{self.server_url}/tools/incremental_update",
                json={
                    "repo_path": repo_path,
                    "changed_files": changed_files,
                    "base_commit": base_commit
                },
                timeout=300  # 5 minutes
            )

            response.raise_for_status()
            result = response.json()

            if result.get("success"):
                logger.info(f"Graph updated: {result.get('nodes_updated', 0)} nodes, "
                           f"{result.get('relationships_updated', 0)} relationships")
            else:
                logger.error(f"Graph update failed: {result.get('error', 'Unknown error')}")

            return result

        except requests.RequestException as e:
            logger.error(f"Error calling incremental_update: {e}")
            return {
                "success": False,
                "error": str(e),
                "nodes_updated": 0,
                "relationships_updated": 0
            }

    def get_impacted_tests(
        self,
        repo_path: str,
        changed_files: List[str],
        impact_threshold: float = 0.1
    ) -> Dict:
        """
        Get tests impacted by code changes

        Args:
            repo_path: Path to repository
            changed_files: List of changed file paths
            impact_threshold: Minimum impact score (0-1)

        Returns:
            Dict with impacted tests
        """
        logger.info(f"Finding impacted tests for {len(changed_files)} changed files")

        try:
            response = requests.post(
                f"{self.server_url}/tools/get_impacted_tests",
                json={
                    "repo_path": repo_path,
                    "changed_files": changed_files,
                    "impact_threshold": impact_threshold
                },
                timeout=60
            )

            response.raise_for_status()
            result = response.json()

            if result.get("success"):
                logger.info(f"Found {result.get('total_tests', 0)} impacted tests")
            else:
                logger.error(f"Impact analysis failed: {result.get('error', 'Unknown error')}")

            return result

        except requests.RequestException as e:
            logger.error(f"Error calling get_impacted_tests: {e}")
            return {
                "success": False,
                "error": str(e),
                "tests": [],
                "total_tests": 0
            }

    def run_tests(
        self,
        repo_path: str,
        tests: Optional[List[str]] = None,
        pytest_args: Optional[List[str]] = None
    ) -> Dict:
        """
        Run tests and get results

        Args:
            repo_path: Path to repository
            tests: List of test identifiers to run (None = all)
            pytest_args: Additional pytest arguments

        Returns:
            Dict with test results
        """
        test_spec = f"{len(tests)} tests" if tests else "all tests"
        logger.info(f"Running {test_spec} for: {repo_path}")

        try:
            response = requests.post(
                f"{self.server_url}/tools/run_tests",
                json={
                    "repo_path": repo_path,
                    "tests": tests,
                    "pytest_args": pytest_args or []
                },
                timeout=600  # 10 minutes
            )

            response.raise_for_status()
            result = response.json()

            if result.get("success"):
                logger.info(f"Tests completed: {result.get('passed', 0)} passed, "
                           f"{result.get('failed', 0)} failed, "
                           f"{result.get('regressions', 0)} regressions")
            else:
                logger.error(f"Test execution failed: {result.get('error', 'Unknown error')}")

            return result

        except requests.RequestException as e:
            logger.error(f"Error calling run_tests: {e}")
            return {
                "success": False,
                "error": str(e),
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "regressions": 0,
                "test_results": []
            }

    def get_stats(self) -> Dict:
        """
        Get graph statistics

        Returns:
            Dict with graph stats
        """
        try:
            response = requests.get(f"{self.server_url}/stats", timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Error getting stats: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    # ========================================================================
    # Convenience Methods
    # ========================================================================

    def analyze_and_run_impacted_tests(
        self,
        repo_path: str,
        changed_files: List[str],
        impact_threshold: float = 0.3,
        max_tests: int = 50
    ) -> Dict:
        """
        Analyze impact and run only the impacted tests

        This is the main workflow method that:
        1. Finds impacted tests
        2. Runs only those tests
        3. Reports regressions

        Args:
            repo_path: Path to repository
            changed_files: List of changed files
            impact_threshold: Minimum impact score
            max_tests: Maximum number of tests to run

        Returns:
            Dict with comprehensive results
        """
        logger.info(f"Analyzing impact and running tests for: {repo_path}")

        # Step 1: Get impacted tests
        impact_result = self.get_impacted_tests(repo_path, changed_files, impact_threshold)

        if not impact_result.get("success"):
            return {
                "success": False,
                "error": "Failed to analyze impact",
                "impact_result": impact_result
            }

        impacted_tests = impact_result.get("tests", [])

        if not impacted_tests:
            logger.info("No impacted tests found")
            return {
                "success": True,
                "impacted_tests": 0,
                "tests_run": 0,
                "passed": 0,
                "failed": 0,
                "regressions": 0,
                "message": "No tests impacted by changes"
            }

        # Step 2: Select top tests to run
        top_tests = sorted(impacted_tests, key=lambda t: t.get("impact_score", 0), reverse=True)[:max_tests]
        test_identifiers = [f"{t['test_file']}::{t['test_name']}" for t in top_tests]

        logger.info(f"Running {len(test_identifiers)} impacted tests")

        # Step 3: Run tests
        test_result = self.run_tests(repo_path, test_identifiers)

        return {
            "success": test_result.get("success", False),
            "impacted_tests": len(impacted_tests),
            "tests_run": len(test_identifiers),
            "passed": test_result.get("passed", 0),
            "failed": test_result.get("failed", 0),
            "skipped": test_result.get("skipped", 0),
            "regressions": test_result.get("regressions", 0),
            "impact_result": impact_result,
            "test_result": test_result
        }

    def clear_database(self) -> Dict:
        """
        Clear all data from the Neo4j database.

        This is useful for ensuring each experimental run starts with a clean state.
        Should be called at the beginning of a full benchmark run.

        Returns:
            Dict with operation results
        """
        logger.info("Clearing Neo4j database...")

        try:
            response = requests.post(
                f"{self.server_url}/tools/clear_database",
                timeout=60
            )

            response.raise_for_status()
            result = response.json()

            if result.get("success"):
                logger.info("Database cleared successfully")
            else:
                logger.error(f"Database clearing failed: {result.get('error', 'Unknown error')}")

            return result

        except requests.RequestException as e:
            logger.error(f"Error calling clear_database: {e}")
            return {
                "success": False,
                "error": str(e)
            }
