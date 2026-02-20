# Benchmark Report: top3_retest_vanilla_12ddefaults
**Date**: 2026-02-18 14:32
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 3

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| vanilla | 3/3 (100%) | 2/3 (66%) | 5m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|
| vanilla | 1.00 | 2 | 0.00 | 0.00 | 0 |

## Per-Instance Comparison

| Instance | vanilla |
|----------|------|
| astropy-13236 | 848 chars |
| astropy-13453 | 608 chars |
| astropy-14309 | 585 chars |

## Timing

### vanilla
- Total: 5.4 min
- Avg per instance: 108s

## Files

- **vanilla** predictions: `benchmark_runs/20260218_142132_top3_retest_vanilla_12ddefaults/predictions/vanilla.jsonl`
- **vanilla** evaluation: `benchmark_runs/20260218_142132_top3_retest_vanilla_12ddefaults/evaluations/vanilla.eval.json`
- Full report JSON: `benchmark_runs/20260218_142132_top3_retest_vanilla_12ddefaults/report.json`
- Progress log: `benchmark_runs/20260218_142132_top3_retest_vanilla_12ddefaults/progress.log`
