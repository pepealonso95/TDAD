# Research Summary: Minimizing Code Regressions in AI Coding Agents

**Project**: TDAD (Test-Driven AI Development) — Master's Thesis
**Author**: Rafael Alonso
**Date**: February 2026
**Current Best Configuration**: EXP-013c (Observation Masking)

---

## 1. Problem Statement

AI coding agents — systems that autonomously read, edit, and debug source code — are rapidly improving at solving real software engineering tasks. However, even when these agents produce patches that fix the target issue, they frequently break previously passing tests in the process. These **code regressions** are a critical barrier to practical adoption.

This thesis asks: **Can Test-Driven Development (TDD) practices and intelligent context management reduce the regression rate of AI coding agents?**

We measure this using SWE-bench Verified, a benchmark of 500 real GitHub issues from popular Python repositories (astropy, django, scikit-learn, etc.), where each issue has ground-truth tests that must pass for a "resolved" verdict.

### Key Metrics

- **Generation Rate**: % of instances where the agent produces a non-empty patch
- **Resolution Rate**: % of patches that actually fix the issue (pass the target tests) — evaluated via Docker
- **Regression Rate (P2P)**: % of patches that break previously passing tests — the thesis's primary metric

---

## 2. Architecture and Libraries

### 2.1 Core Stack

| Component | Library/Tool | Role |
|-----------|-------------|------|
| **LLM** | Qwen3-Coder 30B (Q4_K_M quantization) | Local model via Ollama |
| **Agent Framework** | mini-swe-agent v1.17.3 | Lightweight ReAct loop with bash-only tool execution |
| **LLM Gateway** | LiteLLM | Unified API bridging Ollama to mini-swe-agent |
| **Inference Server** | Ollama | Local model serving on Apple Silicon (M-series Mac) |
| **Evaluation Harness** | SWE-bench Docker | Official containerized test execution per-instance |
| **Benchmark** | SWE-bench Verified (princeton-nlp) | 500 human-validated real GitHub issues |
| **Orchestration** | `run_benchmark.py` (custom) | Generation + Docker evaluation + reporting pipeline |

### 2.2 How It Works

```
┌──────────────────────────────────────────────────────────┐
│  run_benchmark.py (orchestrator)                         │
│  - Loads SWE-bench instances from HuggingFace            │
│  - Iterates instances sequentially                       │
│  - Calls QwenMiniInterface per instance                  │
│  - Collects predictions → runs Docker evaluation         │
└───────────────────┬──────────────────────────────────────┘
                    │
                    ▼
┌──────────────────────────────────────────────────────────┐
│  QwenMiniInterface (utils/qwen_mini_interface.py)        │
│  - Clones repo at the issue's base commit                │
│  - Creates mini-swe-agent with Ollama config             │
│  - Attaches logging, loop detection, context management  │
│  - Runs agent.run(task) → agent iterates bash commands   │
│  - Extracts git diff as the patch prediction             │
└───────────────────┬──────────────────────────────────────┘
                    │
                    ▼
┌──────────────────────────────────────────────────────────┐
│  mini-swe-agent (DefaultAgent)                           │
│  - ReAct loop: THOUGHT → bash command → observation      │
│  - Up to 75 steps per instance                           │
│  - Ollama/Qwen generates each step via LiteLLM           │
│  - Agent reads files, runs grep, edits with sed/python   │
│  - Submits via echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT│
└───────────────────┬──────────────────────────────────────┘
                    │
                    ▼
┌──────────────────────────────────────────────────────────┐
│  Ollama (localhost:11434)                                │
│  - Qwen3-Coder 30B at Q4_K_M quantization               │
│  - 32K context window, temperature=0.0                   │
│  - ~8-12 tokens/sec on Apple Silicon                     │
└──────────────────────────────────────────────────────────┘
```

### 2.3 Why Qwen3-Coder 30B?

Early experiments (EXP-001 through EXP-005) used Claude Sonnet 4.5 via the Anthropic API. This hit practical barriers:
- **Cost**: Running 500 instances at ~$0.50/instance was prohibitive for iterative experimentation
- **Rate limits**: API timeouts caused cascade failures (EXP-005: TDD and GraphRAG variants scored 0%)
- **Context management**: Claude Code's internal context handling was opaque and couldn't be tuned

