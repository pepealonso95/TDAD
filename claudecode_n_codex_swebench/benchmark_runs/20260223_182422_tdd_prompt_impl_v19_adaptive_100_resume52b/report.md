# Benchmark Report: tdd_prompt_impl_v19_adaptive_100_resume52b
**Date**: 2026-02-24 03:11
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 52

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| tdd_prompt | 33/52 (63%) | 17/52 (32%) | 517m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|
| tdd_prompt | 2.83 | 35 | 0.00 | 9.90 | 0 |

## Per-Instance Comparison

| Instance | tdd_prompt |
|----------|------|
| django-11433 | empty |
| django-11451 | 506 chars |
| django-11477 | 660 chars |
| django-11490 | 816 chars |
| django-11532 | 531 chars |
| django-11551 | 2482 chars |
| django-11555 | 969 chars |
| django-11603 | 561 chars |
| django-11728 | 724 chars |
| django-11734 | 1138 chars |
| django-11740 | empty |
| django-11749 | empty |
| django-11790 | 580 chars |
| django-11815 | 846 chars |
| django-11820 | empty |
| django-11848 | 1068 chars |
| django-11880 | 428 chars |
| django-11885 | empty |
| django-11951 | 876 chars |
| django-11964 | empty |
| django-11999 | empty |
| django-12039 | empty |
| django-12050 | 500 chars |
| django-12125 | 599 chars |
| django-12143 | empty |
| django-12155 | 679 chars |
| django-12193 | empty |
| django-12209 | 789 chars |
| django-12262 | 673 chars |
| django-12273 | 769 chars |
| django-12276 | 404 chars |
| django-12304 | 800 chars |
| django-12308 | empty |
| django-12325 | 1049 chars |
| django-12406 | empty |
| django-12419 | 453 chars |
| django-12663 | 521 chars |
| django-12708 | empty |
| django-12713 | empty |
| django-12741 | 2093 chars |
| django-12754 | empty |
| django-12774 | empty |
| django-12858 | empty |
| django-12965 | empty |
| django-13012 | 568 chars |
| django-13023 | 19946 chars |
| django-13028 | 665 chars |
| django-13033 | 885 chars |
| django-13089 | 1590 chars |
| django-13109 | 638 chars |
| django-13112 | 792 chars |
| django-13121 | empty |

## Timing

### tdd_prompt
- Total: 517.1 min
- Avg per instance: 597s

## Files

- **tdd_prompt** predictions: `benchmark_runs/20260223_182422_tdd_prompt_impl_v19_adaptive_100_resume52b/predictions/tdd_prompt.jsonl`
- **tdd_prompt** evaluation: `benchmark_runs/20260223_182422_tdd_prompt_impl_v19_adaptive_100_resume52b/evaluations/tdd_prompt.eval.json`
- Full report JSON: `benchmark_runs/20260223_182422_tdd_prompt_impl_v19_adaptive_100_resume52b/report.json`
- Progress log: `benchmark_runs/20260223_182422_tdd_prompt_impl_v19_adaptive_100_resume52b/progress.log`
