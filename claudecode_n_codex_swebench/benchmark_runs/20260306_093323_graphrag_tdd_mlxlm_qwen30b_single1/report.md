# Benchmark Report: graphrag_tdd_mlxlm_qwen30b_single1
**Date**: 2026-03-06 09:51
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 1

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 1/1 (100%) | 0/1 (0%) | 11m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Graph Guard Pass | Indexed Attempted | Graph Useful | Repo Test Changed | TDD Evidence Pass | TDD Fail-Open | Runtime Fallbacks | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|-------------------|--------------|-------------------|-------------------|---------------|-------------------|------------------|
| graphrag_tdd | 3.00 | 1 | 0.00 | 10.00 | 1 | 1 | 0 | 0 | 1 | 0 | 0 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| astropy-12907 | 1220 chars |

## Timing

### graphrag_tdd
- Total: 10.6 min
- Avg per instance: 637s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260306_093323_graphrag_tdd_mlxlm_qwen30b_single1/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260306_093323_graphrag_tdd_mlxlm_qwen30b_single1/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260306_093323_graphrag_tdd_mlxlm_qwen30b_single1/report.json`
- Progress log: `benchmark_runs/20260306_093323_graphrag_tdd_mlxlm_qwen30b_single1/progress.log`
