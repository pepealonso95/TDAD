# TDAD Methodology Reference

## Test-Driven AI Development (TDAD)

TDAD adapts classical Test-Driven Development for AI coding agents. The key
insight: AI agents are good at generating code but bad at preserving existing
behavior. By making tests the primary feedback signal, we constrain the agent
to produce changes that don't break things.

## The 8-Phase Workflow

### Phase 1: Understand
Read the issue. Identify what's broken or needed. Note edge cases.

### Phase 2: Index
Build the code-test dependency graph. This creates a structural map of which
tests cover which functions, enabling targeted regression checking.

### Phase 3: Explore
Search the codebase. Read relevant files. Understand testing conventions.
The graph helps identify which files are most connected to the issue.

### Phase 4: Impact Analysis
Query the graph for tests impacted by the files you plan to change.
This is the key GraphRAG contribution — instead of running ALL tests,
run only the ones that matter.

### Phase 5: Baseline
Run impacted tests before any changes. Record pass/fail status.
This is your regression baseline.

### Phase 6: Red Phase (Write Tests First)
Write tests that verify the fix BEFORE implementing it.
Run them to confirm they fail. This proves they test the right thing.

### Phase 7: Green Phase (Implement)
Make minimal changes to pass the new tests. Don't over-engineer.

### Phase 8: Regression Check
Run all impacted tests again. Compare with baseline.
Fix any regressions before completing.

## Why GraphRAG?

Traditional TDD tells you to run tests, but doesn't tell you WHICH tests.
In large codebases, running the full suite takes too long for interactive
AI agent workflows. GraphRAG solves this by maintaining a dependency graph
that maps code changes to relevant tests.

### Graph Advantages

1. **Precision**: Only run tests that could be affected
2. **Speed**: Seconds instead of minutes for test selection
3. **Confidence**: Scored results help prioritize
4. **Transitive**: Catches indirect dependencies (A calls B calls C)

## Advisory vs. Prescriptive

The TDAD workflow is advisory, not prescriptive. The AI agent should:
- Use graph results as hints, not absolute truth
- Fall back to broader test runs when graph results seem incomplete
- Trust its own analysis when graph suggestions conflict with evidence
- Always verify with actual test execution

This advisory approach outperformed rigid procedural enforcement in our
evaluations. Agents that were forced to follow exact steps often got stuck;
agents that received hints and made their own decisions performed better.
