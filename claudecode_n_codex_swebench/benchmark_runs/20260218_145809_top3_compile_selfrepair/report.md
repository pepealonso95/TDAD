# Benchmark Report: top3_compile_selfrepair
**Date**: 2026-02-18 15:20
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 3

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| vanilla | 2/3 (66%) | 1/3 (33%) | 20m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|
| vanilla | 3.00 | 2 | 0.00 | 0.00 | 0 |

## Per-Instance Comparison

| Instance | vanilla |
|----------|------|
| astropy-13236 | empty |
| astropy-13453 | 379 chars |
| astropy-14309 | 585 chars |

## Timing

### vanilla
- Total: 20.5 min
- Avg per instance: 410s

## Files

- **vanilla** predictions: `benchmark_runs/20260218_145809_top3_compile_selfrepair/predictions/vanilla.jsonl`
- **vanilla** evaluation: `benchmark_runs/20260218_145809_top3_compile_selfrepair/evaluations/vanilla.eval.json`
- Full report JSON: `benchmark_runs/20260218_145809_top3_compile_selfrepair/report.json`
- Progress log: `benchmark_runs/20260218_145809_top3_compile_selfrepair/progress.log`
