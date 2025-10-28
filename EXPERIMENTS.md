# TDAD Thesis: Experiment Log

**Project**: Test-Driven AI Development - Minimizing Code Regressions in AI Agents
**Author**: Rafael Alonso
**Repository**: https://github.com/pepealonso95/TDAD

---

## Experiment Template

Each experiment entry should include:
- **Experiment ID**: Unique identifier (e.g., EXP-001)
- **Date**: When the experiment was conducted
- **Configuration**: What was changed from baseline
- **Hypothesis**: What we expect to happen
- **Method**: How the experiment was run
- **Results**: Generation rate, evaluation score, regression rate
- **Analysis**: What we learned
- **Next Steps**: What to do next

---

## EXP-001: Baseline Evaluation

### Metadata
- **Date**: October 27-28, 2025
- **Configuration**: Vanilla Claude Code with default SWE-bench prompts
- **Model**: Claude Sonnet 4.5 (default)
- **Dataset**: SWE-bench Lite
- **Sample Size**: 10 instances (quick test)

### Hypothesis
Establish baseline regression rate for Claude Code without modifications. Expected performance based on Anthropic's published results: 15-25% resolution rate.

### Method
```bash
python code_swe_agent.py \
  --dataset_name princeton-nlp/SWE-bench_Lite \
  --limit 10 \
  --backend claude
```

**Configuration Files**:
- Prompt: `prompts/swe_bench_prompt.txt` (default)
- Model Registry: Fixed to use Claude Code aliases
- No additional plugins or modifications

### Results

#### Generation Phase
- **Duration**: 49 minutes 18 seconds
- **Generation Rate**: 80% (8/10 patches generated)
- **Average Time per Instance**: ~5 minutes
- **Empty Patches**: 2/10 (20%)

#### Successful Patches Generated
1. ✅ **astropy__astropy-12907** (3:59)
   - Issue: Separability matrix for nested CompoundModels
   - Patch Size: 17,292 characters
   - Changes: Fixed `_cstack` function bug + comprehensive tests

2. ✅ **astropy__astropy-14182** (5:21)
   - Issue: RST header_rows support
   - Patch Size: 4,092 characters
   - Changes: Modified RST class to accept header_rows parameter

3. ✅ **astropy__astropy-14365** (3:13)
   - Issue: QDP case-sensitive commands
   - Patch Size: 3,154 characters
   - Changes: Added re.IGNORECASE flag to regex

4. ✅ **astropy__astropy-14995** (4:53)
   - Issue: NDDataRef mask propagation
   - Patch Size: 9,728 characters
   - Changes: Fixed mask handling when operand has no mask

5. ✅ **astropy__astropy-6938** (4:19)
   - Issue: FITS D exponents bug
   - Patch Size: 5,186 characters
   - Changes: Test files only (no actual code changes detected)

6. ✅ **astropy__astropy-7746** (5:20)
   - Issue: WCS empty arrays handling
   - Patch Size: 7,034 characters
   - Changes: Added empty array checks in WCS transformations

7. ✅ **django__django-10914** (5:20)
   - Issue: FILE_UPLOAD_PERMISSION default
   - Patch Size: 7,782 characters
   - Changes: Set default to 0o644, updated docs and tests

8. ✅ **django__django-10924** (4:14)
   - Issue: FilePathField callable support
   - Patch Size: 3,245 characters
   - Changes: Allow callable paths to fix migration issues

#### Failed Cases
9. ❌ **django__django-11001** (5:15)
   - Issue: Multiline RawSQL order_by removal
   - Error: Git repository corruption ("Not a git repository")
   - Root Cause: Directory state lost during execution

10. ❌ (Instance not logged - likely similar directory issue)

#### Evaluation Phase (Pending)
- **Status**: Not yet run on full 10 instances
- **Single Instance Test**: 1/1 passed (100% for astropy__astropy-12907)
- **Expected Full Evaluation Time**: ~20 minutes

### Analysis

#### Key Findings

1. **High Generation Rate (80%)**
   - Claude Code successfully attempts fixes on most instances
   - Better than expected for vanilla configuration
   - Only 20% empty patches (agent confusion/analysis-only cases)

2. **Patch Quality Observations**
   - Patches include actual code fixes + tests + documentation
   - Average patch size: 6,939 characters (substantial changes)
   - Agent follows issue descriptions well
   - Implements fixes with proper error handling

3. **Common Failure Patterns**
   - Git repository corruption (directory management issues)
   - Claude Code sometimes cleans up working directory
   - FileNotFoundError when restoring cwd after execution

4. **Performance Characteristics**
   - Execution time highly variable: 3-5 minutes per instance
   - No correlation between patch size and execution time
   - Dataset loading takes ~2-3 minutes initially

