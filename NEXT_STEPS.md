# EXP-002 Next Steps - Ready for Evaluation

## 🎉 What's Been Completed

### ✅ EXP-002 Generation Phase - COMPLETE
- **10 instances processed** on SWE-bench Verified
- **9/10 patches generated** (90% generation rate)
- **1 timeout** (astropy-13579 - TDD complexity issue)
- **Total execution time:** 3 hours 59 minutes
- **Predictions file:** `predictions/predictions_20251029_104634.jsonl`

### ✅ TDD Prompt Created
- **File:** [prompts/swe_bench_tdd.txt](claudecode_n_codex_swebench/prompts/swe_bench_tdd.txt)
- **Size:** 119 lines
- **Key features:**
  - Enforces test-first development
  - Requires baseline test execution
  - Mandates full regression checking
  - 8-step TDD workflow (Understand → Explore → Baseline → Tests → Implement → Verify → Regression Check → Refactor)

### ✅ Regression Analysis Tools Built
- **[analyze_regressions.py](claudecode_n_codex_swebench/analyze_regressions.py)** - Extract regression metrics from evaluation results
- **[cache_dataset.py](claudecode_n_codex_swebench/cache_dataset.py)** - Cache SWE-bench dataset locally
- **[REGRESSION_ANALYSIS.md](claudecode_n_codex_swebench/REGRESSION_ANALYSIS.md)** - Complete guide
- **[QUICK_START.md](QUICK_START.md)** - Quick reference

---

## 🚀 What to Do Next

### Step 1: Run Evaluation (20-30 minutes)

**In your terminal:**

```bash
# Activate conda environment
conda activate py313

# Navigate to project
cd /Users/pepe/Development/TDAD/claudecode_n_codex_swebench

# Run the evaluation script
bash run_evaluation_manual.sh
```

**What this does:**
- Spins up Docker containers for each instance
- Applies patches to clean repositories
- Runs FAIL_TO_PASS tests (should pass - proves fix works)
- Runs PASS_TO_PASS tests (should pass - checks regressions)
- Saves results to `evaluation_results/`

**Expected output:**
```
Evaluating: predictions_20251029_104634.jsonl
🔬 Running Docker evaluation...
[Progress updates for 10 instances]
✅ Evaluation Score: X.XX%
   Evaluation Time: XX.X minutes
```

---

### Step 2: Analyze Regressions (1 minute)

**After evaluation completes:**

```bash
python analyze_regressions.py \
  --predictions predictions/predictions_20251029_104634.jsonl \
  --eval-dir evaluation_results \
  --output reports/exp002_tdd_regressions.json
```

**What you'll get:**

```
======================================================================
REGRESSION ANALYSIS SUMMARY
======================================================================
Total Instances: 10

RESOLUTION METRICS:
  Official Resolved: X/10 (XX.X%)
  Issue Fixed (FAIL_TO_PASS): X/10 (XX.X%)

REGRESSION METRICS:
  Instances with Regressions: X/10 (XX.X%)
  Total PASS_TO_PASS Tests: XXX
  PASS_TO_PASS Tests Failed: XX
  Regression Rate: X.X%  ← YOUR PRIMARY THESIS METRIC

CLEAN RESOLUTION:
  Fixed WITHOUT Regressions: X/10 (XX.X%)
======================================================================
```

---

### Step 3: Compare with Baseline

You also need to evaluate the baseline (EXP-001) to compare:

```bash
# Evaluate baseline predictions
python evaluate_predictions.py \
  --file predictions/predictions_20251027_205019.jsonl

# Analyze baseline regressions
python analyze_regressions.py \
  --predictions predictions/predictions_20251027_205019.jsonl \
  --eval-dir evaluation_results \
  --output reports/exp001_baseline_regressions.json
```

---

### Step 4: Compare Results

Compare the two JSON reports to see if TDD reduced regressions:

```bash
# Quick comparison
python -c "
import json

with open('reports/exp001_baseline_regressions.json') as f:
    baseline = json.load(f)
with open('reports/exp002_tdd_regressions.json') as f:
    tdd = json.load(f)

print('Baseline vs TDD Comparison')
print('='*50)
print(f'Resolution Rate:')
print(f'  Baseline: {baseline[\"resolution_rate\"]:.1f}%')
print(f'  TDD:      {tdd[\"resolution_rate\"]:.1f}%')
print()
print(f'Regression Rate (PRIMARY METRIC):')
print(f'  Baseline: {baseline[\"regression_rate\"]:.1f}%')
print(f'  TDD:      {tdd[\"regression_rate\"]:.1f}%')
print(f'  Change:   {tdd[\"regression_rate\"] - baseline[\"regression_rate\"]:.1f}%')
print()
print(f'Clean Resolution (Fixed without regressions):')
print(f'  Baseline: {baseline[\"clean_resolution_rate\"]:.1f}%')
print(f'  TDD:      {tdd[\"clean_resolution_rate\"]:.1f}%')
"
```

