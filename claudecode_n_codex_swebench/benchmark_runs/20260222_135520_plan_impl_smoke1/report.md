# Benchmark Report: plan_impl_smoke1
**Date**: 2026-02-22 13:56
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 1

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| tdd_prompt | 1/1 (100%) | not evaluated | 1m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|
| tdd_prompt | 1.00 | 0 | 0.00 | 10.00 | 0 |

## Per-Instance Comparison

| Instance | tdd_prompt |
|----------|------|
| astropy-14309 | 576 chars |

## Timing

### tdd_prompt
- Total: 1.1 min
- Avg per instance: 68s

## Files

- **tdd_prompt** predictions: `benchmark_runs/20260222_135520_plan_impl_smoke1/predictions/tdd_prompt.jsonl`
- Full report JSON: `benchmark_runs/20260222_135520_plan_impl_smoke1/report.json`
- Progress log: `benchmark_runs/20260222_135520_plan_impl_smoke1/progress.log`
