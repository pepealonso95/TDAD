# Benchmark Report: graphrag_tdd_runtime_guardrails_smoke1
**Date**: 2026-03-03 15:21
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 1

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 0/1 (0%) | 0/1 (0%) | 6m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Graph Guard Pass | Indexed Attempted | Repo Test Changed | TDD Evidence Pass | TDD Fail-Open | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|-------------------|-------------------|-------------------|---------------|------------------|
| graphrag_tdd | 2.00 | 1 | 0.00 | 10.00 | 0 | 1 | 0 | 0 | 1 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| astropy-12907 | empty |

## Timing

### graphrag_tdd
- Total: 5.6 min
- Avg per instance: 339s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260303_151521_graphrag_tdd_runtime_guardrails_smoke1/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260303_151521_graphrag_tdd_runtime_guardrails_smoke1/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260303_151521_graphrag_tdd_runtime_guardrails_smoke1/report.json`
- Progress log: `benchmark_runs/20260303_151521_graphrag_tdd_runtime_guardrails_smoke1/progress.log`
