# Impact Analysis Strategies

## Overview

TDAD uses 4 Cypher query strategies to identify impacted tests, then combines
results with weighted scoring and tiered selection.

## Strategy 1: Direct (weight: 0.95)

```cypher
MATCH (t:Test)-[r:TESTS]->(target)
WHERE target.file_path IN $changed_files
RETURN t, r.link_confidence
```

Finds tests that directly test functions/classes in the changed files.
Highest weight because these are the most likely to break.

## Strategy 2: Transitive (weight: 0.70)

```cypher
MATCH (t:Test)-[:TESTS]->(fn1:Function)
MATCH (fn1)-[:CALLS*1..3]->(fn2:Function)
WHERE fn2.file_path IN $changed_files
RETURN t
```

Finds tests that test functions which *call* changed functions, up to 3 hops.
Lower weight because the connection is indirect, but catches important
cascade failures.

## Strategy 3: Coverage (weight: 0.80)

```cypher
MATCH (t:Test)-[:DEPENDS_ON]->(f:File)
WHERE f.path IN $changed_files
RETURN t
```

Uses runtime coverage data (from `pytest --cov`) to find tests that executed
code in the changed files. High confidence when available.

## Strategy 4: Imports (weight: 0.50)

```cypher
MATCH (test_file:File)-[:IMPORTS]->(changed_file:File)
WHERE changed_file.path IN $changed_files
MATCH (test_file)-[:CONTAINS]->(t:Test)
RETURN t
```

Broadest strategy: any test in a file that imports the changed file.
Lowest weight as it may catch many unrelated tests.

## Scoring Formula

```
score = (1 - confidence_weight) * base_weight + confidence_weight * link_confidence
```

Where:
- `base_weight`: Strategy weight from the table above
- `link_confidence`: How confident the test linker was in the TESTS edge (0–1)
- `confidence_weight`: How much to weight the link confidence (default 0.3)

## Strategy Profiles

| Profile | Direct | Transitive | Coverage | Imports | Conf. Weight |
|---------|--------|------------|----------|---------|-------------|
| Conservative | 0.95 | 0.55 | 0.85 | 0.40 | 0.35 |
| Balanced | 0.95 | 0.70 | 0.80 | 0.50 | 0.30 |
| Aggressive | 0.95 | 0.82 | 0.90 | 0.65 | 0.25 |

## Tiered Selection

After scoring, tests are selected in tiers with a configurable cap (default 50):

1. **High impact** (score >= 0.8): Selected first — almost certainly affected
2. **Medium impact** (0.5 <= score < 0.8): Fill remaining capacity
3. **Low impact** (score < 0.5): Only if capacity remains

This ensures the most important tests are always included, even with a
small test budget.
