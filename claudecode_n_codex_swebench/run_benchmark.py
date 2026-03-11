#!/usr/bin/env python3
"""
Multi-variant benchmark runner with auto-evaluation and report generation.

Runs the same SWE-bench instances across qwen-mini variants (vanilla, tdd_prompt,
tdd_loop, graphrag_tdd), automatically evaluates with Docker, and produces a comparison
report.

Usage:
    # Vanilla + TDD-prompt on 10 instances
    python run_benchmark.py --dataset princeton-nlp/SWE-bench_Verified \\
        --limit 10 --variants vanilla tdd_prompt

    # Specific instance IDs, skip Docker eval
    python run_benchmark.py --dataset princeton-nlp/SWE-bench_Verified \\
        --instance-ids astropy__astropy-12907 astropy__astropy-13033 \\
        --variants vanilla tdd_loop graphrag_tdd --skip-eval

    # Instance IDs from file
    python run_benchmark.py --dataset princeton-nlp/SWE-bench_Verified \\
        --instance-ids-file failed_instances.txt \\
        --variants vanilla --run-name "batch_rerun"
"""

import argparse
import json
import multiprocessing as mp
import os
import queue
import signal
import shutil
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import jsonlines

from code_swe_agent import CodeSWEAgent, load_cached_dataset
from utils.eval_runtime import (
    cleanup_stale_swebench_eval_containers,
    default_eval_worker_count,
    describe_eval_capacity,
)


# ---------------------------------------------------------------------------
# Variant definitions
# ---------------------------------------------------------------------------

@dataclass
class VariantConfig:
    name: str
    backend: str = "qwen-mini"
    tdd_mode: bool = False
    use_graphrag: bool = False
    tdd_prompt_profile: bool = False
    graphrag_tdd_profile: bool = False


VARIANT_REGISTRY: dict[str, VariantConfig] = {
    "vanilla": VariantConfig("vanilla"),
    "tdd_prompt": VariantConfig("tdd_prompt", tdd_mode=True, tdd_prompt_profile=True),
    "tdd_loop": VariantConfig("tdd_loop", tdd_mode=True),
    "graphrag_tdd": VariantConfig(
        "graphrag_tdd",
        tdd_mode=True,
        use_graphrag=True,
        graphrag_tdd_profile=True,
    ),
    # Backward-compatible aliases
    "baseline": VariantConfig("vanilla"),
    "tdd": VariantConfig("tdd_loop", tdd_mode=True),
    "graphrag": VariantConfig(
        "graphrag_tdd",
        tdd_mode=True,
        use_graphrag=True,
        graphrag_tdd_profile=True,
    ),
}


# ---------------------------------------------------------------------------
# Per-variant results
# ---------------------------------------------------------------------------

@dataclass
class InstanceResult:
    instance_id: str
    patch_chars: int = 0
    has_error: bool = False
    error_msg: str = ""
    elapsed_s: float = 0.0
    resolved: Optional[bool] = None  # filled after Docker eval
    attempts_used: Optional[int] = None
    loop_abort_reason: str = ""
    f2p_pass_rate: Optional[float] = None
    p2p_smoke_failures: Optional[int] = None
    clean_resolution: Optional[bool] = None
    patch_gate_valid: Optional[bool] = None
    patch_gate_reason: str = ""
    patch_gate_severity: str = ""
    test_signal_reliable: Optional[bool] = None
    f2p_reliable: Optional[bool] = None
    f2p_runtime_strategy: str = ""
    f2p_runtime_fallback_used: str = ""
    f2p_runtime_unreliable_reason: str = ""
    p2p_reliable: Optional[bool] = None
    p2p_runtime_strategy: str = ""
    p2p_runtime_fallback_used: str = ""
    p2p_runtime_unreliable_reason: str = ""
    changed_lines_total: Optional[int] = None
    graph_guard_mode: str = ""
    graph_guard_passed: Optional[bool] = None
    graph_guard_reason: str = ""
    test_files_changed_count: Optional[int] = None
    indexed_search_attempted: Optional[bool] = None
    indexed_search_success: Optional[bool] = None
    graph_useful_signal: Optional[bool] = None
    graph_fallback_reason: str = ""
    impacted_selected_count: Optional[int] = None
    impacted_runnable_count: Optional[int] = None
    impacted_runnable_ratio: Optional[float] = None
    impacted_precision_score: Optional[float] = None
    impacted_precision_floor_passed: Optional[bool] = None
    repo_test_changed: Optional[bool] = None
    tdd_evidence_complete: Optional[bool] = None
    tdd_evidence_reason: str = ""
    tdd_fail_open_applied: Optional[bool] = None
    tdd_infra_reasons: list[str] = field(default_factory=list)
    repro_cmd_present: Optional[bool] = None
    repro_failed_before_edit: Optional[bool] = None
    verify_cmd_present: Optional[bool] = None
    verify_pass_after_edit: Optional[bool] = None
    smoke_cmd_present: Optional[bool] = None
    smoke_pass_after_edit: Optional[bool] = None
    repro_runtime_strategy: str = ""
    repro_runtime_fallback_used: str = ""
    repro_runtime_unreliable_reason: str = ""
    prompt_trace_id: str = ""
    prompt_estimated_tokens_after: Optional[int] = None
    prompt_trimmed: Optional[bool] = None
    mlx_backend_pid: Optional[int] = None
    mlx_backend_rss_kb: Optional[int] = None
    mlx_backend_reused_existing: Optional[bool] = None
    mlx_backend_started_now: Optional[bool] = None
    mlx_backend_crash_detected: Optional[bool] = None
    mlx_backend_restarted: Optional[bool] = None
    mlx_backend_failure_reason: str = ""


@dataclass
class VariantResult:
    name: str
    predictions_file: str = ""
    eval_file: str = ""
    instances: list[InstanceResult] = field(default_factory=list)
    total_time_s: float = 0.0
    generation_count: int = 0
    empty_count: int = 0
    resolved_count: int = 0
    unresolved_count: int = 0
    eval_ran: bool = False


# ---------------------------------------------------------------------------
# Process isolation helpers
# ---------------------------------------------------------------------------

