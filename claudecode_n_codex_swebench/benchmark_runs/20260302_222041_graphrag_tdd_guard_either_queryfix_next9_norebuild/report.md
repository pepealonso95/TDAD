# Benchmark Report: graphrag_tdd_guard_either_queryfix_next9_norebuild
**Date**: 2026-03-03 00:57
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 9

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 8/9 (88%) | 2/9 (22%) | 143m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Graph Guard Pass | Indexed Attempted | Repo Test Changed | TDD Evidence Pass | TDD Fail-Open | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|-------------------|-------------------|-------------------|---------------|------------------|
| graphrag_tdd | 2.44 | 3 | 0.00 | 9.78 | 9 | 9 | 0 | 9 | 9 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| astropy-13033 | 1177 chars |
| astropy-13236 | 799 chars |
| astropy-13398 | 3561 chars |
| astropy-13453 | 379 chars |
| astropy-13579 | empty |
| astropy-13977 | 1058 chars |
| astropy-14096 | 1452 chars |
| astropy-14182 | 644 chars |
| astropy-14309 | 483 chars |

## Timing

### graphrag_tdd
- Total: 142.9 min
- Avg per instance: 952s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260302_222041_graphrag_tdd_guard_either_queryfix_next9_norebuild/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260302_222041_graphrag_tdd_guard_either_queryfix_next9_norebuild/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260302_222041_graphrag_tdd_guard_either_queryfix_next9_norebuild/report.json`
- Progress log: `benchmark_runs/20260302_222041_graphrag_tdd_guard_either_queryfix_next9_norebuild/progress.log`
