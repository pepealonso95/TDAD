# Benchmark Report: graphrag_tdd_hybrid_fix_guard_next20_21_40_timeout20_native
**Date**: 2026-02-28 03:30
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 20

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 15/20 (75%) | 7/20 (35%) | 262m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|
| graphrag_tdd | 2.44 | 13 | 0.00 | 9.00 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| astropy-8707 | empty |
| astropy-8872 | 493 chars |
| django-10097 | 598 chars |
| django-10554 | empty |
| django-10880 | empty |
| django-10914 | 625 chars |
| django-10973 | empty |
| django-10999 | 497 chars |
| django-11066 | 767 chars |
| django-11087 | 852 chars |
| django-11095 | empty |
| django-11099 | 901 chars |
| django-11119 | 485 chars |
| django-11133 | 773 chars |
| django-11138 | 1132 chars |
| django-11141 | 1823 chars |
| django-11149 | 1623 chars |
| django-11163 | 971 chars |
| django-11179 | 668 chars |
| django-11206 | 737 chars |

## Timing

### graphrag_tdd
- Total: 261.6 min
- Avg per instance: 785s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260227_230149_graphrag_tdd_hybrid_fix_guard_next20_21_40_timeout20_native/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260227_230149_graphrag_tdd_hybrid_fix_guard_next20_21_40_timeout20_native/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260227_230149_graphrag_tdd_hybrid_fix_guard_next20_21_40_timeout20_native/report.json`
- Progress log: `benchmark_runs/20260227_230149_graphrag_tdd_hybrid_fix_guard_next20_21_40_timeout20_native/progress.log`
