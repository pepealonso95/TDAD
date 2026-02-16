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

## EXP-001B: Model Comparison - Haiku vs Sonnet

### Metadata
- **Date**: October 28, 2025 (23:00-23:10)
- **Configuration**: Controlled comparison on identical instance
- **Models**: Claude Haiku 4.5, Claude Sonnet 4.5
- **Dataset**: SWE-bench Lite (single instance)
- **Sample Size**: 1 instance × 2 runs (1 Haiku, 1 Sonnet)
- **Purpose**: Compare runtime and patch quality between models

### Hypothesis
Based on earlier runs and general model characteristics:
1. Haiku should be faster (smaller model = faster inference)
2. Haiku should produce more minimal patches (less comprehensive)
3. Sonnet should produce more comprehensive patches (tests + docs)
4. Both models should produce the correct core fix

### Method

**Commands Run**:
```bash
# Haiku 4.5 test (logged to /tmp/haiku_test.log)
python code_swe_agent.py --dataset_name princeton-nlp/SWE-bench_Lite --limit 1 --backend claude --model haiku

# Sonnet 4.5 test (logged to /tmp/sonnet_test.log)
python code_swe_agent.py --dataset_name princeton-nlp/SWE-bench_Lite --limit 1 --backend claude
```

**Test Configuration**:
- Same instance tested: `astropy__astropy-12907` (Separability matrix bug)
- Clean repository clones for each test
- No caching between runs
- Full debug logging enabled

### Results

**Instance Tested**: `astropy__astropy-12907` (Separability matrix for nested CompoundModels)

| Metric | Haiku 4.5 | Sonnet 4.5 | Difference |
|--------|-----------|------------|------------|
| **Total Runtime** | 2:35 (155s) | 4:09 (250s) | +95s (61% slower) |
| **Patch Size** | 506 chars | 12,644 chars | 25x larger |
| **Core Fix** | ✅ Correct | ✅ Correct | Identical |
| **Files Modified** | 1 file | 2 files + extras | More comprehensive |
| **Test Coverage** | None | Extensive | Significant difference |

**Core Fix (Identical)**:
```python
# File: astropy/modeling/separable.py, Line 245
# Before (bug)
cright[-right.shape[0]:, -right.shape[1]:] = 1

# After (fix)
cright[-right.shape[0]:, -right.shape[1]:] = right
```

**Detailed Breakdown**:

**Haiku 4.5 Results**:
- **Runtime**: 2:35 (155 seconds)
- **Modified**: `astropy/modeling/separable.py` only
- **Patch Size**: 506 characters
- **Approach**: Minimal fix - changed only the buggy line
- **Git Status**: 1 modified file
- **Prediction File**: `predictions_20251028_225825.jsonl`

**Sonnet 4.5 Results**:
- **Runtime**: 4:09 (250 seconds)
- **Modified**: `astropy/modeling/separable.py`, `astropy/modeling/tests/test_separable.py`
- **Added**: `docs/changes/modeling/12907.bugfix.rst`, `test_issue.py`, `test_nested_compound_fix.py`, `verify_fix.py`
- **Patch Size**: 12,644 characters
- **Approach**: Comprehensive fix with extensive validation
- **Git Status**: 2 modified + 4 untracked files
- **Prediction File**: `predictions_20251028_230313.jsonl`

### Analysis

#### Key Findings

1. **Speed Difference: 61% Slower for Sonnet**
   - Haiku: 2:35 (155s)
   - Sonnet: 4:09 (250s)
   - Additional 95 seconds for Sonnet
   - Likely due to both:
     - Slower model inference (larger model)
     - More comprehensive work (tests + docs + validation)

2. **Patch Quality: Minimal vs Comprehensive**
   - Haiku: 506 chars (1 file, core fix only)
   - Sonnet: 12,644 chars (6 files, fix + tests + docs + validation)
   - **25x size difference**
   - Both produce identical core fix
   - Sonnet adds significant validation infrastructure

3. **Correctness: Both Successful** ✅
   - Both models identified the exact same bug
   - Both applied the identical fix
   - Both return code 0 (successful execution)
   - Both generated valid patches