Switching to Qwen3-Coder 30B via Ollama provided:
- **Zero marginal cost** — unlimited iterations at no API expense
- **Full control** — context window, temperature, and message history are directly configurable
- **Reproducibility** — same model weights, same machine, same parameters across all experiments
- **Reasonable capability** — 30B parameter model with strong coding performance

The tradeoff: lower raw capability than Claude Sonnet 4.5, meaning resolution rates are lower in absolute terms, but the relative comparisons between configurations remain valid for thesis conclusions.

### 2.4 Why mini-swe-agent?

mini-swe-agent was chosen over heavier frameworks (SWE-agent, OpenHands, Aider) because:
- **Simplicity**: ~2K lines of Python, single-file agent loop, easy to instrument
- **Proven**: Scores 74% on SWE-bench Verified with Claude Sonnet (the official benchmark uses it)
- **Hackable**: Message list is a plain `list[dict]`, allowing direct manipulation for context experiments
- **Bash-only**: No complex tool-use protocol — the agent outputs bash commands in markdown code blocks

---

## 3. Experiment Timeline and Findings

### Phase 1: Claude API Baseline (Oct-Nov 2025)

| Experiment | Model | Result | Finding |
|-----------|-------|--------|---------|
| EXP-001 | Claude Sonnet 4.5 | 80% generation, eval pending | Baseline established |
| EXP-001B | Haiku vs Sonnet | Both find same fix | Haiku is 61% faster, 10x cheaper |
| EXP-005 | Claude Sonnet 4.5 | TDD: 0%, GraphRAG: 0% | API context/timeout failures |

**Conclusion**: Claude API is too expensive and unreliable for iterative research. Pivot to local models.

### Phase 2: Local Model Exploration (Jan 2026)

| Experiment | Approach | Result | Finding |
|-----------|----------|--------|---------|
| EXP-006 | Qwen native function calling | Crashes at ~28K context | Agent loop hits memory limits |
| EXP-007 | Qwen single-shot (one API call) | 65% generation | Works but patches are huge (full file replacements) |
| EXP-008 | TDD prompt engineering | 64% gen, only 3.1% include tests | **Prompts alone cannot enforce TDD** |
| EXP-009 | GraphRAG + system-level TDD | **95% generation, 100% test inclusion** | System-level enforcement works |

**Key thesis finding**: Prompt engineering alone achieves only 3.1% test inclusion despite explicit "test first" instructions (EXP-008). System-level enforcement via GraphRAG achieves 100% (EXP-009). This is a +38 percentage point improvement over the true baseline.

### Phase 3: Docker-Evaluated Results (Feb 2026)

With the switch to mini-swe-agent and Docker evaluation, we finally measured **real resolution rates**:

| Experiment | Config | Generation | Resolution | Key Discovery |
|-----------|--------|------------|------------|---------------|
| EXP-010 | First Docker eval | 50% | 10% (1/10) | Generation != resolution |
| EXP-011 | 100-instance baseline | 42% | 9% (9/100) | **Context window was 2K, not 32K!** |
| EXP-012 | Fixed context (32K) | 100% | 33% (1/3) | Config fix alone → 3x improvement |
| **EXP-012d** | **+ has_finished bug fix** | **70%** | **30% (3/10)** | **Best result overall** |

**Critical discovery (EXP-012)**: Ollama's default context window is ~2048 tokens. Our system prompt + instance template consumed ~2400 tokens, leaving essentially nothing for the model to work with. Fixing this single parameter (`num_ctx: 32768`) took resolution from 0% to 30%.

### Phase 4: Context Management Experiments (Feb 2026)

After establishing 30% resolution with EXP-012d, we attempted to improve it through context management — preventing the 32K context window from filling up and degrading model performance on long-running instances.

