# Benchmark Report: graphrag_tdd_single_post_revert_qwen30
**Date**: 2026-03-05 09:33
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 1

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 1/1 (100%) | 0/1 (0%) | 14m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Graph Guard Pass | Indexed Attempted | Graph Useful | Repo Test Changed | TDD Evidence Pass | TDD Fail-Open | Runtime Fallbacks | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|-------------------|--------------|-------------------|-------------------|---------------|-------------------|------------------|
| graphrag_tdd | 3.00 | 0 | 0.00 | 10.00 | 1 | 1 | 0 | 1 | 1 | 0 | 0 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| astropy-12907 | 506 chars |

## Timing

### graphrag_tdd
- Total: 13.9 min
- Avg per instance: 835s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260305_091928_graphrag_tdd_single_post_revert_qwen30/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260305_091928_graphrag_tdd_single_post_revert_qwen30/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260305_091928_graphrag_tdd_single_post_revert_qwen30/report.json`
- Progress log: `benchmark_runs/20260305_091928_graphrag_tdd_single_post_revert_qwen30/progress.log`
