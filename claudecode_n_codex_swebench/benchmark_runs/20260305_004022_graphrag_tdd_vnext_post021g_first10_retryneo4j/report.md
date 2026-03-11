# Benchmark Report: graphrag_tdd_vnext_post021g_first10_retryneo4j
**Date**: 2026-03-05 02:21
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 10

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 3/10 (30%) | 0/10 (0%) | 101m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Graph Guard Pass | Indexed Attempted | Graph Useful | Repo Test Changed | TDD Evidence Pass | TDD Fail-Open | Runtime Fallbacks | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|-------------------|--------------|-------------------|-------------------|---------------|-------------------|------------------|
| graphrag_tdd | 3.00 | 8 | 0.00 | 9.80 | 3 | 10 | 1 | 1 | 10 | 10 | 10 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| astropy-12907 | 506 chars |
| astropy-13033 | 4269 chars |
| astropy-13236 | empty |
| astropy-13398 | empty |
| astropy-13453 | empty |
| astropy-13579 | empty |
| astropy-13977 | empty |
| astropy-14096 | 3073 chars |
| astropy-14182 | empty |
| astropy-14309 | empty |

## Timing

### graphrag_tdd
- Total: 101.0 min
- Avg per instance: 606s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260305_004022_graphrag_tdd_vnext_post021g_first10_retryneo4j/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260305_004022_graphrag_tdd_vnext_post021g_first10_retryneo4j/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260305_004022_graphrag_tdd_vnext_post021g_first10_retryneo4j/report.json`
- Progress log: `benchmark_runs/20260305_004022_graphrag_tdd_vnext_post021g_first10_retryneo4j/progress.log`
