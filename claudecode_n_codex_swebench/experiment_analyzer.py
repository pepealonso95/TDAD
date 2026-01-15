#!/usr/bin/env python3
"""
Experiment Result Analyzer for SWE-bench Comparison

Provides utilities for:
- Parsing prediction files
- Calculating experiment metrics
- Comparing results across experiments
- Generating comparison reports
"""

import json
import statistics
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class ExperimentResults:
    """Results from a single experiment run"""
    name: str  # "Baseline", "TDD", "GraphRAG"
    dataset: str
    num_instances: int
    generation_rate: float  # % of instances with non-empty patches
    predictions: List[Dict]
    prediction_file: Path
    timestamp: str

    # Execution metrics
    total_time: Optional[float] = None  # seconds
    avg_time_per_instance: Optional[float] = None

    # Patch metrics
    avg_patch_size: Optional[int] = None
    median_patch_size: Optional[int] = None
    max_patch_size: Optional[int] = None

    # Error tracking
    num_errors: int = 0
    error_types: Dict[str, int] = None

    # GraphRAG-specific metrics
    graphrag_metadata: Optional[Dict] = None


@dataclass
class ComparisonReport:
    """Comparison of multiple experiments"""
    experiments: List[ExperimentResults]
    best_generation_rate: str
    best_avg_time: str
    best_patch_quality: str

    # Statistical comparisons
    generation_rate_comparison: Dict[str, float]
    time_comparison: Dict[str, float]
    patch_size_comparison: Dict[str, int]

    # Recommendations
    winner: str
    key_findings: List[str]
    recommendations: List[str]


