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

```
TDAD/
├── README.md                           # This file
├── claudecode_n_codex_swebench/       # Main evaluation toolkit
│   ├── README_THESIS.md               # Detailed toolkit documentation
│   ├── code_swe_agent.py              # Agent implementation
│   ├── utils/                         # Modified utilities
│   │   ├── claude_interface.py        # Claude Code wrapper (FIXED)
│   │   ├── model_registry.py          # Model mappings (FIXED)
│   │   └── patch_extractor.py         # Patch extraction (ENHANCED)
│   ├── prompts/                       # Prompt templates
│   │   └── swe_bench_prompt.txt       # Default (baseline)
│   ├── predictions/                   # Generated patches
│   ├── evaluation_results/            # Test results
│   └── benchmark_scores.log           # Historical data
├── experiments/                        # Experiment configurations (TBD)
│   ├── baseline/
│   ├── tdd_prompts/
│   ├── vector_rag/
│   └── graph_rag/
└── analysis/                          # Data analysis notebooks (TBD)
```

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
