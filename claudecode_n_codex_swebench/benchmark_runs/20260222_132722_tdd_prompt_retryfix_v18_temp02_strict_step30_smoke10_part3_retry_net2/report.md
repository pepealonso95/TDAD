# Benchmark Report: tdd_prompt_retryfix_v18_temp02_strict_step30_smoke10_part3_retry_net2
**Date**: 2026-02-22 13:32
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 1

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| tdd_prompt | 1/1 (100%) | 1/1 (100%) | 3m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|
| tdd_prompt | 3.00 | 0 | 0.00 | 10.00 | 0 |

## Per-Instance Comparison

| Instance | tdd_prompt |
|----------|------|
| astropy-14309 | 477 chars |

## Timing

### tdd_prompt
- Total: 3.4 min
- Avg per instance: 202s

## Files

- **tdd_prompt** predictions: `benchmark_runs/20260222_132722_tdd_prompt_retryfix_v18_temp02_strict_step30_smoke10_part3_retry_net2/predictions/tdd_prompt.jsonl`
- **tdd_prompt** evaluation: `benchmark_runs/20260222_132722_tdd_prompt_retryfix_v18_temp02_strict_step30_smoke10_part3_retry_net2/evaluations/tdd_prompt.eval.json`
- Full report JSON: `benchmark_runs/20260222_132722_tdd_prompt_retryfix_v18_temp02_strict_step30_smoke10_part3_retry_net2/report.json`
- Progress log: `benchmark_runs/20260222_132722_tdd_prompt_retryfix_v18_temp02_strict_step30_smoke10_part3_retry_net2/progress.log`
