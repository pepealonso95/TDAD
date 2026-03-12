#!/usr/bin/env python3
"""Main CLI runner for the SWE-bench evaluation harness."""

import argparse
import json
import logging
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

from . import dataset, neo4j_lifecycle, evaluate
from .instance import process_instance, MODEL_SERVER_BASE_URL, MODEL_ID

logger = logging.getLogger(__name__)

RUNS_DIR = Path(__file__).parent / "runs"


def _check_model_server() -> None:
    """Verify the MLX model server is reachable."""
    url = MODEL_SERVER_BASE_URL.rstrip("/").replace("/v1", "") + "/health"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            print(f"MLX server OK at {MODEL_SERVER_BASE_URL}")
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError(
            f"MLX server not reachable at {MODEL_SERVER_BASE_URL}. "
            f"Start it with: mlx_vlm.server --port 8080\n"
            f"Error: {exc}"
        )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run SWE-bench evaluation: opencode baseline vs. opencode + TDAD",
    )
    parser.add_argument(
        "--mode",
        choices=["baseline", "tdad", "both"],
        default="both",
        help="Which mode(s) to run (default: both)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap number of instances (default: all)",
    )
    parser.add_argument(
        "--instance-ids",
        nargs="+",
        default=None,
        help="Specific instance IDs to run",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Per-instance agent timeout in seconds (default: 600)",
    )
    parser.add_argument(
        "--run-name",
        default=None,
        help="Run identifier (default: auto-timestamp)",
    )
    parser.add_argument(
        "--skip-eval",
        action="store_true",
        help="Skip Docker evaluation step",
    )
    parser.add_argument(
        "--dataset",
        default="princeton-nlp/SWE-bench_Verified",
        help="HuggingFace dataset name",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=2,
        help="Max parallel Docker containers for evaluation (default: 2)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose logging",
    )

    args = parser.parse_args(argv)

    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Verify Ollama model server is running
    _check_model_server()
    print()

    # Determine modes to run
    modes = []
    if args.mode in ("baseline", "both"):
        modes.append("baseline")
    if args.mode in ("tdad", "both"):
        modes.append("tdad")

    # Create run directory
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    run_name = args.run_name or timestamp
    run_dir = RUNS_DIR / f"{timestamp}_{run_name}"
    run_dir.mkdir(parents=True, exist_ok=True)
    predictions_dir = run_dir / "predictions"
    predictions_dir.mkdir()

    # Load instances
    instances = dataset.load_instances(
        dataset=args.dataset,
        limit=args.limit,
        instance_ids=args.instance_ids,
    )
    if not instances:
        print("No instances to process.")
        return 1

    # Save config
    config = {
        "mode": args.mode,
        "modes": modes,
        "model": MODEL_ID,
        "model_server": MODEL_SERVER_BASE_URL,
        "limit": args.limit,
        "instance_ids": args.instance_ids,
        "timeout": args.timeout,
        "dataset": args.dataset,
        "run_name": run_name,
        "instance_count": len(instances),
        "skip_eval": args.skip_eval,
    }
    with open(run_dir / "config.json", "w") as f:
        json.dump(config, f, indent=2)

    print(f"Run directory: {run_dir}")
    print(f"Instances: {len(instances)}")
    print(f"Modes: {', '.join(modes)}")
    print(f"Timeout: {args.timeout}s per instance")
    print()

    # Start Neo4j if tdad mode is needed
    neo4j_started = False
    if "tdad" in modes:
        print("Starting Neo4j...")
        neo4j_lifecycle.ensure_running()
        neo4j_started = True
        print("Neo4j ready.\n")

    # Process each mode
    all_predictions = {}
    for mode in modes:
        print(f"{'='*60}")
        print(f"MODE: {mode.upper()}")
        print(f"{'='*60}\n")

        predictions = []
        pred_file = predictions_dir / f"{mode}.jsonl"
        mode_start = time.time()

        for idx, instance in enumerate(instances, 1):
            iid = instance["instance_id"]
            print(f"[{idx}/{len(instances)}] {iid} ({mode})")
            inst_start = time.time()

            prediction = process_instance(
                instance=instance,
                mode=mode,
                timeout=args.timeout,
            )
            predictions.append(prediction)

            elapsed = time.time() - inst_start
            patch_size = len(prediction.get("model_patch", ""))
            status = f"{patch_size} bytes" if patch_size else "EMPTY"
            print(f"  -> {status} ({elapsed:.1f}s)\n")

            # Append to jsonl incrementally
            with open(pred_file, "a") as f:
                f.write(json.dumps(prediction) + "\n")

        mode_elapsed = time.time() - mode_start
        non_empty = sum(1 for p in predictions if p.get("model_patch", "").strip())
        print(f"{mode.upper()} complete: {non_empty}/{len(predictions)} patches "
              f"in {mode_elapsed:.1f}s\n")

        all_predictions[mode] = predictions

    # Evaluation
    baseline_results = None
    tdad_results = None

    if not args.skip_eval:
        print(f"{'='*60}")
        print("EVALUATION")
        print(f"{'='*60}\n")

        for mode in modes:
            pred_file = predictions_dir / f"{mode}.jsonl"
            if pred_file.exists():
                results = evaluate.evaluate_predictions(
                    predictions_file=pred_file,
                    dataset=args.dataset,
                    run_dir=run_dir,
                    max_workers=args.max_workers,
                )
                if mode == "baseline":
                    baseline_results = results
                else:
                    tdad_results = results
    else:
        print("Skipping evaluation (--skip-eval).\n")

    # Generate comparison report
    evaluate.generate_report(
        baseline_results=baseline_results,
        tdad_results=tdad_results,
        baseline_predictions=all_predictions.get("baseline", []),
        tdad_predictions=all_predictions.get("tdad", []),
        instances=instances,
        run_dir=run_dir,
    )

    # Cleanup Neo4j if we started it
    if neo4j_started:
        print("Stopping Neo4j...")
        neo4j_lifecycle.stop()

    print(f"\nDone. Results in: {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
