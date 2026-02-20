# Benchmark Report: current_vanilla_10_step30_compile_submit_stop_linecap200
**Date**: 2026-02-18 20:11
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 10

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| vanilla | 8/10 (80%) | 3/10 (30%) | 58m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|
| vanilla | 2.50 | 2 | 0.00 | 0.00 | 0 |

## Per-Instance Comparison

| Instance | vanilla |
|----------|------|
| astropy-12907 | 1348 chars |
| astropy-13033 | 1198 chars |
| astropy-13236 | 799 chars |
| astropy-13398 | empty |
| astropy-13453 | 795 chars |
| astropy-13579 | 653 chars |
| astropy-13977 | 1341 chars |
| astropy-14096 | empty |
| astropy-14182 | 554 chars |
| astropy-14309 | 558 chars |

## Timing

### vanilla
- Total: 58.0 min
- Avg per instance: 348s

## Files

- **vanilla** predictions: `benchmark_runs/20260218_190623_current_vanilla_10_step30_compile_submit_stop_linecap200/predictions/vanilla.jsonl`
- **vanilla** evaluation: `benchmark_runs/20260218_190623_current_vanilla_10_step30_compile_submit_stop_linecap200/evaluations/vanilla.eval.json`
- Full report JSON: `benchmark_runs/20260218_190623_current_vanilla_10_step30_compile_submit_stop_linecap200/report.json`
- Progress log: `benchmark_runs/20260218_190623_current_vanilla_10_step30_compile_submit_stop_linecap200/progress.log`
