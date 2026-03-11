#!/usr/bin/env python3
"""Dedicated qwen-mini profile for GraphRAG + TDD runs.

Inherits the proven TDD prompt profile (31% baseline) and adds GraphRAG
as a purely additive layer: when graph or its bounded fallback produces
useful regression signal, inject it into the workflow; otherwise behave
like `tdd_prompt`.
"""

from __future__ import annotations

import os

from .qwen_mini_interface_tdd_prompt import QwenMiniInterfaceTDDPrompt


def _profile_int_env(name: str, default: int, *, minimum: int = 0) -> int:
    try:
        return max(minimum, int(str(os.getenv(name, "")).strip() or default))
    except (TypeError, ValueError):
        return max(minimum, int(default))


class QwenMiniInterfaceGraphRAGTDD(QwenMiniInterfaceTDDPrompt):
    """Graph-aware TDD profile: TDD prompt baseline + additive GraphRAG signal."""

    def __init__(self):
        super().__init__()
        # Deterministic decoding for consistency.
        self.temperature = 0.0
        # GraphRAG's value is knowing which tests matter — use test signal
        # at full weight so candidate scoring actually leverages graph output.
        self.test_signal_mode = "hard"
        # Allow two regression repair rounds so the agent can recover if the
        # first repair introduces a new issue.
        self.max_fix_iterations = 2
        self.step_limit = _profile_int_env("QWEN_MINI_GRAPHRAG_TDD_STEP_LIMIT", 56, minimum=1)
        # Give the agent enough room to explore before committing to an edit.
        # Tight limits were causing premature commitment to wrong files.
        self.search_streak_limit = _profile_int_env(
            "QWEN_MINI_GRAPHRAG_TDD_SEARCH_STREAK_LIMIT",
            16,
            minimum=1,
        )
        self.max_read_only_steps_before_edit = _profile_int_env(
            "QWEN_MINI_GRAPHRAG_TDD_MAX_READ_ONLY_STEPS_BEFORE_EDIT",
            25,
            minimum=1,
        )
        self.require_first_edit_by_step = _profile_int_env(
            "QWEN_MINI_GRAPHRAG_TDD_REQUIRE_FIRST_EDIT_BY_STEP",
            32,
            minimum=1,
        )
        self.no_edit_progress_step_limit = _profile_int_env(
            "QWEN_MINI_GRAPHRAG_TDD_NO_EDIT_PROGRESS_STEP_LIMIT",
            28,
            minimum=1,
        )
        self.model_max_tokens = _profile_int_env(
            "QWEN_MINI_GRAPHRAG_TDD_MODEL_MAX_TOKENS",
            2048,
            minimum=256,
        )

    def _format_task(
        self,
        problem_statement: str,
        hints_text: str,
        affected_tests: list = None,
        tdd_mode: bool = False,
        focus_files: list[str] | None = None,
        graphrag_summary: dict | None = None,
    ) -> str:
        # Use TDD prompt's full formatting as the base.
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

        # Lightweight GraphRAG guidance — advisory, not mandatory.
        task += (
            "\n\n## GraphRAG Hints\n"
            "The GraphRAG context above suggests likely root-cause files and impacted tests.\n"
            "Use these hints to prioritize your exploration, but if they look wrong, "
            "investigate other files based on the issue description.\n"
            "After your fix, if regression tests are reported, address them with a minimal follow-up edit.\n"
        )

        return task
