---
name: tdad
description: >-
  Test-driven regression guard for AI coding agents. After every code change,
  look up impacted tests via the .tdad/test_map.txt file and run them before
  submitting a patch. Use whenever fixing bugs, implementing features, or
  refactoring Python code to prevent regressions. Activates when there is a
  .tdad/ directory in the repository.
license: MIT
compatibility: Requires Python 3.10+ and pytest. Works with any Python project.
metadata:
  author: pepealonso95
  version: "0.1.0"
  homepage: https://github.com/pepealonso95/tdad-skill
---

# TDAD — Test-Driven AI Development

Prevent regressions by checking impacted tests before submitting any patch.

## Setup (one-time per repo)

If `.tdad/test_map.txt` does not exist yet:

```bash
pip install tdad
tdad index .
```

This creates `.tdad/test_map.txt` mapping source files to their related tests.

## Bug Fix / Feature Workflow

### 1. Make the change

Read the source, identify the root cause or feature location, and make the minimal change needed.

### 2. Find impacted tests

For **each file you changed**, look up its tests:

```bash
grep 'path/to/changed_file.py' .tdad/test_map.txt
```

Output format: `source_file.py: test_a.py test_b.py test_c.py`

Collect all unique test files from every changed source file.

### 3. Run impacted tests

```bash
python -m pytest <test_files> -x -q 2>&1 | head -50
```

- If all tests pass, the change is safe to submit.
- If any test fails, diagnose and fix before proceeding. Re-run until green.

### 4. If test_map.txt has no entry

Fall back to finding tests by convention:

- `src/foo/bar.py` → look for `tests/test_bar.py` or `tests/foo/test_bar.py`
- Search for imports: `grep -r 'from.*bar import\|import.*bar' tests/`

## Rules

- **Never submit a patch without running impacted tests first.**
- Run the minimum set of tests needed (not the full suite) for speed.
- If you add new functionality, check if existing tests cover it. If not, note the gap but prioritize the fix.
- If `.tdad/test_map.txt` is missing and `tdad` is not installed, use the naming convention fallback in step 4.
