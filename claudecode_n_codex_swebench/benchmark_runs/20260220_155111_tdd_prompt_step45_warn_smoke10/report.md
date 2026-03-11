# Benchmark Report: tdd_prompt_step45_warn_smoke10
**Date**: 2026-02-20 16:52
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 10

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| tdd_prompt | 9/10 (90%) | 2/10 (20%) | 52m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|
| tdd_prompt | 1.70 | 4 | 0.00 | 9.80 | 0 |

## Per-Instance Comparison

| Instance | tdd_prompt |
|----------|------|
| astropy-12907 | 366 chars |
| astropy-13033 | 1198 chars |
| astropy-13236 | 799 chars |
| astropy-13398 | 4024 chars |
| astropy-13453 | 379 chars |
| astropy-13579 | 654 chars |
| astropy-13977 | 865 chars |
| astropy-14096 | empty |
| astropy-14182 | 2081 chars |
| astropy-14309 | 558 chars |

## Timing

### tdd_prompt
- Total: 51.8 min
- Avg per instance: 311s

## Files

- **tdd_prompt** predictions: `benchmark_runs/20260220_155111_tdd_prompt_step45_warn_smoke10/predictions/tdd_prompt.jsonl`
- **tdd_prompt** evaluation: `benchmark_runs/20260220_155111_tdd_prompt_step45_warn_smoke10/evaluations/tdd_prompt.eval.json`
- Full report JSON: `benchmark_runs/20260220_155111_tdd_prompt_step45_warn_smoke10/report.json`
- Progress log: `benchmark_runs/20260220_155111_tdd_prompt_step45_warn_smoke10/progress.log`
