# Benchmark Report: tdd_prompt_retryfix_v4_smoke10_clean
**Date**: 2026-02-20 22:38
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 10

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| tdd_prompt | 5/10 (50%) | 3/10 (30%) | 47m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|
| tdd_prompt | 2.50 | 6 | 0.00 | 9.80 | 0 |

## Per-Instance Comparison

| Instance | tdd_prompt |
|----------|------|
| astropy-12907 | 1166 chars |
| astropy-13033 | 946 chars |
| astropy-13236 | empty |
| astropy-13398 | empty |
| astropy-13453 | 537 chars |
| astropy-13579 | 653 chars |
| astropy-13977 | empty |
| astropy-14096 | empty |
| astropy-14182 | empty |
| astropy-14309 | 558 chars |

## Timing

### tdd_prompt
- Total: 46.6 min
- Avg per instance: 280s

## Files

- **tdd_prompt** predictions: `benchmark_runs/20260220_214713_tdd_prompt_retryfix_v4_smoke10_clean/predictions/tdd_prompt.jsonl`
- **tdd_prompt** evaluation: `benchmark_runs/20260220_214713_tdd_prompt_retryfix_v4_smoke10_clean/evaluations/tdd_prompt.eval.json`
- Full report JSON: `benchmark_runs/20260220_214713_tdd_prompt_retryfix_v4_smoke10_clean/report.json`
- Progress log: `benchmark_runs/20260220_214713_tdd_prompt_retryfix_v4_smoke10_clean/progress.log`