4. **Cost-Benefit Analysis**
   - Haiku: Faster (39% of Sonnet's time) + likely 10-20x cheaper
   - Sonnet: More comprehensive (tests reduce regression risk)
   - For rapid iteration: Haiku wins
   - For production quality: Sonnet wins

5. **Previous vs Current Comparison**
   - **Previous tests** (EXP-001): Haiku 4:43, Sonnet 4:59 (nearly identical)
   - **Current tests** (EXP-001B): Haiku 2:35, Sonnet 4:09 (61% difference)
   - **Why?**: Previous Haiku run included comprehensive tests; current run is minimal
   - **Conclusion**: Haiku's variability in comprehensiveness affects runtime

#### Unexpected Observations

1. **Haiku's Minimal Approach**:
   - This run produced only the core fix (no tests)
   - Previous runs (EXP-001) showed Haiku adding tests
   - Suggests non-deterministic behavior in comprehensiveness
   - Temperature/sampling likely affects "how much to do"

2. **Sonnet's Consistency**:
   - Always produces comprehensive patches
   - Adds tests, docs, validation scripts
   - More predictable output
   - Higher quality baseline

3. **Runtime Variability**:
   - Haiku: 2:35 to 4:45 depending on comprehensiveness
   - Sonnet: 4:09 to 4:59 (more consistent)
   - Most variance from "how much work" not "model speed"

#### Implications for Thesis

1. **Model Selection Strategy**:
   - **Haiku**: Cost-effective for initial passes, rapid iteration
     - 61% faster (when minimal)
     - 10-20x cheaper
     - Correct core fixes
     - Risk: May skip important validation

   - **Sonnet**: Production use, comprehensive validation
     - Consistent comprehensiveness
     - Extensive test coverage
     - Better regression prevention
     - Cost: Slower + more expensive

2. **Evaluation Priority**:
   - Need to run Docker evaluation to see if Sonnet's extra tests actually help
   - Key question: Does comprehensive patch improve resolution rate?
   - Or does minimal fix work just as well?

3. **Experiment Design**:
   - Use Haiku for large-scale testing (300 instances)
   - Use Sonnet for production-quality experiments
   - Consider hybrid: Haiku first pass, Sonnet for refinement

### Toolkit Validation

All toolkit components working correctly during this test:

✅ **Model Registry**: Correct mapping for both Haiku and Sonnet
✅ **Error Handling**: No directory management failures
✅ **Debug Logging**: Full output captured to log files
✅ **Haiku Support**: Executes cleanly with minimal patch generation
✅ **Sonnet Support**: Executes cleanly with comprehensive patch generation

### Next Steps

- [x] Compare Haiku vs Sonnet runtime and quality
- [x] Validate model registry and toolkit fixes
- [x] Document findings in EXPERIMENTS.md
- [ ] Run Docker evaluation on both patches to compare resolution rates
- [ ] Determine if comprehensive tests improve actual pass rates
- [ ] Decide model selection for future experiments:
  - EXP-002 (TDD prompts)
  - Full 300-instance baseline run
- [ ] Consider cost-benefit tradeoff (Haiku savings vs Sonnet quality)

### Raw Data

**Log Files**:
- Haiku: `/tmp/haiku_test.log`
- Sonnet: `/tmp/sonnet_test.log`

**Prediction Files**:
- Haiku: `predictions/predictions_20251028_225825.jsonl` (506 chars)
- Sonnet: `predictions/predictions_20251028_230313.jsonl` (12,644 chars)

**Repository State**: Commit TBD (after updating EXPERIMENTS.md)

### Conclusion

**Haiku 4.5 is significantly faster (61%) but produces minimal patches.** Both models correctly identify and fix the core bug, but Sonnet adds comprehensive test coverage that may prevent regressions.

**Key Tradeoff**:
- Haiku: 2:35 runtime, 506 char patch, 10-20x cheaper → Best for rapid iteration
- Sonnet: 4:09 runtime, 12,644 char patch, more expensive → Best for comprehensive validation

**Critical Question**: Does Sonnet's additional test coverage actually improve SWE-bench resolution rates? This requires Docker evaluation to determine if comprehensive patches pass more tests than minimal patches.

**Recommendation**:
- Use Haiku for large-scale testing (300 instances) to save time and cost
- Use Sonnet for production experiments (TDD, GraphRAG) where quality matters most
- Consider hybrid approach: Haiku generates initial patches, Sonnet refines failures

**Status**: ✅ Complete - Model Comparison Documented

---

## EXP-001C: SWE-bench Verified Dataset Test

### Metadata
- **Date**: October 28, 2025 (23:16)
- **Configuration**: Switch from SWE-bench Lite to SWE-bench Verified
- **Model**: Claude Haiku 4.5
- **Dataset**: SWE-bench Verified (500 human-validated instances)
- **Sample Size**: 1 instance
- **Purpose**: Validate toolkit works with SWE-bench Verified dataset

### Hypothesis
The toolkit should work seamlessly with SWE-bench Verified, which contains 500 human-validated test instances (vs 300 in Lite). This dataset has higher quality assurance and is better for production evaluation.

### Method

**Dataset Change**:
- **Previous**: `princeton-nlp/SWE-bench_Lite` (300 instances)
- **New**: `princeton-nlp/SWE-bench_Verified` (500 instances, human-validated)

**Command**:
```bash
python code_swe_agent.py \
  --dataset_name princeton-nlp/SWE-bench_Verified \
  --limit 1 \
  --backend claude \
  --model haiku
```

### Results

**Instance Tested**: `astropy__astropy-12907` (same as EXP-001B tests)

| Metric | Result |
|--------|--------|
| **Total Runtime** | 2:04 (124 seconds) |
| **Patch Size** | 2,037 characters |
| **Core Fix** | ✅ Correct (line 245) |
| **Files Modified** | 2 (separable.py + test_separable.py) |
| **Test Coverage** | Comprehensive regression test added |
| **Generation Status** | ✅ Success |

**Core Fix (Identical to EXP-001B)**:
```python
# File: astropy/modeling/separable.py, Line 245
# Before (bug)
cright[-right.shape[0]:, -right.shape[1]:] = 1

# After (fix)
cright[-right.shape[0]:, -right.shape[1]:] = right
```

**Test Coverage Added**:
- New test function: `test_nested_compound_models_separability()`
- 36 lines of test code
- Tests both nested and non-nested compound models
- Includes expected separability matrix validation
- Documents regression test for issue #12907

### Analysis

#### Key Findings

1. **Dataset Compatibility** ✅
   - SWE-bench Verified loaded successfully (500 instances)
   - No code changes required in toolkit
   - Same interface as SWE-bench Lite
   - Fast loading (dataset cached locally)

2. **Haiku Performance Consistency**
   - Runtime: 2:04 (124s) vs previous 2:35 (155s)
   - **20% faster** than EXP-001B Haiku test
   - Produced comprehensive patch (2,037 chars) vs minimal (506 chars)
   - Shows Haiku's non-deterministic comprehensiveness again

3. **Patch Quality: Comprehensive**
   - This time Haiku added test coverage (unlike EXP-001B minimal approach)
   - 2,037 characters: between EXP-001B Haiku (506) and Sonnet (12,644)
   - Regression test included with proper documentation
   - Professional code quality

4. **Same Instance, Different Behavior**
   - Same instance (`astropy__astropy-12907`) across EXP-001B and EXP-001C
   - EXP-001B Haiku: 506 chars, no tests
   - EXP-001C Haiku: 2,037 chars, comprehensive test
   - **4x size difference** on identical issue
   - Confirms Haiku's variability in approach

#### Haiku Behavior Patterns

**Observed Across Multiple Runs**:
| Run | Dataset | Runtime | Patch Size | Test Coverage |
|-----|---------|---------|------------|---------------|
| EXP-001B Run 1 | Lite | 2:35 (155s) | 506 chars | None |
| EXP-001C | Verified | 2:04 (124s) | 2,037 chars | Comprehensive |

**Pattern**: Haiku varies between:
- **Minimal mode**: Core fix only (506 chars)
- **Comprehensive mode**: Fix + tests + docs (2,037 chars)
- **Not correlated with dataset** (same instance, different behavior)
- Likely influenced by sampling/temperature

### Implications for Thesis

1. **Dataset Selection**: SWE-bench Verified is recommended for production experiments
   - 500 vs 300 instances (67% more data)
   - Human-validated quality
   - Same API, no code changes needed
   - Better statistical significance

2. **Haiku Variability Challenge**:
   - Cannot rely on consistent comprehensiveness
   - May need multiple runs per instance
   - Or use Sonnet for consistent quality
   - Consider temperature parameter tuning

3. **Future Experiment Design**:
   - **EXP-002 (TDD)**: Use SWE-bench Verified
   - **EXP-003 (Vector RAG)**: Use SWE-bench Verified
   - **EXP-004 (GraphRAG)**: Use SWE-bench Verified
   - Larger sample size for baseline (50-100 instances)

### Next Steps

- [x] Validate SWE-bench Verified dataset compatibility
- [x] Test Haiku on Verified dataset
- [x] Document findings in EXPERIMENTS.md
- [ ] Run larger baseline on SWE-bench Verified (10-50 instances)
- [ ] Compare Verified vs Lite instances (overlap analysis)
- [ ] Decide on final dataset for all experiments
- [ ] Document dataset selection rationale in thesis

### Raw Data

**Log File**: `/tmp/haiku_verified_test.log`
**Prediction File**: `predictions/predictions_20251028_231629.jsonl` (2,037 chars)
**Dataset**: `princeton-nlp/SWE-bench_Verified` (500 instances)

### Conclusion

**SWE-bench Verified is fully compatible and ready for production use.** The dataset loads quickly, has more instances (500 vs 300), and provides human-validated quality assurance.

Haiku's performance on Verified (2:04, 2,037 chars) demonstrates its capability to produce quality patches with test coverage, contrasting with the minimal approach observed in EXP-001B. This variability reinforces the need for either:
- Multiple runs per instance to capture best result
- Sonnet for consistent comprehensive quality
- Ensemble approach (Haiku + Sonnet)

**Recommendation**: Switch all future experiments to SWE-bench Verified for better quality and larger sample size.

**Status**: ✅ Complete - SWE-bench Verified Validated

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

## EXP-004: GraphRAG Test Impact Analysis

### Metadata
- **Date**: November 19, 2025
- **Configuration**: Claude Code + GraphRAG MCP Server + TDD Prompt
- **Model**: Claude Sonnet 4.5
- **Sample Size**: Start with 5-10, scale to 50+
- **Dataset**: SWE-bench Verified
- **Script**: `code_swe_agent_graphrag.py`
- **Prompt**: `prompts/swe_bench_graphrag.txt`

### Hypothesis
GraphRAG-powered test impact analysis will:
1. **Reduce test execution time** by 80-90% (10-50 tests vs 100-500 full suite)
2. **Maintain regression detection** at same level as full test suite
3. **Enable faster feedback loops** for AI agent
4. **Improve resolution rate** via targeted test validation

**Core Innovation**: Intelligent test selection via code-test dependency graph instead of running entire test suite.

### Configuration

**GraphRAG MCP Server Components**:
1. **AST-Based Parser** (`graph_builder.py`)
   - Extracts functions, classes, imports, calls
   - Function-level structural chunking
   - Incremental updates via git diff

2. **Test Linker** (`test_linker.py`)
   - Naming conventions: `test_func` → `func`
   - Coverage data: coverage.py integration
   - Static analysis: imports and calls from tests

3. **Impact Analyzer** (`impact_analyzer.py`)
   - Direct testing (score: 1.0)
   - Transitive call dependencies (score: 0.7)
   - Coverage dependencies (score: variable)
   - Import dependencies (score: 0.5)

4. **Neo4j Graph Database** (`graph_db.py`)
   - Nodes: Files, Functions, Classes, Tests
   - Edges: CONTAINS, CALLS, IMPORTS, TESTS, INHERITS, DEPENDS_ON

**Workflow**:
1. Clone repository
2. Build code-test dependency graph (one-time per repo)
3. Execute Claude Code with GraphRAG prompt
4. Detect changed files via git diff
5. Query graph for impacted tests
6. Run only impacted tests (not full suite)
7. Report regressions if any impacted tests fail

### Method

```bash
# Setup
cd /Users/rafaelalonso/Development/Master/Tesis/claudecode_n_codex_swebench
pip install -r requirements_mcp.txt
export NEO4J_EMBEDDED=true

# Quick test (5 instances)
python code_swe_agent_graphrag.py \
  --dataset_name princeton-nlp/SWE-bench_Verified \
  --limit 5 \
  --backend claude

# Full run (50 instances for statistical significance)
python code_swe_agent_graphrag.py \
  --dataset_name princeton-nlp/SWE-bench_Verified \
  --limit 50 \
  --backend claude

# Baseline comparison (no GraphRAG, just TDD)
python code_swe_agent_graphrag.py \
  --dataset_name princeton-nlp/SWE-bench_Verified \
  --limit 5 \
  --backend claude \
  --no-graphrag
```

### Metrics to Track

**Primary Metrics** (same as other experiments):
- Generation Rate: % instances producing non-empty patches
- Resolution Rate: % patches that fix the issue
- Regression Rate: % patches that break existing tests (**PRIMARY METRIC**)

**GraphRAG-Specific Metrics**:
- Graph Build Time: Time to index repository
- Impact Analysis Time: Time to query graph for impacted tests
- Tests Identified: Number of impacted tests found
- Test Efficiency Ratio: Impacted tests / Total tests (target: 0.1-0.2)
- Impact Analysis Accuracy: Did we catch all regressions with subset?

**Time Metrics**:
- Total Time per Instance
- Graph Build Time per Repo (amortized)
- Test Execution Time (impacted only)
- Traditional Test Time (full suite, for comparison)

### Expected Results

**Conservative Estimate**:
- Generation Rate: ~80% (same as baseline)
- Resolution Rate: ~70% (slight improvement from targeted testing)
- Regression Rate: ~10-15% (better than baseline due to TDD + impact analysis)
- Test Efficiency: 10-20 tests instead of 100+ (80-90% time savings)
- Graph Build Time: 30-60s per repository
- Impact Analysis Time: 1-5s per query

**Ambitious Goal**:
- Regression Rate: <5% (ideal state)
- Test Efficiency: >90% time savings
- Impact Accuracy: 100% (no missed regressions)

### Results
*To be filled after running experiment*

**Quick Test (5 instances)**:
- Generation Rate: TBD
- Graph Builds: TBD
- Average Impacted Tests: TBD
- Test Efficiency Ratio: TBD

**Full Run (50 instances)**:
- Generation Rate: TBD
- Resolution Rate: TBD
- Regression Rate: TBD
- Average Test Time Savings: TBD

### Analysis
*To be filled after evaluation*

**Key Questions**:
1. Did GraphRAG identify all tests that would have failed?
2. Were there false negatives (missed impacted tests)?
3. Were there false positives (unnecessary tests run)?
4. What was the actual time savings?
5. Did targeted testing improve or hurt resolution rate?
6. What impact scores (thresholds) worked best?

### Challenges Encountered
*To be documented during execution*

**Technical Challenges**:
- Neo4j setup and configuration
- Graph building performance for large repos
- Coverage.py integration complexity
- Git diff parsing edge cases

**Conceptual Challenges**:
- Determining appropriate impact thresholds
- Handling dynamic dependencies (eval, imports)
- Dealing with test interdependencies
- Validating impact analysis accuracy

### Next Steps
- [ ] Run initial 5-instance test
- [ ] Validate graph building works correctly
- [ ] Verify impact analysis identifies tests
- [ ] Compare against baseline (EXP-001)
- [ ] Scale to 50 instances
- [ ] Evaluate with Docker to get regression rates
- [ ] Compare time savings vs accuracy trade-offs
- [ ] Analyze false negatives/positives
- [ ] Tune impact score thresholds if needed
- [ ] Final 100+ instance evaluation

### Implementation Details

**New Files Created**:
```
mcp_server/
├── server.py                    # FastAPI MCP server (406 lines)
├── graph_db.py                  # Neo4j database manager (400 lines)
├── graph_builder.py             # AST parser & graph builder (450 lines)
├── test_linker.py               # Test-to-code linker (370 lines)
├── impact_analyzer.py           # Impact analysis logic (330 lines)
├── config.py                    # Configuration (130 lines)
└── README.md                    # Documentation

utils/
└── mcp_graphrag_interface.py   # Client interface (400 lines)

prompts/
└── swe_bench_graphrag.txt      # GraphRAG-enhanced TDD prompt (180 lines)

code_swe_agent_graphrag.py      # Evaluation script (600 lines)

requirements_mcp.txt             # Additional dependencies
```

**Total Lines of Code**: ~3,266 lines (new implementation)

### Status
🟡 **Implementation Complete - Ready for Testing**

**Completed**:
- ✅ MCP server infrastructure
- ✅ AST-based code parsing
- ✅ Neo4j graph database
- ✅ Test linking strategies
- ✅ Impact analysis algorithms
- ✅ Client interface
- ✅ Evaluation script
- ✅ Documentation

**Next**:
- ⏳ Initial 5-instance test run
- ⏳ Validation and debugging
- ⏳ Full experimental evaluation

---

## Comparison Matrix

### Experiment Comparison

| Experiment | Dataset | Generation Rate | Resolution Rate | Regression Rate | Avg Time | Status |
|------------|---------|----------------|-----------------|-----------------|----------|--------|
| EXP-001: Baseline (Sonnet) | Lite | 80% (8/10) | TBD | TBD | 4.9 min | ⏳ Eval Pending |
| EXP-001B: Haiku 4.5 | Lite | 100% (1/1) | TBD | TBD | 2.6 min | ✅ Complete |
| EXP-001B: Sonnet 4.5 | Lite | 100% (1/1) | TBD | TBD | 4.2 min | ✅ Complete |
| EXP-001C: Haiku 4.5 | Verified | 100% (1/1) | TBD | TBD | 2.1 min | ✅ Complete |
| EXP-002: TDD Prompt | TBD | TBD | TBD | TBD | TBD | 🔴 Not Started |
| EXP-003: Vector RAG | TBD | TBD | TBD | TBD | TBD | 🔴 Not Started |
| EXP-004: GraphRAG | Verified | TBD | TBD | TBD | TBD | 🟡 Ready to Test |
| **EXP-007: Qwen Baseline** | Verified | 65% (65/100)* | TBD | TBD | ~1.9 min | ✅ Complete |
| **EXP-007B: Qwen Fixed** | Verified | 57% (57/100) | TBD | TBD | ~2 min | ✅ Complete |
| **EXP-008: Qwen TDD Prompt** | Verified | 64% (64/100)* | TBD | TBD | ~2 min | ✅ Complete |
| **EXP-009: Qwen GraphRAG** | Verified | **95% (95/100)** | TBD | TBD | ~7 min | ✅ Complete |

*Note: EXP-007/008 rates inflated by ~7 placeholder patches; EXP-007B is the true quality baseline

### Model Comparison (EXP-001B + EXP-001C)

**EXP-001B: Haiku vs Sonnet on SWE-bench Lite**
| Metric | Haiku 4.5 | Sonnet 4.5 | Winner |
|--------|-----------|------------|--------|
| **Speed** | 2:35 (155s) | 4:09 (250s) | Haiku (61% faster) |
| **Patch Size** | 506 chars | 12,644 chars | Haiku (minimal) |
| **Cost** | ~$0.005 | ~$0.05-0.10 | Haiku (10-20x cheaper) |
| **Comprehensiveness** | Minimal | Extensive | Sonnet |
| **Test Coverage** | None | Comprehensive | Sonnet |
| **Core Fix** | ✅ Correct | ✅ Correct | Tie |
| **Files Modified** | 1 | 6 | Haiku (focused) |

**Haiku Variability Analysis (Same Instance)**
| Run | Dataset | Patch Size | Test Coverage | Runtime | Consistency |
|-----|---------|------------|---------------|---------|-------------|
| EXP-001B | Lite | 506 chars | None | 2:35 | Minimal mode |
| EXP-001C | Verified | 2,037 chars | Comprehensive | 2:04 | Comprehensive mode |
| **Variance** | - | **4x difference** | Major variance | 20% faster | Non-deterministic |

**Key Finding**: Haiku produces significantly different patches for the same instance, varying from minimal (506) to comprehensive (2,037) approaches. Sonnet is more consistent.

**Target**: Minimize regression rate while maintaining >70% generation rate

**🎉 EXP-009 ACHIEVED**: 95% generation rate with 100% test inclusion - exceeds target!

**📊 True Baseline (EXP-007B)**: 57% generation rate after quality filtering - EXP-009 is +38% improvement!

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

**Last Updated**: January 18, 2026 01:00
**Next Update**: After Docker evaluation of EXP-007B and EXP-009 predictions


---

## EXP-005: Full Three-Way Comparison (50 Instances Each)

### Metadata
- **Date**: 2025-11-20 04:01
- **Dataset**: SWE-bench_Verified
- **Sample Size**: 50 instances per experiment
- **Experiments**: Baseline, TDD, GraphRAG

### Executive Summary

**Winner**: 🏆 **Baseline**

**Key Findings:**
- Baseline achieved the highest generation rate (46.0%), 46.0% better than GraphRAG
- Baseline produced the largest patches on average (9292 chars), suggesting more comprehensive fixes
- Baseline had the fewest errors (27), indicating better stability
- GraphRAG identified an average of 0.0 impacted tests per instance, with graph building taking 0.0s on average

### Detailed Metrics Comparison

| Metric | Baseline | TDD | GraphRAG |
|--------|----------|-----|----------|
| **Generation Rate** | 46.0% | 0.0% | 0.0% |
| **Avg Patch Size** | 9,292 chars | 0 chars | 0 chars |
| **Median Patch Size** | 6,453 chars | 0 chars | 0 chars |
| **Errors** | 27 | 50 | 50 |

### GraphRAG-Specific Metrics

- **Total Graphs Built**: 0
- **Avg Graph Build Time**: 0.0s
- **Avg Impacted Tests Found**: 0.0 tests
- **Avg Impact Analysis Time**: 0.00s
- **Test Range**: 0 - 0 tests

### Error Analysis

**Baseline Errors:**
- Execution Failed: 21
- Repository Setup: 6

**TDD Errors:**
- Execution Failed: 50

**GraphRAG Errors:**
- Execution Failed: 39
- Repository Setup: 11

### Recommendations

1. Use Baseline for production SWE-bench evaluation based on overall performance
2. Investigate why TDD has low generation rate - may need prompt refinement
3. Run Docker evaluation to measure actual resolution and regression rates for GraphRAG

### Next Steps

- [ ] Run Docker evaluation on all three prediction sets
- [ ] Calculate resolution rates from evaluation results
- [ ] Measure regression rates for each approach
- [ ] Compare actual test execution times
- [ ] Analyze specific instances where approaches differed

### Prediction Files

- **Baseline**: `predictions_20251120_010951.jsonl`
- **TDD**: `predictions_20251120_032821.jsonl`
- **GraphRAG**: `predictions_graphrag_20251120_034523.jsonl`


---

## EXP-005: Full Three-Way Comparison (50 Instances Each)

### Metadata
- **Date**: 2025-11-20 04:02
- **Dataset**: SWE-bench_Verified
- **Sample Size**: 50 instances per experiment
- **Experiments**: Baseline, TDD, GraphRAG

### Executive Summary

**Winner**: 🏆 **Baseline**

**Key Findings:**
- Baseline achieved the highest generation rate (46.0%), 46.0% better than GraphRAG
- Baseline produced the largest patches on average (9828 chars), suggesting more comprehensive fixes
- Baseline had the fewest errors (27), indicating better stability
- GraphRAG identified an average of 0.0 impacted tests per instance, with graph building taking 0.0s on average

### Detailed Metrics Comparison

| Metric | Baseline | TDD | GraphRAG |
|--------|----------|-----|----------|
| **Generation Rate** | 46.0% | 0.0% | 0.0% |
| **Avg Patch Size** | 9,828 chars | 0 chars | 0 chars |
| **Median Patch Size** | 8,462 chars | 0 chars | 0 chars |
| **Errors** | 27 | 50 | 50 |

### GraphRAG-Specific Metrics

- **Total Graphs Built**: 0
- **Avg Graph Build Time**: 0.0s
- **Avg Impacted Tests Found**: 0.0 tests
- **Avg Impact Analysis Time**: 0.00s
- **Test Range**: 0 - 0 tests

### Error Analysis

**Baseline Errors:**
- Repository Setup: 3
- Execution Failed: 24

**TDD Errors:**
- Execution Failed: 50

**GraphRAG Errors:**
- Execution Failed: 38
- Repository Setup: 12

### Recommendations

1. Use Baseline for production SWE-bench evaluation based on overall performance
2. Investigate why TDD has low generation rate - may need prompt refinement
3. Run Docker evaluation to measure actual resolution and regression rates for GraphRAG

### Next Steps

- [ ] Run Docker evaluation on all three prediction sets
- [ ] Calculate resolution rates from evaluation results
- [ ] Measure regression rates for each approach
- [ ] Compare actual test execution times
- [ ] Analyze specific instances where approaches differed

### Prediction Files

- **Baseline**: `predictions_20251120_010837.jsonl`
- **TDD**: `predictions_20251120_032802.jsonl`
- **GraphRAG**: `predictions_graphrag_20251120_034503.jsonl`

### Issue discovered
During the experiments, claude code run out of context due to a timeout and had to wait to reset. Next experiments running forward will be run with a local LLM to avoid this issue.

---

## EXP-005: GPT-OSS Integration via Direct Agent

### Metadata
- **Date**: November 20, 2025
- **Configuration**: Direct GPT-OSS agent bypassing Codex CLI
- **Model**: GPT-OSS 20B via Ollama
- **Status**: Implementation complete, testing pending
- **Type**: Infrastructure/Tooling development

### Problem Statement

Initial attempts to use Codex CLI with GPT-OSS for SWE-bench evaluation failed due to incomplete tool integration:

1. **Codex CLI + GPT-OSS**: Generated empty patches (0 characters)
2. **Root Cause**: Codex CLI reports "shell calls are unsupported: maybe require proper 'shell' tool"
3. **Impact**: GPT-OSS could generate responses but couldn't execute actions (file edits, bash commands)

### Hypothesis

Creating a direct GPT-OSS agent (similar to QwenAgent) that bypasses Codex CLI and handles tool execution itself will enable GPT-OSS to:
- Execute shell commands
- Read and write files
- Generate non-empty patches for SWE-bench instances

### Method

#### Architecture Designed

Created three-layer integration following the QwenAgent pattern:

1. **Agent Layer** (`utils/gptoss_agent.py` - 350 lines)
   - ReAct-style agent loop with max 20 iterations
   - Direct Ollama API calls via HTTP
   - Tool execution: `read_file`, `write_file`, `bash`
   - Sliding window context management (4 message pairs)
   - Task completion detection

2. **Interface Layer** (`utils/gptoss_interface.py` - 89 lines)
   - Wraps GPTOSSAgent for SWE-bench integration
   - Checks Ollama service availability
   - Converts agent results to expected format

3. **Main Script Updates** (`code_swe_agent.py`)
   - Added "gptoss" backend support
   - Updated argparse choices: `["claude", "codex", "qwen", "gptoss"]`
   - Skip CLI check for Ollama-based backends

#### GPT-OSS Specific Configuration

Based on Unsloth documentation (https://docs.unsloth.ai/models/gpt-oss-how-to-run-and-fine-tune):

```python
{
    "temperature": 1.0,  # GPT-OSS recommended
    "top_p": 1.0,        # GPT-OSS recommended  
    "top_k": 0,          # GPT-OSS recommended
    "num_predict": 2048,
    "num_ctx": 16384,    # 16K context window
    "num_batch": 256
}
```

#### Tool Calling Protocol

Agent uses XML-style format:
```xml
<tool_call>
<tool>read_file</tool>
<path>path/to/file.py</path>
</tool_call>
```

Alternative simple format:
```
TOOL: read_file("path/to/file.py")
TOOL: write_file("path/to/file.py", "content")
TOOL: bash("ls -la")
```

### Implementation Details

#### Files Created

1. **`utils/gptoss_agent.py`**
   - `GPTOSSAgent` class with autonomous tool loop
   - `_call_ollama()`: HTTP API calls with retry logic
   - `_read_file()`, `_write_file()`, `_run_bash()`: Tool implementations
   - `_extract_tool_calls()`: Parse tool requests from GPT-OSS
   - `_is_task_complete()`: Detect completion markers
   - `_apply_sliding_window()`: Context management
   - `run_task()`: Main agent loop

2. **`utils/gptoss_interface.py`**
   - `GPTOSSCodeInterface` class
   - Ollama service verification
   - `execute_code_cli()`: Wrapper matching expected interface

3. **`code_swe_agent.py` modifications**
   - Import: `from utils.gptoss_interface import GPTOSSCodeInterface`
   - Backend selection: `elif self.backend == "gptoss": self.interface = GPTOSSCodeInterface()`
   - CLI check bypass: `if backend not in ["qwen", "gptoss"]:`

### Usage

```bash
# Run single instance test
python code_swe_agent.py \
  --dataset_name princeton-nlp/SWE-bench_Verified \
  --limit 1 \
  --backend gptoss

# Run full benchmark
python code_swe_agent.py \
  --dataset_name princeton-nlp/SWE-bench_Verified \
  --limit 50 \
  --backend gptoss
```

### Comparison: Codex CLI vs Direct Agent

| Aspect | Codex CLI Approach | Direct Agent Approach |
|--------|-------------------|----------------------|
| **Tool Execution** | Failed - "shell calls unsupported" | Implemented directly |
| **GPT-OSS Integration** | Incomplete in Codex CLI | Direct Ollama API calls |
| **Patch Generation** | 0 characters (empty) | Expected to work |
| **Architecture** | Single CLI call | Multi-iteration agent loop |
| **Context Management** | Handled by Codex CLI | Sliding window implemented |
| **Debugging** | Limited visibility | Full logging of iterations |

### Technical Decisions

1. **Why bypass Codex CLI?**
   - Codex CLI's Ollama integration doesn't support tool execution
   - Cannot provide "shell" tool GPT-OSS needs
   - Direct approach gives full control

2. **Why follow QwenAgent pattern?**
   - Proven architecture already working in codebase
   - Similar Ollama API usage
   - Consistent interface with other backends

3. **Why GPT-OSS over Qwen?**
   - User requested GPT-OSS specifically
   - Qwen had 500 API errors in testing
   - GPT-OSS designed for code generation tasks

### Results

**Status**: Implementation complete, initial testing in progress

**Observed During Development**:
- GPT-OSS connects successfully to Ollama
- Generates "thinking" tokens when called via Codex CLI
- But cannot execute actions due to missing tool interface
- Direct agent approach resolves this architectural limitation

**Pending**:
- [ ] Complete single-instance test
- [ ] Verify patch generation (non-empty)
- [ ] Run 10-instance sample
- [ ] Compare with Claude Code baseline
- [ ] Full 50-instance benchmark

### Analysis

#### Key Insights

1. **Codex CLI Limitations**
   - Not all LLM integrations in Codex CLI are feature-complete
   - Ollama/GPT-OSS missing tool execution layer
   - CLI designed more for interactive use than autonomous agents

2. **Architecture Lessons**
   - Direct API control > CLI wrappers for research
   - Tool-calling protocol needs explicit implementation
   - Agent loops require context management strategy

3. **GPT-OSS Characteristics** (from Unsloth docs)
   - Requires specific inference parameters
   - 20B parameter model (13GB size)
   - Designed for code generation
   - Channel-based chat template format

#### Comparison with Other Backends

| Backend | Integration Method | Tool Execution | Status |
|---------|-------------------|----------------|--------|
| **Claude Code** | Claude CLI | Built-in | Working ✅ |
| **Codex (GPT-OSS)** | Codex CLI | Unsupported ❌ | Failed |
| **GPT-OSS Direct** | Custom agent | Implemented | Testing 🔄 |
| **Qwen** | Custom agent | Implemented | 500 errors ⚠️ |

### Limitations & Concerns

1. **Testing Incomplete**
   - Implementation done but not fully validated
   - May encounter unexpected GPT-OSS behaviors
   - Tool extraction format might need refinement

2. **Performance Unknown**
   - No data on GPT-OSS code generation quality
   - Unclear how 20B model compares to Claude Sonnet 4.5
   - Context window handling untested at scale

3. **Ollama Dependency**
   - Requires Ollama service running locally
   - 13GB model size (memory requirement)
   - May have rate limiting or stability issues

4. **Empty Response Pattern**
   - Early testing showed GPT-OSS returning empty strings
   - May indicate prompt format issues
   - Could require prompt engineering for GPT-OSS

### Next Steps

#### Immediate (Testing Phase)

- [ ] Complete single-instance test with GPT-OSS agent
- [ ] Debug if empty responses continue
- [ ] Verify patch extraction works correctly
- [ ] Check git diff captures changes properly

#### Validation Phase

- [ ] Run 10-instance sample comparison
- [ ] Compare generation rates: Claude vs GPT-OSS
- [ ] Measure execution time per instance
- [ ] Identify error patterns

#### Full Benchmark (If Testing Successful)

- [ ] Run 50-instance SWE-bench Verified
- [ ] Docker evaluation for resolution rates
- [ ] Calculate regression rates
- [ ] Write up comparison analysis

### Artifacts

**Code Files Created**:
- `claudecode_n_codex_swebench/utils/gptoss_agent.py`
- `claudecode_n_codex_swebench/utils/gptoss_interface.py`
- Modified: `claudecode_n_codex_swebench/code_swe_agent.py`

**Documentation**:
- This experiment log entry
- Inline code comments explaining GPT-OSS requirements

**No predictions generated yet** - testing phase

### References

- Unsloth GPT-OSS Documentation: https://docs.unsloth.ai/models/gpt-oss-how-to-run-and-fine-tune
- Ollama API: http://localhost:11434/api/chat
- QwenAgent pattern: `claudecode_n_codex_swebench/utils/qwen_agent.py`
- Codex CLI issue discovered: "shell calls are unsupported: maybe require proper 'shell' tool"

### Decision Log

**Why not fix Codex CLI integration?**
- Codex CLI is external tool (not owned by thesis)
- Would require understanding Codex CLI internals
- Direct agent approach faster to implement
- More maintainable for research purposes

**Why not just use Qwen instead?**
- User specifically requested GPT-OSS
- Qwen had reliability issues (500 errors)
- GPT-OSS is OpenAI's open model (more established)
- Good to have multiple OSS options

**Why implement agent loop vs single-shot?**
- Complex SWE-bench tasks need iteration
- Read-analyze-modify-test workflow requires multiple turns
- Claude Code succeeds via iterative approach
- Agent loop matches proven pattern

---

## EXP-006: QwenAgent Native Function Calling Implementation

### Metadata
- **Date**: January 13, 2026
- **Configuration**: Fixed QwenAgent with native function calling support
- **Model**: qwen3-coder:30b (18GB, already installed in Ollama)
- **Status**: Implementation complete, testing successful

### Problem Statement

The previous QwenAgent implementation had tool execution failures due to:
1. Fragile text-based tool parsing (simple `split(',')` broke on content with commas)
2. No support for Qwen3's native function calling
3. Lost `tool_calls` and `thinking` fields from API response
4. Low truncation limits (2K/4K) insufficient for SWE-bench files

### Changes Implemented

**File**: `claudecode_n_codex_swebench/utils/qwen_agent.py`

| Change | Description |
|--------|-------------|
| Native function calling | Added `_get_tool_definitions()` and `tools` in API payload |
| Return full message dict | `_call_ollama()` now returns full dict, not just content |
| Improved tool extraction | `_extract_tool_calls()` handles native calls + improved regex |
| System role | Changed from `"user"` to `"system"` for system prompt |
| Increased limits | `max_result_len`: 2K→8K, `max_total_len`: 4K→12K |
| Thinking field | Handles `thinking` field in responses |
| Native tool response | Uses `"role": "tool"` for native function call responses |
| More completion markers | Added `"fix has been implemented"`, `"successfully fixed"`, etc. |
| Increased retries | `max_retries`: 3→5 for large context handling |

### Test Results

**Test 1: Basic read_file task** ✅
```
📞 Found 1 native function calls
✅ Converted 1 native calls
🔧 Executing: read_file({'path': 'hello.py'})
Result: success=True, iterations=7
```

**Test 2: write_file with complex content (commas)** ✅
```
Created data.py with: x = [1, 2, 3, 4, 5] and def process(a, b, c): return a + b + c
Native function calling handled commas correctly
Result: success=True, iterations=8
```

**Test 3: SWE-bench instance** ⚠️
- Native function calling worked for 10 iterations
- Agent correctly found files, read code, reproduced issue
- Hit 500 error at iteration 11 (28K chars context - memory limit)
- This is a resource constraint, not code bug

### Key Findings

1. **Native function calling works reliably**
   - Qwen3 properly uses the defined tools
   - JSON argument parsing handles complex content
   - No more comma-splitting issues

2. **Memory constraint with large contexts**
   - qwen3-coder:30b hits 500 errors at ~28K context
   - Sliding window helps but file reads add significant context
   - May need to reduce file truncation or use smaller model

3. **Agent behavior**
   - Agent sometimes reads same file multiple times
   - Could benefit from caching or smarter context management
   - Task completion detection works well

### Recommendations

1. **For production use**: Consider using the Q4_K_M quantized version (17.5GB) or smaller model
2. **Context optimization**: Reduce file truncation from 10K to 5K chars
3. **Caching**: Add file content caching to avoid redundant reads
4. **Model alternatives**: Test with smaller Qwen3 variants for memory-constrained systems

### Files Modified

- `claudecode_n_codex_swebench/utils/qwen_agent.py` - All changes

### Status
✅ **Implementation Complete** - Native function calling working, ready for SWE-bench experiments with memory considerations

---

## EXP-007: Qwen Single-Shot Approach

### Metadata
- **Date**: January 13, 2026
- **Configuration**: Simplified single-shot Ollama API call (no agent loop)
- **Model**: qwen3-coder:30b via Ollama
- **Dataset**: SWE-bench Verified
- **Status**: ✅ Working - First successful patch generated

### Problem Statement

EXP-006's agent loop approach had issues:
1. **500 errors** at ~28K context despite 256K `num_ctx` setting
2. **Sliding window** dropped too much context - model kept re-reading same files
3. **20 iterations** spent analyzing without making changes
4. **Complex agent loop** was fragile and hard to debug

### Solution: Single-Shot Approach

Completely rewrote `utils/qwen_interface.py` to match how Claude Code works:
- **One API call** instead of multi-turn agent loop
- **Explicit output format** using `<<<FILE: path>>>` markers
- **Direct file extraction** from response
- **No iteration management** - model outputs complete solution

### Implementation

**File**: `claudecode_n_codex_swebench/utils/qwen_interface.py` (complete rewrite)

**Key Components**:

1. **Single Prompt** - All context upfront, explicit format instructions:
```python
full_prompt = f"""{prompt}

YOU MUST FIX THIS BUG. Output the COMPLETE fixed file(s).

CRITICAL: Use this EXACT format for EACH file you change:

<<<FILE: path/to/file.py>>>
```python
# The COMPLETE file content goes here
```
<<<END FILE>>>

RULES:
- Output ONLY code, no explanations
- Include the COMPLETE file, not snippets
..."""
```

2. **Flexible Regex Extraction** - Multiple patterns for robustness:
```python
# Pattern 1: <<<FILE: path>>> format (END FILE marker optional)
file_pattern1 = r'<<<FILE:\s*([^\s>]+\.py)>>>\s*```(?:python)?\s*\n(.*?)```'

# Pattern 2: FILE: path followed by code block
file_pattern2 = r'FILE:\s*([^\s`\n]+\.py)\s*\n```(?:python)?\n(.*?)```'

