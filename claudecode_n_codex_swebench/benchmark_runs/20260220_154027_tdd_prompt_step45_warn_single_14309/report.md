# Benchmark Report: tdd_prompt_step45_warn_single_14309
**Date**: 2026-02-20 15:44
**Dataset**: princeton-nlp/SWE-bench_Verified
**Instances**: 1

## Summary Table

| Variant | Generation | Resolution | Time |
|---------|-----------|------------|------|
| tdd_prompt | 1/1 (100%) | 1/1 (100%) | 3m |

## Loop and Test Diagnostics

| Variant | Avg Attempts | Loop Aborts | Avg F2P Pass Rate | Avg P2P Smoke Fails | Clean Candidates |
|---------|--------------|-------------|-------------------|---------------------|------------------|
| tdd_prompt | 1.00 | 1 | 0.00 | 10.00 | 0 |

## Per-Instance Comparison

| Instance | tdd_prompt |
|----------|------|
| astropy-14309 | 655 chars |

## Timing

### tdd_prompt
- Total: 2.6 min
- Avg per instance: 157s

## Files

- **tdd_prompt** predictions: `benchmark_runs/20260220_154027_tdd_prompt_step45_warn_single_14309/predictions/tdd_prompt.jsonl`
- **tdd_prompt** evaluation: `benchmark_runs/20260220_154027_tdd_prompt_step45_warn_single_14309/evaluations/tdd_prompt.eval.json`
- Full report JSON: `benchmark_runs/20260220_154027_tdd_prompt_step45_warn_single_14309/report.json`
- Progress log: `benchmark_runs/20260220_154027_tdd_prompt_step45_warn_single_14309/progress.log`
