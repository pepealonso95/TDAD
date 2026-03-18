# TDAD: Test-Driven AI Development

**Master's Thesis**: Minimizing Code Regressions in AI Programming Agents Using TDD and GraphRAG

**Author**: Rafael Alonso
**Institution**: Universidad ORT
**Date**: October 2025 - March 2026

## Abstract

This thesis investigates whether Test-Driven Development (TDD) practices and
GraphRAG-based test impact analysis can minimize code regressions introduced by
AI coding agents. We evaluate three approaches on SWE-bench Verified (100
instances) using a local Qwen3-Coder 30B model: vanilla baseline, TDD prompt
engineering, and GraphRAG-enforced TDD. The GraphRAG approach **reduced
test-level regressions by 72%** (6.08% to 1.82%) while maintaining comparable
resolution rates.

## Research Question

Can TDD practices and GraphRAG-based code-test relationship indexing reduce the
regression rate of AI coding agents compared to baseline approaches?

## Results

Evaluated on SWE-bench Verified (100 instances), Qwen3-Coder 30B (Q4_K_M):

| Approach | Resolution Rate | Test-Level Regression Rate | Total P2P Failures |
|----------|:--------------:|:--------------------------:|:------------------:|
| Baseline (vanilla) | 31% (31/100) | 6.08% | 562 |
| TDD Prompting | 31% (31/100) | 9.94% | 799 |
| **GraphRAG + TDD** | **29% (29/100)** | **1.82%** | **155** |

### Key Findings

1. **72% regression reduction** -- GraphRAG + TDD reduced pass-to-pass test
   failures from 562 to 155 compared to vanilla baseline.

2. **TDD prompting alone increased regressions** -- Prompt-only TDD (9.94%)
   performed worse than vanilla (6.08%). More ambitious fixes touched more
   code; GraphRAG's graph-based localization counteracted this.

3. **GraphRAG reduces severity, not just frequency** -- When a GraphRAG patch
   was wrong, it caused far less collateral damage (fewer tests broken per
   instance).

4. **Modest resolution trade-off** -- GraphRAG resolved 29% vs vanilla's 31%
   (-2pp), driven by higher empty-patch rate, not lower patch quality.

5. **Smaller models need context, not procedure** -- Verbose, rigid prompts
   hurt the 30B quantized model. Graph-derived context outperformed
   prescriptive step-by-step instructions.

## Repository Structure

```
TDAD/
├── README.md                    # This file
├── EXPERIMENTS.md               # Detailed experiment log (EXP-001 to EXP-028)
├── .claude/CLAUDE.md            # AI assistant instructions
│
├── tdad/                        # TDAD tool (GraphRAG test impact analysis)
│   ├── src/tdad/
│   │   ├── core/                # Config, graph DB backends (Neo4j + NetworkX)
│   │   ├── indexer/             # AST parser, graph builder, test linker
│   │   ├── analyzer/            # Impact analysis (4 strategies)
│   │   └── cli.py               # CLI: tdad index|impact|stats|run-tests
│   ├── tests/
│   ├── SKILL.md                 # Agent-facing skill definition
│   └── README.md                # TDAD tool documentation
│
├── tdad-skill/                  # Published skill repo (github.com/pepealonso95/tdad-skill)
│
├── claudecode_n_codex_swebench/ # SWE-bench evaluation toolkit
│   ├── code_swe_agent.py        # Main agent (vanilla, TDD, GraphRAG modes)
│   ├── run_benchmark.py         # Multi-variant benchmark runner
│   ├── evaluate_predictions.py  # Docker evaluation harness
│   ├── utils/                   # Agent interfaces (Claude, Qwen, qwen-mini)
│   ├── mcp_server/              # GraphRAG MCP server (legacy)
│   ├── prompts/                 # Prompt templates
│   ├── predictions/             # Generated patches
│   ├── evaluation_results/      # Docker eval results
│   └── benchmark_runs/          # Per-run artifacts
│
└── mini_swe_agent_fork/         # Forked mini-swe-agent with bug fixes
```

## How TDAD Works

```
Code Changes
     |
     v
+-----------+     +------------+     +-----------+
| AST Parser|---->| Graph DB   |---->| Impact    |
| (indexer)  |    | File->Func |     | Analyzer  |
|            |    | Func->Func |     | 4 strategies|
+-----------+     | Test->Func |     +-----+-----+
                  +------------+           |
                                           v
                                Ranked list of tests
                                to run & verify
```

1. **Index** -- Parse Python files with AST, build a graph of files, functions,
   classes, tests, and their relationships (CALLS, IMPORTS, TESTS, INHERITS).
2. **Impact** -- Given changed files, traverse the graph to find impacted tests
   using 4 strategies: direct testing, transitive calls, coverage, imports.
3. **Verify** -- Run only the impacted tests. If failures, the agent fixes
   regressions before submitting.

## Experiments

All experiments are documented in [EXPERIMENTS.md](EXPERIMENTS.md). Key milestones:

| Experiment | Description | Resolution | Regression |
|------------|-------------|:----------:|:----------:|
| EXP-001 | Claude Code baseline (10 instances) | 80% gen | -- |
| EXP-011 | Qwen-mini baseline (100 instances) | 9% | -- |
| EXP-012d | Fixed config (32K context, temp=0) | 30% | -- |
| EXP-014 | Vanilla 100-instance final | **31%** | **6.08%** |
| EXP-015m | TDD prompt 100-instance final | **31%** | **9.94%** |
| EXP-023 | Cross-approach regression analysis | -- | **GraphRAG 1.82%** |
| EXP-027 | Autonomous auto-improvement loop | 60% (10-inst) | 0% |
| EXP-028 | NetworkX backend (drop Docker) | -- | -- |

## Setup

```bash
# Clone
git clone https://github.com/pepealonso95/TDAD.git
cd TDAD

# Install TDAD tool
cd tdad
pip install -e .

# Index a repo (uses NetworkX by default -- no Docker needed)
tdad index /path/to/your/repo

# Find impacted tests
tdad impact /path/to/your/repo --files src/module.py
```

For Neo4j backend: `TDAD_BACKEND=neo4j tdad index ...` (requires Docker).

## References

1. Jimenez et al. (2024). "SWE-bench: Can Language Models Resolve Real-World GitHub Issues?"
2. Edge et al. (2024). "From Local to Global: A Graph RAG Approach"
3. Elbaum et al. (2014). "Techniques for improving regression testing"
4. Anthropic. (2025). "Claude Sonnet 4.5: State-of-the-art coding performance"

## License

MIT