#### Toolkit Issues Fixed During Experiment

1. **Model Registry** (`utils/model_registry.py`)
   - Original: Used full model IDs (e.g., `claude-sonnet-4-20250815`)
   - Problem: 404 errors from API
   - Fix: Map to Claude Code aliases (`sonnet`, `opus`)
   - Impact: Enabled successful execution

2. **Debug Logging** (`utils/claude_interface.py`, `utils/patch_extractor.py`)
   - Added: Command preview, stdout/stderr capture, git status
   - Purpose: Visibility into agent behavior for debugging
   - Result: Identified directory management issues

3. **Error Handling** (`utils/claude_interface.py`)
   - Added: Try-catch around `os.chdir()` restore
   - Purpose: Graceful handling of directory cleanup
   - Result: Prevented cascading failures

### Limitations & Concerns

1. **Directory Management**
   - Claude Code's workspace cleanup interferes with toolkit
   - May cause underestimation of success rate
   - Need to investigate why some repos lose git state

2. **Evaluation Pending**
   - Generation rate ≠ resolution rate
   - Don't know yet if patches actually fix issues
   - Docker evaluation required to get real scores

3. **Sample Size**
   - Only 10 instances for quick test
   - May not be representative of full benchmark
   - Need larger sample for statistical significance

4. **Git State Corruption**
   - 2/10 instances lost git repository
   - Possibly related to Claude Code's directory operations
   - May need isolation improvements

### Next Steps

1. **Immediate**
   - [ ] Run Docker evaluation on 8 successful patches
   - [ ] Calculate actual resolution rate (THE REAL SCORE)
   - [ ] Analyze which types of issues Claude handles well

2. **Baseline Completion**
   - [ ] Run full 300-instance benchmark (or 50-instance sample)
   - [ ] Collect statistically significant baseline data
   - [ ] Identify regression patterns in failures

3. **Preparation for EXP-002**
   - [ ] Design TDD prompt modifications
   - [ ] Create prompt template enforcing test-first workflow
   - [ ] Plan A/B comparison methodology

### Raw Data

**Predictions File**: `predictions/predictions_20251027_205019.jsonl`
**Benchmark Log**: `benchmark_scores.log`
**Repository State**: Commit `711b164`

### Expected vs Actual

| Metric | Expected (Anthropic) | Actual |
|--------|---------------------|---------|
| Generation Rate | N/A | 80% |
| Resolution Rate | 15-25% | TBD (pending eval) |
| Execution Time | ~5 min/instance | 4.9 min/instance |

### Conclusion

Baseline successfully established. The toolkit works with Claude Code after fixes. Generation rate of 80% is promising, but true test is the evaluation phase to determine how many patches actually resolve issues without introducing regressions.

The agent demonstrates sophisticated behavior (tests + docs + fixes) but has edge cases around directory management that need addressing for production use.

**Status**: ✅ Generation Complete, ⏳ Evaluation Pending

---

## EXP-002: TDD Prompt Engineering (Planned)

### Metadata
- **Date**: TBD
- **Configuration**: Modified prompt enforcing TDD workflow
- **Model**: Claude Sonnet 4.5 (default)
- **Dataset**: SWE-bench Lite
- **Sample Size**: 10 instances (initial), then 50 or 300

### Hypothesis
Enforcing TDD practices (write tests first, then implementation) will:
1. Reduce regression rate by catching breaking changes early
2. Potentially lower generation rate (more constraint = more failures)
3. Increase patch quality (test coverage guarantees)

### Method
**Prompt Modifications** (`prompts/swe_bench_tdd.txt`):
1. Require test creation before implementation
2. Mandate test execution and confirmation
3. Only allow code changes after tests pass
4. Instruct to run existing tests to catch regressions

**Command**:
```bash
python code_swe_agent.py \
  --dataset_name princeton-nlp/SWE-bench_Lite \
  --limit 10 \
  --backend claude \
  --prompt-template prompts/swe_bench_tdd.txt
```

### Expected Results
- Generation Rate: 60-70% (lower due to stricter requirements)
- Resolution Rate: 20-30% (higher than baseline)
- Regression Rate: <10% (main goal)

### Status
🔴 **Not Started**

---

## EXP-003: Vector RAG with claude-context (Planned)

### Metadata
- **Date**: TBD
- **Configuration**: Baseline + claude-context plugin
- **Model**: Claude Sonnet 4.5 (default)
- **Dataset**: SWE-bench Lite
- **Sample Size**: 10 instances (initial), then 50 or 300

### Hypothesis
Vector-based RAG indexing of the codebase will:
1. Improve code understanding and context retrieval
2. Increase generation rate (better understanding = fewer failures)
3. Improve resolution rate (better fixes from better context)

