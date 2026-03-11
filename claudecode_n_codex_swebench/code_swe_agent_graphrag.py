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
from typing import Any, List, Dict, Optional
from pathlib import Path

from tqdm import tqdm
import jsonlines

from utils.claude_interface import ClaudeCodeInterface
from utils.codex_interface import CodexCodeInterface
from utils.qwen_interface import QwenCodeInterface
from utils.qwen_mini_interface import QwenMiniInterface
from utils.qwen_mini_interface_graphrag_tdd import QwenMiniInterfaceGraphRAGTDD
from utils.prompt_formatter import PromptFormatter
from utils.patch_extractor import PatchExtractor
from utils.model_registry import get_model_name
from utils.graphrag_interface import create_graphrag_interface
from utils.local_model_backend import set_local_backend_idle_if_owned
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
        mcp_server_url: str = "http://localhost:8080",
        graphrag_tool_mode: str = "local",
        graphrag_tdd_profile: bool = False,
        max_attempts: Optional[int] = None,
        step_limit: Optional[int] = None,
        loop_policy: Optional[str] = None,
        max_fix_iterations: Optional[int] = None,
        patch_compile_gate: Optional[bool] = None,
        test_signal_mode: Optional[str] = None,
        retry_policy: Optional[str] = None,
        enforce_tdd_test_first: Optional[bool] = None,
        graph_guard_mode: Optional[str] = None,
        strict_tdd_evidence: Optional[bool] = None,
        test_change_policy: Optional[str] = None,
        strict_tdd_infra_policy: Optional[str] = None,
        strict_tdd_infra_retry_budget: Optional[int] = None,
        indexed_signal_mode: Optional[str] = None,
        graph_refresh_policy: Optional[str] = None,
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
            mcp_server_url: MCP server URL (only used when graphrag_tool_mode=mcp)
            graphrag_tool_mode: GraphRAG transport mode (local|mcp|auto)
        """
        self.backend = (backend or DEFAULT_BACKEND).lower()
        self.use_graphrag = use_graphrag
        self.tdd_mode = tdd_mode
        self.graphrag_tdd_profile = graphrag_tdd_profile

        # Initialize backend interface
        if self.backend == "codex":
            self.interface = CodexCodeInterface()
        elif self.backend == "qwen":
            self.interface = QwenCodeInterface()
        elif self.backend == "qwen-mini":
            if self.use_graphrag and self.tdd_mode and self.graphrag_tdd_profile:
                self.interface = QwenMiniInterfaceGraphRAGTDD()
            else:
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
        if self.backend == "qwen-mini" and hasattr(self.interface, "set_model_name"):
            self.interface.set_model_name(self.model)

        # GraphRAG configuration
        self.impact_threshold = impact_threshold
        self.max_impacted_tests = max_impacted_tests
        self.mcp: Optional[Any] = None
        self.graph_cache: Dict[str, bool] = {}  # Track built graphs by repo
        self.graphrag_tool_mode = str(
            graphrag_tool_mode
            or os.getenv("GRAPH_RAG_TOOL_MODE", "local")
        ).strip().lower()
        self.max_attempts = max_attempts
        self.step_limit = step_limit
        self.loop_policy = loop_policy
        self.max_fix_iterations = max_fix_iterations
        self.patch_compile_gate = patch_compile_gate
        self.test_signal_mode = test_signal_mode
        self.retry_policy = retry_policy
        self.enforce_tdd_test_first = enforce_tdd_test_first
        self.graph_guard_mode = graph_guard_mode
        self.strict_tdd_evidence = strict_tdd_evidence
        self.test_change_policy = test_change_policy
        self.strict_tdd_infra_policy = strict_tdd_infra_policy
        self.strict_tdd_infra_retry_budget = strict_tdd_infra_retry_budget
        self.indexed_signal_mode = indexed_signal_mode
        self.graph_refresh_policy = graph_refresh_policy

        if self.backend == "qwen-mini":
            if self.max_attempts is not None:
                self.interface.max_attempts = self.max_attempts
            if self.step_limit is not None:
                self.interface.step_limit = self.step_limit
            if self.loop_policy is not None:
                self.interface.loop_policy = self.loop_policy
            if self.max_fix_iterations is not None:
                self.interface.max_fix_iterations = self.max_fix_iterations
            if self.patch_compile_gate is not None:
                self.interface.patch_compile_gate = self.patch_compile_gate
            if self.test_signal_mode is not None:
                self.interface.test_signal_mode = self.test_signal_mode
            if self.retry_policy is not None:
                self.interface.retry_policy = self.retry_policy
            if self.enforce_tdd_test_first is not None:
                self.interface.enforce_tdd_test_first = self.enforce_tdd_test_first
            if self.graph_guard_mode is not None:
                self.interface.graph_guard_mode = self.graph_guard_mode
            if self.strict_tdd_evidence is not None:
                self.interface.strict_tdd_evidence = self.strict_tdd_evidence
            if self.test_change_policy is not None:
                self.interface.test_change_policy = self.test_change_policy
            if self.strict_tdd_infra_policy is not None:
                self.interface.strict_tdd_infra_policy = self.strict_tdd_infra_policy
            if self.strict_tdd_infra_retry_budget is not None:
                self.interface.strict_tdd_infra_retry_budget = self.strict_tdd_infra_retry_budget
            if self.indexed_signal_mode is not None:
                self.interface.indexed_signal_mode = self.indexed_signal_mode
            if self.graph_refresh_policy is not None:
                self.interface.graph_refresh_policy = self.graph_refresh_policy

        # Initialize GraphRAG interface if using GraphRAG
        if self.use_graphrag:
            print(
                f"Initializing GraphRAG tool "
                f"(mode={self.graphrag_tool_mode}, server_url={mcp_server_url})..."
            )
            try:
                self.mcp = create_graphrag_interface(
                    mode=self.graphrag_tool_mode,
                    server_url=mcp_server_url,
                )
                mode_effective = getattr(self.mcp, "transport_mode", self.graphrag_tool_mode)
                print(f"GraphRAG tool ready (mode={mode_effective})")
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
                include_tests=True,
                repo_slug=repo_name,
                commit_sha=base_commit,
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
        Get list of changed files using git diff plus untracked files.

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
            untracked_result = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard"],
                capture_output=True,
                text=True
            )

            os.chdir(original_dir)

            if result.returncode == 0:
                # Git diff returns paths RELATIVE to repo root - keep them as-is!
                changed_files_raw = [line.strip() for line in result.stdout.splitlines() if line.strip()]
                if untracked_result.returncode == 0:
                    changed_files_raw.extend(
                        [line.strip() for line in untracked_result.stdout.splitlines() if line.strip()]
                    )
                # Deduplicate preserving order, keep Python files only.
                seen = set()
                changed_files = []
                for path in changed_files_raw:
                    if path.endswith(".py") and path not in seen:
                        seen.add(path)
                        changed_files.append(path)
                return changed_files
            else:
                print(f"Warning: Could not get changed files: {result.stderr}")
                return []

        except Exception as e:
            print(f"Error getting changed files: {e}")
            return []

    def recover_timeout_prediction(self, instance_id: str, worker_pid: int) -> Optional[Dict]:
        """Recover best-effort prediction from interface timeout checkpoint, when supported."""
        recover_fn = getattr(self.interface, "recover_timeout_prediction", None)
        if not callable(recover_fn):
            return None
        try:
            recovered = recover_fn(instance_id=instance_id, worker_pid=worker_pid)
        except TypeError:
            recovered = recover_fn(instance_id, worker_pid)
        if not isinstance(recovered, dict):
            return None
        # Preserve GraphRAG model label in recovered payload.
        recovered.setdefault("model", "qwen-mini-graphrag")
        return recovered

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
                backend_label = getattr(self.interface, "describe_local_backend", lambda: "local LLM")()
                print(f"Running Qwen-Mini ({backend_label}){graphrag_suffix}{tdd_info}...")
                fail_to_pass_tests = self._parse_test_list(instance.get("FAIL_TO_PASS"))
                pass_to_pass_tests = self._parse_test_list(instance.get("PASS_TO_PASS"))

                result = self.interface.execute_code_cli(
                    instance_id=instance["instance_id"],
                    problem_statement=instance["problem_statement"],
                    repo=instance["repo"],
                    base_commit=instance["base_commit"],
                    hints_text=instance.get("hints_text", ""),
                    tdd_mode=self.tdd_mode,
                    graphrag_enabled=self.use_graphrag,
                    graphrag_mcp=self.mcp if self.use_graphrag else None,
                    fail_to_pass_tests=fail_to_pass_tests,
                    pass_to_pass_tests=pass_to_pass_tests,
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
                    "graphrag_metadata": {
                        **graphrag_metadata,
                        **result.get("graphrag_metadata", {}),
                    },
                    "attempts_used": result.get("attempts_used"),
                    "loop_abort_reason": result.get("loop_abort_reason"),
                    "f2p_pass_rate": result.get("f2p_pass_rate"),
                    "f2p_reliable": result.get("f2p_reliable"),
                    "f2p_runtime_strategy": result.get("f2p_runtime_strategy", ""),
                    "f2p_runtime_fallback_used": result.get("f2p_runtime_fallback_used", ""),
                    "f2p_runtime_unreliable_reason": result.get("f2p_runtime_unreliable_reason", ""),
                    "p2p_smoke_failures": result.get("p2p_smoke_failures"),
                    "p2p_reliable": result.get("p2p_reliable"),
                    "p2p_runtime_strategy": result.get("p2p_runtime_strategy", ""),
                    "p2p_runtime_fallback_used": result.get("p2p_runtime_fallback_used", ""),
                    "p2p_runtime_unreliable_reason": result.get("p2p_runtime_unreliable_reason", ""),
                    "test_signal_reliable": result.get("test_signal_reliable"),
                    "clean_resolution": result.get("clean_resolution"),
                    "patch_gate_valid": result.get("patch_gate_valid"),
                    "patch_gate_reason": result.get("patch_gate_reason"),
                    "patch_gate_severity": result.get("patch_gate_severity"),
                    "changed_lines_total": result.get("changed_lines_total"),
                    "graph_guard_mode": result.get("graph_guard_mode"),
                    "graph_guard_passed": result.get("graph_guard_passed"),
                    "graph_guard_raw_passed": result.get("graph_guard_raw_passed"),
                    "graph_guard_reason": result.get("graph_guard_reason"),
                    "graph_guard_signal_shape": result.get("graph_guard_signal_shape"),
                    "graph_guard_used_either": result.get("graph_guard_used_either"),
                    "graph_guard_used_both": result.get("graph_guard_used_both"),
                    "graph_guard_bypassed_unreliable_runtime": result.get(
                        "graph_guard_bypassed_unreliable_runtime",
                    ),
                    "test_files_changed": result.get("test_files_changed", []),
                    "indexed_search_attempted": result.get("indexed_search_attempted"),
                    "indexed_search_success": result.get("indexed_search_success"),
                    "indexed_query_success": result.get("indexed_query_success"),
                    "graph_useful_signal": result.get("graph_useful_signal", False),
                    "graph_fallback_reason": result.get("graph_fallback_reason", ""),
                    "impacted_selected_count": result.get("impacted_selected_count", 0),
                    "impacted_runnable_count": result.get("impacted_runnable_count", 0),
                    "impacted_runnable_ratio": result.get("impacted_runnable_ratio", 0.0),
                    "impacted_precision_score": result.get("impacted_precision_score", 0.0),
                    "impacted_precision_floor_passed": result.get(
                        "impacted_precision_floor_passed",
                        False,
                    ),
                    "impact_empty_reason": result.get("impact_empty_reason", ""),
                    "repo_test_changed": result.get("repo_test_changed"),
                    "runtime_reliable_for_test_contract": result.get(
                        "runtime_reliable_for_test_contract",
                    ),
                    "test_change_required": result.get("test_change_required"),
                    "test_change_enforcement": result.get("test_change_enforcement", ""),
                    "repro_cmd": result.get("repro_cmd", ""),
                    "repro_failed_count": result.get("repro_failed_count"),
                    "repro_total": result.get("repro_total"),
                    "repro_runtime_strategy": result.get("repro_runtime_strategy", ""),
                    "repro_runtime_fallback_used": result.get("repro_runtime_fallback_used", ""),
                    "repro_runtime_unreliable_reason": result.get("repro_runtime_unreliable_reason", ""),
                    "repro_cmd_present": result.get("repro_cmd_present"),
                    "repro_failed_before_edit": result.get("repro_failed_before_edit"),
                    "verify_cmd": result.get("verify_cmd", ""),
                    "verify_cmd_present": result.get("verify_cmd_present"),
                    "verify_pass_after_edit": result.get("verify_pass_after_edit"),
                    "smoke_cmd": result.get("smoke_cmd", ""),
                    "smoke_cmd_present": result.get("smoke_cmd_present"),
                    "smoke_pass_after_edit": result.get("smoke_pass_after_edit"),
                    "tdd_evidence_complete": result.get("tdd_evidence_complete"),
                    "tdd_evidence_reason": result.get("tdd_evidence_reason"),
                    "tdd_fail_open_applied": result.get("tdd_fail_open_applied"),
                    "tdd_infra_reasons": result.get("tdd_infra_reasons", []),
                    "prompt_trace_id": result.get("prompt_trace_id", ""),
                    "prompt_budget_chars": result.get("prompt_budget_chars"),
                    "prompt_chars_before": result.get("prompt_chars_before"),
                    "prompt_chars_after": result.get("prompt_chars_after"),
                    "prompt_estimated_tokens_before": result.get("prompt_estimated_tokens_before"),
                    "prompt_estimated_tokens_after": result.get("prompt_estimated_tokens_after"),
                    "prompt_section_sizes_before": result.get("prompt_section_sizes_before", {}),
                    "prompt_section_sizes_after": result.get("prompt_section_sizes_after", {}),
                    "prompt_trimmed": result.get("prompt_trimmed"),
                    "prompt_trimmed_sections": result.get("prompt_trimmed_sections", []),
                    "mlx_backend_ready": result.get("mlx_backend_ready"),
                    "mlx_backend_started_now": result.get("mlx_backend_started_now"),
                    "mlx_backend_reused_existing": result.get("mlx_backend_reused_existing"),
                    "mlx_backend_before": result.get("mlx_backend_before", {}),
                    "mlx_backend_after": result.get("mlx_backend_after", {}),
                    "mlx_backend_crash_detected": result.get("mlx_backend_crash_detected"),
                    "mlx_backend_restarted": result.get("mlx_backend_restarted"),
                    "mlx_backend_failure_reason": result.get("mlx_backend_failure_reason", ""),
                    "required_test_added": result.get("required_test_added"),
                    "infra_mode_effective": result.get("infra_mode_effective", ""),
                    "tdd_contract_stage": result.get("tdd_contract_stage", ""),
                    "attempt_summaries": result.get("attempt_summaries", []),
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

    @staticmethod
    def _parse_test_list(raw_value) -> List[str]:
        if raw_value is None:
            return []
        if isinstance(raw_value, list):
            return [str(x) for x in raw_value if str(x).strip()]
        if isinstance(raw_value, str):
            raw_value = raw_value.strip()
            if not raw_value:
                return []
            try:
                parsed = json.loads(raw_value)
                if isinstance(parsed, list):
                    return [str(x) for x in parsed if str(x).strip()]
            except json.JSONDecodeError:
                return []
        return []

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
            mode_effective = getattr(self.mcp, "transport_mode", self.graphrag_tool_mode)
            print(f"Stopping GraphRAG tool (mode={mode_effective})...")
            self.mcp.stop_server()
        local_backend = getattr(self.interface, "local_backend", None)
        if local_backend is not None and self.backend == "qwen-mini":
            set_local_backend_idle_if_owned(local_backend, prefix="QWEN_MINI")


def main():
    raw_argv = sys.argv[1:]
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
    parser.add_argument(
        "--graphrag-tool-mode",
        type=str,
        choices=["local", "mcp", "auto"],
        default=os.getenv("GRAPH_RAG_TOOL_MODE", "local"),
        help="GraphRAG transport mode (default: local, use mcp for external server)",
    )
    parser.add_argument("--patch-compile-gate", type=str, choices=["on", "off"],
                       help="Enable/disable compile gate before accepting qwen-mini patches")
    parser.add_argument("--graphrag-tdd-profile", type=str, choices=["on", "off"], default="on",
                       help="Enable GraphRAG-aware qwen-mini TDD profile defaults (default: on)")
    parser.add_argument("--max-attempts", type=int,
                       help="Max attempts per instance for qwen-mini")
    parser.add_argument("--step-limit", type=int,
                       help="Max steps per attempt for qwen-mini")
    parser.add_argument("--loop-policy", type=str, choices=["off", "warn", "strict"],
                       help="Loop control policy for qwen-mini")
    parser.add_argument("--max-fix-iterations", type=int,
                       help="Max test-fix iterations for qwen-mini TDD/GraphRAG loops")
    parser.add_argument("--test-signal-mode", type=str, choices=["off", "soft", "hard"],
                       help="How local F2P/P2P checks influence attempt ranking")
    parser.add_argument("--retry-policy", type=str, choices=["fixed", "adaptive"],
                       help="Retry strategy for qwen-mini attempts")
    parser.add_argument("--enforce-tdd-test-first", type=str, choices=["on", "off"],
                       help="Require strict test-first appendix in qwen-mini TDD mode")
    parser.add_argument("--graph-guard-mode", type=str, choices=["either", "both", "indexed_only"],
                       help="GraphRAG candidate guard mode")
    parser.add_argument("--strict-tdd-evidence", type=str, choices=["on", "off"],
                       help="Require strict reproduce->verify->smoke evidence for TDD candidates")
    parser.add_argument("--test-change-policy", type=str, choices=["any_test_like", "repo_tests_only"],
                       help="Policy for counting unit-test file changes in graph guard")
    parser.add_argument("--strict-tdd-infra-policy", type=str, choices=["fail_closed", "retry_then_fail_open", "fail_open"],
                       help="Policy for strict TDD evidence when pytest signal is infra-unreliable (supports fail_open)")
    parser.add_argument("--strict-tdd-infra-retry-budget", type=int,
                       help="Extra retry budget for infra-unreliable strict TDD pytest checks")
    parser.add_argument("--indexed-signal-mode", type=str, choices=["attempted_query", "successful_query"],
                       help="How indexed-search usage is counted for graph guard")

    args = parser.parse_args()

    backend = args.backend or DEFAULT_BACKEND

    # Check external CLI only for backends that depend on it.
    if backend not in ["qwen", "qwen-mini"]:
        cli_cmd = "codex" if backend == "codex" else "claude"
        try:
            result = subprocess.run([cli_cmd, "--version"], capture_output=True, text=True)
            if result.returncode != 0:
                print(f"Error: {cli_cmd} CLI not found. Please ensure '{cli_cmd}' is installed and in PATH")
                sys.exit(1)
        except FileNotFoundError:
            print(f"Error: {cli_cmd} CLI not found. Please ensure '{cli_cmd}' is installed and in PATH")
            sys.exit(1)

    test_signal_mode_explicit = "--test-signal-mode" in raw_argv
    retry_policy_explicit = "--retry-policy" in raw_argv
    enforce_tdd_test_first_explicit = "--enforce-tdd-test-first" in raw_argv
    graph_guard_mode_explicit = "--graph-guard-mode" in raw_argv
    strict_tdd_evidence_explicit = "--strict-tdd-evidence" in raw_argv
    test_change_policy_explicit = "--test-change-policy" in raw_argv
    strict_tdd_infra_policy_explicit = "--strict-tdd-infra-policy" in raw_argv
    strict_tdd_infra_retry_budget_explicit = "--strict-tdd-infra-retry-budget" in raw_argv
    indexed_signal_mode_explicit = "--indexed-signal-mode" in raw_argv
    step_limit_explicit = "--step-limit" in raw_argv
    max_fix_iterations_explicit = "--max-fix-iterations" in raw_argv

    # Keep standalone CLI behavior aligned with benchmark graph profile defaults
    # unless explicitly overridden.
    use_graph_profile = (
        args.graphrag_tdd_profile == "on"
        and backend == "qwen-mini"
        and args.tdd
        and not args.no_graphrag
    )
    effective_step_limit = args.step_limit
    effective_max_fix_iterations = args.max_fix_iterations
    effective_test_signal_mode = args.test_signal_mode
    effective_retry_policy = args.retry_policy
    effective_enforce_tdd_test_first = args.enforce_tdd_test_first
    effective_graph_guard_mode = args.graph_guard_mode
    effective_strict_tdd_evidence = args.strict_tdd_evidence
    effective_test_change_policy = args.test_change_policy
    effective_strict_tdd_infra_policy = args.strict_tdd_infra_policy
    effective_strict_tdd_infra_retry_budget = args.strict_tdd_infra_retry_budget
    effective_indexed_signal_mode = args.indexed_signal_mode
    if use_graph_profile and not step_limit_explicit:
        effective_step_limit = 40
    if use_graph_profile and not max_fix_iterations_explicit:
        effective_max_fix_iterations = 1
    if use_graph_profile and not test_signal_mode_explicit:
        effective_test_signal_mode = "soft"
    if use_graph_profile and not retry_policy_explicit:
        effective_retry_policy = "adaptive"
    if use_graph_profile and not enforce_tdd_test_first_explicit:
        effective_enforce_tdd_test_first = "off"
    if use_graph_profile and not graph_guard_mode_explicit:
        effective_graph_guard_mode = "either"
    if use_graph_profile and not strict_tdd_evidence_explicit:
        effective_strict_tdd_evidence = "on"
    if use_graph_profile and not test_change_policy_explicit:
        effective_test_change_policy = "repo_tests_only"
    if use_graph_profile and not strict_tdd_infra_policy_explicit:
        effective_strict_tdd_infra_policy = "fail_open"
    if use_graph_profile and not strict_tdd_infra_retry_budget_explicit:
        effective_strict_tdd_infra_retry_budget = 2
    if use_graph_profile and not indexed_signal_mode_explicit:
        effective_indexed_signal_mode = "successful_query"

    agent = GraphRAGCodeSWEAgent(
        prompt_template=args.prompt_template,
        model=args.model,
        backend=backend,
        use_graphrag=not args.no_graphrag,
        tdd_mode=args.tdd,
        impact_threshold=args.impact_threshold,
        max_impacted_tests=args.max_impacted_tests,
        mcp_server_url=args.mcp_server_url,
        graphrag_tool_mode=args.graphrag_tool_mode,
        graphrag_tdd_profile=(args.graphrag_tdd_profile == "on"),
        max_attempts=args.max_attempts,
        step_limit=effective_step_limit,
        loop_policy=args.loop_policy,
        max_fix_iterations=effective_max_fix_iterations,
        patch_compile_gate=(None if args.patch_compile_gate is None else args.patch_compile_gate == "on"),
        test_signal_mode=effective_test_signal_mode,
        retry_policy=effective_retry_policy,
        enforce_tdd_test_first=(
            None if effective_enforce_tdd_test_first is None
            else effective_enforce_tdd_test_first == "on"
        ),
        graph_guard_mode=effective_graph_guard_mode,
        strict_tdd_evidence=(
            None if effective_strict_tdd_evidence is None
            else effective_strict_tdd_evidence == "on"
        ),
        test_change_policy=effective_test_change_policy,
        strict_tdd_infra_policy=effective_strict_tdd_infra_policy,
        strict_tdd_infra_retry_budget=effective_strict_tdd_infra_retry_budget,
        indexed_signal_mode=effective_indexed_signal_mode,
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
