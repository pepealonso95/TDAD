# Benchmark Report: graphrag_tdd_mlxlm_thinking_runtimefix_single1_retry2_failopen
**Date**: 2026-03-06 11:08
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 1

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 1/1 (100%) | 0/1 (0%) | 7m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Graph Guard Pass | Indexed Attempted | Graph Useful | Repo Test Changed | TDD Evidence Pass | TDD Fail-Open | Runtime Fallbacks | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|-------------------|--------------|-------------------|-------------------|---------------|-------------------|------------------|
| graphrag_tdd | 3.00 | 1 | 0.00 | 10.00 | 1 | 1 | 0 | 0 | 1 | 0 | 1 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| astropy-12907 | 889 chars |

## Timing

### graphrag_tdd
- Total: 7.1 min
- Avg per instance: 427s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260306_105401_graphrag_tdd_mlxlm_thinking_runtimefix_single1_retry2_failopen/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260306_105401_graphrag_tdd_mlxlm_thinking_runtimefix_single1_retry2_failopen/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260306_105401_graphrag_tdd_mlxlm_thinking_runtimefix_single1_retry2_failopen/report.json`
- Progress log: `benchmark_runs/20260306_105401_graphrag_tdd_mlxlm_thinking_runtimefix_single1_retry2_failopen/progress.log`
