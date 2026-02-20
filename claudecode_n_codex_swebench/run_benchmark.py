#!/usr/bin/env python3
"""
Multi-variant benchmark runner with auto-evaluation and report generation.

Runs the same SWE-bench instances across qwen-mini variants (vanilla, tdd_loop,
graphrag_tdd), automatically evaluates with Docker, and produces a comparison
report.

Usage:
    # Vanilla + TDD-loop on 10 instances
    python run_benchmark.py --dataset princeton-nlp/SWE-bench_Verified \\
        --limit 10 --variants vanilla tdd_loop

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
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import jsonlines

from code_swe_agent import CodeSWEAgent, load_cached_dataset


# ---------------------------------------------------------------------------
# Variant definitions
# ---------------------------------------------------------------------------

@dataclass
class VariantConfig:
    name: str
    backend: str = "qwen-mini"
    tdd_mode: bool = False
    use_graphrag: bool = False


VARIANT_REGISTRY: dict[str, VariantConfig] = {
    "vanilla": VariantConfig("vanilla"),
    "tdd_loop": VariantConfig("tdd_loop", tdd_mode=True),
    "graphrag_tdd": VariantConfig("graphrag_tdd", tdd_mode=True, use_graphrag=True),
    # Backward-compatible aliases
    "baseline": VariantConfig("vanilla"),
    "tdd": VariantConfig("tdd_loop", tdd_mode=True),
    "graphrag": VariantConfig("graphrag_tdd", tdd_mode=True, use_graphrag=True),
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
        run_name: str = "",
        max_attempts: Optional[int] = None,
        step_limit: Optional[int] = None,
        loop_policy: str = "strict",
        max_fix_iterations: int = 2,
        patch_compile_gate: str = "on",
    ):
        self.dataset = dataset
        self.variants = variants
        self.limit = limit
        self.instance_ids = instance_ids
        self.skip_eval = skip_eval
        self.max_workers = max_workers
        self.run_name = run_name
        self.max_attempts = max_attempts
        self.step_limit = step_limit
        self.loop_policy = loop_policy
        self.max_fix_iterations = max_fix_iterations
        self.patch_compile_gate = patch_compile_gate

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
        print(line)
        with open(self.progress_log, "a") as f:
            f.write(line + "\n")

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

    def _run_variant(self, config: VariantConfig, instances: list) -> VariantResult:
        vr = VariantResult(name=config.name)
        n = len(instances)
        self._log(f"=== VARIANT: {config.name} ({n} instances) ===")

        if config.use_graphrag:
            from code_swe_agent_graphrag import GraphRAGCodeSWEAgent
            agent = GraphRAGCodeSWEAgent(
                backend=config.backend,
                tdd_mode=config.tdd_mode,
                max_attempts=self.max_attempts,
                step_limit=self.step_limit,
                loop_policy=self.loop_policy,
                max_fix_iterations=self.max_fix_iterations,
                patch_compile_gate=(self.patch_compile_gate == "on"),
            )
        else:
            agent = CodeSWEAgent(
                backend=config.backend,
                tdd_mode=config.tdd_mode,
                max_attempts=self.max_attempts,
                step_limit=self.step_limit,
                loop_policy=self.loop_policy,
                max_fix_iterations=self.max_fix_iterations,
                patch_compile_gate=(self.patch_compile_gate == "on"),
            )

        # Initialize prediction file in the run directory
        pred_file = self.run_dir / "predictions" / f"{config.name}.jsonl"
        if pred_file.exists():
            pred_file.unlink()
        agent.pred_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        agent.pred_file = pred_file

        generated = 0
        empty = 0
        variant_t0 = time.time()

        for i, instance in enumerate(instances, 1):
            iid = instance["instance_id"]
            t0 = time.time()

            try:
                prediction = agent.process_instance(instance)
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
            )
            vr.instances.append(ir)

            # Save prediction incrementally
            agent._save_predictions(prediction)

            # Progress line
            total_elapsed = time.time() - variant_t0
            self._log(
                f"  [{config.name}] {i}/{n} done | "
                f"{generated} patches | {empty} empty | "
                f"{iid}: {patch_chars} chars ({elapsed:.0f}s) | "
                f"total: {total_elapsed / 60:.1f}m"
            )

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
        std_pred = Path("predictions") / f"predictions_{config.name}_{agent.pred_timestamp}.jsonl"
        shutil.copy2(pred_file, std_pred)
        self._log(f"  Predictions copied to {std_pred}")

        return vr

    # ------------------------------------------------------------------
    # Docker evaluation
    # ------------------------------------------------------------------

    def _evaluate(self, vr: VariantResult) -> VariantResult:
        pred_path = Path(vr.predictions_file)
        if not pred_path.exists() or pred_path.stat().st_size == 0:
            self._log(f"  Skipping eval for {vr.name}: no predictions file")
            return vr

        self._log(f"=== EVALUATING: {vr.name} ===")

        # Ensure Docker credential bypass
        nocreds = Path("/tmp/docker-nocreds")
        nocreds.mkdir(exist_ok=True)
        config_file = nocreds / "config.json"
        if not config_file.exists():
            config_file.write_text('{"auths":{}}')

        env = os.environ.copy()
        env["DOCKER_CONFIG"] = str(nocreds)

        cmd = [
            sys.executable, "evaluate_predictions.py",
            "--file", str(pred_path),
            "--dataset", self.dataset,
            "--max-workers", str(self.max_workers),
            "--force",
            "--no-update-log",
        ]

        self._log(f"  CMD: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd, env=env, capture_output=True, text=True, timeout=7200
            )
            if result.returncode != 0:
                self._log(f"  Eval FAILED (rc={result.returncode})")
                self._log(f"  stderr: {result.stderr[:500]}")
                return vr
        except subprocess.TimeoutExpired:
            self._log(f"  Eval TIMED OUT after 2h")
            return vr

        # Find the most recent eval result
        eval_jsons = sorted(
            Path("evaluation_results").glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not eval_jsons:
            self._log("  No eval JSON found")
            return vr

        eval_json = eval_jsons[0]
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
        except Exception as exc:
            self._log(f"  Failed to parse eval JSON: {exc}")

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
        lines.append("| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Clean Candidates |")
        lines.append("|---------|--------------|-------------|-------------------|---------------------|------------------|")
        for vr in self.results:
            attempts_vals = [ir.attempts_used for ir in vr.instances if ir.attempts_used is not None]
            avg_attempts = (sum(attempts_vals) / len(attempts_vals)) if attempts_vals else 0.0
            loop_aborts = sum(1 for ir in vr.instances if ir.loop_abort_reason)
            f2p_vals = [ir.f2p_pass_rate for ir in vr.instances if ir.f2p_pass_rate is not None]
            avg_f2p = (sum(f2p_vals) / len(f2p_vals)) if f2p_vals else 0.0
            p2p_vals = [ir.p2p_smoke_failures for ir in vr.instances if ir.p2p_smoke_failures is not None]
            avg_p2p = (sum(p2p_vals) / len(p2p_vals)) if p2p_vals else 0.0
            clean_candidates = sum(1 for ir in vr.instances if ir.clean_resolution is True)
            lines.append(
                f"| {vr.name} | {avg_attempts:.2f} | {loop_aborts} | {avg_f2p:.2f} | {avg_p2p:.2f} | {clean_candidates} |"
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
        self._log(f"Run dir: {self.run_dir}")

        # Save config
        config = {
            "dataset": self.dataset,
            "variants": [asdict(v) for v in self.variants],
            "limit": self.limit,
            "instance_ids": self.instance_ids,
            "skip_eval": self.skip_eval,
            "max_workers": self.max_workers,
            "run_name": self.run_name,
            "max_attempts": self.max_attempts,
            "step_limit": self.step_limit,
            "loop_policy": self.loop_policy,
            "max_fix_iterations": self.max_fix_iterations,
            "patch_compile_gate": self.patch_compile_gate,
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
    parser = argparse.ArgumentParser(
        description="Run SWE-bench across qwen-mini variants and auto-evaluate",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_benchmark.py --dataset princeton-nlp/SWE-bench_Verified --limit 10 --variants vanilla tdd_loop
  python run_benchmark.py --dataset princeton-nlp/SWE-bench_Verified --instance-ids astropy__astropy-12907 --variants vanilla tdd_loop --skip-eval
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
        help="Docker evaluation parallelism (default: 2)",
    )
    parser.add_argument(
        "--run-name", type=str, default="",
        help="Human-readable label for this run",
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

    runner = BenchmarkRunner(
        dataset=args.dataset,
        variants=variant_configs,
        limit=args.limit,
        instance_ids=instance_ids,
        skip_eval=args.skip_eval,
        max_workers=args.max_workers,
        run_name=args.run_name,
        max_attempts=args.max_attempts,
        step_limit=args.step_limit,
        loop_policy=args.loop_policy,
        max_fix_iterations=args.max_fix_iterations,
        patch_compile_gate=args.patch_compile_gate,
    )
    runner.run()


if __name__ == "__main__":
    main()
