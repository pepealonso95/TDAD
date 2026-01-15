# TDAD: Test-Driven AI Development

**Master's Thesis**: Minimizing Code Regressions in AI Programming Agents

**Author**: Rafael Alonso
**Date**: October 2025
**Institution**: Universidad ORT / Berkeley

## Abstract

This thesis investigates whether Test-Driven Development (TDD) practices and GraphRAG-based code understanding can minimize code regressions in AI programming agents. We evaluate Claude Code on the SWE-bench benchmark across four configurations to measure regression rates and determine the effectiveness of different approaches.

## Research Question

**Can TDD practices and GraphRAG indexing reduce the regression rate of AI coding agents compared to baseline approaches?**

## Hypothesis

AI agents that:
1. Follow TDD practices (write/run tests before implementing)
2. Use GraphRAG to understand test-code relationships
3. Validate changes by running impacted tests

...will produce significantly fewer regressions than baseline agents.

## Methodology

### Benchmark
- **Dataset**: SWE-bench Lite (300 real-world GitHub issues)
- **Agent**: Claude Code (Anthropic's AI coding assistant)
- **Model**: Claude Sonnet 4.5
- **Metrics**: Generation rate, resolution rate, regression rate

### Four Experimental Configurations

#### 1. Baseline (Completed)
- Vanilla Claude Code with default prompts
- **Results**: 80% generation rate (8/10 patches in quick test)
- **Purpose**: Establish baseline regression rate

#### 2. TDD Prompt Engineering
- Modified prompts enforcing TDD workflow
- Requires test-first approach
- **Status**: Planned

#### 3. Vector RAG (claude-context)
- Vector-based codebase indexing
- Better semantic code understanding
- **Status**: Planned

#### 4. GraphRAG with Test Impact Analysis (Novel)
- Custom Claude Code plugin
- Graphs code-test relationships
- Runs impacted tests automatically
- **Status**: Planned

## Repository Structure

This repository uses a **single-repo approach** where all thesis components are tracked together:
- Thesis documentation (this file, EXPERIMENTS.md)
- Modified evaluation toolkit (claudecode_n_codex_swebench/)
- Experimental configurations and results
- Analysis scripts and notebooks

**Why single repo?** This approach is ideal for thesis work because:
- All modifications to the toolkit are versioned alongside experiments
- Easy for thesis advisors to review complete project
- Simple backup and recovery (one repository)
- Clear history of how toolkit evolved with experiments

```
TDAD/
├── .git/                               # Single git repository
├── README.md                           # This file - thesis overview
├── EXPERIMENTS.md                      # Detailed experiment log
├── .claude/
│   └── CLAUDE.md                       # Experiment logging discipline
│
├── claudecode_n_codex_swebench/       # Modified evaluation toolkit
│   ├── README_THESIS.md               # Detailed toolkit documentation
│   ├── code_swe_agent.py              # Agent implementation
│   ├── utils/                         # Modified utilities
│   │   ├── claude_interface.py        # Claude Code wrapper (FIXED)
│   │   ├── model_registry.py          # Model mappings (FIXED)
│   │   └── patch_extractor.py         # Patch extraction (ENHANCED)
│   ├── prompts/                       # Prompt templates
│   │   └── swe_bench_prompt.txt       # Default (baseline)
│   ├── predictions/                   # Generated patches (.gitignored)
│   ├── evaluation_results/            # Test results (.gitignored)
│   └── benchmark_scores.log           # Historical data
│
├── experiments/                        # Experiment configurations (TBD)
│   ├── baseline/
│   ├── tdd_prompts/
│   ├── vector_rag/
│   └── graph_rag/
│
└── analysis/                          # Data analysis notebooks (TBD)
```

### Toolkit Attribution

The `claudecode_n_codex_swebench/` directory contains a modified version of an external SWE-bench evaluation toolkit.

**Original Source**: Based on jimmc414's claudecode_swebench implementation
**License**: MIT (maintained)

**Modifications Made for This Thesis**:

1. **Model Registry Updates** (`utils/model_registry.py`)
   - Updated model IDs for Claude Code 2.0.28 compatibility
   - Fixed infinite recursion bug in model name resolution
   - Added support for Haiku 4.5 model
   - Changed from full model IDs to Claude CLI aliases

2. **Enhanced Debug Logging** (`utils/claude_interface.py`, `utils/patch_extractor.py`)
   - Added command execution logging for debugging
   - Added git status output before patch extraction
   - Added prompt/response preview logging
   - Essential for understanding agent behavior in experiments

3. **Robust Error Handling** (`utils/claude_interface.py`)
   - Added try-catch around directory restoration
   - Handles Claude Code's directory cleanup gracefully
   - Prevents cascading failures during batch processing

4. **Dataset Support**
   - Extended to support SWE-bench Verified (500 human-validated instances)
   - Maintained backward compatibility with SWE-bench Lite

**What's NOT Modified**:
- Core evaluation logic (unchanged)
- Docker integration (unchanged)
- Prompt templates (baseline unmodified, will create variants for experiments)
- File extraction and validation (core logic unchanged)

All modifications are tracked in this repository's git history and documented in EXPERIMENTS.md.

## Baseline Results

### Quick Test (10 instances, 49 minutes)

**Generation Rate**: 80% (8/10)

**Successful Patches**:
1. astropy__astropy-12907 - Separability matrix bug fix
2. astropy__astropy-14182 - RST header rows support
3. astropy__astropy-14365 - Case-insensitive QDP commands
4. astropy__astropy-14995 - NDDataRef mask propagation fix
5. astropy__astropy-6938 - FITS D exponents fix
6. astropy__astropy-7746 - WCS empty arrays handling
7. django__django-10914 - FILE_UPLOAD_PERMISSIONS default
8. django__django-10924 - FilePathField callable support

**Failed Cases**:
- 2 instances with git/directory issues

**Next Step**: Docker evaluation to determine actual resolution rate

## GraphRAG Test Impact Analysis (NEW)

### Overview

A novel MCP (Model Context Protocol) server that provides GraphRAG-powered test impact analysis for Claude Code. This system indexes Python codebases using AST-based structural chunking and builds a Neo4j graph database linking tests to code, enabling intelligent test selection and regression prevention.

### Features

- **AST-Based Code Parsing**: Extracts functions, classes, and their relationships
- **Multi-Strategy Test Linking**: Naming conventions, coverage data, static analysis
- **Impact Analysis**: Graph traversal to find tests affected by code changes
- **Intelligent Test Selection**: Run 10-20 targeted tests instead of 100+ full suite
- **FastAPI REST API**: HTTP endpoints for all operations
- **Incremental Updates**: Efficient reindexing of only changed files

### Installation

```bash
cd claudecode_n_codex_swebench

# Install GraphRAG dependencies
pip install -r requirements_mcp.txt

# Configure Neo4j (embedded mode - no separate install needed)
export NEO4J_EMBEDDED=true

# Optional: Configure embeddings with Claude Haiku
export ANTHROPIC_API_KEY=your_key
export EMBEDDINGS_PROVIDER=anthropic
```

### Quick Start

```bash
# Run with GraphRAG test impact analysis
python code_swe_agent_graphrag.py \
  --dataset_name princeton-nlp/SWE-bench_Verified \
  --limit 5 \
  --backend claude

# Disable GraphRAG (use baseline TDD)
python code_swe_agent_graphrag.py \
  --dataset_name princeton-nlp/SWE-bench_Verified \
  --limit 5 \
  --backend claude \
  --no-graphrag
```

### How It Works

1. **Graph Building**: Indexes repository on first run
   - Parses all Python files using AST
   - Extracts functions, classes, imports, calls
   - Links tests to code via naming, coverage, and static analysis
   - Stores in Neo4j graph database

2. **Change Detection**: After Claude Code makes changes
   - Uses git diff to find modified files
   - Identifies specific functions/lines changed

3. **Impact Analysis**: Queries graph for affected tests
   - **Direct testing** (score: 1.0): Tests explicitly testing modified code
   - **Transitive deps** (score: 0.7): Tests for functions calling modified code
   - **Coverage deps** (score: variable): Tests with coverage on modified files
   - **Import deps** (score: 0.5): Tests in files importing modified modules

4. **Targeted Testing**: Runs only impacted tests
   - Sorts by impact score
   - Runs high-impact tests first
   - Catches regressions in seconds vs minutes

### Performance Benefits

| Metric | Traditional TDD | GraphRAG TDD |
|--------|----------------|--------------|
| Tests Run | 100-500 (full suite) | 10-50 (targeted) |
| Execution Time | 5-10 minutes | 10-30 seconds |
| Feedback Loop | Slow | Fast |
| Regression Detection | All tests | Same effectiveness |

### Architecture

```
┌─────────────────────────────────────────┐
│  code_swe_agent_graphrag.py             │
│  (SWE-bench evaluation script)          │
└─────────────┬───────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────┐
│  mcp_graphrag_interface.py              │
│  (Python client)                        │
└─────────────┬───────────────────────────┘
              │ HTTP REST API
              ▼
┌─────────────────────────────────────────┐
│  FastAPI MCP Server (mcp_server/)       │
│  ┌──────────┐ ┌──────────┐ ┌─────────┐ │
│  │ Graph    │ │ Test     │ │ Impact  │ │
│  │ Builder  │ │ Linker   │ │ Analyzer│ │
│  └──────────┘ └──────────┘ └─────────┘ │
│              ↓                           │
│       ┌──────────────┐                  │
│       │ Neo4j Graph  │                  │
│       │ (Code+Tests) │                  │
│       └──────────────┘                  │
└─────────────────────────────────────────┘
```

### Documentation

- **MCP Server**: See [mcp_server/README.md](claudecode_n_codex_swebench/mcp_server/README.md)
- **Prompt Template**: [prompts/swe_bench_graphrag.txt](claudecode_n_codex_swebench/prompts/swe_bench_graphrag.txt)
- **Experiments**: See EXPERIMENTS.md (EXP-004)

## Key Findings (Preliminary)

### Baseline Agent Behavior
1. **High generation rate** (~80%) - agent attempts fixes
2. **Comprehensive patches** - includes tests and documentation
3. **Edge case failures** - directory/git state management issues
4. **Variable execution time** - 3-7 minutes per instance

### Toolkit Improvements Made
1. Fixed model registry for Claude Code compatibility
2. Added comprehensive debug logging
3. Implemented robust error handling
4. Documented edge cases and failure modes

## Setup & Installation

See [claudecode_n_codex_swebench/README_THESIS.md](claudecode_n_codex_swebench/README_THESIS.md) for detailed setup instructions.

### Quick Start

```bash
# Clone repository
git clone https://github.com/rafaelalonso/TDAD.git
cd TDAD/claudecode_n_codex_swebench

# Setup environment
conda create -n py313 python=3.13
conda activate py313
pip install -r requirements.txt

# Verify prerequisites
claude --version  # Claude Code CLI
docker ps         # Docker running

# Run baseline test
python code_swe_agent.py --dataset_name princeton-nlp/SWE-bench_Lite --limit 10 --backend claude
```

## Timeline

- **Week 1-2**: Baseline evaluation ✅
- **Week 3**: TDD prompt experiments
- **Week 4**: Vector RAG integration
- **Week 5-6**: GraphRAG plugin development
- **Week 7**: Full benchmark runs (300 instances × 4 configs)
- **Week 8**: Analysis and thesis writing

## Related Work

- **SWE-bench**: Princeton NLP benchmark for real-world code generation
- **Claude Code**: Anthropic's AI coding assistant (77.2% on SWE-bench Verified)
- **GraphRAG**: Microsoft's approach to knowledge graphs + RAG
- **Test Impact Analysis**: Traditional software engineering technique

## References

1. Anthropic. (2025). "Claude Sonnet 4.5: State-of-the-art coding performance"
2. Jimenez et al. (2024). "SWE-bench: Can Language Models Resolve Real-World GitHub Issues?"
3. Edge et al. (2024). "From Local to Global: A Graph RAG Approach"
4. Elbaum et al. (2014). "Techniques for improving regression testing"

## License

MIT License

## Contact

Rafael Alonso
[Your Email]
[Your University]

## Acknowledgments

- Anthropic for Claude Code and evaluation methodology
- Princeton NLP for SWE-bench benchmark
- Original `claudecode_swebench` toolkit by jimmc414
