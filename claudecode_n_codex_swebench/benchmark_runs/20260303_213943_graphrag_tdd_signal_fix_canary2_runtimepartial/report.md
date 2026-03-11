# Benchmark Report: graphrag_tdd_signal_fix_canary2_runtimepartial
**Date**: 2026-03-03 21:47
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 1

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 1/1 (100%) | 1/1 (100%) | 5m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Graph Guard Pass | Indexed Attempted | Graph Useful | Repo Test Changed | TDD Evidence Pass | TDD Fail-Open | Runtime Fallbacks | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|-------------------|--------------|-------------------|-------------------|---------------|-------------------|------------------|
| graphrag_tdd | 1.00 | 0 | 0.00 | 10.00 | 1 | 1 | 0 | 0 | 1 | 1 | 1 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| astropy-12907 | 506 chars |

## Timing

### graphrag_tdd
- Total: 5.5 min
- Avg per instance: 329s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260303_213943_graphrag_tdd_signal_fix_canary2_runtimepartial/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260303_213943_graphrag_tdd_signal_fix_canary2_runtimepartial/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260303_213943_graphrag_tdd_signal_fix_canary2_runtimepartial/report.json`
- Progress log: `benchmark_runs/20260303_213943_graphrag_tdd_signal_fix_canary2_runtimepartial/progress.log`
