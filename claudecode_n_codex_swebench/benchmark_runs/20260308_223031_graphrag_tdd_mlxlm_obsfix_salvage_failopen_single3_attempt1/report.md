# Benchmark Report: graphrag_tdd_mlxlm_obsfix_salvage_failopen_single3_attempt1
**Date**: 2026-03-08 22:40
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 1

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 0/1 (0%) | 0/1 (0%) | 10m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Graph Guard Pass | Indexed Attempted | Graph Useful | Repo Test Changed | TDD Evidence Pass | TDD Fail-Open | Runtime Fallbacks | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|-------------------|--------------|-------------------|-------------------|---------------|-------------------|------------------|
| graphrag_tdd | 1.00 | 0 | 0.00 | 10.00 | 1 | 0 | 0 | 0 | 1 | 0 | 1 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| astropy-12907 | empty |

## Timing

### graphrag_tdd
- Total: 9.8 min
- Avg per instance: 590s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260308_223031_graphrag_tdd_mlxlm_obsfix_salvage_failopen_single3_attempt1/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260308_223031_graphrag_tdd_mlxlm_obsfix_salvage_failopen_single3_attempt1/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260308_223031_graphrag_tdd_mlxlm_obsfix_salvage_failopen_single3_attempt1/report.json`
- Progress log: `benchmark_runs/20260308_223031_graphrag_tdd_mlxlm_obsfix_salvage_failopen_single3_attempt1/progress.log`
