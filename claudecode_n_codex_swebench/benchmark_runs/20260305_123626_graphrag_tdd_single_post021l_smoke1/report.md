# Benchmark Report: graphrag_tdd_single_post021l_smoke1
**Date**: 2026-03-05 13:02
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 1

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 1/1 (100%) | 0/1 (0%) | 19m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Graph Guard Pass | Indexed Attempted | Graph Useful | Repo Test Changed | TDD Evidence Pass | TDD Fail-Open | Runtime Fallbacks | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|-------------------|--------------|-------------------|-------------------|---------------|-------------------|------------------|
| graphrag_tdd | 3.00 | 1 | 0.00 | 10.00 | 1 | 1 | 0 | 1 | 1 | 0 | 0 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| astropy-12907 | 1272 chars |

## Timing

### graphrag_tdd
- Total: 18.8 min
- Avg per instance: 1130s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260305_123626_graphrag_tdd_single_post021l_smoke1/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260305_123626_graphrag_tdd_single_post021l_smoke1/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260305_123626_graphrag_tdd_single_post021l_smoke1/report.json`
- Progress log: `benchmark_runs/20260305_123626_graphrag_tdd_single_post021l_smoke1/progress.log`