# Pattern 3: **path** or `path` followed by code block
file_pattern3 = r'(?:\*\*|`)([^\s*`]+\.py)(?:\*\*|`)\s*(?::|)\s*\n```(?:python)?\n(.*?)```'
```

3. **Ollama API Settings**:
```python
{
    "num_ctx": 262144,  # 256K context
    "temperature": 0.1,
    "num_predict": 8192,  # Long responses
}
```

### Test Results

**Single Instance Test** ✅
```
Processing astropy__astropy-12907
📄 Found 1 file change(s) in response
📝 Attempting to update: astropy/modeling/separable.py
✅ Updated: astropy/modeling/separable.py
Git status: M astropy/modeling/separable.py
Patch length: 41,954 characters
```

**Performance**:
- Total runtime: 6:43 (403 seconds)
- Model response: 31,103 characters
- Patch generated: 41,954 characters
- Files modified: 1 (separable.py)

### Comparison: Agent Loop vs Single-Shot

| Aspect | Agent Loop (EXP-006) | Single-Shot (EXP-007) |
|--------|---------------------|----------------------|
| **API Calls** | 15-20 per instance | 1 per instance |
| **Context Issues** | 500 errors at 28K | None with 256K |
| **Code Generated** | 0 (20 iterations analyzing) | 41K chars patch |
| **Complexity** | ~500 lines agent code | ~230 lines interface |
| **Debugging** | Multiple iteration logs | Single response |
| **Success** | ❌ No patch | ✅ Patch generated |

### Key Insights

1. **Simpler is better** - Single-shot matches how Claude Code CLI works internally
2. **Explicit format critical** - Model needs exact output structure specified
3. **END FILE marker optional** - Models don't always include closing markers
4. **256K context works** - No memory issues with single large call

### Files Modified

- `utils/qwen_interface.py` - Complete rewrite to single-shot
- `utils/qwen_agent.py` - Kept but no longer used by qwen backend

### Scripts Created

- `run_qwen_100.sh` - Script to run 100 SWE-bench instances with Qwen

### 100-Instance Benchmark Results (January 13-14, 2026)

**Run Command**:
```bash
./run_qwen_100.sh
# Or: python code_swe_agent.py --dataset_name princeton-nlp/SWE-bench_Verified --limit 100 --backend qwen
```

**Runtime**: ~3 hours 11 minutes (11,466 seconds)
**Average per instance**: 114.66 seconds (~1.9 minutes)

#### Generation Statistics

| Metric | Value |
|--------|-------|
| **Total Instances** | 100 |
| **Non-empty Patches** | 65 |
| **Empty Patches** | 35 |
| **Generation Rate** | **65.0%** |

#### Patch Size Distribution

| Metric | Value |
|--------|-------|
| Min Patch Size | 929 chars |
| Max Patch Size | 332,381 chars |
| **Average Patch Size** | **59,206 chars** |
| Median Patch Size | 46,955 chars |

#### Repos Processed

| Repository | Instances | Notes |
|------------|-----------|-------|
| Django | 78 | Web framework issues |
| Astropy | 22 | Scientific computing issues |

#### Observations

1. **High patch sizes** - Model outputs complete files rather than minimal diffs
   - This is expected with single-shot approach (no diff generation)
   - Actual functional changes may be small but full file replacement

2. **35% failure cases** - Empty patches due to:
   - Model outputting wrong file paths (file not found in repo)
   - Model providing analysis instead of code despite prompt
   - Regex extraction missing some output formats

3. **Successful extraction patterns**:
   - `<<<FILE: path>>>` marker worked well for most cases
   - Multiple fallback patterns helped catch variations

#### Sample Log Output (First Instance)
```
Processing astropy__astropy-12907
📄 Found 1 file change(s) in response
📝 Attempting to update: astropy/modeling/separable.py
✅ Updated: astropy/modeling/separable.py
Git status: M astropy/modeling/separable.py
Patch length: 15,057 characters
```

### Comparison: Claude Code vs Qwen Single-Shot

| Metric | Claude Code (EXP-001) | Qwen (EXP-007) |
|--------|----------------------|----------------|
| **Generation Rate** | 80% (8/10) | 65% (65/100) |
| **Avg Time/Instance** | ~5 min | ~1.9 min |
| **Avg Patch Size** | ~7K chars | ~59K chars |
| **Backend** | Claude API | Local Ollama |
| **Cost** | API costs | Free (local) |

### Next Steps

- [x] Run 100-instance benchmark with `./run_qwen_100.sh`
- [ ] Compare generation rate with Claude Code baseline ✅ Done above
- [ ] Run Docker evaluation to measure resolution rate
- [ ] Calculate regression rates
- [ ] Investigate empty patch cases to improve extraction

### Predictions Files

- Single test: `predictions/predictions_20260113_172511.jsonl`
- **100-instance run**: `predictions/predictions_20260113_192818.jsonl`
- Log file: `logs/qwen_run_20260113_192817.log`

### Status
✅ **COMPLETE** - 100-instance benchmark finished with 65% generation rate

**Key Achievement**: Local Qwen3-coder:30b via Ollama achieves competitive generation rate (65%) compared to Claude Code (80%) at zero API cost.

---

## EXP-008: TDD Prompt Engineering with Qwen

### Metadata
- **Date**: January 15, 2026
- **Configuration**: TDD-focused prompt engineering with Qwen
- **Model**: qwen3-coder:30b via Ollama
- **Dataset**: SWE-bench Verified
- **Sample Size**: 100 instances (planned)
- **Status**: ⏳ Ready to Run

### Hypothesis
Using TDD-focused prompts that instruct the model to output tests BEFORE implementation will:
1. Improve code quality by forcing test-first thinking
2. Generate patches that include test coverage
3. Potentially reduce regression rates (main thesis goal)

### Method

**Code Changes Made**:
1. Modified `utils/qwen_interface.py`:
   - Added `tdd_mode` parameter to `execute_code_cli()`
   - Created TDD-specific prompt that requests tests first, implementation second

2. Modified `code_swe_agent.py`:
   - Added `--tdd` argument
   - Passes `tdd_mode` to interface for qwen backend

**TDD Prompt Structure**:
```
STEP 1: WRITE TEST FIRST
- Output test file that reproduces the bug
- Test should FAIL before fix, PASS after

