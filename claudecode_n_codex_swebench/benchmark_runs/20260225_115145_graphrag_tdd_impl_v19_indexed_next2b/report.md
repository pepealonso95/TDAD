# Benchmark Report: graphrag_tdd_impl_v19_indexed_next2b
**Date**: 2026-02-25 12:12
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 2

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 2/2 (100%) | 1/2 (50%) | 19m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|
| graphrag_tdd | 3.00 | 2 | 0.00 | 9.50 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| astropy-13398 | 699 chars |
| astropy-13453 | 701 chars |

## Timing

### graphrag_tdd
- Total: 18.7 min
- Avg per instance: 560s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260225_115145_graphrag_tdd_impl_v19_indexed_next2b/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260225_115145_graphrag_tdd_impl_v19_indexed_next2b/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260225_115145_graphrag_tdd_impl_v19_indexed_next2b/report.json`
- Progress log: `benchmark_runs/20260225_115145_graphrag_tdd_impl_v19_indexed_next2b/progress.log`
