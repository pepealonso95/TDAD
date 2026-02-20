# Benchmark Report: current_vanilla_100_step30_compile_submit_stop_linecap200_resume42_after_dns_restore
**Date**: 2026-02-20 02:06
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 42

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| vanilla | 34/42 (80%) | 15/42 (35%) | 662m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|
| vanilla | 2.21 | 9 | 0.00 | 0.00 | 0 |

## Per-Instance Comparison

| Instance | vanilla |
|----------|------|
| django-11740 | empty |
| django-11749 | 1389 chars |
| django-11790 | empty |
| django-11815 | 794 chars |
| django-11820 | 686 chars |
| django-11848 | 984 chars |
| django-11880 | 591 chars |
| django-11885 | empty |
| django-11951 | 868 chars |
| django-11964 | empty |
| django-11999 | 1180 chars |
| django-12039 | 674 chars |
| django-12050 | 500 chars |
| django-12125 | 599 chars |
| django-12143 | 715 chars |
| django-12155 | 675 chars |
| django-12193 | 1347 chars |
| django-12209 | 1193 chars |
| django-12262 | 681 chars |
| django-12273 | empty |
| django-12276 | 461 chars |
| django-12304 | 830 chars |
| django-12308 | 833 chars |
| django-12325 | 1553 chars |
| django-12406 | empty |
| django-12419 | 453 chars |
| django-12663 | 521 chars |
| django-12708 | 2028 chars |
| django-12713 | 1868 chars |
| django-12741 | empty |
| django-12754 | 1203 chars |
| django-12774 | 775 chars |
| django-12858 | empty |
| django-12965 | 1530 chars |
| django-13012 | 2574 chars |
| django-13023 | 605 chars |
| django-13028 | 665 chars |
| django-13033 | 885 chars |
| django-13089 | 612 chars |
| django-13109 | 638 chars |
| django-13112 | 792 chars |
| django-13121 | 964 chars |

## Timing

### vanilla
- Total: 661.9 min
- Avg per instance: 946s

## Files

- **vanilla** predictions: `benchmark_runs/20260219_145201_current_vanilla_100_step30_compile_submit_stop_linecap200_resume42_after_dns_restore/predictions/vanilla.jsonl`
- **vanilla** evaluation: `benchmark_runs/20260219_145201_current_vanilla_100_step30_compile_submit_stop_linecap200_resume42_after_dns_restore/evaluations/vanilla.eval.json`
- Full report JSON: `benchmark_runs/20260219_145201_current_vanilla_100_step30_compile_submit_stop_linecap200_resume42_after_dns_restore/report.json`
- Progress log: `benchmark_runs/20260219_145201_current_vanilla_100_step30_compile_submit_stop_linecap200_resume42_after_dns_restore/progress.log`