STEP 2: IMPLEMENT THE FIX
- Output implementation file(s)
- Make minimal changes to pass tests
```

**Run Command**:
```bash
cd /Users/rafaelalonso/Development/Master/Tesis/claudecode_n_codex_swebench

python code_swe_agent.py \
  --dataset_name princeton-nlp/SWE-bench_Verified \
  --limit 100 \
  --backend qwen \
  --tdd \
  2>&1 | tee logs/qwen_tdd_100.log
```

### Expected Outputs

Each patch should include:
1. **Test file(s)** - `tests/test_*.py`
2. **Implementation file(s)** - The actual bug fix

### Comparison Plan

| Metric | EXP-007 (Baseline) | EXP-008 (TDD) |
|--------|-------------------|---------------|
| Generation Rate | 65% | ? |
| Includes Tests | No | Yes (expected) |
| Resolution Rate | TBD | ? |
| Regression Rate | TBD | ? |

### Files Modified

| File | Changes |
|------|---------|
| `utils/qwen_interface.py` | Added `tdd_mode` parameter, TDD-specific prompt |
| `code_swe_agent.py` | Added `--tdd` argument, passes to interface |

### Results (January 15, 2026)

#### Generation Statistics

| Metric | EXP-007 (Baseline) | EXP-008 (TDD) | Delta |
|--------|-------------------|---------------|-------|
| **Generation Rate** | 65.0% (65/100) | 64.0% (64/100) | -1.0% |
| **Avg Patch Size** | 59,206 chars | 59,978 chars | +772 |
| **Patches with Tests** | 0 (0%) | 2 (3.1%) | +2 |
| **Multi-file Patches** | 12 (18.5%) | 10 (15.6%) | -2 |

#### Key Finding

**TDD prompt engineering had minimal impact on Qwen's output.**

The model largely ignored the "test first" instruction:
- Only **2 out of 64** patches included test files (3.1%)
- Generation rate slightly decreased (-1%)
- Patch sizes remained virtually identical

#### Patches with Test Files

Only 2 patches included test changes:
1. `django__django-11734` - includes `tests/queries/test_qs_combinators.py`
2. `django__django-11740` - includes `tests/migrations/test_autodetector.py`

### Analysis

The single-shot approach with prompt engineering alone is **insufficient** to enforce TDD methodology.

**Possible reasons:**
1. **Model training bias**: Qwen was likely trained primarily on implementation code, not test-first patterns
2. **Output format constraint**: Asking for complete files favors implementation over test files
3. **Context limitation**: Model may prioritize fixing the bug over following process instructions
4. **Prompt strength**: TDD instructions may need to be more forceful or structured differently

### Implications for Thesis

This result suggests that **prompt engineering alone cannot enforce TDD** in code generation models. Future approaches should consider:

1. **Two-stage generation**: First call generates only test, second call generates implementation
2. **Stronger enforcement**: Reject responses that don't start with test files
3. **Different models**: Try models specifically fine-tuned on test code
4. **RAG approach**: Use GraphRAG to inject existing test patterns as context (EXP-004)

### Predictions File
`predictions/predictions_20260115_005823.jsonl`

### Status
✅ **COMPLETE** - TDD prompt engineering showed minimal impact on test generation

---

## EXP-009: GraphRAG with Code-Test Relationship Indexing

### Metadata
- **Date**: January 15, 2026
- **Configuration**: GraphRAG-enhanced agent with iterative test-fix loop
- **Model**: Claude Code (default) / Qwen
- **Dataset**: SWE-bench Verified
- **Sample Size**: TBD

### Hypothesis

Prompt engineering alone (EXP-008) failed to enforce TDD. GraphRAG-based test impact analysis should provide a more robust approach by:

1. Building a code-test dependency graph (nodes: functions, classes, tests; edges: CALLS, TESTS, IMPORTS)
2. After the agent makes changes, query the graph for impacted tests
3. Run only the impacted tests (scalable regression testing)
4. If tests fail, iterate - give the agent failure details and have it fix regressions
5. Repeat until all impacted tests pass

This approach **enforces** regression checking rather than relying on prompt compliance.

### Method

```bash
cd /Users/rafaelalonso/Development/Master/Tesis/claudecode_n_codex_swebench

