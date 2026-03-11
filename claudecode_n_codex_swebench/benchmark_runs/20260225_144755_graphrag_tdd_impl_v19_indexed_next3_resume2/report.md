# Benchmark Report: graphrag_tdd_impl_v19_indexed_next3_resume2
**Date**: 2026-02-25 15:09
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 2

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 2/2 (100%) | 0/2 (0%) | 19m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|
| graphrag_tdd | 2.00 | 1 | 0.00 | 10.00 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| astropy-13977 | 629 chars |
| astropy-14096 | 1492 chars |

## Timing

### graphrag_tdd
- Total: 19.1 min
- Avg per instance: 574s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260225_144755_graphrag_tdd_impl_v19_indexed_next3_resume2/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260225_144755_graphrag_tdd_impl_v19_indexed_next3_resume2/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260225_144755_graphrag_tdd_impl_v19_indexed_next3_resume2/report.json`
- Progress log: `benchmark_runs/20260225_144755_graphrag_tdd_impl_v19_indexed_next3_resume2/progress.log`