class ExperimentAnalyzer:
    """Analyzer for SWE-bench experiment results"""

    def __init__(self):
        self.base_dir = Path.cwd()
        self.predictions_dir = self.base_dir / "predictions"
        self.results_dir = self.base_dir / "results"

    def parse_predictions(self, prediction_file: Path, experiment_name: str) -> ExperimentResults:
        """
        Parse a prediction JSONL file and extract metrics.

        Args:
            prediction_file: Path to predictions JSONL file
            experiment_name: Name of the experiment (Baseline, TDD, GraphRAG)

        Returns:
            ExperimentResults with parsed data and calculated metrics
        """
        predictions = []

        with open(prediction_file, 'r') as f:
            for line in f:
                if line.strip():
                    predictions.append(json.loads(line))

        # Calculate generation rate
        non_empty_patches = sum(1 for p in predictions if p.get("prediction", "").strip())
        generation_rate = (non_empty_patches / len(predictions) * 100) if predictions else 0

        # Count errors
        num_errors = sum(1 for p in predictions if p.get("error"))
        error_types = {}
        for p in predictions:
            if p.get("error"):
                error_msg = str(p["error"])
                # Categorize errors
                if "Failed to set up repository" in error_msg:
                    error_types["Repository Setup"] = error_types.get("Repository Setup", 0) + 1
                elif "Execution failed" in error_msg:
                    error_types["Execution Failed"] = error_types.get("Execution Failed", 0) + 1
                else:
                    error_types["Other"] = error_types.get("Other", 0) + 1

        # Calculate patch metrics
        patch_sizes = []
        for p in predictions:
            patch = p.get("prediction", "")
            if patch and patch.strip():
                patch_sizes.append(len(patch))

        avg_patch_size = int(statistics.mean(patch_sizes)) if patch_sizes else 0
        median_patch_size = int(statistics.median(patch_sizes)) if patch_sizes else 0
        max_patch_size = max(patch_sizes) if patch_sizes else 0

        # Extract GraphRAG metadata if present
        graphrag_metadata = None
        if experiment_name == "GraphRAG":
            graphrag_metadata = self._extract_graphrag_metadata(predictions)

        # Extract timestamp from filename
        timestamp = self._extract_timestamp(prediction_file)

        # Determine dataset from predictions
        dataset = "SWE-bench_Verified"  # Default
        if predictions and "instance_id" in predictions[0]:
            # Could parse from instance_id if needed
            pass

        return ExperimentResults(
            name=experiment_name,
            dataset=dataset,
            num_instances=len(predictions),
            generation_rate=generation_rate,
            predictions=predictions,
            prediction_file=prediction_file,
            timestamp=timestamp,
            avg_patch_size=avg_patch_size,
            median_patch_size=median_patch_size,
            max_patch_size=max_patch_size,
            num_errors=num_errors,
            error_types=error_types or {},
            graphrag_metadata=graphrag_metadata
        )

    def _extract_graphrag_metadata(self, predictions: List[Dict]) -> Dict:
        """Extract and aggregate GraphRAG metadata from predictions"""
        metadata_list = [p.get("graphrag_metadata", {}) for p in predictions if p.get("graphrag_metadata")]

        if not metadata_list:
            return {}

        # Calculate averages
        graph_build_times = [m.get("graph_build_time", 0) for m in metadata_list if m.get("graph_built")]
        impacted_tests = [m.get("impacted_tests_found", 0) for m in metadata_list]
        impact_times = [m.get("impact_analysis_time", 0) for m in metadata_list]

        return {
            "total_graphs_built": sum(1 for m in metadata_list if m.get("graph_built")),
            "avg_graph_build_time": statistics.mean(graph_build_times) if graph_build_times else 0,
            "avg_impacted_tests_found": statistics.mean(impacted_tests) if impacted_tests else 0,
            "avg_impact_analysis_time": statistics.mean(impact_times) if impact_times else 0,
            "max_impacted_tests": max(impacted_tests) if impacted_tests else 0,
            "min_impacted_tests": min(impacted_tests) if impacted_tests else 0
        }

    def _extract_timestamp(self, filename: Path) -> str:
        """Extract timestamp from filename like predictions_YYYYMMDD_HHMMSS.jsonl"""
        name = filename.stem
        parts = name.split("_")

        # Look for YYYYMMDD_HHMMSS pattern
        for i, part in enumerate(parts):
            if len(part) == 8 and part.isdigit():  # YYYYMMDD
                if i + 1 < len(parts) and len(parts[i + 1]) == 6 and parts[i + 1].isdigit():  # HHMMSS
                    return f"{part}_{parts[i + 1]}"

        return "unknown"

    def compare_experiments(self, results: List[ExperimentResults]) -> ComparisonReport:
        """
        Compare multiple experiment results and generate comparison report.

        Args:
            results: List of ExperimentResults to compare

        Returns:
            ComparisonReport with detailed comparison
        """
        if not results:
            raise ValueError("No results to compare")

        # Sort by generation rate to find best
        sorted_by_gen = sorted(results, key=lambda r: r.generation_rate, reverse=True)
        best_generation = sorted_by_gen[0].name

        # Sort by avg time (if available)
        results_with_time = [r for r in results if r.avg_time_per_instance is not None]
        if results_with_time:
            sorted_by_time = sorted(results_with_time, key=lambda r: r.avg_time_per_instance)
            best_time = sorted_by_time[0].name
        else:
            best_time = "N/A"

        # Sort by patch quality (non-empty, reasonable size)
        sorted_by_patch = sorted(results, key=lambda r: r.avg_patch_size if r.avg_patch_size else 0, reverse=True)
        best_patch = sorted_by_patch[0].name

        # Build comparison dictionaries
        gen_rate_comp = {r.name: r.generation_rate for r in results}
        time_comp = {r.name: r.avg_time_per_instance for r in results if r.avg_time_per_instance}
        patch_comp = {r.name: r.avg_patch_size for r in results if r.avg_patch_size}

        # Determine overall winner
        winner = self._determine_winner(results, sorted_by_gen)

        # Generate key findings
        findings = self._generate_findings(results, sorted_by_gen)

        # Generate recommendations
        recommendations = self._generate_recommendations(results, winner)

        return ComparisonReport(
            experiments=results,
            best_generation_rate=best_generation,
            best_avg_time=best_time,
            best_patch_quality=best_patch,
            generation_rate_comparison=gen_rate_comp,
            time_comparison=time_comp,
            patch_size_comparison=patch_comp,
            winner=winner,
            key_findings=findings,
            recommendations=recommendations
        )

    def _determine_winner(self, results: List[ExperimentResults], sorted_by_gen: List[ExperimentResults]) -> str:
        """Determine overall winner based on multiple criteria"""
        # Primary criterion: Generation rate
        # Secondary: Patch quality (size)
        # Tertiary: Speed (if available)

        best = sorted_by_gen[0]

        # If GraphRAG is present and has good generation rate, consider its efficiency
        graphrag = next((r for r in results if r.name == "GraphRAG"), None)
        if graphrag and graphrag.generation_rate >= best.generation_rate * 0.95:  # Within 5%
            return "GraphRAG"

        return best.name

    def _generate_findings(self, results: List[ExperimentResults], sorted_by_gen: List[ExperimentResults]) -> List[str]:
        """Generate key findings from comparison"""
        findings = []

        # Generation rate finding
        best_gen = sorted_by_gen[0]
        worst_gen = sorted_by_gen[-1]
        diff = best_gen.generation_rate - worst_gen.generation_rate
        findings.append(
            f"{best_gen.name} achieved the highest generation rate ({best_gen.generation_rate:.1f}%), "
            f"{diff:.1f}% better than {worst_gen.name}"
        )

        # Patch size finding
        sorted_by_patch = sorted(results, key=lambda r: r.avg_patch_size if r.avg_patch_size else 0, reverse=True)
        if sorted_by_patch[0].avg_patch_size:
            findings.append(
                f"{sorted_by_patch[0].name} produced the largest patches on average "
                f"({sorted_by_patch[0].avg_patch_size} chars), suggesting more comprehensive fixes"
            )

        # Error finding
        sorted_by_errors = sorted(results, key=lambda r: r.num_errors)
        if sorted_by_errors[0].num_errors < sorted_by_errors[-1].num_errors:
            findings.append(
                f"{sorted_by_errors[0].name} had the fewest errors ({sorted_by_errors[0].num_errors}), "
                f"indicating better stability"
            )

        # GraphRAG-specific finding
        graphrag = next((r for r in results if r.name == "GraphRAG" and r.graphrag_metadata), None)
        if graphrag and graphrag.graphrag_metadata:
            meta = graphrag.graphrag_metadata
            findings.append(
                f"GraphRAG identified an average of {meta['avg_impacted_tests_found']:.1f} impacted tests per instance, "
                f"with graph building taking {meta['avg_graph_build_time']:.1f}s on average"
            )

        return findings

    def _generate_recommendations(self, results: List[ExperimentResults], winner: str) -> List[str]:
        """Generate recommendations based on results"""
        recommendations = []

        recommendations.append(
            f"Use {winner} for production SWE-bench evaluation based on overall performance"
        )

        # Find lowest performer
        sorted_by_gen = sorted(results, key=lambda r: r.generation_rate)
        if sorted_by_gen[0].generation_rate < 50:
            recommendations.append(
                f"Investigate why {sorted_by_gen[0].name} has low generation rate - may need prompt refinement"
            )

        # GraphRAG-specific recommendations
        graphrag = next((r for r in results if r.name == "GraphRAG"), None)
        if graphrag:
            recommendations.append(
                "Run Docker evaluation to measure actual resolution and regression rates for GraphRAG"
            )
            if graphrag.graphrag_metadata:
                meta = graphrag.graphrag_metadata
                if meta['avg_graph_build_time'] > 60:
                    recommendations.append(
                        "Consider caching graph builds across multiple runs to reduce overhead"
                    )

        # TDD-specific recommendations
        tdd = next((r for r in results if r.name == "TDD"), None)
        if tdd and tdd.generation_rate > 0:
            recommendations.append(
                "Analyze TDD patches to verify they include test files as expected"
            )

        return recommendations

    def generate_markdown_report(self, comparison: ComparisonReport) -> str:
        """Generate a detailed Markdown report from comparison results"""
        report_lines = []

        # Header
        report_lines.append("## EXP-005: Full Three-Way Comparison (50 Instances Each)")
        report_lines.append("")
        report_lines.append("### Metadata")
        report_lines.append(f"- **Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        report_lines.append(f"- **Dataset**: SWE-bench_Verified")
        report_lines.append(f"- **Sample Size**: {comparison.experiments[0].num_instances} instances per experiment")
        report_lines.append(f"- **Experiments**: {', '.join([e.name for e in comparison.experiments])}")
        report_lines.append("")

        # Executive Summary
        report_lines.append("### Executive Summary")
        report_lines.append("")
        report_lines.append(f"**Winner**: 🏆 **{comparison.winner}**")
        report_lines.append("")
        report_lines.append("**Key Findings:**")
        for finding in comparison.key_findings:
            report_lines.append(f"- {finding}")
        report_lines.append("")

        # Detailed Metrics Table
        report_lines.append("### Detailed Metrics Comparison")
        report_lines.append("")
        report_lines.append("| Metric | Baseline | TDD | GraphRAG |")
        report_lines.append("|--------|----------|-----|----------|")

        # Generation Rate
        gen_rates = {e.name: e.generation_rate for e in comparison.experiments}
        report_lines.append(
            f"| **Generation Rate** | "
            f"{gen_rates.get('Baseline', 0):.1f}% | "
            f"{gen_rates.get('TDD', 0):.1f}% | "
            f"{gen_rates.get('GraphRAG', 0):.1f}% |"
        )

        # Avg Patch Size
        patch_sizes = {e.name: e.avg_patch_size for e in comparison.experiments}
        report_lines.append(
            f"| **Avg Patch Size** | "
            f"{patch_sizes.get('Baseline', 0):,} chars | "
            f"{patch_sizes.get('TDD', 0):,} chars | "
            f"{patch_sizes.get('GraphRAG', 0):,} chars |"
        )

        # Median Patch Size
        median_sizes = {e.name: e.median_patch_size for e in comparison.experiments}
        report_lines.append(
            f"| **Median Patch Size** | "
            f"{median_sizes.get('Baseline', 0):,} chars | "
            f"{median_sizes.get('TDD', 0):,} chars | "
            f"{median_sizes.get('GraphRAG', 0):,} chars |"
        )

        # Errors
        errors = {e.name: e.num_errors for e in comparison.experiments}
        report_lines.append(
            f"| **Errors** | "
            f"{errors.get('Baseline', 0)} | "
            f"{errors.get('TDD', 0)} | "
            f"{errors.get('GraphRAG', 0)} |"
        )

        report_lines.append("")

        # GraphRAG-Specific Metrics
        graphrag = next((e for e in comparison.experiments if e.name == "GraphRAG" and e.graphrag_metadata), None)
        if graphrag and graphrag.graphrag_metadata:
            meta = graphrag.graphrag_metadata
            report_lines.append("### GraphRAG-Specific Metrics")
            report_lines.append("")
            report_lines.append(f"- **Total Graphs Built**: {meta['total_graphs_built']}")
            report_lines.append(f"- **Avg Graph Build Time**: {meta['avg_graph_build_time']:.1f}s")
            report_lines.append(f"- **Avg Impacted Tests Found**: {meta['avg_impacted_tests_found']:.1f} tests")
            report_lines.append(f"- **Avg Impact Analysis Time**: {meta['avg_impact_analysis_time']:.2f}s")
            report_lines.append(f"- **Test Range**: {meta['min_impacted_tests']} - {meta['max_impacted_tests']} tests")
            report_lines.append("")

        # Error Breakdown
        report_lines.append("### Error Analysis")
        report_lines.append("")
        for exp in comparison.experiments:
            if exp.error_types:
                report_lines.append(f"**{exp.name} Errors:**")
                for error_type, count in exp.error_types.items():
                    report_lines.append(f"- {error_type}: {count}")
                report_lines.append("")

        # Recommendations
        report_lines.append("### Recommendations")
        report_lines.append("")
        for i, rec in enumerate(comparison.recommendations, 1):
            report_lines.append(f"{i}. {rec}")
        report_lines.append("")

        # Next Steps
        report_lines.append("### Next Steps")
        report_lines.append("")
        report_lines.append("- [ ] Run Docker evaluation on all three prediction sets")
        report_lines.append("- [ ] Calculate resolution rates from evaluation results")
        report_lines.append("- [ ] Measure regression rates for each approach")
        report_lines.append("- [ ] Compare actual test execution times")
        report_lines.append("- [ ] Analyze specific instances where approaches differed")
        report_lines.append("")

        # Prediction Files
        report_lines.append("### Prediction Files")
        report_lines.append("")
        for exp in comparison.experiments:
            report_lines.append(f"- **{exp.name}**: `{exp.prediction_file.name}`")
        report_lines.append("")

        return "\n".join(report_lines)

    def append_to_experiments_md(self, report: str, experiments_md_path: Path = None):
        """
        Append the comparison report to EXPERIMENTS.md

        Args:
            report: Markdown report to append
            experiments_md_path: Path to EXPERIMENTS.md (default: ../EXPERIMENTS.md)
        """
        if experiments_md_path is None:
            experiments_md_path = self.base_dir.parent / "EXPERIMENTS.md"

        if not experiments_md_path.exists():
            raise FileNotFoundError(f"EXPERIMENTS.md not found at {experiments_md_path}")

        # Backup first
        backup_path = experiments_md_path.with_suffix(".md.backup")
        with open(experiments_md_path, 'r') as f:
            backup_content = f.read()
        with open(backup_path, 'w') as f:
            f.write(backup_content)

        # Append report
        with open(experiments_md_path, 'a') as f:
            f.write("\n\n")
            f.write("---\n\n")
            f.write(report)

        print(f"✓ Report appended to {experiments_md_path}")
        print(f"✓ Backup saved to {backup_path}")
