# Regression Analysis for SWE-bench Results

## Overview

This document explains how to measure **regression rates** in SWE-bench evaluation results - a critical metric for the TDAD thesis.

## What is a Regression?

In SWE-bench context:
- **FAIL_TO_PASS tests**: Tests that should fail before the patch and pass after (prove the issue is fixed)
- **PASS_TO_PASS tests**: Tests that should pass both before and after the patch (regression tests)
- **Regression**: When a PASS_TO_PASS test fails after applying the patch (code broke existing functionality)

## Key Metrics

### 1. Resolution Rate (Standard SWE-bench metric)
- % of instances where the issue is resolved
- Official metric: `resolved_instances / total_instances`
- Does NOT distinguish between "fixed with regressions" vs "cleanly fixed"

### 2. Regression Rate (PRIMARY METRIC for thesis)
- % of PASS_TO_PASS tests that failed
- Formula: `pass_to_pass_failed / total_pass_to_pass_tests`
- Lower is better (goal: <5% regression rate)

### 3. Clean Resolution Rate (NEW composite metric)
- % of instances fixed WITHOUT introducing regressions
- Formula: `instances_with_all_fail_to_pass_passing_and_no_pass_to_pass_failing / total_instances`
- Most stringent success criteria

### 4. Regression Instance Rate
- % of instances that introduced at least one regression
- Formula: `instances_with_any_pass_to_pass_failing / total_instances`

## How SWE-bench Verified Enables Regression Measurement

Each instance in SWE-bench Verified includes:

```python
{
  "instance_id": "astropy__astropy-12907",
  "FAIL_TO_PASS": "[\"test_file.py::test_bug\", ...]",  # Tests that should now pass
  "PASS_TO_PASS": "[\"test_file.py::test_existing\", ...]",  # Should still pass
  ...
}
```

## Using the Regression Analyzer

### Basic Usage

```bash
# After running evaluation, analyze regressions
python3 analyze_regressions.py \
  --predictions predictions/predictions_20251029_HHMMSS.jsonl \
  --eval-dir evaluation_results
```

### With Output Report

```bash
# Save detailed JSON report
python3 analyze_regressions.py \
  --predictions predictions/predictions_20251029_HHMMSS.jsonl \
  --eval-dir evaluation_results \
  --output regression_report_exp002.json
```

### For Different Datasets

```bash
# For SWE-bench Lite (not recommended for thesis)
python3 analyze_regressions.py \
  --predictions predictions/predictions_20251029_HHMMSS.jsonl \
  --eval-dir evaluation_results \
  --dataset princeton-nlp/SWE-bench_Lite
```

## Output Example

```
======================================================================
REGRESSION ANALYSIS SUMMARY
======================================================================
Predictions File: predictions/predictions_20251029_123456.jsonl
Total Instances: 10

RESOLUTION METRICS:
  Official Resolved: 7/10 (70.0%)
  Issue Fixed (FAIL_TO_PASS): 8/10 (80.0%)

REGRESSION METRICS:
  Instances with Regressions: 2/10 (20.0%)
  Total PASS_TO_PASS Tests: 156
  PASS_TO_PASS Tests Failed: 12
  Regression Rate: 7.7%

CLEAN RESOLUTION:
  Fixed WITHOUT Regressions: 6/10 (60.0%)
======================================================================

INSTANCES WITH REGRESSIONS:
  - django__django-11001: 5/23 PASS_TO_PASS tests failed
    • django/tests/queries/test_ordering.py::test_order_by_multiline
    • django/tests/queries/test_ordering.py::test_order_by_raw_sql
    ... and 3 more
  - astropy__astropy-6938: 7/18 PASS_TO_PASS tests failed
    • astropy/tests/test_fits.py::test_exponent_handling
    ... and 6 more
======================================================================
```

## Workflow for Experiments

### Step 1: Run Experiment
```bash
python3 code_swe_agent.py \
  --dataset_name princeton-nlp/SWE-bench_Verified \
  --limit 10 \
  --backend claude \
  --prompt_template prompts/swe_bench_tdd.txt
```