# Start Neo4j (required for GraphRAG)
# Option 1: Docker
docker run -d --name neo4j -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password neo4j:5

# Option 2: Embedded (configured in config.py)

# Run GraphRAG experiment
python code_swe_agent_graphrag.py \
  --dataset_name princeton-nlp/SWE-bench_Verified \
  --limit 10 \
  --backend claude \
  --use-graphrag \
  --impact-threshold 0.3 \
  --max-impacted-tests 50
```

### Implementation Changes (January 15, 2026)

**Fixed Critical Issues:**

1. **TESTS relationships never created** - Fixed in `graph_builder.py`:
   - Added `File → Test` CONTAINS relationship when creating test nodes

2. **Static analysis query broken** - Fixed in `test_linker.py`:
   - Rewrote `_link_by_static_analysis()` to properly trace `Test → Function → Function (CALLS)`

3. **IMPORTS relationships missing** - Fixed in `graph_builder.py`:
   - Added IMPORTS relationship creation in `_create_relationships()`

4. **No iterative test-fix loop** - Added in `code_swe_agent_graphrag.py`:
   - Added `_format_test_failures_for_agent()` helper method
   - Added iteration loop (max 3 iterations) to fix regressions

5. **MCP server initialization incomplete** - Fixed in `server.py`:
   - Added Neo4j connection verification at startup
   - Added proper cleanup on shutdown

| File | Changes |
|------|---------|
| `mcp_server/graph_builder.py` | Added File→Test CONTAINS, IMPORTS relationships |
| `mcp_server/test_linker.py` | Fixed static analysis query |
| `utils/mcp_graphrag_interface.py` | Added `run_impacted_tests_iteratively()` |
| `code_swe_agent_graphrag.py` | Added iteration loop, failure formatting |
| `mcp_server/server.py` | Fixed lifespan initialization |

### Graph Structure

```
Nodes:
  - File (path, name, content_hash)
  - Function (id, name, file_path, start_line, end_line)
  - Class (id, name, file_path)
  - Test (id, name, file_path, function_name)

