# TDAD — Test-Driven AI Development

**Minimizing code regressions in AI coding agents using TDD and GraphRAG.**

TDAD builds a code-test dependency graph in Neo4j and uses it to identify
exactly which tests are impacted by code changes. When integrated into an
AI agent's workflow, it enforces regression checking before patch submission.

Evaluated on SWE-bench Verified (100 instances), GraphRAG-based test impact
analysis **reduced AI-introduced regressions by 72%** compared to a vanilla
baseline, bringing the test-level regression rate down from 6.08% to 1.82%.

## Quick Start

```bash
# Install
pip install tdad

# Start Neo4j
docker compose up -d

# Index your repo
tdad index /path/to/your/repo

# Find impacted tests for changed files
tdad impact /path/to/your/repo --files src/module.py

# Run impacted tests
tdad run-tests /path/to/your/repo --tests tests/test_module.py::test_foo

# Check graph stats
tdad stats /path/to/your/repo
```

## How It Works

```
Your Code Changes
       |
       v
+-------------+     +--------------+     +-------------+
|  AST Parser |---->|  Neo4j Graph |---->|   Impact    |
|  (indexer)  |     |  File->Func  |     |  Analyzer   |
|             |     |  Func->Func  |     |  4 strategies|
+-------------+     |  Test->Func  |     +------+------+
                    +--------------+            |
                                                v
                                     Ranked list of tests
                                     to run & verify
```

### Architecture

TDAD has four core components:

1. **AST Parser** (`indexer/ast_parser.py`) — Extracts functions, classes,
   imports, and call relationships from Python source files using the `ast`
   module.

2. **Graph Builder** (`indexer/graph_builder.py`) — Populates Neo4j with
   nodes (File, Function, Class, Test) and edges (CONTAINS, CALLS, IMPORTS,
   INHERITS, TESTS). Supports both full and incremental indexing via git diff.

3. **Test Linker** (`indexer/test_linker.py`) — Creates TESTS relationships
   between test nodes and the code they exercise, using three strategies:
   naming conventions, static analysis of imports/calls, and optional
   per-test coverage data.

4. **Impact Analyzer** (`analyzer/impact.py`) — Given a set of changed files,
   traverses the graph to produce a ranked list of impacted tests sorted by
   impact score.

### Graph Schema

- **Nodes**: File, Function, Class, Test
- **Edges**: CONTAINS, CALLS, IMPORTS, INHERITS, TESTS

### Impact Strategies

| Strategy | Weight | Description |
|----------|--------|-------------|
| Direct | 0.95 | Test directly tests a changed function |
| Transitive | 0.70 | Test tests a function that calls changed code |
| Coverage | 0.80 | Test has coverage dependency on changed file |
| Imports | 0.50 | Test file imports the changed file |

## Configuration

All settings via environment variables with `TDAD_` prefix:

| Variable | Default | Description |
|----------|---------|-------------|
| `TDAD_NEO4J_URI` | `bolt://localhost:7687` | Neo4j connection URI |
| `TDAD_NEO4J_USER` | `neo4j` | Neo4j username |
| `TDAD_NEO4J_PASSWORD` | `password` | Neo4j password |
| `TDAD_NEO4J_DATABASE` | `neo4j` | Neo4j database name |
| `TDAD_USE_COVERAGE` | `false` | Enable coverage-based test linking |
| `TDAD_COVERAGE_THRESHOLD` | `0.1` | Minimum coverage to create a link |
| `TDAD_INDEX_WORKERS` | `4` | Parallel parsing workers |
| `TDAD_QUERY_TIMEOUT` | `20.0` | Neo4j query timeout (seconds) |

## Experimental Results

Evaluated on SWE-bench Verified (100 instances) using Qwen3-Coder 30B
(Q4_K_M quantization) via llama.cpp as the AI coding agent.

### Resolution and Regression Rates

| Approach | Resolution Rate | Test-Level Regression Rate | Total P2P Failures |
|----------|:--------------:|:--------------------------:|:------------------:|
| Baseline (vanilla) | 31% (31/100) | 6.08% | 562 |
| TDD Prompting | 31% (31/100) | 9.94% | 799 |
| **GraphRAG + TDD** | **29% (29/100)** | **1.82%** | **155** |

### Regression Reduction

| Comparison | P2P Failure Reduction | Rate Change |
|------------|:---------------------:|:-----------:|
| GraphRAG vs Vanilla | 562 -> 155 | **-72%** |
| GraphRAG vs TDD Prompt | 799 -> 155 | **-81%** |

### Generation Rates

| Approach | Generation Rate | Empty Patches |
|----------|:--------------:|:-------------:|
| Baseline (vanilla) | 86% (86/100) | 14 |
| TDD Prompting | 75% (75/100) | 25 |
| GraphRAG + TDD | 74% (74/100) | 26 |

### Key Findings

1. **72% regression reduction** — GraphRAG + TDD reduced total pass-to-pass
   test failures from 562 to 155 compared to the vanilla baseline, bringing
   the test-level regression rate from 6.08% to 1.82%.

2. **TDD prompting alone increased regressions** — Prompt-only TDD (9.94%)
   performed worse than vanilla (6.08%) because more ambitious fixes touched
   more code. GraphRAG's graph-based localization counteracted this by
   constraining edits to well-understood areas.

3. **GraphRAG reduces severity, not just frequency** — The instance-level
   regression count was similar across approaches (~25 instances), but when
   a GraphRAG patch was wrong it caused far less collateral damage (fewer
   tests broken per instance).

4. **Modest resolution trade-off** — GraphRAG resolved 29% vs vanilla's 31%
   (-2pp). The difference is driven by a higher empty-patch rate (26% vs 14%),
   not by lower patch quality. When GraphRAG generates a patch, it is more
   likely to be correct and less likely to regress.

5. **Smaller models need context, not procedure** — Verbose, rigid prompts
   hurt the 30B quantized model. Providing graph-derived context (what tests
   are impacted) outperformed prescriptive step-by-step instructions.

### Metric Definitions

- **Resolution Rate** — % of instances where the patch fixes the target issue
  (passes all FAIL_TO_PASS tests without breaking PASS_TO_PASS tests).
- **Test-Level Regression Rate** — `sum(PASS_TO_PASS failures) /
  sum(total PASS_TO_PASS tests) * 100` across all evaluated instances.
- **Instance-Level Regression Rate** — % of evaluated instances with at least
  one PASS_TO_PASS failure.
- **Generation Rate** — % of instances where the agent produced a non-empty
  patch.

## Install as an AI Agent Skill

TDAD ships as an [Agent Skill](https://agentskills.io) that teaches coding
agents to check impacted tests before submitting patches.

### Claude Code

```bash
# Via skills.sh
npx skills add pepealonso95/tdad-skill

# Or manually: copy into your project
mkdir -p .claude/skills/tdad
cp SKILL.md .claude/skills/tdad/SKILL.md
```

### Other agents

Any agent that supports the [Agent Skills spec](https://agentskills.io/specification)
can use the `SKILL.md` file directly. Copy it into the agent's skills directory.

### How the skill works

The skill instructs the agent to:
1. Look up impacted tests in `.tdad/test_map.txt` after every code change
2. Run only the impacted tests (not the full suite)
3. Fix any regressions before submitting the patch

See [SKILL.md](SKILL.md) for the full agent-facing instructions.

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/

# Start Neo4j for integration tests
docker compose up -d
```

## License

MIT — see [LICENSE](LICENSE).
