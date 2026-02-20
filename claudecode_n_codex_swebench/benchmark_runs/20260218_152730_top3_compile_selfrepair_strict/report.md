# Benchmark Report: top3_compile_selfrepair_strict
**Date**: 2026-02-18 15:42
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 3

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| vanilla | 2/3 (66%) | 1/3 (33%) | 13m |

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
- Total: 13.1 min
- Avg per instance: 262s

## Files

- **vanilla** predictions: `benchmark_runs/20260218_152730_top3_compile_selfrepair_strict/predictions/vanilla.jsonl`
- **vanilla** evaluation: `benchmark_runs/20260218_152730_top3_compile_selfrepair_strict/evaluations/vanilla.eval.json`
- Full report JSON: `benchmark_runs/20260218_152730_top3_compile_selfrepair_strict/report.json`
- Progress log: `benchmark_runs/20260218_152730_top3_compile_selfrepair_strict/progress.log`