Relationships:
  - CONTAINS: File → Function/Class/Test
  - CALLS: Function → Function
  - IMPORTS: File → File
  - TESTS: Test → Function/Class (created by TestLinker)
```

### Expected Workflow

1. **Graph Build** (~30-60s per repo):
   - Parse all Python files with AST
   - Create nodes for files, functions, classes, tests
   - Create CALLS, CONTAINS, IMPORTS relationships
   - TestLinker creates TESTS relationships

2. **Agent Fix** (~5 min):
   - Agent receives issue and attempts fix

3. **Impact Analysis** (~1-5s):
   - Get changed files from git diff
   - Query graph for impacted tests
   - Return tests sorted by impact score

4. **Iterative Test Loop** (max 3 iterations):
   - Run impacted tests
   - If failures, format details and send to agent
   - Agent fixes regressions
   - Repeat until all pass or max iterations

### Results (January 16-17, 2026)

**Status**: ✅ **COMPLETE** - 100 instances processed

#### Run Configuration
```bash
./run_exp009_test.sh
# Runs: python code_swe_agent_graphrag.py \
#   --dataset_name princeton-nlp/SWE-bench_Verified \
#   --limit 100 --backend qwen --tdd
```

**Predictions File**: `predictions/predictions_graphrag_20260116_215545.jsonl`

#### Generation Statistics

| Metric | EXP-007 (Baseline) | EXP-008 (TDD Prompt) | EXP-009 (GraphRAG) | Delta vs Baseline |
|--------|-------------------|---------------------|-------------------|-------------------|
| **Generation Rate** | 65.0% (65/100) | 64.0% (64/100) | **95.0% (95/100)** | **+30.0%** |
| **Patches with Tests** | 15 (23%) | 13 (20%) | **95 (100%)** | **+77%** |
| **Empty Patches** | 35 | 36 | 5 | -30 |
| **Avg Patch Size** | 59,206 chars | 59,978 chars | 17,738 chars | -70% (more focused) |

#### Patch Size Distribution (EXP-009)

| Metric | Value |
|--------|-------|
| Min | 768 chars |
| Max | 271,673 chars |
| Average | 17,738 chars |
| Median | 2,914 chars |

#### GraphRAG-Specific Metrics

| Metric | Value |
|--------|-------|
| **Graphs Built** | 100/100 (100%) |
| **Avg Graph Build Time** | 706.7s (~11.8 min) |
| **Min/Max Build Time** | 64s / 997s |
| **Avg Impacted Tests Found** | 24.1 tests |
| **Min/Max Impacted Tests** | 0 / 1,360 tests |
| **Avg Impact Analysis Time** | 0.06s |

#### Repositories Processed

| Repository | Instances |
|------------|-----------|
| Django | 78 |
| Astropy | 22 |

### Analysis

#### Key Achievements 🎉

1. **Generation Rate: 95%** - A 30 percentage point improvement over baseline (65%)
   - The TDD-enforced GraphRAG approach significantly improves patch generation
   - Only 5 empty patches out of 100 instances

2. **100% Test Coverage in Patches** - All 95 non-empty patches include test files
   - EXP-008 (prompt-only TDD) achieved only 3.1% test inclusion
   - GraphRAG + TDD mode **enforces** test-first behavior vs just suggesting it

3. **Smaller, More Focused Patches** - Average 17,738 chars vs 59,206 chars (baseline)
   - 70% reduction in patch size suggests more targeted fixes
   - Median of 2,914 chars indicates most patches are concise

4. **Graph Building Works at Scale** - All 100 repos indexed successfully
   - Build times vary (64s-997s) based on repo size
   - Impact analysis is fast (0.06s average) once graph is built

#### Technical Fixes That Enabled This (January 16-17, 2026)

1. **False Positive Prevention** (`mcp_graphrag_interface.py:586`)
   - Fixed: `all_passed = test_result.get("failed", 0) == 0`
   - Now checks both `success` AND `failed == 0`

2. **New File Creation in TDD Mode** (`qwen_interface.py:174-199`)
   - Added ability to create new test files (not just update existing)
   - Returns `created_files` list for patch extraction

3. **New Files in Patch** (`patch_extractor.py:22-67`)
   - Stages created files with `git add -N` before diff
   - Ensures new test files appear in generated patches

4. **Test Error Capture** (`test_linker.py:293-304`)
   - Added `error` field when pytest fails
   - Enables better feedback to agent for iteration

#### Comparison: Prompt Engineering vs Graph-Enforced TDD

| Approach | Generation Rate | Test Inclusion | Mechanism |
|----------|----------------|----------------|-----------|
| EXP-007: Baseline | 65% | 23% | No TDD |
| EXP-008: Prompt TDD | 64% | 20% | "Please write tests" |
| **EXP-009: GraphRAG TDD** | **95%** | **100%** | Enforced by system |

**Conclusion**: Prompt engineering alone cannot enforce TDD practices. The GraphRAG approach with system-level enforcement achieves dramatically better results.

### Limitations Observed

1. **Graph Build Time** - Large repos take 10-16 minutes to index
   - Django repos average ~11 minutes
   - Could be optimized with incremental indexing

2. **Impacted Test Variance** - Range of 0 to 1,360 tests found
   - Some changes affect many tests (1,360 for core Django changes)
   - May need smarter test prioritization for large impact sets

3. **Resolution Rate Unknown** - Need Docker evaluation to measure actual fix rate
   - Generation ≠ Resolution
   - Next step: Run SWE-bench evaluation harness

### Next Steps

- [ ] Run Docker evaluation on `predictions_graphrag_20260116_215545.jsonl`
- [ ] Calculate resolution rate (patches that actually fix issues)
- [ ] Calculate regression rate (patches that break existing tests)
- [ ] Compare resolution rates: EXP-007 vs EXP-008 vs EXP-009
- [ ] Analyze specific failure cases (5 empty patches)
- [ ] Consider graph caching to reduce build times

### Status
✅ **COMPLETE** - GraphRAG with TDD enforcement achieves 95% generation rate with 100% test inclusion

---

## EXP-007B: Qwen Baseline with Bug Fix (Rerun)

### Metadata
- **Date**: January 17, 2026
- **Configuration**: Qwen baseline (no TDD, no GraphRAG) with bug fixes applied
- **Model**: qwen3-coder:30b via Ollama
- **Dataset**: SWE-bench Verified
- **Sample Size**: 100 instances
- **Purpose**: Isolate the effect of bug fixes vs TDD/GraphRAG

### Hypothesis

Re-running EXP-007 baseline with the file creation bug fix should reveal the "true" baseline generation rate. This helps isolate whether EXP-009's 95% improvement came from:
1. Bug fixes (file creation, patch extraction)
2. TDD mode prompts
3. GraphRAG context

### Method

```bash
cd /Users/rafaelalonso/Development/Master/Tesis/claudecode_n_codex_swebench