def _build_agent_from_runtime_spec(spec: dict):
    if bool(spec.get("use_graphrag")):
        from code_swe_agent_graphrag import GraphRAGCodeSWEAgent

        return GraphRAGCodeSWEAgent(
            backend=spec.get("backend", "qwen-mini"),
            model=spec.get("model"),
            tdd_mode=bool(spec.get("tdd_mode")),
            graphrag_tdd_profile=bool(spec.get("graphrag_tdd_profile")),
            max_attempts=spec.get("max_attempts"),
            step_limit=spec.get("step_limit"),
            loop_policy=spec.get("loop_policy"),
            max_fix_iterations=spec.get("max_fix_iterations"),
            patch_compile_gate=spec.get("patch_compile_gate"),
            test_signal_mode=spec.get("test_signal_mode"),
            retry_policy=spec.get("retry_policy"),
            enforce_tdd_test_first=spec.get("enforce_tdd_test_first"),
            graph_guard_mode=spec.get("graph_guard_mode"),
            strict_tdd_evidence=spec.get("strict_tdd_evidence"),
            test_change_policy=spec.get("test_change_policy"),
            strict_tdd_infra_policy=spec.get("strict_tdd_infra_policy"),
            strict_tdd_infra_retry_budget=spec.get("strict_tdd_infra_retry_budget"),
            indexed_signal_mode=spec.get("indexed_signal_mode"),
            graphrag_tool_mode=spec.get("graphrag_tool_mode", "local"),
            graph_refresh_policy=spec.get("graph_refresh_policy"),
        )

    return CodeSWEAgent(
        backend=spec.get("backend", "qwen-mini"),
        model=spec.get("model"),
        tdd_mode=bool(spec.get("tdd_mode")),
        tdd_prompt_profile=bool(spec.get("tdd_prompt_profile")),
        max_attempts=spec.get("max_attempts"),
        step_limit=spec.get("step_limit"),
        loop_policy=spec.get("loop_policy"),
        max_fix_iterations=spec.get("max_fix_iterations"),
        patch_compile_gate=spec.get("patch_compile_gate"),
        test_signal_mode=spec.get("test_signal_mode"),
        retry_policy=spec.get("retry_policy"),
        enforce_tdd_test_first=spec.get("enforce_tdd_test_first"),
    )


def _append_prediction(pred_file: Path, prediction: dict) -> None:
    with jsonlines.open(pred_file, mode="a") as writer:
        writer.write(prediction)


def _instance_worker_entry(agent_spec, instance, result_queue):
    """
    Run a single instance in an isolated process and return the prediction payload.

    Using a separate process lets the parent enforce a hard timeout and kill
    stalled model/indexing calls without freezing the whole benchmark run.
    """
    # Create an isolated process group so timeout cleanup can terminate children.
    try:
        if hasattr(os, "setsid"):
            os.setsid()
    except Exception:
        pass

    agent = None
    try:
        agent = _build_agent_from_runtime_spec(dict(agent_spec or {}))
        prediction = agent.process_instance(instance)
        result_queue.put({
            "ok": True,
            "prediction": prediction,
        })
    except Exception as exc:
        result_queue.put({
            "ok": False,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        })
    finally:
        cleanup_fn = getattr(agent, "cleanup", None) if agent is not None else None
        if callable(cleanup_fn):
            try:
                cleanup_fn()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------

