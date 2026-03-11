# Benchmark Report: graphrag_tdd_advisory_first50
**Date**: 2026-03-10 05:48
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 50

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 39/50 (78%) | 14/50 (28%) | 367m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Graph Guard Pass | Indexed Attempted | Graph Useful | Repo Test Changed | TDD Evidence Pass | TDD Fail-Open | Runtime Fallbacks | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|-------------------|--------------|-------------------|-------------------|---------------|-------------------|------------------|
| graphrag_tdd | 2.76 | 49 | 0.00 | 9.08 | 50 | 41 | 0 | 1 | 50 | 0 | 1 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| astropy-12907 | 506 chars |
| astropy-13033 | empty |
| astropy-13236 | 782 chars |
| astropy-13398 | 3533 chars |
| astropy-13453 | 374 chars |
| astropy-13579 | 703 chars |
| astropy-13977 | 1282 chars |
| astropy-14096 | empty |
| astropy-14182 | 549 chars |
| astropy-14309 | 558 chars |
| astropy-14365 | 476 chars |
| astropy-14369 | 427 chars |
| astropy-14508 | 483 chars |
| astropy-14539 | 532 chars |
| astropy-14598 | 598 chars |
| astropy-14995 | 628 chars |
| astropy-7166 | 535 chars |
| astropy-7336 | 770 chars |
| astropy-7606 | 416 chars |
| astropy-7671 | empty |
| astropy-8707 | empty |
| astropy-8872 | empty |
| django-10097 | 604 chars |
| django-10554 | 642 chars |
| django-10880 | 469 chars |
| django-10914 | 1248 chars |
| django-10973 | empty |
| django-10999 | 497 chars |
| django-11066 | empty |
| django-11087 | 979 chars |
| django-11095 | 967 chars |
| django-11099 | 901 chars |
| django-11119 | 485 chars |
| django-11133 | 545 chars |
| django-11138 | 591 chars |
| django-11141 | 723 chars |
| django-11149 | empty |
| django-11163 | 971 chars |
| django-11179 | 614 chars |
| django-11206 | 737 chars |
| django-11211 | empty |
| django-11239 | 1014 chars |
| django-11265 | 674 chars |
| django-11276 | 788 chars |
| django-11292 | 546 chars |
| django-11299 | empty |
| django-11333 | empty |
| django-11400 | 1436 chars |
| django-11433 | 422 chars |
| django-11451 | 506 chars |

## Timing

### graphrag_tdd
- Total: 367.0 min
- Avg per instance: 440s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260309_232849_graphrag_tdd_advisory_first50/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260309_232849_graphrag_tdd_advisory_first50/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260309_232849_graphrag_tdd_advisory_first50/report.json`
- Progress log: `benchmark_runs/20260309_232849_graphrag_tdd_advisory_first50/progress.log`
