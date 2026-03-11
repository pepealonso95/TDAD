# Benchmark Report: graphrag_tdd_hybrid_fix_guard_next4_21_24
**Date**: 2026-02-27 13:35
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 4

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 2/4 (50%) | 0/4 (0%) | 128m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|
| graphrag_tdd | 2.75 | 2 | 0.00 | 10.00 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| astropy-8707 | empty |
| astropy-8872 | 526 chars |
| django-10097 | 596 chars |
| django-10554 | empty |

## Timing

### graphrag_tdd
- Total: 128.4 min
- Avg per instance: 1926s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260227_112219_graphrag_tdd_hybrid_fix_guard_next4_21_24/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260227_112219_graphrag_tdd_hybrid_fix_guard_next4_21_24/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260227_112219_graphrag_tdd_hybrid_fix_guard_next4_21_24/report.json`
- Progress log: `benchmark_runs/20260227_112219_graphrag_tdd_hybrid_fix_guard_next4_21_24/progress.log`
