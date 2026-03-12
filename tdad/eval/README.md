# SWE-bench Evaluation Harness for opencode + TDAD

Run [opencode](https://opencode.ai) on SWE-bench Verified in two modes — vanilla baseline vs. with the TDAD skill installed — and compare generation rate, resolution rate, and regression rate.

Uses **Qwen3.5-35B-A3B-4bit** via MLX as the local model.

## Prerequisites

- **opencode** CLI installed and on PATH
- **mlx-lm** installed (`pip install mlx-lm`)
- **Docker** running (for Neo4j and SWE-bench evaluation)
- **tdad** installed (`pip install -e .` from the `tdad/` root)
- **swebench** installed (`pip install swebench`)
- **datasets** library (`pip install datasets`)

## Setup: Start the MLX Model Server

Before running any evaluation, start the local model server in a separate terminal:

```bash
mlx_lm.server --model mlx-community/Qwen3.5-35B-A3B-4bit
```

This serves an OpenAI-compatible API on `http://localhost:8080`. The harness will verify connectivity before starting.

## Quick Start

```bash
# From the tdad/ directory

# Single instance, baseline only (smoke test)
python -m eval.run --mode baseline --limit 1

# Single instance, TDAD only
python -m eval.run --mode tdad --limit 1

# Both modes, 10 instances, skip Docker eval
python -m eval.run --mode both --limit 10 --skip-eval

# Both modes, 10 instances, full pipeline with evaluation
python -m eval.run --mode both --limit 10

# Specific instances
python -m eval.run --mode both --instance-ids django__django-10554 astropy__astropy-12907

# Full 500 (all SWE-bench Verified)
python -m eval.run --mode both
```

## CLI Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--mode` | `both` | `baseline`, `tdad`, or `both` |
| `--limit` | None (all) | Cap instance count |
| `--instance-ids` | None | Specific IDs to run |
| `--timeout` | 600 | Per-instance agent timeout (seconds) |
| `--run-name` | auto-timestamp | Run identifier |
| `--skip-eval` | false | Skip Docker evaluation |
| `--dataset` | `princeton-nlp/SWE-bench_Verified` | HuggingFace dataset |
| `--max-workers` | 2 | Parallel Docker containers for eval |
| `-v` | false | Verbose logging |

## Output Structure

```
eval/runs/{timestamp}_{run_name}/
├── config.json              # Run configuration (includes model info)
├── predictions/
│   ├── baseline.jsonl       # Baseline predictions
│   └── tdad.jsonl           # TDAD predictions
├── evaluations/
│   ├── *.eval.json          # SWE-bench evaluation results
├── report.json              # Structured comparison data
└── report.md                # Human-readable comparison report
```

## How It Works

### Model Setup (both modes)

Each cloned repo gets an `opencode.json` that configures:
- Provider: `mlx-local` via `@ai-sdk/openai-compatible`
- Base URL: `http://localhost:8080/v1` (MLX server)
- Model: `mlx-community/Qwen3.5-35B-A3B-4bit`
- Permissions: `allow: ["*"]` (no interactive approval)

### Baseline Mode
1. Clone repo, checkout base commit
2. Write `opencode.json` with MLX provider config
3. Pipe SWE-bench prompt to `opencode run` via stdin
4. Extract `git diff HEAD` as the patch
5. Append to `predictions/baseline.jsonl`

### TDAD Mode
Same as baseline, plus before the agent runs:
- Clear Neo4j graph
- Run `tdad index <repo> --force` to build the code-test dependency graph
- Copy `SKILL.md` into `.opencode/skills/tdad.md`
- Append "Use the @tdad skill for this task." to the prompt

## Interpreting Results

The `report.md` contains:
- **Generation Rate**: % of instances where a non-empty patch was produced
- **Resolution Rate**: % of patches that actually fix the issue (from Docker eval)
- **Delta**: Difference between TDAD and baseline (positive = TDAD is better)
- **Per-Instance Breakdown**: Which instances each mode patched/resolved
