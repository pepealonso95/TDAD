# TDAD GraphRAG MCP Server

GraphRAG-powered Test Impact Analysis for TDAD Thesis - EXP-003/004

## Overview

This MCP (Model Context Protocol) server provides test impact analysis using GraphRAG (Graph Retrieval-Augmented Generation). It indexes Python codebases using AST-based structural chunking, links unit tests to code via static analysis and coverage data, and enables targeted test execution to prevent regressions.

## Features

- **AST-Based Code Parsing**: Extracts functions, classes, and their relationships
- **Test Linking**: Multiple strategies (naming conventions, coverage, static analysis)
- **Impact Analysis**: Graph traversal to find tests affected by code changes
- **Neo4j Graph Database**: Stores code-test dependency graph
- **FastAPI REST API**: HTTP endpoints for all operations
- **Incremental Updates**: Efficient reindexing of only changed files

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI MCP Server                        │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ Graph Builder│  │ Test Linker  │  │Impact Analyzer│     │
│  │   (AST)      │  │  (Coverage)  │  │   (Cypher)    │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
│          │                 │                  │             │
│          └─────────────────┴──────────────────┘             │
│                            │                                │
│                   ┌────────▼────────┐                       │
│                   │  Neo4j Graph DB │                       │
│                   │  (Code + Tests) │                       │
│                   └─────────────────┘                       │
└─────────────────────────────────────────────────────────────┘
                            ▲
                            │ HTTP REST API
                            │
                ┌───────────▼──────────┐
                │   MCP Client         │
                │   (Python Interface) │
                └──────────────────────┘
```

## Installation

### 1. Install Dependencies

```bash
cd /Users/rafaelalonso/Development/Master/Tesis/claudecode_n_codex_swebench
pip install -r requirements_mcp.txt
```

### 2. Setup Neo4j

**Option A: Use Embedded Neo4j (Recommended for development)**

Set environment variable:
```bash
export NEO4J_EMBEDDED=true
```

The server will create a local database in `.neo4j_embedded/`

**Option B: Use Standalone Neo4j**

Install and start Neo4j:
```bash
# macOS with Homebrew
brew install neo4j
neo4j start

# Or use Docker
docker run -d \
  --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password \
  neo4j:latest
```

Configure connection:
```bash
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=password
export NEO4J_EMBEDDED=false
```

### 3. Configure Embeddings (Optional)

For semantic embeddings using Claude Haiku:

```bash
export ANTHROPIC_API_KEY=your_api_key_here
export EMBEDDINGS_PROVIDER=anthropic
export EMBEDDINGS_MODEL=claude-3-haiku-20240307
```

## Usage

### Starting the Server

```bash
cd /Users/rafaelalonso/Development/Master/Tesis/claudecode_n_codex_swebench/mcp_server
python server.py
```

Server will start on `http://localhost:8080`

### Using the Python Client

```python
from utils.mcp_graphrag_interface import GraphRAGMCPInterface

# Initialize client (will start server if not running)
with GraphRAGMCPInterface() as mcp:
    # Build graph for a repository
    result = mcp.build_graph(
        repo_path="/path/to/repo",
        force_rebuild=False,
        include_tests=True
    )

    print(f"Built graph: {result['nodes_created']} nodes")

    # Find impacted tests
    impact = mcp.get_impacted_tests(
        repo_path="/path/to/repo",
        changed_files=["src/module.py"],
        impact_threshold=0.3
    )

    print(f"Found {impact['total_tests']} impacted tests")

    # Run only impacted tests
    test_result = mcp.run_tests(
        repo_path="/path/to/repo",
        tests=[t['test_file'] + '::' + t['test_name'] for t in impact['tests']]
    )

    print(f"Tests: {test_result['passed']} passed, {test_result['failed']} failed")
```

### REST API Endpoints

#### Health Check
```bash
curl http://localhost:8080/health
```

#### Build Graph
```bash
curl -X POST http://localhost:8080/tools/build_code_graph \
  -H "Content-Type: application/json" \
  -d '{
    "repo_path": "/path/to/repo",
    "force_rebuild": false,
    "include_tests": true
  }'
```

#### Get Impacted Tests
```bash
curl -X POST http://localhost:8080/tools/get_impacted_tests \
  -H "Content-Type: application/json" \
  -d '{
    "repo_path": "/path/to/repo",
    "changed_files": ["src/module.py"],
    "impact_threshold": 0.3
  }'
```

