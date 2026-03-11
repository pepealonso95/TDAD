# Benchmark Report: graphrag_tdd_llamacpp_ctx32_defaultcstack_first10
**Date**: 2026-03-09 19:22
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 10

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 8/10 (80%) | 2/10 (20%) | 93m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Graph Guard Pass | Indexed Attempted | Graph Useful | Repo Test Changed | TDD Evidence Pass | TDD Fail-Open | Runtime Fallbacks | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|-------------------|--------------|-------------------|-------------------|---------------|-------------------|------------------|
| graphrag_tdd | 2.80 | 10 | 0.00 | 9.80 | 10 | 8 | 0 | 0 | 10 | 0 | 0 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| astropy-12907 | empty |
| astropy-13033 | 1169 chars |
| astropy-13236 | 848 chars |
| astropy-13398 | 3149 chars |
| astropy-13453 | 637 chars |
| astropy-13579 | 900 chars |
| astropy-13977 | empty |
| astropy-14096 | 669 chars |
| astropy-14182 | 554 chars |
| astropy-14309 | 576 chars |

## Timing

### graphrag_tdd
- Total: 93.0 min
- Avg per instance: 558s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260309_174704_graphrag_tdd_llamacpp_ctx32_defaultcstack_first10/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260309_174704_graphrag_tdd_llamacpp_ctx32_defaultcstack_first10/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260309_174704_graphrag_tdd_llamacpp_ctx32_defaultcstack_first10/report.json`
- Progress log: `benchmark_runs/20260309_174704_graphrag_tdd_llamacpp_ctx32_defaultcstack_first10/progress.log`
