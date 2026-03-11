# Benchmark Report: graphrag_tdd_advisory_canary4_django11066
**Date**: 2026-03-09 23:15
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 1

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 1/1 (100%) | 1/1 (100%) | 5m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Graph Guard Pass | Indexed Attempted | Graph Useful | Repo Test Changed | TDD Evidence Pass | TDD Fail-Open | Runtime Fallbacks | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|-------------------|--------------|-------------------|-------------------|---------------|-------------------|------------------|
| graphrag_tdd | 3.00 | 1 | 0.00 | 3.00 | 1 | 1 | 0 | 0 | 1 | 0 | 0 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| django-11066 | 767 chars |

## Timing

### graphrag_tdd
- Total: 5.0 min
- Avg per instance: 297s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260309_230810_graphrag_tdd_advisory_canary4_django11066/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260309_230810_graphrag_tdd_advisory_canary4_django11066/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260309_230810_graphrag_tdd_advisory_canary4_django11066/report.json`
- Progress log: `benchmark_runs/20260309_230810_graphrag_tdd_advisory_canary4_django11066/progress.log`
