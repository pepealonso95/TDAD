#!/usr/bin/env python3
"""
Generate Comparison Report from Separate Experiment Runs

Use this when experiments were run on different days to manually combine
results and generate a comparison report.

Usage:
    python generate_comparison_report.py --baseline predictions/predictions_20251120_012806.jsonl \
                                         --tdd predictions/predictions_20251120_123456.jsonl \
                                         --graphrag predictions/predictions_graphrag_20251120_234567.jsonl
"""

import argparse
import sys
from pathlib import Path

from experiment_analyzer import ExperimentAnalyzer


def main():
    parser = argparse.ArgumentParser(
        description="Generate comparison report from separate experiment runs"
    )
    parser.add_argument(
        "--baseline",
        type=str,
        required=True,
        help="Path to baseline predictions file (.jsonl)"
    )
    parser.add_argument(
        "--tdd",
        type=str,
        required=True,
        help="Path to TDD predictions file (.jsonl)"
    )
    parser.add_argument(
        "--graphrag",
        type=str,
        required=True,
        help="Path to GraphRAG predictions file (.jsonl)"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output file for comparison report (default: comparison_report_TIMESTAMP.md)"
    )
    parser.add_argument(
        "--skip-experiments-md",
        action="store_true",
        help="Skip appending report to EXPERIMENTS.md"
    )

    args = parser.parse_args()

    # Validate files exist
    baseline_file = Path(args.baseline)
    tdd_file = Path(args.tdd)
    graphrag_file = Path(args.graphrag)

    for file, name in [(baseline_file, "Baseline"), (tdd_file, "TDD"), (graphrag_file, "GraphRAG")]:
        if not file.exists():
            print(f"Error: {name} file not found: {file}")
            sys.exit(1)

    print("="*70)
    print("GENERATING COMPARISON REPORT FROM SEPARATE RUNS")
    print("="*70)
    print(f"Baseline:  {baseline_file.name}")
    print(f"TDD:       {tdd_file.name}")
    print(f"GraphRAG:  {graphrag_file.name}")
    print("="*70)
    print()

    # Initialize analyzer
    analyzer = ExperimentAnalyzer()

    # Parse each experiment
    print("Parsing experiment results...")

    baseline_results = analyzer.parse_predictions(baseline_file, "Baseline")
    print(f"✓ Baseline: {baseline_results.num_instances} instances, {baseline_results.generation_rate:.1f}% generation rate")

    tdd_results = analyzer.parse_predictions(tdd_file, "TDD")
    print(f"✓ TDD: {tdd_results.num_instances} instances, {tdd_results.generation_rate:.1f}% generation rate")

    graphrag_results = analyzer.parse_predictions(graphrag_file, "GraphRAG")
    print(f"✓ GraphRAG: {graphrag_results.num_instances} instances, {graphrag_results.generation_rate:.1f}% generation rate")

    if graphrag_results.graphrag_metadata:
        meta = graphrag_results.graphrag_metadata
        print(f"  • GraphRAG built {meta['total_graphs_built']} graphs")
        print(f"  • Avg impacted tests: {meta['avg_impacted_tests_found']:.1f}")

    print()

    # Generate comparison
    print("Generating comparison report...")
    comparison = analyzer.compare_experiments([baseline_results, tdd_results, graphrag_results])
    report = analyzer.generate_markdown_report(comparison)

    # Save report
    if args.output:
        output_file = Path(args.output)
    else:
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = Path.cwd() / f"comparison_report_{timestamp}.md"

    with open(output_file, 'w') as f:
        f.write(report)

    print(f"✓ Comparison report saved to {output_file.name}")

    # Append to EXPERIMENTS.md unless skipped
    if not args.skip_experiments_md:
        try:
            analyzer.append_to_experiments_md(report)
            print(f"✓ Report appended to EXPERIMENTS.md")
        except Exception as e:
            print(f"✗ Failed to append to EXPERIMENTS.md: {e}")
            print("  Report saved to file, but not appended to EXPERIMENTS.md")

    print()
    print("="*70)
    print("COMPARISON SUMMARY")
    print("="*70)
    print(f"\nWinner: 🏆 {comparison.winner}\n")
    print("Key Findings:")
    for i, finding in enumerate(comparison.key_findings, 1):
        print(f"{i}. {finding}")

    print("\n" + "="*70)
    print("✓ Comparison report generation complete!")


if __name__ == "__main__":
    main()
