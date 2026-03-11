# TDAD — Test-Driven AI Development

**Prevent code regressions in AI coding agents using TDD and GraphRAG.**

TDAD builds a code-test dependency graph in Neo4j and uses it to identify
exactly which tests are impacted by code changes. In SWE-bench evaluations,
this approach reduced AI-introduced regressions by 72%.

## Quick Start

```bash
# Install
pip install tdad

# Start Neo4j
docker compose up -d

# Index your repo
tdad index /path/to/your/repo

# Find impacted tests
tdad impact /path/to/your/repo --files src/module.py

# Run them
tdad run-tests /path/to/your/repo --tests tests/test_module.py::test_foo

# Check graph stats
tdad stats /path/to/your/repo
```

## How It Works

```
Your Code Changes
       │
       ▼
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  AST Parser │────▶│  Neo4j Graph │────▶│   Impact    │
│  (indexer)  │     │  File→Func   │     │  Analyzer   │
│             │     │  Func→Func   │     │  4 strategies│
└─────────────┘     │  Test→Func   │     └──────┬──────┘
                    └──────────────┘            │
                                                ▼
                                     Ranked list of tests
                                     to run & verify
```

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

## Results

Evaluated on SWE-bench Verified (100 instances):

| Approach | Resolution Rate | Regression Rate |
|----------|----------------|-----------------|
| Baseline (vanilla) | 30% | 18% |
| TDD Prompting | 31% | 14% |
| **GraphRAG + TDD** | **33%** | **5%** |

**72% regression reduction** compared to baseline.

## For AI Agents

See [SKILL.md](SKILL.md) for the agent-facing skill definition, including
the 8-phase TDD workflow and GraphRAG advisory hints.

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
