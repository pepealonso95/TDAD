# Benchmark Report: graphrag_tdd_balanced_gate_signal_smoke1
**Date**: 2026-03-03 17:46
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 1

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 1/1 (100%) | 0/1 (0%) | 10m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Graph Guard Pass | Indexed Attempted | Repo Test Changed | TDD Evidence Pass | TDD Fail-Open | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|-------------------|-------------------|-------------------|---------------|------------------|
| graphrag_tdd | 2.00 | 0 | 0.00 | 10.00 | 1 | 1 | 0 | 1 | 1 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| astropy-12907 | 626 chars |

## Timing

### graphrag_tdd
- Total: 10.1 min
- Avg per instance: 608s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260303_173433_graphrag_tdd_balanced_gate_signal_smoke1/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260303_173433_graphrag_tdd_balanced_gate_signal_smoke1/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260303_173433_graphrag_tdd_balanced_gate_signal_smoke1/report.json`
- Progress log: `benchmark_runs/20260303_173433_graphrag_tdd_balanced_gate_signal_smoke1/progress.log`
