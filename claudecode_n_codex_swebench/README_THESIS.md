# Claude Code SWE-bench Evaluation Toolkit

**Thesis Project**: Minimizing Code Regressions in AI Programming Agents using TDD and GraphRAG

This repository contains a modified and enhanced version of the `claudecode_swebench` toolkit, specifically configured for evaluating Claude Code on the SWE-bench benchmark to study code regression patterns in AI agents.

## Baseline Results

### Initial Baseline Test (10 instances)
- **Generation Score**: 80% (8/10 patches generated)
- **Execution Time**: ~49 minutes (avg 5 min/instance)
- **Model**: Claude Sonnet 4.5 (default)
- **Date**: October 27, 2025

### Success Cases
1. ✅ `astropy__astropy-12907` - Separability matrix bug (17KB patch)
2. ✅ `astropy__astropy-14182` - RST header rows support (4KB patch)
3. ✅ `astropy__astropy-14365` - QDP case-insensitive commands (3KB patch)
4. ✅ `astropy__astropy-14995` - NDDataRef mask propagation (9KB patch)
5. ✅ `astropy__astropy-6938` - FITS D exponents (5KB patch)
6. ✅ `astropy__astropy-7746` - WCS empty arrays (7KB patch)
7. ✅ `django__django-10914` - FILE_UPLOAD_PERMISSIONS (7KB patch)
8. ✅ `django__django-10924` - FilePathField callable (3KB patch)

### Failure Cases
- ❌ `django__django-11001` - Git repository corruption
- ❌ Another instance with directory cleanup issue

## Key Modifications from Original Toolkit

### 1. Fixed Model Registry
- **File**: `utils/model_registry.py`
- **Change**: Updated model names to use Claude Code aliases (`sonnet`, `opus`) instead of full model IDs
- **Reason**: Original registry had outdated/incorrect model IDs causing 404 errors

### 2. Enhanced Debug Logging
- **Files**: `utils/claude_interface.py`, `utils/patch_extractor.py`
- **Addition**: Comprehensive debug output showing:
  - Command execution details
  - Prompt preview
  - Claude Code stdout/stderr
  - Git status before patch extraction
  - Patch generation results
- **Purpose**: Visibility into Claude Code execution for debugging failures

### 3. Robust Error Handling
- **File**: `utils/claude_interface.py`
- **Change**: Added try-catch around `os.chdir()` to handle directory cleanup issues
- **Reason**: Claude Code sometimes removes/changes working directory, causing crashes

### 4. Fixed Patch Format
- **Issue**: Original code returned `prediction` field but evaluation expects `model_patch`
- **Status**: Handled by evaluation harness

## Installation

### Prerequisites
- Python 3.8+
- Claude Code CLI (v2.0.28+) installed and authenticated
- Docker (with 50GB+ free disk space, 16GB+ RAM)
- Conda (recommended)

### Setup

```bash
# Clone this repository
git clone https://github.com/rafaelalonso/claudecode-swebench-thesis.git
cd claudecode-swebench-thesis

# Create conda environment
conda create -n py313 python=3.13
conda activate py313

# Install dependencies
pip install -r requirements.txt

# Verify Claude Code is installed
claude --version

# Verify Docker is running
docker ps
```

## Usage

### Run Baseline Evaluation

```bash
# Quick test (10 instances, ~1 hour)
python code_swe_agent.py --dataset_name princeton-nlp/SWE-bench_Lite --limit 10 --backend claude

# Single instance test
python code_swe_agent.py --dataset_name princeton-nlp/SWE-bench_Lite --limit 1 --backend claude

# Full lite benchmark (300 instances, ~25 hours)
python code_swe_agent.py --dataset_name princeton-nlp/SWE-bench_Lite --limit 300 --backend claude
```

### Evaluate Generated Patches

```bash
# Evaluate specific predictions file
python evaluate_predictions.py --file predictions_YYYYMMDD_HHMMSS.jsonl

# Evaluate latest predictions
python evaluate_predictions.py --last 1
```

### View Results

```bash
# Show scores from benchmark log
python show_scores.py

# Check benchmark log directly
cat benchmark_scores.log
```

## Thesis Experiment Plan

### Research Question
Can Test-Driven Development (TDD) practices and GraphRAG indexing minimize code regressions in AI programming agents?

### Hypothesis
By enforcing TDD practices and using GraphRAG to understand test-code relationships, AI agents will produce fewer regressions than baseline approaches.

### Four Test Cases

