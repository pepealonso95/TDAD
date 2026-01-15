# Automated Experiment Runner

Comprehensive tool for running and comparing all three SWE-bench experiment modes.

## Overview

The experiment runner automates:
1. **Baseline** - Standard SWE-bench evaluation
2. **TDD** - Test-Driven Development prompt approach
3. **GraphRAG** - Graph-based test impact analysis

It runs experiments sequentially, collects results, and generates a detailed comparison report that's automatically appended to `EXPERIMENTS.md`.

## Files

- **`run_experiments.py`** - Main orchestration script
- **`experiment_analyzer.py`** - Result parsing and comparison utilities
- **`experiment_comparison.log`** - Execution log
- **`experiment_results_TIMESTAMP.json`** - Intermediate results (auto-saved)
- **`comparison_report_TIMESTAMP.md`** - Standalone comparison report

## Quick Start

### Run All Three Experiments (50 instances each)

```bash
cd claudecode_n_codex_swebench
python run_experiments.py --limit 50
```

**Estimated runtime:** ~10 hours (can run overnight)

### Test with Small Sample

```bash
python run_experiments.py --limit 3
```

**Estimated runtime:** ~15-20 minutes

### Dry Run (See What Would Execute)

```bash
python run_experiments.py --limit 50 --dry-run
```

### Run Specific Experiments Only

```bash
# Only baseline and TDD
python run_experiments.py --limit 50 --experiments baseline,tdd

# Only GraphRAG
python run_experiments.py --limit 50 --experiments graphrag
```

## Command-Line Options

```bash
python run_experiments.py [OPTIONS]

Options:
  --dataset TEXT              Dataset to use
                              (default: princeton-nlp/SWE-bench_Verified)

  --limit INT                 Number of instances per experiment
                              (default: 50)

  --experiments TEXT          Comma-separated list: baseline,tdd,graphrag
                              (default: all three)

  --dry-run                   Show what would run without executing

  --skip-experiments-md       Don't append report to EXPERIMENTS.md

  --help                      Show help message
```

## Output

### Prediction Files

Each experiment generates a prediction file in `predictions/`:

- **Baseline**: `predictions_YYYYMMDD_HHMMSS.jsonl`
- **TDD**: `predictions_YYYYMMDD_HHMMSS.jsonl`
- **GraphRAG**: `predictions_graphrag_YYYYMMDD_HHMMSS.jsonl`

### Intermediate Results

After each experiment completes, results are saved to:
```
experiment_results_YYYYMMDD_HHMMSS.json
```

This allows recovery if the script is interrupted.

### Comparison Report

A standalone report is generated:
```
comparison_report_YYYYMMDD_HHMMSS.md
```

This report is also automatically appended to `../EXPERIMENTS.md` as **EXP-005**.

### Log File

All execution details are logged to:
```
experiment_comparison.log
```

## Report Contents

The comparison report includes:

### Executive Summary
- Winner determination (best overall performer)
- Key findings (top insights)
- Quick statistics

### Detailed Metrics Table
| Metric | Baseline | TDD | GraphRAG |
|--------|----------|-----|----------|
| Generation Rate | 80% | 85% | 82% |
| Avg Patch Size | 2,500 | 3,200 | 2,800 |
| Errors | 2 | 1 | 3 |

### GraphRAG-Specific Metrics
- Total graphs built
- Average graph build time
- Average impacted tests found
- Impact analysis efficiency

### Error Analysis
Breakdown of error types for each experiment

### Recommendations
Specific action items based on results

### Next Steps
Suggested follow-up experiments and analyses

## Example Workflow

### Full Production Run (50 instances)

```bash
# Start the run (will take ~10 hours)
python run_experiments.py --limit 50

# The script will:
# 1. Run Baseline (50 instances)
# 2. Save intermediate results
# 3. Run TDD (50 instances)
# 4. Save intermediate results
# 5. Run GraphRAG (50 instances)
# 6. Generate comparison report
# 7. Append to EXPERIMENTS.md
# 8. Print summary
```

### Quick Test Run (3 instances)

```bash
# Test everything works
python run_experiments.py --limit 3 --skip-experiments-md

# Review results
cat comparison_report_*.md
```

### Resume After Interruption

If interrupted, check the latest `experiment_results_*.json` file to see which experiments completed. Then run only the remaining ones:

```bash
# If baseline and TDD completed, run only GraphRAG
python run_experiments.py --limit 50 --experiments graphrag
```

## Understanding the Comparison

### Generation Rate
Percentage of instances where the model produced a non-empty patch.
- **Higher is better** (shows the model attempted more fixes)
- Target: >80%

### Patch Size
Average number of characters in generated patches.
- Larger patches may indicate more comprehensive fixes
- Or could indicate over-engineering
- Context matters - compare with resolution rate

### Errors
Number of instances that failed with errors.
- **Lower is better**
- Common errors: repository setup, execution failures
- Check error breakdown for patterns

### GraphRAG Metrics
- **Graphs Built**: Should equal number of unique repos
- **Avg Impacted Tests**: ~10-50 tests typical (vs 100+ full suite)
- **Build Time**: First-time cost, amortized across instances
- **Analysis Time**: Should be <5s per instance

## Interpreting Results

### Scenario 1: GraphRAG Wins
- Lower generation rate but higher quality patches
- Fewer regressions (when evaluated)
- More efficient testing
- **Conclusion**: GraphRAG approach is superior

### Scenario 2: TDD Wins
- Higher generation rate
- More comprehensive test coverage
- May have longer execution times
- **Conclusion**: TDD prompt engineering effective

### Scenario 3: Baseline Wins
- Fastest execution
- Simpler approach sufficient
- **Conclusion**: Additional complexity not justified

## Troubleshooting

### "Command not found" errors
Ensure you're in the correct directory:
```bash
cd /Users/rafaelalonso/Development/Master/Tesis/claudecode_n_codex_swebench
```

### Claude Code not responding
Check Claude Code CLI is working:
```bash
claude --version
```

### MCP server not starting (GraphRAG)
Check if Neo4j dependencies are installed:
```bash
pip install -r requirements_mcp.txt
```

### Out of memory errors
Reduce the limit:
```bash
python run_experiments.py --limit 10
```

## Next Steps After Running

1. **Evaluate Predictions**
   ```bash
   python evaluate_predictions.py --file predictions_*.jsonl
   ```

2. **Analyze Regressions**
   ```bash
   python analyze_regressions.py
   ```

3. **View Scores**
   ```bash
   python show_scores.py
   ```

4. **Update Thesis**
   - Results are already in EXPERIMENTS.md
   - Extract key charts and tables
   - Write discussion section

## Tips

- **Run overnight**: 50 instances takes ~10 hours
- **Use tmux/screen**: Prevents interruption if SSH disconnects
- **Monitor progress**: `tail -f experiment_comparison.log`
- **Save predictions**: Prediction files are your raw data - back them up!
- **Test first**: Always run with `--limit 3` before full run

## Support

For issues:
1. Check `experiment_comparison.log`
2. Review prediction files for patterns
3. Verify Claude Code CLI is working
4. Check EXPERIMENTS.md for previous run data

---

**Good luck with your thesis experiments! 🎓**
