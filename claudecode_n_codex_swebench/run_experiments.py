#!/usr/bin/env python3
"""
Automated SWE-bench Experiment Runner

Runs all three experiment modes (Baseline, TDD, GraphRAG) and generates
a comprehensive comparison report.

Usage:
    python run_experiments.py --limit 50
    python run_experiments.py --limit 10 --experiments baseline,tdd
    python run_experiments.py --limit 50 --skip-evaluation --dry-run
"""

import argparse
import json
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from experiment_analyzer import ExperimentAnalyzer, ExperimentResults


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('experiment_comparison.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class ExperimentRunner:
    """Orchestrates running multiple SWE-bench experiments"""

    def __init__(self, dataset: str, limit: int, dry_run: bool = False):
        self.dataset = dataset
        self.limit = limit
        self.dry_run = dry_run
        self.base_dir = Path.cwd()
        self.predictions_dir = self.base_dir / "predictions"
        self.analyzer = ExperimentAnalyzer()

        # Ensure directories exist
        self.predictions_dir.mkdir(exist_ok=True)

    def run_baseline_experiment(self) -> Optional[ExperimentResults]:
        """
        Run baseline SWE-bench experiment.

        Returns:
            ExperimentResults or None if failed
        """
        logger.info("="*70)
        logger.info("EXPERIMENT 1/3: BASELINE")
        logger.info("="*70)

        cmd = [
            sys.executable,
            "code_swe_agent.py",
            "--dataset_name", self.dataset,
            "--limit", str(self.limit),
            "--backend", "claude"
        ]

        logger.info(f"Command: {' '.join(cmd)}")

        if self.dry_run:
            logger.info("DRY RUN: Would execute baseline experiment")
            return None

        try:
            start_time = time.time()

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.base_dir)
            )

            duration = time.time() - start_time

            if result.returncode != 0:
                logger.error(f"Baseline experiment failed: {result.stderr}")
                return None

            logger.info(result.stdout)
            logger.info(f"Baseline experiment completed in {duration:.1f}s")

            # Find the generated prediction file
            prediction_file = self._find_latest_prediction_file("predictions_*.jsonl")

            if not prediction_file:
                logger.error("Could not find baseline prediction file")
                return None

            # Parse results
            results = self.analyzer.parse_predictions(prediction_file, "Baseline")
            results.total_time = duration
            results.avg_time_per_instance = duration / self.limit if self.limit > 0 else 0

            logger.info(f"✓ Baseline: {results.generation_rate:.1f}% generation rate")
            logger.info(f"✓ Prediction file: {prediction_file.name}")

            return results

        except Exception as e:
            logger.error(f"Error running baseline experiment: {e}")
            return None

    def run_tdd_experiment(self) -> Optional[ExperimentResults]:
        """
        Run TDD prompt experiment.

        Returns:
            ExperimentResults or None if failed
        """
        logger.info("="*70)
        logger.info("EXPERIMENT 2/3: TDD PROMPT")
        logger.info("="*70)

        cmd = [
            sys.executable,
            "code_swe_agent.py",
            "--dataset_name", self.dataset,
            "--limit", str(self.limit),
            "--backend", "claude",
            "--prompt_template", "prompts/swe_bench_tdd.txt"
        ]

        logger.info(f"Command: {' '.join(cmd)}")

        if self.dry_run:
            logger.info("DRY RUN: Would execute TDD experiment")
            return None

        try:
            start_time = time.time()

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.base_dir)
            )

            duration = time.time() - start_time

            if result.returncode != 0:
                logger.error(f"TDD experiment failed: {result.stderr}")
                return None

            logger.info(result.stdout)
            logger.info(f"TDD experiment completed in {duration:.1f}s")

            # Find the generated prediction file
            prediction_file = self._find_latest_prediction_file("predictions_*.jsonl")

            if not prediction_file:
                logger.error("Could not find TDD prediction file")
                return None

            # Parse results
            results = self.analyzer.parse_predictions(prediction_file, "TDD")
            results.total_time = duration
            results.avg_time_per_instance = duration / self.limit if self.limit > 0 else 0

            logger.info(f"✓ TDD: {results.generation_rate:.1f}% generation rate")
            logger.info(f"✓ Prediction file: {prediction_file.name}")

            return results

        except Exception as e:
            logger.error(f"Error running TDD experiment: {e}")
            return None

    def run_graphrag_experiment(self) -> Optional[ExperimentResults]:
        """
        Run GraphRAG experiment.

        Returns:
            ExperimentResults or None if failed
        """
        logger.info("="*70)
        logger.info("EXPERIMENT 3/3: GRAPHRAG TEST IMPACT ANALYSIS")
        logger.info("="*70)

        cmd = [
            sys.executable,
            "code_swe_agent_graphrag.py",
            "--dataset_name", self.dataset,
            "--limit", str(self.limit),
            "--backend", "claude"
        ]

        logger.info(f"Command: {' '.join(cmd)}")

        if self.dry_run:
            logger.info("DRY RUN: Would execute GraphRAG experiment")
            return None

        try:
            start_time = time.time()

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.base_dir)
            )

            duration = time.time() - start_time

            if result.returncode != 0:
                logger.error(f"GraphRAG experiment failed: {result.stderr}")
                return None

            logger.info(result.stdout)
            logger.info(f"GraphRAG experiment completed in {duration:.1f}s")

            # Find the generated prediction file (includes _graphrag_ infix)
            prediction_file = self._find_latest_prediction_file("predictions_graphrag_*.jsonl")

            if not prediction_file:
                logger.error("Could not find GraphRAG prediction file")
                return None

            # Parse results
            results = self.analyzer.parse_predictions(prediction_file, "GraphRAG")
            results.total_time = duration
            results.avg_time_per_instance = duration / self.limit if self.limit > 0 else 0

            logger.info(f"✓ GraphRAG: {results.generation_rate:.1f}% generation rate")
            logger.info(f"✓ Prediction file: {prediction_file.name}")

            if results.graphrag_metadata:
                meta = results.graphrag_metadata
                logger.info(f"✓ GraphRAG built {meta['total_graphs_built']} graphs")
                logger.info(f"✓ Avg impacted tests: {meta['avg_impacted_tests_found']:.1f}")

            return results

        except Exception as e:
            logger.error(f"Error running GraphRAG experiment: {e}")
            return None

    def _find_latest_prediction_file(self, pattern: str) -> Optional[Path]:
        """Find the most recent prediction file matching pattern"""
        matching_files = sorted(
            self.predictions_dir.glob(pattern),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

        if matching_files:
            return matching_files[0]

        return None

    def run_all_experiments(self, experiments: List[str]) -> List[ExperimentResults]:
        """
        Run all specified experiments.

        Args:
            experiments: List of experiment names to run (baseline, tdd, graphrag)

        Returns:
            List of ExperimentResults (only successful experiments)
        """
        results = []

        if "baseline" in experiments:
            baseline_result = self.run_baseline_experiment()
            if baseline_result:
                results.append(baseline_result)
                self._save_intermediate_results(results)

        if "tdd" in experiments:
            tdd_result = self.run_tdd_experiment()
            if tdd_result:
                results.append(tdd_result)
                self._save_intermediate_results(results)

        if "graphrag" in experiments:
            graphrag_result = self.run_graphrag_experiment()
            if graphrag_result:
                results.append(graphrag_result)
                self._save_intermediate_results(results)

        return results

    def _save_intermediate_results(self, results: List[ExperimentResults]):
        """Save intermediate results after each experiment"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = self.base_dir / f"experiment_results_{timestamp}.json"

        data = {
            "timestamp": timestamp,
            "experiments": [
                {
                    "name": r.name,
                    "dataset": r.dataset,
                    "num_instances": r.num_instances,
                    "generation_rate": r.generation_rate,
                    "prediction_file": str(r.prediction_file),
                    "total_time": r.total_time,
                    "avg_time_per_instance": r.avg_time_per_instance,
                    "avg_patch_size": r.avg_patch_size,
                    "median_patch_size": r.median_patch_size,
                    "num_errors": r.num_errors,
                    "error_types": r.error_types,
                    "graphrag_metadata": r.graphrag_metadata
                }
                for r in results
            ]
        }

        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)

        logger.info(f"✓ Intermediate results saved to {output_file.name}")

    def generate_comparison_report(self, results: List[ExperimentResults]) -> str:
        """Generate comparison report from results"""
        if not results:
            raise ValueError("No results to compare")

        logger.info("="*70)
        logger.info("GENERATING COMPARISON REPORT")
        logger.info("="*70)

        comparison = self.analyzer.compare_experiments(results)
        report = self.analyzer.generate_markdown_report(comparison)

        # Save report to file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = self.base_dir / f"comparison_report_{timestamp}.md"

        with open(report_file, 'w') as f:
            f.write(report)

        logger.info(f"✓ Comparison report saved to {report_file.name}")

        return report

    def append_to_experiments_md(self, report: str):
        """Append report to EXPERIMENTS.md"""
        try:
            self.analyzer.append_to_experiments_md(report)
            logger.info("✓ Report appended to EXPERIMENTS.md")
        except Exception as e:
            logger.error(f"Failed to append to EXPERIMENTS.md: {e}")

    def print_summary(self, results: List[ExperimentResults]):
        """Print summary of all experiments to console"""
        print("\n" + "="*70)
        print("EXPERIMENT SUMMARY")
        print("="*70)

        for result in results:
            print(f"\n{result.name}:")
            print(f"  Generation Rate: {result.generation_rate:.1f}%")
            print(f"  Avg Patch Size: {result.avg_patch_size:,} chars")
            print(f"  Errors: {result.num_errors}")
            if result.total_time:
                print(f"  Total Time: {result.total_time:.1f}s")
                print(f"  Avg Time/Instance: {result.avg_time_per_instance:.1f}s")

            if result.name == "GraphRAG" and result.graphrag_metadata:
                meta = result.graphrag_metadata
                print(f"  Graphs Built: {meta['total_graphs_built']}")
                print(f"  Avg Impacted Tests: {meta['avg_impacted_tests_found']:.1f}")

        print("\n" + "="*70)

        # Quick winner announcement
        if len(results) > 1:
            comparison = self.analyzer.compare_experiments(results)
            print(f"\n🏆 Overall Winner: {comparison.winner}")
            print(f"\nKey Findings:")
            for finding in comparison.key_findings[:3]:  # Top 3 findings
                print(f"  • {finding}")

        print("\n" + "="*70)


def main():
    parser = argparse.ArgumentParser(
        description="Run all three SWE-bench experiments and generate comparison report"
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default="princeton-nlp/SWE-bench_Verified",
        help="Dataset to use (default: princeton-nlp/SWE-bench_Verified)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Number of instances to process per experiment (default: 50)"
    )
    parser.add_argument(
        "--experiments",
        type=str,
        default="baseline,tdd,graphrag",
        help="Comma-separated list of experiments to run (default: all)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be executed without running"
    )
    parser.add_argument(
        "--skip-experiments-md",
        action="store_true",
        help="Skip appending report to EXPERIMENTS.md"
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompt (for unattended runs)"
    )

    args = parser.parse_args()

    # Parse experiments list
    experiments = [e.strip().lower() for e in args.experiments.split(",")]
    valid_experiments = ["baseline", "tdd", "graphrag"]

    for exp in experiments:
        if exp not in valid_experiments:
            print(f"Error: Invalid experiment '{exp}'. Valid options: {', '.join(valid_experiments)}")
            sys.exit(1)

    # Print configuration
    print("="*70)
    print("AUTOMATED EXPERIMENT RUNNER")
    print("="*70)
    print(f"Dataset: {args.dataset}")
    print(f"Instances per experiment: {args.limit}")
    print(f"Experiments: {', '.join([e.upper() for e in experiments])}")
    print(f"Dry run: {args.dry_run}")
    print("="*70)

    if not args.dry_run and not args.yes:
        response = input("\nThis will run multiple experiments that may take several hours. Continue? (y/n): ")
        if response.lower() != 'y':
            print("Aborted.")
            sys.exit(0)

    # Run experiments
    runner = ExperimentRunner(args.dataset, args.limit, args.dry_run)

    try:
        results = runner.run_all_experiments(experiments)

        if not results:
            logger.error("No experiments completed successfully")
            sys.exit(1)

        # Generate comparison report
        if len(results) > 1:
            report = runner.generate_comparison_report(results)

            # Append to EXPERIMENTS.md unless skipped
            if not args.skip_experiments_md and not args.dry_run:
                runner.append_to_experiments_md(report)

        # Print summary
        runner.print_summary(results)

        logger.info("✓ All experiments completed successfully!")

    except KeyboardInterrupt:
        logger.warning("\n\nExperiments interrupted by user")
        logger.info("Intermediate results have been saved")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
