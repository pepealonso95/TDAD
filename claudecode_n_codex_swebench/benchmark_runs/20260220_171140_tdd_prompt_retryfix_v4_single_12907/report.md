# Benchmark Report: tdd_prompt_retryfix_v4_single_12907
**Date**: 2026-02-20 17:17
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 1

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| tdd_prompt | 1/1 (100%) | 0/1 (0%) | 4m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|
| tdd_prompt | 2.00 | 0 | 0.00 | 10.00 | 0 |

## Per-Instance Comparison

| Instance | tdd_prompt |
|----------|------|
| astropy-12907 | 477 chars |

## Timing

### tdd_prompt
- Total: 3.6 min
- Avg per instance: 218s

## Files

- **tdd_prompt** predictions: `benchmark_runs/20260220_171140_tdd_prompt_retryfix_v4_single_12907/predictions/tdd_prompt.jsonl`
- **tdd_prompt** evaluation: `benchmark_runs/20260220_171140_tdd_prompt_retryfix_v4_single_12907/evaluations/tdd_prompt.eval.json`
- Full report JSON: `benchmark_runs/20260220_171140_tdd_prompt_retryfix_v4_single_12907/report.json`
- Progress log: `benchmark_runs/20260220_171140_tdd_prompt_retryfix_v4_single_12907/progress.log`
