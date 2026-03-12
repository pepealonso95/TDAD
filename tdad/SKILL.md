---
name: tdad
description: Test-Driven AI Development — prevent code regressions with GraphRAG test impact analysis
version: 0.1.0
author: Pepe Alonso
tags: [tdd, testing, graphrag, regression-prevention, neo4j]
tools: [bash]
---

# TDAD — Test-Driven AI Development

A CLI tool that uses a Neo4j code-test dependency graph to identify which tests
are impacted by your code changes. Proven to reduce AI-introduced regressions
by 72% in SWE-bench evaluations.

## Setup

```bash
pip install tdad
docker compose -f /path/to/tdad/docker-compose.yml up -d
```

## TDD Workflow for AI Coding Agents

When fixing a bug or adding a feature, follow this 9-phase workflow.
Use it as advisory guidance — adapt to the situation.

### Phase 1: Understand the Request
Read the user's request. Identify what needs to change and what must stay the same.

### Phase 2: Ensure Graph is Current
```bash
tdad stats /path/to/repo   # check if indexed
tdad index /path/to/repo   # first time or if repo changed since last index
```
If `stats` shows zero nodes, index first. If the repo has changed
significantly since the last index, re-index with `--force`.

### Phase 3: Explore the Codebase
Search for relevant files, read source code, locate existing tests.
Understand the testing patterns and conventions used in the project.

### Phase 4: Plan the Change
Based on your exploration, identify which files and/or functions you'll modify and why.
This gives you the file list needed for impact analysis in the next phase.

### Phase 5: Identify Impacted Tests
```bash
tdad impact /path/to/repo --files src/module.py src/utils.py
```
Returns a ranked list of tests most likely affected by changes to those
files and functions. Use `--strategy conservative` for safety-critical changes.

### Phase 6: Establish Baseline
Run the impacted tests BEFORE making any changes:
```bash
tdad run-tests /path/to/repo --tests tests/test_module.py tests/test_utils.py
```
Record which tests pass. These MUST NOT break after your changes.

### Phase 7: Write Tests First (Red Phase)
Write or modify tests that verify the fix before touching implementation.
Run the new tests to confirm they FAIL — this proves they test the right thing. These tests should be aligned with the user's request.

### Phase 8: Implement (Green Phase)
Make all necessary changes to implement the users request and make sure your new tests pass.
Preserve existing functionality. Follow the repo's coding style.

### Phase 9: Regression Check
Run ALL impacted tests again:
```bash
tdad run-tests /path/to/repo --tests tests/test_module.py tests/test_utils.py
```
If any previously-passing test now fails, fix the regression before proceeding.
Iterate until all tests pass.

## GraphRAG Hints

When `tdad impact` returns results, use them as advisory guidance:

- **High-score tests (>= 0.8)**: Almost certainly affected — run these first
- **Medium-score tests (0.5–0.8)**: Likely affected — include in regression checks
- **Low-score tests (< 0.5)**: Possibly affected — run if time permits

The graph context suggests likely root-cause files and impacted tests.
Use these hints to prioritize your exploration, but if they look wrong,
investigate other files based on the issue description.
After your fix, if regression tests fail, address them with a minimal follow-up edit.

## CLI Reference

| Command | When to Use |
|---------|------------|
| `tdad index <repo> [--force]` | First time, or after major refactors |
| `tdad impact <repo> --files f1.py f2.py` | Before and after editing — know what tests matter |
| `tdad run-tests <repo> --tests t1.py::test_foo` | Run specific tests, get pass/fail summary |
| `tdad stats <repo>` | Verify the graph is populated |

## Quality Checklist

Before completing a task:
- [ ] New tests written that validate the fix or new functionality
- [ ] New tests initially failed (proving they test the issue)
- [ ] New tests now pass (proving the fix or new functionality works)
- [ ] All previously-passing impacted tests still pass

## Anti-Patterns to Avoid

- Writing implementation before tests
- Skipping the baseline test run
- Ignoring test failures in existing tests
- Making large changes without incremental testing
- Assuming tests pass without running them
