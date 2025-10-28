# TDAD Thesis - AI Assistant Instructions

## Project Context

You are assisting with a Master's thesis on **Test-Driven AI Development (TDAD)**: Minimizing code regressions in AI programming agents using TDD and GraphRAG approaches.

**Repository**: https://github.com/pepealonso95/TDAD

## Mandatory Experiment Logging

### 🔴 CRITICAL RULE: Log ALL Changes as Experiments

**Every prompt session that makes changes MUST be logged in `EXPERIMENTS.md`**

### When to Log

Log when you:
- Modify code in `claudecode_n_codex_swebench/`
- Change prompts in `prompts/`
- Run benchmarks or evaluations
- Add plugins or configurations
- Modify experiment parameters
- Make any change that could affect results

### How to Log

1. **At the END of each session**, update `EXPERIMENTS.md`
2. **Use the experiment template** provided in that file
3. **Include**:
   - Experiment ID (EXP-XXX)
   - Date and time
   - What was changed (configuration)
   - Why (hypothesis)
   - How (method)
   - Results (if available)
   - Analysis and next steps

### Example Entry Format

```markdown
## EXP-XXX: [Short Description]

### Metadata
- **Date**: YYYY-MM-DD HH:MM
- **Configuration**: What changed from previous
- **Model**: Claude version used
- **Sample Size**: Number of instances

### Hypothesis
What we expect to happen and why

### Method
```bash
# Exact commands run
```

### Results
- Generation Rate: X%
- Resolution Rate: Y%
- Key findings

### Analysis
What we learned

### Next Steps
- [ ] Item 1
- [ ] Item 2
```

## Project Structure

```
/Users/rafaelalonso/Development/Master/Tesis/
├── README.md                          # Thesis overview
├── EXPERIMENTS.md                     # 🔴 EXPERIMENT LOG (UPDATE THIS!)
├── .claude/CLAUDE.md                  # This file
└── claudecode_n_codex_swebench/      # Evaluation toolkit
    ├── code_swe_agent.py             # Main agent
    ├── prompts/                      # Prompt templates
    │   ├── swe_bench_prompt.txt      # Baseline (EXP-001)
    │   └── swe_bench_tdd.txt         # TDD version (EXP-002, to create)
    ├── utils/                        # Utilities
    ├── predictions/                  # Generated patches
    └── benchmark_scores.log          # Results log
```

## Current Experiment Status

**Active**: EXP-001 (Baseline) - ✅ Generation Complete, ⏳ Evaluation Pending
**Next**: EXP-002 (TDD Prompts) or Evaluation of EXP-001

## Experiment Workflow

### Standard Experiment Execution

1. **Before Starting**
   - Review EXPERIMENTS.md to understand current state
   - Identify experiment ID (next in sequence)
   - Note baseline configuration

2. **During Experiment**
   - Make changes systematically
   - Document assumptions
   - Run with consistent parameters
   - Capture all output

3. **After Completion**
   - 🔴 **UPDATE EXPERIMENTS.md** immediately
   - Commit changes with descriptive message
   - Tag if major milestone

### Git Commit Format

```
[EXP-XXX] Short description

- Bullet point of changes
- Another change
- Reference to EXPERIMENTS.md entry

Updates EXPERIMENTS.md with results
```

## Important Constraints

### Do NOT:
- ❌ Run experiments without logging them
- ❌ Modify multiple things at once (can't isolate effects)
- ❌ Use different sample sizes without noting it
- ❌ Change models mid-experiment
- ❌ Forget to record negative results (failures are data!)

### DO:
- ✅ Log every change session in EXPERIMENTS.md
- ✅ Use consistent terminology (generation rate, resolution rate, regression rate)
- ✅ Keep one variable at a time when possible
- ✅ Document unexpected behaviors
- ✅ Note execution environment changes
- ✅ Save prediction files for later analysis

## Thesis Goals

### Primary Research Question
Can TDD practices and GraphRAG reduce regression rates in AI coding agents?

### Four Key Experiments
1. **EXP-001**: Baseline (vanilla Claude Code) - ✅ IN PROGRESS
2. **EXP-002**: TDD Prompt Engineering - 🔴 PLANNED
3. **EXP-003**: Vector RAG (claude-context) - 🔴 PLANNED
4. **EXP-004**: GraphRAG with Test Impact Analysis - 🔴 PLANNED

### Success Criteria
- **Baseline**: Establish regression rate
- **TDD**: Reduce regressions by >30%
- **Vector RAG**: Improve resolution rate by >20%
- **GraphRAG**: Achieve <5% regression rate (ambitious goal)

## Metrics Definitions

### Generation Rate
- % of instances where agent produced a non-empty patch
- Indicates agent's willingness/ability to attempt fixes

### Resolution Rate (THE REAL SCORE)
- % of patches that actually fix the issue (pass issue-specific tests)
- Measured by Docker evaluation on SWE-bench

### Regression Rate
- % of patches that break previously passing tests
- Calculated from Docker evaluation results
- **PRIMARY METRIC for thesis**

### Time Metrics
- Execution time per instance
- Total time for benchmark run
- Important for practicality assessment

## Common Commands

### Run Experiments
```bash
cd /Users/rafaelalonso/Development/Master/Tesis/claudecode_n_codex_swebench

# Baseline (EXP-001)
conda activate py313
python code_swe_agent.py --dataset_name princeton-nlp/SWE-bench_Lite --limit 10 --backend claude

# With custom prompt (future experiments)
python code_swe_agent.py --dataset_name princeton-nlp/SWE-bench_Lite --limit 10 --backend claude --prompt-template prompts/swe_bench_tdd.txt
```

### Evaluate Results
```bash
# Evaluate specific predictions
python evaluate_predictions.py --file predictions_YYYYMMDD_HHMMSS.jsonl

# View scores
python show_scores.py
cat benchmark_scores.log
```

### Check Status
```bash
# See latest predictions
ls -lh predictions/*.jsonl | tail -5

# Count successful patches
grep -c '"prediction": ""' predictions/predictions_LATEST.jsonl  # Empty
wc -l predictions/predictions_LATEST.jsonl  # Total

# Check evaluation progress
ls -lh evaluation_results/
```

## Troubleshooting

### Issue: Empty patches generated
- Check Claude Code execution logs
- Look for "No changes" in git status
- Agent may have analyzed without implementing

### Issue: Directory/git errors
- Known issue: Claude Code sometimes cleans working directory
- Already handled with try-catch in claude_interface.py
- Document frequency in experiment notes

### Issue: Model 404 errors
- Don't specify --model parameter
- Let Claude Code use default (Sonnet 4.5)
- Model registry already fixed to use aliases

### Issue: Docker out of memory
- Reduce --max-workers parameter
- Ensure Docker has 8GB+ allocated
- Close other applications

## Session End Checklist

Before ending any work session:

- [ ] Updated EXPERIMENTS.md with changes made
- [ ] Committed changes with [EXP-XXX] tag
- [ ] Noted any unexpected behaviors
- [ ] Saved any generated prediction files
- [ ] Updated README.md if major milestone
- [ ] Pushed to GitHub if session complete

## References for AI Assistant

- SWE-bench Paper: https://arxiv.org/abs/2310.06770
- Claude Code Docs: https://docs.claude.com/en/docs/claude-code
- Original Toolkit: https://github.com/jimmc414/claudecode_swebench
- GraphRAG: https://arxiv.org/abs/2404.16130

---

**Remember**: Every change is an experiment. Every experiment must be logged. Scientific rigor requires careful documentation!

🔴 **NEVER forget to update EXPERIMENTS.md at the end of a session!**