#### 1. **Baseline** ✅ (Completed)
- **Configuration**: Vanilla Claude Code with default prompts
- **Results**: 80% generation rate, evaluation pending
- **Purpose**: Establish baseline regression rate

#### 2. **TDD Prompt Modification** (Planned)
- **Configuration**: Modified SWE-bench prompt to enforce TDD
  - Instruct agent to write/run tests first
  - Require test confirmation before considering task complete
- **Files to modify**: `prompts/swe_bench_prompt.txt`
- **Hypothesis**: Explicit TDD instructions will catch regressions

#### 3. **Vector RAG with claude-context** (Planned)
- **Configuration**: Install and use [claude-context](https://github.com/zilliztech/claude-context) plugin
- **Purpose**: Test if vector-based codebase indexing helps
- **Hypothesis**: Better code understanding via RAG reduces regressions

#### 4. **Custom GraphRAG Plugin** (Planned)
- **Configuration**: Build custom Claude Code plugin that:
  - Indexes code with associated tests (graph structure)
  - Identifies impacted tests for code changes
  - Runs impacted tests in a subtask before completion
- **Implementation**: See [Claude Code Plugin Docs](https://docs.claude.com/en/docs/claude-code/plugins)
- **Hypothesis**: Test-aware RAG will minimize regressions most effectively

## Project Structure

```
claudecode-swebench-thesis/
├── code_swe_agent.py          # Main agent - invokes Claude Code
├── swe_bench.py                # Unified CLI tool
├── run_benchmark_with_eval.py  # Orchestrates inference + evaluation
├── evaluate_predictions.py     # Docker-based evaluation
├── show_scores.py              # Display results
├── utils/
│   ├── claude_interface.py    # Claude Code CLI wrapper (MODIFIED)
│   ├── model_registry.py      # Model name mappings (MODIFIED)
│   ├── patch_extractor.py     # Extract patches from git (MODIFIED)
│   ├── prompt_formatter.py    # Format SWE-bench prompts
│   └── ...
├── prompts/
│   └── swe_bench_prompt.txt   # Default prompt template
├── predictions/                # Generated patches
├── evaluation_results/         # Docker evaluation output
├── benchmark_scores.log        # Historical results
└── requirements.txt
```

## Key Metrics Tracked

### Generation Metrics
- **Generation Rate**: % of instances where agent produced a patch
- **Patch Size**: Characters in generated diff
- **Execution Time**: Time per instance

### Evaluation Metrics (THE REAL SCORES)
- **Resolution Rate**: % of patches that actually fix the issue
- **Test Pass Rate**: % of patches that pass all tests
- **Regression Rate**: % of patches that break existing tests

### Expected Performance (from Anthropic)
- **10-15%**: Average
- **20-25%**: Very Good
- **30%+**: Outstanding

## Known Issues

### Directory Management
- Claude Code sometimes removes or changes directories during execution
- Fixed with robust error handling in `claude_interface.py`
- Manifests as FileNotFoundError when restoring cwd

### Git State Corruption
- Some instances lose git repository state
- Causes "Not a git repository" errors
- Typically happens when Claude Code does extensive directory operations

### Empty Patches
- ~20% of instances generate empty patches
- Usually Claude Code analyzes but doesn't make file changes
- May indicate prompt issues or agent confusion

## Debugging

### Enable Verbose Logging
Debug logging is already enabled in the modified toolkit. Check:

```bash
# Watch real-time output
tail -f /tmp/swe_bench_debug.log

# Check specific instance logs
ls logs/
cat logs/instance_*.log
```

### Common Issues

**Issue**: Claude Code not found
```bash
which claude
# Install from: https://claude.ai/download
```

**Issue**: Docker not running
```bash
docker ps
# Start Docker Desktop
```

**Issue**: Model 404 errors
- Solution: Don't specify `--model` parameter
- Let Claude Code use its default (Sonnet 4.5)

## References

- **Original Toolkit**: [jimmc414/claudecode_swebench](https://github.com/jimmc414/claudecode_swebench)
- **SWE-bench**: [Princeton NLP](https://github.com/princeton-nlp/SWE-bench)
- **Claude Code**: [Anthropic](https://claude.ai/code)
- **Anthropic SWE-bench Results**: [Engineering Blog](https://www.anthropic.com/engineering/swe-bench-sonnet)

## License

MIT License (inherited from original toolkit)

## Author

Rafael Alonso
Master's Thesis Project
October 2025

## Acknowledgments

- Original `claudecode_swebench` toolkit by jimmc414
- Anthropic for Claude Code and SWE-bench evaluation methodology
- Princeton NLP for SWE-bench benchmark
