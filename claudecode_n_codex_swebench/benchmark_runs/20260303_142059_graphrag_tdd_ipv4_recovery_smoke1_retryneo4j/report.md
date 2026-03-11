# Benchmark Report: graphrag_tdd_ipv4_recovery_smoke1_retryneo4j
**Date**: 2026-03-03 14:35
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 1

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 0/1 (0%) | 0/1 (0%) | 14m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Graph Guard Pass | Indexed Attempted | Repo Test Changed | TDD Evidence Pass | TDD Fail-Open | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|-------------------|-------------------|-------------------|---------------|------------------|
| graphrag_tdd | 3.00 | 1 | 0.00 | 10.00 | 1 | 1 | 0 | 0 | 0 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| astropy-12907 | empty |

## Timing

### graphrag_tdd
- Total: 13.9 min
- Avg per instance: 836s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260303_142059_graphrag_tdd_ipv4_recovery_smoke1_retryneo4j/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260303_142059_graphrag_tdd_ipv4_recovery_smoke1_retryneo4j/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260303_142059_graphrag_tdd_ipv4_recovery_smoke1_retryneo4j/report.json`
- Progress log: `benchmark_runs/20260303_142059_graphrag_tdd_ipv4_recovery_smoke1_retryneo4j/progress.log`
