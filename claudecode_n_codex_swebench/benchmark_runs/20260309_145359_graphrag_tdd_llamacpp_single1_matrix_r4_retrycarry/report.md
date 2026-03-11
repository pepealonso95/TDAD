# Benchmark Report: graphrag_tdd_llamacpp_single1_matrix_r4_retrycarry
**Date**: 2026-03-09 15:03
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 1

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 0/1 (0%) | 0/1 (0%) | 9m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Graph Guard Pass | Indexed Attempted | Graph Useful | Repo Test Changed | TDD Evidence Pass | TDD Fail-Open | Runtime Fallbacks | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|-------------------|--------------|-------------------|-------------------|---------------|-------------------|------------------|
| graphrag_tdd | 2.00 | 1 | 0.00 | 10.00 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| astropy-12907 | empty |

## Timing

### graphrag_tdd
- Total: 9.0 min
- Avg per instance: 540s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260309_145359_graphrag_tdd_llamacpp_single1_matrix_r4_retrycarry/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260309_145359_graphrag_tdd_llamacpp_single1_matrix_r4_retrycarry/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260309_145359_graphrag_tdd_llamacpp_single1_matrix_r4_retrycarry/report.json`
- Progress log: `benchmark_runs/20260309_145359_graphrag_tdd_llamacpp_single1_matrix_r4_retrycarry/progress.log`
