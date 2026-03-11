# Benchmark Report: graphrag_tdd_phase_logs_smoke1_final
**Date**: 2026-02-26 02:49
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 1

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 1/1 (100%) | 1/1 (100%) | 29m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|
| graphrag_tdd | 3.00 | 0 | 0.00 | 10.00 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| astropy-12907 | 1336 chars |

## Timing

### graphrag_tdd
- Total: 28.7 min
- Avg per instance: 1721s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260226_021600_graphrag_tdd_phase_logs_smoke1_final/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260226_021600_graphrag_tdd_phase_logs_smoke1_final/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260226_021600_graphrag_tdd_phase_logs_smoke1_final/report.json`
- Progress log: `benchmark_runs/20260226_021600_graphrag_tdd_phase_logs_smoke1_final/progress.log`
