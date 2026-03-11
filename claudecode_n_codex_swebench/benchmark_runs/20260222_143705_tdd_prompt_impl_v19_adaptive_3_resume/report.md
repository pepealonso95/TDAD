# Benchmark Report: tdd_prompt_impl_v19_adaptive_3_resume
**Date**: 2026-02-22 14:49
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 3

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| tdd_prompt | 3/3 (100%) | 1/3 (33%) | 9m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|
| tdd_prompt | 2.33 | 1 | 0.00 | 9.67 | 0 |

## Per-Instance Comparison

| Instance | tdd_prompt |
|----------|------|
| astropy-14096 | 517 chars |
| astropy-14182 | 554 chars |
| astropy-14309 | 576 chars |

## Timing

### tdd_prompt
- Total: 8.9 min
- Avg per instance: 178s

## Files

- **tdd_prompt** predictions: `benchmark_runs/20260222_143705_tdd_prompt_impl_v19_adaptive_3_resume/predictions/tdd_prompt.jsonl`
- **tdd_prompt** evaluation: `benchmark_runs/20260222_143705_tdd_prompt_impl_v19_adaptive_3_resume/evaluations/tdd_prompt.eval.json`
- Full report JSON: `benchmark_runs/20260222_143705_tdd_prompt_impl_v19_adaptive_3_resume/report.json`
- Progress log: `benchmark_runs/20260222_143705_tdd_prompt_impl_v19_adaptive_3_resume/progress.log`
