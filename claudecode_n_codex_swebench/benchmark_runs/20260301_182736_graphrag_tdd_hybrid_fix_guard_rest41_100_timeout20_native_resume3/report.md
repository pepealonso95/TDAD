# Benchmark Report: graphrag_tdd_hybrid_fix_guard_rest41_100_timeout20_native_resume3
**Date**: 2026-03-02 01:41
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 28

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 14/28 (50%) | 6/28 (21%) | 429m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|
| graphrag_tdd | 2.88 | 25 | 0.00 | 9.67 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| django-12143 | 715 chars |
| django-12155 | 679 chars |
| django-12193 | 664 chars |
| django-12209 | empty |
| django-12262 | empty |
| django-12273 | empty |
| django-12276 | 515 chars |
| django-12304 | empty |
| django-12308 | empty |
| django-12325 | empty |
| django-12406 | empty |
| django-12419 | 453 chars |
| django-12663 | 521 chars |
| django-12708 | 1563 chars |
| django-12713 | 2140 chars |
| django-12741 | 904 chars |
| django-12754 | empty |
| django-12774 | empty |
| django-12858 | empty |
| django-12965 | 749 chars |
| django-13012 | empty |
| django-13023 | 605 chars |
| django-13028 | 665 chars |
| django-13033 | empty |
| django-13089 | 994 chars |
| django-13109 | empty |
| django-13112 | 792 chars |
| django-13121 | empty |

## Timing

### graphrag_tdd
- Total: 429.0 min
- Avg per instance: 919s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260301_182736_graphrag_tdd_hybrid_fix_guard_rest41_100_timeout20_native_resume3/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260301_182736_graphrag_tdd_hybrid_fix_guard_rest41_100_timeout20_native_resume3/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260301_182736_graphrag_tdd_hybrid_fix_guard_rest41_100_timeout20_native_resume3/report.json`
- Progress log: `benchmark_runs/20260301_182736_graphrag_tdd_hybrid_fix_guard_rest41_100_timeout20_native_resume3/progress.log`
