#!/usr/bin/env python3
"""QwenMiniInterface: mini-swe-agent adapter with local llama.cpp GraphRAG support.

Uses mini-swe-agent's battle-tested default templates (74% SWE-bench Verified)
with a local OpenAI-compatible llama.cpp server by default.
"""

import os
import sys
import time
import tempfile
import subprocess
import shutil
import re
import hashlib
import signal
import shlex
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .local_model_backend import (
    describe_local_backend_runtime,
    ensure_local_backend_ready,
    resolve_qwen_local_backend,
)
from .test_runtime_manager import TestRuntimeManager

# Add mini-swe-agent to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "mini_swe_agent_fork" / "src"))

from minisweagent.models import get_model
from minisweagent.environments import get_environment
from minisweagent.agents.default import DefaultAgent, FormatError

# --------------------------------------------------------------------------- #
# Mini-swe-agent default templates (from config/default.yaml)                  #
# These scored 74% on SWE-bench Verified — do NOT simplify them.              #
# --------------------------------------------------------------------------- #

SYSTEM_TEMPLATE = """\
You are a helpful assistant that can interact with a computer.

Your response must contain exactly ONE bash code block with ONE command (or commands connected with && or ||).
Include a THOUGHT section before your command where you explain your reasoning process.
Format your response as shown in <format_example>.

<format_example>
Your reasoning and analysis here. Explain why you want to perform the action.

```bash
your_command_here
```
</format_example>

After each command result, briefly reflect on what you learned and whether it moved you closer to solving the issue.
Keep iterating until you have verified the fix works. Do not submit prematurely.

Failure to follow these rules will cause your response to be rejected.
"""

INSTANCE_TEMPLATE = """\
Please solve this issue: {{task}}

You can execute bash commands and edit files to implement the necessary changes.

## Quality Requirements (Critical)

1. Minimal Scope: ONLY modify files directly related to the failing behavior.
2. No Public API Changes: Avoid changing public function or class signatures.
3. Test First: Reproduce the issue before editing code.
4. Targeted Fixes: Prefer the smallest change that resolves the issue.
5. No Repetition: If an edit command fails repeatedly, switch strategy.
6. Self-Check Before Submit:
   - No accidental signature changes
   - No duplicated code blocks
   - No placeholder/incomplete code

## Critical: Working Directory and File Location

<important>
- Your current working directory IS the cloned repository. Use `pwd` to confirm.
- NEVER hardcode paths like `/Users/runner/...` or `/opt/miniconda3/...`.
- NEVER try `python3 -c "import <package>"` — the package is unbuilt source code, not installed.
- To find files: `grep -r "pattern" . --include="*.py" -l`
- To read source: use `cat`, `head`, or `sed -n 'START,ENDp'` directly.
- Start with `ls` and `find . -type f -name "*.py" | head -20`.
</important>

## Recommended Workflow

This workflows should be done step-by-step so that you can iterate on your changes and any possible problems.

1. Run pwd and ls to orient yourself. Use grep -r "keyword" . --include="*.py" -l to find relevant files. NEVER import the package.
2. Prefer the provided failing repo test as the repro. Avoid creating new top-level repro scripts.
3. Edit the source code to resolve the issue
4. Verify your fix with targeted pytest or py_compile commands
5. Test edge cases to ensure your fix is robust
6. Submit your changes and finish your work by issuing the following command: `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`.
   Do not combine it with any other command. <important>After this command, you cannot continue working on this task.</important>

## Important Rules

1. Every response must contain exactly one action
2. The action must be enclosed in triple backticks
3. Directory or environment variable changes are not persistent. Every action is executed in a new subshell.
   However, you can prefix any action with `MY_ENV_VAR=MY_VALUE cd /path/to/working/dir && ...` or write/load environment variables from files

<system_information>
{{system}} {{release}} {{version}} {{machine}}
</system_information>

## Formatting your response

Here is an example of a correct response:

<example_response>
THOUGHT: I need to understand the structure of the repository first. Let me check what files are in the current directory to get a better understanding of the codebase.

```bash
ls -la
```
</example_response>

## Common Pitfalls

- NEVER import the package (`python3 -c "import ..."`) — it is unbuilt source. Use cat/grep.
- When failing repo tests are already known, do NOT create top-level repro/debug scripts before the first edit.
- NEVER search in /opt/, /usr/lib/, or site-packages/ — the code is in the current directory.
- If a command fails, try a DIFFERENT approach instead of repeating it.

## Editing Files

Prefer `python3 - <<'PY' ... PY` pathlib edits for multi-line changes. Use `python3 -c ...` only for tiny single-string replacements.
{% if system == "Darwin" -%}
For sed on MacOS: `sed -i '' 's/old/new/g' file.py` (note space after -i). Use sed only for exact anchor-based substitutions you just inspected.
{% else -%}
For sed: `sed -i 's/old/new/g' file.py`. Use sed only for exact anchor-based substitutions you just inspected.
{% endif -%}
View lines: `nl -ba file.py | sed -n '10,20p'`
"""

ACTION_OBSERVATION_TEMPLATE = """\
<returncode>{{output.returncode}}</returncode>
{% if output.output | length < 10000 -%}
<output>
{{ output.output -}}
</output>
{%- else -%}
<warning>
The output of your last command was too long.
Please try a different command that produces less output.
If you're looking at a file you can try use head, tail or sed to view a smaller number of lines selectively.
If you're using grep or find and it produced too much output, you can use a more selective search pattern.
If you really need to see something from the full command's output, you can redirect output to a file and then search in that file.
</warning>
{%- set elided_chars = output.output | length - 10000 -%}
<output_head>
{{ output.output[:5000] }}
</output_head>
<elided_chars>
{{ elided_chars }} characters elided
</elided_chars>
<output_tail>
{{ output.output[-5000:] }}
</output_tail>
{%- endif %}
<step>{{n_model_calls}}/{{step_limit}}</step>{% if n_model_calls >= step_limit - 5 %} <warning>You are almost out of steps. Submit now with: echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT</warning>{% endif %}
<reminder>When done, submit with ONLY this command (no other commands): echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT</reminder>
"""

FORMAT_ERROR_TEMPLATE = """\
Please always provide EXACTLY ONE action in triple backticks, found {{actions|length}} actions.
If you want to end the task, please issue the following command: `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`
without any other command.
Else, please format your response exactly as follows:

<response_example>
Here are some thoughts about why you want to perform the action.

```bash
<action>
```
</response_example>

Note: In rare cases, if you need to reference a similar format in your command, you might have
to proceed in two steps, first writing TRIPLEBACKTICKSBASH, then replacing them with ```bash.
"""

TIMEOUT_TEMPLATE = """\
The last command <command>{{action['action']}}</command> timed out and has been killed.
The output of the command was:
{% if output | length < 10000 -%}
<output>
{{output}}
</output>
{%- else -%}
<warning>Output was too long and has been truncated.</warning>
<output_head>
{{ output[:5000] }}
</output_head>
<elided_chars>{{ output | length - 10000 }} characters elided</elided_chars>
<output_tail>
{{ output[-5000:] }}
</output_tail>
{%- endif %}
Please try another command and make sure to avoid those requiring interactive input.
"""

SHELL_FENCE_REGEX = re.compile(r"```([^\n`]*)\n(.*?)\n```", re.DOTALL)

# Environment variables to prevent interactive hangs and noisy output
DEFAULT_ENV_VARS = {
    "PAGER": "cat",
    "MANPAGER": "cat",
    "LESS": "-R",
    "PIP_PROGRESS_BAR": "off",
    "TQDM_DISABLE": "1",
}


def _read_int_env(raw_value: Optional[str], default: int, *, minimum: int = 0) -> int:
    try:
        return max(minimum, int(str(raw_value or "").strip() or default))
    except (TypeError, ValueError):
        return max(minimum, int(default))


class LoopAbortError(RuntimeError):
    """Raised when strict loop controls detect a stuck trajectory."""


class QwenMiniInterface:
    """Adapter for mini-swe-agent with local OpenAI-compatible GraphRAG integration."""

    def __init__(self):
        # Vanilla defaults
        self.step_limit = 30
        self.max_attempts = 3
        self.max_fix_iterations = 0
        self.loop_policy = "strict"  # off | warn | strict
        self.search_streak_limit = 8
        self.no_diff_streak_limit = 8
        self.repeated_fail_limit = 3
        self.sed_fail_limit = 2
        self.env_bootstrap_fail_limit = 0
        self.python_inline_fail_limit = 0
        self.format_error_limit = 8
        self.no_edit_progress_step_limit = 16
        self.post_edit_no_diff_streak_limit = 2
        self.require_first_edit_by_step = 16
        self.max_read_only_steps_before_edit = 12
        self.path_mismatch_reject_limit = 2
        self.empty_diff_retry_limit = 2
        self.prompt_budget_chars = _read_int_env(
            os.getenv("QWEN_MINI_PROMPT_BUDGET_CHARS"),
            48000,
            minimum=4000,
        )
        self.prompt_budget_tokens = _read_int_env(
            os.getenv("QWEN_MINI_PROMPT_BUDGET_TOKENS"),
            0,
            minimum=0,
        )
        self.prompt_token_estimate_divisor = max(
            1,
            _read_int_env(
                os.getenv("QWEN_MINI_PROMPT_TOKEN_ESTIMATE_DIVISOR"),
                4,
                minimum=1,
            ),
        )
        self.pre_edit_repro_diagnosis_turn_budget = 1
        self.stagnant_failure_signature_limit = 2
        # Hard wall-clock cap per instance execution (across all attempts).
        self.instance_execution_timeout_sec = max(
            60,
            int(os.getenv("INSTANCE_EXEC_TIMEOUT_SEC", "1200")),
        )
        # Hard cap for a single agent.run() call (litellm/local-model response wait).
        self.agent_run_timeout_sec = max(
            60,
            int(os.getenv("AGENT_RUN_TIMEOUT_SEC", "1200")),
        )
        self.model_max_tokens = max(
            256,
            int(os.getenv("QWEN_MINI_MODEL_MAX_TOKENS", "8192")),
        )
        self.p2p_smoke_count = 10
        self.pytest_timeout = 180
        self.patch_compile_gate = True
        self.max_compile_fix_iterations = 2
        self.max_changed_lines = 200
        self.compile_valid_submit_stop = True
        self.enforce_tdd_test_first = True
        self.test_signal_mode = "hard"  # off | soft | hard
        self.retry_policy = "fixed"  # fixed | adaptive
        self.retry_similarity_threshold = 0.80
        self.adaptive_good_patch_max_changed_lines = 80
        self.temperature = 0.0
        self.cost_limit = 0  # Free local inference
        self.graph_guard_mode = "either"  # either | both | indexed_only
        self.strict_tdd_evidence = False
        self.test_change_policy = "any_test_like"  # any_test_like | repo_tests_only
        self.strict_tdd_infra_policy = "fail_closed"  # fail_closed | retry_then_fail_open | fail_open
        self.strict_tdd_infra_retry_budget = 2
        self.strict_tdd_bootstrap_aware_fail_open = False
        self.indexed_signal_mode = "attempted_query"  # attempted_query | successful_query
        self.graph_refresh_policy = "auto"  # auto | initial_only
        self.pre_edit_repro_max_tests = 1
        self.pre_edit_repro_timeout_sec = 60
        self.iter_fix_require_reliable_signal = (
            str(os.getenv("ITER_FIX_REQUIRE_RELIABLE_SIGNAL", "on")).strip().lower()
            in {"1", "true", "on", "yes"}
        )
        self.iter_fix_min_remaining_sec = max(
            0,
            int(os.getenv("ITER_FIX_MIN_REMAINING_SEC", "180") or 180),
        )
        self.graph_regression_fix_round_limit = max(
            0,
            int(os.getenv("GRAPH_REGRESSION_FIX_ROUND_LIMIT", "1") or 1),
        )
        self.graph_zero_signal_fallback_smoke = (
            str(os.getenv("GRAPH_ZERO_SIGNAL_FALLBACK_SMOKE", "on")).strip().lower()
            in {"1", "true", "on", "yes"}
        )
        self.round_control_defaults: dict[str, dict[str, int]] = {}
        self.timeout_recover_best_patch = (
            str(os.getenv("TIMEOUT_RECOVER_BEST_PATCH", "on")).strip().lower()
            in {"1", "true", "on", "yes"}
        )
        self.local_backend = resolve_qwen_local_backend(
            prefix="QWEN_MINI",
            default_model="qwen3-coder:30b",
        )
        ensure_local_backend_ready(self.local_backend, prefix="QWEN_MINI")
        self.local_llm_runtime = self.local_backend.provider_label
        self.local_llm_provider = "ollama" if self.local_backend.provider == "ollama" else "openai"
        self.local_llm_api_base = self.local_backend.api_base
        self.local_llm_api_key = self.local_backend.api_key
        self.local_model = self.local_backend.litellm_model_name
        self.test_runtime_isolation = "off"
        self.test_runtime_cache_dir = str(os.getenv("TEST_RUNTIME_CACHE_DIR", "")).strip()
        self.test_runtime_bootstrap_timeout_sec = 240
        self.test_runtime_auto_editable_install = (
            str(os.getenv("TEST_RUNTIME_AUTO_EDITABLE_INSTALL", "on")).strip().lower()
            in {"1", "true", "on", "yes"}
        )
        self._apply_local_backend_runtime_defaults()
        self.test_runtime_manager = TestRuntimeManager(
            isolation_mode=self.test_runtime_isolation,
            cache_dir=self.test_runtime_cache_dir or None,
            bootstrap_timeout_sec=self.test_runtime_bootstrap_timeout_sec,
            auto_editable_install=self.test_runtime_auto_editable_install,
        )
        self._last_patch_gate_decision: dict[str, Any] = {}
        os.environ["MSWEA_COST_TRACKING"] = "ignore_errors"

    def set_model_name(self, model_name: Optional[str]) -> None:
        """Apply a qwen-mini model override after agent construction."""
        self.local_backend = resolve_qwen_local_backend(
            prefix="QWEN_MINI",
            explicit_model=model_name,
            default_model="qwen3-coder:30b",
        )
        ensure_local_backend_ready(self.local_backend, prefix="QWEN_MINI")
        self.local_llm_runtime = self.local_backend.provider_label
        self.local_llm_provider = "ollama" if self.local_backend.provider == "ollama" else "openai"
        self.local_llm_api_base = self.local_backend.api_base
        self.local_llm_api_key = self.local_backend.api_key
        self.local_model = self.local_backend.litellm_model_name
        self._apply_local_backend_runtime_defaults()
        self._sync_test_runtime_manager_settings()
        self.test_runtime_manager.configure_from_env()

    def describe_local_backend(self) -> str:
        return self.local_backend.provider_label

    def _default_test_runtime_isolation_for_backend(self) -> str:
        if self.local_backend.provider == "mlxlm":
            return "repo_cached_venv"
        return "off"

    def _default_test_runtime_bootstrap_timeout_for_backend(self) -> int:
        if self.local_backend.provider == "mlxlm":
            return 600
        return 240

    def _apply_local_backend_runtime_defaults(self) -> None:
        isolation_default = self._default_test_runtime_isolation_for_backend()
        isolation_raw = os.getenv("TEST_RUNTIME_ISOLATION")
        isolation_value = (
            str(isolation_raw).strip().lower()
            if isolation_raw is not None and str(isolation_raw).strip()
            else isolation_default
        )
        if isolation_value not in {"off", "repo_cached_venv"}:
            isolation_value = isolation_default
        self.test_runtime_isolation = isolation_value

        timeout_default = self._default_test_runtime_bootstrap_timeout_for_backend()
        timeout_raw = os.getenv("TEST_RUNTIME_BOOTSTRAP_TIMEOUT_SEC")
        self.test_runtime_bootstrap_timeout_sec = _read_int_env(
            timeout_raw,
            timeout_default,
            minimum=30,
        )

    # ------------------------------------------------------------------ #
    # Main entry point                                                    #
    # ------------------------------------------------------------------ #

    def execute_code_cli(
        self,
        instance_id: str,
        problem_statement: str,
        repo: str,
        base_commit: str,
        hints_text: str = "",
        tdd_mode: bool = False,
        graphrag_enabled: bool = False,
        graphrag_mcp=None,
        fail_to_pass_tests: Optional[list[str]] = None,
        pass_to_pass_tests: Optional[list[str]] = None,
    ) -> dict:
        """Run mini-swe-agent on a SWE-bench instance. Returns prediction dict."""
        fail_to_pass_tests = fail_to_pass_tests or []
        pass_to_pass_tests = pass_to_pass_tests or []
        all_logs: list[str] = []
        attempt_summaries: list[dict[str, Any]] = []
        attempt_candidates: list[dict[str, Any]] = []
        best_candidate: Optional[dict[str, Any]] = None
        best_score: Optional[tuple] = None
        instance_started_at = time.time()
        worker_pid = os.getpid()
        instance_timeout_reached = False
        graph_impact_strategy = str(os.getenv("GRAPH_IMPACT_STRATEGY", "hybrid")).strip().lower() or "hybrid"
        try:
            graph_impact_threshold = float(os.getenv("GRAPH_IMPACT_THRESHOLD", "0.3"))
        except ValueError:
            graph_impact_threshold = 0.3
        try:
            graph_impact_max_tests = max(1, int(os.getenv("GRAPH_IMPACT_MAX_TESTS", "50")))
        except ValueError:
            graph_impact_max_tests = 50
        graph_guard_mode = str(
            os.getenv("GRAPH_GUARD_MODE", self.graph_guard_mode or "either")
        ).strip().lower() or "either"
        if graph_guard_mode not in {"either", "both", "indexed_only"}:
            graph_guard_mode = "either"
        test_change_policy = str(
            os.getenv("TEST_CHANGE_POLICY", self.test_change_policy or "any_test_like")
        ).strip().lower() or "any_test_like"
        if test_change_policy not in {"any_test_like", "repo_tests_only"}:
            test_change_policy = "any_test_like"
        strict_tdd_infra_policy = str(
            os.getenv("STRICT_TDD_INFRA_POLICY", self.strict_tdd_infra_policy or "fail_closed")
        ).strip().lower() or "fail_closed"
        if strict_tdd_infra_policy not in {"fail_closed", "retry_then_fail_open", "fail_open"}:
            strict_tdd_infra_policy = "fail_closed"
        try:
            strict_tdd_infra_retry_budget = max(
                0,
                int(os.getenv("STRICT_TDD_INFRA_RETRY_BUDGET", str(self.strict_tdd_infra_retry_budget))),
            )
        except ValueError:
            strict_tdd_infra_retry_budget = max(0, int(self.strict_tdd_infra_retry_budget))
        strict_tdd_bootstrap_aware_fail_open = (
            self.strict_tdd_bootstrap_aware_fail_open
            or str(os.getenv("STRICT_TDD_BOOTSTRAP_AWARE_FAIL_OPEN", "off")).strip().lower()
            in {"1", "true", "on", "yes"}
        )
        indexed_signal_mode = str(
            os.getenv("INDEXED_SIGNAL_MODE", self.indexed_signal_mode or "attempted_query")
        ).strip().lower() or "attempted_query"
        if indexed_signal_mode not in {"attempted_query", "successful_query"}:
            indexed_signal_mode = "attempted_query"

        # Persist resolved runtime knobs for helper methods in this execution.
        self.test_change_policy = test_change_policy
        self.strict_tdd_infra_policy = strict_tdd_infra_policy
        self.strict_tdd_infra_retry_budget = strict_tdd_infra_retry_budget
        self.strict_tdd_bootstrap_aware_fail_open = strict_tdd_bootstrap_aware_fail_open
        self.indexed_signal_mode = indexed_signal_mode
        graph_refresh_policy = str(
            os.getenv("GRAPH_REFRESH_POLICY", self.graph_refresh_policy or "auto")
        ).strip().lower() or "auto"
        if graph_refresh_policy not in {"auto", "initial_only"}:
            graph_refresh_policy = "auto"
        self.graph_refresh_policy = graph_refresh_policy
        self._sync_test_runtime_manager_settings()
        self.test_runtime_manager.configure_from_env()
        self.test_runtime_manager.set_context(repo_slug=repo, commit_sha=base_commit)

        strict_tdd_evidence = self.strict_tdd_evidence or (
            str(os.getenv("STRICT_TDD_EVIDENCE", "off")).strip().lower() in {"1", "true", "on", "yes"}
        )
        pre_edit_repro_cache: Optional[dict[str, Any]] = None
        empty_diff_attempts = 0
        graph_zero_impact_streak = 0
        instance_graph_ready = False
        graph_initial_build_count = 0
        graph_incremental_refresh_count = 0
        graph_requery_count = 0
        targeted_coverage_update_count = 0
        prior_attempt_memory = self._load_recent_attempt_memory(instance_id)
        attempt_memory_guidance = self._format_attempt_memory_guidance(prior_attempt_memory)

        for attempt_idx in range(1, self.max_attempts + 1):
            elapsed_total = time.time() - instance_started_at
            if elapsed_total >= self.instance_execution_timeout_sec:
                instance_timeout_reached = True
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] "
                    f"[attempt {attempt_idx}/{self.max_attempts}] "
                    f"INSTANCE_TIMEOUT reached before attempt start: "
                    f"elapsed={elapsed_total:.1f}s cap={self.instance_execution_timeout_sec}s",
                    flush=True,
                )
                break
            repo_path = None
            attempt_logs: list[str] = []

            def log(msg: str):
                ts = datetime.now().strftime("%H:%M:%S")
                line = f"[{ts}] [attempt {attempt_idx}/{self.max_attempts}] {msg}"
                print(line, flush=True)
                attempt_logs.append(line)
                all_logs.append(line)

            graphrag_meta = {
                "graph_built": False,
                "graph_cache_key": "",
                "graph_nodes": 0,
                "graph_rels": 0,
                "changed_files": [],
                "impact_strategy": graph_impact_strategy,
                "impact_strategy_effective": graph_impact_strategy,
                "impact_threshold": graph_impact_threshold,
                "impact_max_tests": graph_impact_max_tests,
                "impacted_total": 0,
                "impacted_run": 0,
                "impacted_failed": 0,
                "impacted_failed_tests": [],
                "impacted_success": None,
                "impacted_error": "",
                "impacted_execution_reliable": None,
                "impacted_graph_freshness": "unknown",
                "impacted_rebuild_triggered": False,
                "impacted_selection_confidence": {"high": 0, "medium": 0, "low": 0},
                "impacted_selected_count": 0,
                "impacted_runnable_count": 0,
                "impacted_runnable_ratio": 0.0,
                "impacted_precision_score": 0.0,
                "impacted_precision_floor_passed": False,
                "graph_useful_signal": False,
                "graph_fallback_reason": "",
                "regression_source": "none",
                "regression_gate_passed": False,
                "regression_signal_reliable": False,
                "regression_tests_selected": 0,
                "regression_tests_run": 0,
                "regression_tests_failed": 0,
                "indexed_search_used": False,
                "indexed_search_attempted": False,
                "indexed_search_success": False,
                "indexed_query_success": False,
                "graph_signal_unavailable": False,
                "impact_seeded_query_used": False,
                "graph_guard_mode": graph_guard_mode,
                "graph_guard_passed": None,
                "graph_guard_reason": "",
                "impact_empty_reason": "",
                "graph_refresh_policy": graph_refresh_policy,
                "graph_initial_build_count": graph_initial_build_count,
                "graph_incremental_refresh_count": graph_incremental_refresh_count,
                "graph_requery_count": graph_requery_count,
                "targeted_coverage_update_count": targeted_coverage_update_count,
                "test_change_policy": test_change_policy,
                "repo_test_changed": False,
                "stagnation_reprobe_used": False,
                "stagnation_reprobe_reason": "",
                "stagnation_reprobe_failed": 0,
                "stagnation_force_rebuild_used": False,
                "stagnation_force_rebuild_budget": 0,
                "test_runtime_isolation": self.test_runtime_manager.isolation_mode,
            }

            try:
                log(f"=== START {instance_id} ===")
                log(f"Repo: {repo}  Commit: {base_commit[:8]}")
                if graphrag_enabled:
                    log(
                        "GraphRAG impact config: "
                        f"strategy={graph_impact_strategy} "
                        f"threshold={graph_impact_threshold} "
                        f"max_tests={graph_impact_max_tests}"
                    )
                    log(f"GraphRAG refresh policy: {graph_refresh_policy}")
                self.test_runtime_manager.clear_repo_cache()
                repo_path = self._setup_repository(repo, base_commit, log)
                log(f"Repo cloned to: {repo_path}")

                pre_edit_repro = {
                    "command": "",
                    "ran": False,
                    "failed": False,
                    "failed_count": 0,
                    "total": 0,
                    "infra_unreliable": False,
                    "infra_reason": "",
                    "signal_confidence": 0.0,
                    "retry_variant_used": "",
                    "runtime_strategy": "",
                    "runtime_fallback_used": "",
                    "runtime_unreliable_reason": "",
                    "runtime_env_id": "",
                    "runtime_bootstrap_error": "",
                    "runtime_bootstrap_error_reason": "",
                    "runtime_install_mode": "",
                    "variant_attempts": [],
                }
                pre_edit_localization = {
                    "success": False,
                    "reason": "",
                    "seed_files": [],
                    "focus_files": [],
                    "affected_tests": [],
                    "total_tests": 0,
                }
                needs_pre_edit_probe = bool(
                    tdd_mode
                    and fail_to_pass_tests
                    and (
                        strict_tdd_evidence
                        or strict_tdd_infra_policy == "fail_closed"
                    )
                )
                if needs_pre_edit_probe:
                    if pre_edit_repro_cache is None:
                        pre_edit_repro_cache = self._run_pre_edit_repro_probe(
                            repo_path=repo_path,
                            fail_to_pass_tests=fail_to_pass_tests,
                            log=log,
                        )
                    pre_edit_repro = dict(pre_edit_repro_cache)
                    log(
                        "PHASE: PRE_EDIT_REPRO_SUMMARY "
                        f"ran={pre_edit_repro.get('ran')} "
                        f"failed={pre_edit_repro.get('failed')} "
                        f"failed_count={pre_edit_repro.get('failed_count')}/"
                        f"{pre_edit_repro.get('total')}"
                    )
                bootstrap_fail_open_applied = False
                bootstrap_fail_open_reason = ""
                skip_codegen_due_to_infra = bool(
                    tdd_mode
                    and fail_to_pass_tests
                    and strict_tdd_infra_policy == "fail_closed"
                    and pre_edit_repro.get("infra_unreliable")
                )
                if skip_codegen_due_to_infra and strict_tdd_bootstrap_aware_fail_open:
                    if self._is_structural_bootstrap_infra_reason(
                        pre_edit_repro.get("infra_reason", ""),
                        pre_edit_repro.get("runtime_bootstrap_error_reason", ""),
                    ):
                        skip_codegen_due_to_infra = False
                        bootstrap_fail_open_applied = True
                        bootstrap_fail_open_reason = str(
                            pre_edit_repro.get("runtime_bootstrap_error_reason", "")
                            or pre_edit_repro.get("infra_reason", "")
                            or "bootstrap_structural_incompat"
                        )
                        log(
                            "PHASE: PRE_EDIT_FAIL_OPEN "
                            f"reason={bootstrap_fail_open_reason} "
                            "policy=bootstrap_aware"
                        )
                if skip_codegen_due_to_infra:
                    log(
                        "PHASE: CODEGEN_BYPASS "
                        f"reason=infra_blocked:pre_edit_infra_unreliable:{pre_edit_repro.get('infra_reason') or 'unknown'} "
                        f"diagnosis_turns=1/{self.pre_edit_repro_diagnosis_turn_budget}"
                    )

                if graphrag_enabled and graphrag_mcp and not skip_codegen_due_to_infra:
                    try:
                        should_build_graph = (
                            graph_refresh_policy != "initial_only"
                            or not instance_graph_ready
                        )
                        if should_build_graph:
                            graph_initial_build_count += 1
                            graphrag_meta["graph_initial_build_count"] = graph_initial_build_count
                            index_t0 = time.time()
                            log("PHASE: INDEXING_START")
                            log("Building GraphRAG index...")
                            graph_result = graphrag_mcp.build_graph(
                                str(repo_path),
                                force_rebuild=False,
                                include_tests=True,
                                repo_slug=repo,
                                commit_sha=base_commit,
                            )
                            graphrag_meta["graph_built"] = bool(graph_result.get("success"))
                            graphrag_meta["graph_cache_key"] = str(graph_result.get("cache_key", ""))
                            graphrag_meta["graph_nodes"] = int(graph_result.get("nodes_created", 0))
                            graphrag_meta["graph_rels"] = int(graph_result.get("relationships_created", 0))
                            if graph_result.get("success"):
                                instance_graph_ready = True
                            log(
                                "GraphRAG build "
                                f"success={graph_result.get('success')} "
                                f"nodes={graphrag_meta['graph_nodes']} rels={graphrag_meta['graph_rels']}"
                            )
                            log(
                                "PHASE: INDEXING_END "
                                f"status={'success' if graph_result.get('success') else 'failed'} "
                                f"elapsed={time.time() - index_t0:.1f}s"
                            )
                        else:
                            graphrag_meta["graph_built"] = True
                            graphrag_meta["graph_initial_build_count"] = graph_initial_build_count
                            log("PHASE: INDEXING_SKIPPED reason=graph_refresh_policy_initial_only")
                    except Exception as e:
                        log(f"PHASE: INDEXING_END status=failed error={e}")
                        log(f"GraphRAG build failed: {e}")
                elif graphrag_enabled and skip_codegen_due_to_infra:
                    log("PHASE: INDEXING_SKIPPED reason=pre_edit_infra_unreliable")

                if graphrag_enabled and graphrag_mcp and not skip_codegen_due_to_infra:
                    pre_edit_localization = self._run_pre_edit_graphrag_localization(
                        repo_path=repo_path,
                        problem_statement=problem_statement,
                        fail_to_pass_tests=fail_to_pass_tests,
                        graphrag_mcp=graphrag_mcp,
                        impact_threshold=graph_impact_threshold,
                        max_tests=graph_impact_max_tests,
                        strategy=graph_impact_strategy,
                        log=log,
                    )

                prev_attempt = attempt_summaries[-1] if attempt_summaries else None
                prev_candidate = attempt_candidates[-1] if attempt_candidates else None
                force_strategy_shift = False
                if attempt_idx > 1 and empty_diff_attempts > 0:
                    force_strategy_shift = True
                    log(
                        "Retry hardening: previous attempt had empty diff. "
                        "Forcing strategy shift."
                    )
                if (
                    self.retry_policy == "adaptive"
                    and attempt_idx > 1
                    and prev_candidate
                    and best_candidate
                ):
                    similarity = self._estimate_attempt_similarity(prev_candidate, best_candidate)
                    if similarity >= self.retry_similarity_threshold:
                        force_strategy_shift = True
                        log(
                            "Adaptive retry: previous attempt is too similar to prior best "
                            f"(sim={similarity:.2f}). Forcing strategy shift."
                        )
                if (
                    attempt_idx > 1
                    and prev_candidate
                    and bool(prev_candidate.get("progress_gate_relocalize"))
                ):
                    force_strategy_shift = True
                    log(
                        "Progress gate: same failure signature repeated without new issue-test progress. "
                        "Relocalizing before the next attempt."
                    )
                    if graphrag_enabled and graphrag_mcp and not skip_codegen_due_to_infra:
                        pre_edit_localization = self._run_pre_edit_graphrag_localization(
                            repo_path=repo_path,
                            problem_statement=problem_statement,
                            fail_to_pass_tests=fail_to_pass_tests,
                            graphrag_mcp=graphrag_mcp,
                            impact_threshold=graph_impact_threshold,
                            max_tests=graph_impact_max_tests,
                            strategy=graph_impact_strategy,
                            log=log,
                        )
                carryover_changed_files = (
                    list(best_candidate.get("changed_files") or [])
                    if best_candidate
                    else []
                )
                if not carryover_changed_files and prev_candidate:
                    carryover_changed_files = list(prev_candidate.get("changed_files") or [])
                if not carryover_changed_files:
                    carryover_changed_files = list(graphrag_meta.get("changed_files") or [])
                pre_edit_focus_files = list(pre_edit_localization.get("focus_files") or [])
                pre_edit_affected_tests = list(pre_edit_localization.get("affected_tests") or [])
                carryover_patch_candidate = bool(
                    best_candidate
                    and str(best_candidate.get("prediction", "") or "").strip()
                    and list(best_candidate.get("changed_files") or [])
                )
                retry_focus_files = self._derive_repair_focus_files(
                    repo_path=repo_path,
                    problem_statement=problem_statement,
                    fail_to_pass_tests=fail_to_pass_tests,
                    changed_files=carryover_changed_files or None,
                    failed_tests=[
                        {
                            "test_name": nodeid,
                            "full_name": nodeid,
                            "test_file": str(nodeid).split("::", 1)[0],
                        }
                        for nodeid in fail_to_pass_tests[:5]
                    ],
                    pinned_files=carryover_changed_files or None,
                )
                retry_focus_files = self._prioritize_focus_files(
                    pre_edit_focus_files + retry_focus_files,
                    max_files=6,
                    pinned_files=carryover_changed_files or None,
                )
                retry_anchor_file = self._select_primary_focus_file(
                    changed_files=carryover_changed_files,
                    focus_files=retry_focus_files,
                )
                retry_diff_excerpt = self._build_current_diff_excerpt(
                    repo_path,
                    changed_files=carryover_changed_files or retry_focus_files,
                )
                if not retry_diff_excerpt and carryover_patch_candidate and best_candidate:
                    retry_diff_excerpt = self._build_diff_excerpt_from_patch_text(
                        str(best_candidate.get("prediction", "") or "")
                    )
                retry_source_context = self._build_focus_source_excerpt(
                    repo_path,
                    focus_files=retry_focus_files,
                    diff_excerpt=retry_diff_excerpt,
                    anchor_file=retry_anchor_file,
                    include_meta=True,
                )
                retry_source_excerpt = str(retry_source_context.get("excerpt", "") or "")
                retry_verify_command = self._build_verify_command(
                    round_mode="retry_refine" if carryover_patch_candidate else "default",
                    focus_files=retry_focus_files,
                    failing_tests=fail_to_pass_tests,
                )
                if carryover_patch_candidate and best_candidate:
                    self._log_candidate_debug(
                        log=log,
                        prefix="RETRY_CARRYOVER",
                        candidate=best_candidate,
                    )
                task = self._format_retry_task(
                    problem_statement=problem_statement,
                    hints_text=hints_text,
                    tdd_mode=tdd_mode,
                    attempt_idx=attempt_idx,
                    prev_attempt=prev_attempt,
                    prev_candidate=prev_candidate,
                    best_candidate=best_candidate,
                    force_strategy_shift=force_strategy_shift,
                    affected_tests=pre_edit_affected_tests,
                    focus_files=retry_focus_files,
                    existing_diff_excerpt=retry_diff_excerpt,
                    source_excerpt=retry_source_excerpt,
                    verify_command=retry_verify_command,
                    memory_guidance=attempt_memory_guidance,
                    graphrag_summary=(pre_edit_localization if graphrag_enabled else None),
                )
                tdd_fix_round = 0
                regression_fix_round = 0
                max_fix_rounds = self.max_fix_iterations if (tdd_mode or graphrag_enabled) else 0
                max_regression_fix_rounds = min(max_fix_rounds, self.graph_regression_fix_round_limit)
                compile_fix_round = 0
                max_compile_fix_rounds = self.max_compile_fix_iterations if self.patch_compile_gate else 0

                run_result: dict[str, Any] = {}
                patch = ""
                test_metrics: dict[str, Any] = {}
                last_patch_gate: dict[str, Any] = {}
                changed_files: list[str] = []
                diff_signature = "EMPTY"
                tdd_signal_reliable = False
                tdd_gate_passed = False
                tdd_gate_infra_unreliable = bool(skip_codegen_due_to_infra)
                round_mode = "retry_refine" if carryover_patch_candidate else "default"
                round_focus_files = retry_focus_files
                if round_focus_files:
                    log("Default round focus files: " + ", ".join(round_focus_files[:4]))
                self._log_round_context(
                    log=log,
                    round_mode=round_mode,
                    focus_files=round_focus_files,
                    verify_command=retry_verify_command,
                    diff_excerpt=retry_diff_excerpt,
                    source_excerpt=retry_source_excerpt,
                    source_context_meta=retry_source_context,
                )

                log("PHASE: CODEGEN_START")
                while True:
                    if skip_codegen_due_to_infra:
                        infra_block_reason = (
                            "infra_blocked:pre_edit_repro_infra_unreliable:"
                            f"{pre_edit_repro.get('infra_reason') or 'unknown'}"
                        )
                        run_result = {
                            "status": "InfraUnreliable",
                            "message": infra_block_reason,
                            "steps": 0,
                            "cost": 0.0,
                            "elapsed": 0.0,
                            "format_errors": 0,
                            "timeouts": 0,
                            "loop_abort_reason": infra_block_reason,
                            "bootstrap_fail_open_applied": bool(bootstrap_fail_open_applied),
                            "bootstrap_fail_open_reason": str(bootstrap_fail_open_reason or ""),
                        }
                        test_metrics = {
                            "f2p_total": len(fail_to_pass_tests),
                            "f2p_passed": 0,
                            "f2p_failed": len(fail_to_pass_tests),
                            "f2p_pass_rate": 0.0 if fail_to_pass_tests else None,
                            "f2p_all_passed": False,
                            "f2p_reliable": False,
                            "f2p_infra_reason": str(pre_edit_repro.get("infra_reason", "") or "pre_edit_repro"),
                            "f2p_signal_confidence": float(pre_edit_repro.get("signal_confidence", 0.0) or 0.0),
                            "f2p_retry_variant_used": str(pre_edit_repro.get("retry_variant_used", "") or ""),
                            "f2p_runtime_strategy": str(pre_edit_repro.get("runtime_strategy", "") or ""),
                            "f2p_runtime_fallback_used": str(
                                pre_edit_repro.get("runtime_fallback_used", "") or ""
                            ),
                            "f2p_runtime_unreliable_reason": str(
                                pre_edit_repro.get("runtime_unreliable_reason", "") or ""
                            ),
                            "f2p_variant_attempts": list(pre_edit_repro.get("variant_attempts") or []),
                            "f2p_runtime_env_id": str(pre_edit_repro.get("runtime_env_id", "") or ""),
                            "f2p_runtime_bootstrap_error": str(
                                pre_edit_repro.get("runtime_bootstrap_error", "") or ""
                            ),
                            "f2p_runtime_bootstrap_error_reason": str(
                                pre_edit_repro.get("runtime_bootstrap_error_reason", "") or ""
                            ),
                            "f2p_runtime_install_mode": str(pre_edit_repro.get("runtime_install_mode", "") or ""),
                            "verify_cmd": str(pre_edit_repro.get("command", "") or ""),
                            "p2p_smoke_total": None,
                            "p2p_smoke_failures": None,
                            "p2p_reliable": None,
                            "p2p_infra_reason": "",
                            "p2p_signal_confidence": 1.0,
                            "p2p_retry_variant_used": "",
                            "p2p_runtime_strategy": "",
                            "p2p_runtime_fallback_used": "",
                            "p2p_runtime_unreliable_reason": "",
                            "p2p_variant_attempts": [],
                            "p2p_runtime_env_id": "",
                            "p2p_runtime_bootstrap_error": "",
                            "p2p_runtime_bootstrap_error_reason": "",
                            "p2p_runtime_install_mode": "",
                            "smoke_cmd": "",
                            "test_signal_reliable": False,
                            "test_signal_confidence": float(pre_edit_repro.get("signal_confidence", 0.0) or 0.0),
                            "clean_resolution": False,
                            "bootstrap_fail_open_applied": bool(bootstrap_fail_open_applied),
                            "bootstrap_fail_open_reason": str(bootstrap_fail_open_reason or ""),
                        }
                        patch = ""
                        changed_files = self._get_changed_files_any(repo_path)
                        graphrag_meta["changed_files"] = list(changed_files)
                        diff_signature = self._compute_diff_signature(repo_path)
                        break

                    remaining_instance_budget = int(
                        self.instance_execution_timeout_sec - (time.time() - instance_started_at)
                    )
                    if remaining_instance_budget <= 0:
                        instance_timeout_reached = True
                        run_result = {
                            "status": "LoopAborted",
                            "message": f"instance_timeout:{self.instance_execution_timeout_sec}s",
                            "steps": 0,
                            "cost": 0.0,
                            "elapsed": 0.0,
                            "format_errors": 0,
                            "timeouts": 1,
                            "loop_abort_reason": f"instance_timeout:{self.instance_execution_timeout_sec}s",
                        }
                        patch = ""
                        changed_files = self._get_changed_files_any(repo_path)
                        graphrag_meta["changed_files"] = list(changed_files)
                        diff_signature = self._compute_diff_signature(repo_path)
                        log(
                            "PHASE: CODEGEN_ABORT instance timeout reached "
                            f"cap={self.instance_execution_timeout_sec}s"
                        )
                        break

                    agent = self._create_agent(repo_path, tdd_mode)
                    run_budget = min(self.agent_run_timeout_sec, max(1, remaining_instance_budget))
                    run_result = self._run_agent_with_controls(
                        agent,
                        task,
                        repo_path,
                        log,
                        run_timeout_sec=run_budget,
                        round_mode=round_mode,
                        focus_files=round_focus_files,
                        pre_edit_infra_unreliable=bool(pre_edit_repro.get("infra_unreliable")),
                    )
                    patch = self._extract_patch(repo_path, log=log)
                    last_patch_gate = dict(self._last_patch_gate_decision)
                    changed_files = self._get_changed_files_any(repo_path)
                    graphrag_meta["changed_files"] = list(changed_files)
                    diff_signature = self._compute_diff_signature(repo_path)
                    log(f"Patch: {len(patch)} chars")
                    compile_gate = last_patch_gate.get("compile_gate", {})
                    compile_failed = int(compile_gate.get("compile_failed", 0) or 0)
                    compile_repair_patch = self._compile_repair_patch_source(
                        patch=patch,
                        last_patch_gate=last_patch_gate,
                    )
                    if compile_failed > 0 and not str(patch or "").strip() and str(compile_repair_patch or "").strip():
                        log("Compile-repair using raw diff preserved from patch-gate rejection.")

                    if compile_failed > 0:
                        run_status = str(run_result.get("status", ""))
                        should_compile_repair, compile_repair_reason = (
                            self._should_continue_compile_fix_round(
                                run_status=run_status,
                                compile_failed=compile_failed,
                                patch=compile_repair_patch,
                                current_round=compile_fix_round,
                                max_rounds=max_compile_fix_rounds,
                            )
                        )
                        if should_compile_repair:
                            compile_fix_round += 1
                            compile_failed_files = list(compile_gate.get("compile_failed_files", []) or [])
                            compile_focus_files = self._prioritize_focus_files(
                                list(dict.fromkeys(
                                    compile_failed_files
                                    + self._derive_repair_focus_files(
                                        repo_path=repo_path,
                                        problem_statement=problem_statement,
                                        fail_to_pass_tests=fail_to_pass_tests,
                                        changed_files=changed_files,
                                        pinned_files=compile_failed_files or changed_files,
                                    )
                                )),
                                max_files=6,
                                pinned_files=compile_failed_files or changed_files,
                            )
                            compile_anchor_file = self._select_primary_focus_file(
                                changed_files=compile_failed_files or changed_files,
                                focus_files=compile_focus_files,
                            )
                            compile_diff_excerpt = self._build_current_diff_excerpt(
                                repo_path,
                                changed_files=compile_failed_files or compile_focus_files,
                            )
                            compile_error_text = ""
                            if compile_gate.get("details"):
                                compile_error_text = str(
                                    (compile_gate.get("details") or [{}])[0].get("current_error", "") or ""
                                )
                            compile_source_context = self._build_focus_source_excerpt(
                                repo_path,
                                focus_files=compile_focus_files,
                                diff_excerpt=compile_diff_excerpt,
                                current_error=compile_error_text,
                                anchor_file=compile_anchor_file,
                                include_meta=True,
                            )
                            task = self._format_compile_failure_task(
                                problem_statement,
                                hints_text,
                                compile_gate,
                                focus_files=compile_focus_files,
                                existing_diff_excerpt=compile_diff_excerpt,
                                source_excerpt=str(compile_source_context.get("excerpt", "") or ""),
                                verify_command=self._build_verify_command(
                                    round_mode="compile_repair",
                                    focus_files=compile_focus_files,
                                    compile_failed_files=compile_gate.get("compile_failed_files") or [],
                                ),
                            )
                            round_mode = "compile_repair"
                            round_focus_files = compile_focus_files
                            self._log_round_context(
                                log=log,
                                round_mode=round_mode,
                                focus_files=round_focus_files,
                                verify_command=self._build_verify_command(
                                    round_mode="compile_repair",
                                    focus_files=compile_focus_files,
                                    compile_failed_files=compile_gate.get("compile_failed_files") or [],
                                ),
                                diff_excerpt=compile_diff_excerpt,
                                source_excerpt=str(compile_source_context.get("excerpt", "") or ""),
                                source_context_meta=compile_source_context,
                            )
                            log(
                                f"Continuing with compile-repair round "
                                f"{compile_fix_round}/{max_compile_fix_rounds}"
                            )
                            continue
                        if compile_repair_reason == "round_limit_reached":
                            log(
                                f"Compile-repair rounds exhausted "
                                f"({compile_fix_round}/{max_compile_fix_rounds})"
                            )
                        else:
                            log(
                                "Compile failures detected but skipping compile-repair "
                                f"because {compile_repair_reason}"
                            )

                    require_test_checks = bool(tdd_mode or graphrag_enabled)
                    log("PHASE: LOCAL_EVAL_START")
                    test_metrics = self._evaluate_candidate(
                        repo_path,
                        fail_to_pass_tests,
                        pass_to_pass_tests,
                        require_test_checks=require_test_checks,
                        log=log,
                    )
                    log(
                        "PHASE: LOCAL_EVAL_END "
                        f"f2p_pass_rate={test_metrics.get('f2p_pass_rate')} "
                        f"p2p_smoke_failures={test_metrics.get('p2p_smoke_failures')}"
                    )
                    f2p_total = int(test_metrics.get("f2p_total", 0) or 0)
                    f2p_all_passed = bool(test_metrics.get("f2p_all_passed", False))
                    f2p_reliable_raw = test_metrics.get("f2p_reliable")
                    f2p_reliable = (f2p_reliable_raw is not False)
                    tdd_signal_reliable = (f2p_total <= 0) or bool(f2p_reliable)
                    tdd_gate_passed = (f2p_total <= 0) or (f2p_all_passed and tdd_signal_reliable)
                    tdd_gate_infra_unreliable = (f2p_total > 0) and (not tdd_signal_reliable)
                    graphrag_meta["regression_source"] = "none"
                    graphrag_meta["regression_gate_passed"] = not graphrag_enabled
                    graphrag_meta["regression_signal_reliable"] = False
                    graphrag_meta["regression_tests_selected"] = 0
                    graphrag_meta["regression_tests_run"] = 0
                    graphrag_meta["regression_tests_failed"] = 0

                    if graphrag_enabled and graphrag_mcp:
                        try:
                            changed_files = self._get_changed_files_any(repo_path)
                            graphrag_meta["changed_files"] = list(changed_files)
                            source_changed_files = self._extract_source_file_changes(
                                changed_files,
                                policy=test_change_policy,
                            )
                            graphrag_meta["source_changed_files"] = list(source_changed_files)
                            graphrag_meta["graph_initial_build_count"] = graph_initial_build_count
                            graphrag_meta["graph_incremental_refresh_count"] = graph_incremental_refresh_count
                            graphrag_meta["graph_requery_count"] = graph_requery_count
                            graphrag_meta["targeted_coverage_update_count"] = targeted_coverage_update_count
                            impact_input_files = list(source_changed_files)
                            repairable_patch_candidate, repairability_reason = (
                                self._can_enter_intra_attempt_repair(
                                    graphrag_enabled=graphrag_enabled,
                                    patch=patch,
                                    source_changed_files=impact_input_files,
                                )
                            )
                            if not str(patch or "").strip():
                                graphrag_meta["impact_empty_reason"] = "no_non_empty_patch_for_impact_query"
                                log("GraphRAG impact query skipped: no non-empty patch candidate available.")
                                if self.graph_zero_signal_fallback_smoke:
                                    log(
                                        "GraphRAG structural impact query skipped; "
                                        "running deterministic targeted fallback tests."
                                    )
                                    deterministic = self._run_deterministic_targeted_tests(
                                        repo_path=repo_path,
                                        fail_to_pass_tests=fail_to_pass_tests,
                                        pass_to_pass_tests=pass_to_pass_tests,
                                        log=log,
                                    )
                                    if self._apply_regression_fallback_result(
                                        graphrag_meta=graphrag_meta,
                                        fallback_result=deterministic,
                                        regression_source="bounded_fallback_smoke",
                                        impact_empty_reason="no_non_empty_patch_for_impact_query",
                                        graph_fallback_reason="no_non_empty_patch_bounded_fallback",
                                    ):
                                        log(
                                            "Deterministic fallback tests: "
                                            f"run={graphrag_meta['impacted_run']} "
                                            f"failed={graphrag_meta['impacted_failed']}"
                                        )
                                        if (
                                            deterministic.get("execution_reliable")
                                            and deterministic.get("selected_tests")
                                        ):
                                            coverage_result = self._record_graphrag_targeted_coverage(
                                                graphrag_mcp=graphrag_mcp,
                                                repo_path=repo_path,
                                                tests=list(deterministic.get("selected_tests") or []),
                                                log=log,
                                            )
                                            if coverage_result:
                                                targeted_coverage_update_count += 1
                                                graphrag_meta["targeted_coverage_update_count"] = (
                                                    targeted_coverage_update_count
                                                )
                            elif not impact_input_files:
                                graphrag_meta["impact_empty_reason"] = "no_source_file_changes_for_impact_query"
                                log("GraphRAG impact query skipped: no source file changes available.")
                                if self.graph_zero_signal_fallback_smoke:
                                    log(
                                        "GraphRAG source-side impact query skipped; "
                                        "running deterministic targeted fallback tests."
                                    )
                                    deterministic = self._run_deterministic_targeted_tests(
                                        repo_path=repo_path,
                                        fail_to_pass_tests=fail_to_pass_tests,
                                        pass_to_pass_tests=pass_to_pass_tests,
                                        log=log,
                                    )
                                    if self._apply_regression_fallback_result(
                                        graphrag_meta=graphrag_meta,
                                        fallback_result=deterministic,
                                        regression_source="bounded_fallback_smoke",
                                        impact_empty_reason="no_source_file_changes_for_impact_query",
                                        graph_fallback_reason="no_source_patch_bounded_fallback",
                                    ):
                                        log(
                                            "Deterministic fallback tests: "
                                            f"run={graphrag_meta['impacted_run']} "
                                            f"failed={graphrag_meta['impacted_failed']}"
                                        )
                                        if (
                                            deterministic.get("execution_reliable")
                                            and deterministic.get("selected_tests")
                                        ):
                                            coverage_result = self._record_graphrag_targeted_coverage(
                                                graphrag_mcp=graphrag_mcp,
                                                repo_path=repo_path,
                                                tests=list(deterministic.get("selected_tests") or []),
                                                log=log,
                                            )
                                            if coverage_result:
                                                targeted_coverage_update_count += 1
                                                graphrag_meta["targeted_coverage_update_count"] = (
                                                    targeted_coverage_update_count
                                                )
                            else:
                                graphrag_meta["indexed_search_attempted"] = True
                                impacted, effective_strategy = self._run_graphrag_impact_query(
                                    graphrag_mcp=graphrag_mcp,
                                    repo_path=repo_path,
                                    impact_input_files=impact_input_files,
                                    impact_threshold=graph_impact_threshold,
                                    max_tests=graph_impact_max_tests,
                                    strategy=graph_impact_strategy,
                                    require_fresh_graph=(graph_refresh_policy != "initial_only"),
                                    log=log,
                                )
                                self._apply_graphrag_impact_result(
                                    graphrag_meta=graphrag_meta,
                                    impacted=impacted,
                                    effective_strategy=effective_strategy,
                                    indexed_signal_mode=indexed_signal_mode,
                                )
                                if graphrag_meta["impacted_run"] <= 0:
                                    fallback_result = self._run_changed_test_file_fallback(
                                        repo_path=repo_path,
                                        changed_files=changed_files,
                                        log=log,
                                    )
                                    if self._apply_regression_fallback_result(
                                        graphrag_meta=graphrag_meta,
                                        fallback_result=fallback_result,
                                        regression_source="changed_test_file_fallback",
                                        impact_empty_reason="no_runnable_impacted_nodeids",
                                        graph_fallback_reason="no_runnable_impacted_nodeids_changed_test_file_fallback",
                                    ):
                                        log(
                                            "GraphRAG fallback changed-test-files: "
                                            f"run={graphrag_meta['impacted_run']} "
                                            f"failed={graphrag_meta['impacted_failed']}"
                                        )
                                        if (
                                            fallback_result.get("execution_reliable")
                                            and fallback_result.get("selected_tests")
                                        ):
                                            coverage_result = self._record_graphrag_targeted_coverage(
                                                graphrag_mcp=graphrag_mcp,
                                                repo_path=repo_path,
                                                tests=list(fallback_result.get("selected_tests") or []),
                                                log=log,
                                            )
                                            if coverage_result:
                                                targeted_coverage_update_count += 1
                                                graphrag_meta["targeted_coverage_update_count"] = (
                                                    targeted_coverage_update_count
                                                )
                                log(
                                    "GraphRAG iterative tests: "
                                    f"success={graphrag_meta['impacted_success']} "
                                    f"run={graphrag_meta['impacted_run']} "
                                    f"failed={graphrag_meta['impacted_failed']} "
                                    f"useful={graphrag_meta['graph_useful_signal']}"
                                )
                                if graphrag_meta["impacted_error"]:
                                    log(f"GraphRAG iterative error: {graphrag_meta['impacted_error']}")

                                graph_selection_empty = int(graphrag_meta["impacted_total"] or 0) <= 0
                                if graph_selection_empty:
                                    graph_zero_impact_streak += 1
                                else:
                                    graph_zero_impact_streak = 0
                                graphrag_meta["graph_zero_impact_streak"] = graph_zero_impact_streak
                                if graph_zero_impact_streak >= 1 and self.graph_zero_signal_fallback_smoke:
                                    graphrag_meta["graph_signal_unavailable"] = True
                                    graphrag_meta["impact_empty_reason"] = (
                                        graphrag_meta["impact_empty_reason"]
                                        or "graph_signal_unavailable_after_zero_impact_streak"
                                    )
                                    log(
                                        "GraphRAG signal unavailable after zero-impact selection; "
                                        "running deterministic targeted fallback tests."
                                    )
                                    deterministic = self._run_deterministic_targeted_tests(
                                        repo_path=repo_path,
                                        fail_to_pass_tests=fail_to_pass_tests,
                                        pass_to_pass_tests=pass_to_pass_tests,
                                        log=log,
                                    )
                                    if self._apply_regression_fallback_result(
                                        graphrag_meta=graphrag_meta,
                                        fallback_result=deterministic,
                                        regression_source="bounded_fallback_smoke",
                                        impact_empty_reason="graph_signal_unavailable_fallback",
                                    ):
                                        log(
                                            "Deterministic fallback tests: "
                                            f"run={graphrag_meta['impacted_run']} "
                                            f"failed={graphrag_meta['impacted_failed']}"
                                        )
                                        if (
                                            deterministic.get("execution_reliable")
                                            and deterministic.get("selected_tests")
                                        ):
                                            coverage_result = self._record_graphrag_targeted_coverage(
                                                graphrag_mcp=graphrag_mcp,
                                                repo_path=repo_path,
                                                tests=list(deterministic.get("selected_tests") or []),
                                                log=log,
                                            )
                                            if coverage_result:
                                                targeted_coverage_update_count += 1
                                                graphrag_meta["targeted_coverage_update_count"] = (
                                                    targeted_coverage_update_count
                                                )

                                continue_regression_fix, graph_execution_failed, regression_source = (
                                    self._get_regression_repair_signal(graphrag_meta)
                                )
                                regression_signal_reliable = bool(
                                    graphrag_meta.get(
                                        "regression_signal_reliable",
                                        graphrag_meta.get("impacted_execution_reliable"),
                                    )
                                )
                                should_start_regression_fix, regression_fix_reason = (
                                    self._should_start_regression_fix_round(
                                        tdd_gate_passed=tdd_gate_passed,
                                        continue_regression_fix=continue_regression_fix,
                                        regression_source=regression_source,
                                        regression_signal_reliable=regression_signal_reliable,
                                        fail_to_pass_tests=fail_to_pass_tests,
                                        current_round=regression_fix_round,
                                        max_rounds=max_regression_fix_rounds,
                                    )
                                )
                                if should_start_regression_fix and not repairable_patch_candidate:
                                    log(
                                        "Skipping regression-fix round: "
                                        f"{repairability_reason}"
                                    )
                                elif should_start_regression_fix:
                                    regression_fix_round += 1
                                    failed_for_prompt = self._build_regression_failure_prompt_tests(
                                        graphrag_meta,
                                        regression_source=regression_source,
                                        graph_execution_failed=graph_execution_failed,
                                    )
                                    current_patch_files = self._get_changed_files_any(repo_path)
                                    regression_focus_files = self._derive_repair_focus_files(
                                        repo_path=repo_path,
                                        problem_statement=problem_statement,
                                        fail_to_pass_tests=fail_to_pass_tests,
                                        changed_files=graphrag_meta.get("changed_files") or changed_files,
                                        failed_tests=failed_for_prompt,
                                        pinned_files=current_patch_files or changed_files,
                                    )
                                    regression_anchor_file = self._select_primary_focus_file(
                                        changed_files=current_patch_files or changed_files,
                                        focus_files=regression_focus_files,
                                    )
                                    task = self._format_graphrag_failure_task(
                                        problem_statement,
                                        hints_text,
                                        failed_for_prompt,
                                        regression_source=regression_source,
                                        focus_files=regression_focus_files,
                                        existing_patch_files=current_patch_files,
                                        existing_diff_excerpt=self._build_current_diff_excerpt(
                                            repo_path,
                                            changed_files=current_patch_files,
                                        ),
                                        source_excerpt=str(
                                            self._build_focus_source_excerpt(
                                                repo_path,
                                                focus_files=regression_focus_files,
                                                diff_excerpt=self._build_current_diff_excerpt(
                                                    repo_path,
                                                    changed_files=current_patch_files,
                                                ),
                                                anchor_file=regression_anchor_file,
                                                include_meta=True,
                                            ).get("excerpt", "") or ""
                                        ),
                                        verify_command=self._build_verify_command(
                                            round_mode="regression_repair",
                                            focus_files=regression_focus_files,
                                            failing_tests=[
                                                str(ft.get("full_name") or ft.get("test_name") or "").strip()
                                                for ft in failed_for_prompt
                                            ],
                                        ),
                                    )
                                    round_mode = "regression_repair"
                                    round_focus_files = regression_focus_files
                                    current_diff_excerpt = self._build_current_diff_excerpt(
                                        repo_path,
                                        changed_files=current_patch_files,
                                    )
                                    current_source_context = self._build_focus_source_excerpt(
                                        repo_path,
                                        focus_files=regression_focus_files,
                                        diff_excerpt=current_diff_excerpt,
                                        anchor_file=regression_anchor_file,
                                        include_meta=True,
                                    )
                                    current_source_excerpt = str(current_source_context.get("excerpt", "") or "")
                                    current_verify_command = self._build_verify_command(
                                        round_mode="regression_repair",
                                        focus_files=regression_focus_files,
                                        failing_tests=[
                                            str(ft.get("full_name") or ft.get("test_name") or "").strip()
                                            for ft in failed_for_prompt
                                        ],
                                    )
                                    self._log_round_context(
                                        log=log,
                                        round_mode=round_mode,
                                        focus_files=round_focus_files,
                                        verify_command=current_verify_command,
                                        diff_excerpt=current_diff_excerpt,
                                        source_excerpt=current_source_excerpt,
                                        source_context_meta=current_source_context,
                                    )
                                    log(
                                        "Continuing with regression-fix round "
                                        f"{regression_fix_round}/{max_regression_fix_rounds} "
                                        f"source={regression_source} reason={regression_fix_reason}"
                                    )
                                    continue
                                if (
                                    (graphrag_meta["impacted_failed"] > 0 or graph_execution_failed)
                                    and not regression_signal_reliable
                                ):
                                    log(
                                        "Skipping regression-fix round: infra_unreliable regression signal."
                                    )
                                elif continue_regression_fix and not should_start_regression_fix:
                                    log(
                                        "Skipping regression-fix round: "
                                        f"{regression_fix_reason}"
                                    )
                        except Exception as e:
                            graphrag_meta["indexed_search_used"] = self._resolve_indexed_signal(
                                graphrag_meta,
                                mode=indexed_signal_mode,
                            )
                            graphrag_meta["impact_empty_reason"] = str(e)
                            log(f"GraphRAG impacted test loop failed: {e}")

                    if graphrag_enabled:
                        regression_tests_run = int(graphrag_meta.get("regression_tests_run", 0) or 0)
                        regression_tests_failed = int(graphrag_meta.get("regression_tests_failed", 0) or 0)
                        regression_signal_reliable = bool(graphrag_meta.get("regression_signal_reliable"))
                        regression_gate_passed = bool(
                            regression_signal_reliable
                            and regression_tests_run > 0
                            and regression_tests_failed == 0
                        )
                        graphrag_meta["regression_gate_passed"] = regression_gate_passed
                    else:
                        graphrag_meta["regression_gate_passed"] = True

                    should_continue_tdd_fix, tdd_fix_skip_reason = self._should_continue_tdd_fix_round(
                        require_test_checks=require_test_checks,
                        f2p_total=f2p_total,
                        f2p_all_passed=f2p_all_passed,
                        f2p_reliable=(f2p_reliable_raw if f2p_reliable_raw is not None else True),
                        current_round=tdd_fix_round,
                        max_rounds=max_fix_rounds,
                        remaining_budget_sec=remaining_instance_budget,
                    )
                    test_repair_allowed, test_repair_skip_reason = self._can_enter_intra_attempt_repair(
                        graphrag_enabled=graphrag_enabled,
                        patch=patch,
                        source_changed_files=graphrag_meta.get("source_changed_files") or [],
                    )
                    if should_continue_tdd_fix and not test_repair_allowed:
                        log(f"Skipping test-fix round: {test_repair_skip_reason}")
                    elif should_continue_tdd_fix:
                        tdd_fix_round += 1
                        failed_focus_tests = [
                            {
                                "test_name": nodeid,
                                "full_name": nodeid,
                                "test_file": str(nodeid).split("::", 1)[0],
                            }
                            for nodeid in fail_to_pass_tests[:5]
                        ]
                        tdd_focus_files = self._derive_repair_focus_files(
                            repo_path=repo_path,
                            problem_statement=problem_statement,
                            fail_to_pass_tests=fail_to_pass_tests,
                            changed_files=changed_files,
                            failed_tests=failed_focus_tests,
                            pinned_files=changed_files,
                        )
                        tdd_anchor_file = self._select_primary_focus_file(
                            changed_files=changed_files,
                            focus_files=tdd_focus_files,
                        )
                        task = self._format_test_failure_task(
                            problem_statement,
                            hints_text,
                            test_metrics,
                            fail_to_pass_tests=fail_to_pass_tests,
                            focus_files=tdd_focus_files,
                            existing_diff_excerpt=self._build_current_diff_excerpt(
                                repo_path,
                                changed_files=changed_files or tdd_focus_files,
                            ),
                            source_excerpt=str(
                                self._build_focus_source_excerpt(
                                    repo_path,
                                    focus_files=tdd_focus_files,
                                    diff_excerpt=self._build_current_diff_excerpt(
                                        repo_path,
                                        changed_files=changed_files or tdd_focus_files,
                                    ),
                                    anchor_file=tdd_anchor_file,
                                    include_meta=True,
                                ).get("excerpt", "") or ""
                            ),
                            verify_command=self._build_verify_command(
                                round_mode="test_repair",
                                focus_files=tdd_focus_files,
                                failing_tests=fail_to_pass_tests,
                            ),
                        )
                        round_mode = "test_repair"
                        round_focus_files = tdd_focus_files
                        current_diff_excerpt = self._build_current_diff_excerpt(
                            repo_path,
                            changed_files=changed_files or tdd_focus_files,
                        )
                        current_source_context = self._build_focus_source_excerpt(
                            repo_path,
                            focus_files=tdd_focus_files,
                            diff_excerpt=current_diff_excerpt,
                            anchor_file=tdd_anchor_file,
                            include_meta=True,
                        )
                        current_source_excerpt = str(current_source_context.get("excerpt", "") or "")
                        current_verify_command = self._build_verify_command(
                            round_mode="test_repair",
                            focus_files=tdd_focus_files,
                            failing_tests=fail_to_pass_tests,
                        )
                        self._log_round_context(
                            log=log,
                            round_mode=round_mode,
                            focus_files=round_focus_files,
                            verify_command=current_verify_command,
                            diff_excerpt=current_diff_excerpt,
                            source_excerpt=current_source_excerpt,
                            source_context_meta=current_source_context,
                        )
                        log(f"Continuing with test-fix round {tdd_fix_round}/{max_fix_rounds}")
                        continue
                    if f2p_total > 0 and (not f2p_all_passed) and tdd_fix_skip_reason:
                        log(f"Skipping test-fix round: {tdd_fix_skip_reason}")

                    if str(run_result.get("loop_abort_reason", "")).startswith("instance_timeout"):
                        instance_timeout_reached = True
                    break

                log(
                    "PHASE: CODEGEN_END "
                    f"status={run_result.get('status', 'unknown')} "
                    f"patch_chars={len(patch)}"
                )
                test_files_changed = self._extract_test_file_changes(
                    changed_files,
                    policy=test_change_policy,
                )
                unit_test_changed = bool(test_files_changed)
                runtime_reliable_for_test_contract = self._is_runtime_reliable_for_test_contract(
                    pre_edit_repro=pre_edit_repro,
                    test_metrics=test_metrics,
                )
                require_test_change, test_change_enforcement = self._resolve_test_change_requirement(
                    tdd_mode=tdd_mode,
                    graphrag_enabled=graphrag_enabled,
                    runtime_reliable_for_test_contract=runtime_reliable_for_test_contract,
                    fail_to_pass_tests=fail_to_pass_tests,
                )
                graphrag_meta["test_files_changed"] = list(test_files_changed)
                graphrag_meta["unit_test_changed"] = bool(unit_test_changed)
                graphrag_meta["repo_test_changed"] = bool(unit_test_changed)
                graphrag_meta["runtime_reliable_for_test_contract"] = bool(
                    runtime_reliable_for_test_contract
                )
                graphrag_meta["test_change_required"] = bool(require_test_change)
                graphrag_meta["test_change_enforcement"] = str(test_change_enforcement)
                indexed_guard_blocked = False
                graph_guard_passed = True
                graph_guard_raw_passed = True
                graph_guard_reason = ""
                graph_guard_signal_shape = "none"
                graph_guard_used_either = False
                graph_guard_used_both = False
                graph_guard_bypassed_unreliable_runtime = False
                if graphrag_enabled:
                    # Additive-only guard: when graph has no useful signal,
                    # skip guard entirely so behavior matches tdd_prompt.
                    graph_has_useful_signal = bool(graphrag_meta.get("graph_useful_signal"))
                    if not graph_has_useful_signal:
                        log(
                            "Graph guard skipped: no useful signal from graph. "
                            "Passthrough to TDD prompt behavior."
                        )
                        graphrag_meta["graph_guard_passed"] = True
                        graphrag_meta["graph_guard_reason"] = "passthrough_no_useful_signal"
                        graphrag_meta["graph_guard_raw_passed"] = True
                        graphrag_meta["graph_guard_bypassed_unreliable_runtime"] = False
                        graphrag_meta["graph_guard_signal_shape"] = "none"
                        graphrag_meta["graph_guard_used_either"] = False
                        graphrag_meta["graph_guard_used_both"] = False
                    else:
                        indexed_used = self._resolve_indexed_signal(
                            graphrag_meta,
                            mode=indexed_signal_mode,
                        )
                        graphrag_meta["indexed_search_used"] = bool(indexed_used)
                        graph_guard_signal_shape = self._classify_graph_guard_signal_shape(
                            indexed_search_used=bool(indexed_used),
                            unit_test_changed=bool(unit_test_changed),
                        )
                        graph_guard_used_either = graph_guard_signal_shape != "none"
                        graph_guard_used_both = graph_guard_signal_shape == "both"
                        log(
                            "Graph guard inputs: "
                            f"mode={graph_guard_mode} "
                            f"indexed_mode={indexed_signal_mode} "
                            f"indexed_attempted={bool(graphrag_meta.get('indexed_search_attempted'))} "
                            f"indexed_success={bool(graphrag_meta.get('indexed_search_success'))} "
                            f"graph_useful={graph_has_useful_signal} "
                            f"indexed_used={indexed_used} "
                            f"test_change_policy={test_change_policy} "
                            f"unit_test_changed={unit_test_changed} "
                            f"runtime_reliable={runtime_reliable_for_test_contract}"
                        )
                        graph_guard_raw_passed, graph_guard_reason = self._evaluate_graph_guard(
                            guard_mode=graph_guard_mode,
                            indexed_search_used=indexed_used,
                            unit_test_changed=unit_test_changed,
                        )
                        graph_guard_passed = bool(graph_guard_raw_passed)
                        if indexed_used and int(graphrag_meta.get("impacted_total", 0) or 0) <= 0:
                            reason = "graph_guard_impacted_selection_missing"
                            graphrag_meta["impact_empty_reason"] = (
                                str(graphrag_meta.get("impact_empty_reason", "") or "") or reason
                            )
                            log(
                                "Graph guard note: indexed query returned zero impacted tests; "
                                "candidate will be scored down but not hard-failed."
                            )
                        if (
                            not graph_guard_passed
                            and patch
                            and tdd_mode
                            and not runtime_reliable_for_test_contract
                        ):
                            graph_guard_bypassed_unreliable_runtime = True
                            graph_guard_passed = True
                            graph_guard_reason = (
                                f"{graph_guard_reason};bypassed_unreliable_runtime"
                                if graph_guard_reason
                                else "bypassed_unreliable_runtime"
                            )
                            log(
                                "Graph guard bypassed due to runtime-unreliable TDD signal; "
                                "candidate retained for scoring."
                            )
                        graphrag_meta["graph_guard_passed"] = bool(graph_guard_passed)
                        graphrag_meta["graph_guard_reason"] = str(graph_guard_reason or "")
                        graphrag_meta["graph_guard_raw_passed"] = bool(graph_guard_raw_passed)
                        graphrag_meta["graph_guard_bypassed_unreliable_runtime"] = bool(
                            graph_guard_bypassed_unreliable_runtime
                        )
                        graphrag_meta["graph_guard_signal_shape"] = str(graph_guard_signal_shape)
                        graphrag_meta["graph_guard_used_either"] = bool(graph_guard_used_either)
                        graphrag_meta["graph_guard_used_both"] = bool(graph_guard_used_both)
                        if not graph_guard_passed:
                            indexed_guard_blocked = True
                            if patch:
                                log(
                                    "Guard: disabling candidate because GraphRAG guard failed "
                                    f"(mode={graph_guard_mode}, reason={graph_guard_reason})."
                                )
                            patch = ""
                            if not str(run_result.get("loop_abort_reason", "")):
                                run_result["loop_abort_reason"] = graph_guard_reason or "graph_guard_failed"

                tdd_evidence = self._compute_tdd_evidence(
                    tdd_mode=tdd_mode,
                    strict_tdd_evidence=strict_tdd_evidence,
                    fail_to_pass_tests=fail_to_pass_tests,
                    pass_to_pass_tests=pass_to_pass_tests,
                    pre_edit_repro=pre_edit_repro,
                    test_metrics=test_metrics,
                    patch_gate_valid=bool(last_patch_gate.get("valid", False)),
                    strict_tdd_infra_policy=strict_tdd_infra_policy,
                    require_test_change=require_test_change,
                    unit_test_changed=unit_test_changed,
                )
                if tdd_evidence.get("tdd_fail_open_applied"):
                    log(
                        "TDD evidence fail-open applied: "
                        f"infra_reasons={','.join(tdd_evidence.get('tdd_infra_reasons', [])) or 'unknown'}"
                    )
                if require_test_change and patch and not unit_test_changed:
                    patch = ""
                    if not str(run_result.get("loop_abort_reason", "")):
                        run_result["loop_abort_reason"] = "missing_repo_test_change"
                    log("Guard: disabling candidate because no repository test file was added/updated.")
                if strict_tdd_evidence and tdd_mode and patch and not bool(tdd_evidence.get("tdd_evidence_complete", False)):
                    patch = ""
                    evidence_reason = str(tdd_evidence.get("evidence_reason", "") or "tdd_evidence_incomplete")
                    if not str(run_result.get("loop_abort_reason", "")):
                        run_result["loop_abort_reason"] = evidence_reason
                    log(f"Guard: disabling candidate due to strict TDD evidence failure: {evidence_reason}")

                candidate = {
                    "attempt": attempt_idx,
                    "prediction": patch,
                    "patch_hash": hashlib.sha1(patch.encode("utf-8", errors="ignore")).hexdigest() if patch else "",
                    "diff_signature": diff_signature,
                    "changed_files": changed_files,
                    "status": run_result.get("status", "unknown"),
                    "message": run_result.get("message", ""),
                    "steps": run_result.get("steps", 0),
                    "cost": run_result.get("cost", 0.0),
                    "elapsed": run_result.get("elapsed", 0.0),
                    "format_errors": run_result.get("format_errors", 0),
                    "timeouts": run_result.get("timeouts", 0),
                    "loop_abort_reason": run_result.get("loop_abort_reason", ""),
                    "prompt_trace_id": run_result.get("prompt_trace_id", ""),
                    "prompt_budget_chars": run_result.get("prompt_budget_chars"),
                    "prompt_chars_before": run_result.get("prompt_chars_before"),
                    "prompt_chars_after": run_result.get("prompt_chars_after"),
                    "prompt_estimated_tokens_before": run_result.get("prompt_estimated_tokens_before"),
                    "prompt_estimated_tokens_after": run_result.get("prompt_estimated_tokens_after"),
                    "prompt_section_sizes_before": run_result.get("prompt_section_sizes_before", {}),
                    "prompt_section_sizes_after": run_result.get("prompt_section_sizes_after", {}),
                    "prompt_trimmed": bool(run_result.get("prompt_trimmed", False)),
                    "prompt_trimmed_sections": list(run_result.get("prompt_trimmed_sections", []) or []),
                    "mlx_backend_ready": bool(run_result.get("mlx_backend_ready", False)),
                    "mlx_backend_started_now": bool(run_result.get("mlx_backend_started_now", False)),
                    "mlx_backend_reused_existing": bool(run_result.get("mlx_backend_reused_existing", False)),
                    "mlx_backend_before": dict(run_result.get("mlx_backend_before", {}) or {}),
                    "mlx_backend_after": dict(run_result.get("mlx_backend_after", {}) or {}),
                    "mlx_backend_crash_detected": bool(run_result.get("mlx_backend_crash_detected", False)),
                    "mlx_backend_restarted": bool(run_result.get("mlx_backend_restarted", False)),
                    "mlx_backend_failure_reason": str(run_result.get("mlx_backend_failure_reason", "") or ""),
                    "f2p_passed": test_metrics.get("f2p_passed"),
                    "f2p_failed": test_metrics.get("f2p_failed"),
                    "f2p_pass_rate": test_metrics.get("f2p_pass_rate"),
                    "f2p_reliable": test_metrics.get("f2p_reliable"),
                    "f2p_infra_reason": test_metrics.get("f2p_infra_reason"),
                    "f2p_retry_variant_used": test_metrics.get("f2p_retry_variant_used"),
                    "f2p_runtime_strategy": test_metrics.get("f2p_runtime_strategy", ""),
                    "f2p_runtime_fallback_used": test_metrics.get("f2p_runtime_fallback_used", ""),
                    "f2p_runtime_unreliable_reason": test_metrics.get(
                        "f2p_runtime_unreliable_reason",
                        "",
                    ),
                    "f2p_variant_attempts": test_metrics.get("f2p_variant_attempts", []),
                    "f2p_runtime_env_id": test_metrics.get("f2p_runtime_env_id", ""),
                    "f2p_runtime_bootstrap_error": test_metrics.get("f2p_runtime_bootstrap_error", ""),
                    "f2p_runtime_bootstrap_error_reason": test_metrics.get(
                        "f2p_runtime_bootstrap_error_reason",
                        "",
                    ),
                    "f2p_runtime_install_mode": test_metrics.get("f2p_runtime_install_mode", ""),
                    "verify_cmd": test_metrics.get("verify_cmd", ""),
                    "p2p_smoke_failures": test_metrics.get("p2p_smoke_failures"),
                    "p2p_reliable": test_metrics.get("p2p_reliable"),
                    "p2p_infra_reason": test_metrics.get("p2p_infra_reason"),
                    "p2p_retry_variant_used": test_metrics.get("p2p_retry_variant_used"),
                    "p2p_runtime_strategy": test_metrics.get("p2p_runtime_strategy", ""),
                    "p2p_runtime_fallback_used": test_metrics.get("p2p_runtime_fallback_used", ""),
                    "p2p_runtime_unreliable_reason": test_metrics.get(
                        "p2p_runtime_unreliable_reason",
                        "",
                    ),
                    "p2p_variant_attempts": test_metrics.get("p2p_variant_attempts", []),
                    "p2p_runtime_env_id": test_metrics.get("p2p_runtime_env_id", ""),
                    "p2p_runtime_bootstrap_error": test_metrics.get("p2p_runtime_bootstrap_error", ""),
                    "p2p_runtime_bootstrap_error_reason": test_metrics.get(
                        "p2p_runtime_bootstrap_error_reason",
                        "",
                    ),
                    "p2p_runtime_install_mode": test_metrics.get("p2p_runtime_install_mode", ""),
                    "smoke_cmd": test_metrics.get("smoke_cmd", ""),
                    "test_signal_reliable": test_metrics.get("test_signal_reliable"),
                    "test_signal_confidence": test_metrics.get("test_signal_confidence"),
                    "clean_resolution": test_metrics.get("clean_resolution"),
                    "tdd_gate_passed": bool(tdd_gate_passed),
                    "tdd_signal_reliable": bool(tdd_signal_reliable),
                    "tdd_gate_infra_unreliable": bool(tdd_gate_infra_unreliable),
                    "regression_gate_passed": bool(graphrag_meta.get("regression_gate_passed", not graphrag_enabled)),
                    "regression_source": str(graphrag_meta.get("regression_source", "none") or "none"),
                    "regression_tests_selected": int(graphrag_meta.get("regression_tests_selected", 0) or 0),
                    "regression_tests_run": int(graphrag_meta.get("regression_tests_run", 0) or 0),
                    "regression_tests_failed": int(graphrag_meta.get("regression_tests_failed", 0) or 0),
                    "regression_signal_reliable": bool(graphrag_meta.get("regression_signal_reliable", False)),
                    "patch_gate_valid": bool(last_patch_gate.get("valid", False)),
                    "patch_gate_reason": str(last_patch_gate.get("reason", "")),
                    "patch_gate_severity": str(last_patch_gate.get("severity", "")),
                    "changed_lines_total": int(last_patch_gate.get("metrics", {}).get("changed_lines_total", 0) or 0),
                    "files_changed_count": int(last_patch_gate.get("metrics", {}).get("files_changed", 0) or 0),
                    "retry_force_strategy_shift": force_strategy_shift,
                    "compile_fix_rounds": compile_fix_round,
                    "indexed_search_guard_blocked": indexed_guard_blocked,
                    "graph_guard_mode": graph_guard_mode,
                    "graph_guard_passed": bool(graph_guard_passed),
                    "graph_guard_raw_passed": bool(graph_guard_raw_passed),
                    "graph_guard_reason": graph_guard_reason,
                    "graph_guard_signal_shape": str(graph_guard_signal_shape),
                    "graph_guard_used_either": bool(graph_guard_used_either),
                    "graph_guard_used_both": bool(graph_guard_used_both),
                    "graph_guard_bypassed_unreliable_runtime": bool(
                        graph_guard_bypassed_unreliable_runtime
                    ),
                    "test_files_changed": list(test_files_changed),
                    "indexed_search_attempted": bool(graphrag_meta.get("indexed_search_attempted")),
                    "indexed_search_success": bool(graphrag_meta.get("indexed_search_success")),
                    "indexed_query_success": bool(graphrag_meta.get("indexed_query_success")),
                    "graph_useful_signal": bool(graphrag_meta.get("graph_useful_signal")),
                    "graph_fallback_reason": str(graphrag_meta.get("graph_fallback_reason", "") or ""),
                    "graph_signal_unavailable": bool(graphrag_meta.get("graph_signal_unavailable")),
                    "graph_zero_impact_streak": int(graphrag_meta.get("graph_zero_impact_streak", 0) or 0),
                    "graph_refresh_policy": str(graphrag_meta.get("graph_refresh_policy", "") or ""),
                    "graph_initial_build_count": int(graphrag_meta.get("graph_initial_build_count", 0) or 0),
                    "graph_incremental_refresh_count": int(
                        graphrag_meta.get("graph_incremental_refresh_count", 0) or 0
                    ),
                    "graph_requery_count": int(graphrag_meta.get("graph_requery_count", 0) or 0),
                    "targeted_coverage_update_count": int(
                        graphrag_meta.get("targeted_coverage_update_count", 0) or 0
                    ),
                    "impacted_selected_count": int(graphrag_meta.get("impacted_selected_count", 0) or 0),
                    "impacted_runnable_count": int(graphrag_meta.get("impacted_runnable_count", 0) or 0),
                    "impacted_runnable_ratio": float(graphrag_meta.get("impacted_runnable_ratio", 0.0) or 0.0),
                    "impacted_precision_score": float(graphrag_meta.get("impacted_precision_score", 0.0) or 0.0),
                    "impacted_precision_floor_passed": bool(
                        graphrag_meta.get("impacted_precision_floor_passed", False)
                    ),
                    "impact_empty_reason": str(graphrag_meta.get("impact_empty_reason", "") or ""),
                    "repo_test_changed": bool(graphrag_meta.get("repo_test_changed")),
                    "runtime_reliable_for_test_contract": bool(runtime_reliable_for_test_contract),
                    "test_change_required": bool(require_test_change),
                    "test_change_enforcement": str(test_change_enforcement),
                    "repro_cmd": str(pre_edit_repro.get("command", "") or ""),
                    "repro_failed_count": int(pre_edit_repro.get("failed_count", 0) or 0),
                    "repro_total": int(pre_edit_repro.get("total", 0) or 0),
                    "repro_infra_unreliable": bool(pre_edit_repro.get("infra_unreliable")),
                    "repro_infra_reason": str(pre_edit_repro.get("infra_reason", "") or ""),
                    "repro_runtime_strategy": str(pre_edit_repro.get("runtime_strategy", "") or ""),
                    "repro_runtime_fallback_used": str(pre_edit_repro.get("runtime_fallback_used", "") or ""),
                    "repro_runtime_unreliable_reason": str(
                        pre_edit_repro.get("runtime_unreliable_reason", "") or ""
                    ),
                    "repro_runtime_env_id": str(pre_edit_repro.get("runtime_env_id", "") or ""),
                    "repro_runtime_bootstrap_error": str(pre_edit_repro.get("runtime_bootstrap_error", "") or ""),
                    "repro_runtime_bootstrap_error_reason": str(
                        pre_edit_repro.get("runtime_bootstrap_error_reason", "") or ""
                    ),
                    "repro_runtime_install_mode": str(pre_edit_repro.get("runtime_install_mode", "") or ""),
                    "repro_variant_attempts": list(pre_edit_repro.get("variant_attempts") or []),
                    "repro_cmd_present": bool(tdd_evidence.get("repro_cmd_present")),
                    "repro_failed_before_edit": bool(tdd_evidence.get("repro_failed_before_edit")),
                    "verify_cmd_present": bool(tdd_evidence.get("verify_cmd_present")),
                    "verify_pass_after_edit": bool(tdd_evidence.get("verify_pass_after_edit")),
                    "smoke_cmd_present": bool(tdd_evidence.get("smoke_cmd_present")),
                    "smoke_pass_after_edit": bool(tdd_evidence.get("smoke_pass_after_edit")),
                    "tdd_evidence_complete": bool(tdd_evidence.get("tdd_evidence_complete")),
                    "tdd_evidence_reason": str(tdd_evidence.get("evidence_reason", "")),
                    "tdd_fail_open_applied": bool(tdd_evidence.get("tdd_fail_open_applied", False)),
                    "tdd_infra_reasons": list(tdd_evidence.get("tdd_infra_reasons", [])),
                    "required_test_added": bool(tdd_evidence.get("required_test_added", True)),
                    "infra_mode_effective": str(tdd_evidence.get("infra_mode_effective", strict_tdd_infra_policy)),
                    "tdd_contract_stage": str(tdd_evidence.get("tdd_contract_stage", "")),
                    "bootstrap_fail_open_applied": bool(bootstrap_fail_open_applied),
                    "bootstrap_fail_open_reason": str(bootstrap_fail_open_reason or ""),
                    "timeout_recovered": False,
                    "timeout_recovery_source": "",
                    "graphrag_metadata": graphrag_meta,
                }
                progress_gate = self._evaluate_monotonic_progress(
                    candidate=candidate,
                    prev_candidate=attempt_candidates[-1] if attempt_candidates else None,
                )
                candidate.update(progress_gate)
                if indexed_guard_blocked:
                    candidate["patch_gate_valid"] = False
                    gate_reason = str(candidate.get("patch_gate_reason", "") or "")
                    guard_reason = str(graph_guard_reason or "graph_guard_failed")
                    candidate["patch_gate_reason"] = (
                        f"{gate_reason};{guard_reason}" if gate_reason else guard_reason
                    )
                    candidate["patch_gate_severity"] = "fail"
                if require_test_change and not bool(candidate.get("required_test_added", False)):
                    candidate["patch_gate_valid"] = False
                    gate_reason = str(candidate.get("patch_gate_reason", "") or "")
                    missing_test_reason = "missing_repo_test_change"
                    candidate["patch_gate_reason"] = (
                        f"{gate_reason};{missing_test_reason}" if gate_reason else missing_test_reason
                    )
                    candidate["patch_gate_severity"] = "fail"
                if strict_tdd_evidence and tdd_mode and not bool(candidate.get("tdd_evidence_complete")):
                    candidate["patch_gate_valid"] = False
                    gate_reason = str(candidate.get("patch_gate_reason", "") or "")
                    evidence_reason = str(candidate.get("tdd_evidence_reason", "") or "tdd_evidence_incomplete")
                    candidate["patch_gate_reason"] = (
                        f"{gate_reason};{evidence_reason}" if gate_reason else evidence_reason
                    )
                    candidate["patch_gate_severity"] = "fail"
                self._log_candidate_debug(
                    log=log,
                    prefix="ATTEMPT_CANDIDATE",
                    candidate=candidate,
                )
                log(
                    "PROGRESS_GATE "
                    f"passed={candidate['progress_gate_passed']} "
                    f"reason={candidate['progress_gate_reason']} "
                    f"signature={candidate['failure_signature']} "
                    f"stagnation={candidate['progress_gate_stagnation_count']}"
                )
                attempt_candidates.append(candidate)
                attempt_summaries.append({
                    "attempt": candidate["attempt"],
                    "status": candidate["status"],
                    "patch_chars": len(candidate["prediction"]),
                    "steps": candidate["steps"],
                    "format_errors": candidate["format_errors"],
                    "timeouts": candidate["timeouts"],
                    "loop_abort_reason": candidate["loop_abort_reason"],
                    "prompt_trace_id": candidate["prompt_trace_id"],
                    "prompt_budget_chars": candidate["prompt_budget_chars"],
                    "prompt_chars_before": candidate["prompt_chars_before"],
                    "prompt_chars_after": candidate["prompt_chars_after"],
                    "prompt_estimated_tokens_before": candidate["prompt_estimated_tokens_before"],
                    "prompt_estimated_tokens_after": candidate["prompt_estimated_tokens_after"],
                    "prompt_section_sizes_before": candidate["prompt_section_sizes_before"],
                    "prompt_section_sizes_after": candidate["prompt_section_sizes_after"],
                    "prompt_trimmed": candidate["prompt_trimmed"],
                    "prompt_trimmed_sections": candidate["prompt_trimmed_sections"],
                    "mlx_backend_ready": candidate["mlx_backend_ready"],
                    "mlx_backend_started_now": candidate["mlx_backend_started_now"],
                    "mlx_backend_reused_existing": candidate["mlx_backend_reused_existing"],
                    "mlx_backend_before": candidate["mlx_backend_before"],
                    "mlx_backend_after": candidate["mlx_backend_after"],
                    "mlx_backend_crash_detected": candidate["mlx_backend_crash_detected"],
                    "mlx_backend_restarted": candidate["mlx_backend_restarted"],
                    "mlx_backend_failure_reason": candidate["mlx_backend_failure_reason"],
                    "f2p_passed": candidate["f2p_passed"],
                    "f2p_failed": candidate["f2p_failed"],
                    "f2p_pass_rate": candidate["f2p_pass_rate"],
                    "f2p_reliable": candidate["f2p_reliable"],
                    "f2p_infra_reason": candidate["f2p_infra_reason"],
                    "f2p_retry_variant_used": candidate["f2p_retry_variant_used"],
                    "f2p_runtime_strategy": candidate["f2p_runtime_strategy"],
                    "f2p_runtime_fallback_used": candidate["f2p_runtime_fallback_used"],
                    "f2p_runtime_unreliable_reason": candidate["f2p_runtime_unreliable_reason"],
                    "f2p_runtime_env_id": candidate["f2p_runtime_env_id"],
                    "f2p_runtime_bootstrap_error": candidate["f2p_runtime_bootstrap_error"],
                    "f2p_runtime_bootstrap_error_reason": candidate["f2p_runtime_bootstrap_error_reason"],
                    "f2p_runtime_install_mode": candidate["f2p_runtime_install_mode"],
                    "verify_cmd": candidate["verify_cmd"],
                    "p2p_smoke_failures": candidate["p2p_smoke_failures"],
                    "p2p_reliable": candidate["p2p_reliable"],
                    "p2p_infra_reason": candidate["p2p_infra_reason"],
                    "p2p_retry_variant_used": candidate["p2p_retry_variant_used"],
                    "p2p_runtime_strategy": candidate["p2p_runtime_strategy"],
                    "p2p_runtime_fallback_used": candidate["p2p_runtime_fallback_used"],
                    "p2p_runtime_unreliable_reason": candidate["p2p_runtime_unreliable_reason"],
                    "p2p_runtime_env_id": candidate["p2p_runtime_env_id"],
                    "p2p_runtime_bootstrap_error": candidate["p2p_runtime_bootstrap_error"],
                    "p2p_runtime_bootstrap_error_reason": candidate["p2p_runtime_bootstrap_error_reason"],
                    "p2p_runtime_install_mode": candidate["p2p_runtime_install_mode"],
                    "smoke_cmd": candidate["smoke_cmd"],
                    "test_signal_reliable": candidate["test_signal_reliable"],
                    "test_signal_confidence": candidate["test_signal_confidence"],
                    "clean_resolution": candidate["clean_resolution"],
                    "tdd_gate_passed": candidate["tdd_gate_passed"],
                    "tdd_signal_reliable": candidate["tdd_signal_reliable"],
                    "regression_gate_passed": candidate["regression_gate_passed"],
                    "regression_source": candidate["regression_source"],
                    "regression_tests_selected": candidate["regression_tests_selected"],
                    "regression_tests_run": candidate["regression_tests_run"],
                    "regression_tests_failed": candidate["regression_tests_failed"],
                    "regression_signal_reliable": candidate["regression_signal_reliable"],
                    "patch_gate_valid": candidate["patch_gate_valid"],
                    "patch_gate_reason": candidate["patch_gate_reason"],
                    "patch_gate_severity": candidate["patch_gate_severity"],
                    "changed_lines_total": candidate["changed_lines_total"],
                    "files_changed_count": candidate["files_changed_count"],
                    "changed_files": candidate["changed_files"],
                    "retry_force_strategy_shift": candidate["retry_force_strategy_shift"],
                    "compile_fix_rounds": candidate["compile_fix_rounds"],
                    "indexed_search_guard_blocked": candidate["indexed_search_guard_blocked"],
                    "graph_guard_mode": candidate["graph_guard_mode"],
                    "graph_guard_passed": candidate["graph_guard_passed"],
                    "graph_guard_raw_passed": candidate["graph_guard_raw_passed"],
                    "graph_guard_reason": candidate["graph_guard_reason"],
                    "graph_guard_signal_shape": candidate["graph_guard_signal_shape"],
                    "graph_guard_used_either": candidate["graph_guard_used_either"],
                    "graph_guard_used_both": candidate["graph_guard_used_both"],
                    "graph_guard_bypassed_unreliable_runtime": candidate[
                        "graph_guard_bypassed_unreliable_runtime"
                    ],
                    "test_files_changed": candidate["test_files_changed"],
                    "indexed_search_attempted": candidate["indexed_search_attempted"],
                    "indexed_search_success": candidate["indexed_search_success"],
                    "indexed_query_success": candidate["indexed_query_success"],
                    "graph_useful_signal": candidate["graph_useful_signal"],
                    "graph_fallback_reason": candidate["graph_fallback_reason"],
                    "graph_signal_unavailable": candidate["graph_signal_unavailable"],
                    "graph_zero_impact_streak": candidate["graph_zero_impact_streak"],
                    "graph_refresh_policy": candidate["graph_refresh_policy"],
                    "graph_initial_build_count": candidate["graph_initial_build_count"],
                    "graph_incremental_refresh_count": candidate["graph_incremental_refresh_count"],
                    "graph_requery_count": candidate["graph_requery_count"],
                    "targeted_coverage_update_count": candidate["targeted_coverage_update_count"],
                    "impacted_selected_count": candidate["impacted_selected_count"],
                    "impacted_runnable_count": candidate["impacted_runnable_count"],
                    "impacted_runnable_ratio": candidate["impacted_runnable_ratio"],
                    "impacted_precision_score": candidate["impacted_precision_score"],
                    "impacted_precision_floor_passed": candidate["impacted_precision_floor_passed"],
                    "impact_empty_reason": candidate["impact_empty_reason"],
                    "repo_test_changed": candidate["repo_test_changed"],
                    "runtime_reliable_for_test_contract": candidate[
                        "runtime_reliable_for_test_contract"
                    ],
                    "test_change_required": candidate["test_change_required"],
                    "test_change_enforcement": candidate["test_change_enforcement"],
                    "repro_cmd": candidate["repro_cmd"],
                    "repro_failed_count": candidate["repro_failed_count"],
                    "repro_total": candidate["repro_total"],
                    "repro_infra_unreliable": candidate["repro_infra_unreliable"],
                    "repro_infra_reason": candidate["repro_infra_reason"],
                    "repro_runtime_strategy": candidate["repro_runtime_strategy"],
                    "repro_runtime_fallback_used": candidate["repro_runtime_fallback_used"],
                    "repro_runtime_unreliable_reason": candidate["repro_runtime_unreliable_reason"],
                    "repro_runtime_env_id": candidate["repro_runtime_env_id"],
                    "repro_runtime_bootstrap_error": candidate["repro_runtime_bootstrap_error"],
                    "repro_runtime_bootstrap_error_reason": candidate["repro_runtime_bootstrap_error_reason"],
                    "repro_runtime_install_mode": candidate["repro_runtime_install_mode"],
                    "repro_cmd_present": candidate["repro_cmd_present"],
                    "repro_failed_before_edit": candidate["repro_failed_before_edit"],
                    "verify_cmd_present": candidate["verify_cmd_present"],
                    "verify_pass_after_edit": candidate["verify_pass_after_edit"],
                    "smoke_cmd_present": candidate["smoke_cmd_present"],
                    "smoke_pass_after_edit": candidate["smoke_pass_after_edit"],
                    "tdd_evidence_complete": candidate["tdd_evidence_complete"],
                    "tdd_evidence_reason": candidate["tdd_evidence_reason"],
                    "tdd_fail_open_applied": candidate["tdd_fail_open_applied"],
                    "tdd_infra_reasons": candidate["tdd_infra_reasons"],
                    "required_test_added": candidate["required_test_added"],
                    "infra_mode_effective": candidate["infra_mode_effective"],
                    "tdd_contract_stage": candidate["tdd_contract_stage"],
                    "bootstrap_fail_open_applied": candidate["bootstrap_fail_open_applied"],
                    "bootstrap_fail_open_reason": candidate["bootstrap_fail_open_reason"],
                    "failure_signature": candidate["failure_signature"],
                    "progress_gate_passed": candidate["progress_gate_passed"],
                    "progress_gate_reason": candidate["progress_gate_reason"],
                    "progress_gate_stagnation_count": candidate["progress_gate_stagnation_count"],
                    "progress_gate_relocalize": candidate["progress_gate_relocalize"],
                })
                try:
                    self._append_attempt_memory(instance_id, candidate)
                except Exception as attempt_memory_exc:
                    log(f"Attempt memory write skipped: {attempt_memory_exc}")

                attempt_empty_diff = (
                    ("empty_diff" in str(candidate.get("patch_gate_reason", "")))
                    or len(candidate.get("prediction", "")) == 0
                )
                if attempt_empty_diff:
                    empty_diff_attempts += 1
                    log(
                        "Attempt produced empty diff candidate "
                        f"(streak={empty_diff_attempts}/{self.empty_diff_retry_limit})."
                    )
                else:
                    empty_diff_attempts = 0

                score = self._score_candidate(candidate)
                if self._should_replace_best_candidate(
                    candidate,
                    score,
                    best_candidate,
                    best_score,
                ):
                    best_score = score
                    best_candidate = candidate
                    log(
                        "New best candidate selected with "
                        f"score={score} "
                        f"verification_progress={self._candidate_verification_progress(candidate)}"
                    )
                    self._log_candidate_debug(
                        log=log,
                        prefix="BEST_CANDIDATE",
                        candidate=best_candidate,
                    )
                    try:
                        self._write_timeout_checkpoint(
                            instance_id=instance_id,
                            worker_pid=worker_pid,
                            candidate=best_candidate,
                        )
                    except Exception as checkpoint_exc:
                        log(f"Timeout checkpoint write skipped: {checkpoint_exc}")

                if skip_codegen_due_to_infra:
                    log("Early stop: fail-closed pre-edit infra gate triggered.")
                    break

                if attempt_empty_diff and empty_diff_attempts >= self.empty_diff_retry_limit:
                    log(
                        "Early stop: repeated empty-diff attempts reached hard limit "
                        f"({self.empty_diff_retry_limit})."
                    )
                    break

                if candidate.get("clean_resolution") is True and len(candidate["prediction"]) > 0:
                    log("Early stop: clean candidate found.")
                    break

                if self._should_stop_on_adaptive_submission(candidate):
                    log("Adaptive early stop: compile-valid low-risk submission selected.")
                    break

                compile_valid_submitted = (
                    candidate.get("status") == "Submitted"
                    and len(candidate.get("prediction", "")) > 0
                    and bool(candidate.get("patch_gate_valid"))
                    and "syntax_compile_failed" not in str(candidate.get("patch_gate_reason", ""))
                )
                if compile_valid_submitted and self._should_stop_on_compile_valid_submission(
                    candidate=candidate,
                    tdd_mode=tdd_mode,
                    graphrag_enabled=graphrag_enabled,
                ):
                    log("Early stop: compile-valid submitted patch found.")
                    break

                if instance_timeout_reached:
                    break

            except Exception as e:
                log(f"EXCEPTION: {e}")
                import traceback
                log(traceback.format_exc())
            finally:
                if repo_path and repo_path.exists():
                    try:
                        shutil.rmtree(repo_path.parent, ignore_errors=True)
                    except Exception:
                        pass
            if instance_timeout_reached:
                break

        self._save_log(instance_id, all_logs)

        if not best_candidate:
            return {
                "instance_id": instance_id,
                "prediction": "",
                "error": (
                    f"instance_timeout:{self.instance_execution_timeout_sec}s"
                    if instance_timeout_reached
                    else "No successful attempt"
                ),
                "status": "error",
                "attempts_used": len(attempt_summaries),
                "prompt_trace_id": "",
                "prompt_budget_chars": self.prompt_budget_chars,
                "prompt_chars_before": 0,
                "prompt_chars_after": 0,
                "prompt_estimated_tokens_before": 0,
                "prompt_estimated_tokens_after": 0,
                "prompt_section_sizes_before": {},
                "prompt_section_sizes_after": {},
                "prompt_trimmed": False,
                "prompt_trimmed_sections": [],
                "mlx_backend_ready": False,
                "mlx_backend_started_now": False,
                "mlx_backend_reused_existing": False,
                "mlx_backend_before": {},
                "mlx_backend_after": {},
                "mlx_backend_crash_detected": False,
                "mlx_backend_restarted": False,
                "mlx_backend_failure_reason": "",
                "patch_gate_valid": False,
                "patch_gate_reason": (
                    "instance_timeout"
                    if instance_timeout_reached
                    else "no_attempt_completed"
                ),
                "patch_gate_severity": "fail",
                "test_signal_reliable": None,
                "tdd_gate_passed": False,
                "tdd_signal_reliable": False,
                "tdd_gate_infra_unreliable": False,
                "regression_gate_passed": False,
                "regression_source": "none",
                "regression_tests_selected": 0,
                "regression_tests_run": 0,
                "regression_tests_failed": 0,
                "regression_signal_reliable": False,
                "timeout_recovered": False,
                "timeout_recovery_source": "",
                "f2p_reliable": None,
                "f2p_runtime_strategy": "",
                "f2p_runtime_fallback_used": "",
                "f2p_runtime_unreliable_reason": "",
                "f2p_runtime_env_id": "",
                "f2p_runtime_bootstrap_error": "",
                "f2p_runtime_bootstrap_error_reason": "",
                "f2p_runtime_install_mode": "",
                "p2p_reliable": None,
                "p2p_runtime_strategy": "",
                "p2p_runtime_fallback_used": "",
                "p2p_runtime_unreliable_reason": "",
                "p2p_runtime_env_id": "",
                "p2p_runtime_bootstrap_error": "",
                "p2p_runtime_bootstrap_error_reason": "",
                "p2p_runtime_install_mode": "",
                "changed_lines_total": None,
                "graph_guard_mode": graph_guard_mode,
                "graph_guard_passed": False,
                "graph_guard_raw_passed": False,
                "graph_guard_reason": "no_attempt_completed",
                "graph_guard_signal_shape": "none",
                "graph_guard_used_either": False,
                "graph_guard_used_both": False,
                "graph_guard_bypassed_unreliable_runtime": False,
                "test_files_changed": [],
                "indexed_search_attempted": False,
                "indexed_search_success": False,
                "indexed_query_success": False,
                "graph_useful_signal": False,
                "graph_fallback_reason": "",
                "graph_signal_unavailable": False,
                "graph_zero_impact_streak": 0,
                "graph_refresh_policy": graph_refresh_policy,
                "graph_initial_build_count": graph_initial_build_count,
                "graph_incremental_refresh_count": graph_incremental_refresh_count,
                "graph_requery_count": graph_requery_count,
                "targeted_coverage_update_count": targeted_coverage_update_count,
                "impacted_selected_count": 0,
                "impacted_runnable_count": 0,
                "impacted_runnable_ratio": 0.0,
                "impacted_precision_score": 0.0,
                "impacted_precision_floor_passed": False,
                "impact_empty_reason": "no_attempt_completed",
                "repo_test_changed": False,
                "runtime_reliable_for_test_contract": False,
                "test_change_required": False,
                "test_change_enforcement": "not_applicable",
                "repro_cmd": "",
                "repro_failed_count": 0,
                "repro_total": 0,
                "repro_infra_unreliable": False,
                "repro_infra_reason": "",
                "repro_runtime_strategy": "",
                "repro_runtime_fallback_used": "",
                "repro_runtime_unreliable_reason": "",
                "repro_runtime_env_id": "",
                "repro_runtime_bootstrap_error": "",
                "repro_runtime_bootstrap_error_reason": "",
                "repro_runtime_install_mode": "",
                "repro_cmd_present": False,
                "repro_failed_before_edit": False,
                "verify_cmd_present": False,
                "verify_pass_after_edit": False,
                "smoke_cmd_present": False,
                "smoke_pass_after_edit": False,
                "tdd_evidence_complete": False,
                "tdd_evidence_reason": "no_attempt_completed",
                "tdd_fail_open_applied": False,
                "tdd_infra_reasons": [],
                "required_test_added": False,
                "infra_mode_effective": strict_tdd_infra_policy,
                "tdd_contract_stage": "incomplete",
                "bootstrap_fail_open_applied": False,
                "bootstrap_fail_open_reason": "",
                "attempt_summaries": attempt_summaries,
            }

        return {
            "instance_id": instance_id,
            "prediction": best_candidate.get("prediction", ""),
            "status": best_candidate.get("status", "unknown"),
            "message": best_candidate.get("message", ""),
            "steps": best_candidate.get("steps", 0),
            "cost": best_candidate.get("cost", 0.0),
            "elapsed": best_candidate.get("elapsed", 0.0),
            "format_errors": best_candidate.get("format_errors", 0),
            "timeouts": best_candidate.get("timeouts", 0),
            "attempts_used": len(attempt_summaries),
            "loop_abort_reason": best_candidate.get("loop_abort_reason", ""),
            "prompt_trace_id": best_candidate.get("prompt_trace_id", ""),
            "prompt_budget_chars": best_candidate.get("prompt_budget_chars"),
            "prompt_chars_before": best_candidate.get("prompt_chars_before"),
            "prompt_chars_after": best_candidate.get("prompt_chars_after"),
            "prompt_estimated_tokens_before": best_candidate.get("prompt_estimated_tokens_before"),
            "prompt_estimated_tokens_after": best_candidate.get("prompt_estimated_tokens_after"),
            "prompt_section_sizes_before": best_candidate.get("prompt_section_sizes_before", {}),
            "prompt_section_sizes_after": best_candidate.get("prompt_section_sizes_after", {}),
            "prompt_trimmed": best_candidate.get("prompt_trimmed", False),
            "prompt_trimmed_sections": best_candidate.get("prompt_trimmed_sections", []),
            "mlx_backend_ready": best_candidate.get("mlx_backend_ready", False),
            "mlx_backend_started_now": best_candidate.get("mlx_backend_started_now", False),
            "mlx_backend_reused_existing": best_candidate.get("mlx_backend_reused_existing", False),
            "mlx_backend_before": best_candidate.get("mlx_backend_before", {}),
            "mlx_backend_after": best_candidate.get("mlx_backend_after", {}),
            "mlx_backend_crash_detected": best_candidate.get("mlx_backend_crash_detected", False),
            "mlx_backend_restarted": best_candidate.get("mlx_backend_restarted", False),
            "mlx_backend_failure_reason": best_candidate.get("mlx_backend_failure_reason", ""),
            "f2p_pass_rate": best_candidate.get("f2p_pass_rate"),
            "f2p_reliable": best_candidate.get("f2p_reliable"),
            "f2p_infra_reason": best_candidate.get("f2p_infra_reason"),
            "f2p_retry_variant_used": best_candidate.get("f2p_retry_variant_used"),
            "f2p_runtime_strategy": best_candidate.get("f2p_runtime_strategy", ""),
            "f2p_runtime_fallback_used": best_candidate.get("f2p_runtime_fallback_used", ""),
            "f2p_runtime_unreliable_reason": best_candidate.get("f2p_runtime_unreliable_reason", ""),
            "f2p_runtime_env_id": best_candidate.get("f2p_runtime_env_id", ""),
            "f2p_runtime_bootstrap_error": best_candidate.get("f2p_runtime_bootstrap_error", ""),
            "f2p_runtime_bootstrap_error_reason": best_candidate.get(
                "f2p_runtime_bootstrap_error_reason",
                "",
            ),
            "f2p_runtime_install_mode": best_candidate.get("f2p_runtime_install_mode", ""),
            "verify_cmd": best_candidate.get("verify_cmd", ""),
            "p2p_smoke_failures": best_candidate.get("p2p_smoke_failures"),
            "p2p_reliable": best_candidate.get("p2p_reliable"),
            "p2p_infra_reason": best_candidate.get("p2p_infra_reason"),
            "p2p_retry_variant_used": best_candidate.get("p2p_retry_variant_used"),
            "p2p_runtime_strategy": best_candidate.get("p2p_runtime_strategy", ""),
            "p2p_runtime_fallback_used": best_candidate.get("p2p_runtime_fallback_used", ""),
            "p2p_runtime_unreliable_reason": best_candidate.get("p2p_runtime_unreliable_reason", ""),
            "p2p_runtime_env_id": best_candidate.get("p2p_runtime_env_id", ""),
            "p2p_runtime_bootstrap_error": best_candidate.get("p2p_runtime_bootstrap_error", ""),
            "p2p_runtime_bootstrap_error_reason": best_candidate.get(
                "p2p_runtime_bootstrap_error_reason",
                "",
            ),
            "p2p_runtime_install_mode": best_candidate.get("p2p_runtime_install_mode", ""),
            "smoke_cmd": best_candidate.get("smoke_cmd", ""),
            "test_signal_reliable": best_candidate.get("test_signal_reliable"),
            "test_signal_confidence": best_candidate.get("test_signal_confidence"),
            "clean_resolution": best_candidate.get("clean_resolution"),
            "tdd_gate_passed": best_candidate.get("tdd_gate_passed"),
            "tdd_signal_reliable": best_candidate.get("tdd_signal_reliable"),
            "tdd_gate_infra_unreliable": best_candidate.get("tdd_gate_infra_unreliable"),
            "regression_gate_passed": best_candidate.get("regression_gate_passed"),
            "regression_source": best_candidate.get("regression_source"),
            "regression_tests_selected": best_candidate.get("regression_tests_selected"),
            "regression_tests_run": best_candidate.get("regression_tests_run"),
            "regression_tests_failed": best_candidate.get("regression_tests_failed"),
            "regression_signal_reliable": best_candidate.get("regression_signal_reliable"),
            "timeout_recovered": best_candidate.get("timeout_recovered", False),
            "timeout_recovery_source": best_candidate.get("timeout_recovery_source", ""),
            "patch_gate_valid": best_candidate.get("patch_gate_valid"),
            "patch_gate_reason": best_candidate.get("patch_gate_reason"),
            "patch_gate_severity": best_candidate.get("patch_gate_severity"),
            "changed_lines_total": best_candidate.get("changed_lines_total"),
            "compile_fix_rounds": best_candidate.get("compile_fix_rounds", 0),
            "graph_guard_mode": best_candidate.get("graph_guard_mode"),
            "graph_guard_passed": best_candidate.get("graph_guard_passed"),
            "graph_guard_raw_passed": best_candidate.get("graph_guard_raw_passed"),
            "graph_guard_reason": best_candidate.get("graph_guard_reason"),
            "graph_guard_signal_shape": best_candidate.get("graph_guard_signal_shape"),
            "graph_guard_used_either": best_candidate.get("graph_guard_used_either"),
            "graph_guard_used_both": best_candidate.get("graph_guard_used_both"),
            "graph_guard_bypassed_unreliable_runtime": best_candidate.get(
                "graph_guard_bypassed_unreliable_runtime",
                False,
            ),
            "test_files_changed": best_candidate.get("test_files_changed", []),
            "indexed_search_attempted": best_candidate.get("indexed_search_attempted"),
            "indexed_search_success": best_candidate.get("indexed_search_success"),
            "indexed_query_success": best_candidate.get("indexed_query_success", False),
            "graph_useful_signal": best_candidate.get("graph_useful_signal", False),
            "graph_fallback_reason": best_candidate.get("graph_fallback_reason", ""),
            "graph_signal_unavailable": best_candidate.get("graph_signal_unavailable", False),
            "graph_zero_impact_streak": best_candidate.get("graph_zero_impact_streak", 0),
            "graph_refresh_policy": best_candidate.get("graph_refresh_policy", ""),
            "graph_initial_build_count": best_candidate.get("graph_initial_build_count", 0),
            "graph_incremental_refresh_count": best_candidate.get(
                "graph_incremental_refresh_count",
                0,
            ),
            "graph_requery_count": best_candidate.get("graph_requery_count", 0),
            "targeted_coverage_update_count": best_candidate.get(
                "targeted_coverage_update_count",
                0,
            ),
            "impacted_selected_count": best_candidate.get("impacted_selected_count", 0),
            "impacted_runnable_count": best_candidate.get("impacted_runnable_count", 0),
            "impacted_runnable_ratio": best_candidate.get("impacted_runnable_ratio", 0.0),
            "impacted_precision_score": best_candidate.get("impacted_precision_score", 0.0),
            "impacted_precision_floor_passed": best_candidate.get(
                "impacted_precision_floor_passed",
                False,
            ),
            "impact_empty_reason": best_candidate.get("impact_empty_reason", ""),
            "repo_test_changed": best_candidate.get("repo_test_changed"),
            "runtime_reliable_for_test_contract": best_candidate.get(
                "runtime_reliable_for_test_contract",
                False,
            ),
            "test_change_required": best_candidate.get("test_change_required", False),
            "test_change_enforcement": best_candidate.get(
                "test_change_enforcement",
                "not_applicable",
            ),
            "repro_cmd": best_candidate.get("repro_cmd", ""),
            "repro_failed_count": best_candidate.get("repro_failed_count"),
            "repro_total": best_candidate.get("repro_total"),
            "repro_infra_unreliable": best_candidate.get("repro_infra_unreliable"),
            "repro_infra_reason": best_candidate.get("repro_infra_reason", ""),
            "repro_runtime_strategy": best_candidate.get("repro_runtime_strategy", ""),
            "repro_runtime_fallback_used": best_candidate.get("repro_runtime_fallback_used", ""),
            "repro_runtime_unreliable_reason": best_candidate.get("repro_runtime_unreliable_reason", ""),
            "repro_runtime_env_id": best_candidate.get("repro_runtime_env_id", ""),
            "repro_runtime_bootstrap_error": best_candidate.get("repro_runtime_bootstrap_error", ""),
            "repro_runtime_bootstrap_error_reason": best_candidate.get(
                "repro_runtime_bootstrap_error_reason",
                "",
            ),
            "repro_runtime_install_mode": best_candidate.get("repro_runtime_install_mode", ""),
            "repro_cmd_present": best_candidate.get("repro_cmd_present"),
            "repro_failed_before_edit": best_candidate.get("repro_failed_before_edit"),
            "verify_cmd_present": best_candidate.get("verify_cmd_present"),
            "verify_pass_after_edit": best_candidate.get("verify_pass_after_edit"),
            "smoke_cmd_present": best_candidate.get("smoke_cmd_present"),
            "smoke_pass_after_edit": best_candidate.get("smoke_pass_after_edit"),
            "tdd_evidence_complete": best_candidate.get("tdd_evidence_complete"),
            "tdd_evidence_reason": best_candidate.get("tdd_evidence_reason"),
            "tdd_fail_open_applied": best_candidate.get("tdd_fail_open_applied"),
            "tdd_infra_reasons": best_candidate.get("tdd_infra_reasons", []),
            "required_test_added": best_candidate.get("required_test_added", True),
            "infra_mode_effective": best_candidate.get("infra_mode_effective", ""),
            "tdd_contract_stage": best_candidate.get("tdd_contract_stage", ""),
            "bootstrap_fail_open_applied": best_candidate.get("bootstrap_fail_open_applied", False),
            "bootstrap_fail_open_reason": best_candidate.get("bootstrap_fail_open_reason", ""),
            "attempt_summaries": attempt_summaries,
            "graphrag_metadata": best_candidate.get("graphrag_metadata", {}),
        }

    def _should_stop_on_compile_valid_submission(
        self,
        candidate: dict[str, Any],
        tdd_mode: bool,
        graphrag_enabled: bool,
    ) -> bool:
        """Control whether compile-valid submitted patches should short-circuit retries."""
        if not self.compile_valid_submit_stop:
            return False
        if tdd_mode and candidate.get("tdd_gate_passed") is False:
            return False
        if graphrag_enabled and candidate.get("regression_gate_passed") is False:
            return False
        # Any compile-valid submitted patch is eligible to short-circuit retries.
        # Compile-invalid submissions continue via compile-fix rounds / next attempts.
        return True

    def _should_stop_on_adaptive_submission(self, candidate: dict[str, Any]) -> bool:
        """Adaptive early stop once we have a low-risk compile-valid submitted patch."""
        if self.retry_policy != "adaptive":
            return False
        if candidate.get("tdd_gate_passed") is False:
            return False
        if candidate.get("regression_gate_passed") is False:
            return False
        if candidate.get("status") != "Submitted":
            return False
        if len(candidate.get("prediction", "")) == 0:
            return False
        if not bool(candidate.get("patch_gate_valid")):
            return False
        if candidate.get("loop_abort_reason"):
            return False
        gate_reason = str(candidate.get("patch_gate_reason", ""))
        if "potential_signature_change" in gate_reason or "too_many_changed_lines" in gate_reason:
            return False
        changed_lines = int(candidate.get("changed_lines_total") or 0)
        if changed_lines <= 0:
            return False
        return changed_lines <= self.adaptive_good_patch_max_changed_lines

    def _estimate_attempt_similarity(self, a: dict[str, Any], b: dict[str, Any]) -> float:
        """Estimate similarity between two attempts to detect repeated trajectories."""
        if not a or not b:
            return 0.0
        if a.get("diff_signature") and a.get("diff_signature") == b.get("diff_signature"):
            return 1.0
        files_a = set(a.get("changed_files") or [])
        files_b = set(b.get("changed_files") or [])
        if files_a or files_b:
            inter = len(files_a & files_b)
            union = len(files_a | files_b)
            file_overlap = inter / union if union else 0.0
        else:
            file_overlap = 0.0
        len_a = len(a.get("prediction", ""))
        len_b = len(b.get("prediction", ""))
        if len_a > 0 and len_b > 0:
            size_ratio = min(len_a, len_b) / max(len_a, len_b)
        else:
            size_ratio = 0.0
        hash_match = 1.0 if a.get("patch_hash") and a.get("patch_hash") == b.get("patch_hash") else 0.0
        return max(hash_match, (0.65 * file_overlap) + (0.35 * size_ratio))

    def _resolve_round_control_profile(self, round_mode: str) -> dict[str, Any]:
        """Return loop-control thresholds for the current agent round."""
        normalized_mode = str(round_mode or "default").strip().lower() or "default"

        def _round_int(name: str, fallback: int, *, minimum: int = 0) -> int:
            env_name = f"QWEN_MINI_{normalized_mode.upper()}_{name.upper()}"
            if normalized_mode == "default":
                return _read_int_env(os.getenv(env_name), fallback, minimum=minimum)
            override = (self.round_control_defaults.get(normalized_mode) or {}).get(name)
            return _read_int_env(os.getenv(env_name), override if override is not None else fallback, minimum=minimum)

        if normalized_mode == "regression_repair":
            return {
                "round_mode": normalized_mode,
                "search_streak_limit": _round_int(
                    "search_streak_limit",
                    3,
                    minimum=1,
                ),
                "max_read_only_steps_before_edit": _round_int(
                    "max_read_only_steps_before_edit",
                    3,
                    minimum=1,
                ),
                "require_first_edit_by_step": _round_int(
                    "require_first_edit_by_step",
                    5,
                    minimum=1,
                ),
                "no_edit_progress_step_limit": _round_int(
                    "no_edit_progress_step_limit",
                    min(int(self.no_edit_progress_step_limit), 10),
                    minimum=1,
                ),
                "env_bootstrap_fail_limit": max(1, int(self.env_bootstrap_fail_limit or 0)),
                "max_retries": 1,
                "exploratory_pre_edit_limit": _round_int(
                    "exploratory_pre_edit_limit",
                    1,
                    minimum=0,
                ),
                "require_direct_edit_first": False,
                "block_scratch_python_before_edit": True,
                "blocked_guard_abort_limit": _round_int(
                    "blocked_guard_abort_limit",
                    3,
                    minimum=0,
                ),
            }
        if normalized_mode == "compile_repair":
            return {
                "round_mode": normalized_mode,
                "search_streak_limit": _round_int(
                    "search_streak_limit",
                    2,
                    minimum=1,
                ),
                "max_read_only_steps_before_edit": _round_int(
                    "max_read_only_steps_before_edit",
                    2,
                    minimum=1,
                ),
                "require_first_edit_by_step": _round_int(
                    "require_first_edit_by_step",
                    4,
                    minimum=1,
                ),
                "no_edit_progress_step_limit": _round_int(
                    "no_edit_progress_step_limit",
                    min(int(self.no_edit_progress_step_limit), 8),
                    minimum=1,
                ),
                "env_bootstrap_fail_limit": max(1, int(self.env_bootstrap_fail_limit or 0)),
                "max_retries": 1,
                "exploratory_pre_edit_limit": _round_int(
                    "exploratory_pre_edit_limit",
                    1,
                    minimum=0,
                ),
                "require_direct_edit_first": False,
                "block_scratch_python_before_edit": True,
                "blocked_guard_abort_limit": _round_int(
                    "blocked_guard_abort_limit",
                    3,
                    minimum=0,
                ),
            }
        if normalized_mode == "retry_refine":
            return {
                "round_mode": normalized_mode,
                "search_streak_limit": _round_int(
                    "search_streak_limit",
                    4,
                    minimum=1,
                ),
                "max_read_only_steps_before_edit": _round_int(
                    "max_read_only_steps_before_edit",
                    4,
                    minimum=1,
                ),
                "require_first_edit_by_step": _round_int(
                    "require_first_edit_by_step",
                    6,
                    minimum=1,
                ),
                "no_edit_progress_step_limit": _round_int(
                    "no_edit_progress_step_limit",
                    min(int(self.no_edit_progress_step_limit), 12),
                    minimum=1,
                ),
                "env_bootstrap_fail_limit": max(1, int(self.env_bootstrap_fail_limit or 0)),
                "max_retries": 1,
                "exploratory_pre_edit_limit": _round_int(
                    "exploratory_pre_edit_limit",
                    2,
                    minimum=0,
                ),
                "require_direct_edit_first": False,
                "block_scratch_python_before_edit": True,
                "blocked_guard_abort_limit": _round_int(
                    "blocked_guard_abort_limit",
                    2,
                    minimum=0,
                ),
            }
        is_repair_round = normalized_mode in {
            "test_repair",
        }
        if not is_repair_round:
            return {
                "round_mode": "default",
                "search_streak_limit": _round_int(
                    "search_streak_limit",
                    int(self.search_streak_limit),
                    minimum=1,
                ),
                "max_read_only_steps_before_edit": _round_int(
                    "max_read_only_steps_before_edit",
                    int(self.max_read_only_steps_before_edit),
                    minimum=1,
                ),
                "require_first_edit_by_step": _round_int(
                    "require_first_edit_by_step",
                    int(self.require_first_edit_by_step),
                    minimum=1,
                ),
                "no_edit_progress_step_limit": _round_int(
                    "no_edit_progress_step_limit",
                    int(self.no_edit_progress_step_limit),
                    minimum=1,
                ),
                "env_bootstrap_fail_limit": int(self.env_bootstrap_fail_limit),
                "max_retries": 2,
                "exploratory_pre_edit_limit": 0,
                "require_direct_edit_first": False,
                "block_scratch_python_before_edit": False,
                "blocked_guard_abort_limit": 0,
            }
        return {
            "round_mode": normalized_mode,
            "search_streak_limit": _round_int(
                "search_streak_limit",
                3,
                minimum=1,
            ),
            "max_read_only_steps_before_edit": _round_int(
                "max_read_only_steps_before_edit",
                3,
                minimum=1,
            ),
            "require_first_edit_by_step": _round_int(
                "require_first_edit_by_step",
                5,
                minimum=1,
            ),
            "no_edit_progress_step_limit": _round_int(
                "no_edit_progress_step_limit",
                min(int(self.no_edit_progress_step_limit), 10),
                minimum=1,
            ),
            "env_bootstrap_fail_limit": max(1, int(self.env_bootstrap_fail_limit or 0)),
            "max_retries": 1,
            "exploratory_pre_edit_limit": _round_int(
                "exploratory_pre_edit_limit",
                1,
                minimum=0,
            ),
            "require_direct_edit_first": False,
            "block_scratch_python_before_edit": True,
            "blocked_guard_abort_limit": _round_int(
                "blocked_guard_abort_limit",
                3,
                minimum=0,
            ),
        }

    def _is_test_like_file(self, path: str) -> bool:
        lower_path = str(path or "").strip().lower().replace("\\", "/")
        if not lower_path.endswith(".py"):
            return False
        file_name = lower_path.rsplit("/", 1)[-1]
        path_parts = [part for part in lower_path.split("/") if part]
        return (
            any(part in {"tests", "testing"} for part in path_parts)
            or file_name.startswith("test_")
            or file_name.endswith("_test.py")
            or "/test/" in lower_path
        )

    def _derive_source_candidate_from_test_file(self, repo_path: Path, test_file: str) -> list[str]:
        """Infer likely source files from a repository test path."""
        repo_root = repo_path.resolve()
        test_path = str(test_file or "").strip().replace("\\", "/")
        if not test_path.endswith(".py"):
            return []

        candidates: list[str] = []

        def _add(candidate: str) -> None:
            rel = str(candidate or "").strip().lstrip("./")
            if not rel.endswith(".py"):
                return
            abs_path = (repo_root / rel).resolve(strict=False)
            try:
                abs_path.relative_to(repo_root)
            except Exception:
                return
            if abs_path.exists() and abs_path.is_file():
                rel_path = abs_path.relative_to(repo_root).as_posix()
                if rel_path not in candidates:
                    candidates.append(rel_path)

        if "/tests/" in test_path:
            prefix, suffix = test_path.split("/tests/", 1)
            file_name = suffix.rsplit("/", 1)[-1]
            source_dir = prefix
            if file_name.startswith("test_"):
                _add(f"{source_dir}/{file_name[5:]}")
            if file_name.endswith("_test.py"):
                _add(f"{source_dir}/{file_name[:-8]}.py")

        file_name = test_path.rsplit("/", 1)[-1]
        parent_dir = test_path.rsplit("/", 1)[0] if "/" in test_path else ""
        if file_name.startswith("test_") and parent_dir:
            _add(f"{parent_dir}/{file_name[5:]}")
        if file_name.endswith("_test.py") and parent_dir:
            _add(f"{parent_dir}/{file_name[:-8]}.py")

        abs_test_path = (repo_root / test_path.lstrip("./")).resolve(strict=False)
        if abs_test_path.exists() and abs_test_path.is_file():
            try:
                test_text = abs_test_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                test_text = ""
            for line in test_text.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                import_match = re.match(r"from\s+([A-Za-z0-9_.]+)\s+import\s+(.+)", stripped)
                if import_match:
                    module = str(import_match.group(1) or "").strip()
                    imported = str(import_match.group(2) or "")
                    module_path = module.replace(".", "/")
                    _add(f"{module_path}.py")
                    _add(f"{module_path}/__init__.py")
                    package_dir = (repo_root / module_path).resolve(strict=False)
                    if package_dir.exists() and package_dir.is_dir():
                        cleaned = imported.replace("(", "").replace(")", "")
                        for raw_name in cleaned.split(","):
                            token = str(raw_name or "").strip()
                            if not token or token == "*":
                                continue
                            name = token.split(" as ", 1)[0].strip()
                            if not name:
                                continue
                            _add(f"{module_path}/{name}.py")
                            _add(f"{module_path}/{name.lower()}.py")
                    continue
                plain_match = re.match(r"import\s+([A-Za-z0-9_.]+)", stripped)
                if plain_match:
                    module = str(plain_match.group(1) or "").strip()
                    module_path = module.replace(".", "/")
                    _add(f"{module_path}.py")
                    _add(f"{module_path}/__init__.py")

        return candidates

    def _prioritize_focus_files(
        self,
        files: list[str],
        *,
        max_files: int = 6,
        pinned_files: Optional[list[str]] = None,
    ) -> list[str]:
        """Prefer likely source files before tests/debug helpers for edit-first rounds."""
        normalized: list[str] = []
        pinned: list[str] = []
        seen: set[str] = set()

        def _add(raw_path: str, target: list[str]) -> None:
            path = str(raw_path or "").strip().lstrip("./").replace("\\", "/")
            if not path or path in seen:
                return
            if self._is_repair_noise_python_file(path):
                return
            seen.add(path)
            target.append(path)

        for raw_path in pinned_files or []:
            _add(raw_path, pinned)
        for raw_path in files or []:
            _add(raw_path, normalized)

        def _rank(path: str) -> tuple[int, int]:
            lower_path = path.lower()
            file_name = lower_path.rsplit("/", 1)[-1]
            path_parts = [part for part in lower_path.split("/") if part]
            in_test_dir = any(part in {"tests", "testing"} for part in path_parts)
            is_test_name = file_name.startswith("test_") or file_name.endswith("_test.py")
            is_noise = self._is_repair_noise_python_file(path)
            is_package_init = file_name == "__init__.py"
            if is_noise:
                return (4, len(path_parts))
            if in_test_dir or is_test_name or "/test/" in lower_path:
                return (3, len(path_parts))
            if is_package_init:
                return (1, len(path_parts))
            return (0, len(path_parts))

        prioritized = pinned + sorted(normalized, key=_rank)
        return prioritized[: max(1, int(max_files or 6))]

    def _select_primary_focus_file(
        self,
        *,
        changed_files: Optional[list[str]] = None,
        focus_files: Optional[list[str]] = None,
    ) -> str:
        changed = [
            str(path).strip().lstrip("./").replace("\\", "/")
            for path in (changed_files or [])
            if str(path).strip()
        ]
        focus = [
            str(path).strip().lstrip("./").replace("\\", "/")
            for path in (focus_files or [])
            if str(path).strip()
        ]
        for candidate in changed:
            if (
                candidate.endswith(".py")
                and not self._is_test_like_file(candidate)
                and os.path.basename(candidate) != "__init__.py"
            ):
                return candidate
        for candidate in changed:
            if candidate.endswith(".py"):
                return candidate
        for candidate in focus:
            if (
                candidate.endswith(".py")
                and not self._is_test_like_file(candidate)
                and os.path.basename(candidate) != "__init__.py"
            ):
                return candidate
        for candidate in focus:
            if candidate.endswith(".py"):
                return candidate
        return ""

    def _derive_repair_focus_files(
        self,
        *,
        repo_path: Path,
        problem_statement: str,
        fail_to_pass_tests: list[str],
        changed_files: Optional[list[str]] = None,
        failed_tests: Optional[list[dict[str, Any]]] = None,
        max_files: int = 6,
        pinned_files: Optional[list[str]] = None,
    ) -> list[str]:
        """Derive likely files for a repair round from repro/tests/changed files."""
        repo_root = repo_path.resolve()
        candidates: list[str] = []
        seen: set[str] = set()

        def _add(candidate: str) -> None:
            path_text = str(candidate or "").strip()
            if not path_text:
                return
            rel_text = path_text
            if path_text.startswith(str(repo_root)):
                rel_text = os.path.relpath(path_text, repo_root)
            rel_text = rel_text.lstrip("./").replace("\\", "/")
            if not rel_text.endswith(".py"):
                return
            abs_path = (repo_root / rel_text).resolve(strict=False)
            try:
                abs_path.relative_to(repo_root)
            except Exception:
                return
            if not abs_path.exists() or not abs_path.is_file():
                return
            rel_norm = abs_path.relative_to(repo_root).as_posix()
            if self._is_repair_noise_python_file(rel_norm):
                return
            if rel_norm in seen:
                return
            seen.add(rel_norm)
            candidates.append(rel_norm)

        for path in changed_files or []:
            _add(path)

        for nodeid in fail_to_pass_tests or []:
            test_file = str(nodeid or "").split("::", 1)[0].strip()
            if not test_file.endswith(".py"):
                continue
            for source_candidate in self._derive_source_candidate_from_test_file(repo_path, test_file):
                _add(source_candidate)
            _add(test_file)

        for path in self._derive_graphrag_seed_files(
            repo_path=repo_path,
            problem_statement=problem_statement,
            fail_to_pass_tests=fail_to_pass_tests,
            max_files=max_files,
        ):
            _add(path)

        for failed in failed_tests or []:
            test_file = str(failed.get("test_file") or "").strip()
            if test_file:
                for source_candidate in self._derive_source_candidate_from_test_file(repo_path, test_file):
                    _add(source_candidate)
                _add(test_file)

        return self._prioritize_focus_files(
            candidates,
            max_files=max_files,
            pinned_files=pinned_files or changed_files,
        )

    def _repair_round_scratch_python_target(
        self,
        *,
        command: str,
        repo_path: Path,
        focus_files: Optional[list[str]] = None,
    ) -> str:
        """Return the created python target path when a repair-round scratch file is detected."""
        command_text = str(command or "").strip()
        if not command_text:
            return ""
        patterns = (
            r"\bcat\s+>\>?\s*([^\s;&|]+\.py)\b",
            r"\btee\s+([^\s;&|]+\.py)\b",
        )
        target = ""
        for pattern in patterns:
            match = re.search(pattern, command_text)
            if match:
                target = str(match.group(1) or "").strip().strip("'\"")
                if target:
                    break
        if not target:
            return ""

        repo_root = repo_path.resolve()
        abs_target = (
            Path(target).expanduser().resolve(strict=False)
            if Path(target).is_absolute()
            else (repo_root / target).resolve(strict=False)
        )
        try:
            rel_target = abs_target.relative_to(repo_root).as_posix()
        except Exception:
            return target

        if self._is_repair_noise_python_file(rel_target):
            return rel_target
        if rel_target in {str(path).strip().lstrip("./").replace("\\", "/") for path in (focus_files or [])}:
            return ""
        if abs_target.exists():
            return ""
        path_parts = {part.lower() for part in abs_target.parts}
        if "tests" in path_parts or "testing" in path_parts:
            return ""
        return rel_target

    def _should_continue_compile_fix_round(
        self,
        *,
        run_status: str,
        compile_failed: int,
        patch: str,
        current_round: int,
        max_rounds: int,
    ) -> tuple[bool, str]:
        """Decide whether to enter compile repair for a non-empty broken patch."""
        if compile_failed <= 0:
            return False, "no_compile_failures"
        if not str(patch or "").strip():
            return False, "empty_patch"
        if current_round >= max_rounds:
            return False, "round_limit_reached"
        status = str(run_status or "").strip() or "unknown"
        if status not in {"Submitted", "LoopAborted"}:
            return False, f"status={status}"
        return True, "compile_failures_present"

    def _compile_repair_patch_source(
        self,
        *,
        patch: str,
        last_patch_gate: Optional[dict[str, Any]] = None,
    ) -> str:
        patch_text = str(patch or "")
        if patch_text.strip():
            return patch_text
        gate = dict(last_patch_gate or {})
        compile_gate = dict(gate.get("compile_gate") or {})
        compile_failed = int(compile_gate.get("compile_failed", 0) or 0)
        raw_diff = str(gate.get("diff", "") or "")
        if compile_failed > 0 and raw_diff.strip():
            return raw_diff
        return patch_text

    def _should_start_regression_fix_round(
        self,
        *,
        tdd_gate_passed: bool,
        continue_regression_fix: bool,
        regression_source: str,
        regression_signal_reliable: bool,
        fail_to_pass_tests: list[str],
        current_round: int,
        max_rounds: int,
    ) -> tuple[bool, str]:
        """Decide whether GraphRAG/fallback regression failures should drive a repair round."""
        if not continue_regression_fix:
            return False, "no_reliable_regression_signal"
        if current_round >= max_rounds:
            return False, "round_limit_reached"
        if tdd_gate_passed:
            return True, "tdd_gate_passed"
        if (
            regression_signal_reliable
            and bool(fail_to_pass_tests)
            and self._is_fallback_regression_source(regression_source)
        ):
            return True, "fallback_signal_guided_red_repro"
        return False, "tdd_gate_failed"

    def _run_agent_with_controls(
        self,
        agent: DefaultAgent,
        task: str,
        repo_path: Path,
        log=print,
        run_timeout_sec: Optional[int] = None,
        round_mode: str = "default",
        focus_files: Optional[list[str]] = None,
        pre_edit_infra_unreliable: bool = False,
    ) -> dict[str, Any]:
        """Run a single agent task with hard loop controls."""
        round_profile = self._resolve_round_control_profile(round_mode)
        normalized_focus_files = [
            str(path).strip().lstrip("./").replace("\\", "/")
            for path in (focus_files or [])
            if str(path).strip()
        ]
        default_focus_soft_limit = 0
        if str(round_profile.get("round_mode", "default")) == "default" and normalized_focus_files:
            default_focus_soft_limit = min(
                max(4, int(round_profile["require_first_edit_by_step"]) // 3),
                6,
            )
        if str(round_profile.get("round_mode", "default")) != "default":
            focus_suffix = ""
            if normalized_focus_files:
                focus_suffix = " focus_files=" + ",".join(normalized_focus_files[:4])
                if len(normalized_focus_files) > 4:
                    focus_suffix += f",...(+{len(normalized_focus_files) - 4})"
            log(
                "REPAIR_PROFILE "
                f"mode={round_profile['round_mode']} "
                f"first_edit_by_step={round_profile['require_first_edit_by_step']} "
                f"read_only_cap={round_profile['max_read_only_steps_before_edit']} "
                f"search_cap={round_profile['search_streak_limit']}"
                f"{focus_suffix}"
            )
        format_errors = [0]
        format_salvages = [0]
        timeouts = [0]
        command_history: list[str] = []
        last_cmd = [""]
        loop_abort_reason = [""]
        diff_state = {
            "prev_sig": self._compute_diff_signature(repo_path),
            "seen_nonempty": False,
            "no_diff_streak": 0,
            "post_edit_no_diff_streak": 0,
            "search_streak": 0,
            "failed_cmd_streak": 0,
            "failed_cmd_norm": "",
            "sed_fail_streak": 0,
            "env_bootstrap_fail_streak": (
                1
                if pre_edit_infra_unreliable
                and str(round_profile.get("round_mode", "default")) == "default"
                else 0
            ),
            "python_inline_fail_streak": 0,
        }
        max_retries = 2
        command_guard_state: dict[str, Any] = {
            "path_mismatch_rejects": 0,
            "lint_rejects": 0,
            "commands_seen": 0,
            "counted_commands_seen": 0,
            "blocked_repair_streak": 0,
            "read_only_steps": 0,
            "edit_seen": False,
            "first_edit_step": 0,
            "first_test_seen": False,
            "first_test_step": 0,
            "last_executed_command": "",
        }

        original_add_message = agent.add_message
        original_parse_action = agent.parse_action
        original_env_execute = agent.env.execute

        def guarded_execute(command: str, cwd: str = "", *, timeout: int | None = None):
            current_diff_excerpt = self._build_current_diff_excerpt(
                repo_path,
                changed_files=self._get_changed_files_any(repo_path),
                max_files=2,
                max_chars=1200,
            )
            current_source_excerpt = self._build_focus_source_excerpt(
                repo_path,
                focus_files=normalized_focus_files,
                diff_excerpt=current_diff_excerpt,
            )
            verify_command = self._build_verify_command(
                round_mode=str(round_profile.get("round_mode", "default")),
                focus_files=normalized_focus_files,
            )
            guard = self._apply_round_command_guard(
                command=command,
                repo_path=repo_path,
                round_profile=round_profile,
                focus_files=normalized_focus_files,
                edit_seen=bool(command_guard_state.get("edit_seen")),
                env_bootstrap_fail_streak=int(diff_state.get("env_bootstrap_fail_streak", 0) or 0),
                read_only_steps=int(command_guard_state.get("read_only_steps", 0) or 0),
                exploratory_soft_limit=int(default_focus_soft_limit or 0),
                diff_excerpt=current_diff_excerpt,
                source_excerpt=current_source_excerpt,
                verify_command=verify_command,
            )
            effective_cmd = str(guard.get("command", command) or command)
            command_guard_state["last_executed_command"] = effective_cmd

            if bool(guard.get("blocked")):
                reason = str(guard.get("reason", "command_blocked") or "command_blocked")
                if reason.startswith("path_mismatch"):
                    command_guard_state["path_mismatch_rejects"] += 1
                if reason.startswith("lint"):
                    command_guard_state["lint_rejects"] += 1
                msg = str(guard.get("message", "") or "Command blocked by guardrails.")
                return {
                    "output": f"COMMAND_GUARD:{reason}\n{msg}",
                    "returncode": 126,
                }

            try:
                runtime_verify = self._maybe_execute_runtime_verify_command(
                    command=effective_cmd,
                    repo_path=repo_path,
                    timeout=timeout,
                    log=log,
                )
                if runtime_verify is not None:
                    return runtime_verify
                return original_env_execute(effective_cmd, cwd=cwd, timeout=timeout)
            except TypeError:
                return original_env_execute(effective_cmd)

        agent.env.execute = guarded_execute

        def tolerant_parse_action(response: dict) -> dict:
            try:
                return original_parse_action(response)
            except FormatError:
                current_diff_excerpt = self._build_current_diff_excerpt(
                    repo_path,
                    changed_files=self._get_changed_files_any(repo_path),
                    max_files=2,
                    max_chars=1200,
                )
                current_source_excerpt = self._build_focus_source_excerpt(
                    repo_path,
                    focus_files=normalized_focus_files,
                    diff_excerpt=current_diff_excerpt,
                )
                verify_command = self._build_verify_command(
                    round_mode=str(round_profile.get("round_mode", "default")),
                    focus_files=normalized_focus_files,
                )
                salvage = self._select_format_salvage_action(
                    response.get("content", ""),
                    repo_path=repo_path,
                    round_profile=round_profile,
                    focus_files=normalized_focus_files,
                    edit_seen=bool(command_guard_state.get("edit_seen")),
                    env_bootstrap_fail_streak=int(diff_state.get("env_bootstrap_fail_streak", 0) or 0),
                    read_only_steps=int(command_guard_state.get("read_only_steps", 0) or 0),
                    exploratory_soft_limit=int(default_focus_soft_limit or 0),
                    diff_excerpt=current_diff_excerpt,
                    source_excerpt=current_source_excerpt,
                    verify_command=verify_command,
                )
                if salvage is None:
                    raise
                format_salvages[0] += 1
                selected = str(salvage["action"] or "").strip()
                if not selected:
                    raise
                last_cmd[0] = selected
                if command_history:
                    command_history[-1] = selected
                else:
                    command_history.append(selected)
                log(
                    "  FORMAT_SALVAGE "
                    f"#{format_salvages[0]} "
                    f"reason={salvage['reason']} "
                    f"blocks={salvage['block_count']} "
                    f"raw={str(salvage.get('raw_action', '') or '')[:120]} "
                    f"selected={selected[:160]}"
                )
                return {"action": selected, **response}

        agent.parse_action = tolerant_parse_action

        def logging_add_message(role, content="", **kwargs):
            if role == "assistant":
                preview = content[:500] + ("..." if len(content) > 500 else "")
                log(f"--- Step {agent.model.n_calls} ---")
                log(f"AGENT:\n{preview}")
                cmds = re.findall(r"```bash\s*\n(.*?)\n```", content, re.DOTALL)
                if cmds:
                    cmd = cmds[0].strip()
                    last_cmd[0] = cmd
                    command_history.append(cmd)

            elif role == "user":
                if "EXACTLY ONE action" in content:
                    format_errors[0] += 1
                    log(f"  FORMAT_ERROR #{format_errors[0]}")
                elif "timed out" in content:
                    timeouts[0] += 1
                    log(f"  TIMEOUT #{timeouts[0]}")
                else:
                    preview = content[:300] + ("..." if len(content) > 300 else "")
                    log(f"  OBS: {preview}")

                if self.loop_policy == "off":
                    original_add_message(role, content, **kwargs)
                    return

                if "<returncode>" not in content:
                    if format_errors[0] >= self.format_error_limit:
                        loop_abort_reason[0] = f"format_error_limit:{format_errors[0]}"
                    original_add_message(role, content, **kwargs)
                    if role == "user" and loop_abort_reason[0]:
                        force_abort_prefixes = ("no_edit_progress", "format_error_limit")
                        if self.loop_policy == "strict" or loop_abort_reason[0].startswith(force_abort_prefixes):
                            raise LoopAbortError(loop_abort_reason[0])
                    return

                rc = self._extract_return_code(content)
                cmd = str(command_guard_state.get("last_executed_command") or last_cmd[0] or "")
                command_guard_state["commands_seen"] += 1
                cmd_norm = self._normalize_command(cmd)
                base_cmd = cmd.split()[0] if cmd.split() else ""
                cmd_flags = self._classify_command(cmd)
                loop_warnings: list[str] = []
                abort_reason = ""
                guard_reason = self._extract_command_guard_reason(content)
                guard_counts_toward_metrics = self._command_guard_counts_toward_loop_metrics(
                    guard_reason
                )
                current_diff_excerpt = self._build_current_diff_excerpt(
                    repo_path,
                    changed_files=self._get_changed_files_any(repo_path),
                    max_files=2,
                    max_chars=1200,
                )
                current_source_excerpt = self._build_focus_source_excerpt(
                    repo_path,
                    focus_files=normalized_focus_files,
                    diff_excerpt=current_diff_excerpt,
                )
                verify_command = self._build_verify_command(
                    round_mode=str(round_profile.get("round_mode", "default")),
                    focus_files=normalized_focus_files,
                )
                if guard_counts_toward_metrics:
                    command_guard_state["counted_commands_seen"] += 1
                    command_guard_state["blocked_repair_streak"] = 0

                if guard_reason.startswith("path_mismatch"):
                    loop_warnings.append(
                        "<warning>Command blocked by path guard. Use repository-relative paths only.</warning>"
                    )
                    if command_guard_state["path_mismatch_rejects"] >= self.path_mismatch_reject_limit:
                        abort_reason = (
                            f"env_path_mismatch:{command_guard_state['path_mismatch_rejects']}"
                        )
                elif guard_reason.startswith("repair_round_edit_required"):
                    loop_warnings.append(
                        "<warning>Regression repair round is edit-first. "
                        "Your next command must directly modify a focus file.</warning>"
                    )
                    loop_warnings.append(
                        self._build_repair_edit_required_message(
                            focus_files=normalized_focus_files,
                            diff_excerpt=current_diff_excerpt,
                            source_excerpt=current_source_excerpt,
                            verify_command=verify_command,
                        )
                    )
                elif guard_reason.startswith("repair_round_exploration_cap"):
                    loop_warnings.append(
                        "<warning>Repair round exploration cap reached. The next command must be "
                        "a direct edit to a focus file.</warning>"
                    )
                    loop_warnings.append(
                        self._build_repair_edit_required_message(
                            focus_files=normalized_focus_files,
                            diff_excerpt=current_diff_excerpt,
                            source_excerpt=current_source_excerpt,
                            verify_command=verify_command,
                        )
                    )
                elif guard_reason.startswith("default_round_edit_required"):
                    loop_warnings.append(
                        "<warning>Default-round exploration cap reached. Turn the current hypothesis "
                        "into a direct edit now.</warning>"
                    )
                    loop_warnings.append(
                        self._build_edit_required_message(
                            round_label="Default round",
                            focus_files=normalized_focus_files,
                            exploratory_limit=max(1, int(default_focus_soft_limit or 1)),
                            diff_excerpt=current_diff_excerpt,
                            source_excerpt=current_source_excerpt,
                            verify_command=verify_command,
                        )
                    )
                elif guard_reason.startswith("default_round_compound_exploration"):
                    loop_warnings.append(
                        "<warning>Do not chain exploratory shell commands in the default round. "
                        "Use one focused read/edit/test command only.</warning>"
                    )
                elif guard_reason.startswith("repair_round_compound_exploration"):
                    loop_warnings.append(
                        "<warning>Do not chain exploratory shell commands in repair rounds. "
                        "Use one direct edit or one targeted verification command only.</warning>"
                    )
                elif guard_reason.startswith("repair_round_scratch_python_file"):
                    loop_warnings.append(
                        "<warning>Ad-hoc repro scripts are blocked in repair rounds. "
                        "Edit existing source/test files directly.</warning>"
                    )
                elif guard_reason.startswith("git_revert_blocked"):
                    loop_warnings.append(
                        "<warning>Reverting the candidate patch is blocked. "
                        "Modify the current changed file instead of resetting it.</warning>"
                    )
                    loop_warnings.append(
                        self._build_edit_required_message(
                            round_label=(
                                "Repair rounds"
                                if str(round_profile.get("round_mode", "default")) != "default"
                                else "Default round"
                            ),
                            focus_files=normalized_focus_files,
                            exploratory_limit=max(
                                1,
                                int(
                                    round_profile.get("exploratory_pre_edit_limit", 2)
                                    or default_focus_soft_limit
                                    or 2
                                ),
                            ),
                            diff_excerpt=current_diff_excerpt,
                            source_excerpt=current_source_excerpt,
                            verify_command=verify_command,
                        )
                    )
                elif guard_reason.startswith("default_round_scratch_python_file"):
                    loop_warnings.append(
                        "<warning>Default round already has a failing repro test. "
                        "Do not create a scratch python repro script; edit source or run a targeted pytest command.</warning>"
                    )
                elif guard_reason.startswith("focus_round_inline_python_probe"):
                    if str(round_profile.get("round_mode", "default")) != "default":
                        loop_warnings.append(
                            "<warning>Inline python runtime probes are blocked in focused repair rounds. "
                            "Edit a focus file directly now.</warning>"
                        )
                        loop_warnings.append(
                            self._build_repair_edit_required_message(
                                focus_files=normalized_focus_files,
                                diff_excerpt=current_diff_excerpt,
                                source_excerpt=current_source_excerpt,
                                verify_command=verify_command,
                            )
                        )
                    else:
                        loop_warnings.append(
                            "<warning>Inline python runtime probes are blocked in focused rounds. "
                            "Edit a focus file directly or run targeted pytest/py_compile instead.</warning>"
                        )
                elif guard_reason.startswith("submit_requires_semantic_patch"):
                    loop_warnings.append(
                        "<warning>Do not submit an empty or comment-only patch. "
                        "Make an executable code change first.</warning>"
                    )
                elif guard_reason.startswith("lint"):
                    loop_warnings.append(
                        "<warning>Command blocked by command linter. "
                        "Return exactly one valid bash command without prompt artifacts.</warning>"
                    )

                blocked_repair_guard = (
                    bool(guard_reason)
                    and str(round_profile.get("round_mode", "default")) != "default"
                )
                if blocked_repair_guard:
                    command_guard_state["blocked_repair_streak"] += 1
                    if (
                        int(round_profile.get("blocked_guard_abort_limit", 0) or 0) > 0
                        and command_guard_state["blocked_repair_streak"]
                        >= int(round_profile.get("blocked_guard_abort_limit", 0) or 0)
                        and not abort_reason
                    ):
                        abort_reason = (
                            f"repair_blocked_streak:{command_guard_state['blocked_repair_streak']}"
                        )

                if guard_counts_toward_metrics and rc != 0 and cmd_norm:
                    if diff_state["failed_cmd_norm"] == cmd_norm:
                        diff_state["failed_cmd_streak"] += 1
                    else:
                        diff_state["failed_cmd_norm"] = cmd_norm
                        diff_state["failed_cmd_streak"] = 1
                    if diff_state["failed_cmd_streak"] >= self.repeated_fail_limit:
                        abort_reason = (
                            f"repeated_failing_command:{base_cmd} x{diff_state['failed_cmd_streak']}"
                        )
                elif guard_counts_toward_metrics:
                    diff_state["failed_cmd_norm"] = ""
                    diff_state["failed_cmd_streak"] = 0

                if guard_counts_toward_metrics:
                    if cmd_flags["is_exploratory"]:
                        diff_state["search_streak"] += 1
                    else:
                        diff_state["search_streak"] = 0
                    if (
                        diff_state["search_streak"] >= int(round_profile["search_streak_limit"])
                        and not abort_reason
                    ):
                        abort_reason = f"search_only_streak:{diff_state['search_streak']}"

                    if cmd_flags["is_edit"]:
                        if not command_guard_state["edit_seen"]:
                            command_guard_state["edit_seen"] = True
                            command_guard_state["first_edit_step"] = int(agent.model.n_calls)
                        command_guard_state["read_only_steps"] = 0
                    else:
                        if not command_guard_state["edit_seen"]:
                            command_guard_state["read_only_steps"] += 1
                            if (
                                command_guard_state["read_only_steps"]
                                >= int(round_profile["max_read_only_steps_before_edit"])
                                and not abort_reason
                            ):
                                abort_reason = (
                                    f"read_only_streak:{command_guard_state['read_only_steps']}"
                                )

                    if cmd_flags["is_test"] and not command_guard_state["first_test_seen"]:
                        command_guard_state["first_test_seen"] = True
                        command_guard_state["first_test_step"] = int(agent.model.n_calls)

                if (
                    not command_guard_state["edit_seen"]
                    and command_guard_state["counted_commands_seen"]
                    >= int(round_profile["require_first_edit_by_step"])
                    and not abort_reason
                ):
                    abort_reason = (
                        "first_edit_missing_by_step:"
                        f"{int(round_profile['require_first_edit_by_step'])}"
                    )

                # Repeated environment/bootstrap failures (pytest setup/build/import)
                # are usually low-signal in this harness; force an early retry pivot.
                cmd_lower = cmd.lower()
                python_inline_import_cmd = (
                    ("python -c" in cmd_lower or "python3 -c" in cmd_lower)
                    and ("import astropy" in cmd_lower or "from astropy" in cmd_lower)
                )
                env_bootstrap_cmd = (
                    "pytest" in cmd_lower
                    or "setup.py build_ext" in cmd_lower
                    or "pip install" in cmd_lower
                    or "python setup.py" in cmd_lower
                    or python_inline_import_cmd
                )
                bootstrap_import_error = (
                    rc != 0
                    and "importerror" in content.lower()
                    and "astropy" in content.lower()
                )
                if guard_counts_toward_metrics and (
                    (env_bootstrap_cmd and rc != 0) or bootstrap_import_error
                ):
                    diff_state["env_bootstrap_fail_streak"] += 1
                    loop_warnings.append(
                        "<warning>Environment/test bootstrap keeps failing. "
                        "Stop setup attempts and pivot to source-level fixes now.</warning>"
                    )
                    if (
                        int(round_profile["env_bootstrap_fail_limit"]) > 0
                        and diff_state["env_bootstrap_fail_streak"]
                        >= int(round_profile["env_bootstrap_fail_limit"])
                        and not abort_reason
                    ):
                        abort_reason = f"env_bootstrap_fail_streak:{diff_state['env_bootstrap_fail_streak']}"
                elif guard_counts_toward_metrics and not env_bootstrap_cmd:
                    diff_state["env_bootstrap_fail_streak"] = 0

                if guard_counts_toward_metrics and "sed -i" in cmd and rc != 0:
                    diff_state["sed_fail_streak"] += 1
                    if "sed -i ''" not in cmd and sys.platform == "darwin":
                        loop_warnings.append(
                            "<warning>macOS sed requires `sed -i '' ...`. "
                            "Prefer python-based edits if sed keeps failing.</warning>"
                        )
                    if diff_state["sed_fail_streak"] >= self.sed_fail_limit and not abort_reason:
                        abort_reason = f"sed_fail_streak:{diff_state['sed_fail_streak']}"
                elif guard_counts_toward_metrics:
                    diff_state["sed_fail_streak"] = 0

                python_inline_cmd = "python -c" in cmd_lower or "python3 -c" in cmd_lower
                if guard_counts_toward_metrics and python_inline_cmd and rc != 0:
                    diff_state["python_inline_fail_streak"] += 1
                    loop_warnings.append(
                        "<warning>`python -c` edit command failed. "
                        "Use `python - <<'PY' ... PY` for multi-line edits.</warning>"
                    )
                    if (
                        self.python_inline_fail_limit > 0
                        and diff_state["python_inline_fail_streak"] >= self.python_inline_fail_limit
                        and not abort_reason
                    ):
                        abort_reason = (
                            f"python_inline_fail_streak:{diff_state['python_inline_fail_streak']}"
                        )
                elif guard_counts_toward_metrics and not python_inline_cmd:
                    diff_state["python_inline_fail_streak"] = 0

                if guard_counts_toward_metrics:
                    current_sig = self._compute_diff_signature(repo_path)
                    if current_sig != "EMPTY":
                        diff_state["seen_nonempty"] = True
                    noop_first_edit = self._is_noop_first_edit_attempt(
                        cmd_flags=cmd_flags,
                        seen_nonempty=bool(diff_state["seen_nonempty"]),
                        prev_sig=str(diff_state["prev_sig"]),
                        current_sig=current_sig,
                    )
                    if noop_first_edit:
                        command_guard_state["edit_seen"] = False
                        command_guard_state["first_edit_step"] = 0
                        loop_warnings.append(
                            "<warning>Your last edit command did not change the working tree. "
                            "A real code edit is still required before more exploration.</warning>"
                        )
                        if str(round_profile.get("round_mode", "default")) == "default":
                            loop_warnings.append(
                                self._build_edit_required_message(
                                    round_label="Default round",
                                    focus_files=normalized_focus_files,
                                    exploratory_limit=max(1, int(default_focus_soft_limit or 1)),
                                    diff_excerpt=current_diff_excerpt,
                                    source_excerpt=current_source_excerpt,
                                    verify_command=verify_command,
                                )
                            )

                    if diff_state["seen_nonempty"]:
                        if current_sig == diff_state["prev_sig"]:
                            diff_state["no_diff_streak"] += 1
                        else:
                            diff_state["no_diff_streak"] = 0
                        if (
                            diff_state["no_diff_streak"] >= self.no_diff_streak_limit
                            and not abort_reason
                        ):
                            abort_reason = f"no_diff_streak:{diff_state['no_diff_streak']}"
                    elif (
                        command_guard_state["counted_commands_seen"]
                        >= int(round_profile["no_edit_progress_step_limit"])
                        and not abort_reason
                    ):
                        abort_reason = (
                            f"no_edit_progress:{command_guard_state['counted_commands_seen']}"
                        )
                    (
                        diff_state["post_edit_no_diff_streak"],
                        post_edit_no_diff_abort,
                    ) = self._update_post_edit_no_diff_streak(
                        round_mode=str(round_profile.get("round_mode", "default")),
                        edit_seen=bool(command_guard_state["edit_seen"]),
                        seen_nonempty=bool(diff_state["seen_nonempty"]),
                        cmd_flags=cmd_flags,
                        current_sig=current_sig,
                        prev_sig=str(diff_state["prev_sig"]),
                        streak=int(diff_state.get("post_edit_no_diff_streak", 0) or 0),
                    )
                    if post_edit_no_diff_abort and not abort_reason:
                        abort_reason = (
                            "post_edit_no_diff_streak:"
                            f"{diff_state['post_edit_no_diff_streak']}"
                        )
                        loop_warnings.append(
                            "<warning>Non-empty candidate patch already exists and the last commands "
                            "did not change it. Stop browsing and let this patch be evaluated, or run one "
                            "targeted verification command immediately.</warning>"
                        )
                    diff_state["prev_sig"] = current_sig

                import_cmds = [
                    c for c in command_history[-3:]
                    if "python3 -c" in c and "import " in c
                ]
                if len(import_cmds) >= 2:
                    loop_warnings.append(
                        "<warning>STOP importing package modules. Use source files directly (`cat`, `grep`, `nl`).</warning>"
                    )
                if format_errors[0] >= self.format_error_limit and not abort_reason:
                    abort_reason = f"format_error_limit:{format_errors[0]}"

                if abort_reason:
                    loop_abort_reason[0] = abort_reason
                    force_abort_prefixes = ("no_edit_progress", "format_error_limit")
                    will_abort_now = (
                        self.loop_policy == "strict"
                        or abort_reason.startswith(force_abort_prefixes)
                    )
                    if will_abort_now:
                        loop_warnings.append(
                            "<warning>Trajectory aborted due to repeated low-signal behavior. "
                            "Submit and restart with a different strategy.</warning>"
                        )
                    else:
                        loop_warnings.append(
                            "<warning>Low-signal trajectory detected. "
                            "Change strategy immediately and produce a concrete edit.</warning>"
                        )
                    if abort_reason.startswith("repair_blocked_streak"):
                        loop_warnings.append(
                            "<warning>Repair round repeated blocked commands. "
                            "Abort this round and restart with a tighter strategy.</warning>"
                        )

                if loop_warnings:
                    warning_text = "\n".join(loop_warnings)
                    content = warning_text + "\n" + content
                    log(f"  LOOP_WARNING injected: {warning_text[:220]}")

            original_add_message(role, content, **kwargs)

            if role == "user" and loop_abort_reason[0]:
                force_abort_prefixes = ("no_edit_progress", "format_error_limit")
                if self.loop_policy == "strict" or loop_abort_reason[0].startswith(force_abort_prefixes):
                    raise LoopAbortError(loop_abort_reason[0])

        agent.add_message = logging_add_message

        status = "error"
        message = ""
        t0 = time.time()
        timeout_budget = max(1, int(run_timeout_sec or self.agent_run_timeout_sec))
        prepared_task, prompt_telemetry = self._prepare_prompt_for_agent_run(
            task=task,
            round_mode=str(round_profile.get("round_mode", "default")),
            focus_files=normalized_focus_files,
            log=log,
        )
        backend_observability: dict[str, Any] = {
            "provider": self.local_backend.provider,
            "trace_id": str(prompt_telemetry.get("trace_id", "") or ""),
            "ready": self.local_backend.provider != "mlxlm",
            "started_now": False,
            "reused_existing": False,
            "before": {},
            "after": {},
            "crash_detected": False,
            "restarted": False,
            "failure_reason": "",
        }

        class _AgentRunTimeout(RuntimeError):
            pass

        for attempt in range(int(round_profile["max_retries"]) + 1):
            try:
                elapsed = time.time() - t0
                remaining = timeout_budget - int(elapsed)
                if remaining <= 0:
                    raise _AgentRunTimeout(f"instance_timeout:{timeout_budget}s")

                backend_ready = ensure_local_backend_ready(self.local_backend, prefix="QWEN_MINI")
                backend_observability["ready"] = bool(backend_ready.get("ready", True))
                backend_observability["started_now"] = bool(backend_ready.get("started_now", False))
                backend_observability["reused_existing"] = bool(
                    backend_ready.get("reused_existing", False)
                )
                backend_before = describe_local_backend_runtime(
                    self.local_backend,
                    prefix="QWEN_MINI",
                )
                backend_observability["before"] = dict(backend_before)
                if self.local_backend.provider == "mlxlm":
                    log(
                        "MLX_TRACE_START "
                        f"id={prompt_telemetry['trace_id']} "
                        f"run_retry={attempt + 1}/{int(round_profile['max_retries']) + 1} "
                        f"pid={backend_before.get('pid', 0)} "
                        f"alive={backend_before.get('alive', False)} "
                        f"state={backend_before.get('state', '') or '-'} "
                        f"rss_kb={backend_before.get('rss_kb')} "
                        f"started_now={backend_observability['started_now']} "
                        f"reused_existing={backend_observability['reused_existing']} "
                        f"log_path={backend_before.get('log_path', '') or '-'}"
                    )

                alarm_supported = hasattr(signal, "SIGALRM") and hasattr(signal, "setitimer")
                previous_handler = None
                if alarm_supported:
                    previous_handler = signal.getsignal(signal.SIGALRM)

                    def _timeout_handler(signum, frame):
                        raise _AgentRunTimeout(f"instance_timeout:{timeout_budget}s")

                    signal.signal(signal.SIGALRM, _timeout_handler)
                    signal.setitimer(signal.ITIMER_REAL, max(1, remaining))
                try:
                    status, message = agent.run(prepared_task)
                finally:
                    if alarm_supported:
                        signal.setitimer(signal.ITIMER_REAL, 0.0)
                        signal.signal(signal.SIGALRM, previous_handler)
                backend_after = describe_local_backend_runtime(
                    self.local_backend,
                    prefix="QWEN_MINI",
                )
                backend_observability["after"] = dict(backend_after)
                backend_observability["crash_detected"] = bool(
                    backend_before.get("alive") and not backend_after.get("alive")
                )
                backend_observability["restarted"] = bool(
                    backend_before.get("pid")
                    and backend_after.get("pid")
                    and int(backend_before.get("pid") or 0) != int(backend_after.get("pid") or 0)
                )
                if self.local_backend.provider == "mlxlm":
                    log(
                        "MLX_TRACE_END "
                        f"id={prompt_telemetry['trace_id']} "
                        f"pid={backend_after.get('pid', 0)} "
                        f"alive={backend_after.get('alive', False)} "
                        f"state={backend_after.get('state', '') or '-'} "
                        f"rss_kb={backend_after.get('rss_kb')} "
                        f"crash_detected={backend_observability['crash_detected']} "
                        f"restarted={backend_observability['restarted']}"
                    )
                break
            except _AgentRunTimeout as e:
                status = "LoopAborted"
                message = str(e)
                timeouts[0] += 1
                loop_abort_reason[0] = str(e)
                log(f"AGENT_TIMEOUT: {e}")
                backend_observability["failure_reason"] = "agent_run_timeout"
                break
            except LoopAbortError as e:
                status = "LoopAborted"
                message = str(e)
                backend_observability["failure_reason"] = "loop_abort"
                break
            except (ConnectionError, OSError) as e:
                backend_after = describe_local_backend_runtime(
                    self.local_backend,
                    prefix="QWEN_MINI",
                )
                backend_observability["after"] = dict(backend_after)
                backend_observability["crash_detected"] = bool(
                    backend_observability.get("before", {}).get("alive")
                    and not backend_after.get("alive")
                )
                backend_observability["restarted"] = bool(
                    backend_observability.get("before", {}).get("pid")
                    and backend_after.get("pid")
                    and int(backend_observability["before"].get("pid") or 0)
                    != int(backend_after.get("pid") or 0)
                )
                if self.local_backend.provider == "mlxlm":
                    backend_observability["failure_reason"] = "mlxlm_backend_connection_failure"
                if attempt < max_retries:
                    log(
                        f"{self.local_backend.provider_label} connection error "
                        f"(attempt {attempt + 1}/{max_retries + 1}): {e}"
                    )
                    log("Waiting 30s before retry...")
                    time.sleep(30)
                else:
                    raise
        elapsed = time.time() - t0

        log(f"Agent finished: status={status}  elapsed={elapsed:.1f}s  steps={agent.model.n_calls}")
        log(f"Format errors: {format_errors[0]}  Timeouts: {timeouts[0]}")
        if loop_abort_reason[0]:
            log(f"Loop abort reason: {loop_abort_reason[0]}")
        agent.env.execute = original_env_execute

        return {
            "status": status,
            "message": message,
            "steps": agent.model.n_calls,
            "cost": agent.model.cost,
            "elapsed": elapsed,
            "format_errors": format_errors[0],
            "timeouts": timeouts[0],
            "loop_abort_reason": loop_abort_reason[0],
            "prompt_trace_id": prompt_telemetry.get("trace_id", ""),
            "prompt_budget_chars": prompt_telemetry.get("budget_chars"),
            "prompt_chars_before": prompt_telemetry.get("chars_before"),
            "prompt_chars_after": prompt_telemetry.get("chars_after"),
            "prompt_estimated_tokens_before": prompt_telemetry.get("estimated_tokens_before"),
            "prompt_estimated_tokens_after": prompt_telemetry.get("estimated_tokens_after"),
            "prompt_section_sizes_before": prompt_telemetry.get("section_sizes_before", {}),
            "prompt_section_sizes_after": prompt_telemetry.get("section_sizes_after", {}),
            "prompt_trimmed": prompt_telemetry.get("trimmed", False),
            "prompt_trimmed_sections": prompt_telemetry.get("trimmed_sections", []),
            "mlx_backend_ready": backend_observability.get("ready", False),
            "mlx_backend_started_now": backend_observability.get("started_now", False),
            "mlx_backend_reused_existing": backend_observability.get("reused_existing", False),
            "mlx_backend_before": backend_observability.get("before", {}),
            "mlx_backend_after": backend_observability.get("after", {}),
            "mlx_backend_crash_detected": backend_observability.get("crash_detected", False),
            "mlx_backend_restarted": backend_observability.get("restarted", False),
            "mlx_backend_failure_reason": backend_observability.get("failure_reason", ""),
        }

    def _extract_test_file_changes(
        self,
        changed_files: list[str],
        *,
        policy: Optional[str] = None,
    ) -> list[str]:
        mode = str(policy or self.test_change_policy or "any_test_like").strip().lower()
        if mode not in {"any_test_like", "repo_tests_only"}:
            mode = "any_test_like"
        test_files: list[str] = []
        seen: set[str] = set()
        for raw_path in changed_files or []:
            path = str(raw_path or "").replace("\\", "/").strip()
            lower_path = path.lower()
            if not lower_path.endswith(".py"):
                continue
            file_name = lower_path.rsplit("/", 1)[-1]
            path_parts = [part for part in lower_path.split("/") if part]
            in_repo_test_dir = any(part in {"tests", "testing"} for part in path_parts)

            is_test_like_name = (
                file_name.startswith("test_")
                or file_name.endswith("_test.py")
            )

            if mode == "repo_tests_only":
                matches = in_repo_test_dir
            else:
                matches = in_repo_test_dir or is_test_like_name or "/test/" in lower_path

            if matches and path not in seen:
                seen.add(path)
                test_files.append(path)
        return test_files

    def _extract_source_file_changes(
        self,
        changed_files: list[str],
        *,
        policy: Optional[str] = None,
    ) -> list[str]:
        test_files = set(self._extract_test_file_changes(changed_files, policy=policy))
        source_files: list[str] = []
        seen: set[str] = set()
        for raw_path in changed_files or []:
            path = str(raw_path or "").replace("\\", "/").strip()
            if not path or path in seen:
                continue
            if path in test_files:
                continue
            if not path.lower().endswith(".py"):
                continue
            seen.add(path)
            source_files.append(path)
        return source_files

    def _has_unit_test_changes(self, changed_files: list[str], *, policy: Optional[str] = None) -> bool:
        return bool(self._extract_test_file_changes(changed_files, policy=policy))

    def _resolve_indexed_signal(self, graphrag_meta: dict[str, Any], *, mode: str) -> bool:
        signal_mode = str(mode or self.indexed_signal_mode or "attempted_query").strip().lower()
        if signal_mode == "successful_query":
            if "graph_useful_signal" in graphrag_meta:
                return bool(graphrag_meta.get("graph_useful_signal"))
            return bool(graphrag_meta.get("indexed_search_success"))
        return bool(graphrag_meta.get("indexed_search_attempted"))

    def _is_fallback_regression_source(self, regression_source: str) -> bool:
        source = str(regression_source or "").strip().lower()
        return source in {"bounded_fallback_smoke", "changed_test_file_fallback"}

    def _get_regression_repair_signal(self, graphrag_meta: dict[str, Any]) -> tuple[bool, bool, str]:
        regression_source = str(graphrag_meta.get("regression_source", "none") or "none")
        graph_has_useful_signal = bool(graphrag_meta.get("graph_useful_signal"))
        impacted_run = int(graphrag_meta.get("impacted_run", 0) or 0)
        impacted_failed = int(graphrag_meta.get("impacted_failed", 0) or 0)
        failed_tests = list(graphrag_meta.get("impacted_failed_tests") or [])
        graph_execution_failed = (
            graph_has_useful_signal
            and graphrag_meta.get("impacted_success") is False
            and impacted_run <= 0
        )
        repair_source_eligible = graph_has_useful_signal or (
            self._is_fallback_regression_source(regression_source)
            and impacted_failed > 0
            and len(failed_tests) > 0
        )
        regression_signal_reliable = bool(
            graphrag_meta.get("regression_signal_reliable", graphrag_meta.get("impacted_execution_reliable"))
        )
        regression_failures_present = impacted_failed > 0 or graph_execution_failed
        continue_regression_fix = bool(
            repair_source_eligible and regression_failures_present and regression_signal_reliable
        )
        return continue_regression_fix, graph_execution_failed, regression_source

    def _build_regression_failure_prompt_tests(
        self,
        graphrag_meta: dict[str, Any],
        *,
        regression_source: str,
        graph_execution_failed: bool,
    ) -> list[dict[str, Any]]:
        failed_for_prompt = list(graphrag_meta.get("impacted_failed_tests") or [])
        if graph_execution_failed and not failed_for_prompt:
            failed_for_prompt = [
                {
                    "test_name": "graph_impact_execution",
                    "error": (
                        graphrag_meta.get("impacted_error")
                        or "Impacted-test execution produced no runnable signal"
                    ),
                }
            ]
        elif not failed_for_prompt and int(graphrag_meta.get("impacted_failed", 0) or 0) > 0:
            failed_for_prompt = [
                {
                    "test_name": regression_source or "regression_fallback",
                    "error": (
                        graphrag_meta.get("impacted_error")
                        or "Reliable regression checks failed but did not return named failing tests"
                    ),
                }
            ]
        return failed_for_prompt

    def _sync_test_runtime_manager_settings(self) -> None:
        """Apply interface-level runtime knobs to the runtime manager before env overrides."""
        mode = str(self.test_runtime_isolation or "off").strip().lower()
        if mode not in {"off", "repo_cached_venv"}:
            mode = "off"
        self.test_runtime_manager.isolation_mode = mode

        cache_dir = str(self.test_runtime_cache_dir or "").strip()
        if cache_dir:
            self.test_runtime_manager.cache_dir = Path(cache_dir)

        try:
            timeout_sec = max(30, int(self.test_runtime_bootstrap_timeout_sec or 240))
        except (TypeError, ValueError):
            timeout_sec = 240
        self.test_runtime_manager.bootstrap_timeout_sec = timeout_sec
        self.test_runtime_manager.bootstrap_attempt_timeout_sec = timeout_sec
        self.test_runtime_manager.bootstrap_max_total_sec = max(
            timeout_sec,
            int(self.test_runtime_manager.bootstrap_max_total_sec or timeout_sec),
        )
        self.test_runtime_manager.auto_editable_install = bool(self.test_runtime_auto_editable_install)

    def _run_runtime_subprocess(
        self,
        *,
        repo_path: Path,
        args: list[str],
        timeout: Optional[int] = None,
        log=print,
    ) -> dict[str, Any]:
        repo_root = repo_path.resolve()
        runtime = self.test_runtime_manager.get_runtime(repo_root, log=log)
        if not bool(runtime.get("runtime_ready", True)):
            bootstrap_reason = str(runtime.get("bootstrap_error_reason", "") or "runtime_bootstrap_failed")
            bootstrap_error = str(runtime.get("bootstrap_error", "") or bootstrap_reason)
            return {
                "output": f"RUNTIME_BOOTSTRAP_FAILED:{bootstrap_reason}\n{bootstrap_error}",
                "returncode": 1,
                "runtime": runtime,
            }
        runtime_env = dict(runtime.get("env") or os.environ)
        effective_timeout = max(30, int(timeout or self.pytest_timeout))
        try:
            result = subprocess.run(
                args,
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
                check=False,
                env=runtime_env,
            )
            output = f"{result.stdout}\n{result.stderr}".strip()
            return {
                "output": output,
                "returncode": int(result.returncode),
                "runtime": runtime,
            }
        except subprocess.TimeoutExpired:
            return {
                "output": "command_timeout",
                "returncode": 124,
                "runtime": runtime,
            }
        except Exception as exc:
            return {
                "output": str(exc),
                "returncode": 1,
                "runtime": runtime,
            }

    def _parse_simple_shell_command(self, command: str) -> Optional[list[str]]:
        text = str(command or "").strip()
        if not text:
            return None
        if re.search(r"(?:&&|\|\||;|\|)", text):
            return None
        try:
            return shlex.split(text)
        except ValueError:
            return None

    def _parse_pytest_command(self, command: str) -> Optional[dict[str, Any]]:
        tokens = self._parse_simple_shell_command(command)
        if not tokens:
            return None
        if tokens[0] == "pytest":
            return {"args": tokens[1:]}
        if len(tokens) >= 3 and tokens[0] in {"python", "python3"} and tokens[1] == "-m" and tokens[2] == "pytest":
            return {"args": tokens[3:]}
        return None

    def _extract_pytest_targets(self, pytest_args: list[str]) -> list[str]:
        value_options = {
            "-k",
            "-m",
            "-p",
            "-c",
            "-o",
            "--maxfail",
            "--rootdir",
            "--confcutdir",
            "--basetemp",
            "--durations",
            "--ignore",
            "--deselect",
            "--import-mode",
            "--lfnf",
        }
        targets: list[str] = []
        skip_next = False
        for token in pytest_args:
            current = str(token or "").strip()
            if not current:
                continue
            if skip_next:
                skip_next = False
                continue
            if current in value_options:
                skip_next = True
                continue
            if any(current.startswith(f"{option}=") for option in value_options if option.startswith("--")):
                continue
            if current.startswith("-"):
                continue
            targets.append(current)
        return targets

    def _maybe_execute_runtime_verify_command(
        self,
        *,
        command: str,
        repo_path: Path,
        timeout: Optional[int] = None,
        log=print,
    ) -> Optional[dict[str, Any]]:
        pytest_command = self._parse_pytest_command(command)
        if pytest_command is not None:
            pytest_args = list(pytest_command.get("args") or [])
            runtime = self.test_runtime_manager.get_runtime(repo_path.resolve(), log=log)
            runtime_python = str(runtime.get("python_executable", sys.executable) or sys.executable)
            direct = self._run_runtime_subprocess(
                repo_path=repo_path,
                args=[runtime_python, "-m", "pytest", *pytest_args],
                timeout=timeout,
                log=log,
            )
            direct_output = str(direct.get("output", "") or "")
            direct_rc_raw = direct.get("returncode", 1)
            direct_rc = int(1 if direct_rc_raw is None else direct_rc_raw)
            infra_unreliable, infra_reason = self._detect_pytest_infra_failure(direct_output, direct_rc)
            targets = self._extract_pytest_targets(pytest_args)
            if infra_unreliable and targets:
                fallback = self._run_pytest_subset(
                    repo_path,
                    targets,
                    timeout=max(30, int(timeout or self.pytest_timeout)),
                    log=log,
                )
                fallback_output = str(fallback.get("output", "") or "").strip()
                fallback_note = (
                    f"Normalized runtime pytest fallback used after {infra_reason or 'infra_failure'}.\n"
                    f"Original command: {command}\n"
                )
                return {
                    "output": (fallback_note + fallback_output).strip(),
                    "returncode": int(
                        1 if fallback.get("returncode") is None else fallback.get("returncode")
                    ),
                }
            return {
                "output": direct_output,
                "returncode": direct_rc,
            }

        tokens = self._parse_simple_shell_command(command)
        if not tokens:
            return None
        if len(tokens) >= 4 and tokens[0] in {"python", "python3"} and tokens[1] == "-m" and tokens[2] == "py_compile":
            runtime = self.test_runtime_manager.get_runtime(repo_path.resolve(), log=log)
            runtime_python = str(runtime.get("python_executable", sys.executable) or sys.executable)
            compile_result = self._run_runtime_subprocess(
                repo_path=repo_path,
                args=[runtime_python, "-m", "py_compile", *tokens[3:]],
                timeout=timeout,
                log=log,
            )
            compile_rc_raw = compile_result.get("returncode", 1)
            return {
                "output": str(compile_result.get("output", "") or ""),
                "returncode": int(1 if compile_rc_raw is None else compile_rc_raw),
            }
        return None

    def _is_runtime_reliable_for_test_contract(
        self,
        *,
        pre_edit_repro: dict[str, Any],
        test_metrics: dict[str, Any],
    ) -> bool:
        """Return True when runtime signals are reliable enough to enforce strict test-change gates."""
        reliability_flags: list[bool] = []
        if str(pre_edit_repro.get("command", "") or "").strip():
            reliability_flags.append(not bool(pre_edit_repro.get("infra_unreliable")))

        f2p_reliable = test_metrics.get("f2p_reliable")
        if f2p_reliable is not None:
            reliability_flags.append(bool(f2p_reliable))

        p2p_reliable = test_metrics.get("p2p_reliable")
        if p2p_reliable is not None:
            reliability_flags.append(bool(p2p_reliable))

        test_signal_reliable = test_metrics.get("test_signal_reliable")
        if test_signal_reliable is False:
            reliability_flags.append(False)

        if not reliability_flags:
            return False
        return all(reliability_flags)

    def _should_continue_tdd_fix_round(
        self,
        *,
        require_test_checks: bool,
        f2p_total: int,
        f2p_all_passed: bool,
        f2p_reliable: Optional[bool],
        current_round: int,
        max_rounds: int,
        remaining_budget_sec: int,
    ) -> tuple[bool, str]:
        if not require_test_checks:
            return False, "test_checks_disabled"
        if current_round >= max_rounds:
            return False, "round_limit_reached"
        if f2p_total <= 0:
            return False, "no_f2p_targets"
        if f2p_all_passed:
            return False, "f2p_already_green"
        if remaining_budget_sec < self.iter_fix_min_remaining_sec:
            return False, "low_remaining_budget"
        if self.iter_fix_require_reliable_signal and f2p_reliable is not True:
            return False, "infra_unreliable"
        return True, ""

    def _resolve_test_change_requirement(
        self,
        *,
        tdd_mode: bool,
        graphrag_enabled: bool,
        runtime_reliable_for_test_contract: bool,
        fail_to_pass_tests: Optional[list[str]] = None,
    ) -> tuple[bool, str]:
        if not (tdd_mode and graphrag_enabled):
            return False, "not_applicable"
        if fail_to_pass_tests:
            return False, "waived_existing_repo_fail_to_pass"
        if runtime_reliable_for_test_contract:
            return True, "required_reliable_runtime"
        return False, "waived_unreliable_runtime"

    def _classify_graph_guard_signal_shape(
        self,
        *,
        indexed_search_used: bool,
        unit_test_changed: bool,
    ) -> str:
        if indexed_search_used and unit_test_changed:
            return "both"
        if indexed_search_used:
            return "either_indexed"
        if unit_test_changed:
            return "either_test_change"
        return "none"

    def _evaluate_graph_guard(
        self,
        *,
        guard_mode: str,
        indexed_search_used: bool,
        unit_test_changed: bool,
    ) -> tuple[bool, str]:
        mode = str(guard_mode or "either").strip().lower()
        if mode not in {"either", "both", "indexed_only"}:
            mode = "either"

        if mode == "indexed_only":
            if indexed_search_used:
                return True, ""
            return False, "graph_guard_indexed_only_failed:indexed_search_missing"

        if mode == "both":
            missing: list[str] = []
            if not indexed_search_used:
                missing.append("indexed_search_missing")
            if not unit_test_changed:
                missing.append("unit_test_change_missing")
            if missing:
                return False, f"graph_guard_both_failed:{','.join(missing)}"
            return True, ""

        # mode == either
        if indexed_search_used or unit_test_changed:
            return True, ""
        return False, "graph_guard_either_failed:indexed_search_missing,unit_test_change_missing"

    def _record_graphrag_targeted_coverage(
        self,
        *,
        graphrag_mcp,
        repo_path: Path,
        tests: list[str],
        log=print,
    ) -> dict[str, Any]:
        """Persist bounded coverage links for already-selected targeted tests when supported."""
        selected = [str(test).strip() for test in (tests or []) if str(test).strip()]
        if not selected:
            return {}

        recorder = getattr(graphrag_mcp, "record_targeted_test_coverage", None)
        if not callable(recorder):
            return {}

        try:
            result = recorder(
                repo_path=str(repo_path),
                tests=selected,
            )
        except Exception as e:
            log(f"GraphRAG targeted coverage ingestion failed: {e}")
            return {
                "success": False,
                "links_created": 0,
                "tests_considered": len(selected),
                "warnings": [str(e)],
            }

        if result:
            log(
                "GraphRAG targeted coverage: "
                f"tests={int(result.get('tests_considered', len(selected)) or len(selected))} "
                f"links={int(result.get('links_created', 0) or 0)} "
                f"success={bool(result.get('success', False))}"
            )
        return dict(result or {})

    def _apply_regression_fallback_result(
        self,
        *,
        graphrag_meta: dict[str, Any],
        fallback_result: Optional[dict[str, Any]],
        regression_source: str,
        impact_empty_reason: str = "",
        graph_fallback_reason: str = "",
    ) -> bool:
        result = dict(fallback_result or {})
        if not result:
            return False

        if impact_empty_reason and not str(graphrag_meta.get("impact_empty_reason", "") or "").strip():
            graphrag_meta["impact_empty_reason"] = impact_empty_reason
        if graph_fallback_reason and not str(graphrag_meta.get("graph_fallback_reason", "") or "").strip():
            graphrag_meta["graph_fallback_reason"] = graph_fallback_reason

        graphrag_meta["impacted_run"] = int(
            result.get("tests_run", graphrag_meta.get("impacted_run", 0)) or 0
        )
        graphrag_meta["impacted_failed"] = int(
            result.get("failed", graphrag_meta.get("impacted_failed", 0)) or 0
        )
        graphrag_meta["impacted_success"] = bool(
            result.get("success", graphrag_meta.get("impacted_success", False))
        )
        graphrag_meta["impacted_execution_reliable"] = bool(
            result.get("execution_reliable", False)
        )
        if result.get("failed_tests"):
            graphrag_meta["impacted_failed_tests"] = list(result.get("failed_tests") or [])

        graphrag_meta["regression_source"] = str(regression_source or "none") or "none"
        graphrag_meta["regression_tests_selected"] = int(
            result.get("selected_count", len(result.get("selected_tests") or [])) or 0
        )
        graphrag_meta["regression_tests_run"] = int(graphrag_meta.get("impacted_run", 0) or 0)
        graphrag_meta["regression_tests_failed"] = int(graphrag_meta.get("impacted_failed", 0) or 0)
        graphrag_meta["regression_signal_reliable"] = bool(
            graphrag_meta.get("impacted_execution_reliable", False)
        )
        return True

    def _can_enter_intra_attempt_repair(
        self,
        *,
        graphrag_enabled: bool,
        patch: str,
        source_changed_files: Optional[list[str]],
    ) -> tuple[bool, str]:
        if not graphrag_enabled:
            return True, ""
        if not str(patch or "").strip():
            return False, "no_non_empty_patch_candidate"
        if not list(source_changed_files or []):
            return False, "no_source_patch_candidate"
        return True, ""

    def _has_semantic_code_change(
        self,
        *,
        added_lines: list[str],
        removed_lines: list[str],
    ) -> bool:
        doc_markers = {'"""', "'''"}
        for raw_line in list(added_lines or []) + list(removed_lines or []):
            stripped = str(raw_line or "").strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                continue
            if stripped in doc_markers:
                continue
            return True
        return False

    def _update_post_edit_no_diff_streak(
        self,
        *,
        round_mode: str,
        edit_seen: bool,
        seen_nonempty: bool,
        cmd_flags: dict[str, bool],
        current_sig: str,
        prev_sig: str,
        streak: int,
    ) -> tuple[int, bool]:
        if str(round_mode or "default") != "default":
            return 0, False
        if not edit_seen or not seen_nonempty:
            return 0, False
        if cmd_flags.get("is_edit") or cmd_flags.get("is_test"):
            return 0, False
        if current_sig != "EMPTY" and current_sig == prev_sig:
            next_streak = int(streak or 0) + 1
            return next_streak, next_streak >= int(self.post_edit_no_diff_streak_limit or 0)
        return 0, False

    def _is_noop_first_edit_attempt(
        self,
        *,
        cmd_flags: dict[str, bool],
        seen_nonempty: bool,
        prev_sig: str,
        current_sig: str,
    ) -> bool:
        if not cmd_flags.get("is_edit"):
            return False
        if seen_nonempty:
            return False
        return str(prev_sig or "") == "EMPTY" and str(current_sig or "") == "EMPTY"

    def _apply_graphrag_impact_result(
        self,
        *,
        graphrag_meta: dict[str, Any],
        impacted: dict[str, Any],
        effective_strategy: str,
        indexed_signal_mode: str,
    ) -> None:
        graphrag_meta["indexed_search_success"] = bool(
            impacted.get("impact_query_success", impacted.get("success", False))
        )
        graphrag_meta["indexed_query_success"] = bool(
            graphrag_meta["indexed_search_success"]
        )
        graphrag_meta["impact_strategy_effective"] = effective_strategy
        graphrag_meta["impacted_total"] = int(impacted.get("total_impacted", 0) or 0)
        graphrag_meta["impacted_run"] = int(impacted.get("tests_run", 0) or 0)
        graphrag_meta["impacted_failed"] = int(impacted.get("failed", 0) or 0)
        graphrag_meta["impacted_failed_tests"] = list(impacted.get("failed_tests", []) or [])
        graphrag_meta["impacted_success"] = bool(impacted.get("success", False))
        graphrag_meta["impacted_error"] = str(impacted.get("error", "") or "")
        graphrag_meta["impact_empty_reason"] = str(
            impacted.get("error", "")
            or impacted.get("impact_error", "")
            or ""
        )
        graphrag_meta["impacted_execution_reliable"] = bool(
            impacted.get("execution_reliable", False)
            or (
                bool(impacted.get("success", False))
                and int(impacted.get("tests_run", 0) or 0) > 0
            )
        )
        graphrag_meta["impacted_graph_freshness"] = str(
            impacted.get("graph_freshness", "unknown")
        )
        graphrag_meta["impacted_rebuild_triggered"] = bool(
            impacted.get("rebuild_triggered", False)
        )
        selection_conf = impacted.get("selection_confidence_summary")
        graphrag_meta["impacted_selection_confidence"] = dict(
            selection_conf
            if isinstance(selection_conf, dict)
            else {"high": 0, "medium": 0, "low": 0}
        )
        graphrag_meta["impacted_selected_count"] = int(
            impacted.get("selected_count", 0) or 0
        )
        graphrag_meta["impacted_runnable_count"] = int(
            impacted.get("runnable_count", graphrag_meta["impacted_run"]) or 0
        )
        graphrag_meta["impacted_runnable_ratio"] = float(
            impacted.get("runnable_ratio", 0.0) or 0.0
        )
        graphrag_meta["impacted_precision_score"] = float(
            impacted.get("precision_score", 0.0) or 0.0
        )
        graphrag_meta["impacted_precision_floor_passed"] = bool(
            impacted.get("precision_floor_passed", False)
        )
        graphrag_meta["graph_useful_signal"] = bool(
            impacted.get("graph_useful_signal", False)
        )
        graphrag_meta["graph_fallback_reason"] = str(
            impacted.get("graph_fallback_reason", "") or ""
        )
        graphrag_meta["indexed_search_used"] = self._resolve_indexed_signal(
            graphrag_meta,
            mode=indexed_signal_mode,
        )
        graphrag_meta["regression_source"] = "graph_impacted"
        graphrag_meta["regression_tests_selected"] = int(
            graphrag_meta["impacted_selected_count"] or 0
        )
        graphrag_meta["regression_tests_run"] = int(
            graphrag_meta["impacted_run"] or 0
        )
        graphrag_meta["regression_tests_failed"] = int(
            graphrag_meta["impacted_failed"] or 0
        )
        graphrag_meta["regression_signal_reliable"] = bool(
            graphrag_meta["impacted_execution_reliable"]
        )

    def _extract_return_code(self, observation: str) -> int:
        m = re.search(r"<returncode>(-?\d+)</returncode>", observation)
        if not m:
            return 0
        try:
            return int(m.group(1))
        except ValueError:
            return 0

    def _normalize_command(self, command: str) -> str:
        if not command:
            return ""
        norm = " ".join(command.strip().split())
        norm = re.sub(r"\b\d+\b", "<N>", norm)
        return norm[:400]

    def _looks_like_shell_command(self, command: str) -> bool:
        text = str(command or "").strip()
        if not text:
            return False
        first_line = ""
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            first_line = stripped
            break
        first = first_line.split()[0] if first_line.split() else ""
        if not first:
            return False
        shell_starts = {
            "apply_patch",
            "bash",
            "cat",
            "cd",
            "cp",
            "echo",
            "find",
            "git",
            "grep",
            "head",
            "ls",
            "mkdir",
            "mv",
            "patch",
            "perl",
            "pwd",
            "pytest",
            "python",
            "python3",
            "rg",
            "rm",
            "sed",
            "sh",
            "tail",
            "tee",
            "touch",
            "wc",
            "zsh",
        }
        return (
            first in shell_starts
            or first.startswith("./")
            or "=" in first
            or text == "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
        )

    def _is_noop_echo_command(self, command: str) -> bool:
        text = str(command or "").strip()
        if not text or text == "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT":
            return False
        first_line = ""
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            first_line = stripped
            break
        if not first_line.startswith("echo "):
            return False
        if any(token in text for token in (">", ">>", "| tee", "|tee", "tee ")):
            return False
        return True

    def _is_brittle_python_sed_edit(self, command: str) -> bool:
        text = str(command or "").strip()
        lower = text.lower()
        if "sed -i" not in lower or ".py" not in lower:
            return False
        return (
            len(text) > 180
            or "\\n" in text
            or text.count("\\") >= 8
            or "\n" in text
        )

    def _is_full_python_cat_dump(self, command: str) -> bool:
        text = str(command or "").strip()
        try:
            tokens = shlex.split(text)
        except Exception:
            tokens = text.split()
        if not tokens or tokens[0] != "cat":
            return False
        return any(str(token).endswith(".py") for token in tokens[1:])

    def _extract_shell_fence_actions(self, content: str) -> list[str]:
        actions: list[str] = []
        for match in SHELL_FENCE_REGEX.finditer(str(content or "")):
            lang = str(match.group(1) or "").strip().lower()
            action = str(match.group(2) or "").strip()
            if not action:
                continue
            if lang and lang not in {"bash", "sh", "shell", "zsh"}:
                continue
            if not self._looks_like_shell_command(action):
                continue
            if self._is_noop_echo_command(action):
                continue
            actions.append(action)
        return actions

    def _select_format_salvage_action(
        self,
        content: str,
        *,
        repo_path: Optional[Path] = None,
        round_profile: Optional[dict[str, Any]] = None,
        focus_files: Optional[list[str]] = None,
        edit_seen: bool = False,
        env_bootstrap_fail_streak: int = 0,
        read_only_steps: int = 0,
        exploratory_soft_limit: int = 0,
        diff_excerpt: str = "",
        source_excerpt: str = "",
        verify_command: str = "",
    ) -> Optional[dict[str, Any]]:
        actions = self._extract_shell_fence_actions(content)
        if not actions:
            return None
        ranked_actions = actions[:6]

        ranked: list[tuple[int, int, str, str, str]] = []
        effective_round_profile = dict(round_profile or {"round_mode": "default"})
        for idx, action in enumerate(ranked_actions):
            effective_command = str(action or "").strip()
            blocked_reason = ""
            if repo_path is not None:
                guard = self._apply_round_command_guard(
                    command=action,
                    repo_path=repo_path,
                    round_profile=effective_round_profile,
                    focus_files=focus_files,
                    edit_seen=edit_seen,
                    env_bootstrap_fail_streak=env_bootstrap_fail_streak,
                    read_only_steps=read_only_steps,
                    exploratory_soft_limit=exploratory_soft_limit,
                    diff_excerpt=diff_excerpt,
                    source_excerpt=source_excerpt,
                    verify_command=verify_command,
                )
                effective_command = str(guard.get("command", action) or action).strip()
                if bool(guard.get("blocked")):
                    blocked_reason = str(guard.get("reason", "command_blocked") or "command_blocked")
            if blocked_reason:
                continue
            flags = self._classify_command(effective_command)
            submit_only = effective_command == "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
            if flags["is_edit"]:
                priority = 4
                reason = "multiple_blocks_first_edit"
            elif flags["is_test"]:
                priority = 3
                reason = "multiple_blocks_first_test"
            elif flags["is_exploratory"]:
                priority = 1
                reason = "multiple_blocks_first_exploratory"
            else:
                priority = 2
                reason = "multiple_blocks_first_other"
            if submit_only and len(actions) > 1:
                priority = -1
                reason = "defer_submit_block"
            ranked.append((priority, -idx, reason, effective_command, action))

        ranked.sort(reverse=True)
        if not ranked:
            return None
        priority, neg_idx, reason, effective_command, raw_action = ranked[0]
        if priority < 0:
            return None
        return {
            "action": effective_command,
            "raw_action": raw_action,
            "reason": reason,
            "block_count": len(actions),
        }

    def _extract_command_guard_reason(self, observation: str) -> str:
        text = str(observation or "")
        m = re.search(r"COMMAND_GUARD:([^\n<]+)", text)
        return str(m.group(1)).strip() if m else ""

    def _command_guard_counts_toward_loop_metrics(self, guard_reason: str) -> bool:
        """Command-guard rejections did not execute, so they should not advance loop counters."""
        return not bool(str(guard_reason or "").strip())

    def _classify_command(self, command: str) -> dict[str, bool]:
        cmd = str(command or "")
        lower = cmd.lower()
        base = cmd.strip().split()[0] if cmd.strip().split() else ""
        is_test = (
            "pytest" in lower
            or "python -m pytest" in lower
            or "python3 -m pytest" in lower
            or re.search(r"\btox\b", lower) is not None
            or re.search(r"\bnox\b", lower) is not None
        )
        edit_markers = (
            "sed -i",
            "perl -i",
            "apply_patch",
            "git apply",
            "patch -p",
            "write_text(",
            "cat >",
            "tee ",
            ">>",
        )
        is_inline_python = (
            "python - <<" in lower
            or "python3 - <<" in lower
            or "python -c" in lower
            or "python3 -c" in lower
        )
        python_edit_markers = (
            "write_text(",
            ".write(",
            "writelines(",
            "truncate(",
            "rename(",
            "unlink(",
            "replace(",
        )
        is_edit = any(marker in lower for marker in edit_markers) or (
            is_inline_python and any(marker in lower for marker in python_edit_markers)
        )
        is_exploratory = (
            base in {"find", "grep", "rg", "ls", "pwd", "head", "tail", "cat", "nl", "wc", "sed"}
            and not is_test
            and not is_edit
        )
        return {
            "is_test": bool(is_test),
            "is_edit": bool(is_edit),
            "is_exploratory": bool(is_exploratory),
        }

    def _rewrite_multiline_python_c(self, command: str) -> tuple[str, bool]:
        cmd = str(command or "")
        m = re.search(r"\b(python(?:3)?)\s+-c\s+", cmd)
        if not m:
            return cmd, False
        suffix = cmd[m.end() :].lstrip()
        if not suffix or suffix[0] not in {"'", '"'}:
            return cmd, False
        quote = suffix[0]
        body = suffix[1:]
        closing_index = body.rfind(quote)
        if closing_index < 0:
            return cmd, False
        script = body[:closing_index]
        if "\n" not in script:
            return cmd, False
        prefix = cmd[: m.start()]
        trailing = body[closing_index + 1 :]
        # Preserve behavior for simple "cd ... && python -c ..." shapes.
        if trailing.strip():
            return cmd, False
        exe = str(m.group(1))
        heredoc = f"{exe} - <<'PY'\n{script}\nPY"
        return f"{prefix}{heredoc}", True

    def _is_repair_noise_python_file(self, candidate: str) -> bool:
        rel_norm = str(candidate or "").strip().lstrip("./").replace("\\", "/")
        if not rel_norm.endswith(".py") or "/" in rel_norm:
            return False
        basename = os.path.basename(rel_norm).lower()
        return bool(
            re.match(
                r"^(repro|reproduce|scratch|debug|tmp|temp|issue_repro|test_issue|check_issue|diagnose).*\.py$",
                basename,
            )
        )

    def _rewrite_repo_paths(self, command: str, repo_path: Path) -> tuple[str, bool]:
        cmd = str(command or "")
        repo_abs = str(repo_path.resolve())
        rewritten = cmd
        rewritten = re.sub(r"(?<![\w/])/repo\b", repo_abs, rewritten)
        rewritten = re.sub(r"(?<![\w/])/opt/miniconda3\b", repo_abs, rewritten)
        return rewritten, rewritten != cmd

    def _rewrite_macos_sed_inplace(self, command: str) -> tuple[str, bool]:
        """Normalize `sed -i` to the macOS-compatible form when possible."""
        cmd = str(command or "")
        if sys.platform != "darwin":
            return cmd, False
        if "sed -i " not in cmd:
            return cmd, False
        if "sed -i ''" in cmd or "sed -i''" in cmd:
            return cmd, False
        rewritten = cmd.replace("sed -i ", "sed -i '' ")
        return rewritten, rewritten != cmd

    def _extract_diff_anchor_line(self, diff_excerpt: str) -> str:
        text = str(diff_excerpt or "")
        if not text:
            return ""
        fallback = ""
        for raw_line in text.splitlines():
            if raw_line.startswith(("diff --git", "---", "+++", "@@")):
                continue
            if not raw_line.startswith(("-", "+", " ")):
                continue
            candidate = raw_line[1:].strip()
            if not candidate:
                continue
            if len(candidate) < 8 or len(candidate) > 160:
                continue
            if not fallback:
                fallback = candidate
            looks_prose = (
                candidate.startswith(("#", '"""', "'''"))
                or bool(re.search(r"\b[a-zA-Z_][a-zA-Z0-9_]*\s*:\s*[A-Za-z_][A-Za-z0-9_.\[\]]*", candidate))
                or (
                    not re.search(r"[=(){}\[\]:]", candidate)
                    and candidate.endswith((".", ","))
                )
            )
            if looks_prose:
                continue
            return candidate
        return fallback

    def _build_direct_edit_command_example(
        self,
        *,
        primary_file: str,
        diff_excerpt: str = "",
    ) -> str:
        primary = str(primary_file or "").strip().lstrip("./").replace("\\", "/")
        anchor = self._extract_diff_anchor_line(diff_excerpt)
        if anchor:
            return (
                "python3 - <<'PY'\n"
                "from pathlib import Path\n"
                f"p = Path('{primary}')\n"
                "text = p.read_text()\n"
                f"old = {anchor!r}\n"
                "new = 'REPLACED_BLOCK'\n"
                "assert old in text, 'anchor_missing'\n"
                "p.write_text(text.replace(old, new, 1))\n"
                f"print('patched {primary}')\n"
                "PY"
            )
        return (
            "python3 - <<'PY'\n"
            "from pathlib import Path\n"
            f"p = Path('{primary}')\n"
            "text = p.read_text()\n"
            "p.write_text(text.replace('OLD_BLOCK', 'NEW_BLOCK', 1))\n"
            f"print('patched {primary}')\n"
            "PY"
        )

    def _parse_diff_new_start_line(self, diff_excerpt: str) -> Optional[int]:
        text = str(diff_excerpt or "")
        if not text:
            return None
        match = re.search(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", text, re.MULTILINE)
        if not match:
            return None
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            return None

    def _parse_compile_error_line(self, error_text: str) -> Optional[int]:
        text = str(error_text or "")
        match = re.search(r"@(\d+):\d+\s*$", text)
        if not match:
            match = re.search(r"line (\d+)", text)
        if not match:
            return None
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            return None

    def _build_source_excerpt(
        self,
        repo_path: Path,
        *,
        file_path: str,
        center_line: Optional[int] = None,
        context_lines: int = 8,
        max_chars: int = 1400,
    ) -> str:
        rel_path = str(file_path or "").strip().lstrip("./").replace("\\", "/")
        if not rel_path:
            return ""
        abs_path = (repo_path / rel_path).resolve(strict=False)
        try:
            abs_path.relative_to(repo_path.resolve())
        except Exception:
            return ""
        if not abs_path.exists() or not abs_path.is_file():
            return ""
        try:
            text = abs_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = abs_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""
        lines = text.splitlines()
        if not lines:
            return ""
        line_no = int(center_line or 1)
        line_no = max(1, min(line_no, len(lines)))
        start = max(1, line_no - max(1, int(context_lines or 1)))
        end = min(len(lines), line_no + max(1, int(context_lines or 1)))
        excerpt = "\n".join(
            f"{idx:>4}: {lines[idx - 1]}"
            for idx in range(start, end + 1)
        )
        if len(excerpt) > max_chars:
            excerpt = excerpt[:max_chars].rstrip() + "\n... [excerpt truncated]"
        return excerpt

    def _find_anchor_line_in_source(
        self,
        lines: list[str],
        *,
        anchor_text: str = "",
        near_line: Optional[int] = None,
    ) -> Optional[int]:
        anchor = str(anchor_text or "").strip()
        if not anchor or not lines:
            return None
        matches: list[int] = []
        for idx, line in enumerate(lines, start=1):
            if anchor in line:
                matches.append(idx)
        if not matches:
            return None
        if near_line is None:
            return matches[0]
        return min(matches, key=lambda idx: abs(idx - int(near_line)))

    def _find_enclosing_symbol_line(
        self,
        lines: list[str],
        *,
        line_no: int,
    ) -> tuple[Optional[int], str]:
        if not lines:
            return None, ""
        cursor = max(1, min(int(line_no or 1), len(lines)))
        pattern = re.compile(r"^\s*(def|class)\s+([A-Za-z_][A-Za-z0-9_]*)\b")
        for idx in range(cursor, 0, -1):
            match = pattern.match(lines[idx - 1])
            if match:
                return idx, str(match.group(2) or "").strip()
        return None, ""

    def _build_source_excerpt_context(
        self,
        repo_path: Path,
        *,
        file_path: str,
        center_line: Optional[int] = None,
        anchor_text: str = "",
        context_lines: int = 8,
        max_chars: int = 1400,
    ) -> dict[str, Any]:
        rel_path = str(file_path or "").strip().lstrip("./").replace("\\", "/")
        if not rel_path:
            return {
                "excerpt": "",
                "file_path": "",
                "source_kind": "none",
                "center_line": None,
                "anchor_line": None,
                "symbol_line": None,
                "symbol_name": "",
            }
        abs_path = (repo_path / rel_path).resolve(strict=False)
        try:
            abs_path.relative_to(repo_path.resolve())
        except Exception:
            return {
                "excerpt": "",
                "file_path": rel_path,
                "source_kind": "none",
                "center_line": None,
                "anchor_line": None,
                "symbol_line": None,
                "symbol_name": "",
            }
        if not abs_path.exists() or not abs_path.is_file():
            return {
                "excerpt": "",
                "file_path": rel_path,
                "source_kind": "none",
                "center_line": None,
                "anchor_line": None,
                "symbol_line": None,
                "symbol_name": "",
            }
        try:
            text = abs_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = abs_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return {
                "excerpt": "",
                "file_path": rel_path,
                "source_kind": "none",
                "center_line": None,
                "anchor_line": None,
                "symbol_line": None,
                "symbol_name": "",
            }
        lines = text.splitlines()
        if not lines:
            return {
                "excerpt": "",
                "file_path": rel_path,
                "source_kind": "none",
                "center_line": None,
                "anchor_line": None,
                "symbol_line": None,
                "symbol_name": "",
            }

        requested_center = max(1, min(int(center_line or 1), len(lines)))
        anchor_line = self._find_anchor_line_in_source(
            lines,
            anchor_text=anchor_text,
            near_line=requested_center,
        )
        resolved_center = anchor_line or requested_center
        symbol_line, symbol_name = self._find_enclosing_symbol_line(
            lines,
            line_no=resolved_center,
        )

        source_kind = "generic_file_excerpt"
        if anchor_line is not None:
            source_kind = "diff_hunk"
        elif symbol_line is not None and resolved_center > 1:
            source_kind = "function_anchor"

        if symbol_line is not None:
            start = max(1, symbol_line)
            end = min(
                len(lines),
                max(
                    resolved_center + max(2, int(context_lines or 1)),
                    symbol_line + max(10, int(context_lines or 1) * 2),
                ),
            )
        else:
            start = max(1, resolved_center - max(1, int(context_lines or 1)))
            end = min(len(lines), resolved_center + max(1, int(context_lines or 1)))
        excerpt = "\n".join(
            f"{idx:>4}: {lines[idx - 1]}"
            for idx in range(start, end + 1)
        )
        if len(excerpt) > max_chars:
            excerpt = excerpt[:max_chars].rstrip() + "\n... [excerpt truncated]"
        return {
            "excerpt": excerpt,
            "file_path": rel_path,
            "source_kind": source_kind,
            "center_line": resolved_center,
            "anchor_line": anchor_line,
            "symbol_line": symbol_line,
            "symbol_name": symbol_name,
        }

    def _build_focus_source_excerpt(
        self,
        repo_path: Path,
        *,
        focus_files: Optional[list[str]] = None,
        diff_excerpt: str = "",
        current_error: str = "",
        anchor_file: str = "",
        include_meta: bool = False,
    ) -> Any:
        selected = [
            str(path).strip().lstrip("./").replace("\\", "/")
            for path in (focus_files or [])
            if str(path).strip()
        ]
        normalized_anchor = str(anchor_file or "").strip().lstrip("./").replace("\\", "/")
        if normalized_anchor:
            if normalized_anchor in selected:
                selected = [normalized_anchor] + [path for path in selected if path != normalized_anchor]
            else:
                selected = [normalized_anchor] + selected
        if not selected:
            return {} if include_meta else ""
        center_line = self._parse_compile_error_line(current_error)
        if center_line is None:
            center_line = self._parse_diff_new_start_line(diff_excerpt)
        context = self._build_source_excerpt_context(
            repo_path,
            file_path=selected[0],
            center_line=center_line,
            anchor_text=self._extract_diff_anchor_line(diff_excerpt),
        )
        return context if include_meta else str(context.get("excerpt", "") or "")

    def _build_verify_command(
        self,
        *,
        round_mode: str,
        focus_files: Optional[list[str]] = None,
        failing_tests: Optional[list[str]] = None,
        compile_failed_files: Optional[list[str]] = None,
    ) -> str:
        mode = str(round_mode or "default").strip().lower() or "default"
        selected_tests = [
            str(test).strip()
            for test in (failing_tests or [])
            if str(test).strip()
        ]
        if selected_tests and mode != "compile_repair":
            return self._format_pytest_command(selected_tests, max_args=2)
        compile_files = [
            str(path).strip().lstrip("./").replace("\\", "/")
            for path in (compile_failed_files or [])
            if str(path).strip()
        ]
        if mode == "compile_repair" and compile_files:
            quoted = " ".join(shlex.quote(path) for path in compile_files[:2])
            return f"python -m py_compile {quoted}"
        selected = [
            str(path).strip().lstrip("./").replace("\\", "/")
            for path in (focus_files or [])
            if str(path).strip()
        ]
        test_files = [
            path for path in selected
            if "/tests/" in path
            or path.startswith("tests/")
            or os.path.basename(path).startswith("test_")
            or path.endswith("_test.py")
        ]
        if test_files:
            return f"python -m pytest -q {shlex.quote(test_files[0])}"
        py_files = [path for path in selected if path.endswith(".py")]
        if py_files:
            return f"python -m py_compile {shlex.quote(py_files[0])}"
        return ""

    def _summarize_previous_wrong_hypothesis(
        self,
        prev_candidate: Optional[dict[str, Any]],
    ) -> str:
        candidate = dict(prev_candidate or {})
        changed_files = [
            str(path).strip().lstrip("./").replace("\\", "/")
            for path in (candidate.get("changed_files") or [])
            if str(path).strip()
        ]
        patch_text = str(candidate.get("prediction", "") or "")
        function_names: list[str] = []
        for match in re.finditer(r"^[+\- ]\s*def\s+([A-Za-z_][A-Za-z0-9_]*)", patch_text, re.MULTILINE):
            name = str(match.group(1))
            if name not in function_names:
                function_names.append(name)
        if not changed_files and not function_names:
            return ""
        parts: list[str] = []
        if changed_files:
            parts.append("changed " + ", ".join(changed_files[:3]))
        if function_names:
            parts.append("touched " + ", ".join(function_names[:3]))
        return "; ".join(parts)

    def _build_edit_required_message(
        self,
        *,
        round_label: str,
        focus_files: Optional[list[str]] = None,
        exploratory_limit: int = 2,
        diff_excerpt: str = "",
        source_excerpt: str = "",
        verify_command: str = "",
    ) -> str:
        selected = [
            str(path).strip().lstrip("./").replace("\\", "/")
            for path in (focus_files or [])
            if str(path).strip()
        ]
        label = str(round_label or "This round").strip() or "This round"
        limit = max(0, int(exploratory_limit or 0))
        if limit == 0:
            limit_line = f"{label}: no exploratory commands are allowed before the next edit."
        elif limit == 1:
            limit_line = f"{label} allows at most 1 exploratory command before the next edit."
        else:
            limit_line = f"{label} allows at most {limit} exploratory commands before the next edit."
        lines = [
            limit_line,
            "Your next command MUST be a direct edit, not another search/read command.",
        ]
        if selected:
            lines.append("Edit one of these files now:")
            for path in selected[:3]:
                lines.append(f"- {path}")
            primary = selected[0]
            lines.extend(
                [
                    "Run a direct edit command next, for example:",
                    self._build_direct_edit_command_example(
                        primary_file=primary,
                        diff_excerpt=diff_excerpt,
                    ),
                ]
            )
            if source_excerpt:
                lines.extend(
                    [
                        "Relevant source excerpt:",
                        "```python",
                        source_excerpt,
                        "```",
                    ]
                )
            if verify_command:
                lines.extend(
                    [
                        "After the edit, verify with:",
                        verify_command,
                    ]
                )
        else:
            lines.append("Edit the most likely source file directly with a heredoc or corrected sed command.")
        return "\n".join(lines)

    def _is_inline_python_runtime_probe(
        self,
        command: str,
        *,
        cmd_flags: Optional[dict[str, bool]] = None,
    ) -> bool:
        lower = str(command or "").lower()
        is_inline_python = (
            "python -c" in lower
            or "python3 -c" in lower
            or "python - <<" in lower
            or "python3 - <<" in lower
        )
        if not is_inline_python:
            return False
        flags = cmd_flags or self._classify_command(command)
        if flags.get("is_edit") or flags.get("is_test"):
            return False
        if "python -m py_compile" in lower or "python3 -m py_compile" in lower:
            return False
        return True

    def _is_compound_exploratory_command(
        self,
        command: str,
        *,
        cmd_flags: Optional[dict[str, bool]] = None,
    ) -> bool:
        text = str(command or "")
        if not text:
            return False
        flags = cmd_flags or self._classify_command(command)
        if flags.get("is_edit") or flags.get("is_test"):
            return False
        return "&&" in text or "||" in text

    def _build_repair_edit_required_message(
        self,
        *,
        focus_files: Optional[list[str]] = None,
        diff_excerpt: str = "",
        source_excerpt: str = "",
        verify_command: str = "",
    ) -> str:
        """Build a direct-edit hint when repair-round exploration is exhausted."""
        return self._build_edit_required_message(
            round_label="Repair rounds",
            focus_files=focus_files,
            exploratory_limit=0,
            diff_excerpt=diff_excerpt,
            source_excerpt=source_excerpt,
            verify_command=verify_command,
        )

    def _command_cd_targets_outside_repo(self, command: str, repo_path: Path) -> list[str]:
        repo_abs = repo_path.resolve()
        targets_outside: list[str] = []
        for m in re.finditer(r"(?:^|&&|\|\||;)\s*cd\s+([^\s;&|]+)", str(command or "")):
            raw_target = str(m.group(1)).strip().strip("'\"")
            if not raw_target:
                continue
            if any(token in raw_target for token in ("$", "`", "$(", "${")):
                targets_outside.append(raw_target)
                continue
            target_path = Path(raw_target)
            try:
                resolved = (
                    target_path.expanduser().resolve(strict=False)
                    if target_path.is_absolute()
                    else (repo_abs / target_path).resolve(strict=False)
                )
                resolved.relative_to(repo_abs)
            except Exception:
                targets_outside.append(raw_target)
        return targets_outside

    def _preflight_command(self, *, command: str, repo_path: Path) -> dict[str, Any]:
        raw_command = str(command or "").strip()
        if not raw_command:
            return {
                "blocked": True,
                "reason": "lint_empty_command",
                "command": raw_command,
                "message": "Empty command blocked.",
            }

        lint_patterns = (
            "<format_example>",
            "<response_example>",
            "<example_response>",
            "<step>",
            "<returncode>",
            "```",
        )
        lower_raw = raw_command.lower()
        if any(pattern in lower_raw for pattern in lint_patterns):
            return {
                "blocked": True,
                "reason": "lint_malformed_command",
                "command": raw_command,
                "message": "Malformed command contained prompt/format artifacts.",
            }

        rewritten = raw_command
        rewritten, py_rewritten = self._rewrite_multiline_python_c(rewritten)
        if ("python -c" in rewritten.lower() or "python3 -c" in rewritten.lower()) and "\n" in rewritten:
            return {
                "blocked": True,
                "reason": "lint_multiline_python_c_blocked",
                "command": rewritten,
                "message": "Multiline python -c blocked; use python heredoc.",
            }

        rewritten, sed_rewritten = self._rewrite_macos_sed_inplace(rewritten)
        rewritten, path_rewritten = self._rewrite_repo_paths(rewritten, repo_path)
        outside_targets = self._command_cd_targets_outside_repo(rewritten, repo_path)
        if outside_targets:
            return {
                "blocked": True,
                "reason": "path_mismatch_outside_repo",
                "command": rewritten,
                "message": (
                    "Command attempted to cd outside repository root: "
                    + ", ".join(outside_targets[:3])
                ),
            }

        lower_rewritten = rewritten.lower()
        if re.search(r"\bgit\s+checkout\b", lower_rewritten) or re.search(
            r"\bgit\s+restore\b", lower_rewritten
        ):
            return {
                "blocked": True,
                "reason": "git_revert_blocked",
                "command": rewritten,
                "message": (
                    "Self-revert commands are blocked during benchmark runs. "
                    "Modify the current candidate patch instead of reverting it."
                ),
            }
        if self._is_noop_echo_command(rewritten):
            return {
                "blocked": True,
                "reason": "lint_noop_echo",
                "command": rewritten,
                "message": (
                    "Standalone echo commands are explanatory no-ops here. "
                    "Read a file, edit a file, run targeted pytest/py_compile, or submit."
                ),
            }
        if self._is_brittle_python_sed_edit(rewritten):
            return {
                "blocked": True,
                "reason": "lint_brittle_sed_edit",
                "command": rewritten,
                "message": (
                    "Long or multiline sed rewrites against Python files are blocked. "
                    "Use a safer python/pathlib edit or a smaller single-line replacement."
                ),
            }

        return {
            "blocked": False,
            "reason": "",
            "command": rewritten,
            "rewritten": bool(py_rewritten or path_rewritten or sed_rewritten),
        }

    def _apply_round_command_guard(
        self,
        *,
        command: str,
        repo_path: Path,
        round_profile: dict[str, Any],
        focus_files: Optional[list[str]] = None,
        edit_seen: bool = False,
        env_bootstrap_fail_streak: int = 0,
        read_only_steps: int = 0,
        exploratory_soft_limit: int = 0,
        diff_excerpt: str = "",
        source_excerpt: str = "",
        verify_command: str = "",
    ) -> dict[str, Any]:
        guard = self._preflight_command(command=command, repo_path=repo_path)
        effective_cmd = str(guard.get("command", command) or command)
        if bool(guard.get("blocked")):
            return guard

        if effective_cmd == "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT":
            patch_gate = self._validate_patch_quality(repo_path)
            fail_reasons = {
                str(reason).strip()
                for reason in list(patch_gate.get("fail_reasons") or [])
                if str(reason).strip()
            }
            if "empty_diff" in fail_reasons or "comment_only_diff" in fail_reasons:
                guidance = self._build_minimal_fix_guidance(
                    diff_excerpt=str(patch_gate.get("diff", "") or ""),
                    patch_gate_reason=str(patch_gate.get("reason", "") or ""),
                )
                return {
                    "blocked": True,
                    "reason": "submit_requires_semantic_patch",
                    "command": effective_cmd,
                    "message": (
                        "Submission is blocked because the current patch is not a valid executable fix yet. "
                        + guidance
                    ),
                }

        normalized_focus_files = [
            str(path).strip().lstrip("./").replace("\\", "/")
            for path in (focus_files or [])
            if str(path).strip()
        ]
        if not normalized_focus_files or edit_seen:
            return guard

        if (
            bool(round_profile.get("block_scratch_python_before_edit"))
            or str(round_profile.get("round_mode", "default")) == "default"
        ):
            scratch_target = self._repair_round_scratch_python_target(
                command=effective_cmd,
                repo_path=repo_path,
                focus_files=normalized_focus_files,
            )
            if scratch_target:
                repair_round = str(round_profile.get("round_mode", "default")) != "default"
                guard_reason = (
                    "repair_round_scratch_python_file"
                    if repair_round
                    else "default_round_scratch_python_file"
                )
                guard_message = (
                    "Repair rounds must edit existing source/test files directly. "
                    if repair_round
                    else "Default round already has a failing repro test. "
                    "Edit existing source/test files directly instead of creating scratch python files. "
                )
                return {
                    "blocked": True,
                    "reason": guard_reason,
                    "command": effective_cmd,
                    "message": f"{guard_message}Blocked scratch python file creation: {scratch_target}",
                }

        cmd_flags = self._classify_command(effective_cmd)
        if self._is_full_python_cat_dump(effective_cmd):
            return {
                "blocked": True,
                "reason": "focus_round_full_file_dump",
                "command": effective_cmd,
                "message": (
                    "Full-file Python dumps are blocked in focused rounds because they bloat prompt context. "
                    "Use `sed -n`, `nl -ba`, or `grep -n` on a narrow range instead."
                ),
            }
        if env_bootstrap_fail_streak >= 1 and cmd_flags["is_test"]:
            return {
                "blocked": True,
                "reason": "focus_round_test_after_env_fail",
                "command": effective_cmd,
                "message": (
                    "A focused runtime test already failed due to environment/bootstrap noise. "
                    "Do not spend another pre-edit turn on pytest right now. Read or edit a focus file instead."
                ),
            }
        if self._is_compound_exploratory_command(effective_cmd, cmd_flags=cmd_flags):
            repair_round = str(round_profile.get("round_mode", "default")) != "default"
            return {
                "blocked": True,
                "reason": (
                    "repair_round_compound_exploration"
                    if repair_round
                    else "default_round_compound_exploration"
                ),
                "command": effective_cmd,
                "message": (
                    "Use exactly one focused command per turn here. "
                    "Do not chain exploratory shell commands before the first edit."
                ),
            }
        if self._is_inline_python_runtime_probe(effective_cmd, cmd_flags=cmd_flags):
            repair_round = str(round_profile.get("round_mode", "default")) != "default"
            return {
                "blocked": True,
                "reason": "focus_round_inline_python_probe",
                "command": effective_cmd,
                "message": (
                    "Inline python runtime probes are blocked once a failing repro test and focus files are known. "
                    + (
                        "Edit a focus file directly now."
                        if repair_round
                        else "Edit a focus file directly or run a targeted pytest/py_compile command instead."
                    )
                ),
            }

        if (
            bool(round_profile.get("require_direct_edit_first"))
            and cmd_flags["is_exploratory"]
            and not cmd_flags["is_edit"]
        ):
            return {
                "blocked": True,
                "reason": "repair_round_edit_required",
                "command": effective_cmd,
                "message": self._build_repair_edit_required_message(
                    focus_files=normalized_focus_files,
                    diff_excerpt=diff_excerpt,
                    source_excerpt=source_excerpt,
                    verify_command=verify_command,
                ),
            }

        exploratory_limit = int(round_profile.get("exploratory_pre_edit_limit", 0) or 0)
        if exploratory_limit <= 0 and exploratory_soft_limit > 0:
            exploratory_limit = exploratory_soft_limit
        if exploratory_limit > 0 and cmd_flags["is_exploratory"] and read_only_steps >= exploratory_limit:
            repair_round = str(round_profile.get("round_mode", "default")) != "default"
            guard_reason = (
                "repair_round_exploration_cap"
                if repair_round
                else "default_round_edit_required"
            )
            guard_message = (
                self._build_repair_edit_required_message(
                    focus_files=normalized_focus_files,
                    diff_excerpt=diff_excerpt,
                    source_excerpt=source_excerpt,
                    verify_command=verify_command,
                )
                if repair_round
                else self._build_edit_required_message(
                    round_label="Default round",
                    focus_files=normalized_focus_files,
                    exploratory_limit=exploratory_limit,
                    diff_excerpt=diff_excerpt,
                    source_excerpt=source_excerpt,
                    verify_command=verify_command,
                )
            )
            return {
                "blocked": True,
                "reason": guard_reason,
                "command": effective_cmd,
                "message": guard_message,
            }

        return guard

    def _compute_diff_signature(self, repo_path: Path) -> str:
        try:
            status_result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=False,
            )
            status_text = str(status_result.stdout or "").strip()
            if not status_text:
                return "EMPTY"
            return f"STATUS_LEN:{len(status_text)}|HASH:{hash(status_text[:5000])}"
        except Exception:
            return "DIFF_ERR"

    def _format_pytest_command(self, tests: list[str], *, max_args: int = 3) -> str:
        if not tests:
            return "python -m pytest -q"
        selected = tests[:max_args]
        suffix = ""
        if len(tests) > max_args:
            suffix = f" ... (+{len(tests) - max_args} more)"
        args = " ".join(shlex.quote(t) for t in selected)
        return f"python -m pytest -q {args}{suffix}"

    def _run_pre_edit_repro_probe(
        self,
        repo_path: Path,
        fail_to_pass_tests: list[str],
        log=print,
    ) -> dict[str, Any]:
        selected = list(fail_to_pass_tests[: max(1, self.pre_edit_repro_max_tests)])
        if not selected:
            return {
                "command": "",
                "ran": False,
                "failed": False,
                "failed_count": 0,
                "total": 0,
                "infra_unreliable": False,
                "infra_reason": "",
                "signal_confidence": 1.0,
                "retry_variant_used": "",
                "runtime_strategy": "",
                "runtime_fallback_used": "",
                "runtime_unreliable_reason": "",
                "runtime_env_id": "",
                "runtime_bootstrap_error": "",
                "runtime_bootstrap_error_reason": "",
                "runtime_install_mode": "",
                "variant_attempts": [],
            }

        timeout = min(max(30, self.pre_edit_repro_timeout_sec), max(30, self.pytest_timeout))
        command = self._format_pytest_command(selected, max_args=3)
        log(f"PHASE: PRE_EDIT_REPRO_START cmd={command}")
        result = self._run_pytest_subset(repo_path, selected, timeout=timeout, log=log)
        failed_count = int(result.get("failed", 0) or 0)
        passed_count = int(result.get("passed", 0) or 0)
        ran = (failed_count + passed_count) > 0
        failed = failed_count > 0
        log(
            "PHASE: PRE_EDIT_REPRO_END "
            f"failed={failed} failed_count={failed_count}/{len(selected)} "
            f"infra_unreliable={bool(result.get('infra_unreliable'))}"
        )
        return {
            "command": command,
            "ran": ran,
            "failed": failed,
            "failed_count": failed_count,
            "total": len(selected),
            "infra_unreliable": bool(result.get("infra_unreliable")),
            "infra_reason": str(result.get("infra_reason", "") or ""),
            "signal_confidence": float(result.get("signal_confidence", 1.0) or 1.0),
            "retry_variant_used": str(result.get("retry_variant_used", "") or ""),
            "runtime_strategy": str(result.get("runtime_strategy", "") or ""),
            "runtime_fallback_used": str(result.get("runtime_fallback_used", "") or ""),
            "runtime_unreliable_reason": str(result.get("runtime_unreliable_reason", "") or ""),
            "runtime_env_id": str(result.get("runtime_env_id", "") or ""),
            "runtime_bootstrap_error": str(result.get("runtime_bootstrap_error", "") or ""),
            "runtime_bootstrap_error_reason": str(result.get("runtime_bootstrap_error_reason", "") or ""),
            "runtime_install_mode": str(result.get("runtime_install_mode", "") or ""),
            "variant_attempts": list(result.get("variant_attempts") or []),
        }

    def _compute_tdd_evidence(
        self,
        *,
        tdd_mode: bool,
        strict_tdd_evidence: bool,
        fail_to_pass_tests: list[str],
        pass_to_pass_tests: list[str],
        pre_edit_repro: dict[str, Any],
        test_metrics: dict[str, Any],
        patch_gate_valid: bool,
        strict_tdd_infra_policy: str = "fail_closed",
        require_test_change: bool = False,
        unit_test_changed: bool = True,
    ) -> dict[str, Any]:
        if not tdd_mode:
            return {
                "repro_cmd_present": True,
                "repro_failed_before_edit": True,
                "verify_cmd_present": True,
                "verify_pass_after_edit": True,
                "smoke_cmd_present": True,
                "smoke_pass_after_edit": True,
                "tdd_evidence_complete": True,
                "evidence_reason": "",
                "tdd_fail_open_applied": False,
                "tdd_infra_reasons": [],
                "required_test_added": True,
                "infra_mode_effective": "off",
                "tdd_contract_stage": "complete",
            }

        f2p_total = int(test_metrics.get("f2p_total", 0) or 0)
        p2p_total = int(test_metrics.get("p2p_smoke_total", 0) or 0)
        p2p_fail = test_metrics.get("p2p_smoke_failures")
        verify_cmd_present = f2p_total > 0
        verify_pass_after_edit = bool(test_metrics.get("f2p_all_passed", False)) if verify_cmd_present else False
        smoke_cmd_present = p2p_total > 0
        smoke_pass_after_edit = bool(smoke_cmd_present and p2p_fail == 0)

        # Fallback smoke signal when PASS_TO_PASS is unavailable: compile gate.
        if not smoke_cmd_present and not pass_to_pass_tests:
            smoke_cmd_present = True
            smoke_pass_after_edit = bool(patch_gate_valid)

        has_f2p_contract = bool(fail_to_pass_tests)
        repro_cmd_present = bool(pre_edit_repro.get("command")) if has_f2p_contract else True
        repro_failed_before_edit = bool(pre_edit_repro.get("failed")) if has_f2p_contract else True

        infra_policy = str(strict_tdd_infra_policy or self.strict_tdd_infra_policy or "fail_closed").strip().lower()
        if infra_policy not in {"fail_closed", "retry_then_fail_open", "fail_open"}:
            infra_policy = "fail_closed"
        allow_infra_fail_open = infra_policy in {"retry_then_fail_open", "fail_open"}

        f2p_reliable = test_metrics.get("f2p_reliable")
        p2p_reliable = test_metrics.get("p2p_reliable")
        verify_infra_unreliable = bool(verify_cmd_present and f2p_reliable is False)
        smoke_infra_unreliable = bool(smoke_cmd_present and p2p_reliable is False)
        tdd_fail_open_applied = False
        tdd_infra_reasons: list[str] = []

        missing: list[str] = []
        if not repro_cmd_present:
            missing.append("missing_repro_command")
        if not repro_failed_before_edit:
            missing.append("repro_not_failing_pre_edit")
        if require_test_change and not unit_test_changed:
            missing.append("missing_repo_test_change")
        if not verify_cmd_present:
            missing.append("missing_verify_command")
        if not verify_pass_after_edit:
            if allow_infra_fail_open and verify_infra_unreliable:
                tdd_fail_open_applied = True
                tdd_infra_reasons.append(str(test_metrics.get("f2p_infra_reason", "") or "verify_infra_unreliable"))
            else:
                missing.append("verify_not_passing_post_edit")
        if not smoke_cmd_present:
            missing.append("missing_smoke_command")
        if not smoke_pass_after_edit:
            if allow_infra_fail_open and smoke_infra_unreliable:
                tdd_fail_open_applied = True
                tdd_infra_reasons.append(str(test_metrics.get("p2p_infra_reason", "") or "smoke_infra_unreliable"))
            else:
                missing.append("smoke_not_passing_post_edit")

        evidence_complete = len(missing) == 0
        if not strict_tdd_evidence:
            evidence_complete = True
            missing = []

        return {
            "repro_cmd_present": repro_cmd_present,
            "repro_failed_before_edit": repro_failed_before_edit,
            "verify_cmd_present": verify_cmd_present,
            "verify_pass_after_edit": verify_pass_after_edit,
            "smoke_cmd_present": smoke_cmd_present,
            "smoke_pass_after_edit": smoke_pass_after_edit,
            "tdd_evidence_complete": evidence_complete,
            "evidence_reason": (
                ""
                if evidence_complete
                else f"tdd_evidence_incomplete:{','.join(missing)}"
            ),
            "tdd_fail_open_applied": bool(tdd_fail_open_applied),
            "tdd_infra_reasons": sorted({reason for reason in tdd_infra_reasons if reason}),
            "required_test_added": bool((not require_test_change) or unit_test_changed),
            "infra_mode_effective": infra_policy,
            "tdd_contract_stage": "complete" if evidence_complete else "incomplete",
        }

    def _run_changed_test_file_fallback(
        self,
        *,
        repo_path: Path,
        changed_files: list[str],
        log=print,
        max_files: int = 8,
    ) -> dict[str, Any]:
        """Run changed repository test files when impacted nodeids are unrunnable."""
        changed_test_files = self._extract_test_file_changes(
            changed_files,
            policy="repo_tests_only",
        )
        if not changed_test_files:
            return {}

        selected = list(changed_test_files[: max(1, max_files)])
        log(
            "GraphRAG fallback selected changed repo test files: "
            f"{', '.join(selected[:4])}"
            + (f" ... (+{len(selected) - 4} more)" if len(selected) > 4 else "")
        )
        result = self._run_pytest_subset(
            repo_path,
            selected,
            timeout=min(max(60, self.pytest_timeout), 300),
            log=log,
        )
        passed = int(result.get("passed", 0) or 0)
        failed = int(result.get("failed", 0) or 0)
        infra_unreliable = bool(result.get("infra_unreliable"))
        tests_run = passed + failed
        failed_tests: list[dict[str, Any]] = []
        if failed > 0:
            for path in selected[: min(len(selected), failed)]:
                failed_tests.append(
                    {
                        "test_name": path,
                        "full_name": path,
                        "test_file": path,
                        "error": "changed_test_file_fallback_failed",
                    }
                )
        return {
            "tests_run": tests_run,
            "passed": passed,
            "failed": failed,
            "success": (failed == 0) and (tests_run > 0) and (not infra_unreliable),
            "execution_reliable": not infra_unreliable,
            "failed_tests": failed_tests,
            "selected_tests": list(selected),
        }

    def _run_graphrag_impact_query(
        self,
        *,
        graphrag_mcp,
        repo_path: Path,
        impact_input_files: list[str],
        impact_threshold: float,
        max_tests: int,
        strategy: str,
        require_fresh_graph: bool,
        log=print,
    ) -> tuple[dict[str, Any], str]:
        """Run GraphRAG impacted-test query with optional hybrid coverage fallback."""
        impacted = graphrag_mcp.run_impacted_tests_iteratively(
            repo_path=str(repo_path),
            changed_files=impact_input_files,
            impact_threshold=impact_threshold,
            max_tests=max_tests,
            strategy=strategy,
            require_fresh_graph=require_fresh_graph,
        )
        effective_strategy = str(strategy or "")
        impacted_success = bool(impacted.get("success", False))
        impacted_run = int(impacted.get("tests_run", 0) or 0)
        impacted_total = int(impacted.get("total_impacted", 0) or 0)

        if strategy == "hybrid" and (not impacted_success or impacted_run <= 0):
            fallback = graphrag_mcp.run_impacted_tests_iteratively(
                repo_path=str(repo_path),
                changed_files=impact_input_files,
                impact_threshold=impact_threshold,
                max_tests=max_tests,
                strategy="coverage_diff",
                require_fresh_graph=require_fresh_graph,
            )
            fallback_success = bool(fallback.get("success", False))
            fallback_run = int(fallback.get("tests_run", 0) or 0)
            fallback_total = int(fallback.get("total_impacted", 0) or 0)
            if (
                fallback_run > impacted_run
                or fallback_total > impacted_total
                or (fallback_success and not impacted_success)
            ):
                impacted = fallback
                effective_strategy = "coverage_diff_fallback"
                log(
                    "GraphRAG hybrid fallback used coverage_diff: "
                    f"total={fallback_total} run={fallback_run} success={fallback_success}"
                )
        return impacted, effective_strategy

    def _derive_graphrag_seed_files(
        self,
        *,
        repo_path: Path,
        problem_statement: str,
        fail_to_pass_tests: list[str],
        max_files: int = 8,
    ) -> list[str]:
        repo_root = repo_path.resolve()
        candidates: list[str] = []

        for raw in re.findall(r"([A-Za-z0-9_./-]+\.py)", str(problem_statement or "")):
            candidates.append(raw)

        for nodeid in fail_to_pass_tests or []:
            token = str(nodeid or "").split("::", 1)[0].strip()
            if token.endswith(".py"):
                for source_candidate in self._derive_source_candidate_from_test_file(repo_path, token):
                    candidates.append(source_candidate)
                candidates.append(token)

        normalized: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            path_text = str(candidate or "").strip()
            if not path_text:
                continue
            rel_text = path_text
            if path_text.startswith(str(repo_root)):
                rel_text = os.path.relpath(path_text, repo_root)
            rel_text = rel_text.lstrip("./")
            abs_path = (repo_root / rel_text).resolve(strict=False)
            try:
                abs_path.relative_to(repo_root)
            except Exception:
                continue
            if not abs_path.exists() or not abs_path.is_file():
                continue
            rel_norm = abs_path.relative_to(repo_root).as_posix()
            if rel_norm not in seen:
                seen.add(rel_norm)
                normalized.append(rel_norm)
            if len(normalized) >= max(1, max_files):
                break
        return self._prioritize_focus_files(normalized, max_files=max_files)

    def _run_deterministic_targeted_tests(
        self,
        *,
        repo_path: Path,
        fail_to_pass_tests: list[str],
        pass_to_pass_tests: list[str],
        log=print,
    ) -> dict[str, Any]:
        targets: list[str] = []
        seen: set[str] = set()
        for nodeid in (fail_to_pass_tests or [])[:3]:
            token = str(nodeid or "").strip()
            if token and token not in seen:
                seen.add(token)
                targets.append(token)
        for nodeid in (pass_to_pass_tests or [])[:2]:
            token = str(nodeid or "").strip()
            if token and token not in seen:
                seen.add(token)
                targets.append(token)
        if not targets:
            return {}

        log(
            "Deterministic targeted fallback selected: "
            + ", ".join(targets[:4])
            + (f" ... (+{len(targets) - 4} more)" if len(targets) > 4 else "")
        )
        result = self._run_pytest_subset(
            repo_path,
            targets,
            timeout=min(max(60, self.pytest_timeout), 240),
            log=log,
        )
        passed = int(result.get("passed", 0) or 0)
        failed = int(result.get("failed", 0) or 0)
        tests_run = passed + failed
        infra_unreliable = bool(result.get("infra_unreliable"))
        failed_tests: list[dict[str, Any]] = []
        if failed > 0:
            for name in targets[: min(len(targets), failed)]:
                failed_tests.append(
                    {
                        "test_name": name,
                        "full_name": name,
                        "test_file": str(name).split("::", 1)[0],
                        "error": "deterministic_targeted_fallback_failed",
                    }
                )
        return {
            "tests_run": tests_run,
            "passed": passed,
            "failed": failed,
            "success": (failed == 0) and (tests_run > 0) and (not infra_unreliable),
            "execution_reliable": not infra_unreliable,
            "failed_tests": failed_tests,
            "selected_tests": list(targets),
        }

    def _evaluate_candidate(
        self,
        repo_path: Path,
        fail_to_pass_tests: list[str],
        pass_to_pass_tests: list[str],
        require_test_checks: bool,
        log=print,
    ) -> dict[str, Any]:
        metrics: dict[str, Any] = {
            "f2p_total": len(fail_to_pass_tests),
            "f2p_passed": None,
            "f2p_failed": None,
            "f2p_pass_rate": None,
            "f2p_all_passed": False,
            "f2p_reliable": None,
            "f2p_infra_reason": "",
            "f2p_signal_confidence": 1.0,
            "f2p_retry_variant_used": "",
            "f2p_runtime_strategy": "",
            "f2p_runtime_fallback_used": "",
            "f2p_runtime_unreliable_reason": "",
            "f2p_variant_attempts": [],
            "f2p_runtime_env_id": "",
            "f2p_runtime_bootstrap_error": "",
            "f2p_runtime_bootstrap_error_reason": "",
            "f2p_runtime_install_mode": "",
            "verify_cmd": "",
            "p2p_smoke_total": None,
            "p2p_smoke_failures": None,
            "p2p_reliable": None,
            "p2p_infra_reason": "",
            "p2p_signal_confidence": 1.0,
            "p2p_retry_variant_used": "",
            "p2p_runtime_strategy": "",
            "p2p_runtime_fallback_used": "",
            "p2p_runtime_unreliable_reason": "",
            "p2p_variant_attempts": [],
            "p2p_runtime_env_id": "",
            "p2p_runtime_bootstrap_error": "",
            "p2p_runtime_bootstrap_error_reason": "",
            "p2p_runtime_install_mode": "",
            "smoke_cmd": "",
            "test_signal_reliable": True,
            "test_signal_confidence": 1.0,
            "clean_resolution": None,
        }
        if not require_test_checks:
            return metrics

        reliability_flags: list[bool] = []
        confidence_values: list[float] = []
        if fail_to_pass_tests:
            metrics["verify_cmd"] = self._format_pytest_command(fail_to_pass_tests, max_args=3)
            f2p = self._run_pytest_subset(repo_path, fail_to_pass_tests, timeout=self.pytest_timeout, log=log)
            metrics["f2p_passed"] = f2p["passed"]
            metrics["f2p_failed"] = f2p["failed"]
            total = max(len(fail_to_pass_tests), 1)
            metrics["f2p_pass_rate"] = f2p["passed"] / total
            metrics["f2p_all_passed"] = f2p["failed"] == 0
            metrics["f2p_reliable"] = not bool(f2p.get("infra_unreliable"))
            metrics["f2p_infra_reason"] = str(f2p.get("infra_reason", "") or "")
            metrics["f2p_signal_confidence"] = float(f2p.get("signal_confidence", 1.0) or 1.0)
            metrics["f2p_retry_variant_used"] = str(f2p.get("retry_variant_used", "") or "")
            metrics["f2p_runtime_strategy"] = str(f2p.get("runtime_strategy", "") or "")
            metrics["f2p_runtime_fallback_used"] = str(f2p.get("runtime_fallback_used", "") or "")
            metrics["f2p_runtime_unreliable_reason"] = str(
                f2p.get("runtime_unreliable_reason", "") or ""
            )
            metrics["f2p_variant_attempts"] = list(f2p.get("variant_attempts") or [])
            metrics["f2p_runtime_env_id"] = str(f2p.get("runtime_env_id", "") or "")
            metrics["f2p_runtime_bootstrap_error"] = str(f2p.get("runtime_bootstrap_error", "") or "")
            metrics["f2p_runtime_bootstrap_error_reason"] = str(
                f2p.get("runtime_bootstrap_error_reason", "") or ""
            )
            metrics["f2p_runtime_install_mode"] = str(f2p.get("runtime_install_mode", "") or "")
            reliability_flags.append(bool(metrics["f2p_reliable"]))
            confidence_values.append(float(metrics["f2p_signal_confidence"]))
            log(
                "F2P check: "
                f"passed={metrics['f2p_passed']} failed={metrics['f2p_failed']} total={len(fail_to_pass_tests)}"
            )
            if not metrics["f2p_reliable"]:
                log(f"F2P signal unreliable: {f2p.get('infra_reason', 'infra_failure')}")
            if metrics["f2p_retry_variant_used"]:
                log(f"F2P retry variant used: {metrics['f2p_retry_variant_used']}")
            if metrics["f2p_runtime_fallback_used"]:
                log(f"F2P runtime fallback used: {metrics['f2p_runtime_fallback_used']}")

        smoke_tests = pass_to_pass_tests[:self.p2p_smoke_count]
        if smoke_tests:
            metrics["smoke_cmd"] = self._format_pytest_command(smoke_tests, max_args=3)
            p2p = self._run_pytest_subset(repo_path, smoke_tests, timeout=self.pytest_timeout, log=log)
            metrics["p2p_smoke_total"] = len(smoke_tests)
            metrics["p2p_smoke_failures"] = p2p["failed"]
            metrics["p2p_reliable"] = not bool(p2p.get("infra_unreliable"))
            metrics["p2p_infra_reason"] = str(p2p.get("infra_reason", "") or "")
            metrics["p2p_signal_confidence"] = float(p2p.get("signal_confidence", 1.0) or 1.0)
            metrics["p2p_retry_variant_used"] = str(p2p.get("retry_variant_used", "") or "")
            metrics["p2p_runtime_strategy"] = str(p2p.get("runtime_strategy", "") or "")
            metrics["p2p_runtime_fallback_used"] = str(p2p.get("runtime_fallback_used", "") or "")
            metrics["p2p_runtime_unreliable_reason"] = str(
                p2p.get("runtime_unreliable_reason", "") or ""
            )
            metrics["p2p_variant_attempts"] = list(p2p.get("variant_attempts") or [])
            metrics["p2p_runtime_env_id"] = str(p2p.get("runtime_env_id", "") or "")
            metrics["p2p_runtime_bootstrap_error"] = str(p2p.get("runtime_bootstrap_error", "") or "")
            metrics["p2p_runtime_bootstrap_error_reason"] = str(
                p2p.get("runtime_bootstrap_error_reason", "") or ""
            )
            metrics["p2p_runtime_install_mode"] = str(p2p.get("runtime_install_mode", "") or "")
            reliability_flags.append(bool(metrics["p2p_reliable"]))
            confidence_values.append(float(metrics["p2p_signal_confidence"]))
            log(
                "P2P smoke: "
                f"failed={metrics['p2p_smoke_failures']} total={metrics['p2p_smoke_total']}"
            )
            if not metrics["p2p_reliable"]:
                log(f"P2P signal unreliable: {p2p.get('infra_reason', 'infra_failure')}")
            if metrics["p2p_retry_variant_used"]:
                log(f"P2P retry variant used: {metrics['p2p_retry_variant_used']}")
            if metrics["p2p_runtime_fallback_used"]:
                log(f"P2P runtime fallback used: {metrics['p2p_runtime_fallback_used']}")

        if reliability_flags:
            metrics["test_signal_reliable"] = all(reliability_flags)
        if confidence_values:
            metrics["test_signal_confidence"] = min(confidence_values)

        if metrics["f2p_all_passed"] and metrics["p2p_smoke_failures"] is not None:
            metrics["clean_resolution"] = metrics["p2p_smoke_failures"] == 0
        return metrics

    def _run_pytest_subset(self, repo_path: Path, tests: list[str], timeout: int, log=print) -> dict[str, Any]:
        repo_root = repo_path.resolve()
        test_list = list(tests)
        runtime_strategy = "repo_python_first_then_importlib_fallback"
        variant_attempts: list[dict[str, Any]] = []
        runtime = self.test_runtime_manager.get_runtime(repo_root, log=log)
        runtime_env_id = str(runtime.get("runtime_env_id", "") or "")
        runtime_bootstrap_error = str(runtime.get("bootstrap_error", "") or "")
        runtime_bootstrap_error_reason = str(runtime.get("bootstrap_error_reason", "") or "")
        runtime_ready = bool(runtime.get("runtime_ready", True))
        runtime_python = str(runtime.get("python_executable", sys.executable) or sys.executable)
        runtime_bootstrap_actions = list(runtime.get("bootstrap_actions") or [])
        runtime_install_mode = str(runtime.get("runtime_install_mode", "") or "")
        runtime_bootstrap_attempts = list(runtime.get("runtime_bootstrap_attempts") or [])
        runtime_base_env = dict(runtime.get("env") or os.environ)

        def _finalize(payload: dict[str, Any], *, fallback_used: str = "") -> dict[str, Any]:
            payload["retry_variant_used"] = str(fallback_used or "")
            payload["runtime_strategy"] = runtime_strategy
            payload["runtime_fallback_used"] = str(fallback_used or "")
            payload["runtime_unreliable_reason"] = (
                str(payload.get("infra_reason", "") or "")
                if bool(payload.get("infra_unreliable"))
                else ""
            )
            payload["variant_attempts"] = list(variant_attempts)
            payload["runtime_env_id"] = runtime_env_id
            payload["runtime_bootstrap_error"] = runtime_bootstrap_error
            payload["runtime_bootstrap_error_reason"] = runtime_bootstrap_error_reason
            payload["runtime_bootstrap_actions"] = list(runtime_bootstrap_actions)
            payload["runtime_install_mode"] = runtime_install_mode
            payload["runtime_bootstrap_attempts"] = list(runtime_bootstrap_attempts)
            return payload

        def _normalized_pytest_env(*, ignore_import_mismatch: bool = False) -> dict[str, str]:
            env = dict(runtime_base_env)
            extra_paths = [str(repo_root)]
            for candidate in ("src", "lib"):
                path = repo_root / candidate
                if path.exists() and path.is_dir():
                    extra_paths.append(str(path))
            existing = env.get("PYTHONPATH", "")
            if existing:
                extra_paths.append(existing)
            deduped: list[str] = []
            seen: set[str] = set()
            for entry in extra_paths:
                if entry and entry not in seen:
                    seen.add(entry)
                    deduped.append(entry)
            env["PYTHONPATH"] = os.pathsep.join(deduped)
            if ignore_import_mismatch:
                env["PY_IGNORE_IMPORTMISMATCH"] = "1"
            else:
                env.pop("PY_IGNORE_IMPORTMISMATCH", None)
            return env

        if not test_list:
            return _finalize(
                {
                    "passed": 0,
                    "failed": 0,
                    "returncode": 0,
                    "output": "",
                    "infra_unreliable": False,
                    "infra_reason": "",
                    "signal_confidence": 1.0,
                    "variant": "no_tests",
                    "command": "",
                }
            )

        if not runtime_ready:
            runtime_infra_reason = runtime_bootstrap_error_reason or "runtime_bootstrap_failed"
            variant_attempts.append(
                {
                    "variant": "runtime_bootstrap",
                    "command": "",
                    "returncode": 1,
                    "infra_unreliable": True,
                    "infra_reason": runtime_infra_reason,
                    "passed": 0,
                    "failed": len(test_list),
                    "signal_confidence": 0.1,
                }
            )
            return _finalize(
                {
                    "passed": 0,
                    "failed": len(test_list),
                    "returncode": 1,
                    "output": runtime_bootstrap_error[:2000],
                    "infra_unreliable": True,
                    "infra_reason": runtime_infra_reason,
                    "signal_confidence": 0.1,
                    "variant": "runtime_bootstrap",
                    "command": "",
                }
            )

        def _run_variant(
            *,
            variant: str,
            import_mode_importlib: bool,
            ignore_import_mismatch: bool = False,
            disable_warnings_plugin: bool = False,
            cache_clear: bool = False,
        ) -> dict[str, Any]:
            cmd = [runtime_python, "-m", "pytest", "-q"]
            if disable_warnings_plugin:
                cmd.extend(["-p", "no:warnings"])
            if import_mode_importlib:
                cmd.append("--import-mode=importlib")
            if cache_clear:
                cmd.append("--cache-clear")
            cmd.extend(test_list)
            command = " ".join(cmd)
            try:
                result = subprocess.run(
                    cmd,
                    cwd=repo_root,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                    env=_normalized_pytest_env(ignore_import_mismatch=ignore_import_mismatch),
                )
                output = f"{result.stdout}\n{result.stderr}"
                infra_unreliable, infra_reason = self._detect_pytest_infra_failure(output, result.returncode)
                passed, failed = self._parse_pytest_counts(output)
                if passed + failed == 0:
                    if result.returncode == 0:
                        passed = len(test_list)
                    else:
                        failed = max(1, len(test_list))
                passed = min(max(int(passed), 0), len(test_list))
                failed = min(max(int(failed), 0), len(test_list))
                # When pytest reports concrete pass/fail counts, warnings-plugin
                # hook conflicts are noisy but not necessarily signal-breaking.
                if (
                    infra_unreliable
                    and infra_reason == "warnings_hook_conflict"
                    and (passed + failed) > 0
                ):
                    infra_unreliable = False
                    infra_reason = ""
                confidence = 0.92
                if import_mode_importlib:
                    confidence = 0.88
                if disable_warnings_plugin:
                    confidence = min(confidence, 0.84)
                if infra_unreliable:
                    confidence = 0.35
                payload = {
                    "passed": passed,
                    "failed": failed,
                    "returncode": result.returncode,
                    "output": output[:2000],
                    "infra_unreliable": infra_unreliable,
                    "infra_reason": infra_reason,
                    "signal_confidence": confidence,
                    "variant": variant,
                    "command": command,
                }
            except subprocess.TimeoutExpired:
                log(f"pytest timeout on {len(test_list)} test(s) variant={variant}")
                payload = {
                    "passed": 0,
                    "failed": len(test_list),
                    "returncode": 124,
                    "output": "timeout",
                    "infra_unreliable": True,
                    "infra_reason": "pytest_timeout",
                    "signal_confidence": 0.2,
                    "variant": variant,
                    "command": command,
                }
            except Exception as exc:
                log(f"pytest execution error ({variant}): {exc}")
                payload = {
                    "passed": 0,
                    "failed": len(test_list),
                    "returncode": 1,
                    "output": str(exc),
                    "infra_unreliable": True,
                    "infra_reason": "pytest_exec_exception",
                    "signal_confidence": 0.2,
                    "variant": variant,
                    "command": command,
                }

            variant_attempts.append(
                {
                    "variant": variant,
                    "command": payload["command"],
                    "returncode": int(payload.get("returncode", 1)),
                    "infra_unreliable": bool(payload.get("infra_unreliable")),
                    "infra_reason": str(payload.get("infra_reason", "") or ""),
                    "passed": int(payload.get("passed", 0) or 0),
                    "failed": int(payload.get("failed", 0) or 0),
                    "signal_confidence": float(payload.get("signal_confidence", 0.0) or 0.0),
                }
            )
            return payload

        def _reason_rank(reason: str) -> int:
            ranking = {
                "runtime_bootstrap_failed": 0,
                "bootstrap_timeout": 2,
                "network_error": 4,
                "pytest_timeout": 6,
                "pytest_missing": 8,
                "distribution_not_found": 14,
                "module_not_found": 16,
                "collection_error": 18,
                "import_error": 20,
                "import_path_mismatch": 22,
                "conftest_import_error": 24,
                "warnings_hook_conflict": 26,
                "source_checkout_unbuilt_extensions": 30,
                "legacy_build_backend_incompat": 32,
                "": 100,
            }
            return ranking.get(str(reason or ""), 12)

        def _is_improved(candidate: dict[str, Any], baseline: dict[str, Any]) -> bool:
            candidate_reliable = not bool(candidate.get("infra_unreliable"))
            baseline_reliable = not bool(baseline.get("infra_unreliable"))
            if candidate_reliable and not baseline_reliable:
                return True
            if candidate_reliable != baseline_reliable:
                return False
            candidate_score = (
                _reason_rank(str(candidate.get("infra_reason", "") or "")),
                int(candidate.get("passed", 0) or 0),
                -int(candidate.get("failed", 0) or 0),
                float(candidate.get("signal_confidence", 0.0) or 0.0),
            )
            baseline_score = (
                _reason_rank(str(baseline.get("infra_reason", "") or "")),
                int(baseline.get("passed", 0) or 0),
                -int(baseline.get("failed", 0) or 0),
                float(baseline.get("signal_confidence", 0.0) or 0.0),
            )
            return candidate_score > baseline_score

        selected = _run_variant(
            variant="repo_python_default",
            import_mode_importlib=False,
        )
        fallback_used = ""
        retry_reasons = {
            "import_path_mismatch",
            "conftest_import_error",
            "module_not_found",
            "collection_error",
            "import_error",
            "warnings_hook_conflict",
        }
        if bool(selected.get("infra_unreliable")) and str(selected.get("infra_reason", "")) in retry_reasons:
            fallback = _run_variant(
                variant="repo_python_importlib_fallback",
                import_mode_importlib=True,
                ignore_import_mismatch=True,
                disable_warnings_plugin=True,
                cache_clear=True,
            )
            if _is_improved(fallback, selected):
                selected = fallback
                fallback_used = str(fallback.get("variant", "repo_python_importlib_fallback"))
            else:
                fallback_used = "repo_python_importlib_fallback_attempted"

        return _finalize(selected, fallback_used=fallback_used)

    def _detect_pytest_infra_failure(self, output: str, returncode: int) -> tuple[bool, str]:
        text = (output or "").lower()
        signatures = {
            "cannot disable warnings logging": "warnings_hook_conflict",
            "pytest-warnings plugin did not import": "warnings_hook_conflict",
            "importpathmismatcherror": "import_path_mismatch",
            "import file mismatch": "import_path_mismatch",
            "importerror while loading conftest": "conftest_import_error",
            "source checkout without building extension modules": "source_checkout_unbuilt_extensions",
            "cannot import astropy from source checkout": "source_checkout_unbuilt_extensions",
            "setuptools.dep_util": "legacy_build_backend_incompat",
            "modulenotfounderror": "module_not_found",
            "no module named": "module_not_found",
            "error collecting": "collection_error",
            "could not import": "import_error",
            "command not found: pytest": "pytest_missing",
            "distributionnotfound": "distribution_not_found",
        }
        for pattern, reason in signatures.items():
            if pattern in text:
                return True, reason
        if returncode == 127:
            return True, "pytest_missing"
        if returncode == 124:
            return True, "pytest_timeout"
        return False, ""

    def _is_structural_bootstrap_infra_reason(
        self,
        infra_reason: str,
        runtime_bootstrap_error_reason: str = "",
    ) -> bool:
        structural = {
            "legacy_build_backend_incompat",
            "editable_build_backend_failure",
            "build_backend_failure",
            "source_checkout_unbuilt_extensions",
            "package_build_failed",
            "wheel_build_failed",
        }
        transient = {
            "pytest_timeout",
            "bootstrap_timeout",
            "pytest_missing",
            "network_error",
        }
        reasons = {
            str(infra_reason or "").strip().lower(),
            str(runtime_bootstrap_error_reason or "").strip().lower(),
        }
        reasons.discard("")
        if not reasons:
            return False
        if reasons & structural:
            return True
        if reasons & transient:
            return False
        return any(
            value.startswith("legacy_build_backend")
            or value.startswith("editable_build_backend")
            or value.startswith("source_checkout_unbuilt_extensions")
            for value in reasons
        )

    def _parse_pytest_counts(self, output: str) -> tuple[int, int]:
        passed = 0
        failed = 0
        pm = re.search(r"(\d+)\s+passed", output)
        fm = re.search(r"(\d+)\s+failed", output)
        if pm:
            passed = int(pm.group(1))
        if fm:
            failed = int(fm.group(1))
        return passed, failed

    def _score_candidate(self, candidate: dict[str, Any]) -> tuple:
        patch_chars = len(candidate.get("prediction", ""))
        non_empty = 1 if patch_chars > 0 else 0
        clean_resolution = 1 if candidate.get("clean_resolution") is True else 0
        verify_pass_after_edit = 1 if candidate.get("verify_pass_after_edit") else 0
        smoke_pass_after_edit = 1 if candidate.get("smoke_pass_after_edit") else 0
        tdd_gate_passed = 1 if candidate.get("tdd_gate_passed", True) else 0
        regression_gate_passed = 1 if candidate.get("regression_gate_passed", True) else 0
        progress_gate_passed = 1 if candidate.get("progress_gate_passed", True) else 0
        submitted_score = 1 if candidate.get("status") == "Submitted" else 0
        gate_severity = str(candidate.get("patch_gate_severity", ""))
        gate_score = {"info": 2, "warn": 1}.get(gate_severity, 0)
        gate_valid = 1 if candidate.get("patch_gate_valid") else 0
        loop_penalty = 1 if candidate.get("loop_abort_reason") else 0
        signature_penalty = 1 if "potential_signature_change" in str(candidate.get("patch_gate_reason", "")) else 0
        changed_lines = int(candidate.get("changed_lines_total") or 0)
        changed_line_penalty = changed_lines if changed_lines > 0 else 10**6
        attempt_idx = int(candidate.get("attempt") or 99)
        f2p_score, p2p_penalty = self._score_test_signal_components(candidate)
        format_errors = int(candidate.get("format_errors") or 0)
        timeout_penalty = int(candidate.get("timeouts") or 0)
        step_penalty = int(candidate.get("steps") or 0)
        graphrag_penalty = 0
        tdd_evidence_penalty = 0 if candidate.get("tdd_evidence_complete", True) else 1
        tdd_fail_open_penalty = 1 if candidate.get("tdd_fail_open_applied") else 0
        required_test_penalty = 0 if candidate.get("required_test_added", True) else 1
        indexed_query_penalty = 0
        if bool(candidate.get("indexed_search_attempted")):
            indexed_query_penalty = 0 if candidate.get("indexed_query_success", False) else 1
        graphrag_meta = candidate.get("graphrag_metadata") or {}
        if graphrag_meta.get("indexed_search_used"):
            impacted_total = int(graphrag_meta.get("impacted_total", 0) or 0)
            impacted_run = int(graphrag_meta.get("impacted_run", 0) or 0)
            impacted_success = graphrag_meta.get("impacted_success")
            if impacted_total <= 0:
                graphrag_penalty += 1
            if impacted_total > 0 and impacted_run <= 0:
                graphrag_penalty += 1
            if impacted_success is False:
                graphrag_penalty += 1
            if graphrag_meta.get("impacted_precision_floor_passed") is False and impacted_total > 0:
                graphrag_penalty += 1
            if graphrag_meta.get("graph_useful_signal") is False:
                graphrag_penalty += 1
            fallback_reason = str(graphrag_meta.get("graph_fallback_reason", "") or "")
            if fallback_reason in {"low_runnable_ratio", "no_runnable_nodeids"}:
                graphrag_penalty += 1
        if bool(candidate.get("indexed_search_attempted")) and int(
            (candidate.get("graphrag_metadata") or {}).get("impacted_run", 0) or 0
        ) <= 0:
            graphrag_penalty += 1
        if bool(candidate.get("graph_signal_unavailable")):
            graphrag_penalty += 2
        if candidate.get("graph_guard_passed") is False:
            graphrag_penalty += 1
        return (
            clean_resolution,
            verify_pass_after_edit,
            smoke_pass_after_edit,
            tdd_gate_passed,
            regression_gate_passed,
            progress_gate_passed,
            gate_valid,
            gate_score,
            submitted_score,
            -signature_penalty,
            f2p_score,
            -p2p_penalty,
            -graphrag_penalty,
            -tdd_evidence_penalty,
            -tdd_fail_open_penalty,
            -required_test_penalty,
            -indexed_query_penalty,
            -loop_penalty,
            -changed_line_penalty,
            -format_errors,
            -timeout_penalty,
            -step_penalty,
            -attempt_idx,
            non_empty,
            -patch_chars,
        )

    def _candidate_verification_progress(self, candidate: dict[str, Any]) -> tuple:
        f2p_rate = candidate.get("f2p_pass_rate")
        f2p_progress = float(f2p_rate) if f2p_rate is not None else 0.0
        p2p_fail = candidate.get("p2p_smoke_failures")
        p2p_penalty = int(p2p_fail) if p2p_fail is not None else 0
        return (
            1 if candidate.get("patch_gate_valid") else 0,
            1 if candidate.get("clean_resolution") is True else 0,
            1 if candidate.get("verify_pass_after_edit") else 0,
            1 if candidate.get("smoke_pass_after_edit") else 0,
            f2p_progress,
            -p2p_penalty,
        )

    def _should_replace_best_candidate(
        self,
        candidate: dict[str, Any],
        score: tuple,
        best_candidate: Optional[dict[str, Any]],
        best_score: Optional[tuple],
    ) -> bool:
        if best_candidate is None or best_score is None:
            return True
        candidate_progress = self._candidate_verification_progress(candidate)
        best_progress = self._candidate_verification_progress(best_candidate)
        if candidate_progress != best_progress:
            return candidate_progress > best_progress
        return score > best_score

    def _score_test_signal_components(self, candidate: dict[str, Any]) -> tuple[float, int]:
        mode = str(self.test_signal_mode or "hard").lower()
        if mode not in {"off", "soft", "hard"}:
            mode = "hard"
        if mode == "off":
            return 0.0, 0

        f2p_rate = candidate.get("f2p_pass_rate")
        f2p_score = float(f2p_rate) if f2p_rate is not None else 0.0
        p2p_fail = candidate.get("p2p_smoke_failures")
        p2p_penalty = int(p2p_fail) if p2p_fail is not None else 0
        confidence = float(candidate.get("test_signal_confidence", 1.0) or 1.0)
        confidence = max(0.0, min(1.0, confidence))
        if candidate.get("test_signal_reliable") is False:
            confidence = min(confidence, 0.35)
        weighted_f2p = f2p_score * confidence
        weighted_p2p = int(round(p2p_penalty * confidence))

        if mode == "soft":
            return weighted_f2p * 0.25, int(round(weighted_p2p * 0.25))
        return weighted_f2p, weighted_p2p

    def _append_repair_focus_guidance(
        self,
        task: str,
        *,
        focus_files: Optional[list[str]] = None,
        require_edit_first: bool = False,
        diff_excerpt: str = "",
    ) -> str:
        selected = [
            str(path).strip().lstrip("./").replace("\\", "/")
            for path in (focus_files or [])
            if str(path).strip()
        ]
        if selected:
            task += "Likely files to inspect/edit first:\n"
            for path in selected[:6]:
                task += f"- {path}\n"
        if str(diff_excerpt or "").strip():
            task += (
                "A non-empty patch already exists. Refine the shown diff hunk or adjacent executable lines "
                "before widening scope to a different helper or file.\n"
            )
        task += "Do not create ad-hoc repro scripts or new top-level Python files in this round.\n"
        if require_edit_first:
            task += "Do not run read/search before first edit in this round.\n"
        else:
            task += "If you need one read command, spend it on a listed likely file, then edit immediately.\n"
        task += "Prefer `python3 - <<'PY'` pathlib edits for multi-line changes; use `sed -i` only for exact anchor-based substitutions.\n"
        if selected:
            task += "Suggested first command shape:\n```bash\n"
            task += self._build_direct_edit_command_example(
                primary_file=selected[0],
                diff_excerpt=diff_excerpt,
            )
            task += "\n```\n"
        return task

    def _build_current_diff_excerpt(
        self,
        repo_path: Path,
        *,
        changed_files: Optional[list[str]] = None,
        max_files: int = 3,
        max_chars: int = 2400,
    ) -> str:
        selected = [
            str(path).strip().lstrip("./").replace("\\", "/")
            for path in (changed_files or self._get_changed_files_any(repo_path))
            if str(path).strip()
        ]
        if not selected:
            return ""
        cmd = ["git", "diff", "--unified=0", "--"] + selected[: max(1, int(max_files or 1))]
        try:
            result = subprocess.run(
                cmd,
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception:
            return ""
        diff_text = str(result.stdout or "").strip()
        if not diff_text:
            return ""
        if len(diff_text) > max_chars:
            diff_text = diff_text[:max_chars].rstrip() + "\n... [diff truncated]"
        return diff_text

    def _build_diff_excerpt_from_patch_text(
        self,
        patch_text: str,
        *,
        max_chars: int = 2400,
    ) -> str:
        diff_text = str(patch_text or "").strip()
        if not diff_text or "diff --git " not in diff_text:
            return ""
        if len(diff_text) > max_chars:
            diff_text = diff_text[:max_chars].rstrip() + "\n... [diff truncated]"
        return diff_text

    def _preview_diff_text(
        self,
        diff_text: str,
        *,
        max_lines: int = 12,
        max_chars: int = 800,
    ) -> str:
        text = str(diff_text or "").strip()
        if not text:
            return ""
        lines = text.splitlines()[: max(1, int(max_lines or 1))]
        preview = "\n".join(lines).strip()
        if len(preview) > max_chars:
            preview = preview[:max_chars].rstrip() + "\n... [preview truncated]"
        return preview

    def _build_minimal_fix_guidance(
        self,
        *,
        diff_excerpt: str = "",
        patch_gate_reason: str = "",
    ) -> str:
        lines = [
            "Minimal fix guidance:",
            "- Stay inside the current hunk in the primary file.",
            "- Prefer replacing one existing executable line or block, not adding explanatory comments or broad new branches.",
            "- Do not change quoting or docstrings unless that is the actual bug fix.",
        ]
        anchor = self._extract_diff_anchor_line(diff_excerpt)
        if anchor:
            lines.append(f"- Start from this current changed line: `{anchor}`")
            lines.append("- Refine the shown hunk directly before switching files or re-deriving a new hypothesis.")
        gate_reason = str(patch_gate_reason or "")
        if "too_many_changed_lines" in gate_reason or "repetitive_code" in gate_reason:
            lines.append("- The previous patch was too large or repetitive. Shrink it to the smallest possible replacement.")
            lines.append("- The next patch should usually stay within one file and about 1-5 executable changed lines.")
            lines.append("- Do not add explanatory comments while shrinking the patch.")
        if "comment_only_diff" in gate_reason:
            lines.append("- Comments alone will not be accepted. Change executable code.")
        return "\n".join(lines)

    def _build_candidate_debug_summary(self, candidate: dict[str, Any]) -> str:
        changed_files = ",".join(list(candidate.get("changed_files") or [])[:3]) or "-"
        return (
            f"attempt={candidate.get('attempt')} "
            f"patch_chars={len(candidate.get('prediction', '') or '')} "
            f"gate={candidate.get('patch_gate_reason', '') or 'ok'} "
            f"verify={bool(candidate.get('verify_pass_after_edit'))} "
            f"smoke={bool(candidate.get('smoke_pass_after_edit'))} "
            f"regression_source={candidate.get('regression_source', 'none')} "
            f"changed_files={changed_files}"
        )

    def _log_candidate_debug(
        self,
        *,
        log,
        prefix: str,
        candidate: Optional[dict[str, Any]],
    ) -> None:
        payload = dict(candidate or {})
        if not payload:
            return
        log(f"{prefix} {self._build_candidate_debug_summary(payload)}")
        diff_preview = self._preview_diff_text(str(payload.get("prediction", "") or ""))
        if diff_preview:
            log(f"{prefix}_DIFF\n{diff_preview}")

    def _log_round_context(
        self,
        *,
        log,
        round_mode: str,
        focus_files: Optional[list[str]] = None,
        verify_command: str = "",
        diff_excerpt: str = "",
        source_excerpt: str = "",
        source_context_meta: Optional[dict[str, Any]] = None,
    ) -> None:
        selected = self._prioritize_focus_files(
            [
                str(path).strip().lstrip("./").replace("\\", "/")
                for path in (focus_files or [])
                if str(path).strip()
            ],
            max_files=4,
        )
        anchor = self._extract_diff_anchor_line(diff_excerpt)
        summary = [
            f"mode={str(round_mode or 'default')}",
            f"focus={','.join(selected) if selected else '-'}",
            f"verify={verify_command or '-'}",
            f"anchor={anchor or '-'}",
        ]
        log("ROUND_CONTEXT " + " ".join(summary))
        diff_preview = self._preview_diff_text(diff_excerpt)
        if diff_preview:
            log("ROUND_CONTEXT_DIFF\n" + diff_preview)
        meta = dict(source_context_meta or {})
        if meta:
            meta_summary = [
                f"kind={meta.get('source_kind') or 'none'}",
                f"file={meta.get('file_path') or '-'}",
                f"line={meta.get('center_line') or '-'}",
                f"symbol={meta.get('symbol_name') or '-'}",
            ]
            log("ROUND_CONTEXT_SOURCE_META " + " ".join(meta_summary))
        source_preview = self._preview_diff_text(source_excerpt, max_lines=10, max_chars=700)
        if source_preview:
            log("ROUND_CONTEXT_SOURCE\n" + source_preview)

    def _build_prompt_trace_id(self, round_mode: str) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        mode = re.sub(r"[^a-z0-9]+", "", str(round_mode or "default").lower())[:12] or "default"
        return f"{mode}_{os.getpid()}_{stamp}"

    def _estimate_prompt_tokens(self, text: str) -> int:
        payload = str(text or "")
        if not payload:
            return 0
        divisor = max(1, int(self.prompt_token_estimate_divisor or 4))
        return (len(payload) + divisor - 1) // divisor

    def _resolve_backend_context_window_tokens(self) -> Optional[int]:
        backend = getattr(self, "local_backend", None)
        provider = str(getattr(backend, "provider", "") or "").strip().lower()
        env_prefix = str(getattr(backend, "env_prefix", "QWEN_MINI") or "QWEN_MINI").strip()
        env_names: list[str] = []
        default_value = ""
        if provider == "llamacpp":
            env_names = [
                f"{env_prefix}_LLAMACPP_CTX_SIZE",
                "QWEN_LLAMACPP_CTX_SIZE",
            ]
            default_value = "16384"
        elif provider == "ollama":
            env_names = [
                f"{env_prefix}_OLLAMA_NUM_CTX",
                "QWEN_OLLAMA_NUM_CTX",
                "OLLAMA_NUM_CTX",
            ]
        elif provider == "mlxlm":
            env_names = [
                f"{env_prefix}_MLXLM_CTX_SIZE",
                "QWEN_MLXLM_CTX_SIZE",
                "MLXLM_CTX_SIZE",
            ]
        raw_value = ""
        for env_name in env_names:
            candidate = str(os.getenv(env_name, "")).strip()
            if candidate:
                raw_value = candidate
                break
        if not raw_value:
            raw_value = default_value
        resolved = _read_int_env(raw_value, 0, minimum=0)
        return resolved or None

    def _resolve_prompt_budget(self) -> dict[str, Any]:
        divisor = max(1, int(getattr(self, "prompt_token_estimate_divisor", 4) or 4))
        configured_chars = max(4000, int(getattr(self, "prompt_budget_chars", 48000) or 48000))
        configured_tokens = max(0, int(getattr(self, "prompt_budget_tokens", 0) or 0))
        context_window_tokens = self._resolve_backend_context_window_tokens()
        budget_source = "chars_only"
        budget_tokens: Optional[int] = None

        if configured_tokens > 0:
            budget_tokens = configured_tokens
            budget_source = "explicit_tokens"
        elif context_window_tokens:
            generation_reserve = max(512, int(getattr(self, "model_max_tokens", 0) or 0))
            protocol_overhead = max(512, min(2048, context_window_tokens // 8))
            raw_budget = max(1024, context_window_tokens - generation_reserve - protocol_overhead)
            budget_tokens = max(1024, int(raw_budget * 0.85))
            budget_source = "backend_context_window"

        conservative_chars_per_token = max(2, divisor - 1)
        budget_chars = configured_chars
        if budget_tokens is not None:
            derived_chars = max(4000, int(budget_tokens * conservative_chars_per_token))
            if configured_tokens > 0 or not str(os.getenv("QWEN_MINI_PROMPT_BUDGET_CHARS", "")).strip():
                budget_chars = min(configured_chars, derived_chars)
            else:
                budget_chars = min(configured_chars, derived_chars)

        return {
            "budget_chars": max(4000, int(budget_chars or configured_chars)),
            "budget_tokens": budget_tokens,
            "context_window_tokens": context_window_tokens,
            "budget_source": budget_source,
        }

    def _prompt_exceeds_budget(
        self,
        text: str,
        *,
        budget_chars: int,
        budget_tokens: Optional[int],
    ) -> bool:
        payload = str(text or "")
        if len(payload) > max(4000, int(budget_chars or 0)):
            return True
        if budget_tokens is not None and self._estimate_prompt_tokens(payload) > max(0, int(budget_tokens)):
            return True
        return False

    def _replace_regex_block(
        self,
        text: str,
        pattern: str,
        replacement_fn,
        *,
        flags: int = re.DOTALL,
        limit: int = 0,
    ) -> tuple[str, int]:
        compiled = re.compile(pattern, flags)
        replacements = 0

        def _wrapped(match: re.Match[str]) -> str:
            nonlocal replacements
            if limit and replacements >= limit:
                return match.group(0)
            replacements += 1
            return replacement_fn(match)

        return compiled.sub(_wrapped, text), replacements

    def _collect_prompt_section_sizes(self, task: str) -> dict[str, int]:
        text = str(task or "")
        total = len(text)
        retry_size = 0
        diff_size = 0
        source_size = 0
        failure_size = 0

        retry_start = text.find("\n\n## Retry Guidance\n")
        if retry_start >= 0:
            next_markers = [
                marker
                for marker in (
                    "\nBest-so-far diff excerpt:\n",
                    "\nCurrent diff excerpt:\n",
                    "\nCurrent source excerpt:\n",
                    "\nPreferred verification command",
                    "\nKnown failing target tests:\n",
                )
                if text.find(marker, retry_start + 1) >= 0
            ]
            next_positions = [text.find(marker, retry_start + 1) for marker in next_markers]
            retry_end = min(next_positions) if next_positions else total
            retry_size = max(0, retry_end - retry_start)

        diff_size = sum(
            len(match.group(0))
            for match in re.finditer(
                r"\n(?:Current diff excerpt|Best-so-far diff excerpt|Current rejected diff excerpt):\n```diff\n.*?\n```\n?",
                text,
                re.DOTALL,
            )
        )
        source_size = sum(
            len(match.group(0))
            for match in re.finditer(
                r"\n(?:Current source excerpt|Compile-error source excerpt):\n```python\n.*?\n```\n?",
                text,
                re.DOTALL,
            )
        )
        failure_patterns = (
            r"Known failing target tests:\n(?:- .*\n)+",
            r"\nFailing files:\n(?:- .*\n)+",
            r"\n\n## (?:Repair Round|Compile Repair Round|GraphRAG Impacted Test Failures|Changed-Test Regression Failures|Fallback Regression Failures)\n",
        )
        for pattern in failure_patterns:
            failure_size += sum(len(match.group(0)) for match in re.finditer(pattern, text, re.DOTALL))

        first_dynamic = re.search(
            r"\n\n## (?:Retry Guidance|Repair Round|Compile Repair Round|GraphRAG Impacted Test Failures|Changed-Test Regression Failures|Fallback Regression Failures)\n",
            text,
        )
        task_size = first_dynamic.start() if first_dynamic else total
        guidance_size = max(0, total - task_size - retry_size - diff_size - source_size - failure_size)
        return {
            "task": max(0, task_size),
            "retry_text": max(0, retry_size),
            "diff_excerpt": max(0, diff_size),
            "source_excerpt": max(0, source_size),
            "failure_test_context": max(0, failure_size),
            "guidance": max(0, guidance_size),
        }

    def _truncate_retry_guidance(self, task: str) -> tuple[str, int]:
        text = str(task or "")
        start = text.find("\n\n## Retry Guidance\n")
        if start < 0:
            return text, 0
        next_markers = [
            position
            for position in (
                text.find("\nBest-so-far diff excerpt:\n", start + 1),
                text.find("\nCurrent diff excerpt:\n", start + 1),
                text.find("\nCurrent source excerpt:\n", start + 1),
                text.find("\nPreferred verification command", start + 1),
                text.find("\nKnown failing target tests:\n", start + 1),
            )
            if position >= 0
        ]
        end = min(next_markers) if next_markers else len(text)
        original = text[start:end]
        replacement = "\n\n## Retry Guidance\n[trimmed for prompt budget]\n"
        updated = text[:start] + replacement + text[end:]
        return updated, max(0, len(original) - len(replacement))

    def _truncate_fenced_section(
        self,
        task: str,
        *,
        headings: tuple[str, ...],
        language: str,
        max_content_chars: int,
        note: str,
    ) -> tuple[str, int]:
        text = str(task or "")
        total_trimmed = 0
        heading_group = "|".join(re.escape(item) for item in headings)
        pattern = (
            rf"\n(?:{heading_group}):\n```{re.escape(language)}\n"
            r"(.*?)\n```\n?"
        )

        def _replacement(match: re.Match[str]) -> str:
            nonlocal total_trimmed
            body = str(match.group(1) or "")
            if len(body) <= max_content_chars:
                return match.group(0)
            kept = body[: max(200, max_content_chars)].rstrip()
            replacement = (
                match.group(0).replace(
                    body,
                    kept + f"\n... [{note}]",
                    1,
                )
            )
            total_trimmed += max(0, len(match.group(0)) - len(replacement))
            return replacement

        updated, _ = self._replace_regex_block(text, pattern, _replacement, flags=re.DOTALL)
        return updated, total_trimmed

    def _truncate_bullet_section(
        self,
        task: str,
        *,
        heading: str,
        max_items: int,
    ) -> tuple[str, int]:
        text = str(task or "")
        pattern = rf"({re.escape(heading)}\n)((?:- .*\n)+)"
        total_trimmed = 0

        def _replacement(match: re.Match[str]) -> str:
            nonlocal total_trimmed
            bullet_lines = [line for line in str(match.group(2) or "").splitlines() if line.strip()]
            if len(bullet_lines) <= max_items:
                return match.group(0)
            kept = bullet_lines[:max_items]
            omitted = len(bullet_lines) - len(kept)
            replacement = match.group(1) + "\n".join(kept) + f"\n- ... ({omitted} additional items trimmed)\n"
            total_trimmed += max(0, len(match.group(0)) - len(replacement))
            return replacement

        updated, _ = self._replace_regex_block(text, pattern, _replacement, flags=re.DOTALL)
        return updated, total_trimmed

    def _final_prompt_hard_cap(self, task: str, budget_chars: int) -> tuple[str, int]:
        text = str(task or "")
        if len(text) <= budget_chars:
            return text, 0
        note = "\n\n[prompt tail trimmed for budget]\n"
        keep = max(0, budget_chars - len(note))
        trimmed = len(text) - keep
        return text[:keep].rstrip() + note, trimmed

    def _prepare_prompt_for_agent_run(
        self,
        *,
        task: str,
        round_mode: str,
        focus_files: Optional[list[str]],
        log,
    ) -> tuple[str, dict[str, Any]]:
        original = str(task or "")
        budget = self._resolve_prompt_budget()
        budget_chars = int(budget.get("budget_chars") or 48000)
        budget_tokens = budget.get("budget_tokens")
        context_window_tokens = budget.get("context_window_tokens")
        budget_source = str(budget.get("budget_source") or "chars_only")
        trace_id = self._build_prompt_trace_id(round_mode)
        section_sizes = self._collect_prompt_section_sizes(original)
        trimmed_sections: list[dict[str, Any]] = []
        prepared = original

        def _record_trim(section: str, action: str, removed_chars: int) -> None:
            if removed_chars <= 0:
                return
            trimmed_sections.append(
                {
                    "section": section,
                    "action": action,
                    "removed_chars": int(removed_chars),
                }
            )

        if self._prompt_exceeds_budget(prepared, budget_chars=budget_chars, budget_tokens=budget_tokens):
            prepared, removed = self._truncate_retry_guidance(prepared)
            _record_trim("retry_text", "truncate_section", removed)
        if self._prompt_exceeds_budget(prepared, budget_chars=budget_chars, budget_tokens=budget_tokens):
            prepared, removed = self._truncate_fenced_section(
                prepared,
                headings=(
                    "Current diff excerpt",
                    "Best-so-far diff excerpt",
                    "Current rejected diff excerpt",
                ),
                language="diff",
                max_content_chars=1400,
                note="diff trimmed for prompt budget",
            )
            _record_trim("diff_excerpt", "truncate_fence", removed)
        if self._prompt_exceeds_budget(prepared, budget_chars=budget_chars, budget_tokens=budget_tokens):
            prepared, removed = self._truncate_fenced_section(
                prepared,
                headings=("Current source excerpt", "Compile-error source excerpt"),
                language="python",
                max_content_chars=1200,
                note="source trimmed for prompt budget",
            )
            _record_trim("source_excerpt", "truncate_fence", removed)
        if self._prompt_exceeds_budget(prepared, budget_chars=budget_chars, budget_tokens=budget_tokens):
            prepared, removed = self._truncate_bullet_section(
                prepared,
                heading="Known failing target tests:",
                max_items=3,
            )
            _record_trim("failure_test_context", "truncate_bullets", removed)
        if self._prompt_exceeds_budget(prepared, budget_chars=budget_chars, budget_tokens=budget_tokens):
            prepared, removed = self._truncate_bullet_section(
                prepared,
                heading="Failing files:",
                max_items=3,
            )
            _record_trim("failure_test_context", "truncate_bullets", removed)
        if self._prompt_exceeds_budget(prepared, budget_chars=budget_chars, budget_tokens=budget_tokens):
            prepared, removed = self._final_prompt_hard_cap(prepared, budget_chars)
            _record_trim("guidance", "hard_cap_tail", removed)

        final_sizes = self._collect_prompt_section_sizes(prepared)
        telemetry = {
            "trace_id": trace_id,
            "round_mode": str(round_mode or "default"),
            "focus_file_count": len(focus_files or []),
            "budget_chars": budget_chars,
            "budget_tokens": budget_tokens,
            "context_window_tokens": context_window_tokens,
            "budget_source": budget_source,
            "chars_before": len(original),
            "chars_after": len(prepared),
            "estimated_tokens_before": self._estimate_prompt_tokens(original),
            "estimated_tokens_after": self._estimate_prompt_tokens(prepared),
            "section_sizes_before": section_sizes,
            "section_sizes_after": final_sizes,
            "trimmed": bool(trimmed_sections),
            "trimmed_sections": trimmed_sections,
        }
        log(
            "PROMPT_TRACE "
            f"id={trace_id} mode={telemetry['round_mode']} "
            f"focus_count={telemetry['focus_file_count']} "
            f"chars_before={telemetry['chars_before']} chars_after={telemetry['chars_after']} "
            f"tokens_before={telemetry['estimated_tokens_before']} "
            f"tokens_after={telemetry['estimated_tokens_after']} "
            f"budget_chars={budget_chars} budget_tokens={budget_tokens if budget_tokens is not None else '-'} "
            f"context_window_tokens={context_window_tokens if context_window_tokens is not None else '-'} "
            f"budget_source={budget_source} trimmed={telemetry['trimmed']}"
        )
        log(
            "PROMPT_TRACE_SECTIONS "
            f"id={trace_id} "
            + " ".join(
                f"{name}={int(final_sizes.get(name, 0) or 0)}"
                for name in (
                    "task",
                    "retry_text",
                    "diff_excerpt",
                    "source_excerpt",
                    "failure_test_context",
                    "guidance",
                )
            )
        )
        if trimmed_sections:
            log(
                "PROMPT_TRACE_TRIM "
                f"id={trace_id} "
                + "; ".join(
                    f"{item['section']}:{item['action']}:{item['removed_chars']}"
                    for item in trimmed_sections
                )
            )
        return prepared, telemetry

    def _format_test_failure_task(
        self,
        problem_statement: str,
        hints_text: str,
        metrics: dict[str, Any],
        *,
        fail_to_pass_tests: Optional[list[str]] = None,
        focus_files: Optional[list[str]] = None,
        existing_diff_excerpt: str = "",
        source_excerpt: str = "",
        verify_command: str = "",
    ) -> str:
        task = problem_statement
        if hints_text:
            task += f"\n\n## Hints\n\n{hints_text}"
        infra_unreliable = bool(metrics.get("f2p_reliable") is False)
        task += (
            "\n\n## Repair Round\n\n"
            "Your previous patch did not pass the required target tests.\n"
            f"- FAIL_TO_PASS passed: {metrics.get('f2p_passed')}/{metrics.get('f2p_total')}\n"
            "Produce a minimal correction patch and re-verify before submission.\n"
            "If an edit command fails repeatedly, switch to a different editing method immediately.\n"
            "Do not rediscover repository structure in this round.\n"
            "First command in this round must be a direct edit to a focus file.\n"
            "Do not run read/search or inline python probes before first edit in this round.\n"
            "Avoid scratch analysis scripts unless they directly verify changed lines.\n"
        )
        if fail_to_pass_tests:
            task += "Known failing target tests:\n"
            for nodeid in list(fail_to_pass_tests)[:5]:
                task += f"- {nodeid}\n"
        if str(existing_diff_excerpt or "").strip():
            task += "\nCurrent diff excerpt:\n```diff\n"
            task += str(existing_diff_excerpt).strip()
            task += "\n```\n"
        if str(source_excerpt or "").strip():
            task += "\nCurrent source excerpt:\n```python\n"
            task += str(source_excerpt).strip()
            task += "\n```\n"
        if str(existing_diff_excerpt or "").strip():
            task += self._build_minimal_fix_guidance(diff_excerpt=existing_diff_excerpt) + "\n"
            task += (
                "A compile-valid patch already exists. Modify the shown hunk directly instead of re-reading file headers or broadening to sibling helpers.\n"
            )
        if verify_command:
            task += f"\nPreferred verification command:\n`{verify_command}`\n"
        task = self._append_repair_focus_guidance(
            task,
            focus_files=focus_files,
            require_edit_first=True,
            diff_excerpt=existing_diff_excerpt,
        )
        if infra_unreliable:
            task += (
                "Runtime signal is infra-unreliable. Do not run setup/build/install loops in this round.\n"
                "Use direct source-level fix and concise verification evidence only.\n"
            )
        return task

    def _format_graphrag_failure_task(
        self,
        problem_statement: str,
        hints_text: str,
        failed_tests: list[dict[str, Any]],
        *,
        regression_source: str = "graph_impacted",
        focus_files: Optional[list[str]] = None,
        existing_patch_files: Optional[list[str]] = None,
        existing_diff_excerpt: str = "",
        source_excerpt: str = "",
        verify_command: str = "",
    ) -> str:
        task = problem_statement
        if hints_text:
            task += f"\n\n## Hints\n\n{hints_text}"
        source = str(regression_source or "graph_impacted")
        if source == "changed_test_file_fallback":
            task += "\n\n## Changed-Test Regression Failures\n"
            task += (
                "GraphRAG selection did not yield runnable impacted tests, so changed test files "
                "were used as fallback regression checks.\n"
            )
        elif source == "bounded_fallback_smoke":
            task += "\n\n## Fallback Regression Failures\n"
            task += (
                "GraphRAG signal was weak, so deterministic targeted regression checks were used.\n"
            )
        else:
            task += "\n\n## GraphRAG Impacted Test Failures\n"
            task += "GraphRAG identified the following impacted tests as failing.\n"
        task += "Fix regressions with minimal code edits.\n"
        for ft in failed_tests[:10]:
            task += (
                f"- {ft.get('full_name') or ft.get('test_name')}: "
                f"{(ft.get('error') or '')[:200]}\n"
            )
        selected_patch_files = [
            str(path).strip().lstrip("./").replace("\\", "/")
            for path in (existing_patch_files or [])
            if str(path).strip()
        ]
        if selected_patch_files:
            task += "\n## Existing Candidate Patch\n"
            task += (
                "A non-empty patch already exists. Modify that patch directly instead of rediscovering the repository.\n"
            )
            for path in selected_patch_files[:5]:
                task += f"- {path}\n"
        if str(existing_diff_excerpt or "").strip():
            task += "\nCurrent diff excerpt:\n```diff\n"
            task += str(existing_diff_excerpt).strip()
            task += "\n```\n"
        if str(source_excerpt or "").strip():
            task += "\nCurrent source excerpt:\n```python\n"
            task += str(source_excerpt).strip()
            task += "\n```\n"
        if str(existing_diff_excerpt or "").strip():
            task += self._build_minimal_fix_guidance(diff_excerpt=existing_diff_excerpt) + "\n"
            task += (
                "A non-empty candidate patch already exists. Refine that hunk directly before reconsidering the wider file or repository.\n"
            )
        task += (
            "First command in this round must be a direct edit to a focus file.\n"
            "Do not run read/search or inline python probes before first edit.\n"
            "Keep edits localized to impacted areas and re-verify with targeted commands after the edit.\n"
        )
        if verify_command:
            task += f"Preferred verification command: `{verify_command}`\n"
        task = self._append_repair_focus_guidance(
            task,
            focus_files=focus_files,
            require_edit_first=True,
            diff_excerpt=existing_diff_excerpt,
        )
        return task

    def _format_compile_failure_task(
        self,
        problem_statement: str,
        hints_text: str,
        compile_gate: dict[str, Any],
        *,
        focus_files: Optional[list[str]] = None,
        existing_diff_excerpt: str = "",
        source_excerpt: str = "",
        verify_command: str = "",
    ) -> str:
        task = problem_statement
        if hints_text:
            task += f"\n\n## Hints\n\n{hints_text}"

        failed_files = compile_gate.get("compile_failed_files", []) or []
        details = compile_gate.get("details", []) or []
        failed_detail_map = {
            d.get("file", ""): d for d in details if d.get("file") in failed_files
        }

        task += (
            "\n\n## Compile Repair Round\n\n"
            "Your previous patch failed Python syntax compile checks.\n"
            "Fix the compile errors first, with minimal targeted edits, then submit again.\n"
            "This is a syntax-repair round only. Do not rediscover the repository or rewrite whole functions.\n"
        )
        if failed_files:
            task += "\nFailing files:\n"
            for file_path in failed_files[:10]:
                detail = failed_detail_map.get(file_path, {})
                current_error = detail.get("current_error", "unknown")
                task += f"- {file_path}: {current_error}\n"
        if str(existing_diff_excerpt or "").strip():
            task += "\nCurrent rejected diff excerpt:\n```diff\n"
            task += str(existing_diff_excerpt).strip()
            task += "\n```\n"
        if str(source_excerpt or "").strip():
            task += "\nCompile-error source excerpt:\n```python\n"
            task += str(source_excerpt).strip()
            task += "\n```\n"
        if str(existing_diff_excerpt or "").strip():
            task += self._build_minimal_fix_guidance(diff_excerpt=existing_diff_excerpt) + "\n"
            task += (
                "The rejected patch already identifies the hunk to fix. Repair that hunk directly before exploring other helpers.\n"
            )

        task += (
            "\nRequirements:\n"
            "1. Do not add placeholders.\n"
            "2. Keep public signatures stable.\n"
            "3. Make only minimal edits needed to restore compilable Python syntax.\n"
            "4. Do not do broad replacements, whole-function rewrites, or multiline shell substitutions unless unavoidable.\n"
            "5. First command in this round must be a direct edit to a failing focus file; do not run read/search before first edit.\n"
            "6. Before submitting, run `python -m py_compile <failing_file.py>` for the changed failing files.\n"
        )
        if verify_command:
            task += f"\nPreferred verification command:\n`{verify_command}`\n"
        task = self._append_repair_focus_guidance(
            task,
            focus_files=focus_files or failed_files,
            require_edit_first=True,
            diff_excerpt=existing_diff_excerpt,
        )
        return task

    def _format_retry_task(
        self,
        problem_statement: str,
        hints_text: str,
        tdd_mode: bool,
        attempt_idx: int,
        prev_attempt: Optional[dict[str, Any]],
        prev_candidate: Optional[dict[str, Any]] = None,
        best_candidate: Optional[dict[str, Any]] = None,
        force_strategy_shift: bool = False,
        affected_tests: Optional[list[str]] = None,
        focus_files: Optional[list[str]] = None,
        existing_diff_excerpt: str = "",
        source_excerpt: str = "",
        verify_command: str = "",
        memory_guidance: str = "",
        graphrag_summary: Optional[dict[str, Any]] = None,
    ) -> str:
        task = self._format_task(
            problem_statement,
            hints_text,
            affected_tests or [],
            tdd_mode,
            focus_files=focus_files,
            graphrag_summary=graphrag_summary,
        )
        if memory_guidance:
            task += "\n\n## Prior Attempt Memory\n"
            task += memory_guidance + "\n"
        if attempt_idx <= 1:
            return task

        task += "\n\n## Retry Guidance\n"
        has_carried_patch = bool(str(existing_diff_excerpt or "").strip())
        if has_carried_patch:
            task += (
                f"Retry attempt {attempt_idx}/{self.max_attempts}. Stay in patch-refinement mode.\n"
                "Modify the shown diff hunk or adjacent executable lines before widening scope.\n"
                "Do not restart repository discovery or re-open the file header to understand it.\n"
            )
        else:
            task += f"Retry attempt {attempt_idx}/{self.max_attempts}. Use a different edit strategy than before.\n"
        task += "Keep commands short and avoid repeating previously failing command patterns.\n"
        extra_retry_guidance = str(os.getenv("QWEN_MINI_EXTRA_RETRY_GUIDANCE", "") or "").strip()
        if extra_retry_guidance:
            task += extra_retry_guidance + "\n"
        if focus_files and has_carried_patch:
            task += (
                "The current source excerpt is already centered on the likely helper/hunk. "
                "Refine that helper before moving to sibling functions.\n"
            )
        if focus_files:
            task += (
                "First command in this retry must be a direct edit to a carried-over focus file.\n"
                "Do not run read/search or inline python probes before first edit in this retry.\n"
            )

        if not prev_attempt:
            return task

        loop_abort_reason = str(prev_attempt.get("loop_abort_reason", ""))
        patch_gate_reason = str(prev_attempt.get("patch_gate_reason", ""))
        if patch_gate_reason:
            task += f"Previous patch gate result: {patch_gate_reason}.\n"
        if loop_abort_reason:
            task += f"Previous loop abort: {loop_abort_reason}. Change approach immediately.\n"
        prev_format_errors = int(prev_attempt.get("format_errors") or 0)
        if prev_format_errors > 0:
            task += (
                f"Previous attempt had {prev_format_errors} format errors. "
                "Always output exactly one bash block with one command.\n"
            )
        prev_timeouts = int(prev_attempt.get("timeouts") or 0)
        if prev_timeouts > 0:
            task += (
                f"Previous attempt had {prev_timeouts} timeout(s). "
                "Prefer faster, scoped commands.\n"
            )
        progress_gate_reason = str(prev_attempt.get("progress_gate_reason", "") or "")
        progress_gate_stagnation_count = int(prev_attempt.get("progress_gate_stagnation_count", 0) or 0)
        if progress_gate_reason:
            task += (
                "Previous progress gate: "
                f"{progress_gate_reason} (stagnation={progress_gate_stagnation_count}).\n"
            )
            if progress_gate_reason == "stagnant_failure_signature":
                task += (
                    "That means the branch did not make monotonic issue-test progress.\n"
                )
            if progress_gate_stagnation_count >= self.stagnant_failure_signature_limit:
                task += (
                    "Same failure signature repeated twice. Relocalize now: choose a different root-cause hypothesis "
                    "or a different file/symbol target before the next edit.\n"
                )
        prev_regression_source = str(prev_attempt.get("regression_source", "none") or "none")
        prev_regression_run = int(prev_attempt.get("regression_tests_run") or 0)
        prev_regression_failed = int(prev_attempt.get("regression_tests_failed") or 0)
        prev_regression_reliable = bool(prev_attempt.get("regression_signal_reliable"))
        if prev_regression_source != "none" and prev_regression_run > 0:
            task += (
                "Previous bounded regression signal "
                f"({prev_regression_source}) ran {prev_regression_run} tests with "
                f"{prev_regression_failed} failures.\n"
            )
            if prev_regression_reliable:
                task += (
                    "Use that existing regression signal after your next edit instead of rediscovering "
                    "regression scope.\n"
                )
        if force_strategy_shift:
            if has_carried_patch:
                task += (
                    "The previous attempt is too similar to the best prior candidate. "
                    "Change the fix mechanism inside the same hunk before widening scope, unless strong evidence says the hunk is wrong. "
                    "Do not restart with broad repository discovery.\n"
                )
            else:
                task += (
                    "The previous attempt is too similar to the best prior candidate. "
                    "Change the fix mechanism now, but stay anchored to the best-so-far file unless there is strong evidence the file is wrong. "
                    "Do not restart with broad repository discovery.\n"
                )

        if prev_candidate:
            changed = prev_candidate.get("changed_files") or []
            if changed:
                task += f"Previous changed files: {', '.join(changed[:6])}\n"
            changed_lines = int(prev_candidate.get("changed_lines_total") or 0)
            if changed_lines > 0:
                task += f"Previous changed lines total: {changed_lines}. Keep this attempt smaller and more targeted.\n"
            wrong_hypothesis = self._summarize_previous_wrong_hypothesis(prev_candidate)
            if wrong_hypothesis:
                task += (
                    "Previous failed hypothesis: "
                    + wrong_hypothesis
                    + ". Do not repeat that same hypothesis or broad rewrite.\n"
                )
            previous_failed_regression_tests = []
            prev_meta = dict(prev_candidate.get("graphrag_metadata") or {})
            for item in list(prev_meta.get("impacted_failed_tests") or [])[:3]:
                if isinstance(item, dict):
                    name = str(item.get("full_name") or item.get("test_name") or "").strip()
                else:
                    name = str(item or "").strip()
                if name:
                    previous_failed_regression_tests.append(name)
            if previous_failed_regression_tests:
                task += (
                    "Previously failing regression tests: "
                    + ", ".join(previous_failed_regression_tests)
                    + ".\n"
                )
        if best_candidate:
            best_changed = best_candidate.get("changed_files") or []
            if best_changed:
                task += f"Best-so-far changed files: {', '.join(best_changed[:6])}\n"
                if has_carried_patch:
                    task += (
                        "Start from those files and the shown hunk. Modify the current patch before considering a new hypothesis.\n"
                    )
                else:
                    task += (
                        "Start from those files. Do not rediscover repository structure before editing or running "
                        "one targeted verification command.\n"
                    )
        if str(existing_diff_excerpt or "").strip():
            task += "\nBest-so-far diff excerpt:\n```diff\n"
            task += str(existing_diff_excerpt).strip()
            task += "\n```\n"
        if str(source_excerpt or "").strip():
            task += "\nCurrent source excerpt:\n```python\n"
            task += str(source_excerpt).strip()
            task += "\n```\n"
        if str(existing_diff_excerpt or "").strip():
            task += self._build_minimal_fix_guidance(
                diff_excerpt=existing_diff_excerpt,
                patch_gate_reason=patch_gate_reason,
            ) + "\n"
            task += (
                "Refine the shown diff hunk directly. Prefer replacing the current changed block over introducing a new helper-level theory.\n"
            )
        if verify_command:
            task += f"Preferred verification command: `{verify_command}`\n"

        if "syntax_compile_failed" in patch_gate_reason:
            task += (
                "If syntax failed, first fix the reported failing file(s), then run py_compile before submit.\n"
            )
        if "empty_diff" in patch_gate_reason:
            task += (
                "Previous attempt produced no accepted patch. Start by editing one likely target file and verify "
                "non-empty `git diff` before broad test runs.\n"
            )
        if loop_abort_reason.startswith("no_diff_streak"):
            task += (
                "No-diff streak means commands were not changing files. Run one direct edit command now, then "
                "confirm with `git diff --name-only`.\n"
            )
        if loop_abort_reason.startswith("no_edit_progress"):
            task += (
                "Previous attempt made no code edits before abort. "
                "This attempt: apply a direct code edit immediately to the most likely target file.\n"
                "Do not spend steps on broad searches or environment setup before the first edit.\n"
            )
        if loop_abort_reason.startswith("first_edit_missing_by_step"):
            task += (
                "You failed the first-edit deadline. Apply a minimal code edit in your next 1-2 commands.\n"
            )
        if loop_abort_reason.startswith("read_only_streak"):
            task += (
                "You exceeded read-only exploration steps. Stop browsing and edit the likely target file now.\n"
            )
        if loop_abort_reason.startswith("env_path_mismatch"):
            task += (
                "Use repository-relative paths only. Do not cd outside repo or use /opt/miniconda3 or /repo.\n"
            )
        if loop_abort_reason.startswith("search_only_streak"):
            task += (
                "Search-only streak means over-exploration. Stop searching and apply a concrete minimal edit now.\n"
            )
            if focus_files:
                task += (
                    "Target one of these files immediately: "
                    + ", ".join(str(path) for path in list(focus_files)[:3])
                    + ".\n"
                )
        if loop_abort_reason.startswith("post_edit_no_diff_streak"):
            task += (
                "A non-empty patch already existed but you kept browsing without improving it. "
                "Keep the next patch minimal, modify the current hunk directly, and verify it quickly instead of broadening the rewrite.\n"
            )
        if loop_abort_reason.startswith("repair_blocked_streak"):
            task += (
                "Previous repair round ignored direct-edit instructions repeatedly. "
                "Do not inspect the repository again; modify the current patch or the primary focus file immediately.\n"
            )
        if loop_abort_reason.startswith("env_bootstrap_fail_streak"):
            task += (
                "Previous attempt spent steps on failing environment setup/tests. "
                "Do not run pytest/setup/import bootstrap commands this attempt.\n"
                "Open the likely source file directly and apply a minimal edit based on issue text + nearby tests.\n"
            )
        if loop_abort_reason.startswith("python_inline_fail_streak"):
            task += (
                "Previous attempt failed on `python -c` editing. "
                "Use safer editing commands (e.g., `python - <<'PY' ... PY`) and keep edits minimal.\n"
            )
        if "too_many_changed_lines" in patch_gate_reason:
            task += "Previous patch was too large. Rework as a localized fix under the line-change limit.\n"
        if "potential_signature_change" in patch_gate_reason:
            task += "Keep public function/class signatures unchanged unless the issue explicitly requires it.\n"
        if focus_files:
            task = self._append_repair_focus_guidance(
                task,
                focus_files=focus_files,
                require_edit_first=True,
                diff_excerpt=existing_diff_excerpt,
            )

        return task

    def _get_changed_files_any(self, repo_path: Path) -> list[str]:
        return self._list_repo_changes(repo_path)

    def _get_changed_files(self, repo_path: Path) -> list[str]:
        return [path for path in self._list_repo_changes(repo_path) if path.endswith(".py")]

    def _list_repo_changes(self, repo_path: Path) -> list[str]:
        """List changed files including untracked files (repo-relative paths)."""
        changed: list[str] = []
        seen: set[str] = set()

        try:
            diff_result = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=False,
            )
            for line in diff_result.stdout.splitlines():
                path = line.strip()
                if path and path not in seen:
                    seen.add(path)
                    changed.append(path)
        except Exception:
            pass

        try:
            untracked_result = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=False,
            )
            for line in untracked_result.stdout.splitlines():
                path = line.strip()
                if path and path not in seen:
                    seen.add(path)
                    changed.append(path)
        except Exception:
            pass

        return changed

    # ------------------------------------------------------------------ #
    # Repository setup                                                    #
    # ------------------------------------------------------------------ #

    def _setup_repository(self, repo: str, base_commit: str, log=print) -> Path:
        """Clone repository and checkout base commit."""
        tmpdir = tempfile.mkdtemp(prefix="swe_qwen_")
        repo_path = Path(tmpdir) / "repo"
        repo_url = f"https://github.com/{repo}"
        log(f"Cloning {repo_url}...")
        result = subprocess.run(
            ["git", "clone", "--depth", "1", "--single-branch", repo_url, str(repo_path)],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            log("Shallow clone failed, retrying full clone...")
            subprocess.run(
                ["git", "clone", repo_url, str(repo_path)],
                check=True,
                capture_output=True,
                text=True,
            )

        # Fetch full history so we can checkout base_commit
        subprocess.run(
            ["git", "fetch", "--unshallow"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        )

        log(f"Checking out {base_commit[:8]}...")
        subprocess.run(
            ["git", "checkout", base_commit],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True,
        )

        return repo_path

    # ------------------------------------------------------------------ #
    # Agent creation                                                      #
    # ------------------------------------------------------------------ #

    def _create_agent(self, repo_path: Path, tdd_mode: bool = False) -> DefaultAgent:
        """Instantiate mini-swe-agent with local OpenAI-compatible config."""

        # Model — local llama.cpp/OpenAI-compatible endpoint by default.
        model = get_model(
            input_model_name=self.local_model,
            config={
                "model_kwargs": self.local_backend.build_litellm_kwargs(
                    temperature=self.temperature,
                    max_tokens=self.model_max_tokens,
                    timeout=self.agent_run_timeout_sec,
                    num_ctx=32768,
                ),
                "model_class": "litellm",
                "cost_tracking": "ignore_errors",
            },
        )

        # Environment — MUST use 'cwd' (not 'working_dir')
        env = get_environment(
            config={
                "environment_class": "local",
                "cwd": str(repo_path),
                "env": DEFAULT_ENV_VARS,
            },
            default_type="local",
        )

        # Build instance template — default + optional TDD appendix
        instance_tpl = INSTANCE_TEMPLATE
        if tdd_mode and self.enforce_tdd_test_first:
            instance_tpl += """
## Additional Requirement: Test-Driven Development

Before fixing the code, you MUST:
1. Write a failing test that reproduces the issue
2. Run it to confirm it fails
3. Then fix the code
4. Re-run the test to confirm it passes

Use existing test frameworks (pytest, unittest) found in the repository.
"""

        agent = DefaultAgent(
            model=model,
            env=env,
            system_template=SYSTEM_TEMPLATE,
            instance_template=instance_tpl,
            action_observation_template=ACTION_OBSERVATION_TEMPLATE,
            format_error_template=FORMAT_ERROR_TEMPLATE,
            timeout_template=TIMEOUT_TEMPLATE,
            step_limit=self.step_limit,
            cost_limit=self.cost_limit,
        )

        return agent

    # ------------------------------------------------------------------ #
    # Task formatting                                                     #
    # ------------------------------------------------------------------ #

    def _format_task(
        self,
        problem_statement: str,
        hints_text: str,
        affected_tests: list = None,
        tdd_mode: bool = False,
        focus_files: Optional[list[str]] = None,
        graphrag_summary: Optional[dict[str, Any]] = None,
    ) -> str:
        """Format SWE-bench instance as agent task prompt."""
        task = problem_statement

        if hints_text:
            task += f"\n\n## Hints\n\n{hints_text}"

        graphrag_context = self._format_graphrag_start_context(graphrag_summary)
        if graphrag_context:
            task += graphrag_context

        if affected_tests:
            task += "\n\n## Affected Tests (from GraphRAG analysis)\n\nThe following tests are likely affected by this issue:\n"
            for test in affected_tests[:10]:
                task += f"- {test}\n"
            task += "\nConsider these tests when implementing your fix.\n"

        selected_focus_files = [
            str(path).strip().lstrip("./").replace("\\", "/")
            for path in (focus_files or [])
            if str(path).strip()
        ]
        selected_focus_files = self._prioritize_focus_files(selected_focus_files, max_files=5)
        if selected_focus_files:
            task += "\n\n## Likely Focus Files\n\n"
            for path in selected_focus_files[:5]:
                task += f"- {path}\n"
            task += (
                "\nUse these files as the initial working set. Inspect briefly, then edit one of them directly.\n"
                "Do not create standalone repro/debug scripts before the first edit.\n"
                "Do not use inline python runtime probes before the first edit.\n"
                "Treat the failing repo test and issue statement as the repro contract.\n"
                "Prefer the smallest localized change in the likely source file.\n"
                "Do not rewrite a whole function or class unless the failure clearly requires it.\n"
                "If you identify the likely bug mechanism, the next command should be an edit or a targeted pytest command.\n"
                "Prefer a single-line `python3 -c` pathlib edit or `sed -i` over multiline heredoc edits.\n"
            )

        if tdd_mode and selected_focus_files:
            task += (
                "\n\n## TDD Workflow\n\n"
                "The failing test is already your repro. Avoid environment/bootstrap detours.\n"
                "Within the first few commands, either edit one likely source file or run a targeted failing test.\n"
            )

        extra_task_guidance = str(os.getenv("QWEN_MINI_EXTRA_TASK_GUIDANCE", "") or "").strip()
        if extra_task_guidance:
            task += "\n\n## Additional Task Guidance\n\n"
            task += extra_task_guidance + "\n"

        return task

    def _format_graphrag_start_context(
        self,
        graphrag_summary: Optional[dict[str, Any]],
    ) -> str:
        if graphrag_summary is None:
            return ""

        summary = dict(graphrag_summary or {})
        seed_files = [
            str(path).strip().lstrip("./").replace("\\", "/")
            for path in (summary.get("seed_files") or [])
            if str(path).strip()
        ]
        focus_files = [
            str(path).strip().lstrip("./").replace("\\", "/")
            for path in (summary.get("focus_files") or [])
            if str(path).strip()
        ]
        affected_tests = [
            str(test).strip()
            for test in (summary.get("affected_tests") or [])
            if str(test).strip()
        ]
        total_tests = int(summary.get("total_tests", 0) or 0)
        success = bool(summary.get("success"))
        reason = str(summary.get("reason", "") or "").strip()

        lines = [
            "",
            "",
            "## GraphRAG Start Context",
            "Graph-derived repository context was prepared before this attempt. Use it before the first edit.",
        ]
        if seed_files:
            lines.append("Seed files:")
            lines.extend(f"- {path}" for path in seed_files[:6])
        if focus_files:
            lines.append("Priority focus files:")
            lines.extend(f"- {path}" for path in focus_files[:6])
        if affected_tests:
            lines.append("Impacted tests:")
            lines.extend(f"- {test}" for test in affected_tests[:6])
            if total_tests > len(affected_tests):
                lines.append(f"- ... ({total_tests - len(affected_tests)} more graph matches)")
        else:
            lines.append("Impacted tests: none ranked from graph localization.")

        if reason:
            prefix = "Localization note"
            if not success:
                prefix = "Localization warning"
            lines.append(f"{prefix}: {reason}")
        elif not success and not seed_files and not focus_files:
            lines.append("Localization warning: no graph seed files were derived from the issue/test context.")

        lines.append(
            "Start from the highest-confidence source file here. Only widen scope if this graph-informed hypothesis is falsified."
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # Patch extraction                                                    #
    # ------------------------------------------------------------------ #

    def _compile_python_source(self, source: str, filename: str) -> Optional[str]:
        """Compile Python source and return None if valid, else an error string."""
        try:
            compile(source, filename, "exec")
            return None
        except SyntaxError as e:
            return f"SyntaxError:{e.msg}@{e.lineno}:{e.offset}"
        except Exception as e:
            return f"{type(e).__name__}:{e}"

    def _check_compile_gate(self, repo_path: Path) -> dict[str, Any]:
        """Compile changed Python files and classify syntax failures."""
        changed_py_files = self._get_changed_files(repo_path)
        failed_files: list[str] = []
        preexisting_failures: list[str] = []
        details: list[dict[str, str]] = []
        checked = 0

        for rel_path in changed_py_files:
            abs_path = repo_path / rel_path
            if not abs_path.exists() or not abs_path.is_file():
                continue

            checked += 1
            try:
                current_src = abs_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                current_src = abs_path.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                failed_files.append(rel_path)
                details.append(
                    {
                        "file": rel_path,
                        "current_error": f"ReadError:{e}",
                        "baseline_error": "unknown",
                    }
                )
                continue

            current_err = self._compile_python_source(current_src, rel_path)
            if current_err is None:
                continue

            baseline = subprocess.run(
                ["git", "show", f"HEAD:{rel_path}"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=False,
            )
            if baseline.returncode != 0:
                failed_files.append(rel_path)
                details.append(
                    {
                        "file": rel_path,
                        "current_error": current_err,
                        "baseline_error": "missing",
                    }
                )
                continue

            baseline_err = self._compile_python_source(baseline.stdout, f"HEAD:{rel_path}")
            if baseline_err is None:
                failed_files.append(rel_path)
                details.append(
                    {
                        "file": rel_path,
                        "current_error": current_err,
                        "baseline_error": "ok",
                    }
                )
            else:
                preexisting_failures.append(rel_path)
                details.append(
                    {
                        "file": rel_path,
                        "current_error": current_err,
                        "baseline_error": baseline_err,
                    }
                )

        return {
            "enabled": True,
            "python_files_changed": len(changed_py_files),
            "compile_checked": checked,
            "compile_failed": len(failed_files),
            "compile_failed_files": failed_files,
            "compile_skipped_preexisting": len(preexisting_failures),
            "compile_preexisting_files": preexisting_failures,
            "details": details,
        }

    def _validate_patch_quality(self, repo_path: Path) -> dict:
        """Validate patch quality and return decision metadata."""
        result = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        diff = result.stdout

        fail_reasons = []
        warn_reasons = []

        if not diff.strip():
            fail_reasons.append("empty_diff")

        files_changed = len(re.findall(r"^diff --git ", diff, flags=re.MULTILINE))
        if files_changed > 3:
            fail_reasons.append(f"too_many_files:{files_changed}")

        removed_lines = re.findall(r"^-(?!--\s)(.*)$", diff, flags=re.MULTILINE)
        removed_lines_count = len(removed_lines)
        added_lines = re.findall(r"^\+(?!\+\+\s)(.*)$", diff, flags=re.MULTILINE)
        added_lines_count = len(added_lines)
        changed_lines_total = removed_lines_count + added_lines_count
        if self.max_changed_lines > 0 and changed_lines_total > self.max_changed_lines:
            fail_reasons.append(
                f"too_many_changed_lines:{changed_lines_total}_limit_{self.max_changed_lines}"
            )
        if removed_lines_count > 50 and added_lines_count > 0 and removed_lines_count > 5 * added_lines_count:
            fail_reasons.append(f"catastrophic_deletion:{removed_lines_count}_removed_vs_{added_lines_count}_added")
        if (
            changed_lines_total > 0
            and not self._has_semantic_code_change(
                added_lines=added_lines,
                removed_lines=removed_lines,
            )
        ):
            fail_reasons.append("comment_only_diff")

        normalized_added = [line.strip() for line in added_lines if line.strip()]
        repeated_lines = Counter(normalized_added)
        duplicate_line_max_count = max(repeated_lines.values(), default=0)
        if duplicate_line_max_count >= 4:
            fail_reasons.append(f"repetitive_code:max_repeat={duplicate_line_max_count}")

        placeholder_markers = ("TODO", "FIXME", "Placeholder", "NotImplementedError")
        if any(marker in line for line in added_lines for marker in placeholder_markers):
            fail_reasons.append("placeholder_code")

        removed_defs = re.findall(
            r"^-def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*:",
            diff,
            flags=re.MULTILINE,
        )
        added_defs = re.findall(
            r"^\+def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*:",
            diff,
            flags=re.MULTILINE,
        )

        signature_change_detected = False
        removed_map: dict[str, list[str]] = {}
        for name, params in removed_defs:
            removed_map.setdefault(name, []).append("".join(params.split()))
        for name, params in added_defs:
            normalized_params = "".join(params.split())
            previous = removed_map.get(name, [])
            if previous and normalized_params not in previous:
                signature_change_detected = True
                break
        if not signature_change_detected and (removed_defs and not added_defs):
            signature_change_detected = True
        if not signature_change_detected and (added_defs and not removed_defs):
            signature_change_detected = True
        if signature_change_detected:
            warn_reasons.append("potential_signature_change")

        removed_function_without_replacement: list[str] = []
        for section_match in re.finditer(
            r"^diff --git a/(.*?) b/.*?\n(.*?)(?=^diff --git |\Z)",
            diff,
            flags=re.MULTILINE | re.DOTALL,
        ):
            file_path = str(section_match.group(1) or "").strip()
            if not file_path.endswith(".py") or self._is_test_like_file(file_path):
                continue
            section_text = str(section_match.group(2) or "")
            removed_names = re.findall(
                r"^-\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
                section_text,
                flags=re.MULTILINE,
            )
            if not removed_names:
                continue
            added_names = {
                str(name)
                for name in re.findall(
                    r"^\+\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
                    section_text,
                    flags=re.MULTILINE,
                )
            }
            for name in removed_names:
                if name not in added_names:
                    removed_function_without_replacement.append(f"{file_path}:{name}")
        if removed_function_without_replacement:
            preview = "|".join(removed_function_without_replacement[:3])
            fail_reasons.append(f"removed_function_without_replacement:{preview}")

        compile_gate = {
            "enabled": False,
            "python_files_changed": 0,
            "compile_checked": 0,
            "compile_failed": 0,
            "compile_failed_files": [],
            "compile_skipped_preexisting": 0,
            "compile_preexisting_files": [],
            "details": [],
        }
        if self.patch_compile_gate:
            compile_gate = self._check_compile_gate(repo_path)
            failed_files = compile_gate.get("compile_failed_files", [])
            if failed_files:
                fail_reasons.append(f"syntax_compile_failed:{'|'.join(failed_files)}")
            if compile_gate.get("compile_skipped_preexisting", 0) > 0:
                warn_reasons.append(
                    f"compile_preexisting_failures:{compile_gate['compile_skipped_preexisting']}"
                )

        metrics = {
            "files_changed": files_changed,
            "added_lines": len(added_lines),
            "removed_lines": removed_lines_count,
            "changed_lines_total": changed_lines_total,
            "changed_lines_limit": self.max_changed_lines,
            "duplicate_line_max_count": duplicate_line_max_count,
            "signature_change_detected": signature_change_detected,
            "removed_function_without_replacement": list(removed_function_without_replacement),
            "python_files_changed": compile_gate.get("python_files_changed", 0),
            "compile_checked": compile_gate.get("compile_checked", 0),
            "compile_failed": compile_gate.get("compile_failed", 0),
            "compile_skipped_preexisting": compile_gate.get("compile_skipped_preexisting", 0),
        }

        if fail_reasons:
            return {
                "valid": False,
                "severity": "fail",
                "reason": ",".join(fail_reasons),
                "fail_reasons": fail_reasons,
                "warn_reasons": warn_reasons,
                "metrics": metrics,
                "compile_gate": compile_gate,
                "diff": diff,
            }

        if warn_reasons:
            return {
                "valid": True,
                "severity": "warn",
                "reason": ",".join(warn_reasons),
                "fail_reasons": fail_reasons,
                "warn_reasons": warn_reasons,
                "metrics": metrics,
                "compile_gate": compile_gate,
                "diff": diff,
            }

        return {
            "valid": True,
            "severity": "info",
            "reason": "ok",
            "fail_reasons": fail_reasons,
            "warn_reasons": warn_reasons,
            "metrics": metrics,
            "compile_gate": compile_gate,
            "diff": diff,
        }

    def _extract_patch(self, repo_path: Path, log=print) -> str:
        """Extract git diff with quality-gate validation."""
        validation = self._validate_patch_quality(repo_path)
        self._last_patch_gate_decision = validation
        log(
            "PATCH_GATE_RESULT "
            f"valid={validation['valid']} "
            f"severity={validation['severity']} "
            f"reason={validation['reason']} "
            f"metrics={validation['metrics']}"
        )
        diff_preview = self._preview_diff_text(str(validation.get("diff", "") or ""))
        if diff_preview:
            log("PATCH_GATE_DIFF\n" + diff_preview)
        gate_guidance = self._build_minimal_fix_guidance(
            diff_excerpt=str(validation.get("diff", "") or ""),
            patch_gate_reason=str(validation.get("reason", "") or ""),
        )
        if str(validation.get("reason", "") or "") != "ok":
            log("PATCH_GATE_GUIDANCE\n" + gate_guidance)
        compile_gate = validation.get("compile_gate", {})
        if compile_gate.get("enabled"):
            log(
                "PATCH_GATE_COMPILE "
                f"checked={compile_gate.get('compile_checked', 0)} "
                f"failed={compile_gate.get('compile_failed', 0)} "
                f"preexisting={compile_gate.get('compile_skipped_preexisting', 0)} "
                f"failed_files={compile_gate.get('compile_failed_files', [])}"
            )

        if not validation["valid"]:
            log("PATCH_GATE_REJECT returning empty patch")
            return ""

        if validation["severity"] == "warn":
            log("PATCH_GATE_WARN accepted patch with warnings")

        return validation["diff"]

    # ------------------------------------------------------------------ #
    # Logging                                                             #
    # ------------------------------------------------------------------ #

    def _timeout_checkpoint_path(self, instance_id: str, worker_pid: int) -> Path:
        checkpoint_dir = Path(__file__).parent.parent / "logs" / "timeout_checkpoints"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        safe_instance = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(instance_id))
        return checkpoint_dir / f"{safe_instance}.{int(worker_pid)}.json"

    def _write_timeout_checkpoint(
        self,
        *,
        instance_id: str,
        worker_pid: int,
        candidate: dict[str, Any],
    ) -> None:
        if not self.timeout_recover_best_patch:
            return
        prediction = str(candidate.get("prediction", "") or "")
        if not prediction:
            return
        if not bool(candidate.get("patch_gate_valid", False)):
            return

        payload = {
            "instance_id": str(instance_id),
            "model": "qwen-mini",
            "prediction": prediction,
            "status": candidate.get("status", "unknown"),
            "message": candidate.get("message", ""),
            "loop_abort_reason": candidate.get("loop_abort_reason", ""),
            "patch_gate_valid": bool(candidate.get("patch_gate_valid", False)),
            "patch_gate_reason": str(candidate.get("patch_gate_reason", "") or ""),
            "patch_gate_severity": str(candidate.get("patch_gate_severity", "") or ""),
            "changed_lines_total": int(candidate.get("changed_lines_total") or 0),
            "f2p_pass_rate": candidate.get("f2p_pass_rate"),
            "f2p_reliable": candidate.get("f2p_reliable"),
            "p2p_smoke_failures": candidate.get("p2p_smoke_failures"),
            "p2p_reliable": candidate.get("p2p_reliable"),
            "test_signal_reliable": candidate.get("test_signal_reliable"),
            "graph_useful_signal": candidate.get("graph_useful_signal"),
            "impacted_selected_count": candidate.get("impacted_selected_count"),
            "impacted_runnable_count": candidate.get("impacted_runnable_count"),
            "impacted_runnable_ratio": candidate.get("impacted_runnable_ratio"),
            "impacted_precision_score": candidate.get("impacted_precision_score"),
            "impacted_precision_floor_passed": candidate.get("impacted_precision_floor_passed"),
            "graph_fallback_reason": str(candidate.get("graph_fallback_reason", "") or ""),
            "repo_test_changed": candidate.get("repo_test_changed"),
            "verify_cmd_present": candidate.get("verify_cmd_present"),
            "verify_pass_after_edit": candidate.get("verify_pass_after_edit"),
            "smoke_cmd_present": candidate.get("smoke_cmd_present"),
            "smoke_pass_after_edit": candidate.get("smoke_pass_after_edit"),
            "attempts_used": int(candidate.get("attempt") or 0),
            "timeout_recovered": True,
            "timeout_recovery_source": "worker_checkpoint",
            "checkpoint_written_at": datetime.now().isoformat(),
        }
        checkpoint = self._timeout_checkpoint_path(instance_id=instance_id, worker_pid=worker_pid)
        tmp = checkpoint.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(checkpoint)

    def recover_timeout_prediction(self, instance_id: str, worker_pid: int) -> Optional[dict[str, Any]]:
        if not self.timeout_recover_best_patch:
            return None
        if not worker_pid:
            return None
        checkpoint = self._timeout_checkpoint_path(instance_id=instance_id, worker_pid=worker_pid)
        if not checkpoint.exists():
            return None
        try:
            data = json.loads(checkpoint.read_text(encoding="utf-8"))
        except Exception:
            return None
        prediction = str(data.get("prediction", "") or "")
        if not prediction:
            return None
        if data.get("instance_id") != str(instance_id):
            return None
        return data

    def _attempt_memory_path(self, instance_id: str) -> Path:
        memory_dir = Path(__file__).parent.parent / "logs" / "attempt_memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        safe_instance = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(instance_id))
        return memory_dir / f"{safe_instance}.jsonl"

    def _load_recent_attempt_memory(
        self,
        instance_id: str,
        *,
        max_entries: int = 4,
    ) -> list[dict[str, Any]]:
        path = self._attempt_memory_path(instance_id)
        if not path.exists():
            return []
        entries: list[dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    text = str(line or "").strip()
                    if not text:
                        continue
                    try:
                        payload = json.loads(text)
                    except Exception:
                        continue
                    if isinstance(payload, dict):
                        entries.append(payload)
        except Exception:
            return []
        return entries[-max(1, int(max_entries or 1)) :]

    def _derive_attempt_rejection_reason(self, candidate: dict[str, Any]) -> str:
        if bool(candidate.get("clean_resolution")):
            return "clean_resolution"
        patch_gate_reason = str(candidate.get("patch_gate_reason", "") or "").strip()
        if patch_gate_reason and not bool(candidate.get("patch_gate_valid", False)):
            return patch_gate_reason
        progress_gate_reason = str(candidate.get("progress_gate_reason", "") or "").strip()
        if progress_gate_reason and not bool(candidate.get("progress_gate_passed", True)):
            return progress_gate_reason
        loop_abort_reason = str(candidate.get("loop_abort_reason", "") or "").strip()
        if loop_abort_reason:
            return loop_abort_reason
        if candidate.get("tdd_gate_passed") is False:
            return "issue_tests_not_green"
        if candidate.get("regression_gate_passed") is False:
            return "regression_gate_failed"
        return "candidate_unresolved"

    def _append_attempt_memory(self, instance_id: str, candidate: dict[str, Any]) -> None:
        entry = {
            "recorded_at": datetime.now().isoformat(),
            "attempt": int(candidate.get("attempt") or 0),
            "changed_files": list(candidate.get("changed_files") or [])[:4],
            "hypothesis_summary": self._summarize_previous_wrong_hypothesis(candidate),
            "rejection_reason": self._derive_attempt_rejection_reason(candidate),
            "failure_signature": str(candidate.get("failure_signature", "") or ""),
            "progress_gate_reason": str(candidate.get("progress_gate_reason", "") or ""),
            "progress_gate_stagnation_count": int(
                candidate.get("progress_gate_stagnation_count", 0) or 0
            ),
            "f2p_passed": candidate.get("f2p_passed"),
            "f2p_failed": candidate.get("f2p_failed"),
            "verify_pass_after_edit": bool(candidate.get("verify_pass_after_edit")),
            "smoke_pass_after_edit": bool(candidate.get("smoke_pass_after_edit")),
        }
        path = self._attempt_memory_path(instance_id)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=True) + "\n")

    def _format_attempt_memory_guidance(
        self,
        entries: list[dict[str, Any]],
        *,
        max_entries: int = 3,
    ) -> str:
        lines: list[str] = []
        for entry in list(entries or [])[-max(1, int(max_entries or 1)) :]:
            reason = str(entry.get("rejection_reason", "") or "").strip()
            if reason == "clean_resolution":
                continue
            summary = str(entry.get("hypothesis_summary", "") or "").strip()
            if not summary:
                changed = [str(path).strip() for path in list(entry.get("changed_files") or []) if str(path).strip()]
                if changed:
                    summary = "changed " + ", ".join(changed[:3])
            if not summary:
                continue
            lines.append(f"- {summary}; rejected because {reason or 'candidate_unresolved'}.")
        if not lines:
            return ""
        lines.append(
            "- Do not repeat a rejected branch unless the hypothesis or failure signature materially changes."
        )
        return "\n".join(lines)

    def _format_impacted_test_name(self, impacted_test: dict[str, Any]) -> str:
        full_name = str(impacted_test.get("full_name", "") or "").strip()
        if full_name:
            return full_name
        test_file = str(impacted_test.get("test_file", "") or "").strip().replace("\\", "/")
        test_name = str(
            impacted_test.get("test_name")
            or impacted_test.get("test_id")
            or ""
        ).strip()
        if test_file and test_name:
            return f"{test_file}::{test_name}"
        return test_file or test_name

    def _extract_impacted_test_names(
        self,
        impacted_records: list[dict[str, Any]],
        *,
        limit: int = 3,
    ) -> list[str]:
        names: list[str] = []
        for record in list(impacted_records or [])[: max(1, int(limit or 1))]:
            if not isinstance(record, dict):
                continue
            name = self._format_impacted_test_name(record)
            if name:
                names.append(name)
        return names

    def _build_failure_signature(self, candidate: dict[str, Any]) -> str:
        payload = {
            "patch_gate_reason": str(candidate.get("patch_gate_reason", "") or ""),
            "loop_abort_reason": str(candidate.get("loop_abort_reason", "") or ""),
            "f2p_failed": candidate.get("f2p_failed"),
            "p2p_smoke_failures": candidate.get("p2p_smoke_failures"),
            "regression_tests_failed": candidate.get("regression_tests_failed"),
            "changed_files": list(candidate.get("changed_files") or [])[:3],
            "impacted_failed_tests": self._extract_impacted_test_names(
                list((candidate.get("graphrag_metadata") or {}).get("impacted_failed_tests") or []),
                limit=3,
            ),
        }
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:12]

    def _evaluate_monotonic_progress(
        self,
        *,
        candidate: dict[str, Any],
        prev_candidate: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        signature = self._build_failure_signature(candidate)
        result = {
            "failure_signature": signature,
            "progress_gate_passed": True,
            "progress_gate_reason": "first_attempt",
            "progress_gate_stagnation_count": 0,
            "progress_gate_relocalize": False,
        }
        if not prev_candidate:
            return result

        prev_signature = str(
            prev_candidate.get("failure_signature")
            or self._build_failure_signature(prev_candidate)
        )
        prev_stagnation = int(prev_candidate.get("progress_gate_stagnation_count", 0) or 0)
        curr_f2p_passed = candidate.get("f2p_passed")
        prev_f2p_passed = prev_candidate.get("f2p_passed")
        if curr_f2p_passed is not None and prev_f2p_passed is not None:
            if int(curr_f2p_passed) > int(prev_f2p_passed):
                result["progress_gate_reason"] = "new_issue_tests_green"
                return result

        curr_reg_failed = candidate.get("regression_tests_failed")
        prev_reg_failed = prev_candidate.get("regression_tests_failed")
        if (
            candidate.get("regression_signal_reliable")
            and prev_candidate.get("regression_signal_reliable")
            and curr_reg_failed is not None
            and prev_reg_failed is not None
            and int(curr_reg_failed) < int(prev_reg_failed)
        ):
            result["progress_gate_reason"] = "regression_failures_reduced"
            return result

        if bool(candidate.get("clean_resolution")) and not bool(prev_candidate.get("clean_resolution")):
            result["progress_gate_reason"] = "clean_resolution_improved"
            return result

        if signature != prev_signature:
            result["progress_gate_reason"] = "failure_signature_changed"
            return result

        stagnation = prev_stagnation + 1
        result["progress_gate_passed"] = False
        result["progress_gate_reason"] = "stagnant_failure_signature"
        result["progress_gate_stagnation_count"] = stagnation
        result["progress_gate_relocalize"] = stagnation >= self.stagnant_failure_signature_limit
        return result

    def _run_pre_edit_graphrag_localization(
        self,
        *,
        repo_path: Path,
        problem_statement: str,
        fail_to_pass_tests: list[str],
        graphrag_mcp,
        impact_threshold: float,
        max_tests: int,
        strategy: str,
        log=print,
    ) -> dict[str, Any]:
        seed_files = self._derive_graphrag_seed_files(
            repo_path=repo_path,
            problem_statement=problem_statement,
            fail_to_pass_tests=fail_to_pass_tests,
        )
        result = {
            "success": False,
            "reason": "",
            "seed_files": seed_files,
            "focus_files": list(seed_files),
            "affected_tests": [],
            "total_tests": 0,
        }
        if not seed_files:
            result["reason"] = "no_seed_files"
            return result

        log(
            "PHASE: PRE_EDIT_GRAPH_LOCALIZATION_START "
            f"seeds={len(seed_files)} strategy={strategy}"
        )
        try:
            impact = graphrag_mcp.get_impacted_tests(
                repo_path=str(repo_path),
                changed_files=seed_files,
                impact_threshold=impact_threshold,
                strategy=strategy,
                require_fresh_graph=False,
            )
        except Exception as exc:
            result["reason"] = f"localization_error:{exc}"
            log(
                "PHASE: PRE_EDIT_GRAPH_LOCALIZATION_END "
                f"status=failed error={exc}"
            )
            return result

        impacted_tests = list(impact.get("tests") or [])
        focus_files = list(seed_files)
        for impacted_test in impacted_tests[:6]:
            if not isinstance(impacted_test, dict):
                continue
            test_file = str(impacted_test.get("test_file", "") or "").strip().replace("\\", "/")
            if test_file:
                for source_candidate in self._derive_source_candidate_from_test_file(repo_path, test_file):
                    focus_files.append(source_candidate)
                focus_files.append(test_file)
            for matched in list(impacted_test.get("matched_changed_files") or []):
                focus_files.append(str(matched or ""))
            for traversal_item in list(impacted_test.get("traversal_path") or []):
                traversal_text = str(traversal_item or "").split("::", 1)[0].strip()
                if traversal_text.endswith(".py"):
                    focus_files.append(traversal_text)

        result["success"] = bool(impact.get("success", False))
        result["reason"] = str(impact.get("error", "") or "")
        result["focus_files"] = self._prioritize_focus_files(focus_files, max_files=6)
        result["affected_tests"] = self._extract_impacted_test_names(impacted_tests, limit=6)
        result["total_tests"] = int(impact.get("total_tests", len(impacted_tests)) or 0)
        log(
            "PHASE: PRE_EDIT_GRAPH_LOCALIZATION_END "
            f"status={'success' if result['success'] else 'empty'} "
            f"affected={len(result['affected_tests'])} "
            f"focus={','.join(result['focus_files'][:4]) if result['focus_files'] else '-'}"
        )
        return result

    def _save_log(self, instance_id: str, log_lines: list[str]):
        """Write log to logs/{instance_id}.log."""
        log_dir = Path(__file__).parent.parent / "logs"
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / f"{instance_id}.log"
        log_file.write_text("\n".join(log_lines) + "\n")
        print(f"[QwenMini] Log saved to {log_file}")