---

## 📊 Expected Results

### Hypothesis:
TDD approach should reduce regression rate while maintaining resolution rate.

### Success Criteria:

✅ **Primary Goal:** Regression rate reduced by >30%
- Example: 15% → <10%

✅ **Secondary Goal:** Resolution rate maintained
- Should not drop significantly

✅ **Ideal:** Clean resolution rate improved
- More instances fixed WITHOUT introducing regressions

---

## 📝 What to Update After Evaluation

### Update EXPERIMENTS.md

Add EXP-002 results section:

```markdown
## EXP-002: TDD Prompt Engineering

### Metadata
- **Date**: October 29, 2025
- **Configuration**: TDD prompt with test-first enforcement
- **Model**: Claude Sonnet 4.5
- **Dataset**: SWE-bench Verified
- **Sample Size**: 10 instances

### Results
- **Generation Rate**: 90% (9/10)
- **Resolution Rate**: XX% (X/10 resolved)
- **Regression Rate**: X.X% (PRIMARY METRIC)
- **Clean Resolution Rate**: XX% (X/10 fixed without regressions)

### Comparison to Baseline (EXP-001)
- Resolution Rate: XX% (baseline: YY%) — Change: ±Z%
- **Regression Rate: X.X% (baseline: Y.Y%) — Change: -Z.Z%** ← KEY FINDING
- Clean Resolution: XX% (baseline: YY%) — Change: ±Z%

### Analysis
[Discussion of whether TDD approach helped or not]

### Next Steps
[Based on results - scale up, iterate on prompt, or try different approach]
```

---

## 🔍 Troubleshooting

### Issue: "No files selected for evaluation"
**Solution:** The script prompts for file selection interactively. Use the manual script instead.

### Issue: Python version errors
**Solution:** Ensure you're using conda py313 environment (`conda activate py313`)

### Issue: Docker not running
**Solution:** Start Docker Desktop before running evaluation

### Issue: Evaluation takes too long
**Solution:**
- Reduce max_workers (currently 4)
- Or be patient - 10 instances takes ~20-30 minutes

---

## 📁 Key Files

### Generated Files:
- `predictions/predictions_20251029_104634.jsonl` - 9 TDD patches (229KB)
- `run_evaluation_manual.sh` - Evaluation script (NEW)

### Analysis Tools:
- `analyze_regressions.py` - Regression analysis
- `cache_dataset.py` - Dataset caching
- `REGRESSION_ANALYSIS.md` - Documentation

### Documentation:
- `QUICK_START.md` - Quick reference
- `EXPERIMENTS.md` - Full experiment log
- `NEXT_STEPS.md` - This file

---

## 🎯 The Key Question

**Did TDD reduce regression rate?**

You'll know after running the evaluation! The regression analysis will show:
- How many PASS_TO_PASS tests failed (regressions)
- Whether TDD approach prevented regressions better than baseline
- If the stricter workflow is worth the trade-offs (slower, one timeout)

---

## 💡 Quick Commands Summary

```bash
# 1. Activate environment
conda activate py313

# 2. Navigate to project
cd /Users/pepe/Development/TDAD/claudecode_n_codex_swebench

# 3. Evaluate EXP-002 (TDD)
bash run_evaluation_manual.sh

# 4. Analyze EXP-002 regressions
python analyze_regressions.py \
  --predictions predictions/predictions_20251029_104634.jsonl \
  --output reports/exp002_tdd_regressions.json

# 5. Evaluate EXP-001 (Baseline) - if not done yet
python evaluate_predictions.py \
  --file predictions/predictions_20251027_205019.jsonl

# 6. Analyze baseline regressions
python analyze_regressions.py \
  --predictions predictions/predictions_20251027_205019.jsonl \
  --output reports/exp001_baseline_regressions.json
```

---

**Ready to start? Run:** `conda activate py313 && cd /Users/pepe/Development/TDAD/claudecode_n_codex_swebench && bash run_evaluation_manual.sh`

Good luck with your evaluation! 🚀
