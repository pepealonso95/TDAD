# Project Agent Memory

## Experiment Logging (Persistent Rule)

- Whenever benchmark behavior, prompts, loops, gates, retries, or run settings are changed, document it in `EXPERIMENTS.md`.
- Whenever a benchmark run is executed, record the run in `EXPERIMENTS.md` before finishing the task.
- Each experiment entry must include:
  - Date and run ID / run name
  - Exact config and code changes
  - Reasoning/hypothesis for the tweak
  - Command(s) used
  - Results (resolved/unresolved, notable regressions, runtime) and next steps

