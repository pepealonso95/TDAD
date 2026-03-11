# Benchmark Report: graphrag_tdd_guard_relaxation_vnext_smoke1
**Date**: 2026-03-03 21:09
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 1

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 1/1 (100%) | 0/1 (0%) | 14m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Graph Guard Pass | Indexed Attempted | Graph Useful | Repo Test Changed | TDD Evidence Pass | TDD Fail-Open | Runtime Fallbacks | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|-------------------|--------------|-------------------|-------------------|---------------|-------------------|------------------|
| graphrag_tdd | 2.00 | 0 | 0.00 | 10.00 | 1 | 1 | 0 | 0 | 1 | 1 | 1 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| astropy-12907 | 399 chars |

## Timing

### graphrag_tdd
- Total: 13.6 min
- Avg per instance: 817s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260303_205351_graphrag_tdd_guard_relaxation_vnext_smoke1/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260303_205351_graphrag_tdd_guard_relaxation_vnext_smoke1/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260303_205351_graphrag_tdd_guard_relaxation_vnext_smoke1/report.json`
- Progress log: `benchmark_runs/20260303_205351_graphrag_tdd_guard_relaxation_vnext_smoke1/progress.log`
