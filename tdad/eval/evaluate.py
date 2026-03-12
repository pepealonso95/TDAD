"""Docker evaluation and comparison report generation."""

import json
import logging
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


def evaluate_predictions(
    predictions_file: Path,
    dataset: str,
    run_dir: Path,
    max_workers: int = 2,
) -> Optional[Dict[str, Any]]:
    """Run swebench Docker evaluation on a predictions file.

    Args:
        predictions_file: Path to the .jsonl predictions file.
        dataset: HuggingFace dataset name.
        run_dir: Directory for evaluation outputs.
        max_workers: Parallel Docker containers.

    Returns:
        Dict with resolved_ids, total, resolved_count, or None on failure.
    """
    eval_dir = run_dir / "evaluations"
    eval_dir.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    run_id = f"eval_{timestamp}"

    cmd = [
        sys.executable, "-m", "swebench.harness.run_evaluation",
        "--predictions_path", str(predictions_file),
        "--dataset_name", dataset,
        "--split", "test",
        "--run_id", run_id,
        "--max_workers", str(max_workers),
        "--timeout", "600",
        "--cache_level", "env",
        "--report_dir", str(eval_dir),
    ]

    logger.info("Running evaluation: %s", " ".join(cmd))
    print(f"\nRunning Docker evaluation for {predictions_file.name}...")
    print(f"Command: {' '.join(cmd)}")

    try:
        start_time = time.time()
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=str(eval_dir),
        )

        output_lines = []
        for line in iter(process.stdout.readline, ""):
            print(line, end="")
            output_lines.append(line)

        process.wait()
        eval_time = time.time() - start_time

        if process.returncode != 0:
            logger.error("Evaluation failed with exit code %d", process.returncode)
            return None

        # Parse results from JSON report
        results = _parse_eval_results(eval_dir, run_id, output_lines)
        if results:
            results["eval_time"] = eval_time
        return results

    except Exception as exc:
        logger.error("Evaluation error: %s", exc, exc_info=True)
        return None


