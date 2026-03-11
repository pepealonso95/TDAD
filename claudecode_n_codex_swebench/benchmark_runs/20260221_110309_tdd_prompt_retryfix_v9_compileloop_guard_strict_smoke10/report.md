# Benchmark Report: tdd_prompt_retryfix_v9_compileloop_guard_strict_smoke10
**Date**: 2026-02-21 13:32
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 10

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| tdd_prompt | 9/10 (90%) | 2/10 (20%) | 140m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|
| tdd_prompt | 3.00 | 4 | 0.00 | 9.80 | 0 |

## Per-Instance Comparison

| Instance | tdd_prompt |
|----------|------|
| astropy-12907 | 534 chars |
| astropy-13033 | 1177 chars |
| astropy-13236 | empty |
| astropy-13398 | 3467 chars |
| astropy-13453 | 601 chars |
| astropy-13579 | 653 chars |
| astropy-13977 | 1090 chars |
| astropy-14096 | 544 chars |
| astropy-14182 | 1566 chars |
| astropy-14309 | 549 chars |

## Timing

### tdd_prompt
- Total: 139.9 min
- Avg per instance: 839s

## Files

- **tdd_prompt** predictions: `benchmark_runs/20260221_110309_tdd_prompt_retryfix_v9_compileloop_guard_strict_smoke10/predictions/tdd_prompt.jsonl`
- **tdd_prompt** evaluation: `benchmark_runs/20260221_110309_tdd_prompt_retryfix_v9_compileloop_guard_strict_smoke10/evaluations/tdd_prompt.eval.json`
- Full report JSON: `benchmark_runs/20260221_110309_tdd_prompt_retryfix_v9_compileloop_guard_strict_smoke10/report.json`
- Progress log: `benchmark_runs/20260221_110309_tdd_prompt_retryfix_v9_compileloop_guard_strict_smoke10/progress.log`
