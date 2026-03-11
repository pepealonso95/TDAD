# Benchmark Report: graphrag_tdd_qwen35_single1_iso
**Date**: 2026-03-03 23:45
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 1

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| graphrag_tdd | 0/1 (0%) | 0/1 (0%) | 20m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Graph Guard Pass | Indexed Attempted | Graph Useful | Repo Test Changed | TDD Evidence Pass | TDD Fail-Open | Runtime Fallbacks | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|-------------------|--------------|-------------------|-------------------|---------------|-------------------|------------------|
| graphrag_tdd | 0.00 | 1 | 0.00 | 0.00 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Per-Instance Comparison

| Instance | graphrag_tdd |
|----------|------|
| astropy-12907 | empty |

## Timing

### graphrag_tdd
- Total: 20.0 min
- Avg per instance: 1200s

## Files

- **graphrag_tdd** predictions: `benchmark_runs/20260303_232546_graphrag_tdd_qwen35_single1_iso/predictions/graphrag_tdd.jsonl`
- **graphrag_tdd** evaluation: `benchmark_runs/20260303_232546_graphrag_tdd_qwen35_single1_iso/evaluations/graphrag_tdd.eval.json`
- Full report JSON: `benchmark_runs/20260303_232546_graphrag_tdd_qwen35_single1_iso/report.json`
- Progress log: `benchmark_runs/20260303_232546_graphrag_tdd_qwen35_single1_iso/progress.log`
