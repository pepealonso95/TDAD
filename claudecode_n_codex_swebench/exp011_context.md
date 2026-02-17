# EXP-011 Context — Resume Document

## What This File Is
This is a conversation context summary for resuming work after EXP-011. Created Feb 15, 2026, updated Feb 16, 2026 with final results.

---

## Session Summary (Feb 15, 2026)

### What Was Done This Session

#### 1. EXP-010-REPAIR: Quality Enforcement (COMPLETED — FAILED)

Ran the EXP-010-REPAIR experiment to test if quality validation gates on qwen-mini patches would improve resolution rate from the 1/10 (10%) baseline.

**Three quality enforcement layers** were already implemented in `utils/qwen_mini_interface.py`:
- Enhanced INSTANCE_TEMPLATE (lines 54-76) with 6 quality requirements
- `_validate_patch_quality()` method (lines 530-627) — checks: empty diff, file count ≤3, repetitive code (4+ identical lines), placeholder detection, signature change detection
- Quality gate in `_extract_patch()` (lines 629-647) — calls validation, rejects failures

**Steps completed:**
1. Verified validation code already existed (no code changes needed)
2. Single instance test (astropy-12907) — passed, 372 chars, 89.2s
3. Batch regeneration of 9 failed instances via `./regenerate_failed_qwen_mini.sh`
4. Consolidation via `./consolidate_predictions.sh` → 10 predictions total
5. Docker evaluation completed

**EXP-010-REPAIR Results:**
- **Resolution: 1/10 (10%)** — identical to baseline, NO improvement
- **Resolved**: astropy-14309 (same instance as baseline)
- **Unresolved**: astropy-13033, astropy-14182, astropy-13579
- **Empty patches**: 6/10 (60%)
- **Non-empty patches**: 4/10 (40%)
- Evaluation file: `evaluation_results/qwen-mini.eval_20260215_223735.json`
- Predictions file: `predictions/predictions_consolidated_20260215_201134.jsonl`

**Key findings:**
- Validation gates correctly caught bad patches (repetitive code in astropy-13236, empty diffs)
- But the model (qwen3-coder:30b) isn't generating correct fixes
- Nondeterminism: same instance produced different results across runs
- Quality enforcement prevents regressions but doesn't improve resolution

**Conclusion**: Per the plan's "If This Fails" criteria, pivoting away from single-pass quality enforcement approach.

#### 2. Created `run_benchmark.py` Multi-Variant Benchmark Runner

Built a new orchestration script (~600 lines) that:
- Runs SWE-bench instances across qwen-mini variants (baseline, TDD, GraphRAG)
- Logs progress per-instance with timing
- Auto-runs Docker evaluation after generation
- Generates comparison reports (Markdown + JSON)

**CLI interface:**
```bash
python run_benchmark.py \
  --dataset princeton-nlp/SWE-bench_Verified \
  --limit 100 \
  --variants baseline tdd graphrag \
  --max-workers 2 \
  --run-name "exp011_100_baseline"
```

**Key files:**
- Script: `claudecode_n_codex_swebench/run_benchmark.py`
- Plan: `~/.claude/plans/cryptic-snuggling-manatee.md`

**Bug fixed in `evaluate_predictions.py`:**
- The `--file` flag only worked for files matching `predictions_YYYYMMDD_HHMMSS.jsonl` regex pattern
- Added fallback: if file exists but isn't in the pattern-matched list, add it directly with basic metadata (around line 372-386)

#### 3. EXP-011 (COMPLETED)

**Command:**
```bash
cd /Users/rafaelalonso/Development/Master/Tesis/claudecode_n_codex_swebench
DOCKER_CONFIG=/tmp/docker-nocreds /opt/homebrew/Caskroom/miniconda/base/bin/python run_benchmark.py \
  --dataset princeton-nlp/SWE-bench_Verified \
  --limit 100 \
  --variants baseline \
  --max-workers 2 \
  --run-name "exp011_100_baseline"
```

**Background task ID**: `bdb572e`
**Output file**: `/private/tmp/claude-501/-Users-rafaelalonso-Development-Master-Tesis/tasks/bdb572e.output`

**Run directory**: `benchmark_runs/20260215_234439_exp011_100_baseline/`
```
benchmark_runs/20260215_234439_exp011_100_baseline/
├── config.json
├── progress.log          ← check this for status
├── predictions/
│   └── baseline.jsonl    ← predictions accumulate here
├── evaluations/          ← filled after generation completes
├── report.md             ← generated at end
└── report.json           ← generated at end
```

**FINAL RESULTS (completed Feb 16 ~12:32 PM):**

| Metric | Value |
|--------|-------|
| **Generation rate** | 42/100 (42%) |
| **Resolution rate** | **9/100 (9%)** |
| **Resolution among generated** | 9/42 (21%) |
| **Total time** | 752 min (12.5 hours) |
| **Avg per instance** | 7.5 min |