python code_swe_agent.py \
  --dataset_name princeton-nlp/SWE-bench_Verified \
  --limit 100 \
  --backend qwen
```

**Key Differences from EXP-007:**
- File creation bug fixed (can now create new files)
- Stricter validation (rejects placeholder responses)
- `created_files` passed to patch extractor

### Results

#### Generation Statistics

| Metric | EXP-007 (Original) | EXP-007B (Fixed) | Delta |
|--------|-------------------|------------------|-------|
| **Generation Rate** | 65.0% (65/100) | **57.0% (57/100)** | -8% |
| **Empty Patches** | 35 | 43 | +8 |
| **Patches Creating New Files** | 0 | 5 | +5 |
| **Patches with Test Files** | 15 | 8 | -7 |

#### Patch Size Distribution

| Metric | EXP-007 | EXP-007B |
|--------|---------|----------|
| Min | - | 917 chars |
| Max | - | 186,710 chars |
| Average | 59,206 chars | 41,375 chars |
| Median | - | 21,396 chars |

### Analysis

#### Key Discovery: Original 65% Was Inflated

The original EXP-007 had **7 patches containing placeholder text** like:
- `"# The COMPLETE file content goes here"`
- `"# Include ALL imports"`

These were counted as "successful" patches but were actually garbage. The new validation rejects them.

**Math check**: 65 - 7 = 58 ≈ 57% (the new baseline)

#### Why EXP-007B is Lower (Not a Bug!)

| Factor | Effect |
|--------|--------|
| Placeholder rejection | -7 patches |
| Too-short response rejection | Minor |
| No-Python-code rejection | Minor |
| **Net effect** | ~8% "drop" in generation rate |

This is a **quality improvement**, not a regression. The original 65% included low-quality patches.

#### File Creation Bug Fix Working

- EXP-007: **0 new files created** (bug prevented it)
- EXP-007B: **5 new files created** (bug fixed!)

The fix works, but without TDD mode, Qwen doesn't naturally output test files.

### Comparison: All Qwen Experiments

| Experiment | Gen Rate | New Files | Test Files | Quality |
|------------|----------|-----------|------------|---------|
| EXP-007 (Original) | 65% | 0 | 15 | Inflated by 7 placeholder patches |
| EXP-007B (Fixed) | **57%** | 5 | 8 | True quality baseline |
| EXP-008 (TDD Prompt) | 64% | 0 | 13 | Prompt-only TDD didn't help |
| **EXP-009 (GraphRAG+TDD)** | **95%** | 93 | 95 | Full pipeline |

### Key Insight

**The 38% improvement from EXP-007B (57%) to EXP-009 (95%) comes from TDD mode + GraphRAG, NOT from bug fixes alone.**

| Component | Contribution |
|-----------|-------------|
| Bug fixes (file creation, validation) | Enables new file creation, improves quality |
| TDD mode prompts | Makes Qwen output test files first |
| GraphRAG context | Provides codebase understanding |
| **Combined effect** | +38% generation rate |

### Implications for Thesis

1. **Prompt engineering alone doesn't work** (EXP-008: 64% ≈ baseline)
2. **Bug fixes enable but don't drive improvement** (EXP-007B: 57% baseline)
3. **TDD + GraphRAG together are the key** (EXP-009: 95%)

The thesis hypothesis is supported: **System-level enforcement of TDD (via GraphRAG) is more effective than prompt-based suggestions.**

### Predictions File

`predictions/predictions_20260117_221000.jsonl`

### Status
✅ **COMPLETE** - Baseline with bug fix establishes true 57% quality baseline

---

## EXP-010: Docker Truth Validation and Repair Baseline (10 Submitted Instances)

### Metadata
- **Date**: February 15, 2026
- **Configuration**: Qwen-Mini single-pass with official Docker harness evaluation
- **Model**: qwen3-coder:30b via Ollama (`qwen-mini` backend)
- **Dataset**: SWE-bench Verified
- **Sample Size**: 500 total dataset, 10 submitted predictions
- **Purpose**: Validate true functional success rate with containerized evaluation and establish a concrete repair baseline

### Hypothesis

A real Docker SWE-bench evaluation on the submitted predictions will expose true code correctness (not just code generation), isolate failure classes, and provide a reliable baseline for repair.

### Method

```bash
cd /Users/rafaelalonso/Development/Master/Tesis/claudecode_n_codex_swebench

