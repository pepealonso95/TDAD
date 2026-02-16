## EXP-010-REPAIR: Quality Enforcement for Qwen-Mini Single-Pass

### Metadata
- **Date**: 2026-02-15
- **Configuration**: Qwen-Mini (mini-swe-agent) with three-layer quality enforcement
- **Model**: Qwen3-Coder:30B (Ollama local)
- **Sample Size**: 10 instances (9 regenerated + 1 kept from EXP-010)
- **Parent Experiment**: EXP-010 (baseline had 1/10 resolved, 10% resolution rate)

### Hypothesis
Adding quality enforcement layers to qwen-mini will improve patch quality and resolution rate while maintaining single-pass architecture parity with EXP-007.

**Three quality enforcement layers:**
1. **Enhanced Prompts**: Explicit quality requirements in INSTANCE_TEMPLATE
2. **Patch Validation**: Pre-submission quality checks (file count, signatures, repetition, placeholders)
3. **Quality Gate**: Automatic rejection of patches failing validation

### Method

#### Changes Made
Modified `utils/qwen_mini_interface.py`:

1. **Enhanced INSTANCE_TEMPLATE** (lines 54-76):
   - Minimal scope requirement
   - No public API changes
   - Test-first approach
   - Targeted fixes
   - No repetition
   - Self-check before submit

2. **Validation Method** (`_validate_patch_quality()`, lines 530-627):
   - Empty diff check
   - File count ≤3
   - Repetitive code detection (4+ identical lines)
   - Placeholder detection (TODO, FIXME)
   - Function signature change detection (as warning)

3. **Quality Gate** (`_extract_patch()`, lines 629-647):
   - Calls validation before accepting patch
   - Rejects patches failing validation (returns empty string)
   - Logs validation decision and metrics

#### Execution
```bash
# Single instance test (Phase 2)
python code_swe_agent.py \
  --dataset_name princeton-nlp/SWE-bench_Verified \
  --instance_id astropy__astropy-12907 \
  --backend qwen-mini

# Regenerate 9 failed instances (Phase 3)
./regenerate_failed_qwen_mini.sh

# Consolidate with 1 resolved instance (Phase 4)
./consolidate_predictions.sh

# Docker evaluation (Phase 5)
DOCKER_CONFIG=/tmp/docker-nocreds python3 evaluate_predictions.py \
  --file predictions/predictions_consolidated_YYYYMMDD_HHMMSS.jsonl \
  --dataset princeton-nlp/SWE-bench_Verified \
  --max-workers 2 \
  --force
```

### Results

#### Generation Metrics
- **Total predictions**: [TO_FILL]/10
- **Non-empty patches**: [TO_FILL]/[TO_FILL] ([TO_FILL]%)
- **Empty patches**: [TO_FILL]/[TO_FILL] ([TO_FILL]%)
- **Validation rejections**: [TO_FILL]
- **Validation warnings**: [TO_FILL]

#### Resolution Metrics (Docker Evaluation)
- **Resolved**: [TO_FILL]/10 ([TO_FILL]%)
- **Unresolved**: [TO_FILL]/10 ([TO_FILL]%)
- **PASS→FAIL regressions**: [TO_FILL]
- **FAIL→PASS fixes**: [TO_FILL]

#### Comparison with EXP-010 Baseline
| Metric | EXP-010 Baseline | EXP-010-REPAIR | Change |
|--------|------------------|----------------|---------|
| Generation Rate | 50% (5/10) | [TO_FILL]% | [TO_FILL] |
| Resolution Rate | 10% (1/10) | [TO_FILL]% | [TO_FILL] |
| Regressions | 4/10 (40%) | [TO_FILL]% | [TO_FILL] |

#### Failure Mode Coverage
| Original Failure | Detection Method | Result |
|-----------------|------------------|---------|
| astropy-12907 (removed swap) | Signature change detection | [TO_FILL] |
| astropy-13033 (wrong focus) | Prompt: "Test first" | [TO_FILL] |
| astropy-13236 (duplicates 6x) | Repetitive hunk check | [TO_FILL] |
| astropy-14182 (broke signature) | Signature change detection | [TO_FILL] |
| Empty patches (5) | Better format guidance | [TO_FILL] |

#### Quality Validation Statistics
- **Patches validated**: [TO_FILL]
- **Rejected - empty diff**: [TO_FILL]
- **Rejected - too many files**: [TO_FILL]
- **Rejected - repetitive code**: [TO_FILL]
- **Rejected - placeholders**: [TO_FILL]
- **Warned - signature change**: [TO_FILL]
- **Accepted - clean**: [TO_FILL]

### Analysis

#### What Worked
[TO_FILL after evaluation]

#### What Didn't Work
[TO_FILL after evaluation]

#### Key Findings
[TO_FILL after evaluation]

### Next Steps

**If Resolution Rate ≥30% (Success Criteria Met):**
- [ ] Scale to 100 instances (full EXP-010 size)
- [ ] Compare with EXP-009 GraphRAG (95% generation baseline)
- [ ] Test optional test validation layer
- [ ] Document quality enforcement best practices

**If Resolution Rate <30% (Below Success Criteria):**
- [ ] Analyze failure modes in detail
- [ ] Consider pivot to EXP-009 GraphRAG approach
- [ ] Acknowledge single-pass limitations
- [ ] Plan multi-pass architecture for EXP-011

### Predictions File
`predictions/predictions_consolidated_YYYYMMDD_HHMMSS.jsonl`

### Evaluation Results
`evaluation_results/qwen-mini.eval_YYYYMMDD_HHMMSS.json`

### Status
🟡 **IN PROGRESS** - Regeneration running, evaluation pending

---
