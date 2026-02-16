#!/usr/bin/env python3
"""
SWE-bench agent with GraphRAG-powered test impact analysis.

This extends the base CodeSWEAgent with GraphRAG capabilities for intelligent
test selection and regression prevention.
"""

import argparse
import json
import os
import sys
import subprocess
import tempfile
import shutil
import time
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path

from tqdm import tqdm
import jsonlines

from utils.claude_interface import ClaudeCodeInterface
from utils.codex_interface import CodexCodeInterface
from utils.qwen_interface import QwenCodeInterface
from utils.qwen_mini_interface import QwenMiniInterface
from utils.prompt_formatter import PromptFormatter
from utils.patch_extractor import PatchExtractor
from utils.model_registry import get_model_name
from utils.mcp_graphrag_interface import GraphRAGMCPInterface
from code_swe_agent import load_cached_dataset


DEFAULT_BACKEND = os.environ.get("CODE_SWE_BACKEND", "claude")
DEFAULT_GRAPHRAG_PROMPT = "prompts/swe_bench_graphrag.txt"


class GraphRAGCodeSWEAgent:
    """
    SWE-bench agent with GraphRAG test impact analysis.

    This agent extends the base functionality with:
    - Code-test dependency graph building
    - Intelligent test impact analysis
    - Targeted test execution
    - Regression tracking with graph context
    """

    def __init__(
        self,
        prompt_template: Optional[str] = None,
        model: Optional[str] = None,
        backend: str = DEFAULT_BACKEND,
        use_graphrag: bool = True,
        tdd_mode: bool = False,
        impact_threshold: float = 0.3,
        max_impacted_tests: int = 50,
        mcp_server_url: str = "http://localhost:8080"
    ):
        """
        Initialize GraphRAG-enhanced agent.

        Args:
            prompt_template: Path to prompt template (defaults to GraphRAG template)
            model: Model to use
            backend: Backend (claude or codex)
            use_graphrag: Enable GraphRAG features
            tdd_mode: Enable TDD-focused prompts (for Qwen backend)
            impact_threshold: Minimum impact score (0-1) for test selection
            max_impacted_tests: Maximum number of impacted tests to run
            mcp_server_url: MCP server URL (for external server)
        """
        self.backend = (backend or DEFAULT_BACKEND).lower()

        # Initialize backend interface
        if self.backend == "codex":
            self.interface = CodexCodeInterface()
        elif self.backend == "qwen":
            self.interface = QwenCodeInterface()
        elif self.backend == "qwen-mini":
            self.interface = QwenMiniInterface()
        else:
            self.backend = "claude"
            self.interface = ClaudeCodeInterface()

        # Use GraphRAG prompt template by default
        if prompt_template is None and use_graphrag:
            prompt_template = DEFAULT_GRAPHRAG_PROMPT

        self.prompt_formatter = PromptFormatter(prompt_template)
        self.patch_extractor = PatchExtractor()
        self.base_dir = Path.cwd()
        self.results_dir = self.base_dir / "results"
        self.predictions_dir = self.base_dir / "predictions"

        # Resolve model name from alias
        self.model = get_model_name(model, self.backend) if model else None
        self.model_alias = model  # Keep original alias for logging

        # GraphRAG configuration
        self.use_graphrag = use_graphrag
        self.tdd_mode = tdd_mode
        self.impact_threshold = impact_threshold
        self.max_impacted_tests = max_impacted_tests
        self.mcp: Optional[GraphRAGMCPInterface] = None
        self.graph_cache: Dict[str, bool] = {}  # Track built graphs by repo

        # Initialize MCP interface if using GraphRAG
        if self.use_graphrag:
            print(f"Initializing GraphRAG MCP server at {mcp_server_url}...")
            try:
                self.mcp = GraphRAGMCPInterface(server_url=mcp_server_url)
                print("GraphRAG MCP server ready")
            except Exception as e:
                print(f"Warning: Failed to initialize GraphRAG: {e}")
                print("Continuing without GraphRAG features...")
                self.use_graphrag = False

        # Create directories if they don't exist
        self.results_dir.mkdir(exist_ok=True)
        self.predictions_dir.mkdir(exist_ok=True)
        self.pred_timestamp: Optional[str] = None
        self.pred_file: Optional[Path] = None

    def setup_repository(self, instance: Dict) -> Optional[str]:
        """Set up a repository for testing."""
        instance_id = instance["instance_id"]
        repo_name = instance["repo"]
        base_commit = instance["base_commit"]

        # Create temporary directory for this instance (cross-platform)
        temp_dir = Path(tempfile.gettempdir()) / f"swe_bench_{instance_id}"

        try:
            # Remove if exists
            if temp_dir.exists():
                shutil.rmtree(temp_dir)

            # Save current directory
            original_dir = Path.cwd()

            # Clone repository
            print(f"Cloning {repo_name} to {temp_dir}")
            clone_url = f"https://github.com/{repo_name}.git"

            result = subprocess.run(
                ["git", "clone", clone_url, str(temp_dir)],
                capture_output=True,
                text=True,
                cwd=str(original_dir)  # Ensure we're in a valid directory
            )

            if result.returncode != 0:
                print(f"Failed to clone repository: {result.stderr}")
                return None

            # Checkout base commit
            os.chdir(temp_dir)
            result = subprocess.run(
                ["git", "checkout", base_commit],
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                print(f"Failed to checkout commit: {result.stderr}")
                os.chdir(str(original_dir))  # Return to original directory
                return None

            os.chdir(str(original_dir))  # Return to original directory
            return str(temp_dir)

        except Exception as e:
            print(f"Error setting up repository: {e}")
            # Try to return to original directory if possible
            try:
                os.chdir(str(original_dir))
            except Exception as chdir_error:
                print(f"Warning: Failed to return to original directory: {chdir_error}")
            return None

    def build_graph_for_repo(self, repo_path: str, repo_name: str, base_commit: str) -> Dict:
        """
        Build GraphRAG graph for a repository.

        Args:
            repo_path: Path to repository
            repo_name: Repository name for caching
            base_commit: Git commit hash for caching

        Returns:
            Dict with build results
        """
        if not self.use_graphrag or not self.mcp:
            return {"success": False, "error": "GraphRAG not enabled"}

        # Check cache using (repo_name, commit) tuple
        cache_key = f"{repo_name}@{base_commit}"
        if cache_key in self.graph_cache:
            print(f"Graph already built for {repo_name} at commit {base_commit[:8]}")
            return {"success": True, "cached": True}

        print(f"Building code-test dependency graph for {repo_name}...")
        start_time = time.time()

        try:
            result = self.mcp.build_graph(
                repo_path=repo_path,
                force_rebuild=False,
                include_tests=True
            )

            duration = time.time() - start_time

            if result.get("success"):
                self.graph_cache[cache_key] = True
                print(f"Graph built: {result.get('nodes_created', 0)} nodes, "
                     f"{result.get('relationships_created', 0)} edges "
                     f"in {duration:.1f}s")
                print(f"Cached graph for {cache_key}")
            else:
                print(f"Graph build failed: {result.get('error', 'Unknown error')}")

            return {
                **result,
                "build_time": duration
            }

        except Exception as e:
            print(f"Error building graph: {e}")
            return {
                "success": False,
                "error": str(e),
                "build_time": time.time() - start_time
            }

    def analyze_impact(self, repo_path: str, changed_files: List[str]) -> Dict:
        """
        Analyze test impact for changed files.

        Args:
            repo_path: Path to repository
            changed_files: List of changed file paths

        Returns:
            Dict with impact analysis results
        """
        if not self.use_graphrag or not self.mcp:
            return {"success": False, "tests": [], "total_tests": 0}

        print(f"Analyzing impact for {len(changed_files)} changed files...")
        start_time = time.time()

        try:
            result = self.mcp.get_impacted_tests(
                repo_path=repo_path,
                changed_files=changed_files,
                impact_threshold=self.impact_threshold
            )

            duration = time.time() - start_time

            if result.get("success"):
                total_tests = result.get("total_tests", 0)
                print(f"Found {total_tests} impacted tests in {duration:.2f}s")

                # Show impact breakdown
                if total_tests > 0:
                    tests = result.get("tests", [])
                    high_impact = sum(1 for t in tests if t.get("impact_score", 0) >= 0.8)
                    medium_impact = sum(1 for t in tests if 0.5 <= t.get("impact_score", 0) < 0.8)
                    low_impact = sum(1 for t in tests if t.get("impact_score", 0) < 0.5)
                    print(f"  - High impact: {high_impact}")
                    print(f"  - Medium impact: {medium_impact}")
                    print(f"  - Low impact: {low_impact}")
            else:
                print(f"Impact analysis failed: {result.get('error', 'Unknown error')}")

            return {
                **result,
                "analysis_time": duration
            }

        except Exception as e:
            print(f"Error analyzing impact: {e}")
            return {
                "success": False,
                "error": str(e),
                "tests": [],
                "total_tests": 0,
                "analysis_time": time.time() - start_time
            }

    def get_changed_files(self, repo_path: str) -> List[str]:
        """
        Get list of changed files using git diff.

        Args:
            repo_path: Path to repository

        Returns:
            List of changed file paths (RELATIVE to repo root)
        """
        try:
            original_dir = os.getcwd()
            os.chdir(repo_path)

            result = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"],
                capture_output=True,
                text=True
            )

            os.chdir(original_dir)

            if result.returncode == 0:
                # Git diff returns paths RELATIVE to repo root - keep them as-is!
                changed_files = [
                    line.strip()
                    for line in result.stdout.splitlines()
                    if line.strip() and line.strip().endswith('.py')
                ]
                return changed_files
            else:
                print(f"Warning: Could not get changed files: {result.stderr}")
                return []

        except Exception as e:
            print(f"Error getting changed files: {e}")
            return []

    def process_instance(self, instance: Dict) -> Dict:
        """Process a single SWE-bench instance with GraphRAG."""
        instance_id = instance["instance_id"]
        repo_name = instance["repo"]
        base_commit = instance["base_commit"]
        print(f"\n{'='*60}")
        print(f"Processing {instance_id}")
        print(f"Repository: {repo_name}")
        print(f"Commit: {base_commit[:8]}")
        print(f"{'='*60}")

        original_dir = os.getcwd()
        graphrag_metadata = {
            "use_graphrag": self.use_graphrag,
            "graph_built": False,
            "graph_build_time": 0,
            "impacted_tests_found": 0,
            "impact_analysis_time": 0,
            "changed_files": [],
            "test_efficiency_ratio": None
        }

        # qwen-mini handles repository setup internally and has integrated GraphRAG
        if self.backend == "qwen-mini":
            try:
                graphrag_suffix = " + GraphRAG" if self.use_graphrag else ""
                tdd_info = " (TDD mode)" if self.tdd_mode else ""
                print(f"Running Qwen-Mini{graphrag_suffix}{tdd_info}...")

                result = self.interface.execute_code_cli(
                    instance_id=instance["instance_id"],
                    problem_statement=instance["problem_statement"],
                    repo=instance["repo"],
                    base_commit=instance["base_commit"],
                    hints_text=instance.get("hints_text", ""),
                    tdd_mode=self.tdd_mode,
                    graphrag_enabled=self.use_graphrag,
                    graphrag_mcp=self.mcp if self.use_graphrag else None
                )

                if result.get("error"):
                    return {
                        "instance_id": instance_id,
                        "model": "qwen-mini-graphrag",
                        "prediction": "",
                        "error": result["error"],
                        "graphrag_metadata": graphrag_metadata
                    }

                return {
                    "instance_id": instance_id,
                    "model": "qwen-mini-graphrag",
                    "prediction": result.get("prediction", ""),
                    "graphrag_metadata": graphrag_metadata
                }
            except Exception as e:
                import traceback
                print(f"Error processing instance: {e}")
                print(f"Traceback: {traceback.format_exc()}")
                return {
                    "instance_id": instance_id,
                    "model": "qwen-mini-graphrag",
                    "prediction": "",
                    "error": str(e),
                    "graphrag_metadata": graphrag_metadata
                }

        repo_path = self.setup_repository(instance)
        if not repo_path:
            return {
                "instance_id": instance_id,
                "model": f"{self.backend}-code-graphrag",
                "prediction": "",
                "error": "Failed to set up repository",
                "graphrag_metadata": graphrag_metadata
            }

        try:
            # Step 1: Build graph if using GraphRAG
            if self.use_graphrag:
                graph_result = self.build_graph_for_repo(repo_path, repo_name, base_commit)
                graphrag_metadata["graph_built"] = graph_result.get("success", False)
                graphrag_metadata["graph_build_time"] = graph_result.get("build_time", 0)

            # Step 2: Format prompt and execute
            prompt = self.prompt_formatter.format_for_cli(instance)

            os.chdir(repo_path)
            subprocess.run(["git", "add", "-A"], capture_output=True)
            subprocess.run(["git", "stash"], capture_output=True)

            model_info = f" with model {self.model_alias}" if self.model else ""
            graphrag_suffix = " + GraphRAG" if self.use_graphrag else ""
            print(f"Running {self.backend.title()} Code{model_info}{graphrag_suffix}...")

            result = self.interface.execute_code_cli(prompt, repo_path, self.model, tdd_mode=self.tdd_mode)

            if not result["success"]:
                print(f"{self.backend.title()} Code execution failed: {result['stderr']}")
                os.chdir(original_dir)
                return {
                    "instance_id": instance_id,
                    "model": self.model_alias or f"{self.backend}-code-graphrag",
                    "prediction": "",
                    "error": f"Execution failed: {result['stderr']}",
                    "graphrag_metadata": graphrag_metadata
                }

            # Step 3: Analyze impact if GraphRAG is enabled
            if self.use_graphrag:
                changed_files = self.get_changed_files(repo_path)
                graphrag_metadata["changed_files"] = changed_files

                if changed_files:
                    impact_result = self.analyze_impact(repo_path, changed_files)
                    graphrag_metadata["impacted_tests_found"] = impact_result.get("total_tests", 0)
                    graphrag_metadata["impact_analysis_time"] = impact_result.get("analysis_time", 0)

                    # Store impact data
                    if impact_result.get("success"):
                        graphrag_metadata["impacted_tests"] = impact_result.get("tests", [])[:self.max_impacted_tests]

                        # Step 3.5: Iterative test-fix loop
                        max_fix_iterations = 3
                        iteration = 0
                        graphrag_metadata["iterations"] = 0
                        graphrag_metadata["final_test_result"] = None

                        while iteration < max_fix_iterations and changed_files:
                            iteration += 1
                            print(f"\n--- Iteration {iteration}: Running impacted tests ---")

                            test_result = self.mcp.run_impacted_tests_iteratively(
                                repo_path=repo_path,
                                changed_files=changed_files,
                                impact_threshold=self.impact_threshold,
                                max_tests=self.max_impacted_tests
                            )

                            graphrag_metadata["iterations"] = iteration
                            graphrag_metadata["final_test_result"] = {
                                "success": test_result.get("success"),
                                "passed": test_result.get("passed", 0),
                                "failed": test_result.get("failed", 0),
                                "tests_run": test_result.get("tests_run", 0)
                            }

                            if test_result.get("success"):
                                print(f"All {test_result.get('tests_run', 0)} impacted tests pass!")
                                break

                            failed_tests = test_result.get("failed_tests", [])
                            if not failed_tests:
                                print("Tests failed but no failure details available")
                                break

                            print(f"Failed tests: {len(failed_tests)}")
                            for ft in failed_tests[:5]:  # Show top 5
                                print(f"  - {ft.get('test_name')} (impact: {ft.get('impact_score', 0):.2f})")

                            if iteration >= max_fix_iterations:
                                print(f"Max iterations ({max_fix_iterations}) reached, some tests still failing")
                                break

                            # Format failure info for agent to fix
                            failure_prompt = self._format_test_failures_for_agent(
                                failed_tests, test_result, instance
                            )

                            print(f"\nAsking agent to fix {len(failed_tests)} failing tests...")

                            # Run agent again with failure context
                            fix_result = self.interface.execute_code_cli(failure_prompt, repo_path, self.model, tdd_mode=self.tdd_mode)

                            if not fix_result["success"]:
                                print("Agent failed to fix regressions")
                                break

                            # Get new changed files for next iteration
                            changed_files = self.get_changed_files(repo_path)
                            graphrag_metadata["changed_files"] = changed_files
                else:
                    print("No Python files changed")

            # Step 4: Extract and validate patch
            # Pass created_files so they can be staged for inclusion in diff
            created_files = result.get("created_files", [])
            patch = self.patch_extractor.extract_from_cli_output(result["stdout"], repo_path, created_files)

            is_valid, error = self.patch_extractor.validate_patch(patch)
            if not is_valid:
                print(f"Invalid patch: {error}")
                patch = ""

            prediction = self.patch_extractor.format_for_swebench(
                patch, instance_id, self.model_alias or f"{self.backend}-code-graphrag"
            )

            # Add GraphRAG metadata to prediction
            prediction["graphrag_metadata"] = graphrag_metadata

            # Step 5: Save results
            self._save_result(instance_id, result, patch, graphrag_metadata)

            return prediction

        except Exception as e:
            import traceback
            print(f"Error processing instance: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return {
                "instance_id": instance_id,
                "model": self.model_alias or f"{self.backend}-code-graphrag",
                "prediction": "",
                "error": str(e),
                "graphrag_metadata": graphrag_metadata
            }
        finally:
            try:
                os.chdir(original_dir)
            except Exception as e:
                print(f"Warning: Could not restore directory: {e}")

            if repo_path and os.path.exists(repo_path):
                shutil.rmtree(repo_path)

    def _save_result(self, instance_id: str, result: Dict, patch: str, graphrag_metadata: Dict):
        """Save detailed results for debugging."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        result_file = self.results_dir / f"{instance_id}_{timestamp}_graphrag.json"

        with open(result_file, 'w') as f:
            json.dump({
                "instance_id": instance_id,
                "timestamp": timestamp,
                "claude_output": result,
                "extracted_patch": patch,
                "graphrag_metadata": graphrag_metadata
            }, f, indent=2)

    def _format_test_failures_for_agent(
        self,
        failed_tests: List[Dict],
        test_result: Dict,
        instance: Dict
    ) -> str:
        """
        Format test failures into a prompt for the agent to fix regressions.

        Args:
            failed_tests: List of failed test details
            test_result: Full test result dict
            instance: Original SWE-bench instance

        Returns:
            Formatted prompt string for the agent
        """
        prompt = f"""REGRESSION DETECTED in {instance.get('repo', 'repository')}

