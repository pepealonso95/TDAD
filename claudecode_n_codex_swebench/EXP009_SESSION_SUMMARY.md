# Session Summary: EXP-006 through EXP-009

## Overview

This document summarizes experiments 006-009 for the TDAD Thesis (Test-Driven AI Development), covering the evolution from agent-based approaches to single-shot and GraphRAG implementations.

---

## EXP-006: QwenAgent Native Function Calling

**Date**: January 13, 2026
**Status**: ✅ Complete

### Goal
Implement native function calling support in QwenAgent to enable reliable tool execution.

### Changes Made
- Added `_get_tool_definitions()` for native function calling in Ollama API
- Changed system role handling (`"user"` → `"system"`)
- Increased context limits (2K→8K for results, 4K→12K for total)
- Added `thinking` field handling
- Improved completion markers

### Results
- ✅ Native function calling works reliably for simple tasks
- ⚠️ SWE-bench instances hit 500 errors at ~28K context (memory limit)

### Key Insight
Agent loop approach is fragile with large codebases - context accumulates quickly.

---

## EXP-007: Qwen Single-Shot Approach

**Date**: January 13, 2026
**Status**: ✅ Complete

### Goal
Simplify approach by using single API call with explicit output format (matching Claude Code pattern).

### Changes Made
Complete rewrite of `utils/qwen_interface.py`:
- One API call instead of multi-turn agent loop
- `<<<FILE: path>>>` output format markers
- Multiple fallback regex patterns
- 256K context window, 0.1 temperature

### Results
| Metric | Value |
|--------|-------|
| Generation Rate | **65%** (65/100) |
| Avg Patch Size | 59,206 chars |
| Avg Time/Instance | ~1.9 min |

### Key Insight
Single-shot is simpler and more reliable than agent loops for code generation.

---

## EXP-008: TDD Prompt Engineering with Qwen

**Date**: January 15, 2026
**Status**: ✅ Complete

### Goal
Use TDD-focused prompts to enforce "test first, implementation second" pattern.

### Changes Made
- Added `tdd_mode` parameter to `execute_code_cli()`
- Created TDD-specific prompt requesting tests before implementation
- Added `--tdd` CLI argument

### Results
| Metric | EXP-007 (Baseline) | EXP-008 (TDD) |
|--------|-------------------|---------------|
| Generation Rate | 65.0% | **64.0%** |
| Patches with Tests | 0% | **3.1%** |

### Key Insight
**Prompt engineering alone cannot enforce TDD** - Qwen largely ignored "test first" instructions. Need stronger enforcement via architecture (e.g., GraphRAG).

---

## EXP-009: GraphRAG with Code-Test Relationship Indexing

**Date**: January 15-16, 2026
**Status**: 🔄 In Progress (Debugging)

### Goal
Implement GraphRAG-based test impact analysis to enforce regression testing:
1. Index codebase as a graph with tests as nodes
2. Query graph to find tests related to changed code
3. Run only impacted tests (scalable)
4. Iterate to fix regressions

### Issues Found and Fixed

#### Issue 1: Qwen `matches` Variable Undefined ✅ FIXED
- **File**: `utils/qwen_interface.py`
- Pattern 1 was missing, causing undefined `matches`

#### Issue 2: Extra Files in Patch ✅ FIXED
- **File**: `utils/patch_extractor.py`
- Removed `git add -N .` that was adding untracked files

#### Issue 3: Graph Build Timeout (10 min) ✅ FIXED
- **File**: `utils/mcp_graphrag_interface.py`
- Increased timeout: 600s → 1800s (30 min)
- Added graph caching by repo+commit hash

#### Issue 4: Qwen Placeholder Responses ✅ FIXED
- **File**: `utils/qwen_interface.py`
- Added content validation to reject:
  - Placeholder text ("# The COMPLETE file content goes here")
  - Too-short responses (<50 chars)
  - Non-Python content

#### Issue 5: Pattern Matching Inconsistency ✅ FIXED
- **File**: `utils/qwen_interface.py`
- Added CRLF normalization (`\r\n` → `\n`)
- Strip Qwen3 thinking blocks (`<think>...</think>`)
- Made patterns more flexible with `\s*`
- Added duplicate file detection

#### Issue 6: TDD Mode Not Enabled in GraphRAG Agent ✅ FIXED
- **Files**: `code_swe_agent_graphrag.py`, `claude_interface.py`, `codex_interface.py`
- Added `tdd_mode` parameter
- Added `--tdd` CLI flag

#### Issue 7: Impact Analyzer Returns 0 Tests for Changed Test Files (Not Fixed)
- User decided this is acceptable for current experiment
- **Optional future fix**: Add 5th strategy to find tests IN changed files

### Files Modified

| File | Changes |
|------|---------|
| `utils/qwen_interface.py` | Pattern fixes, content validation, CRLF handling, thinking blocks |
| `utils/patch_extractor.py` | Removed `git add -N .` |
| `utils/mcp_graphrag_interface.py` | 30-min timeout, graph caching |
| `code_swe_agent_graphrag.py` | Added `tdd_mode` parameter and `--tdd` flag |
| `utils/claude_interface.py` | Added `tdd_mode` parameter (ignored) |
| `utils/codex_interface.py` | Added `tdd_mode` parameter (ignored) |

### Test Run Results (10 instances)
- 5/10 instances processed before timeout
- Graph builds: 4 successful, 1 timeout (different commit cache miss)
- Content validation correctly rejected placeholder responses
- TDD Mode was `False` (now fixed)

---

## Commands to Run

### Without TDD Mode
```bash
cd /Users/rafaelalonso/Development/Master/Tesis/claudecode_n_codex_swebench
python code_swe_agent_graphrag.py --dataset_name princeton-nlp/SWE-bench_Verified --limit 10 --backend qwen
```

### With TDD Mode (Recommended)
```bash
cd /Users/rafaelalonso/Development/Master/Tesis/claudecode_n_codex_swebench
python code_swe_agent_graphrag.py --dataset_name princeton-nlp/SWE-bench_Verified --limit 10 --backend qwen --tdd
```

---

## Comparison Matrix

| Experiment | Approach | Generation Rate | Key Finding |
|------------|----------|-----------------|-------------|
| EXP-006 | Agent loop | N/A (500 errors) | Too much context accumulation |
| EXP-007 | Single-shot | **65%** | Simple is better |
| EXP-008 | TDD prompts | 64% | Prompts can't enforce TDD |
| EXP-009 | GraphRAG | TBD | Enforces regression testing via architecture |

---

## Key Insights for Thesis

1. **Single-shot > Agent loops** for code generation (simpler, more reliable)
2. **Prompt engineering alone is insufficient** to enforce TDD methodology
3. **Architectural enforcement** (GraphRAG) is needed for reliable regression testing
4. **Large repos need special handling** (caching, increased timeouts)
5. **Content validation critical** to filter garbage responses

---

## Next Steps

1. Run full EXP-009 with `--tdd` flag enabled
2. Evaluate results with SWE-bench Docker harness
3. Compare regression rates against baseline (EXP-007)
4. Document findings in thesis

---

## Plan File Location

Detailed plan with all issues and implementation: `/Users/rafaelalonso/.claude/plans/shimmering-imagining-cascade.md`
