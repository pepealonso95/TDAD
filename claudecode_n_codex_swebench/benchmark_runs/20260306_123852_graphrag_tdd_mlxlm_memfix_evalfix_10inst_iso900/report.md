# Benchmark Report: graphrag_tdd_mlxlm_memfix_evalfix_10inst_iso900
**Date**: 2026-03-06 14:33
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 10

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 3/10 (30%) | 1/10 (10%) | 108m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Graph Guard Pass | Indexed Attempted | Graph Useful | Repo Test Changed | TDD Evidence Pass | TDD Fail-Open | Runtime Fallbacks | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|-------------------|--------------|-------------------|-------------------|---------------|-------------------|------------------|
| graphrag_tdd | 2.50 | 6 | 0.00 | 10.00 | 6 | 3 | 0 | 0 | 6 | 0 | 6 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| astropy-12907 | 1070 chars |
| astropy-13033 | empty |
| astropy-13236 | 799 chars |
| astropy-13398 | empty |
| astropy-13453 | empty |
| astropy-13579 | 653 chars |
| astropy-13977 | empty |
| astropy-14096 | empty |
| astropy-14182 | empty |
| astropy-14309 | empty |

## Timing

### graphrag_tdd
- Total: 107.8 min
- Avg per instance: 647s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260306_123852_graphrag_tdd_mlxlm_memfix_evalfix_10inst_iso900/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260306_123852_graphrag_tdd_mlxlm_memfix_evalfix_10inst_iso900/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260306_123852_graphrag_tdd_mlxlm_memfix_evalfix_10inst_iso900/report.json`
- Progress log: `benchmark_runs/20260306_123852_graphrag_tdd_mlxlm_memfix_evalfix_10inst_iso900/progress.log`
