# Benchmark Report: graphrag_tdd_impl_v19_indexed_next2
**Date**: 2026-02-25 11:47
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 2

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 2/2 (100%) | 1/2 (50%) | 16m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|
| graphrag_tdd | 2.50 | 1 | 0.00 | 10.00 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| astropy-13033 | 983 chars |
| astropy-13236 | 799 chars |

## Timing

### graphrag_tdd
- Total: 16.1 min
- Avg per instance: 482s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260225_112935_graphrag_tdd_impl_v19_indexed_next2/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260225_112935_graphrag_tdd_impl_v19_indexed_next2/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260225_112935_graphrag_tdd_impl_v19_indexed_next2/report.json`
- Progress log: `benchmark_runs/20260225_112935_graphrag_tdd_impl_v19_indexed_next2/progress.log`