### Method
1. Install claude-context plugin: https://github.com/zilliztech/claude-context
2. Index each repository before running Claude Code
3. Use default prompt (baseline)

**Command**:
```bash
# Index codebase
claude-context index <repo_path>

# Run with indexed context
python code_swe_agent.py \
  --dataset_name princeton-nlp/SWE-bench_Lite \
  --limit 10 \
  --backend claude
```

### Expected Results
- Generation Rate: 85-90% (better context = fewer confusion failures)
- Resolution Rate: 18-25% (marginal improvement)
- Regression Rate: Similar to baseline (~15%)

### Status
🔴 **Not Started**

---

## EXP-004: GraphRAG with Test Impact Analysis (Planned)

### Metadata
- **Date**: TBD
- **Configuration**: Custom Claude Code plugin with GraphRAG
- **Model**: Claude Sonnet 4.5 (default)
- **Dataset**: SWE-bench Lite
- **Sample Size**: 10 instances (initial), then 50 or 300

### Hypothesis
Graph-based RAG with explicit test-code relationships will:
1. Enable automatic test impact analysis
2. Catch regressions before completion
3. Achieve lowest regression rate of all configurations

### Method

**Plugin Development**:
1. Create custom Claude Code plugin (see: https://docs.claude.com/en/docs/claude-code/plugins)
2. Build graph structure: nodes = files, edges = dependencies/test relationships
3. Implement test impact analyzer
4. Integrate with Claude Code workflow

**Graph Structure**:
```
Code File → Tests That Cover It
Test File → Code It Tests
Import → Dependency
```

**Workflow**:
1. Agent makes code changes
2. Plugin identifies impacted tests via graph traversal
3. Plugin runs impacted tests in subtask
4. Only complete if tests pass
5. Report any failures to agent for fixing

**Command**:
```bash
python code_swe_agent.py \
  --dataset_name princeton-nlp/SWE-bench_Lite \
  --limit 10 \
  --backend claude \
  --plugin graph-rag-test-impact
```

### Expected Results
- Generation Rate: 75-85% (test failures block some completions)
- Resolution Rate: 25-35% (highest of all configs)
- Regression Rate: <5% (main innovation - tests catch breaks)

### Implementation Plan
1. Week 1: Research Claude Code plugin API
2. Week 2: Build graph builder from AST/imports
3. Week 3: Implement test impact analyzer
4. Week 4: Integrate with Claude Code
5. Week 5: Test and refine

### Status
🔴 **Not Started**

---

## Comparison Matrix (To Be Filled)

| Experiment | Generation Rate | Resolution Rate | Regression Rate | Avg Time |
|------------|----------------|-----------------|-----------------|----------|
| EXP-001: Baseline | 80% (8/10) | TBD | TBD | 4.9 min |
| EXP-002: TDD Prompt | TBD | TBD | TBD | TBD |
| EXP-003: Vector RAG | TBD | TBD | TBD | TBD |
| EXP-004: GraphRAG | TBD | TBD | TBD | TBD |

**Target**: Minimize regression rate while maintaining >70% generation rate

---

## Notes & Observations

### General Patterns
- (To be filled as experiments progress)

### Unexpected Findings
- (To be filled as experiments progress)

### Open Questions
1. How to properly measure regression rate?
   - Option A: Run full test suite and count new failures
   - Option B: Use SWE-bench's built-in evaluation
   - Option C: Manual code review

2. What sample size is statistically significant?
   - 10 instances: Quick feedback, high variance
   - 50 instances: ~4 hours, moderate confidence
   - 300 instances: ~25 hours, high confidence

3. Should we test on same 10/50/300 instances across all experiments?
   - Pro: Direct comparison, controlled
   - Con: Might overfit to specific issues

---

## Appendix

### Hardware Specifications
- **Machine**: MacBook (Apple Silicon)
- **RAM**: 16GB+ recommended for Docker
- **Disk**: 50GB+ free for Docker images
- **Docker Memory Allocation**: 8GB+

### Software Versions
- **Claude Code**: v2.0.28
- **Python**: 3.13.9
- **Docker**: Latest
- **SWE-bench**: 4.1.0

### Key References
- [SWE-bench Paper](https://arxiv.org/abs/2310.06770)
- [Anthropic's SWE-bench Results](https://www.anthropic.com/engineering/swe-bench-sonnet)
- [Claude Code Documentation](https://docs.claude.com/en/docs/claude-code)
- [GraphRAG Paper](https://arxiv.org/abs/2404.16130)

---

**Last Updated**: October 28, 2025
**Next Update**: After EXP-001 evaluation completion
