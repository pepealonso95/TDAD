# Benchmark Report: graphrag_tdd_mlxlm_obsfix_salvage_failopen_single2
**Date**: 2026-03-08 19:52
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 1

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 1/1 (100%) | 0/1 (0%) | 21m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Graph Guard Pass | Indexed Attempted | Graph Useful | Repo Test Changed | TDD Evidence Pass | TDD Fail-Open | Runtime Fallbacks | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|-------------------|--------------|-------------------|-------------------|---------------|-------------------|------------------|
| graphrag_tdd | 2.00 | 1 | 0.00 | 10.00 | 1 | 1 | 0 | 0 | 1 | 0 | 1 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| astropy-12907 | 960 chars |

## Timing

### graphrag_tdd
- Total: 21.2 min
- Avg per instance: 1273s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260308_192424_graphrag_tdd_mlxlm_obsfix_salvage_failopen_single2/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260308_192424_graphrag_tdd_mlxlm_obsfix_salvage_failopen_single2/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260308_192424_graphrag_tdd_mlxlm_obsfix_salvage_failopen_single2/report.json`
- Progress log: `benchmark_runs/20260308_192424_graphrag_tdd_mlxlm_obsfix_salvage_failopen_single2/progress.log`
