# Benchmark Report: graphrag_tdd_mlxlm_thinking_runtimefix_single1_retry1
**Date**: 2026-03-06 10:52
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 1

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 0/1 (0%) | 0/1 (0%) | 1m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Graph Guard Pass | Indexed Attempted | Graph Useful | Repo Test Changed | TDD Evidence Pass | TDD Fail-Open | Runtime Fallbacks | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|-------------------|--------------|-------------------|-------------------|---------------|-------------------|------------------|
| graphrag_tdd | 1.00 | 1 | 0.00 | 0.00 | 1 | 0 | 0 | 0 | 1 | 0 | 1 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| astropy-12907 | empty |

## Timing

### graphrag_tdd
- Total: 0.6 min
- Avg per instance: 36s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260306_105203_graphrag_tdd_mlxlm_thinking_runtimefix_single1_retry1/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260306_105203_graphrag_tdd_mlxlm_thinking_runtimefix_single1_retry1/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260306_105203_graphrag_tdd_mlxlm_thinking_runtimefix_single1_retry1/report.json`
- Progress log: `benchmark_runs/20260306_105203_graphrag_tdd_mlxlm_thinking_runtimefix_single1_retry1/progress.log`