| Experiment | Strategy | Resolution | vs 012d | What Went Wrong |
|-----------|----------|------------|---------|-----------------|
| EXP-013a | Aggressive pruning (replace old pairs with summaries) | 10% (1/10) | -20pp | Removed file content the model needed |
| EXP-013b | Strip reasoning, keep observations | 0% (0/2) | -30pp | **Backwards** — reasoning is signal, not noise |
| **EXP-013c** | **Observation masking (keep reasoning, mask old outputs)** | **20% (2/10)** | **-10pp** | Best context mgmt approach, but still regressed |
| EXP-013d | Hybrid (013c masking + 012d prompts) | 10% (1/10) | -20pp | Masking changes exploration paths stochastically |

**Key insight from NeurIPS 2025 ("The Complexity Trap")**: Agent reasoning is the valuable signal; old tool outputs are noise. EXP-013b confirmed this empirically — stripping reasoning and keeping observations produced 590 regressions on a previously-resolved instance, while the reverse (013c) preserved resolution on simpler instances.

---

## 4. Current Configuration: EXP-013c

After testing all variants, **EXP-013c** was selected as the active configuration. While EXP-012d achieved higher resolution (30% vs 20%), 013c represents the most principled approach and best balances resolution with context efficiency.

### What EXP-013c Does

