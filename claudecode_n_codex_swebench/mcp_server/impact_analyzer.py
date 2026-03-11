"""
Test Impact Analyzer - Identifies tests impacted by code changes

Uses graph traversal to find:
1. Tests directly testing changed functions
2. Tests testing functions that call changed functions
3. Tests with coverage dependencies on changed files
"""
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import git
from unidiff import PatchSet

from .config import config
from .graph_db import get_db

logger = logging.getLogger(__name__)


class ImpactAnalyzer:
    """Analyzes the impact of code changes on tests"""

    def __init__(self):
        self.db = get_db()
        self._last_diagnostics: Dict[str, Any] = {}
        self._active_changed_symbols: List[Dict[str, Any]] = []
        self._active_changed_symbol_ids: List[str] = []
        self._active_changed_symbol_file_fallbacks: List[str] = []

    def get_last_diagnostics(self) -> Dict[str, Any]:
        """Return diagnostics produced by the latest impact analysis call."""
        return dict(self._last_diagnostics)

    def _run_query(self, session, query: str, **params):
        run_query = getattr(self.db, "run_query", None)
        if callable(run_query):
            return run_query(session, query, **params)
        return session.run(query, **params)

    def _get_strategy_weights(self, strategy: str) -> Dict[str, float]:
        """Get strategy-specific scoring weights."""
        selected = (strategy or "balanced").strip().lower()
        if selected not in {"conservative", "balanced", "aggressive"}:
            selected = "balanced"
        return {
            "strategy_name": selected,
            **{
                "conservative": {
                    "direct": 0.95,
                    "transitive": 0.55,
                    "coverage": 0.85,
                    "imports": 0.4,
                    "confidence_weight": 0.35,
                    "line_boost_max": 0.15,
                },
                "balanced": {
                    "direct": 0.95,
                    "transitive": 0.7,
                    "coverage": 0.8,
                    "imports": 0.5,
                    "confidence_weight": 0.3,
                    "line_boost_max": 0.2,
                },
                "aggressive": {
                    "direct": 0.95,
                    "transitive": 0.82,
                    "coverage": 0.9,
                    "imports": 0.65,
                    "confidence_weight": 0.25,
                    "line_boost_max": 0.25,
                },
            }[selected],
        }

    def _compute_score(
        self,
        *,
        base_weight: float,
        link_confidence: float,
        line_change_count: int,
        line_boost_max: float,
        confidence_weight: float,
    ) -> Tuple[float, float]:
        """Compute impact score and line boost component."""
        line_boost = min(line_boost_max, line_change_count / 100.0) if line_change_count > 0 else 0.0
        score = ((1.0 - confidence_weight) * base_weight) + (confidence_weight * link_confidence) + line_boost
        return min(1.0, max(0.0, float(score))), line_boost

    def get_impacted_tests(
        self,
        repo_path: Path,
        changed_files: Optional[List[str]] = None,
        base_commit: str = "HEAD",
        impact_threshold: float = 0.1,
        strategy: str = "balanced",
    ) -> List[Dict]:
        """
        Get tests impacted by code changes

        Args:
            repo_path: Path to repository
            changed_files: List of changed files (or use git diff)
            base_commit: Git commit to compare against
            impact_threshold: Minimum impact score (0-1) to include

        Returns:
            List of impacted tests with scores
        """
        logger.info(f"Analyzing test impact for: {repo_path}")

        if changed_files is None:
            changed_files = self._get_changed_files(repo_path, base_commit)
        changed_files = self._normalize_changed_files(repo_path, changed_files)

        weights = self._get_strategy_weights(strategy)
        selected_strategy = str(weights["strategy_name"])
        logger.info(
            f"Analyzing impact of {len(changed_files)} changed files (strategy={selected_strategy})"
        )

        if not changed_files:
            self._last_diagnostics = {
                "strategy": selected_strategy,
                "changed_files_count": 0,
                "changed_lines_by_file": {},
                "warnings": ["No changed Python files after normalization"],
                "empty_reason": "no_changed_python_files",
            }
            return []

        changed_lines = self._get_changed_lines(repo_path, changed_files, base_commit)
        changed_symbols, symbol_fallback_files = self._resolve_changed_symbols(
            changed_files=changed_files,
            changed_lines=changed_lines,
        )
        self._active_changed_symbols = list(changed_symbols)
        self._active_changed_symbol_ids = [
            str(symbol.get("target_id") or "")
            for symbol in changed_symbols
            if symbol.get("target_id")
        ]
        self._active_changed_symbol_file_fallbacks = list(symbol_fallback_files)
        impacted_tests: Dict[str, Dict[str, Any]] = {}
        strategy_results = {
            "direct": self._find_directly_tested_functions(changed_files),
            "transitive": self._find_transitive_dependencies(changed_files),
            "coverage": self._find_coverage_dependencies(changed_files),
            "imports": self._find_import_dependencies(changed_files),
        }

        def maybe_update(test: Dict[str, Any], source: str, reason: str) -> None:
            test_id = str(test.get("test_id", ""))
            if not test_id:
                return
            target_file = (
                test.get("target_file")
                or test.get("covered_file")
                or test.get("imported_file")
            )
            line_change_count = len(changed_lines.get(str(target_file), set())) if target_file else 0
            link_confidence = float(
                test.get("link_confidence")
                if test.get("link_confidence") is not None
                else test.get("coverage_pct", 0.6)
            )
            link_confidence = max(0.0, min(1.0, link_confidence))
            base_weight = float(weights[source])
            score, line_boost = self._compute_score(
                base_weight=base_weight,
                link_confidence=link_confidence,
                line_change_count=line_change_count,
                line_boost_max=float(weights["line_boost_max"]),
                confidence_weight=float(weights["confidence_weight"]),
            )
            candidate = {
                **test,
                "impact_score": score,
                "impact_reason": reason,
                "confidence": link_confidence,
                "line_change_count": line_change_count,
                "score_components": {
                    "strategy": selected_strategy,
                    "source": source,
                    "base_weight": base_weight,
                    "confidence_weight": float(weights["confidence_weight"]),
                    "link_confidence": link_confidence,
                    "line_boost": line_boost,
                },
                "traversal_path": list(test.get("traversal_path") or []),
            }

            existing = impacted_tests.get(test_id)
            if (
                existing is None
                or candidate["impact_score"] > existing.get("impact_score", 0.0)
                or (
                    candidate["impact_score"] == existing.get("impact_score", 0.0)
                    and candidate["confidence"] > existing.get("confidence", 0.0)
                )
            ):
                impacted_tests[test_id] = candidate

        for test in strategy_results["direct"]:
            maybe_update(test, "direct", "Directly tests changed code")
        for test in strategy_results["transitive"]:
            maybe_update(test, "transitive", "Transitive call dependency from changed code")
        for test in strategy_results["coverage"]:
            maybe_update(test, "coverage", "Coverage dependency on changed file")
        for test in strategy_results["imports"]:
            maybe_update(test, "imports", "Imports changed file")

        filtered_tests = [
            test for test in impacted_tests.values() if test.get("impact_score", 0.0) >= impact_threshold
        ]
        filtered_tests.sort(
            key=lambda t: (
                -float(t.get("impact_score", 0.0)),
                -float(t.get("confidence", 0.0)),
                -int(t.get("line_change_count", 0)),
                str(t.get("test_id", "")),
            )
        )

        self._last_diagnostics = {
            "strategy": selected_strategy,
            "changed_files_count": len(changed_files),
            "changed_lines_by_file": {k: sorted(list(v)) for k, v in changed_lines.items()},
            "changed_symbol_count": len(changed_symbols),
            "changed_symbol_ids": [
                str(symbol.get("target_id") or "")
                for symbol in changed_symbols[:50]
                if symbol.get("target_id")
            ],
            "symbol_file_fallbacks": list(symbol_fallback_files),
            "candidate_counts": {k: len(v) for k, v in strategy_results.items()},
            "selected_count": len(filtered_tests),
            "impact_threshold": impact_threshold,
            "warnings": [],
            "empty_reason": "" if filtered_tests else "no_candidates_above_threshold",
        }

        logger.info(f"Found {len(filtered_tests)} impacted tests (threshold: {impact_threshold})")
        return filtered_tests

    def _normalize_changed_files(self, repo_path: Path, changed_files: List[str]) -> List[str]:
        """Normalize changed files to unique repo-relative Python paths."""
        normalized: List[str] = []
        seen: Set[str] = set()
        repo_root = Path(repo_path).resolve()

        for raw_path in changed_files:
            if not raw_path:
                continue
            candidate = Path(raw_path)
            if candidate.is_absolute():
                try:
                    rel_path = str(candidate.resolve().relative_to(repo_root))
                except ValueError:
                    logger.debug(f"Skipping out-of-repo changed file path: {raw_path}")
                    continue
            else:
                rel_path = str(candidate)

            if not rel_path.endswith(".py"):
                continue
            if rel_path not in seen:
                seen.add(rel_path)
                normalized.append(rel_path)

        return normalized

    def _get_changed_files(self, repo_path: Path, base_commit: str) -> List[str]:
        """Get list of changed files using git diff plus untracked files."""
        try:
            repo = git.Repo(repo_path)
            diff = repo.git.diff('--name-only', base_commit)
            changed_files = [line.strip() for line in diff.splitlines() if line.strip()]
            untracked_files = [path for path in repo.untracked_files if path]
            merged: List[str] = []
            seen: Set[str] = set()
            for path in changed_files + untracked_files:
                if path not in seen:
                    seen.add(path)
                    merged.append(path)
            return [f for f in merged if f.endswith('.py')]
        except Exception as e:
            logger.error(f"Error getting changed files from git: {e}")
            return []

    def _get_changed_lines(
        self,
        repo_path: Path,
        changed_files: List[str],
        base_commit: str
    ) -> Dict[str, Set[int]]:
        """
        Get specific line numbers that changed in each file

        Returns:
            Dict mapping file_path -> set of changed line numbers
        """
        changed_lines = {}

        try:
            repo = git.Repo(repo_path)
            diff_text = repo.git.diff('-U0', base_commit)  # No context lines

            # Parse unified diff
            patch_set = PatchSet(diff_text)

            for patched_file in patch_set:
                if patched_file.is_added_file or patched_file.is_modified_file:
                    file_path = patched_file.path
                    if file_path not in changed_files:
                        continue
                    lines = set()

                    for hunk in patched_file:
                        # Get added and modified lines
                        for line in hunk:
                            if line.is_added or line.is_removed:
                                lines.add(line.target_line_no or line.source_line_no)

                    changed_lines[file_path] = lines

        except Exception as e:
            logger.error(f"Error parsing changed lines: {e}")

        return changed_lines

    def _resolve_changed_symbols(
        self,
        *,
        changed_files: List[str],
        changed_lines: Dict[str, Set[int]],
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """Resolve changed functions/classes from changed line ranges."""
        file_rows: List[Dict[str, Any]] = []
        fallback_files: List[str] = []

        for file_path in changed_files:
            lines = sorted(int(line) for line in changed_lines.get(file_path, set()) if line)
            if lines:
                file_rows.append(
                    {
                        "file_path": file_path,
                        "changed_lines": lines,
                        "min_line": min(lines),
                        "max_line": max(lines),
                    }
                )
            else:
                fallback_files.append(file_path)

        resolved: List[Dict[str, Any]] = []
        with self.db.driver.session(database=config.neo4j.database) as session:
            if file_rows:
                result = self._run_query(
                    session,
                    """
                    UNWIND $rows AS row
                    MATCH (target)
                    WHERE (target:Function OR target:Class)
                      AND target.file_path = row.file_path
                      AND coalesce(target.start_line, target.end_line, 0) <= row.max_line
                      AND coalesce(target.end_line, target.start_line, 0) >= row.min_line
                    WITH DISTINCT target, row
                    WHERE any(line IN row.changed_lines
                              WHERE line >= coalesce(target.start_line, target.end_line, 0)
                                AND line <= coalesce(target.end_line, target.start_line, 0))
                    RETURN DISTINCT
                        target.id as target_id,
                        labels(target)[0] as target_type,
                        target.name as target_name,
                        target.file_path as target_file,
                        target.start_line as start_line,
                        target.end_line as end_line,
                        target.qualified_name as qualified_name
                    """,
                    rows=file_rows,
                )
                resolved.extend(result.data())

        matched_files = {
            str(symbol.get("target_file") or "")
            for symbol in resolved
            if symbol.get("target_file")
        }
        for file_path in changed_files:
            if file_path not in matched_files and file_path not in fallback_files:
                fallback_files.append(file_path)

        deduped_symbols: List[Dict[str, Any]] = []
        seen_ids: Set[str] = set()
        for symbol in resolved:
            target_id = str(symbol.get("target_id") or "")
            if not target_id or target_id in seen_ids:
                continue
            seen_ids.add(target_id)
            deduped_symbols.append(symbol)

        deduped_fallbacks = list(dict.fromkeys(path for path in fallback_files if path))
        return deduped_symbols, deduped_fallbacks

    def _find_directly_tested_functions(self, changed_files: List[str]) -> List[Dict]:
        """Find tests that directly test functions in changed files"""
        symbol_ids = list(self._active_changed_symbol_ids or [])
        fallback_files = list(self._active_changed_symbol_file_fallbacks or [])
        with self.db.driver.session(database=config.neo4j.database) as session:
            result = self._run_query(
                session,
                """
                MATCH (t:Test)-[r:TESTS]->(target)
                WHERE (target:Function OR target:Class)
                  AND (
                    (size($symbol_ids) > 0 AND target.id IN $symbol_ids)
                    OR target.file_path IN $fallback_files
                    OR (size($symbol_ids) = 0 AND size($fallback_files) = 0 AND target.file_path IN $changed_files)
                  )
                RETURN DISTINCT
                    t.id as test_id,
                    t.name as test_name,
                    t.file_path as test_file,
                    target.name as target_function,
                    target.file_path as target_file,
                    target.id as target_id,
                    labels(target)[0] as target_type,
                    coalesce(r.link_confidence, r.coverage, 1.0) as link_confidence,
                    [target.id] as traversal_path
                """,
                changed_files=changed_files,
                symbol_ids=symbol_ids,
                fallback_files=fallback_files,
            )
            return result.data()

    def _find_transitive_dependencies(self, changed_files: List[str]) -> List[Dict]:
        """Find tests that test functions calling changed functions"""
        symbol_ids = list(self._active_changed_symbol_ids or [])
        fallback_files = list(self._active_changed_symbol_file_fallbacks or [])
        with self.db.driver.session(database=config.neo4j.database) as session:
            result = self._run_query(
                session,
                """
                MATCH (t:Test)-[r1:TESTS]->(fn1:Function)
                MATCH path = (fn1)-[:CALLS*1..3]->(fn2:Function)
                WHERE (
                    (size($symbol_ids) > 0 AND fn2.id IN $symbol_ids)
                    OR fn2.file_path IN $fallback_files
                    OR (size($symbol_ids) = 0 AND size($fallback_files) = 0 AND fn2.file_path IN $changed_files)
                )
                WITH t, r1, fn1, fn2, path,
                    length(path) as traversal_depth,
                    reduce(
                        call_conf = 1.0,
                        rel IN relationships(path) |
                            call_conf * coalesce(rel.resolution_confidence, 0.7)
                    ) as path_confidence
                ORDER BY t.id, fn2.id, traversal_depth ASC, path_confidence DESC
                WITH t, r1, fn1, fn2, collect(
                    {
                        traversal_depth: traversal_depth,
                        path_confidence: path_confidence,
                        traversal_path: [node IN nodes(path) | node.id]
                    }
                )[0] as best_path
                RETURN DISTINCT
                    t.id as test_id,
                    t.name as test_name,
                    t.file_path as test_file,
                    fn1.name as calling_function,
                    fn2.name as called_function,
                    fn2.file_path as target_file,
                    fn2.id as target_id,
                    best_path.traversal_depth as traversal_depth,
                    (
                        coalesce(r1.link_confidence, r1.coverage, 0.8)
                        * best_path.path_confidence
                        * (1.0 / toFloat(best_path.traversal_depth))
                    ) as link_confidence,
                    best_path.traversal_path as traversal_path
                """,
                changed_files=changed_files,
                symbol_ids=symbol_ids,
                fallback_files=fallback_files,
            )
            return result.data()

    def _find_coverage_dependencies(self, changed_files: List[str]) -> List[Dict]:
        """Find tests with coverage dependencies on changed files"""
        with self.db.driver.session(database=config.neo4j.database) as session:
            result = self._run_query(
                session,
                """
                MATCH (t:Test)-[r]->(f:File)
                WHERE type(r) = 'DEPENDS_ON' AND f.path IN $changed_files
                RETURN DISTINCT
                    t.id as test_id,
                    t.name as test_name,
                    t.file_path as test_file,
                    toFloat(coalesce(r.link_confidence, 0.0)) as coverage_pct,
                    f.path as covered_file,
                    coalesce(r.link_confidence, 0.5) as link_confidence,
                    [f.path] as traversal_path
                """,
                changed_files=changed_files
            )
            return result.data()

    def _find_import_dependencies(self, changed_files: List[str]) -> List[Dict]:
        """Find tests in files that import changed files"""
        with self.db.driver.session(database=config.neo4j.database) as session:
            result = self._run_query(
                session,
                """
                MATCH (test_file:File)-[:IMPORTS]->(changed_file:File)
                WHERE changed_file.path IN $changed_files
                MATCH (test_file)-[:CONTAINS]->(t:Test)
                RETURN DISTINCT
                    t.id as test_id,
                    t.name as test_name,
                    t.file_path as test_file,
                    changed_file.path as imported_file,
                    0.45 as link_confidence,
                    [test_file.path, changed_file.path] as traversal_path
                """,
                changed_files=changed_files
            )
            return result.data()

    def get_impact_summary(self, repo_path: Path, changed_files: List[str]) -> Dict:
        """Get a summary of impact analysis"""
        impacted_tests = self.get_impacted_tests(repo_path, changed_files)

        # Categorize by impact score
        high_impact = [t for t in impacted_tests if t["impact_score"] >= 0.8]
        medium_impact = [t for t in impacted_tests if 0.5 <= t["impact_score"] < 0.8]
        low_impact = [t for t in impacted_tests if t["impact_score"] < 0.5]

        return {
            "total_impacted": len(impacted_tests),
            "high_impact": len(high_impact),
            "medium_impact": len(medium_impact),
            "low_impact": len(low_impact),
            "changed_files": len(changed_files),
            "recommendation": self._get_recommendation(impacted_tests)
        }

    def _get_recommendation(self, impacted_tests: List[Dict]) -> str:
        """Get recommendation based on impact analysis"""
        if not impacted_tests:
            return "No tests impacted. Safe to proceed, but consider adding tests."

        high_impact = [t for t in impacted_tests if t["impact_score"] >= 0.8]

        if len(high_impact) == 0:
            return "Low impact detected. Run all tests to be safe."
        elif len(high_impact) <= 10:
            return f"Run {len(high_impact)} high-impact tests before committing."
        else:
            return f"High impact: {len(high_impact)} tests affected. Run full test suite."

    def get_minimal_test_set(
        self,
        repo_path: Path,
        changed_files: List[str],
        max_tests: int = 50
    ) -> List[str]:
        """
        Get minimal set of tests to run for maximum coverage

        Returns list of test identifiers (file::test_name)
        """
        impacted_tests = self.get_impacted_tests(repo_path, changed_files)

        top_tests = self._select_tiered_tests(impacted_tests, max_tests=max_tests)

        # Format as pytest identifiers
        test_identifiers = [
            f"{t['test_file']}::{t['test_name']}"
            for t in top_tests
        ]

        return test_identifiers

    def _select_tiered_tests(self, impacted_tests: List[Dict], max_tests: int) -> List[Dict]:
        """Select tests by confidence bands before falling back to lower-impact tests."""
        if max_tests <= 0 or not impacted_tests:
            return []

        high = [t for t in impacted_tests if t.get("impact_score", 0) >= 0.8]
        medium = [t for t in impacted_tests if 0.5 <= t.get("impact_score", 0) < 0.8]
        low = [t for t in impacted_tests if t.get("impact_score", 0) < 0.5]

        for band in (high, medium, low):
            band.sort(
                key=lambda t: (
                    t.get("impact_score", 0.0),
                    t.get("line_change_count", 0),
                    t.get("test_id", ""),
                ),
                reverse=True,
            )

        selected: List[Dict] = []
        seen_ids: Set[str] = set()
        for band in (high, medium, low):
            for test in band:
                test_id = str(test.get("test_id", ""))
                if test_id in seen_ids:
                    continue
                selected.append(test)
                seen_ids.add(test_id)
                if len(selected) >= max_tests:
                    return selected

        return selected
