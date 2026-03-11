# Benchmark Report: graphrag_tdd_advisory_next50_51_100
**Date**: 2026-03-10 14:35
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 50

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 36/50 (72%) | 13/50 (26%) | 460m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Graph Guard Pass | Indexed Attempted | Graph Useful | Repo Test Changed | TDD Evidence Pass | TDD Fail-Open | Runtime Fallbacks | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|-------------------|--------------|-------------------|-------------------|---------------|-------------------|------------------|
| graphrag_tdd | 2.72 | 48 | 0.00 | 9.90 | 50 | 38 | 0 | 0 | 50 | 0 | 0 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| django-11477 | empty |
| django-11490 | 844 chars |
| django-11532 | 504 chars |
| django-11551 | empty |
| django-11555 | empty |
| django-11603 | 561 chars |
| django-11728 | 724 chars |
| django-11734 | empty |
| django-11740 | empty |
| django-11749 | 1293 chars |
| django-11790 | 712 chars |
| django-11815 | 850 chars |
| django-11820 | empty |
| django-11848 | 935 chars |
| django-11880 | 428 chars |
| django-11885 | 2553 chars |
| django-11951 | 862 chars |
| django-11964 | 668 chars |
| django-11999 | empty |
| django-12039 | 674 chars |
| django-12050 | 500 chars |
| django-12125 | 745 chars |
| django-12143 | empty |
| django-12155 | 675 chars |
| django-12193 | empty |
| django-12209 | 804 chars |
| django-12262 | 575 chars |
| django-12273 | empty |
| django-12276 | empty |
| django-12304 | 800 chars |
| django-12308 | 834 chars |
| django-12325 | 1142 chars |
| django-12406 | 622 chars |
| django-12419 | 453 chars |
| django-12663 | 521 chars |
| django-12708 | 1284 chars |
| django-12713 | 1868 chars |
| django-12741 | 904 chars |
| django-12754 | empty |
| django-12774 | 1277 chars |
| django-12858 | 673 chars |
| django-12965 | empty |
| django-13012 | 545 chars |
| django-13023 | 711 chars |
| django-13028 | 665 chars |
| django-13033 | 885 chars |
| django-13089 | empty |
| django-13109 | 1580 chars |
| django-13112 | 792 chars |
| django-13121 | 612 chars |

## Timing

### graphrag_tdd
- Total: 460.2 min
- Avg per instance: 552s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260310_064159_graphrag_tdd_advisory_next50_51_100/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260310_064159_graphrag_tdd_advisory_next50_51_100/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260310_064159_graphrag_tdd_advisory_next50_51_100/report.json`
- Progress log: `benchmark_runs/20260310_064159_graphrag_tdd_advisory_next50_51_100/progress.log`