class BenchmarkRunner:
    def __init__(
        self,
        dataset: str,
        variants: list[VariantConfig],
        limit: Optional[int] = None,
        instance_ids: Optional[list[str]] = None,
        skip_eval: bool = False,
        max_workers: int = 2,
        eval_max_workers: Optional[int] = None,
        run_name: str = "",
        model: Optional[str] = None,
        max_attempts: Optional[int] = None,
        step_limit: Optional[int] = None,
        loop_policy: str = "strict",
        max_fix_iterations: int = 2,
        patch_compile_gate: str = "on",
        test_signal_mode: str = "hard",
        retry_policy: str = "fixed",
        enforce_tdd_test_first: str = "on",
        graph_guard_mode: str = "either",
        strict_tdd_evidence: str = "off",
        test_change_policy: str = "any_test_like",
        strict_tdd_infra_policy: str = "fail_closed",
        strict_tdd_infra_retry_budget: int = 2,
        indexed_signal_mode: str = "attempted_query",
        graphrag_tool_mode: str = "local",
        instance_timeout_sec: int = 1200,
        isolate_instances: str = "off",
        test_signal_mode_explicit: bool = False,
        retry_policy_explicit: bool = False,
        enforce_tdd_test_first_explicit: bool = False,
        graph_guard_mode_explicit: bool = False,
        strict_tdd_evidence_explicit: bool = False,
        test_change_policy_explicit: bool = False,
        strict_tdd_infra_policy_explicit: bool = False,
        strict_tdd_infra_retry_budget_explicit: bool = False,
        indexed_signal_mode_explicit: bool = False,
        step_limit_explicit: bool = False,
        max_fix_iterations_explicit: bool = False,
        max_workers_explicit: bool = False,
    ):
        self.dataset = dataset
        self.variants = variants
        self.limit = limit
        self.instance_ids = instance_ids
        self.skip_eval = skip_eval
        self.max_workers = max_workers
        self.eval_max_workers = eval_max_workers
        self.run_name = run_name
        self.model = model
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
        self.strict_tdd_infra_retry_budget = max(0, int(strict_tdd_infra_retry_budget))
        self.indexed_signal_mode = indexed_signal_mode
        self.graphrag_tool_mode = str(graphrag_tool_mode or "local").strip().lower() or "local"
        self.instance_timeout_sec = max(0, int(instance_timeout_sec))
        self.isolate_instances = isolate_instances
        self.test_signal_mode_explicit = test_signal_mode_explicit
        self.retry_policy_explicit = retry_policy_explicit
        self.enforce_tdd_test_first_explicit = enforce_tdd_test_first_explicit
        self.graph_guard_mode_explicit = graph_guard_mode_explicit
        self.strict_tdd_evidence_explicit = strict_tdd_evidence_explicit
        self.test_change_policy_explicit = test_change_policy_explicit
        self.strict_tdd_infra_policy_explicit = strict_tdd_infra_policy_explicit
        self.strict_tdd_infra_retry_budget_explicit = strict_tdd_infra_retry_budget_explicit
        self.indexed_signal_mode_explicit = indexed_signal_mode_explicit
        self.step_limit_explicit = step_limit_explicit
        self.max_fix_iterations_explicit = max_fix_iterations_explicit
        self.max_workers_explicit = max_workers_explicit

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = f"_{run_name}" if run_name else ""
        self.run_dir = Path("benchmark_runs") / f"{ts}{suffix}"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "predictions").mkdir(exist_ok=True)
        (self.run_dir / "evaluations").mkdir(exist_ok=True)

        self.progress_log = self.run_dir / "progress.log"
        self.results: list[VariantResult] = []

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line, flush=True)
        with open(self.progress_log, "a") as f:
            f.write(line + "\n")

    def _effective_graphrag_tool_mode(self, config: VariantConfig) -> str:
        """
        Benchmark runs always hard-pin GraphRAG variants to the in-process tool.

        MCP/auto compatibility remains available outside the benchmark runner.
        """
        if not config.use_graphrag:
            return self.graphrag_tool_mode
        return "local"

    def _effective_variant_controls(self, config: VariantConfig) -> dict:
        """
        Resolve per-variant controls exactly as used at runtime.

        Keeping this logic centralized ensures saved benchmark config mirrors
        the effective controls passed into each agent.
        """
        is_tdd_prompt_profile = bool(config.tdd_prompt_profile)
        is_graphrag_tdd_profile = bool(config.graphrag_tdd_profile)

        step_limit = self.step_limit
        max_fix_iterations = self.max_fix_iterations
        test_signal_mode = self.test_signal_mode
        retry_policy = self.retry_policy
        enforce_tdd_test_first = (self.enforce_tdd_test_first == "on")
        graph_guard_mode = self.graph_guard_mode
        strict_tdd_evidence = (self.strict_tdd_evidence == "on")
        test_change_policy = self.test_change_policy
        strict_tdd_infra_policy = self.strict_tdd_infra_policy
        strict_tdd_infra_retry_budget = int(self.strict_tdd_infra_retry_budget)
        indexed_signal_mode = self.indexed_signal_mode

        # Prompt-only TDD profile defaults should remain owned by the profile
        # unless the user explicitly overrides a knob via CLI.
        if is_tdd_prompt_profile and not self.test_signal_mode_explicit:
            test_signal_mode = None
        if is_tdd_prompt_profile and not self.retry_policy_explicit:
            retry_policy = None
        if is_tdd_prompt_profile and not self.enforce_tdd_test_first_explicit:
            enforce_tdd_test_first = None

        # GraphRAG TDD is additive to TDD prompt defaults; the only profile
        # runtime override is one fix iteration unless explicitly set by CLI.
        if is_graphrag_tdd_profile and not self.step_limit_explicit:
            step_limit = 56
        if is_graphrag_tdd_profile and not self.test_signal_mode_explicit:
            test_signal_mode = "soft"
        if is_graphrag_tdd_profile and not self.retry_policy_explicit:
            retry_policy = "adaptive"
        if is_graphrag_tdd_profile and not self.enforce_tdd_test_first_explicit:
            enforce_tdd_test_first = False
        if is_graphrag_tdd_profile and not self.max_fix_iterations_explicit:
            max_fix_iterations = 1
        graph_refresh_policy = "auto"

        return {
            "step_limit": step_limit,
            "max_fix_iterations": max_fix_iterations,
            "test_signal_mode": test_signal_mode,
            "retry_policy": retry_policy,
            "enforce_tdd_test_first": enforce_tdd_test_first,
            "graph_guard_mode": graph_guard_mode,
            "strict_tdd_evidence": strict_tdd_evidence,
            "test_change_policy": test_change_policy,
            "strict_tdd_infra_policy": strict_tdd_infra_policy,
            "strict_tdd_infra_retry_budget": strict_tdd_infra_retry_budget,
            "indexed_signal_mode": indexed_signal_mode,
            "graphrag_tool_mode": self._effective_graphrag_tool_mode(config),
            "graph_refresh_policy": graph_refresh_policy,
        }

    def _default_eval_max_workers(self) -> int:
        return max(1, int(default_eval_worker_count(instance_count=len(self.instance_ids or []) or self.limit)))

    def _resolve_eval_max_workers(self) -> int:
        if self.eval_max_workers is not None:
            return max(1, int(self.eval_max_workers))
        if self.max_workers_explicit and int(self.max_workers) > 1:
            return max(1, int(self.max_workers))
        return self._default_eval_max_workers()

    def _build_agent_runtime_spec(self, config: VariantConfig, controls: dict) -> dict:
        return {
            "backend": config.backend,
            "model": self.model,
            "tdd_mode": config.tdd_mode,
            "use_graphrag": config.use_graphrag,
            "tdd_prompt_profile": config.tdd_prompt_profile,
            "graphrag_tdd_profile": config.graphrag_tdd_profile,
            "max_attempts": self.max_attempts,
            "step_limit": controls["step_limit"],
            "loop_policy": self.loop_policy,
            "max_fix_iterations": controls["max_fix_iterations"],
            "patch_compile_gate": (self.patch_compile_gate == "on"),
            "test_signal_mode": controls["test_signal_mode"],
            "retry_policy": controls["retry_policy"],
            "enforce_tdd_test_first": controls["enforce_tdd_test_first"],
            "graph_guard_mode": controls["graph_guard_mode"],
            "strict_tdd_evidence": controls["strict_tdd_evidence"],
            "test_change_policy": controls["test_change_policy"],
            "strict_tdd_infra_policy": controls["strict_tdd_infra_policy"],
            "strict_tdd_infra_retry_budget": controls["strict_tdd_infra_retry_budget"],
            "indexed_signal_mode": controls["indexed_signal_mode"],
            "graphrag_tool_mode": controls["graphrag_tool_mode"],
            "graph_refresh_policy": controls["graph_refresh_policy"],
        }

    # ------------------------------------------------------------------
    # Instance loading
    # ------------------------------------------------------------------

    def _load_instances(self) -> list:
        all_data = load_cached_dataset(self.dataset, split="test", limit=self.limit)
        if self.instance_ids:
            id_set = set(self.instance_ids)
            filtered = [inst for inst in all_data if inst["instance_id"] in id_set]
            if not filtered:
                # If --limit didn't load enough, reload without limit
                all_data = load_cached_dataset(self.dataset, split="test")
                filtered = [inst for inst in all_data if inst["instance_id"] in id_set]
            missing = id_set - {inst["instance_id"] for inst in filtered}
            if missing:
                self._log(f"WARNING: {len(missing)} instance(s) not found: {missing}")
            return filtered
        return list(all_data)

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def _terminate_worker_process(self, proc: mp.Process):
        """Best-effort worker shutdown, including child subprocesses."""
        if not proc.is_alive():
            return

        try:
            # If worker created a new process group, kill the full group.
            if hasattr(os, "killpg"):
                os.killpg(proc.pid, signal.SIGTERM)
            else:
                proc.terminate()
        except ProcessLookupError:
            pass
        except Exception:
            proc.terminate()

        proc.join(timeout=5)
        if proc.is_alive():
            try:
                if hasattr(os, "killpg"):
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
            except ProcessLookupError:
                pass
            except Exception:
                proc.kill()
            proc.join(timeout=2)

    def _run_instance_with_timeout(self, agent, instance: dict, *, agent_spec: Optional[dict] = None) -> dict:
        """Run a single instance with a hard wall-clock timeout."""
        iid = instance.get("instance_id", "<unknown>")

        if self.isolate_instances != "on":
            # Run in-process for live logs and rely on interface-level timeouts.
            return agent.process_instance(instance)

        if not agent_spec:
            raise ValueError("agent_spec is required when isolate_instances=on")

        # Use spawn so MLX/Metal and GraphRAG runtime state is created fresh in the child.
        try:
            ctx = mp.get_context("spawn")
        except ValueError:
            self._log(
                "  WARN: multiprocessing spawn context unavailable; "
                f"running instance without hard timeout | {iid}"
            )
            fallback_agent = _build_agent_from_runtime_spec(agent_spec)
            try:
                return fallback_agent.process_instance(instance)
            finally:
                cleanup_fn = getattr(fallback_agent, "cleanup", None)
                if callable(cleanup_fn):
                    cleanup_fn()

        result_queue = ctx.Queue(maxsize=1)
        proc = ctx.Process(
            target=_instance_worker_entry,
            args=(agent_spec, instance, result_queue),
            daemon=False,
        )
        proc.start()
        payload = None
        try:
            deadline = (
                time.time() + float(self.instance_timeout_sec)
                if self.instance_timeout_sec > 0
                else None
            )
            poll_interval = 0.25

            while True:
                if payload is None:
                    try:
                        payload = result_queue.get(timeout=poll_interval)
                    except queue.Empty:
                        payload = None

                if payload is not None:
                    proc.join(timeout=5)
                    if proc.is_alive():
                        self._terminate_worker_process(proc)
                    break

                if not proc.is_alive():
                    proc.join(timeout=0.1)
                    break

                if deadline is not None and time.time() >= deadline:
                    self._terminate_worker_process(proc)
                    raise TimeoutError(f"instance_timeout:{self.instance_timeout_sec}s")
        finally:
            try:
                result_queue.close()
            except Exception:
                pass

        if payload and payload.get("ok"):
            return payload.get("prediction") or {}

        if payload and not payload.get("ok"):
            err = str(payload.get("error", "unknown_worker_error"))
            tb = str(payload.get("traceback", "")).strip()
            if tb:
                self._log(f"  [{iid}] worker traceback:\n{tb}")
            raise RuntimeError(err)

        if proc.exitcode not in (0, None):
            raise RuntimeError(f"worker_exitcode:{proc.exitcode}")

        raise RuntimeError("worker_no_result")

    def _run_variant(self, config: VariantConfig, instances: list) -> VariantResult:
        vr = VariantResult(name=config.name)
        n = len(instances)
        self._log(f"=== VARIANT: {config.name} ({n} instances) ===")
        controls = self._effective_variant_controls(config)
        step_limit = controls["step_limit"]
        max_fix_iterations = controls["max_fix_iterations"]
        test_signal_mode = controls["test_signal_mode"]
        retry_policy = controls["retry_policy"]
        enforce_tdd_test_first = controls["enforce_tdd_test_first"]
        graph_guard_mode = controls["graph_guard_mode"]
        strict_tdd_evidence = controls["strict_tdd_evidence"]
        test_change_policy = controls["test_change_policy"]
        strict_tdd_infra_policy = controls["strict_tdd_infra_policy"]
        strict_tdd_infra_retry_budget = controls["strict_tdd_infra_retry_budget"]
        indexed_signal_mode = controls["indexed_signal_mode"]
        effective_graphrag_tool_mode = controls["graphrag_tool_mode"]
        graph_refresh_policy = controls["graph_refresh_policy"]

        self._log(
            "  Effective controls "
            f"[{config.name}]: step_limit={step_limit} "
            f"max_fix_iterations={max_fix_iterations} "
            f"test_signal_mode={test_signal_mode} "
            f"retry_policy={retry_policy} "
            f"enforce_tdd_test_first={enforce_tdd_test_first} "
            f"graph_guard_mode={graph_guard_mode} "
            f"strict_tdd_evidence={strict_tdd_evidence} "
            f"test_change_policy={test_change_policy} "
            f"strict_tdd_infra_policy={strict_tdd_infra_policy} "
            f"strict_tdd_infra_retry_budget={strict_tdd_infra_retry_budget} "
            f"indexed_signal_mode={indexed_signal_mode} "
            f"graphrag_tool_mode={effective_graphrag_tool_mode} "
            f"graph_refresh_policy={graph_refresh_policy} "
            f"isolate_instances={self.isolate_instances} "
            f"instance_timeout_sec={self.instance_timeout_sec}"
        )

        # Initialize prediction file in the run directory
        pred_file = self.run_dir / "predictions" / f"{config.name}.jsonl"
        if pred_file.exists():
            pred_file.unlink()
        pred_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        agent_spec = self._build_agent_runtime_spec(config, controls)
        agent = None

        if config.use_graphrag and effective_graphrag_tool_mode != self.graphrag_tool_mode:
            self._log(
                f"  GraphRAG benchmark hardening [{config.name}]: "
                f"forcing tool mode to local (requested={self.graphrag_tool_mode})"
            )

        if self.isolate_instances != "on":
            agent = _build_agent_from_runtime_spec(agent_spec)
            agent.pred_timestamp = pred_timestamp
            agent.pred_file = pred_file

        generated = 0
        empty = 0
        variant_t0 = time.time()

        try:
            for i, instance in enumerate(instances, 1):
                iid = instance["instance_id"]
                t0 = time.time()
                self._log(f"  [{config.name}] {i}/{n} PHASE: INSTANCE_START | {iid}")
                if config.use_graphrag:
                    self._log(f"  [{config.name}] {i}/{n} PHASE: INDEXING_AND_CODEGEN_START | {iid}")

                try:
                    prediction = self._run_instance_with_timeout(
                        agent,
                        instance,
                        agent_spec=agent_spec,
                    )
                except TimeoutError as exc:
                    self._log(f"  [{config.name}] {i}/{n} PHASE: INSTANCE_TIMEOUT | {iid} | {exc}")
                    prediction = {
                        "instance_id": iid,
                        "model": "qwen-mini",
                        "prediction": "",
                        "error": str(exc),
                        "loop_abort_reason": str(exc),
                    }
                except Exception as exc:
                    prediction = {
                        "instance_id": iid,
                        "model": "qwen-mini",
                        "prediction": "",
                        "error": str(exc),
                    }

                elapsed = time.time() - t0
                patch_chars = len(prediction.get("prediction", ""))
                has_error = bool(prediction.get("error"))

                if patch_chars > 0:
                    generated += 1
                else:
                    empty += 1

                ir = InstanceResult(
                    instance_id=iid,
                    patch_chars=patch_chars,
                    has_error=has_error,
                    error_msg=prediction.get("error", ""),
                    elapsed_s=elapsed,
                    attempts_used=prediction.get("attempts_used"),
                    loop_abort_reason=prediction.get("loop_abort_reason", "") or "",
                    f2p_pass_rate=prediction.get("f2p_pass_rate"),
                    p2p_smoke_failures=prediction.get("p2p_smoke_failures"),
                    clean_resolution=prediction.get("clean_resolution"),
                    patch_gate_valid=prediction.get("patch_gate_valid"),
                    patch_gate_reason=prediction.get("patch_gate_reason", "") or "",
                    patch_gate_severity=prediction.get("patch_gate_severity", "") or "",
                    test_signal_reliable=prediction.get("test_signal_reliable"),
                    f2p_reliable=prediction.get("f2p_reliable"),
                    f2p_runtime_strategy=prediction.get("f2p_runtime_strategy", "") or "",
                    f2p_runtime_fallback_used=prediction.get("f2p_runtime_fallback_used", "") or "",
                    f2p_runtime_unreliable_reason=prediction.get("f2p_runtime_unreliable_reason", "") or "",
                    p2p_reliable=prediction.get("p2p_reliable"),
                    p2p_runtime_strategy=prediction.get("p2p_runtime_strategy", "") or "",
                    p2p_runtime_fallback_used=prediction.get("p2p_runtime_fallback_used", "") or "",
                    p2p_runtime_unreliable_reason=prediction.get("p2p_runtime_unreliable_reason", "") or "",
                    changed_lines_total=prediction.get("changed_lines_total"),
                    graph_guard_mode=prediction.get("graph_guard_mode", "") or "",
                    graph_guard_passed=prediction.get("graph_guard_passed"),
                    graph_guard_reason=prediction.get("graph_guard_reason", "") or "",
                    test_files_changed_count=len(prediction.get("test_files_changed", []) or []),
                    indexed_search_attempted=prediction.get("indexed_search_attempted"),
                    indexed_search_success=prediction.get("indexed_search_success"),
                    graph_useful_signal=prediction.get("graph_useful_signal"),
                    graph_fallback_reason=prediction.get("graph_fallback_reason", "") or "",
                    impacted_selected_count=prediction.get("impacted_selected_count"),
                    impacted_runnable_count=prediction.get("impacted_runnable_count"),
                    impacted_runnable_ratio=prediction.get("impacted_runnable_ratio"),
                    impacted_precision_score=prediction.get("impacted_precision_score"),
                    impacted_precision_floor_passed=prediction.get("impacted_precision_floor_passed"),
                    repo_test_changed=prediction.get("repo_test_changed"),
                    tdd_evidence_complete=prediction.get("tdd_evidence_complete"),
                    tdd_evidence_reason=prediction.get("tdd_evidence_reason", "") or "",
                    tdd_fail_open_applied=prediction.get("tdd_fail_open_applied"),
                    tdd_infra_reasons=list(prediction.get("tdd_infra_reasons", []) or []),
                    repro_cmd_present=prediction.get("repro_cmd_present"),
                    repro_failed_before_edit=prediction.get("repro_failed_before_edit"),
                    verify_cmd_present=prediction.get("verify_cmd_present"),
                    verify_pass_after_edit=prediction.get("verify_pass_after_edit"),
                    smoke_cmd_present=prediction.get("smoke_cmd_present"),
                    smoke_pass_after_edit=prediction.get("smoke_pass_after_edit"),
                    repro_runtime_strategy=prediction.get("repro_runtime_strategy", "") or "",
                    repro_runtime_fallback_used=prediction.get("repro_runtime_fallback_used", "") or "",
                    repro_runtime_unreliable_reason=prediction.get("repro_runtime_unreliable_reason", "") or "",
                    prompt_trace_id=prediction.get("prompt_trace_id", "") or "",
                    prompt_estimated_tokens_after=prediction.get("prompt_estimated_tokens_after"),
                    prompt_trimmed=prediction.get("prompt_trimmed"),
                    mlx_backend_pid=(prediction.get("mlx_backend_after", {}) or {}).get("pid"),
                    mlx_backend_rss_kb=(prediction.get("mlx_backend_after", {}) or {}).get("rss_kb"),
                    mlx_backend_reused_existing=prediction.get("mlx_backend_reused_existing"),
                    mlx_backend_started_now=prediction.get("mlx_backend_started_now"),
                    mlx_backend_crash_detected=prediction.get("mlx_backend_crash_detected"),
                    mlx_backend_restarted=prediction.get("mlx_backend_restarted"),
                    mlx_backend_failure_reason=prediction.get("mlx_backend_failure_reason", "") or "",
                )
                vr.instances.append(ir)

                # Save prediction incrementally
                if agent is not None:
                    agent._save_predictions(prediction)
                else:
                    _append_prediction(pred_file, prediction)

                # Progress line
                total_elapsed = time.time() - variant_t0
                self._log(
                    f"  [{config.name}] {i}/{n} done | "
                    f"{generated} patches | {empty} empty | "
                    f"{iid}: {patch_chars} chars ({elapsed:.0f}s) | "
                    f"total: {total_elapsed / 60:.1f}m"
                )
                if config.use_graphrag:
                    self._log(f"  [{config.name}] {i}/{n} PHASE: INDEXING_AND_CODEGEN_END | {iid}")

            vr.total_time_s = time.time() - variant_t0
            vr.generation_count = generated
            vr.empty_count = empty
            vr.predictions_file = str(pred_file)

            self._log(
                f"=== {config.name} DONE: "
                f"{generated}/{n} generated ({generated * 100 // n}%) | "
                f"{vr.total_time_s / 60:.1f}m ==="
            )

            # Also copy predictions to the standard predictions/ directory
            # so evaluate_predictions.py can find them
            std_pred = Path("predictions") / f"predictions_{config.name}_{pred_timestamp}.jsonl"
            shutil.copy2(pred_file, std_pred)
            self._log(f"  Predictions copied to {std_pred}")

            return vr
        finally:
            cleanup_fn = getattr(agent, "cleanup", None) if agent is not None else None
            if callable(cleanup_fn):
                try:
                    cleanup_fn()
                    self._log(f"  [{config.name}] PHASE: AGENT_CLEANUP complete")
                except Exception as exc:
                    self._log(f"  [{config.name}] PHASE: AGENT_CLEANUP warning={exc}")

    # ------------------------------------------------------------------
    # Docker evaluation
    # ------------------------------------------------------------------

    def _evaluate(self, vr: VariantResult) -> VariantResult:
        pred_path = Path(vr.predictions_file)
        if not pred_path.exists() or pred_path.stat().st_size == 0:
            self._log(f"  Skipping eval for {vr.name}: no predictions file")
            return vr

        self._log(f"=== EVALUATING: {vr.name} ===")
        self._log(f"  [{vr.name}] PHASE: EVAL_START")
        removed_containers = cleanup_stale_swebench_eval_containers()

        # Ensure Docker credential bypass
        nocreds = Path("/tmp/docker-nocreds")
        nocreds.mkdir(exist_ok=True)
        config_file = nocreds / "config.json"
        if not config_file.exists():
            config_file.write_text('{"auths":{}}')

        env = os.environ.copy()
        env["DOCKER_CONFIG"] = str(nocreds)

        eval_workers = self._resolve_eval_max_workers()
        capacity = describe_eval_capacity(instance_count=len(vr.instances))
        cmd = [
            sys.executable, "evaluate_predictions.py",
            "--file", str(pred_path),
            "--dataset", self.dataset,
            "--max-workers", str(eval_workers),
            "--force",
            "--no-update-log",
        ]

        self._log(
            "  Eval capacity: "
            f"workers={eval_workers} cpu_total={capacity['cpu_total']} "
            f"cpu_target={capacity['cpu_target']} mem_gib={capacity['mem_total_gib']} "
            f"mem_target={capacity['mem_target']}"
        )
        if removed_containers:
            self._log(f"  Removed stale SWE-bench eval containers: {', '.join(removed_containers)}")
        self._log(f"  Eval workers: {eval_workers}")
        self._log(f"  CMD: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd, env=env, capture_output=True, text=True, timeout=7200
            )
            if result.returncode != 0:
                self._log(f"  Eval FAILED (rc={result.returncode})")
                if result.stdout:
                    self._log(f"  stdout: {result.stdout[-800:]}")
                self._log(f"  stderr: {result.stderr[:500]}")
                self._log(f"  [{vr.name}] PHASE: EVAL_END status=failed")
                return vr
        except subprocess.TimeoutExpired:
            self._log(f"  Eval TIMED OUT after 2h")
            self._log(f"  [{vr.name}] PHASE: EVAL_END status=timeout")
            return vr

        eval_json = None
        for line in result.stdout.splitlines():
            if line.startswith("EVAL_JSON_PATH:"):
                candidate = line.split(":", 1)[1].strip()
                if candidate:
                    path = Path(candidate)
                    if path.exists():
                        eval_json = path
                        break

        if eval_json is None:
            self._log("  No exact eval JSON path reported; refusing result attribution")
            if result.stdout:
                self._log(f"  eval stdout tail: {result.stdout[-800:]}")
            if result.stderr:
                self._log(f"  eval stderr tail: {result.stderr[-500:]}")
            self._log(f"  [{vr.name}] PHASE: EVAL_END status=no_exact_result")
            return vr

        self._log(f"  Eval result: {eval_json.name}")

        # Copy to run directory
        dst = self.run_dir / "evaluations" / f"{vr.name}.eval.json"
        shutil.copy2(eval_json, dst)
        vr.eval_file = str(dst)
        vr.eval_ran = True

        # Parse results
        try:
            data = json.loads(eval_json.read_text())
            vr.resolved_count = data.get("resolved_instances", 0)
            vr.unresolved_count = data.get("unresolved_instances", 0)

            # Enrich per-instance results with resolved status
            instances_data = data.get("instances", {})
            for ir in vr.instances:
                inst_info = instances_data.get(ir.instance_id, {})
                ir.resolved = inst_info.get("resolved")
                if ir.resolved is True and ir.p2p_smoke_failures is not None:
                    ir.clean_resolution = ir.p2p_smoke_failures == 0

            self._log(
                f"  Resolved: {vr.resolved_count}/{len(vr.instances)} "
                f"({vr.resolved_count * 100 // max(len(vr.instances), 1)}%)"
            )
            self._log(f"  [{vr.name}] PHASE: EVAL_END status=success")
        except Exception as exc:
            self._log(f"  Failed to parse eval JSON: {exc}")
            self._log(f"  [{vr.name}] PHASE: EVAL_END status=parse_error")

        return vr

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    def _generate_report(self, instances: list) -> str:
        n = len(instances)
        variant_names = [vr.name for vr in self.results]
        lines: list[str] = []

        lines.append(f"# Benchmark Report: {self.run_name or 'unnamed'}")
        lines.append(f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"**Dataset**: {self.dataset}")
        lines.append(f"**Instances**: {n}")
        lines.append("")

        # Summary table
        lines.append("## Summary Table")
        lines.append("")
        header = "| Variant | Generation | Resolution | Time |"
        sep = "|---------|-----------|------------|------|"
        lines.append(header)
        lines.append(sep)
        for vr in self.results:
            gen_pct = vr.generation_count * 100 // max(n, 1)
            gen_str = f"{vr.generation_count}/{n} ({gen_pct}%)"
            if vr.eval_ran:
                res_pct = vr.resolved_count * 100 // max(n, 1)
                res_str = f"{vr.resolved_count}/{n} ({res_pct}%)"
            else:
                res_str = "not evaluated"
            time_str = f"{vr.total_time_s / 60:.0f}m"
            lines.append(f"| {vr.name} | {gen_str} | {res_str} | {time_str} |")
        lines.append("")

        # Loop/test diagnostics
        lines.append("## Loop and Test Diagnostics")
        lines.append("")
        lines.append("| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Graph Guard Pass | Indexed Attempted | Graph Useful | Repo Test Changed | TDD Evidence Pass | TDD Fail-Open | Runtime Fallbacks | Clean Candidates |")
        lines.append("|---------|--------------|-------------|-------------------|---------------------|------------------|-------------------|--------------|-------------------|-------------------|---------------|-------------------|------------------|")
        for vr in self.results:
            attempts_vals = [ir.attempts_used for ir in vr.instances if ir.attempts_used is not None]
            avg_attempts = (sum(attempts_vals) / len(attempts_vals)) if attempts_vals else 0.0
            loop_aborts = sum(1 for ir in vr.instances if ir.loop_abort_reason)
            f2p_vals = [ir.f2p_pass_rate for ir in vr.instances if ir.f2p_pass_rate is not None]
            avg_f2p = (sum(f2p_vals) / len(f2p_vals)) if f2p_vals else 0.0
            p2p_vals = [ir.p2p_smoke_failures for ir in vr.instances if ir.p2p_smoke_failures is not None]
            avg_p2p = (sum(p2p_vals) / len(p2p_vals)) if p2p_vals else 0.0
            graph_guard_pass = sum(1 for ir in vr.instances if ir.graph_guard_passed is True)
            indexed_attempted = sum(1 for ir in vr.instances if ir.indexed_search_attempted is True)
            graph_useful = sum(1 for ir in vr.instances if ir.graph_useful_signal is True)
            repo_test_changed = sum(1 for ir in vr.instances if ir.repo_test_changed is True)
            tdd_evidence_pass = sum(1 for ir in vr.instances if ir.tdd_evidence_complete is True)
            tdd_fail_open = sum(1 for ir in vr.instances if ir.tdd_fail_open_applied is True)
            runtime_fallbacks = sum(
                1
                for ir in vr.instances
                if bool(ir.f2p_runtime_fallback_used) or bool(ir.p2p_runtime_fallback_used)
            )
            clean_candidates = sum(1 for ir in vr.instances if ir.clean_resolution is True)
            lines.append(
                f"| {vr.name} | {avg_attempts:.2f} | {loop_aborts} | {avg_f2p:.2f} | {avg_p2p:.2f} | {graph_guard_pass} | {indexed_attempted} | {graph_useful} | {repo_test_changed} | {tdd_evidence_pass} | {tdd_fail_open} | {runtime_fallbacks} | {clean_candidates} |"
            )
        lines.append("")

        # Per-instance comparison
        lines.append("## Per-Instance Comparison")
        lines.append("")
        inst_header = "| Instance | " + " | ".join(variant_names) + " |"
        inst_sep = "|----------|" + "|".join(["------" for _ in variant_names]) + "|"
        lines.append(inst_header)
        lines.append(inst_sep)

        # Build lookup: variant_name -> instance_id -> InstanceResult
        lookup: dict[str, dict[str, InstanceResult]] = {}
        for vr in self.results:
            lookup[vr.name] = {ir.instance_id: ir for ir in vr.instances}

        for inst in instances:
            iid = inst["instance_id"]
            short_id = iid.split("__")[-1] if "__" in iid else iid
            cells = []
            for vname in variant_names:
                ir = lookup.get(vname, {}).get(iid)
                if ir is None:
                    cells.append("—")
                elif ir.patch_chars == 0:
                    cells.append("empty")
                else:
                    label = f"{ir.patch_chars} chars"
                    if ir.resolved is True:
                        label += " **resolved**"
                    elif ir.resolved is False:
                        label += " unresolved"
                    cells.append(label)
            lines.append(f"| {short_id} | " + " | ".join(cells) + " |")
        lines.append("")

        # Timing details
        lines.append("## Timing")
        lines.append("")
        for vr in self.results:
            lines.append(f"### {vr.name}")
            lines.append(f"- Total: {vr.total_time_s / 60:.1f} min")
            if vr.instances:
                avg = vr.total_time_s / len(vr.instances)
                lines.append(f"- Avg per instance: {avg:.0f}s")
            lines.append("")

        # File references
        lines.append("## Files")
        lines.append("")
        for vr in self.results:
            lines.append(f"- **{vr.name}** predictions: `{vr.predictions_file}`")
            if vr.eval_file:
                lines.append(f"- **{vr.name}** evaluation: `{vr.eval_file}`")
        lines.append(f"- Full report JSON: `{self.run_dir / 'report.json'}`")
        lines.append(f"- Progress log: `{self.progress_log}`")
        lines.append("")

        return "\n".join(lines)

    def _save_report(self, instances: list):
        # Markdown report
        md = self._generate_report(instances)
        report_md = self.run_dir / "report.md"
        report_md.write_text(md)
        self._log(f"Report saved to {report_md}")

        # JSON report (machine-readable)
        report_data = {
            "run_name": self.run_name,
            "dataset": self.dataset,
            "timestamp": datetime.now().isoformat(),
            "instance_count": len(instances),
            "instance_ids": [inst["instance_id"] for inst in instances],
            "variants": [],
        }
        for vr in self.results:
            vr_dict = {
                "name": vr.name,
                "predictions_file": vr.predictions_file,
                "eval_file": vr.eval_file,
                "total_time_s": vr.total_time_s,
                "generation_count": vr.generation_count,
                "empty_count": vr.empty_count,
                "resolved_count": vr.resolved_count,
                "unresolved_count": vr.unresolved_count,
                "eval_ran": vr.eval_ran,
                "loop_abort_count": sum(1 for ir in vr.instances if ir.loop_abort_reason),
                "avg_attempts_used": (
                    sum(ir.attempts_used for ir in vr.instances if ir.attempts_used is not None)
                    / max(1, len([ir for ir in vr.instances if ir.attempts_used is not None]))
                ),
                "avg_f2p_pass_rate": (
                    sum(ir.f2p_pass_rate for ir in vr.instances if ir.f2p_pass_rate is not None)
                    / max(1, len([ir for ir in vr.instances if ir.f2p_pass_rate is not None]))
                ),
                "avg_p2p_smoke_failures": (
                    sum(ir.p2p_smoke_failures for ir in vr.instances if ir.p2p_smoke_failures is not None)
                    / max(1, len([ir for ir in vr.instances if ir.p2p_smoke_failures is not None]))
                ),
                "clean_resolution_count": sum(1 for ir in vr.instances if ir.clean_resolution is True),
                "instances": [asdict(ir) for ir in vr.instances],
            }
            report_data["variants"].append(vr_dict)

        report_json = self.run_dir / "report.json"
        report_json.write_text(json.dumps(report_data, indent=2))
        self._log(f"JSON report saved to {report_json}")

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self):
        self._log(f"=== BENCHMARK START: {self.run_name or 'unnamed'} ===")
        self._log(f"Dataset: {self.dataset}")
        self._log(f"Variants: {[v.name for v in self.variants]}")
        self._log(f"Skip eval: {self.skip_eval}")
        self._log(f"Eval workers: {self._resolve_eval_max_workers()}")
        self._log(f"Run dir: {self.run_dir}")

        # Save config
        variants_effective_controls = [
            {
                "name": variant.name,
                **self._effective_variant_controls(variant),
            }
            for variant in self.variants
        ]
        config = {
            "dataset": self.dataset,
            "variants": [asdict(v) for v in self.variants],
            "variants_effective_controls": variants_effective_controls,
            "limit": self.limit,
            "instance_ids": self.instance_ids,
            "skip_eval": self.skip_eval,
            "max_workers": self.max_workers,
            "eval_max_workers": self.eval_max_workers,
            "eval_max_workers_effective": self._resolve_eval_max_workers(),
            "run_name": self.run_name,
            "model": self.model,
            "max_attempts": self.max_attempts,
            "step_limit": self.step_limit,
            "loop_policy": self.loop_policy,
            "max_fix_iterations": self.max_fix_iterations,
            "patch_compile_gate": self.patch_compile_gate,
            "test_signal_mode": self.test_signal_mode,
            "retry_policy": self.retry_policy,
            "enforce_tdd_test_first": self.enforce_tdd_test_first,
            "graph_guard_mode": self.graph_guard_mode,
            "strict_tdd_evidence": self.strict_tdd_evidence,
            "test_change_policy": self.test_change_policy,
            "strict_tdd_infra_policy": self.strict_tdd_infra_policy,
            "strict_tdd_infra_retry_budget": self.strict_tdd_infra_retry_budget,
            "indexed_signal_mode": self.indexed_signal_mode,
            "graphrag_tool_mode": self.graphrag_tool_mode,
            "graphrag_tool_mode_effective_for_benchmark_variants": (
                "local"
                if any(variant.use_graphrag for variant in self.variants)
                else self.graphrag_tool_mode
            ),
            "instance_timeout_sec": self.instance_timeout_sec,
            "isolate_instances": self.isolate_instances,
            "test_signal_mode_explicit": self.test_signal_mode_explicit,
            "retry_policy_explicit": self.retry_policy_explicit,
            "enforce_tdd_test_first_explicit": self.enforce_tdd_test_first_explicit,
            "graph_guard_mode_explicit": self.graph_guard_mode_explicit,
            "strict_tdd_evidence_explicit": self.strict_tdd_evidence_explicit,
            "test_change_policy_explicit": self.test_change_policy_explicit,
            "strict_tdd_infra_policy_explicit": self.strict_tdd_infra_policy_explicit,
            "strict_tdd_infra_retry_budget_explicit": self.strict_tdd_infra_retry_budget_explicit,
            "indexed_signal_mode_explicit": self.indexed_signal_mode_explicit,
            "step_limit_explicit": self.step_limit_explicit,
            "max_fix_iterations_explicit": self.max_fix_iterations_explicit,
        }
        (self.run_dir / "config.json").write_text(json.dumps(config, indent=2))

        # Load instances
        instances = self._load_instances()
        n = len(instances)
        self._log(f"Loaded {n} instances")

        if n == 0:
            self._log("No instances to process. Exiting.")
            return

        if self.instance_ids:
            self._log(f"Instance IDs: {[i['instance_id'] for i in instances]}")

        # Run each variant
        for config in self.variants:
            vr = self._run_variant(config, instances)

            if not self.skip_eval:
                vr = self._evaluate(vr)

            self.results.append(vr)

        # Generate reports
        self._save_report(instances)

        # Print summary
        self._log("")
        self._log("=" * 60)
        self._log("BENCHMARK COMPLETE")
        self._log("=" * 60)
        for vr in self.results:
            gen_pct = vr.generation_count * 100 // max(n, 1)
            res_str = ""
            if vr.eval_ran:
                res_pct = vr.resolved_count * 100 // max(n, 1)
                res_str = f" | resolved: {vr.resolved_count}/{n} ({res_pct}%)"
            self._log(
                f"  {vr.name}: generated {vr.generation_count}/{n} ({gen_pct}%)"
                f"{res_str} | {vr.total_time_s / 60:.1f}m"
            )
        self._log(f"\nFull report: {self.run_dir / 'report.md'}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    raw_argv = sys.argv[1:]
    parser = argparse.ArgumentParser(
        description="Run SWE-bench across qwen-mini variants and auto-evaluate",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_benchmark.py --dataset princeton-nlp/SWE-bench_Verified --limit 10 --variants vanilla tdd_prompt
  python run_benchmark.py --dataset princeton-nlp/SWE-bench_Verified --instance-ids astropy__astropy-12907 --variants vanilla tdd_prompt --skip-eval
  python run_benchmark.py --dataset princeton-nlp/SWE-bench_Verified --instance-ids-file failed.txt --variants graphrag_tdd
""",
    )

    # Instance selection (mutually exclusive)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--limit", type=int, help="First N instances from dataset")
    group.add_argument(
        "--instance-ids", nargs="+",
        help="Specific instance IDs to run",
    )
    group.add_argument(
        "--instance-ids-file", type=str,
        help="File with one instance ID per line",
    )

    parser.add_argument(
        "--dataset", type=str,
        default="princeton-nlp/SWE-bench_Verified",
        help="HuggingFace dataset name (default: SWE-bench_Verified)",
    )
    parser.add_argument(
        "--variants", nargs="+",
        choices=list(VARIANT_REGISTRY.keys()),
        default=["vanilla"],
        help="Variants to run (default: vanilla)",
    )
    parser.add_argument(
        "--skip-eval", action="store_true",
        help="Skip Docker evaluation after generation",
    )
    parser.add_argument(
        "--max-workers", type=int, default=2,
        help="Legacy evaluation worker hint; use --eval-max-workers for explicit control",
    )
    parser.add_argument(
        "--eval-max-workers", type=int, default=None,
        help="Docker evaluation parallelism (default: auto, based on CPU count)",
    )
    parser.add_argument(
        "--run-name", type=str, default="",
        help="Human-readable label for this run",
    )
    parser.add_argument(
        "--model", type=str, default=None,
        help="Model alias/name to pass through to the selected backend",
    )
    parser.add_argument(
        "--max-attempts", type=int, default=3,
        help="Max attempts per instance for qwen-mini (default: 3)",
    )
    parser.add_argument(
        "--step-limit", type=int, default=30,
        help="Max steps per attempt for qwen-mini (default: 30)",
    )
    parser.add_argument(
        "--loop-policy", type=str, choices=["off", "warn", "strict"], default="strict",
        help="Loop control policy for qwen-mini (default: strict)",
    )
    parser.add_argument(
        "--max-fix-iterations", type=int, default=0,
        help="Max iterative test-fix rounds for tdd_loop/graphrag_tdd (default: 0, EXP-012d-like)",
    )
    parser.add_argument(
        "--patch-compile-gate", type=str, choices=["on", "off"], default="on",
        help="Compile changed Python files before accepting qwen-mini patches (default: on)",
    )
    parser.add_argument(
        "--test-signal-mode", type=str, choices=["off", "soft", "hard"], default="hard",
        help="How local F2P/P2P signals influence qwen-mini attempt ranking (default: hard)",
    )
    parser.add_argument(
        "--retry-policy", type=str, choices=["fixed", "adaptive"], default="fixed",
        help="Retry strategy for qwen-mini attempts (default: fixed)",
    )
    parser.add_argument(
        "--enforce-tdd-test-first", type=str, choices=["on", "off"], default="on",
        help="Require explicit test-first appendix in qwen-mini TDD mode (default: on)",
    )
    parser.add_argument(
        "--graph-guard-mode", type=str, choices=["either", "both", "indexed_only"], default="either",
        help="GraphRAG candidate guard mode (default: either)",
    )
    parser.add_argument(
        "--strict-tdd-evidence", type=str, choices=["on", "off"], default="off",
        help="Require strict reproduce->verify->smoke evidence for TDD candidates (default: off)",
    )
    parser.add_argument(
        "--test-change-policy", type=str, choices=["any_test_like", "repo_tests_only"], default="any_test_like",
        help="Policy for counting unit-test file changes in graph guard (default: any_test_like)",
    )
    parser.add_argument(
        "--strict-tdd-infra-policy", type=str, choices=["fail_closed", "retry_then_fail_open", "fail_open"], default="fail_closed",
        help="Strict TDD evidence behavior on infra-unreliable pytest signals (default: fail_closed; supports fail_open)",
    )
    parser.add_argument(
        "--strict-tdd-infra-retry-budget", type=int, default=2,
        help="Extra retry budget for infra-unreliable strict TDD checks (default: 2)",
    )
    parser.add_argument(
        "--indexed-signal-mode", type=str, choices=["attempted_query", "successful_query"], default="attempted_query",
        help="How indexed-search usage is counted for graph guard (default: attempted_query)",
    )
    parser.add_argument(
        "--graphrag-tool-mode", type=str, choices=["local", "mcp", "auto"],
        default=os.getenv("GRAPH_RAG_TOOL_MODE", "local"),
        help="GraphRAG transport mode (default: local; use mcp for external server mode)",
    )
    parser.add_argument(
        "--instance-timeout-sec", type=int, default=1200,
        help="Hard timeout per instance in seconds (default: 1200, set 0 to disable)",
    )
    parser.add_argument(
        "--isolate-instances", type=str, choices=["on", "off"], default="off",
        help="Run each instance in a worker subprocess for hard-kill isolation (default: off, live logs)",
    )

    args = parser.parse_args()

    # Resolve instance IDs
    instance_ids = args.instance_ids
    if args.instance_ids_file:
        p = Path(args.instance_ids_file)
        if not p.exists():
            print(f"Error: file not found: {p}")
            sys.exit(1)
        instance_ids = [
            line.strip() for line in p.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    # Need either --limit or --instance-ids
    if args.limit is None and instance_ids is None:
        parser.error("Specify --limit, --instance-ids, or --instance-ids-file")

    # Build variant configs
    variant_configs = [VARIANT_REGISTRY[name] for name in args.variants]
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
    max_workers_explicit = "--max-workers" in raw_argv

    runner = BenchmarkRunner(
        dataset=args.dataset,
        variants=variant_configs,
        limit=args.limit,
        instance_ids=instance_ids,
        skip_eval=args.skip_eval,
        max_workers=args.max_workers,
        eval_max_workers=args.eval_max_workers,
        run_name=args.run_name,
        model=args.model,
        max_attempts=args.max_attempts,
        step_limit=args.step_limit,
        loop_policy=args.loop_policy,
        max_fix_iterations=args.max_fix_iterations,
        patch_compile_gate=args.patch_compile_gate,
        test_signal_mode=args.test_signal_mode,
        retry_policy=args.retry_policy,
        enforce_tdd_test_first=args.enforce_tdd_test_first,
        graph_guard_mode=args.graph_guard_mode,
        strict_tdd_evidence=args.strict_tdd_evidence,
        test_change_policy=args.test_change_policy,
        strict_tdd_infra_policy=args.strict_tdd_infra_policy,
        strict_tdd_infra_retry_budget=args.strict_tdd_infra_retry_budget,
        indexed_signal_mode=args.indexed_signal_mode,
        graphrag_tool_mode=args.graphrag_tool_mode,
        instance_timeout_sec=args.instance_timeout_sec,
        isolate_instances=args.isolate_instances,
        test_signal_mode_explicit=test_signal_mode_explicit,
        retry_policy_explicit=retry_policy_explicit,
        enforce_tdd_test_first_explicit=enforce_tdd_test_first_explicit,
        graph_guard_mode_explicit=graph_guard_mode_explicit,
        strict_tdd_evidence_explicit=strict_tdd_evidence_explicit,
        test_change_policy_explicit=test_change_policy_explicit,
        strict_tdd_infra_policy_explicit=strict_tdd_infra_policy_explicit,
        strict_tdd_infra_retry_budget_explicit=strict_tdd_infra_retry_budget_explicit,
        indexed_signal_mode_explicit=indexed_signal_mode_explicit,
        step_limit_explicit=step_limit_explicit,
        max_fix_iterations_explicit=max_fix_iterations_explicit,
        max_workers_explicit=max_workers_explicit,
    )
    runner.run()


if __name__ == "__main__":
    main()
