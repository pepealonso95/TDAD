# Benchmark Report: graphrag_tdd_hybrid_fix_guard_first20
**Date**: 2026-02-27 02:39
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 20

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 17/20 (85%) | 6/20 (30%) | 251m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|
| graphrag_tdd | 2.70 | 11 | 0.00 | 9.25 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| astropy-12907 | 987 chars |
| astropy-13033 | 1198 chars |
| astropy-13236 | 863 chars |
| astropy-13398 | 1037 chars |
| astropy-13453 | 383 chars |
| astropy-13579 | 1187 chars |
| astropy-13977 | 1619 chars |
| astropy-14096 | 592 chars |
| astropy-14182 | 802 chars |
| astropy-14309 | 601 chars |
| astropy-14365 | 497 chars |
| astropy-14369 | 759 chars |
| astropy-14508 | 483 chars |
| astropy-14539 | 532 chars |
| astropy-14598 | empty |
| astropy-14995 | 628 chars |
| astropy-7166 | 537 chars |
| astropy-7336 | 901 chars |
| astropy-7606 | empty |
| astropy-7671 | empty |

## Timing

### graphrag_tdd
- Total: 250.5 min
- Avg per instance: 752s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260226_221531_graphrag_tdd_hybrid_fix_guard_first20/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260226_221531_graphrag_tdd_hybrid_fix_guard_first20/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260226_221531_graphrag_tdd_hybrid_fix_guard_first20/report.json`
- Progress log: `benchmark_runs/20260226_221531_graphrag_tdd_hybrid_fix_guard_first20/progress.log`