**9 Resolved Instances:**
1. astropy__astropy-14539 (532 chars)
2. django__django-10914 (625 chars)
3. django__django-10973 (2584 chars)
4. django__django-11066 (767 chars)
5. django__django-11163 (971 chars)
6. django__django-12050 (500 chars)
7. django__django-12143 (715 chars)
8. django__django-12419 (453 chars)
9. django__django-12663 (545 chars)

**Key finding**: 9% resolution at n=100 confirms the ~10% rate from n=10 experiments. This is the established qwen-mini baseline.

---

## Important Technical Notes

### Python Environment
- **DO NOT use system python3** (`/Library/Developer/CommandLineTools/.../python3`) — missing `jsonlines` and `swebench`
- **USE conda python**: `/opt/homebrew/Caskroom/miniconda/base/bin/python`
- `conda activate py313` doesn't work in Claude Code shell — use full path instead
- `DOCKER_CONFIG=/tmp/docker-nocreds` must be set to avoid Docker credential deadlocks

### Key Files Modified This Session
| File | Change |
|------|--------|
| `evaluate_predictions.py` | Fixed `--file` flag to work with non-standard filenames |
| `run_benchmark.py` | NEW — multi-variant benchmark runner |
| `consolidate_predictions.sh` | NEW — merges repaired + resolved predictions |
| `check_progress.sh` | NEW — quick regeneration status check |
| `exp010_repair_template.md` | NEW — EXPERIMENTS.md entry template |

### Key Files NOT Modified
| File | Notes |
|------|-------|
| `utils/qwen_mini_interface.py` | All validation code was already present |
| `code_swe_agent.py` | Imported by run_benchmark.py, not changed |
| `code_swe_agent_graphrag.py` | Available for GraphRAG variant, not changed |
| `EXPERIMENTS.md` | **NEEDS UPDATE** with EXP-010-REPAIR and EXP-011 entries |

### User's CLAUDE.md Rules
- **Never git add, commit, or push** — user handles git manually
- **Every session must log to EXPERIMENTS.md** — not yet done for this session
- Use experiment ID format EXP-XXX
- Follow the template in EXPERIMENTS.md

---

## When Resuming: What to Do Next

### EXPERIMENTS.md is up to date
Both EXP-010-REPAIR and EXP-011 have been logged in EXPERIMENTS.md.

### Next Experiments to Run
1. **EXP-012: TDD variant** — `python run_benchmark.py --limit 100 --variants baseline tdd --run-name "exp012_tdd"`
2. **EXP-013: GraphRAG variant** — `python run_benchmark.py --limit 100 --variants baseline graphrag --run-name "exp013_graphrag"`
3. **Consider Claude backend** — for higher resolution rate comparison
4. **Analyze regression rate** — extract PASS→FAIL counts from `evaluations/baseline.eval.json`

### Run commands (use correct Python)
```bash
cd /Users/rafaelalonso/Development/Master/Tesis/claudecode_n_codex_swebench
DOCKER_CONFIG=/tmp/docker-nocreds /opt/homebrew/Caskroom/miniconda/base/bin/python \
  run_benchmark.py \
  --dataset princeton-nlp/SWE-bench_Verified \
  --limit 100 \
  --variants baseline tdd \
  --max-workers 2 \
  --run-name "exp012_tdd_comparison"
```

---

## Experiment History Summary

| Experiment | Config | Sample | Gen Rate | Res Rate | Status |
|-----------|--------|--------|----------|----------|--------|
| EXP-010 | qwen-mini baseline | 10 | 50% | 10% (1/10) | Done |
| EXP-010-REPAIR | qwen-mini + validation | 10 | 40% | 10% (1/10) | Done |
| EXP-011 | qwen-mini baseline | 100 | TBD | TBD | **RUNNING** |

---

## File Locations Quick Reference

```
/Users/rafaelalonso/Development/Master/Tesis/
├── EXPERIMENTS.md                    ← needs updating
├── codex plan.md                     ← has execution log for EXP-010-REPAIR
└── claudecode_n_codex_swebench/
    ├── run_benchmark.py              ← new benchmark runner
    ├── code_swe_agent.py             ← main agent (CodeSWEAgent)
    ├── code_swe_agent_graphrag.py    ← GraphRAG agent
    ├── evaluate_predictions.py       ← fixed --file flag
    ├── utils/
    │   └── qwen_mini_interface.py    ← has validation gates
    ├── predictions/
    │   └── predictions_consolidated_20260215_201134.jsonl  ← EXP-010-REPAIR
    ├── evaluation_results/
    │   └── qwen-mini.eval_20260215_223735.json            ← EXP-010-REPAIR eval
    └── benchmark_runs/
        └── 20260215_234439_exp011_100_baseline/           ← EXP-011 (running)
            ├── progress.log
            ├── predictions/baseline.jsonl
            └── ...
```