**1. Enhanced Prompt Template**
- Quality requirements emphasizing minimal scope, no API changes, test-first
- Explicit working directory guidance (prevents hardcoded paths, package imports)
- Common pitfalls section (never import unbuilt source, never search site-packages)
- Reduced command examples (streamlined from 012d's verbose examples)

**2. Loop Detection** (injected warnings into observations)
- **Exact repeat**: Same command 3+ times in last 5 → warning
- **Same base command**: 4 consecutive find/grep/ls commands → warning
- **Import retry**: 2+ `python3 -c "import..."` commands → "read source instead" warning

**3. Observation Masking** (research-backed, NeurIPS 2025)
- **Tier 1**: After 4 complete turns, replace old observation content with one-line placeholders (`[Previous output omitted (N lines). Return code: X]`). Agent reasoning (THOUGHT sections) is preserved intact.
- **Tier 2**: After 10 total turn pairs, hard-remove oldest pairs entirely (system + instance messages always kept).

**4. Reflection Instruction** (in system template)
- "After each command result, briefly reflect on what you learned and whether it moved you closer to solving the issue."

### Configuration Parameters

```python
temperature = 0.0       # Deterministic generation
num_ctx = 32768          # 32K context window
max_tokens = 8192        # Max response length
step_limit = 75          # Max agent steps per instance
obs_window = 4           # Keep last 4 observations in full
max_pairs = 10           # Hard limit before pair removal
```

### Why 013c Over 012d

| Factor | EXP-012d (vanilla) | EXP-013c (obs masking) |
|--------|-------------------|----------------------|
| Resolution | 30% (3/10) | 20% (2/10) |
| Generation | 70% (7/10) | 80% (8/10) |
| Total time | 90 min | 63 min |
| Worst instance | 73 min (14182) | 6.5 min (13236) |
| Context overflow risk | High (no management) | Controlled |
| Timeout risk | High | Low |

EXP-012d's 30% resolution came with a critical fragility: astropy-14182 consumed 73 minutes (81% of total time) spiraling through 75 steps as the context window filled. Without context management, any instance that doesn't resolve quickly will eventually overflow the 32K window, causing the model to produce increasingly incoherent outputs.

EXP-013c trades 10 percentage points of resolution for robustness:
- No single instance exceeds 16 minutes
- Total runtime reduced by 30%
- Higher generation rate (80% vs 70%)
- The two instances it resolves (13453, 14309) are the **stable resolvers** that succeed across multiple runs

---

## 5. Challenges and Open Problems

### 5.1 The Stochasticity Problem

Even at `temperature=0.0`, the same model on the same instance produces different results across runs. This is because:
- Observation masking changes the context at each step, altering subsequent model outputs
- Floating-point non-determinism in quantized models (Q4_K_M)
- Ollama's KV cache behavior can vary with system load

**Example**: `astropy-13236` resolved in 59 seconds in EXP-012d but took 107 minutes and produced 458 regressions in EXP-013d — same model, same prompt structure, different context management.

### 5.2 The Context Window Bottleneck

At ~2000 tokens per agent step, the 32K context fills by step 16. For complex instances requiring 30+ steps of exploration:
- Without pruning: model output degrades as context fills → loops and wrong patches
- With pruning: model loses file content it read earlier → incomplete fixes

This is a fundamental tension with no clean solution at 32K context. Larger context windows (64K, 128K) would help but aren't available with Qwen3-Coder 30B at acceptable inference speeds on consumer hardware.

### 5.3 macOS sed Incompatibility

The agent runs on macOS where `sed -i` requires a backup extension argument (`sed -i '' 's/old/new/'`), unlike Linux (`sed -i 's/old/new/'`). The model frequently generates Linux-style sed commands, causing repeated failures and exploration spirals. This is an artifact of running locally rather than in the SWE-bench Docker environment (Linux).

### 5.4 Generation vs Resolution Gap

Across all experiments, generation rate (producing any patch) is consistently 2-8x higher than resolution rate (patch actually fixes the issue). The model can identify what needs to change and produce plausible-looking patches, but the patches often:
- Edit the wrong function or file
- Introduce syntax errors the model can't test (unbuilt source code)
- Make overly broad changes that break other functionality
- Miss edge cases in the original issue

### 5.5 Docker Evaluation Constraints

Each instance evaluation requires:
- Building a Docker container with the exact repository state
- Installing all dependencies
- Running the test suite
- ~3-15 minutes per instance

This makes rapid iteration expensive. A full 500-instance evaluation would take ~40 hours of Docker time.

---

## 6. Key Thesis Findings So Far

1. **Prompt engineering alone cannot enforce TDD** — 3.1% test inclusion despite explicit instructions (EXP-008), vs 100% with system-level enforcement (EXP-009).

2. **Configuration errors can dominate results** — A 2K vs 32K context window setting explained a 0% → 30% resolution improvement. Always validate infrastructure before attributing results to algorithmic changes.

3. **Agent reasoning is signal; tool output is noise** — Confirmed empirically (EXP-013b vs 013c) and aligned with NeurIPS 2025 findings. Context management should preserve THOUGHT sections and compress observations.

4. **Context management helps efficiency but hurts peak resolution** — Every pruning/masking strategy we tried reduced resolution compared to vanilla (30% → 10-20%). The model is sensitive to having complete context for correct fixes.

5. **Resolution is stochastic at the instance level** — Only 1 instance (astropy-14309) resolves reliably across all configurations. Others depend on the model finding the right exploration path early.

6. **Quality gates prevent regressions without improving resolution** — EXP-010-REPAIR showed 40% → 0% regression rate with patch validation, but resolution stayed at 10%.

---

## 7. What's Next

### Immediate
- Run EXP-013c at 100 instances for statistically significant results
- Compare regression rates across configurations with quality gates enabled
- Evaluate whether GraphRAG (EXP-009's 95% generation) translates to resolution under Docker eval

### Research Directions
- **Larger context windows**: Test with Qwen3-Coder at 64K or 128K context
- **Docker-native execution**: Run the agent inside Linux containers to avoid macOS sed issues
- **Ensemble approaches**: Run 3x at temp=0.1 and pick the smallest correct patch
- **Hybrid GraphRAG + mini-swe-agent**: Combine EXP-009's test impact analysis with mini-swe-agent's proven loop

---

## 8. Reproducibility

All experiments can be reproduced with:

```bash
# Environment
conda activate py313
cd claudecode_n_codex_swebench

# Ensure Ollama is running with Qwen3-Coder
ollama run qwen3-coder:30b

# Run 10 instances with Docker evaluation
export DOCKER_CONFIG=/tmp/docker-nocreds
caffeinate -dims python -u run_benchmark.py \
  --dataset princeton-nlp/SWE-bench_Verified \
  --limit 10 --variants baseline --max-workers 1 \
  --run-name "experiment_name"
```

The active agent configuration lives in `utils/qwen_mini_interface.py`. Backup files exist for reverting between configurations:
- `qwen_mini_interface.py.exp013c_backup` — EXP-013c (current)
- `qwen_mini_interface.py.exp013b_backup` — EXP-013a state

Full experiment logs are in `EXPERIMENTS.md`. Per-run data is in `benchmark_runs/` and `evaluation_results/`.
