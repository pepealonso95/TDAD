# Benchmark Report: graphrag_tdd_advisory_repair_relaxed_missed6
**Date**: 2026-03-10 15:52
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 6

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 5/6 (83%) | 2/6 (33%) | 51m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Graph Guard Pass | Indexed Attempted | Graph Useful | Repo Test Changed | TDD Evidence Pass | TDD Fail-Open | Runtime Fallbacks | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|-------------------|--------------|-------------------|-------------------|---------------|-------------------|------------------|
| graphrag_tdd | 2.83 | 4 | 0.00 | 8.67 | 6 | 5 | 0 | 0 | 6 | 0 | 0 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| astropy-7166 | 537 chars |
| django-11815 | 796 chars |
| django-12155 | 679 chars |
| django-12708 | empty |
| django-12741 | 904 chars |
| django-13109 | 1580 chars |

## Timing

### graphrag_tdd
- Total: 51.3 min
- Avg per instance: 513s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260310_145624_graphrag_tdd_advisory_repair_relaxed_missed6/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260310_145624_graphrag_tdd_advisory_repair_relaxed_missed6/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260310_145624_graphrag_tdd_advisory_repair_relaxed_missed6/report.json`
- Progress log: `benchmark_runs/20260310_145624_graphrag_tdd_advisory_repair_relaxed_missed6/progress.log`
