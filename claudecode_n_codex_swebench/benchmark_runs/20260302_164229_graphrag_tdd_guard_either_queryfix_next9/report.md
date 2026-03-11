# Benchmark Report: graphrag_tdd_guard_either_queryfix_next9
**Date**: 2026-03-02 19:19
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 9

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 8/9 (88%) | 2/9 (22%) | 143m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Graph Guard Pass | Indexed Attempted | Repo Test Changed | TDD Evidence Pass | TDD Fail-Open | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|-------------------|-------------------|-------------------|---------------|------------------|
| graphrag_tdd | 2.56 | 5 | 0.00 | 9.78 | 9 | 9 | 0 | 9 | 9 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| astropy-13033 | 1198 chars |
| astropy-13236 | 799 chars |
| astropy-13398 | 3849 chars |
| astropy-13453 | 379 chars |
| astropy-13579 | 1998 chars |
| astropy-13977 | empty |
| astropy-14096 | 1004 chars |
| astropy-14182 | 554 chars |
| astropy-14309 | 483 chars |

## Timing

### graphrag_tdd
- Total: 143.5 min
- Avg per instance: 957s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260302_164229_graphrag_tdd_guard_either_queryfix_next9/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260302_164229_graphrag_tdd_guard_either_queryfix_next9/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260302_164229_graphrag_tdd_guard_either_queryfix_next9/report.json`
- Progress log: `benchmark_runs/20260302_164229_graphrag_tdd_guard_either_queryfix_next9/progress.log`