### Step 2: Evaluate Predictions
```bash
python3 evaluate_predictions.py --file predictions/predictions_TIMESTAMP.jsonl
```

### Step 3: Analyze Regressions
```bash
python3 analyze_regressions.py \
  --predictions predictions/predictions_TIMESTAMP.jsonl \
  --eval-dir evaluation_results \
  --output reports/exp002_regression_analysis.json
```

### Step 4: Compare Experiments

```bash
# Baseline (EXP-001)
python3 analyze_regressions.py \
  --predictions predictions/baseline_predictions.jsonl \
  --output reports/exp001_regressions.json

# TDD (EXP-002)
python3 analyze_regressions.py \
  --predictions predictions/tdd_predictions.jsonl \
  --output reports/exp002_regressions.json

# Compare JSON reports to measure improvement
```

## Expected Results for Thesis

### Hypothesis:
TDD approach should reduce regression rate while maintaining resolution rate.

### Target Metrics (EXP-002 vs EXP-001):

| Metric | Baseline (EXP-001) | TDD (EXP-002) | Target |
|--------|-------------------|---------------|--------|
| Resolution Rate | ~15-25% | ~15-25% | Maintain |
| Regression Rate | ~10-15% | ~3-7% | Reduce by >30% |
| Clean Resolution | ~12-20% | ~12-22% | Maintain or improve |
| Regression Instance Rate | ~20-30% | ~10-15% | Reduce significantly |

### Success Criteria:
- ✅ **Primary**: Regression rate reduced by >30%
- ✅ **Secondary**: Resolution rate maintained (not significantly reduced)
- ✅ **Ideal**: Clean resolution rate improved

## Limitations & Notes

### Current Implementation:
1. **Test Output Parsing**: Currently uses regex to parse pytest output
   - May not work for all test frameworks
   - Handles pytest (most common) well

2. **Report.json Dependency**: Relies on SWE-bench harness output
   - If `test_output.txt` is missing, cannot calculate regressions
   - Falls back to official `report.json` for basic resolution status

3. **Test Name Matching**: Requires exact test name matches
   - SWE-bench uses pytest-style paths: `file.py::test_name`
   - Should work for all SWE-bench Verified instances

### Future Enhancements:
1. Support for additional test frameworks (unittest, nose, etc.)
2. More sophisticated test output parsing
3. Visualization of regression patterns
4. Time-series analysis across experiments

## Integration with EXPERIMENTS.md

When logging experiments, include these regression metrics:

```markdown
## EXP-002: TDD Prompt Engineering

### Results
- **Resolution Rate**: 70% (7/10 issues resolved)
- **Regression Rate**: 7.7% (12/156 PASS_TO_PASS tests failed) ← KEY METRIC
- **Clean Resolution Rate**: 60% (6/10 fixed without regressions)
- **Regression Instance Rate**: 20% (2/10 instances had regressions)

### Comparison to Baseline
- Resolution Rate: 70% (baseline: 72%) — ✅ Maintained
- **Regression Rate: 7.7% (baseline: 15.2%) — ✅ Reduced by 49%**
- Clean Resolution Rate: 60% (baseline: 55%) — ✅ Improved
```

## Troubleshooting

### Issue: "No test_output.txt found"
- **Cause**: Evaluation hasn't run yet or failed
- **Solution**: Run `evaluate_predictions.py` first

### Issue: "0 tests parsed from output"
- **Cause**: Test output format not recognized
- **Solution**: Check `test_output.txt` manually and update regex patterns

### Issue: "Instance not found in dataset"
- **Cause**: Wrong dataset specified
- **Solution**: Ensure `--dataset` matches the dataset used for predictions

### Issue: "PASS_TO_PASS tests not found"
- **Cause**: Dataset doesn't include test info
- **Solution**: Use SWE-bench Verified (not older SWE-bench versions)

## References

- SWE-bench Paper: https://arxiv.org/abs/2310.06770
- SWE-bench Verified: https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified
- Test Categories: https://www.swebench.com/SWE-bench/guides/evaluation/