def _parse_eval_results(
    eval_dir: Path,
    run_id: str,
    output_lines: List[str],
) -> Optional[Dict[str, Any]]:
    """Parse evaluation results from JSON report or output text."""
    # Try to find the JSON report file
    for json_file in eval_dir.glob(f"*.{run_id}.json"):
        try:
            with open(json_file) as f:
                data = json.load(f)
            return {
                "resolved_ids": data.get("resolved_ids", []),
                "resolved_count": data.get("resolved_instances", len(data.get("resolved_ids", []))),
                "total": data.get("total_instances", 0),
                "json_path": str(json_file),
            }
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to parse eval JSON %s: %s", json_file, exc)

    # Fallback: regex on output
    output_text = "".join(output_lines)
    patterns = [
        r"(\d+) of (\d+) instances",
        r"(\d+)/(\d+) resolved",
        r"resolved (\d+) of (\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, output_text)
        if match:
            resolved = int(match.group(1))
            total = int(match.group(2))
            return {
                "resolved_ids": [],
                "resolved_count": resolved,
                "total": total,
                "json_path": None,
            }

    logger.warning("Could not parse evaluation results")
    return None


def generate_report(
    baseline_results: Optional[Dict[str, Any]],
    tdad_results: Optional[Dict[str, Any]],
    baseline_predictions: List[dict],
    tdad_predictions: List[dict],
    instances: List[dict],
    run_dir: Path,
) -> None:
    """Generate comparison report (report.md + report.json).

    Args:
        baseline_results: Eval results for baseline (or None if not run/failed).
        tdad_results: Eval results for tdad (or None if not run/failed).
        baseline_predictions: List of baseline prediction dicts.
        tdad_predictions: List of tdad prediction dicts.
        instances: Original SWE-bench instances.
        run_dir: Output directory.
    """
    report_data = {}

    for label, predictions, results in [
        ("baseline", baseline_predictions, baseline_results),
        ("tdad", tdad_predictions, tdad_results),
    ]:
        if not predictions:
            continue

        total = len(predictions)
        non_empty = sum(1 for p in predictions if p.get("model_patch", "").strip())
        generation_rate = (non_empty / total * 100) if total else 0.0

        mode_data = {
            "total_instances": total,
            "patches_generated": non_empty,
            "generation_rate": round(generation_rate, 2),
        }

        if results:
            resolved = results.get("resolved_count", 0)
            resolution_rate = (resolved / total * 100) if total else 0.0
            mode_data["resolved_count"] = resolved
            mode_data["resolution_rate"] = round(resolution_rate, 2)
            mode_data["eval_time"] = results.get("eval_time")
            mode_data["resolved_ids"] = results.get("resolved_ids", [])

        report_data[label] = mode_data

    # Compute deltas if both modes present
    if "baseline" in report_data and "tdad" in report_data:
        b = report_data["baseline"]
        t = report_data["tdad"]
        report_data["delta"] = {
            "generation_rate": round(t["generation_rate"] - b["generation_rate"], 2),
        }
        if "resolution_rate" in b and "resolution_rate" in t:
            report_data["delta"]["resolution_rate"] = round(
                t["resolution_rate"] - b["resolution_rate"], 2
            )

    # Per-instance breakdown
    instance_map = {i["instance_id"]: i for i in instances}
    baseline_map = {p["instance_id"]: p for p in baseline_predictions}
    tdad_map = {p["instance_id"]: p for p in tdad_predictions}
    baseline_resolved = set(
        (baseline_results or {}).get("resolved_ids", [])
    )
    tdad_resolved = set(
        (tdad_results or {}).get("resolved_ids", [])
    )

    breakdown = []
    all_ids = sorted(set(list(baseline_map.keys()) + list(tdad_map.keys())))
    for iid in all_ids:
        entry = {"instance_id": iid, "repo": instance_map.get(iid, {}).get("repo", "")}
        if iid in baseline_map:
            entry["baseline_patch"] = bool(baseline_map[iid].get("model_patch", "").strip())
            entry["baseline_resolved"] = iid in baseline_resolved
        if iid in tdad_map:
            entry["tdad_patch"] = bool(tdad_map[iid].get("model_patch", "").strip())
            entry["tdad_resolved"] = iid in tdad_resolved
        breakdown.append(entry)

    report_data["per_instance"] = breakdown

    # Write JSON
    json_path = run_dir / "report.json"
    with open(json_path, "w") as f:
        json.dump(report_data, f, indent=2)
    logger.info("Report JSON written to %s", json_path)

    # Write Markdown
    md_path = run_dir / "report.md"
    md_path.write_text(_format_markdown_report(report_data))
    logger.info("Report Markdown written to %s", md_path)

    print(f"\nReport written to:\n  {json_path}\n  {md_path}")


def _format_markdown_report(data: dict) -> str:
    """Format the report data as a Markdown document."""
    lines = ["# SWE-bench Evaluation Report\n"]

    # Summary table
    lines.append("## Summary\n")
    lines.append("| Metric | Baseline | TDAD | Delta |")
    lines.append("|--------|----------|------|-------|")

    b = data.get("baseline", {})
    t = data.get("tdad", {})
    d = data.get("delta", {})

    def _fmt(val, suffix="%"):
        return f"{val}{suffix}" if val is not None else "N/A"

    lines.append(
        f"| Instances | {b.get('total_instances', 'N/A')} "
        f"| {t.get('total_instances', 'N/A')} | |"
    )
    lines.append(
        f"| Generation Rate | {_fmt(b.get('generation_rate'))} "
        f"| {_fmt(t.get('generation_rate'))} "
        f"| {_fmt(d.get('generation_rate'), 'pp')} |"
    )
    if "resolution_rate" in b or "resolution_rate" in t:
        lines.append(
            f"| Resolution Rate | {_fmt(b.get('resolution_rate'))} "
            f"| {_fmt(t.get('resolution_rate'))} "
            f"| {_fmt(d.get('resolution_rate'), 'pp')} |"
        )

    # Per-instance breakdown
    breakdown = data.get("per_instance", [])
    if breakdown:
        lines.append("\n## Per-Instance Breakdown\n")
        lines.append("| Instance | Repo | BL Patch | BL Resolved | TDAD Patch | TDAD Resolved |")
        lines.append("|----------|------|----------|-------------|------------|---------------|")
        for entry in breakdown:
            iid = entry["instance_id"]
            repo = entry.get("repo", "")
            bl_patch = "Y" if entry.get("baseline_patch") else "N" if "baseline_patch" in entry else "-"
            bl_res = "Y" if entry.get("baseline_resolved") else "N" if "baseline_resolved" in entry else "-"
            td_patch = "Y" if entry.get("tdad_patch") else "N" if "tdad_patch" in entry else "-"
            td_res = "Y" if entry.get("tdad_resolved") else "N" if "tdad_resolved" in entry else "-"
            lines.append(f"| {iid} | {repo} | {bl_patch} | {bl_res} | {td_patch} | {td_res} |")

    return "\n".join(lines) + "\n"
