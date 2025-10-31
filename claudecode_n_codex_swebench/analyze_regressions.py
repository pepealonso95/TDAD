#!/usr/bin/env python3
"""
Regression Analysis for SWE-bench Evaluation Results

Analyzes evaluation results to extract regression metrics:
- Resolution rate (issues fixed)
- Regression rate (PASS_TO_PASS tests that failed)
- Clean resolution rate (fixed without regressions)

Reads evaluation output from SWE-bench harness and extracts detailed
test-level results to calculate regression statistics.
"""

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datasets import load_dataset
import jsonlines


class RegressionAnalyzer:
    """Analyzes SWE-bench evaluation results for regressions"""

    def __init__(self, eval_results_dir: str, dataset_name: str = "princeton-nlp/SWE-bench_Verified",
                 cache_dir: Optional[str] = None):
        self.eval_results_dir = Path(eval_results_dir)
        self.dataset_name = dataset_name
        self.cache_dir = Path(cache_dir) if cache_dir else Path("data")
        self.dataset = None
        self.test_info_cache = None

    def load_dataset_info(self):
        """Load SWE-bench dataset to get PASS_TO_PASS and FAIL_TO_PASS test info"""
        if self.dataset is None:
            # Try to load from local cache first
            cache_file = self.cache_dir / (self.dataset_name.replace("/", "_") + ".json")
            quick_cache = self.cache_dir / (self.dataset_name.replace("/", "_") + "_tests.json")

            if quick_cache.exists():
                print(f"Loading test info from local cache: {quick_cache}")
                with open(quick_cache, 'r') as f:
                    self.test_info_cache = json.load(f)
                print(f"✅ Loaded {len(self.test_info_cache)} instances from cache")
                return
            elif cache_file.exists():
                print(f"Loading dataset from local cache: {cache_file}")
                with open(cache_file, 'r') as f:
                    instances = json.load(f)
                self.dataset = instances
                print(f"✅ Loaded {len(instances)} instances from cache")
            else:
                print(f"Loading dataset from HuggingFace: {self.dataset_name}")
                print("This may take a few minutes on first run...")
                self.dataset = load_dataset(self.dataset_name, split='test')
                print(f"✅ Loaded {len(self.dataset)} instances")
                print(f"💡 Tip: Run 'python3 cache_dataset.py' to cache for faster future loads")

    def get_test_info(self, instance_id: str) -> Dict[str, List[str]]:
        """Get FAIL_TO_PASS and PASS_TO_PASS tests for an instance"""
        self.load_dataset_info()

        # Use quick cache if available
        if self.test_info_cache:
            info = self.test_info_cache.get(instance_id, {})
            return {
                'fail_to_pass': json.loads(info.get('fail_to_pass', '[]')) if isinstance(info.get('fail_to_pass'), str) else info.get('fail_to_pass', []),
                'pass_to_pass': json.loads(info.get('pass_to_pass', '[]')) if isinstance(info.get('pass_to_pass'), str) else info.get('pass_to_pass', [])
            }

        # Find the instance in the dataset
        for instance in self.dataset:
            if instance['instance_id'] == instance_id:
                return {
                    'fail_to_pass': json.loads(instance.get('FAIL_TO_PASS', '[]')) if isinstance(instance.get('FAIL_TO_PASS'), str) else instance.get('FAIL_TO_PASS', []),
                    'pass_to_pass': json.loads(instance.get('PASS_TO_PASS', '[]')) if isinstance(instance.get('PASS_TO_PASS'), str) else instance.get('PASS_TO_PASS', [])
                }

        return {'fail_to_pass': [], 'pass_to_pass': []}

    def parse_test_output(self, test_output_path: Path) -> Dict[str, List[str]]:
        """
        Parse test_output.txt to extract passed and failed tests

        Returns:
            Dict with 'passed' and 'failed' lists of test names
        """
        if not test_output_path.exists():
            return {'passed': [], 'failed': []}

        passed_tests = []
        failed_tests = []

        try:
            with open(test_output_path, 'r', errors='ignore') as f:
                content = f.read()

            # Common pytest patterns
            # PASSED tests: test_file.py::test_name PASSED
            passed_pattern = r'([\w/\-.]+\.py::\S+)\s+PASSED'
            passed_matches = re.findall(passed_pattern, content)
            passed_tests.extend(passed_matches)

            # FAILED tests: test_file.py::test_name FAILED
            failed_pattern = r'([\w/\-.]+\.py::\S+)\s+FAILED'
            failed_matches = re.findall(failed_pattern, content)
            failed_tests.extend(failed_matches)

            # Alternative patterns for different test frameworks
            # unittest: test_name (module.TestClass) ... ok/FAIL
            # etc.

        except Exception as e:
            print(f"Warning: Could not parse {test_output_path}: {e}")

        return {'passed': passed_tests, 'failed': failed_tests}

    def analyze_instance(self, instance_id: str, eval_log_dir: Path) -> Dict:
        """
        Analyze a single instance for regressions

        Returns:
            Dict with resolution and regression information
        """
        # Get expected test info from dataset
        test_info = self.get_test_info(instance_id)
        fail_to_pass_tests = test_info['fail_to_pass']
        pass_to_pass_tests = test_info['pass_to_pass']

        # Parse test output
        test_output_path = eval_log_dir / instance_id / 'test_output.txt'
        test_results = self.parse_test_output(test_output_path)

        # Read report.json if available
        report_path = eval_log_dir / instance_id / 'report.json'
        resolved = False
        if report_path.exists():
            try:
                with open(report_path, 'r') as f:
                    report = json.load(f)
                    resolved = report.get(instance_id, {}).get('resolved', False)
            except (json.JSONDecodeError, OSError) as e:
                print(f"Warning: Could not read report.json for {instance_id}: {e}")

        # Calculate metrics
        passed_tests_set = set(test_results['passed'])
        failed_tests_set = set(test_results['failed'])

        # Check FAIL_TO_PASS tests (should now pass)
        fail_to_pass_passed = sum(1 for test in fail_to_pass_tests if test in passed_tests_set)
        fail_to_pass_failed = sum(1 for test in fail_to_pass_tests if test in failed_tests_set)

        # Check PASS_TO_PASS tests (should still pass - regressions if they don't)
        pass_to_pass_passed = sum(1 for test in pass_to_pass_tests if test in passed_tests_set)
        pass_to_pass_failed = sum(1 for test in pass_to_pass_tests if test in failed_tests_set)

        # Calculate rates
        issue_fixed = (fail_to_pass_failed == 0) if fail_to_pass_tests else False
        has_regressions = pass_to_pass_failed > 0
        clean_resolution = issue_fixed and not has_regressions

        return {
            'instance_id': instance_id,
            'resolved': resolved,  # From official report
            'issue_fixed': issue_fixed,  # Our calculation
            'has_regressions': has_regressions,
            'clean_resolution': clean_resolution,
            'fail_to_pass': {
                'total': len(fail_to_pass_tests),
                'passed': fail_to_pass_passed,
                'failed': fail_to_pass_failed,
                'tests': fail_to_pass_tests
            },
            'pass_to_pass': {
                'total': len(pass_to_pass_tests),
                'passed': pass_to_pass_passed,
                'failed': pass_to_pass_failed,
                'tests': pass_to_pass_tests,
                'failed_tests': [test for test in pass_to_pass_tests if test in failed_tests_set]
            },
            'test_output_exists': test_output_path.exists(),
            'report_exists': report_path.exists()
        }

    def analyze_predictions(self, predictions_file: Path, run_id: Optional[str] = None) -> Dict:
        """
        Analyze all instances in a predictions file

        Args:
            predictions_file: Path to predictions JSONL file
            run_id: Run ID for the evaluation (if known)

        Returns:
            Dict with aggregate statistics
        """
        # Load predictions
        predictions = []
        with jsonlines.open(predictions_file) as reader:
            predictions = list(reader)

        print(f"\nAnalyzing {len(predictions)} predictions from {predictions_file.name}")

        # Find evaluation results directory
        # Pattern: evaluation_results/<run_id>/<instance_id>/
        if not run_id:
            # Try to infer from timestamp
            timestamp = predictions_file.stem.replace('predictions_', '')
            run_id = timestamp

        eval_log_dir = self.eval_results_dir

        # Analyze each instance
        results = []
        for pred in predictions:
            instance_id = pred['instance_id']
            instance_result = self.analyze_instance(instance_id, eval_log_dir)
            results.append(instance_result)

        # Calculate aggregate metrics
        total = len(results)
        resolved_count = sum(1 for r in results if r['resolved'])
        issue_fixed_count = sum(1 for r in results if r['issue_fixed'])
        has_regressions_count = sum(1 for r in results if r['has_regressions'])
        clean_resolution_count = sum(1 for r in results if r['clean_resolution'])

        # Calculate regression rate (of instances with regressions)
        total_pass_to_pass_tests = sum(r['pass_to_pass']['total'] for r in results)
        total_pass_to_pass_failed = sum(r['pass_to_pass']['failed'] for r in results)

        regression_rate = (total_pass_to_pass_failed / total_pass_to_pass_tests * 100) if total_pass_to_pass_tests > 0 else 0

        summary = {
            'predictions_file': str(predictions_file),
            'total_instances': total,
            'resolved_count': resolved_count,
            'resolution_rate': (resolved_count / total * 100) if total > 0 else 0,
            'issue_fixed_count': issue_fixed_count,
            'issue_fixed_rate': (issue_fixed_count / total * 100) if total > 0 else 0,
            'instances_with_regressions': has_regressions_count,
            'regression_instance_rate': (has_regressions_count / total * 100) if total > 0 else 0,
            'clean_resolution_count': clean_resolution_count,
            'clean_resolution_rate': (clean_resolution_count / total * 100) if total > 0 else 0,
            'total_pass_to_pass_tests': total_pass_to_pass_tests,
            'pass_to_pass_failed': total_pass_to_pass_failed,
            'regression_rate': regression_rate,
            'instance_details': results
        }

        return summary

    def print_summary(self, summary: Dict):
        """Print formatted summary"""
        print("\n" + "="*70)
        print("REGRESSION ANALYSIS SUMMARY")
        print("="*70)
        print(f"Predictions File: {summary['predictions_file']}")
        print(f"Total Instances: {summary['total_instances']}")
        print()
        print("RESOLUTION METRICS:")
        print(f"  Official Resolved: {summary['resolved_count']}/{summary['total_instances']} "
              f"({summary['resolution_rate']:.1f}%)")
        print(f"  Issue Fixed (FAIL_TO_PASS): {summary['issue_fixed_count']}/{summary['total_instances']} "
              f"({summary['issue_fixed_rate']:.1f}%)")
        print()
        print("REGRESSION METRICS:")
        print(f"  Instances with Regressions: {summary['instances_with_regressions']}/{summary['total_instances']} "
              f"({summary['regression_instance_rate']:.1f}%)")
        print(f"  Total PASS_TO_PASS Tests: {summary['total_pass_to_pass_tests']}")
        print(f"  PASS_TO_PASS Tests Failed: {summary['pass_to_pass_failed']}")
        print(f"  Regression Rate: {summary['regression_rate']:.1f}%")
        print()
        print("CLEAN RESOLUTION:")
        print(f"  Fixed WITHOUT Regressions: {summary['clean_resolution_count']}/{summary['total_instances']} "
              f"({summary['clean_resolution_rate']:.1f}%)")
        print("="*70)

        # Print instances with regressions
        if summary['instances_with_regressions'] > 0:
            print("\nINSTANCES WITH REGRESSIONS:")
            for instance in summary['instance_details']:
                if instance['has_regressions']:
                    print(f"  - {instance['instance_id']}: "
                          f"{instance['pass_to_pass']['failed']}/{instance['pass_to_pass']['total']} "
                          f"PASS_TO_PASS tests failed")
                    if instance['pass_to_pass']['failed_tests']:
                        for test in instance['pass_to_pass']['failed_tests'][:3]:  # Show first 3
                            print(f"    • {test}")
                        if len(instance['pass_to_pass']['failed_tests']) > 3:
                            print(f"    ... and {len(instance['pass_to_pass']['failed_tests']) - 3} more")

    def save_report(self, summary: Dict, output_path: Path):
        """Save detailed report to JSON"""
        with open(output_path, 'w') as f:
            json.dump(summary, f, indent=2)
        print(f"\nDetailed report saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Analyze SWE-bench evaluation results for regressions"
    )
    parser.add_argument(
        "--predictions", "-p",
        type=str,
        required=True,
        help="Path to predictions JSONL file"
    )
    parser.add_argument(
        "--eval-dir", "-e",
        type=str,
        default="evaluation_results",
        help="Path to evaluation results directory"
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default="princeton-nlp/SWE-bench_Verified",
        help="Dataset name (default: princeton-nlp/SWE-bench_Verified)"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        help="Path to save detailed JSON report"
    )
    parser.add_argument(
        "--run-id",
        type=str,
        help="Run ID for evaluation results"
    )
    parser.add_argument(
        "--cache-dir",
        type=str,
        default="data",
        help="Directory with cached dataset (default: data)"
    )

    args = parser.parse_args()

    analyzer = RegressionAnalyzer(args.eval_dir, args.dataset, args.cache_dir)
    predictions_path = Path(args.predictions)

    if not predictions_path.exists():
        print(f"Error: Predictions file not found: {predictions_path}")
        return 1

    summary = analyzer.analyze_predictions(predictions_path, args.run_id)
    analyzer.print_summary(summary)

    if args.output:
        analyzer.save_report(summary, Path(args.output))

    return 0


if __name__ == "__main__":
    exit(main())