The following tests are failing after your changes. You MUST fix these regressions
to complete the task successfully.

ORIGINAL ISSUE:
{instance.get('problem_statement', 'See original issue description.')}

FAILING TESTS:
"""
        for ft in failed_tests:
            impact_level = "HIGH - directly tests changed code" if ft.get('impact_score', 0) >= 0.8 else \
                          "MEDIUM - transitively affected" if ft.get('impact_score', 0) >= 0.5 else \
                          "LOW - indirectly related"
            prompt += f"""
Test: {ft.get('full_name', ft.get('test_name', 'Unknown'))}
File: {ft.get('test_file', 'Unknown')}
Impact: {ft.get('impact_score', 0):.2f} ({impact_level})
Error: {ft.get('error', 'No error message available')[:500]}
"""

        # Add truncated test output
        stdout = test_result.get('stdout', '')[:2000]
        if stdout:
            prompt += f"""
TEST OUTPUT (truncated):
{stdout}
"""

        prompt += """
INSTRUCTIONS:
1. Analyze why each test is failing
2. Fix the regression WITHOUT breaking your original fix for the issue
3. The goal is to make all tests pass while still solving the original problem
4. Focus on the high-impact tests first as they directly test the changed code

Remember: These tests passed before your changes, so you introduced a regression.
Make minimal changes to fix the tests while preserving your fix for the original issue.
"""
        return prompt

    def run_on_dataset(self, dataset_name: str, split: str = "test",
                      limit: Optional[int] = None) -> List[Dict]:
        """Run on a full dataset."""
        print(f"Loading dataset: {dataset_name}")
        dataset = load_cached_dataset(dataset_name, split=split, limit=limit)

        # Clear Neo4j database for fresh experimental run
        if self.use_graphrag and self.mcp:
            print("\n" + "="*60)
            print("Clearing Neo4j database for fresh experimental run...")
            print("="*60)
            clear_result = self.mcp.clear_database()
            if clear_result.get("success"):
                print("✓ Database cleared successfully")
            else:
                print(f"✗ Failed to clear database: {clear_result.get('error', 'Unknown error')}")
                print("  Continuing anyway, but results may be contaminated...")
            print()

        self.pred_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.pred_file = self.predictions_dir / f"predictions_graphrag_{self.pred_timestamp}.jsonl"
        if self.pred_file.exists():
            self.pred_file.unlink()
        json_file = self.predictions_dir / f"predictions_graphrag_{self.pred_timestamp}.json"
        if json_file.exists():
            json_file.unlink()

        predictions: List[Dict] = []

        for instance in tqdm(dataset, desc="Processing instances"):
            prediction = self.process_instance(instance)
            predictions.append(prediction)

            # Save prediction incrementally
            self._save_predictions(prediction)

        # Calculate aggregate GraphRAG stats
        self._print_graphrag_summary(predictions)

        with open(json_file, 'w') as f:
            json.dump(predictions, f, indent=2)

        print(f"\nSaved predictions to {self.pred_file}")
        return predictions

    def run_on_instance(self, instance_id: str, dataset_name: str = "princeton-nlp/SWE-bench_Lite") -> Dict:
        """Run on a single instance by ID."""
        dataset = load_cached_dataset(dataset_name, split="test", instance_id=instance_id)
        return self.process_instance(dataset[0])

    def _save_predictions(self, prediction: Dict):
        """Append a single prediction to the jsonl file."""
        if not self.pred_file:
            raise ValueError("Prediction timestamp not initialized. Call run_on_dataset first.")

        with jsonlines.open(self.pred_file, mode='a') as writer:
            writer.write(prediction)

    def _print_graphrag_summary(self, predictions: List[Dict]):
        """Print summary of GraphRAG performance."""
        if not self.use_graphrag:
            return

        print(f"\n{'='*60}")
        print("GraphRAG Performance Summary")
        print(f"{'='*60}")

        total_instances = len(predictions)
        graphs_built = sum(1 for p in predictions if p.get("graphrag_metadata", {}).get("graph_built", False))
        total_graph_time = sum(p.get("graphrag_metadata", {}).get("graph_build_time", 0) for p in predictions)
        total_analysis_time = sum(p.get("graphrag_metadata", {}).get("impact_analysis_time", 0) for p in predictions)
        total_impacted_tests = sum(p.get("graphrag_metadata", {}).get("impacted_tests_found", 0) for p in predictions)

        print(f"Total instances: {total_instances}")
        print(f"Graphs successfully built: {graphs_built}")
        print(f"Total graph build time: {total_graph_time:.1f}s")
        print(f"Average graph build time: {total_graph_time/max(graphs_built, 1):.1f}s")
        print(f"Total impact analysis time: {total_analysis_time:.1f}s")
        print(f"Average impact analysis time: {total_analysis_time/max(total_instances, 1):.2f}s")
        print(f"Total impacted tests identified: {total_impacted_tests}")
        print(f"Average impacted tests per instance: {total_impacted_tests/max(total_instances, 1):.1f}")
        print(f"{'='*60}\n")

    def cleanup(self):
        """Cleanup GraphRAG resources."""
        if self.mcp:
            print("Stopping GraphRAG MCP server...")
            self.mcp.stop_server()


def main():
    parser = argparse.ArgumentParser(description="Run code models on SWE-bench with GraphRAG")
    parser.add_argument("--dataset_name", type=str,
                       default="princeton-nlp/SWE-bench_Lite",
                       help="Dataset to use")
    parser.add_argument("--instance_id", type=str,
                       help="Run on a specific instance ID")
    parser.add_argument("--limit", type=int,
                       help="Limit number of instances to process")
    parser.add_argument("--prompt_template", type=str,
                       help="Path to custom prompt template")
    parser.add_argument("--model", type=str,
                       help="Model to use (e.g., opus-4.1, codex-4.2, or any name)")
    parser.add_argument("--backend", type=str, choices=["claude", "codex", "qwen", "qwen-mini"],
                       help="Code model backend to use (claude, codex, qwen, or qwen-mini)")
    parser.add_argument("--no-graphrag", action="store_true",
                       help="Disable GraphRAG features (use baseline TDD)")
    parser.add_argument("--tdd", action="store_true",
                       help="Enable TDD mode (test-first prompts, for Qwen backend)")
    parser.add_argument("--impact-threshold", type=float, default=0.3,
                       help="Minimum impact score for test selection (0-1)")
    parser.add_argument("--max-impacted-tests", type=int, default=50,
                       help="Maximum number of impacted tests to identify")
    parser.add_argument("--mcp-server-url", type=str, default="http://localhost:8080",
                       help="MCP server URL (if already running externally)")

    args = parser.parse_args()

    backend = args.backend or DEFAULT_BACKEND

    # Check if selected CLI is available
    cli_cmd = "codex" if backend == "codex" else "claude"
    try:
        result = subprocess.run([cli_cmd, "--version"], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Error: {cli_cmd} CLI not found. Please ensure '{cli_cmd}' is installed and in PATH")
            sys.exit(1)
    except FileNotFoundError:
        print(f"Error: {cli_cmd} CLI not found. Please ensure '{cli_cmd}' is installed and in PATH")
        sys.exit(1)

    agent = GraphRAGCodeSWEAgent(
        prompt_template=args.prompt_template,
        model=args.model,
        backend=backend,
        use_graphrag=not args.no_graphrag,
        tdd_mode=args.tdd,
        impact_threshold=args.impact_threshold,
        max_impacted_tests=args.max_impacted_tests,
        mcp_server_url=args.mcp_server_url
    )

    try:
        # Run on specific instance or dataset
        if args.instance_id:
            print(f"Running on instance: {args.instance_id}")
            prediction = agent.run_on_instance(args.instance_id, args.dataset_name)
            print(f"Prediction saved: {prediction}")
        else:
            print(f"Running on dataset: {args.dataset_name}")
            predictions = agent.run_on_dataset(args.dataset_name, limit=args.limit)
            print(f"Processed {len(predictions)} instances")
    finally:
        agent.cleanup()


if __name__ == "__main__":
    main()
