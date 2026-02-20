# Benchmark Report: current_vanilla_10_step30_compile_submit_stop
**Date**: 2026-02-18 18:36
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 10

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| vanilla | 10/10 (100%) | 2/10 (20%) | 40m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|
| vanilla | 1.70 | 0 | 0.00 | 0.00 | 0 |

## Per-Instance Comparison

| Instance | vanilla |
|----------|------|
| astropy-12907 | 506 chars |
| astropy-13033 | 1198 chars |
| astropy-13236 | 1061 chars |
| astropy-13398 | 3503 chars |
| astropy-13453 | 2615 chars |
| astropy-13579 | 1902 chars |
| astropy-13977 | 1108 chars |
| astropy-14096 | 605 chars |
| astropy-14182 | 624 chars |
| astropy-14309 | 585 chars |

## Timing

### vanilla
- Total: 40.5 min
- Avg per instance: 243s

## Files

- **vanilla** predictions: `benchmark_runs/20260218_174616_current_vanilla_10_step30_compile_submit_stop/predictions/vanilla.jsonl`
- **vanilla** evaluation: `benchmark_runs/20260218_174616_current_vanilla_10_step30_compile_submit_stop/evaluations/vanilla.eval.json`
- Full report JSON: `benchmark_runs/20260218_174616_current_vanilla_10_step30_compile_submit_stop/report.json`
- Progress log: `benchmark_runs/20260218_174616_current_vanilla_10_step30_compile_submit_stop/progress.log`
