# Benchmark Report: top3_strict_softretry
**Date**: 2026-02-18 17:04
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 3

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| vanilla | 3/3 (100%) | 2/3 (66%) | 17m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|
| vanilla | 3.00 | 0 | 0.00 | 0.00 | 0 |

## Per-Instance Comparison

| Instance | vanilla |
|----------|------|
| astropy-13236 | 799 chars |
| astropy-13453 | 379 chars |
| astropy-14309 | 576 chars |

## Timing

### vanilla
- Total: 16.6 min
- Avg per instance: 332s

## Files

- **vanilla** predictions: `benchmark_runs/20260218_164418_top3_strict_softretry/predictions/vanilla.jsonl`
- **vanilla** evaluation: `benchmark_runs/20260218_164418_top3_strict_softretry/evaluations/vanilla.eval.json`
- Full report JSON: `benchmark_runs/20260218_164418_top3_strict_softretry/report.json`
- Progress log: `benchmark_runs/20260218_164418_top3_strict_softretry/progress.log`
