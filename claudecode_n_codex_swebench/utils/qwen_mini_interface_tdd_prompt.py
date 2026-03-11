#!/usr/bin/env python3
"""Dedicated qwen-mini interface profile for pure prompt-guided TDD runs.

This class intentionally leaves the default QwenMiniInterface behavior untouched.
It only enriches task text for tdd_mode=True so vanilla can continue using the
baseline prompt path.
"""

from __future__ import annotations

from typing import Optional

from .qwen_mini_interface import QwenMiniInterface


class QwenMiniInterfaceTDDPrompt(QwenMiniInterface):
    """Prompt-profile copy for TDD runs (no GraphRAG assumptions)."""

    def __init__(self):
        super().__init__()
        # Do not short-circuit retries on compile-valid submit; let attempts
        # continue unless a clean resolution is found.
        self.compile_valid_submit_stop = False
        self.enforce_tdd_test_first = False
        # Revert to deterministic decoding for repair stability.
        self.temperature = 0.0
        # Prompt-only TDD needs slightly more room than vanilla step-30.
        self.step_limit = 40
        # Keep loop controls close to the historically stable TDD profile.
        self.format_error_limit = 8
        self.no_edit_progress_step_limit = 16
        self.no_diff_streak_limit = 8
        # Keep environment/bootstrap failures as warnings only for TDD prompt.
        self.env_bootstrap_fail_limit = 0
        self.python_inline_fail_limit = 0
        # Compile-invalid attempts should retry cleanly; avoid long in-attempt
        # compile-repair spirals on corrupted patches.
        self.max_fix_iterations = 0
        # Local pytest signal is often noisy in this harness; rank mostly by
        # patch quality and gate risk.
        self.test_signal_mode = "off"
        self.retry_policy = "adaptive"
        self.adaptive_good_patch_max_changed_lines = 80
        self._prompt_fail_to_pass_tests: list[str] = []
        self._prompt_pass_to_pass_tests: list[str] = []

    def _score_candidate(self, candidate: dict) -> tuple:
        """TDD prompt scoring: patch quality first, test signal only if configured."""
        patch_chars = len(candidate.get("prediction", ""))
        non_empty = 1 if patch_chars > 0 else 0
        clean_resolution = 1 if candidate.get("clean_resolution") is True else 0
        gate_valid = 1 if candidate.get("patch_gate_valid") else 0
        gate_severity = str(candidate.get("patch_gate_severity", ""))
        gate_score = {"info": 2, "warn": 1}.get(gate_severity, 0)
        loop_clean = 1 if not candidate.get("loop_abort_reason") else 0
        submitted_score = 1 if candidate.get("status") == "Submitted" else 0
        signature_penalty = 1 if "potential_signature_change" in str(candidate.get("patch_gate_reason", "")) else 0
        changed_lines = int(candidate.get("changed_lines_total") or 0)
        changed_line_penalty = changed_lines if changed_lines > 0 else 10**6
        f2p_score, p2p_penalty = self._score_test_signal_components(candidate)
        attempt_idx = int(candidate.get("attempt") or 99)
        format_errors = int(candidate.get("format_errors") or 0)
        timeout_penalty = int(candidate.get("timeouts") or 0)
        step_penalty = int(candidate.get("steps") or 0)
        return (
            non_empty,
            clean_resolution,
            gate_valid,
            gate_score,
            loop_clean,
            submitted_score,
            -signature_penalty,
            -changed_line_penalty,
            f2p_score,
            -p2p_penalty,
            -attempt_idx,
            -format_errors,
            -timeout_penalty,
            -step_penalty,
            -patch_chars,
        )

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
        # Persist test context for prompt formatting during this instance run.
        self._prompt_fail_to_pass_tests = list(fail_to_pass_tests or [])
        self._prompt_pass_to_pass_tests = list(pass_to_pass_tests or [])
        try:
            return super().execute_code_cli(
                instance_id=instance_id,
                problem_statement=problem_statement,
                repo=repo,
                base_commit=base_commit,
                hints_text=hints_text,
                tdd_mode=tdd_mode,
                graphrag_enabled=graphrag_enabled,
                graphrag_mcp=graphrag_mcp,
                fail_to_pass_tests=fail_to_pass_tests,
                pass_to_pass_tests=pass_to_pass_tests,
            )
        finally:
            self._prompt_fail_to_pass_tests = []
            self._prompt_pass_to_pass_tests = []

    def _format_task(
        self,
        problem_statement: str,
        hints_text: str,
        affected_tests: list = None,
        tdd_mode: bool = False,
        focus_files: Optional[list[str]] = None,
        graphrag_summary: Optional[dict] = None,
    ) -> str:
        task = super()._format_task(
            problem_statement=problem_statement,
            hints_text=hints_text,
            affected_tests=affected_tests,
            tdd_mode=tdd_mode,
            focus_files=focus_files,
            graphrag_summary=graphrag_summary,
        )

        if not tdd_mode:
            return task

        fail_to_pass_tests = self._prompt_fail_to_pass_tests
        pass_to_pass_tests = self._prompt_pass_to_pass_tests

        task += (
            "\n\n## Prompt-Guided TDD Workflow (Pure Prompting)\n"
            "Use this compact loop:\n"
            "1. Locate the likely function from issue text + test names.\n"
            "2. Make one minimal source edit quickly.\n"
            "3. Validate statically and submit.\n\n"
            "Hard rules:\n"
            "- Keep edits minimal and local; do not change public signatures unless required.\n"
            "- Do not use absolute paths from issue text (`/Users/runner/...`). Stay in repo root.\n"
            "- Do not run `pip install` or `setup.py build_ext`.\n"
            "- Avoid repeated bootstrap/setup loops. Use targeted `python -m pytest -q ...` or `python -m py_compile ...` only.\n"
            "- Inspect targeted ranges (`nl -ba`, `sed -n`), avoid full-file dumps.\n"
            "- Turn the initial exploration into a concrete edit within a moderate number of commands; do not spend a long stretch only browsing.\n"
            "- If your reasoning suggests multiple commands, choose the single best next command and leave the others for later turns.\n"
            "- Never include a second bash block for a future step.\n"
            "- Do not output THOUGHT:, plans, bullet lists, or any prose outside the single bash block. Visible reasoning is a format failure.\n"
            "- After first non-empty diff: run `git diff --name-only` and `python -m py_compile <changed.py>` then submit.\n"
            "- Every response must be exactly one bash code block with one executable command.\n"
        )

        if fail_to_pass_tests:
            task += "\n\n## Target FAIL_TO_PASS Tests\n"
            for test_name in fail_to_pass_tests[:20]:
                task += f"- {test_name}\n"
            if len(fail_to_pass_tests) > 20:
                task += f"- ... ({len(fail_to_pass_tests) - 20} more)\n"
            task += "\nUse these names to guide file/function targeting.\n"
        else:
            task += (
                "\n\nNo FAIL_TO_PASS list is available. "
                "infer target behavior from issue text and existing tests.\n"
            )

        smoke_tests = pass_to_pass_tests[: self.p2p_smoke_count]
        if smoke_tests:
            task += "\n\n## PASS_TO_PASS Smoke Tests\n"
            for test_name in smoke_tests:
                task += f"- {test_name}\n"
            task += "\nUse this list to avoid broad regressions.\n"
        else:
            task += (
                "\n\nNo PASS_TO_PASS smoke list is available. "
                "favor minimal edits and static validation.\n"
            )

        return task
