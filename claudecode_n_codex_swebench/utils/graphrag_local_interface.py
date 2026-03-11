"""
Local in-process GraphRAG interface.

This avoids HTTP/MCP transport and calls GraphRAG core modules directly:
- GraphBuilder
- ImpactAnalyzer
- TestLinker / TestRunner
- GraphDB
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp_server.config import config
from mcp_server.graph_builder import GraphBuilder
from mcp_server.graph_db import get_db
from mcp_server.impact_analyzer import ImpactAnalyzer
from mcp_server.test_linker import TestLinker, TestRunner

from .mcp_graphrag_interface import GraphRAGMCPInterface

logger = logging.getLogger(__name__)


def _impacted_test_key(test: Dict[str, Any]) -> str:
    """Build a stable key for impacted-test deduplication."""
    test_id = str(test.get("test_id") or "").strip()
    if test_id:
        return f"id:{test_id}"
    test_file = str(test.get("test_file") or "").strip().replace("\\", "/")
    test_name = str(test.get("test_name") or "").strip()
    if test_file and test_name:
        return f"nodeid:{test_file}::{test_name}"
    return ""


def _merge_impacted_tests(
    graph_tests: List[Dict[str, Any]],
    coverage_tests: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge graph-traversal and coverage-diff impacted tests."""
    merged: Dict[str, Dict[str, Any]] = {}

    def upsert(test: Dict[str, Any], source: str) -> None:
        key = _impacted_test_key(test)
        if not key:
            return

        score = float(test.get("impact_score", 0.0) or 0.0)
        row = merged.get(key)
        if row is None:
            row = dict(test)
            row["graph_impact_score"] = score if source == "graph" else 0.0
            row["coverage_impact_score"] = score if source == "coverage" else 0.0
            merged[key] = row
            return

        if source == "graph":
            row["graph_impact_score"] = max(float(row.get("graph_impact_score", 0.0) or 0.0), score)
        else:
            row["coverage_impact_score"] = max(float(row.get("coverage_impact_score", 0.0) or 0.0), score)

        for field in ("test_id", "test_name", "test_file"):
            if not row.get(field) and test.get(field):
                row[field] = test.get(field)

        if score > float(row.get("impact_score", 0.0) or 0.0):
            row["impact_score"] = score
            if test.get("impact_reason"):
                row["impact_reason"] = test.get("impact_reason")

        if source == "graph":
            row["line_change_count"] = max(
                int(row.get("line_change_count", 0) or 0),
                int(test.get("line_change_count", 0) or 0),
            )
            row["confidence"] = max(
                float(row.get("confidence", 0.0) or 0.0),
                float(test.get("confidence", 0.0) or 0.0),
            )
            existing_path = list(row.get("traversal_path") or [])
            for item in list(test.get("traversal_path") or []):
                if item not in existing_path:
                    existing_path.append(item)
            if existing_path:
                row["traversal_path"] = existing_path
        else:
            existing_changed = set(row.get("matched_changed_files", []) or [])
            existing_changed.update(list(test.get("matched_changed_files", []) or []))
            if existing_changed:
                row["matched_changed_files"] = sorted(existing_changed)
            row["coverage_hits"] = max(
                int(row.get("coverage_hits", 0) or 0),
                int(test.get("coverage_hits", 0) or 0),
            )

    for record in graph_tests:
        upsert(record, "graph")
    for record in coverage_tests:
        upsert(record, "coverage")

    merged_rows = list(merged.values())
    for row in merged_rows:
        graph_score = float(row.get("graph_impact_score", 0.0) or 0.0)
        coverage_score = float(row.get("coverage_impact_score", 0.0) or 0.0)
        corroborated = graph_score > 0.0 and coverage_score > 0.0
        consensus_bonus = 0.05 if corroborated else 0.0
        row["impact_score"] = min(
            1.0,
            max(float(row.get("impact_score", 0.0) or 0.0), graph_score, coverage_score) + consensus_bonus,
        )
        if corroborated:
            row["impact_reason"] = "Graph traversal + runtime coverage overlap"
            row["impact_source"] = "graph+coverage"
        elif coverage_score > 0.0:
            row["impact_source"] = "coverage"
            row.setdefault("impact_reason", "Coverage overlap with changed files")
        else:
            row["impact_source"] = "graph"
            row.setdefault("impact_reason", "Graph traversal impact")

    merged_rows.sort(
        key=lambda row: (
            -float(row.get("impact_score", 0.0) or 0.0),
            -float(row.get("graph_impact_score", 0.0) or 0.0),
            -float(row.get("coverage_impact_score", 0.0) or 0.0),
            str(row.get("test_id") or ""),
            str(row.get("test_name") or ""),
        )
    )
    return merged_rows


