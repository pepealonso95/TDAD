# TDAD Thesis - Quick Start Guide

## What Was Completed

### ✅ Phase 1: TDD Implementation (DONE)
1. **Created TDD Prompt** ([swe_bench_tdd.txt](claudecode_n_codex_swebench/prompts/swe_bench_tdd.txt))
   - Enforces test-first development
   - Requires running existing tests before completion
   - Structured workflow: Understand → Explore → Baseline → Write Tests → Implement → Verify → Regression Check

2. **Running EXP-002** (IN PROGRESS - Background)
   - 10 instances on SWE-bench Verified
   - Using TDD prompt with Sonnet 4.5
   - Estimated time: ~50 minutes total

### ✅ Phase 2: Regression Measurement Infrastructure (DONE)
1. **Created Regression Analyzer** ([analyze_regressions.py](claudecode_n_codex_swebench/analyze_regressions.py))
   - Extracts PASS_TO_PASS and FAIL_TO_PASS test info from dataset
   - Parses test execution results
   - Calculates:
     - Resolution Rate (standard metric)
     - **Regression Rate** (PRIMARY thesis metric)
     - Clean Resolution Rate (fixed without regressions)
     - Regression Instance Rate

2. **Created Dataset Caching Tool** ([cache_dataset.py](claudecode_n_codex_swebench/cache_dataset.py))
   - Downloads and caches SWE-bench Verified dataset locally
   - Creates quick-access test info file
   - Speeds up subsequent analysis (no HuggingFace reload)

3. **Documentation**
   - [REGRESSION_ANALYSIS.md](claudecode_n_codex_swebench/REGRESSION_ANALYSIS.md) - Complete guide to regression measurement
   - Updated [.gitignore](claudecode_n_codex_swebench/.gitignore) - Excludes large data files

## How to Use the New Tools

### 1. Cache the Dataset (First Time Setup - RECOMMENDED)

```bash
cd claudecode_n_codex_swebench

# Download and cache SWE-bench Verified locally
python3 cache_dataset.py

# This creates:
#   data/princeton-nlp_SWE-bench_Verified.json (full dataset)
#   data/princeton-nlp_SWE-bench_Verified_tests.json (quick access for test info)
```

**Benefits:**
- Future loads are near-instant (< 1 second vs 2-3 minutes)
- No network dependency after first download
- Smaller file (test info only) for analysis

### 2. Monitor Running Experiment (EXP-002)

```bash
# Check progress
tail -f /tmp/exp_002_run.log

# Or check output directory
ls -lh claudecode_n_codex_swebench/predictions/
```

### 3. When Experiment Completes

#### Step 3a: Run Evaluation (Docker)

```bash
cd claudecode_n_codex_swebench

# Find your predictions file
ls -lht predictions/predictions_*.jsonl | head -1

# Run evaluation (this will take ~20-30 minutes for 10 instances)
python3 evaluate_predictions.py --file predictions/predictions_TIMESTAMP.jsonl
```

#### Step 3b: Analyze Regressions

```bash
# Basic analysis
python3 analyze_regressions.py \
  --predictions predictions/predictions_TIMESTAMP.jsonl \
  --eval-dir evaluation_results

# With saved report
python3 analyze_regressions.py \
  --predictions predictions/predictions_TIMESTAMP.jsonl \
  --eval-dir evaluation_results \
  --output reports/exp002_regression_report.json
```

**Output Example:**
```
======================================================================
REGRESSION ANALYSIS SUMMARY
======================================================================
Total Instances: 10

RESOLUTION METRICS:
  Official Resolved: 7/10 (70.0%)
  Issue Fixed (FAIL_TO_PASS): 8/10 (80.0%)

REGRESSION METRICS:
  Instances with Regressions: 2/10 (20.0%)
  Total PASS_TO_PASS Tests: 156
  PASS_TO_PASS Tests Failed: 12
  Regression Rate: 7.7%  ← KEY METRIC FOR THESIS

CLEAN RESOLUTION:
  Fixed WITHOUT Regressions: 6/10 (60.0%)
======================================================================
```

### 4. Compare with Baseline (EXP-001)

