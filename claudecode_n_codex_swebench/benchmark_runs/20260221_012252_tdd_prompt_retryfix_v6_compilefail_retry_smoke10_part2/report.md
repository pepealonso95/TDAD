# Benchmark Report: tdd_prompt_retryfix_v6_compilefail_retry_smoke10_part2
**Date**: 2026-02-21 02:07
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 5

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| tdd_prompt | 4/5 (80%) | 1/5 (20%) | 41m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|
| tdd_prompt | 2.20 | 2 | 0.00 | 9.80 | 0 |

## Per-Instance Comparison

| Instance | tdd_prompt |
|----------|------|
| astropy-13579 | 1603 chars |
| astropy-13977 | 796 chars |
| astropy-14096 | empty |
| astropy-14182 | 624 chars |
| astropy-14309 | 558 chars |

## Timing

### tdd_prompt
- Total: 40.6 min
- Avg per instance: 487s

## Files

- **tdd_prompt** predictions: `benchmark_runs/20260221_012252_tdd_prompt_retryfix_v6_compilefail_retry_smoke10_part2/predictions/tdd_prompt.jsonl`
- **tdd_prompt** evaluation: `benchmark_runs/20260221_012252_tdd_prompt_retryfix_v6_compilefail_retry_smoke10_part2/evaluations/tdd_prompt.eval.json`
- Full report JSON: `benchmark_runs/20260221_012252_tdd_prompt_retryfix_v6_compilefail_retry_smoke10_part2/report.json`
- Progress log: `benchmark_runs/20260221_012252_tdd_prompt_retryfix_v6_compilefail_retry_smoke10_part2/progress.log`
