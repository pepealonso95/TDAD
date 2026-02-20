# Benchmark Report: top3_retest_vanilla
**Date**: 2026-02-18 12:07
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 3

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| vanilla | 3/3 (100%) | 1/3 (33%) | 13m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|
| vanilla | 3.00 | 1 | 0.00 | 0.00 | 0 |

## Per-Instance Comparison

| Instance | vanilla |
|----------|------|
| astropy-13236 | 872 chars |
| astropy-13453 | 379 chars |
| astropy-14309 | 585 chars |

## Timing

### vanilla
- Total: 12.7 min
- Avg per instance: 253s

## Files

- **vanilla** predictions: `benchmark_runs/20260218_114951_top3_retest_vanilla/predictions/vanilla.jsonl`
- **vanilla** evaluation: `benchmark_runs/20260218_114951_top3_retest_vanilla/evaluations/vanilla.eval.json`
- Full report JSON: `benchmark_runs/20260218_114951_top3_retest_vanilla/report.json`
- Progress log: `benchmark_runs/20260218_114951_top3_retest_vanilla/progress.log`