```bash
# First, analyze baseline if not done yet
python3 analyze_regressions.py \
  --predictions predictions/predictions_20251027_205019.jsonl \
  --eval-dir evaluation_results \
  --output reports/exp001_baseline_regressions.json

# Then compare both JSON reports
# Use your preferred tool (jq, Python script, or manual inspection)
```

## Understanding the Results

### Key Question: Did TDD Reduce Regressions?

**Success Criteria:**
- ✅ Regression Rate reduced by >30% (e.g., 15% → <10%)
- ✅ Resolution Rate maintained (not significantly reduced)
- ✅ Clean Resolution Rate improved or maintained

**Example Comparison:**

| Metric | Baseline (EXP-001) | TDD (EXP-002) | Change |
|--------|-------------------|---------------|--------|
| Resolution Rate | 72% | 70% | -2% ✅ Maintained |
| **Regression Rate** | **15.2%** | **7.7%** | **-49%** ✅ **REDUCED** |
| Clean Resolution | 55% | 60% | +5% ✅ Improved |

## Next Steps After EXP-002 Completes

### Immediate (Today):
1. ✅ Wait for EXP-002 to complete (~40 more minutes)
2. ✅ Run evaluation on generated patches
3. ✅ Run regression analysis
4. ✅ Update EXPERIMENTS.md with results

### Short-term (This Week):
1. Compare EXP-002 vs EXP-001 baseline
2. Decide if TDD showed promise
3. If yes: Run larger sample (50-100 instances)
4. If no: Iterate on TDD prompt or try different approach

### Medium-term (Next 2 Weeks):
1. Run full baseline (100+ instances)
2. Run full TDD experiment (100+ instances)
3. Statistical analysis for thesis
4. Begin EXP-003 (Vector RAG) planning

## Troubleshooting

### Dataset Loading is Slow
**Solution:** Run `python3 cache_dataset.py` once to cache locally

### Experiment Seems Stuck
**Check:** `tail -f /tmp/exp_002_run.log`
**Note:** First instance takes longest (includes dataset load time)

### No Evaluation Results
**Cause:** Evaluation hasn't been run yet
**Solution:** Run `python3 evaluate_predictions.py` first

### analyze_regressions.py Shows 0% Regression Rate
**Possible Causes:**
1. Evaluation not completed
2. test_output.txt files missing
3. Test output format not recognized

**Solutions:**
1. Verify evaluation completed successfully
2. Check `evaluation_results/` directory has instance folders
3. Manually inspect a test_output.txt file for format

## File Structure After Setup

```
claudecode_n_codex_swebench/
├── prompts/
│   ├── swe_bench_prompt.txt         # Baseline
│   └── swe_bench_tdd.txt           # TDD (NEW)
├── predictions/
│   ├── predictions_20251027_*.jsonl  # EXP-001 baseline
│   └── predictions_20251029_*.jsonl  # EXP-002 TDD
├── evaluation_results/
│   └── <instance_id>/
│       ├── report.json
│       ├── test_output.txt
│       └── run_instance.log
├── data/                            # NEW - cached dataset
│   ├── princeton-nlp_SWE-bench_Verified.json
│   └── princeton-nlp_SWE-bench_Verified_tests.json
├── reports/                         # NEW - analysis reports
│   ├── exp001_baseline_regressions.json
│   └── exp002_tdd_regressions.json
├── cache_dataset.py                # NEW
├── analyze_regressions.py          # NEW
└── REGRESSION_ANALYSIS.md          # NEW
```

## Current Status Summary

### ✅ Completed:
- TDD prompt created
- Regression analysis infrastructure built
- Dataset caching implemented
- Documentation written

### ⏳ In Progress:
- EXP-002 running (10 instances, ~40 minutes remaining)

### 📋 Pending:
- Evaluation of EXP-002 results
- Regression analysis of EXP-002
- Comparison with baseline
- Update EXPERIMENTS.md
- Decision on next steps

## Questions?

Check these docs:
- [REGRESSION_ANALYSIS.md](claudecode_n_codex_swebench/REGRESSION_ANALYSIS.md) - Detailed regression measurement guide
- [EXPERIMENTS.md](EXPERIMENTS.md) - Full experiment log
- [.claude/CLAUDE.md](.claude/CLAUDE.md) - Project instructions

---

**Last Updated:** October 29, 2025 (EXP-002 in progress)
