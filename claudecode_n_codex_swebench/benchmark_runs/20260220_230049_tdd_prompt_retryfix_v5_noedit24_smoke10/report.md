# Benchmark Report: tdd_prompt_retryfix_v5_noedit24_smoke10
**Date**: 2026-02-21 00:11
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 10

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| tdd_prompt | 10/10 (100%) | 2/10 (20%) | 61m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|
| tdd_prompt | 1.80 | 2 | 0.00 | 9.80 | 0 |

## Per-Instance Comparison

| Instance | tdd_prompt |
|----------|------|
| astropy-12907 | 506 chars |
| astropy-13033 | 761 chars |
| astropy-13236 | 984 chars |
| astropy-13398 | 3488 chars |
| astropy-13453 | 379 chars |
| astropy-13579 | 726 chars |
| astropy-13977 | 716 chars |
| astropy-14096 | 2007 chars |
| astropy-14182 | 1502 chars |
| astropy-14309 | 585 chars |

## Timing

### tdd_prompt
- Total: 61.3 min
- Avg per instance: 368s

## Files

- **tdd_prompt** predictions: `benchmark_runs/20260220_230049_tdd_prompt_retryfix_v5_noedit24_smoke10/predictions/tdd_prompt.jsonl`
- **tdd_prompt** evaluation: `benchmark_runs/20260220_230049_tdd_prompt_retryfix_v5_noedit24_smoke10/evaluations/tdd_prompt.eval.json`
- Full report JSON: `benchmark_runs/20260220_230049_tdd_prompt_retryfix_v5_noedit24_smoke10/report.json`
- Progress log: `benchmark_runs/20260220_230049_tdd_prompt_retryfix_v5_noedit24_smoke10/progress.log`
