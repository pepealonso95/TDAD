#!/usr/bin/env python3
"""
Reconstruct SWE-bench evaluation artifacts from existing run logs.

This is useful when Docker evaluation completed per-instance runs, but aggregate
JSON/report files were not materialized for the run checkpoint.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


RESULT_RE_TEMPLATE = r"Result for {instance_id}: resolved: (True|False)"
BOOL_RE = r"(True|False)"


@dataclass
class InstanceResult:
    instance_id: str
    resolved: Optional[bool]
    patch_exists: Optional[bool]
    patch_successfully_applied: Optional[bool]
    parse_status: str
    source_log: Optional[str]
    source_report: Optional[str]

    def as_report_dict(self) -> Dict[str, Dict[str, object]]:
        """Return report.json-compatible structure for a single instance."""
        return {
            self.instance_id: {
                "resolved": self.resolved,
                "patch_exists": self.patch_exists,
                "patch_successfully_applied": self.patch_successfully_applied,
                "reconstructed_from_log": True,
            }
        }


def parse_bool_token(token: str) -> bool:
    return token == "True"


def read_predictions(predictions_path: Path) -> List[Dict[str, object]]:
    if not predictions_path.exists():
        raise FileNotFoundError(f"Predictions file not found: {predictions_path}")

    rows: List[Dict[str, object]] = []
    with predictions_path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON on line {i} in {predictions_path}: {exc}"
                ) from exc
            rows.append(obj)
    return rows


def parse_instance_from_report_json(
    report_path: Path, instance_id: str
) -> Optional[InstanceResult]:
    if not report_path.exists():
        return None

    try:
        with report_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return InstanceResult(
            instance_id=instance_id,
            resolved=None,
            patch_exists=None,
            patch_successfully_applied=None,
            parse_status="invalid_report_json",
            source_log=None,
            source_report=str(report_path),
        )

    record = data.get(instance_id)
    if not isinstance(record, dict):
        return InstanceResult(
            instance_id=instance_id,
            resolved=None,
            patch_exists=None,
            patch_successfully_applied=None,
            parse_status="missing_instance_in_report",
            source_log=None,
            source_report=str(report_path),
        )

    return InstanceResult(
        instance_id=instance_id,
        resolved=record.get("resolved"),
        patch_exists=record.get("patch_exists"),
        patch_successfully_applied=record.get("patch_successfully_applied"),
        parse_status="ok_report_json",
        source_log=None,
        source_report=str(report_path),
    )


def parse_instance_from_run_log(
    run_log_path: Path, instance_id: str, patch_from_prediction: Optional[bool]
) -> InstanceResult:
    if not run_log_path.exists():
        return InstanceResult(
            instance_id=instance_id,
            resolved=None,
            patch_exists=patch_from_prediction,
            patch_successfully_applied=None,
            parse_status="missing_run_log",
            source_log=None,
            source_report=None,
        )

    text = run_log_path.read_text(encoding="utf-8", errors="ignore")

    resolved_matches = re.findall(
        RESULT_RE_TEMPLATE.format(instance_id=re.escape(instance_id)), text
    )
    resolved = parse_bool_token(resolved_matches[-1]) if resolved_matches else None

    patch_applied_matches = re.findall(
        rf"'patch_successfully_applied':\s*{BOOL_RE}", text
    )
    patch_applied = (
        parse_bool_token(patch_applied_matches[-1]) if patch_applied_matches else None
    )

    patch_exists_matches = re.findall(rf"'patch_exists':\s*{BOOL_RE}", text)
    patch_exists = (
        parse_bool_token(patch_exists_matches[-1]) if patch_exists_matches else None
    )
    if patch_exists is None:
        patch_none_matches = re.findall(rf"'patch_is_None':\s*{BOOL_RE}", text)
        if patch_none_matches:
            patch_exists = not parse_bool_token(patch_none_matches[-1])
    if patch_exists is None:
        patch_exists = patch_from_prediction

    status = "ok_run_log" if resolved is not None else "missing_resolution_marker"
    return InstanceResult(
        instance_id=instance_id,
        resolved=resolved,
        patch_exists=patch_exists,
        patch_successfully_applied=patch_applied,
        parse_status=status,
        source_log=str(run_log_path),
        source_report=None,
    )


def build_instance_results(
    predictions_rows: List[Dict[str, object]],
    eval_log_dir: Path,
) -> List[InstanceResult]:
    results: List[InstanceResult] = []

    for row in predictions_rows:
        instance_id = row.get("instance_id")
        if not isinstance(instance_id, str) or not instance_id:
            continue

        patch_text = row.get("prediction")
        if patch_text is None:
            patch_text = row.get("model_patch")
        patch_exists_from_predictions = (
            bool(patch_text.strip()) if isinstance(patch_text, str) else None
        )

        instance_dir = eval_log_dir / instance_id
        if not instance_dir.exists():
            results.append(
                InstanceResult(
                    instance_id=instance_id,
                    resolved=None,
                    patch_exists=patch_exists_from_predictions,
                    patch_successfully_applied=None,
                    parse_status="missing_instance_dir",
                    source_log=None,
                    source_report=None,
                )
            )
            continue

        report_result = parse_instance_from_report_json(
            instance_dir / "report.json", instance_id
        )
        if report_result and report_result.parse_status == "ok_report_json":
            if report_result.patch_exists is None:
                report_result.patch_exists = patch_exists_from_predictions
            if report_result.source_log is None:
                run_log = instance_dir / "run_instance.log"
                if run_log.exists():
                    report_result.source_log = str(run_log)
            results.append(report_result)
            continue

        log_result = parse_instance_from_run_log(
            instance_dir / "run_instance.log", instance_id, patch_exists_from_predictions
        )
        if report_result and report_result.parse_status != "ok_report_json":
            # Preserve report parsing issue if run log also fails.
            if log_result.parse_status == "missing_resolution_marker":
                log_result.parse_status = report_result.parse_status
            log_result.source_report = report_result.source_report
        results.append(log_result)

    return results


def aggregate_results(
    results: List[InstanceResult],
    model_name: str,
    run_id: str,
    dataset: str,
    predictions_path: Path,
    eval_log_dir: Path,
) -> Dict[str, object]:
    total_instances = len(results)
    resolved_instances = sum(1 for r in results if r.resolved is True)
    unresolved_instances = sum(1 for r in results if r.resolved is False)
    evaluated_instances = resolved_instances + unresolved_instances
    incomplete_instances = [r.instance_id for r in results if r.resolved is None]
    resolution_rate = (resolved_instances / total_instances) if total_instances else 0.0

    return {
        "run_id": run_id,
        "model": model_name,
        "dataset": dataset,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "predictions_path": str(predictions_path),
            "eval_log_dir": str(eval_log_dir),
        },
        "total_instances": total_instances,
        "evaluated_instances": evaluated_instances,
        "resolved_instances": resolved_instances,
        "unresolved_instances": unresolved_instances,
        "incomplete_instances": incomplete_instances,
        "resolution_rate": resolution_rate,
        "instances": {
            r.instance_id: {
                "resolved": r.resolved,
                "patch_exists": r.patch_exists,
                "patch_successfully_applied": r.patch_successfully_applied,
                "parse_status": r.parse_status,
                "source_log": r.source_log,
                "source_report": r.source_report,
            }
            for r in results
        },
    }


def write_csv(results: List[InstanceResult], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["instance_id", "resolved", "source_log", "parse_status"]
        )
        writer.writeheader()
        for r in results:
            writer.writerow(
                {
                    "instance_id": r.instance_id,
                    "resolved": r.resolved,
                    "source_log": r.source_log or "",
                    "parse_status": r.parse_status,
                }
            )


def write_json(output: Dict[str, object], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
        f.write("\n")


def write_reconstructed_report_json(eval_log_dir: Path, results: List[InstanceResult]) -> int:
    written = 0
    for r in results:
        instance_dir = eval_log_dir / r.instance_id
        if not instance_dir.exists():
            continue
        report_path = instance_dir / "report.json"
        with report_path.open("w", encoding="utf-8") as f:
            json.dump(r.as_report_dict(), f, indent=4)
            f.write("\n")
        written += 1
    return written


def detect_model_name(predictions_rows: List[Dict[str, object]], fallback: str) -> str:
    for row in predictions_rows:
        model = row.get("model_name_or_path")
        if isinstance(model, str) and model:
            return model
        model = row.get("model")
        if isinstance(model, str) and model:
            return model
    return fallback


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reconstruct SWE-bench eval artifacts from run logs."
    )
    parser.add_argument(
        "--predictions",
        required=True,
        help="Path to predictions JSONL file.",
    )
    parser.add_argument(
        "--eval-log-dir",
        required=True,
        help="Path to run_evaluation checkpoint directory containing per-instance logs.",
    )
    parser.add_argument(
        "--model-name",
        default="qwen-code",
        help="Model name for output artifact file naming.",
    )
    parser.add_argument(
        "--run-id",
        default="vanilla_qwen_10inst",
        help="Run identifier for output artifact file naming.",
    )
    parser.add_argument(
        "--dataset",
        default="princeton-nlp/SWE-bench_Verified",
        help="Dataset name metadata for output JSON.",
    )
    parser.add_argument(
        "--output-dir",
        default="evaluation_results",
        help="Directory for aggregate JSON/CSV outputs.",
    )
    parser.add_argument(
        "--write-report-json",
        action="store_true",
        help="Also write per-instance report.json files into eval-log-dir.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    predictions_path = Path(args.predictions).resolve()
    eval_log_dir = Path(args.eval_log_dir).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not eval_log_dir.exists():
        raise FileNotFoundError(f"Eval log directory not found: {eval_log_dir}")

    predictions_rows = read_predictions(predictions_path)
    model_name = args.model_name
    if not model_name:
        model_name = detect_model_name(predictions_rows, "unknown-model")

    results = build_instance_results(predictions_rows, eval_log_dir)
    aggregate = aggregate_results(
        results=results,
        model_name=model_name,
        run_id=args.run_id,
        dataset=args.dataset,
        predictions_path=predictions_path,
        eval_log_dir=eval_log_dir,
    )

    json_output_path = output_dir / f"{model_name}.{args.run_id}.json"
    csv_output_path = output_dir / f"{model_name}.{args.run_id}.csv"

    write_json(aggregate, json_output_path)
    write_csv(results, csv_output_path)

    written_reports = 0
    if args.write_report_json:
        written_reports = write_reconstructed_report_json(eval_log_dir, results)

    print(f"Wrote aggregate JSON: {json_output_path}")
    print(f"Wrote aggregate CSV: {csv_output_path}")
    if args.write_report_json:
        print(f"Wrote per-instance report.json files: {written_reports}")

    print(
        "Summary:"
        f" total={aggregate['total_instances']}"
        f" resolved={aggregate['resolved_instances']}"
        f" unresolved={aggregate['unresolved_instances']}"
        f" incomplete={len(aggregate['incomplete_instances'])}"
        f" rate={aggregate['resolution_rate']:.4f}"
    )


if __name__ == "__main__":
    main()