DOCKER_CONFIG=/tmp/docker-nocreds python3 evaluate_predictions.py \
  --file predictions_20260214_122836.jsonl \
  --dataset princeton-nlp/SWE-bench_Verified \
  --max-workers 2 \
  --force
```

### Results

#### Official Run Output

- **Run ID**: `eval_20260215_134052`
- **Report File**: `claudecode_n_codex_swebench/evaluation_results/qwen-mini.eval_20260215_134052.json`
- **Total Instances**: `500`
- **Submitted Instances**: `10`
- **Completed Instances**: `5`
- **Empty Patch Instances**: `5`
- **Resolved Instances**: `1`
- **Unresolved Instances**: `4`

#### Instance-Level Outcome

- **Resolved**: `astropy__astropy-14309`
- **Unresolved**:
  - `astropy__astropy-12907`
  - `astropy__astropy-13033`
  - `astropy__astropy-13236`
  - `astropy__astropy-14182`
- **Empty Patch**:
  - `astropy__astropy-13398`
  - `astropy__astropy-13453`
  - `astropy__astropy-13579`
  - `astropy__astropy-13977`
  - `astropy__astropy-14096`

### Analysis

#### Failure Modes by Unresolved Instance

- `astropy__astropy-12907`: modified `_cdot` operand handling and introduced regression (`PASS_TO_PASS` breakage).
- `astropy__astropy-13033`: patch focused on error-message formatting; target failing behavior remained unresolved.
- `astropy__astropy-13236`: produced duplicated warning blocks multiple times; non-targeted and noisy patch.
- `astropy__astropy-14182`: constructor/signature changes in RST path created baseline regressions.

#### Denominator Clarification

- **Full dataset view**: `1/500 = 0.2%`
- **Submitted batch view**: `1/10 = 10%`
- **Non-empty patch view**: `1/5 = 20%`

#### Architecture and Approach Changes Introduced

- Switched from reconstruction-style confidence to **official Docker harness truth validation**.
- Added Docker credential-helper bypass for reliability:
  - `DOCKER_CONFIG=/tmp/docker-nocreds`
- Used forced clean rerun to avoid stale result reuse:
  - `--force`
- Locked a stabilization run shape for repair:
  - Backend: `qwen-mini` single-pass
  - Scope: rerun same 10 submitted instances before scaling up

### Decisions and Next Actions

1. Regenerate patches for unresolved + empty-patch instances with stricter targeted-edit constraints.
2. Re-evaluate the repaired 10-instance batch with Docker harness.
3. Scale to larger sample only after improving resolved count and reducing regressions.

### Predictions File

`predictions_20260214_122836.jsonl`

### Status
🟡 **PARTIAL** - Infrastructure path is validated; patch quality is the current bottleneck

---