class GraphRAGLocalInterface(GraphRAGMCPInterface):
    """
    GraphRAG interface that runs in-process without MCP/HTTP transport.

    It intentionally reuses selection/iteration helpers from GraphRAGMCPInterface
    but replaces transport calls with direct local core calls.
    """

    def __init__(self):
        self.server_url = "local://graphrag"
        self.server_process = None
        self.transport_mode = "local"
        self._indexed_graph_identities: Dict[str, Dict[str, str]] = {}
        self._last_graph_status: Dict[str, object] = {}

    def _verify_server(self):
        """Fail fast if MCP transport verification leaks into local mode."""
        self._raise_transport_unavailable("_verify_server")

    def stop_server(self):
        """Explicit no-op for local in-process mode."""

    def __enter__(self):
        """Use local context management without inherited MCP lifecycle hooks."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop_server()
        return False

    def _raise_transport_unavailable(self, method_name: str):
        raise RuntimeError(
            f"{method_name} is unavailable in local GraphRAG mode; "
            "use the in-process GraphRAG operations instead."
        )

    def _start_server(self):
        self._raise_transport_unavailable("_start_server")

    def _post_with_heartbeat(self, *args, **kwargs):
        self._raise_transport_unavailable("_post_with_heartbeat")

    def _request_with_retry(self, *args, **kwargs):
        self._raise_transport_unavailable("_request_with_retry")

    def _poll_build_job(self, *args, **kwargs):
        self._raise_transport_unavailable("_poll_build_job")

    def _get_graph_meta(self) -> Dict:
        """Fetch graph metadata from local Neo4j state."""
        try:
            meta = get_db().get_status_metadata()
            return {"success": True, **meta}
        except Exception as e:
            logger.error(f"Error getting local graph status metadata: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    def _progress_logger(self, prefix: str):
        """Create throttled progress callback for local indexing stages."""
        state: Dict[str, Any] = {
            "stage": "",
            "progress": -1,
            "last_log_ts": 0.0,
        }

        def _callback(update: Dict[str, Any]) -> None:
            stage = str(update.get("stage", "unknown"))
            progress = float(update.get("progress_pct", 0.0) or 0.0)
            files_done = int(update.get("files_done", 0) or 0)
            files_total = int(update.get("files_total", 0) or 0)
            nodes_written = int(update.get("nodes_written", 0) or 0)
            edges_written = int(update.get("edges_written", 0) or 0)
            now = time.time()
            should_log = (
                stage != state["stage"]
                or int(progress) != int(state["progress"])
                or (now - float(state["last_log_ts"])) >= 15.0
            )
            if should_log:
                self._phase_log(
                    f"{prefix} status=running stage={stage} progress={progress:.1f}% "
                    f"files={files_done}/{files_total} nodes={nodes_written} edges={edges_written}"
                )
                state["stage"] = stage
                state["progress"] = progress
                state["last_log_ts"] = now

        return _callback

    def build_graph(
        self,
        repo_path: str,
        force_rebuild: bool = False,
        include_tests: bool = True,
        repo_slug: Optional[str] = None,
        commit_sha: Optional[str] = None,
    ) -> Dict:
        """Build code graph locally (no MCP server)."""
        resolved_repo_slug = self._resolve_repo_slug(repo_path, repo_slug=repo_slug)
        resolved_commit_sha = self._resolve_commit_sha(repo_path, commit_sha=commit_sha)
        resolved_repo_fingerprint = self._resolve_repo_fingerprint(
            repo_path,
            commit_sha=resolved_commit_sha,
        )
        expected_graph_identity = f"{resolved_repo_slug}@{resolved_commit_sha}"
        cache_key = self._get_repo_cache_key(
            repo_path,
            repo_slug=resolved_repo_slug,
            commit_sha=resolved_commit_sha,
        )
        self._phase_log(
            "INDEXING_START "
            f"repo={resolved_repo_slug} commit={resolved_commit_sha[:8]} "
            f"force_rebuild={force_rebuild} mode=local"
        )

        if not force_rebuild:
            if cache_key in self._indexed_graph_identities and self._check_graph_exists(
                expected_graph_identity,
                repo_path=repo_path,
                strict_graph_identity=True,
                require_fresh_graph=True,
                expected_repo_fingerprint=resolved_repo_fingerprint,
            ):
                stats = self.get_stats()
                self._phase_log(
                    "INDEXING_END status=cached source=in_process "
                    f"graph_identity={expected_graph_identity}"
                )
                return {
                    "success": True,
                    "cached": True,
                    "cache_key": cache_key,
                    "graph_identity": expected_graph_identity,
                    "repo_fingerprint": resolved_repo_fingerprint,
                    "nodes_created": stats.get("total_nodes", 0),
                    "relationships_created": stats.get("total_relationships", 0),
                }
            if self._check_graph_exists(
                expected_graph_identity,
                repo_path=repo_path,
                strict_graph_identity=True,
                require_fresh_graph=True,
                expected_repo_fingerprint=resolved_repo_fingerprint,
            ):
                stats = self.get_stats()
                self._indexed_graph_identities[cache_key] = {
                    "graph_identity": expected_graph_identity,
                    "repo_fingerprint": resolved_repo_fingerprint,
                }
                self._phase_log(
                    "INDEXING_END status=cached source=neo4j "
                    f"graph_identity={expected_graph_identity}"
                )
                return {
                    "success": True,
                    "cached": True,
                    "cache_key": cache_key,
                    "graph_identity": expected_graph_identity,
                    "repo_fingerprint": resolved_repo_fingerprint,
                    "nodes_created": stats.get("total_nodes", 0),
                    "relationships_created": stats.get("total_relationships", 0),
                }

        start = time.time()
        try:
            builder = GraphBuilder()
            progress_callback = self._progress_logger("INDEXING_PROGRESS")
            build_result = builder.build_graph(
                repo_path=Path(repo_path),
                force_rebuild=force_rebuild,
                repo_slug=resolved_repo_slug,
                commit_sha=resolved_commit_sha,
                repo_fingerprint=resolved_repo_fingerprint,
                progress_callback=progress_callback,
            )

            warnings = []
            if include_tests:
                linker = TestLinker()
                test_links = linker.link_tests(Path(repo_path))
                warnings.extend(test_links.get("warnings", []))

            duration = time.time() - start
            result = {
                "success": True,
                "request_id": f"local_build_{int(start)}",
                "nodes_created": int(build_result.get("nodes_created", 0) or 0),
                "relationships_created": int(build_result.get("relationships_created", 0) or 0),
                "duration_seconds": duration,
                "warnings": warnings,
                "message": f"Graph built locally: {int(build_result.get('files_processed', 0) or 0)} files",
                "cache_key": cache_key,
                "graph_identity": expected_graph_identity,
                "repo_fingerprint": resolved_repo_fingerprint,
            }
            self._indexed_graph_identities[cache_key] = {
                "graph_identity": expected_graph_identity,
                "repo_fingerprint": resolved_repo_fingerprint,
            }
            self._phase_log(
                "INDEXING_END status=success "
                f"graph_identity={expected_graph_identity} "
                f"nodes={result['nodes_created']} rels={result['relationships_created']} "
                f"elapsed={duration:.1f}s"
            )
            return result
        except Exception as e:
            logger.error(f"Error building local graph: {e}")
            self._phase_log(f"INDEXING_END status=failed error={e}")
            return {
                "success": False,
                "error": str(e),
                "nodes_created": 0,
                "relationships_created": 0,
                "cache_key": cache_key,
                "graph_identity": expected_graph_identity,
                "repo_fingerprint": resolved_repo_fingerprint,
            }

    def incremental_update(
        self,
        repo_path: str,
        changed_files: Optional[List[str]] = None,
        base_commit: str = "HEAD",
        include_tests: bool = True,
        repo_slug: Optional[str] = None,
        commit_sha: Optional[str] = None,
        repo_fingerprint: Optional[str] = None,
    ) -> Dict:
        """Incrementally update graph locally."""
        self._phase_log("INDEXING_INCREMENTAL_START mode=local")
        resolved_repo_slug = self._resolve_repo_slug(repo_path, repo_slug=repo_slug)
        resolved_commit_sha = self._resolve_commit_sha(repo_path, commit_sha=commit_sha)
        resolved_repo_fingerprint = repo_fingerprint or self._resolve_repo_fingerprint(
            repo_path,
            commit_sha=resolved_commit_sha,
        )

        start = time.time()
        try:
            builder = GraphBuilder()
            progress_callback = self._progress_logger("INDEXING_INCREMENTAL_PROGRESS")
            result = builder.incremental_update(
                repo_path=Path(repo_path),
                changed_files=changed_files,
                base_commit=base_commit,
                repo_slug=resolved_repo_slug,
                commit_sha=resolved_commit_sha,
                repo_fingerprint=resolved_repo_fingerprint,
                progress_callback=progress_callback,
            )

            warnings = []
            if include_tests:
                linker = TestLinker()
                test_links = linker.link_tests(Path(repo_path))
                warnings.extend(test_links.get("warnings", []))

            cache_key = self._get_repo_cache_key(
                repo_path,
                repo_slug=resolved_repo_slug,
                commit_sha=resolved_commit_sha,
            )
            self._indexed_graph_identities[cache_key] = {
                "graph_identity": f"{resolved_repo_slug}@{resolved_commit_sha}",
                "repo_fingerprint": resolved_repo_fingerprint,
            }

            duration = time.time() - start
            self._phase_log(
                "INDEXING_INCREMENTAL_END status=success "
                f"nodes={int(result.get('nodes_updated', 0) or 0)} "
                f"rels={int(result.get('relationships_updated', 0) or 0)} "
                f"elapsed={duration:.1f}s"
            )
            return {
                "success": True,
                "request_id": f"local_incremental_{int(start)}",
                "nodes_updated": int(result.get("nodes_updated", 0) or 0),
                "relationships_updated": int(result.get("relationships_updated", 0) or 0),
                "duration_seconds": duration,
                "warnings": warnings,
            }
        except Exception as e:
            logger.error(f"Error in local incremental update: {e}")
            self._phase_log(f"INDEXING_INCREMENTAL_END status=failed error={e}")
            return {
                "success": False,
                "error": str(e),
                "nodes_updated": 0,
                "relationships_updated": 0,
            }

    def _run_impact_query_locally(
        self,
        repo_path: str,
        changed_files: List[str],
        impact_threshold: float,
        strategy: str,
    ) -> Dict[str, Any]:
        """Run impacted test query using local graph/coverage analyzers."""
        repo = Path(repo_path)
        strategy = str(strategy or "hybrid").strip().lower()

        if strategy == "coverage_diff":
            linker = TestLinker()
            tests = linker.get_impacted_tests_by_coverage(
                repo_path=repo,
                changed_files=changed_files,
                impact_threshold=impact_threshold,
                max_tests=int(getattr(config.analysis, "coverage_diff_max_tests", 200)),
            )
            warnings = linker.get_warnings()
            diagnostics = {
                "strategy_used": "coverage_diff",
                "coverage_diff_max_tests": int(getattr(config.analysis, "coverage_diff_max_tests", 200)),
                "coverage_max_test_files": int(getattr(config.analysis, "coverage_max_test_files", 0)),
                "coverage_timeout_seconds": int(getattr(config.analysis, "coverage_timeout_seconds", 0)),
                "coverage_max_files_per_test": int(
                    os.getenv("GRAPH_COVERAGE_MAX_FILES_PER_TEST", "20")
                ),
                "coverage_max_link_rows": int(getattr(config.analysis, "coverage_max_link_rows", 0)),
                "warnings": warnings,
            }
            return {"tests": tests, "warnings": warnings, "diagnostics": diagnostics}

        if strategy == "hybrid":
            graph_tests: List[Dict[str, Any]] = []
            coverage_tests: List[Dict[str, Any]] = []
            warnings: List[str] = []
            diagnostics: Dict[str, Any] = {}

            graph_strategy = str(
                os.getenv("GRAPH_IMPACT_GRAPH_STRATEGY", "balanced")
            ).strip().lower()
            graph_error: Optional[str] = None
            coverage_error: Optional[str] = None

            analyzer = ImpactAnalyzer()
            try:
                graph_tests = analyzer.get_impacted_tests(
                    repo,
                    changed_files,
                    impact_threshold=impact_threshold,
                    strategy=graph_strategy,
                )
                diagnostics["graph"] = analyzer.get_last_diagnostics()
                warnings.extend(list(diagnostics["graph"].get("warnings", [])))
            except Exception as e:
                graph_error = str(e)
                warnings.append(f"Graph traversal impact failed: {graph_error}")

            linker = TestLinker()
            try:
                coverage_tests = linker.get_impacted_tests_by_coverage(
                    repo_path=repo,
                    changed_files=changed_files,
                    impact_threshold=impact_threshold,
                    max_tests=int(getattr(config.analysis, "coverage_diff_max_tests", 200)),
                )
                warnings.extend(linker.get_warnings())
            except Exception as e:
                coverage_error = str(e)
                warnings.append(f"Coverage-diff impact failed: {coverage_error}")

            if graph_error and coverage_error:
                raise RuntimeError(
                    "Hybrid impact analysis failed in both graph and coverage paths: "
                    f"graph={graph_error}; coverage={coverage_error}"
                )

            tests = _merge_impacted_tests(graph_tests, coverage_tests)
            hybrid_max_tests = max(
                1,
                int(os.getenv("GRAPH_IMPACT_HYBRID_MAX_TESTS", "300")),
            )
            tests = tests[:hybrid_max_tests]

            diagnostics.update(
                {
                    "strategy_used": "hybrid",
                    "graph_strategy": graph_strategy,
                    "graph_candidates": len(graph_tests),
                    "coverage_candidates": len(coverage_tests),
                    "merged_candidates": len(tests),
                    "coverage_diff_max_tests": int(getattr(config.analysis, "coverage_diff_max_tests", 200)),
                    "coverage_max_test_files": int(getattr(config.analysis, "coverage_max_test_files", 0)),
                    "coverage_timeout_seconds": int(getattr(config.analysis, "coverage_timeout_seconds", 0)),
                    "coverage_max_files_per_test": int(
                        os.getenv("GRAPH_COVERAGE_MAX_FILES_PER_TEST", "20")
                    ),
                    "coverage_max_link_rows": int(getattr(config.analysis, "coverage_max_link_rows", 0)),
                    "hybrid_max_tests": hybrid_max_tests,
                    "graph_error": graph_error,
                    "coverage_error": coverage_error,
                    "warnings": warnings,
                }
            )
            return {"tests": tests, "warnings": warnings, "diagnostics": diagnostics}

        analyzer = ImpactAnalyzer()
        tests = analyzer.get_impacted_tests(
            repo,
            changed_files,
            impact_threshold=impact_threshold,
            strategy=strategy,
        )
        diagnostics = analyzer.get_last_diagnostics()
        warnings = list(diagnostics.get("warnings", []))
        return {"tests": tests, "warnings": warnings, "diagnostics": diagnostics}

    def get_impacted_tests(
        self,
        repo_path: str,
        changed_files: List[str],
        impact_threshold: float = 0.1,
        strategy: Optional[str] = None,
        strict_graph_identity: bool = True,
        require_fresh_graph: bool = True,
    ) -> Dict:
        """Get impacted tests locally using graph + optional coverage strategies."""
        chosen_strategy = str(
            strategy or os.getenv("GRAPH_IMPACT_STRATEGY", "hybrid")
        ).strip()
        normalized_files = self._normalize_changed_files(repo_path, changed_files)
        resolved_repo_slug = self._resolve_repo_slug(repo_path)
        resolved_commit_sha = self._resolve_commit_sha(repo_path)
        resolved_repo_fingerprint = self._resolve_repo_fingerprint(
            repo_path,
            commit_sha=resolved_commit_sha,
        )
        expected_graph_identity = f"{resolved_repo_slug}@{resolved_commit_sha}"

        if not normalized_files:
            return {
                "success": True,
                "tests": [],
                "total_tests": 0,
                "message": "No changed Python files",
                "graph_id": expected_graph_identity,
                "graph_freshness": "unknown",
                "rebuild_triggered": False,
                "staleness_reason": "no_changed_python_files",
                "selection_confidence_summary": {"high": 0, "medium": 0, "low": 0},
            }

        try:
            self._phase_log(
                "IMPACT_STATUS_START "
                f"files={len(normalized_files)} strategy={chosen_strategy}"
            )
            status = self._get_graph_status(
                expected_graph_identity=expected_graph_identity,
                expected_repo_fingerprint=resolved_repo_fingerprint if require_fresh_graph else None,
                repo_path=repo_path,
                strict_graph_identity=strict_graph_identity,
            )
            self._phase_log(
                "IMPACT_STATUS_END "
                f"exists={bool(status.get('exists', False))} "
                f"fresh={bool(status.get('fresh', False))} "
                f"reason={status.get('staleness_reason', '') or '-'}"
            )
            rebuild_triggered = False
            staleness_reason = str(status.get("staleness_reason", ""))

            if not bool(status.get("exists", False)):
                logger.info("Graph missing for impacted test query, triggering local build")
                self._phase_log("IMPACT_REFRESH_START reason=missing_graph mode=full_build")
                build_result = self.build_graph(
                    repo_path=repo_path,
                    force_rebuild=False,
                    include_tests=True,
                    repo_slug=resolved_repo_slug,
                    commit_sha=resolved_commit_sha,
                )
                rebuild_triggered = bool(build_result.get("success", False))
            elif require_fresh_graph and not bool(status.get("fresh", False)):
                logger.info(
                    "Graph stale for impacted test query (%s), attempting local incremental refresh",
                    staleness_reason or "unknown",
                )
                self._phase_log(
                    "IMPACT_REFRESH_START "
                    f"reason={staleness_reason or 'stale_graph'} mode=incremental"
                )
                update_result = self.incremental_update(
                    repo_path=repo_path,
                    changed_files=normalized_files,
                    base_commit="HEAD",
                    include_tests=True,
                    repo_slug=resolved_repo_slug,
                    commit_sha=resolved_commit_sha,
                    repo_fingerprint=resolved_repo_fingerprint,
                )
                rebuild_triggered = bool(update_result.get("success", False))
                if not rebuild_triggered:
                    logger.warning("Local incremental refresh failed; forcing full graph rebuild")
                    self._phase_log("IMPACT_REFRESH_RETRY reason=incremental_failed mode=full_build")
                    build_result = self.build_graph(
                        repo_path=repo_path,
                        force_rebuild=True,
                        include_tests=True,
                        repo_slug=resolved_repo_slug,
                        commit_sha=resolved_commit_sha,
                    )
                    rebuild_triggered = bool(build_result.get("success", False))

            self._phase_log(
                "IMPACT_QUERY_START "
                f"files={len(normalized_files)} strategy={chosen_strategy}"
            )
            local_result = self._run_impact_query_locally(
                repo_path=repo_path,
                changed_files=normalized_files,
                impact_threshold=impact_threshold,
                strategy=chosen_strategy,
            )
            tests = list(local_result.get("tests", []) or [])
            diagnostics = dict(local_result.get("diagnostics", {}) or {})
            warnings = list(local_result.get("warnings", []) or [])
            self._phase_log(
                "IMPACT_QUERY_END "
                f"selected={len(tests)} warnings={len(warnings)}"
            )

            summary = {
                "high": sum(1 for t in tests if float(t.get("impact_score", 0.0)) >= 0.8),
                "medium": sum(1 for t in tests if 0.5 <= float(t.get("impact_score", 0.0)) < 0.8),
                "low": sum(1 for t in tests if float(t.get("impact_score", 0.0)) < 0.5),
            }
            post_status = status
            if rebuild_triggered:
                self._phase_log("IMPACT_STATUS_RECHECK_START reason=rebuild_triggered")
                post_status = self._get_graph_status(
                    expected_graph_identity=expected_graph_identity,
                    expected_repo_fingerprint=resolved_repo_fingerprint if require_fresh_graph else None,
                    repo_path=repo_path,
                    strict_graph_identity=strict_graph_identity,
                )
                self._phase_log(
                    "IMPACT_STATUS_RECHECK_END "
                    f"exists={bool(post_status.get('exists', False))} "
                    f"fresh={bool(post_status.get('fresh', False))} "
                    f"reason={post_status.get('staleness_reason', '') or '-'}"
                )
            return {
                "success": True,
                "tests": tests,
                "total_tests": len(tests),
                "warnings": warnings,
                "diagnostics": diagnostics,
                "graph_id": str(post_status.get("graph_identity") or expected_graph_identity),
                "graph_freshness": (
                    "fresh"
                    if bool(post_status.get("fresh", False))
                    else ("stale" if bool(post_status.get("exists", False)) else "missing")
                ),
                "rebuild_triggered": rebuild_triggered,
                "staleness_reason": staleness_reason,
                "selection_confidence_summary": summary,
            }
        except Exception as e:
            self._phase_log(f"IMPACT_QUERY_END status=error error={e}")
            logger.error(f"Error running local impacted test query: {e}")
            return {
                "success": False,
                "error": str(e),
                "tests": [],
                "total_tests": 0,
                "graph_id": expected_graph_identity,
                "graph_freshness": "unknown",
                "rebuild_triggered": False,
                "staleness_reason": "request_error",
                "selection_confidence_summary": {"high": 0, "medium": 0, "low": 0},
            }

    def run_tests(
        self,
        repo_path: str,
        tests: Optional[List[str]] = None,
        pytest_args: Optional[List[str]] = None,
    ) -> Dict:
        """Run tests locally using TestRunner."""
        runner = TestRunner()
        result = runner.run_tests(
            repo_path=Path(repo_path),
            tests=tests,
            pytest_args=pytest_args or [],
        )
        tests_run = int(result.get("passed", 0) or 0) + int(result.get("failed", 0) or 0)
        if tests and tests_run > 0:
            self.record_targeted_test_coverage(
                repo_path=repo_path,
                tests=list(tests),
            )
        return result

    def record_targeted_test_coverage(
        self,
        *,
        repo_path: str,
        tests: List[str],
    ) -> Dict[str, Any]:
        """Persist bounded coverage links for already-selected targeted tests."""
        if not tests:
            return {
                "success": True,
                "links_created": 0,
                "tests_considered": 0,
                "warnings": [],
            }
        linker = TestLinker()
        try:
            return linker.link_selected_tests_by_coverage(
                repo_path=Path(repo_path),
                tests=list(tests),
            )
        except Exception as e:
            logger.warning(f"Targeted coverage ingestion failed: {e}")
            return {
                "success": False,
                "links_created": 0,
                "tests_considered": len(tests),
                "warnings": [str(e)],
            }

    def get_stats(self) -> Dict:
        """Get local graph stats from Neo4j."""
        try:
            stats = get_db().get_stats()
            return {"success": True, **stats}
        except Exception as e:
            logger.error(f"Error getting local graph stats: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    def clear_database(self) -> Dict:
        """Clear Neo4j graph data and local cache."""
        try:
            get_db().clear_database()
            self._indexed_graph_identities.clear()
            return {
                "success": True,
                "message": "Database cleared successfully",
            }
        except Exception as e:
            logger.error(f"Error clearing local graph DB: {e}")
            return {
                "success": False,
                "error": str(e),
            }