#### Run Tests
```bash
curl -X POST http://localhost:8080/tools/run_tests \
  -H "Content-Type: application/json" \
  -d '{
    "repo_path": "/path/to/repo",
    "tests": ["tests/test_module.py::test_function"],
    "pytest_args": ["-v"]
  }'
```

## Graph Schema

### Nodes

- **File**: Python source files
  - Properties: `path`, `name`, `content_hash`, `last_modified`

- **Function**: Functions and methods
  - Properties: `id`, `name`, `file_path`, `start_line`, `end_line`, `signature`, `docstring`, `embedding`

- **Class**: Class definitions
  - Properties: `id`, `name`, `file_path`, `start_line`, `end_line`, `docstring`, `embedding`

- **Test**: Unit tests
  - Properties: `id`, `name`, `file_path`, `function_name`, `test_type`

### Relationships

- **CONTAINS**: File → Function/Class
- **CALLS**: Function → Function
- **IMPORTS**: File → File
- **TESTS**: Test → Function/Class
- **INHERITS**: Class → Class
- **DEPENDS_ON**: Test → File (from coverage data)

## Impact Analysis Strategies

The server uses multiple strategies to find impacted tests:

1. **Direct Testing** (Score: 1.0)
   - Tests that directly test modified functions/classes

2. **Transitive Dependencies** (Score: 0.7)
   - Tests that test functions calling modified code

3. **Coverage Dependencies** (Score: variable)
   - Tests with coverage on modified files

4. **Import Dependencies** (Score: 0.5)
   - Tests in files that import modified files

## Configuration

Edit `mcp_server/config.py` or use environment variables:

```python
# Server Configuration
MCP_SERVER_HOST=0.0.0.0
MCP_SERVER_PORT=8080

# Neo4j Configuration
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
NEO4J_EMBEDDED=true

# Embeddings Configuration
ANTHROPIC_API_KEY=your_key
EMBEDDINGS_PROVIDER=anthropic
EMBEDDINGS_MODEL=claude-3-haiku-20240307

# Analysis Configuration
# (Set in config.py)
- chunk_level: "function" | "class" | "file"
- test_file_patterns: ["test_*.py", "*_test.py"]
- use_coverage: true
- coverage_threshold: 0.1
```

## Troubleshooting

### Neo4j Connection Issues

```bash
# Check if Neo4j is running
curl http://localhost:7474

# Check connection
python -c "from mcp_server.graph_db import get_db; db = get_db(); print('Connected!')"
```

### Server Won't Start

```bash
# Check port availability
lsof -i :8080

# Check logs
python mcp_server/server.py 2>&1 | tee server.log
```

### Coverage Not Working

```bash
# Install coverage.py
pip install coverage pytest-cov

# Test coverage manually
cd /path/to/repo
pytest --cov=. --cov-report=json
```

## Development

### Running Tests

```bash
pytest mcp_server/tests/
```

### Adding New Impact Strategies

Edit `mcp_server/impact_analyzer.py` and add new methods:

```python
def _find_my_custom_strategy(self, changed_files: List[str]) -> List[Dict]:
    """Custom impact detection logic"""
    # ... implement ...
    return impacted_tests
```

### Extending Graph Schema

Edit `mcp_server/graph_db.py` to add new node types or relationships.

## Performance

- **Initial Indexing**: ~1-5 minutes for repos with 100-1000 files
- **Incremental Updates**: ~10-30 seconds for 1-10 changed files
- **Impact Analysis**: ~1-5 seconds per query
- **Test Execution**: Depends on test suite size

## Experiment Usage (EXP-003/004)

This MCP server is designed for TDAD thesis experiments:

- **EXP-003**: TDD + GraphRAG impact analysis
- **EXP-004**: Full GraphRAG with test selection

See `/Users/rafaelalonso/Development/Master/Tesis/EXPERIMENTS.md` for experiment protocols.

## License

Part of TDAD Master's Thesis - Rafael Alonso, 2024

## References

- SWE-bench: https://arxiv.org/abs/2310.06770
- GraphRAG: https://arxiv.org/abs/2404.16130
- Neo4j: https://neo4j.com/docs/
- FastAPI: https://fastapi.tiangolo.com/
