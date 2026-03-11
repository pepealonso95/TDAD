# Benchmark Report: graphrag_tdd_hybrid_fix_guard1
**Date**: 2026-02-26 17:23
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 1

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 1/1 (100%) | 1/1 (100%) | 5m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|
| graphrag_tdd | 1.00 | 0 | 0.00 | 10.00 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| astropy-12907 | 1402 chars |

## Timing

### graphrag_tdd
- Total: 4.7 min
- Avg per instance: 282s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260226_171628_graphrag_tdd_hybrid_fix_guard1/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260226_171628_graphrag_tdd_hybrid_fix_guard1/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260226_171628_graphrag_tdd_hybrid_fix_guard1/report.json`
- Progress log: `benchmark_runs/20260226_171628_graphrag_tdd_hybrid_fix_guard1/progress.log`
