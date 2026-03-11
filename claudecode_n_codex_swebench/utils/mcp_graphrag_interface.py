"""
MCP GraphRAG Interface - Client for GraphRAG MCP Server

This interface provides a client to interact with the GraphRAG MCP server
for test impact analysis. It follows the pattern established by claude_interface.py.
"""
import logging
import hashlib
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


class GraphRAGMCPInterface:
    """
    Client interface for GraphRAG MCP server

    Manages server lifecycle and provides high-level methods for:
    - Building code-test dependency graphs
    - Analyzing test impact from code changes
    - Running targeted tests
    """

    def __init__(self, server_url: str = "http://localhost:8080"):
        """
        Initialize MCP interface

        Args:
            server_url: URL of the MCP server
        """
        self.server_url = server_url
        self.server_process: Optional[subprocess.Popen] = None
        self._indexed_graph_identities: Dict[str, Dict[str, str]] = {}
        self._last_graph_status: Dict[str, object] = {}
        self._verify_server()

    def _verify_server(self):
        """Check if server is running, start if not"""
        try:
            response = requests.get(f"{self.server_url}/ready", timeout=2)
            if response.status_code == 200 and bool(response.json().get("ready", False)):
                logger.info(f"GraphRAG MCP server is running at {self.server_url}")
                return
            # Fallback to health endpoint for backward compatibility.
            response = requests.get(f"{self.server_url}/health", timeout=2)
            if response.status_code == 200:
                logger.info(f"GraphRAG MCP server health endpoint reachable at {self.server_url}")
                return
        except requests.RequestException:
            pass

        # Server not running, try to start it
        logger.info("GraphRAG MCP server not running, attempting to start...")
        self._start_server()

    def _start_server(self):
        """Start the MCP server"""
        try:
            # Get path to the package directory (parent of mcp_server)
            package_dir = Path(__file__).parent.parent

            # Verify the mcp_server package exists
            mcp_server_dir = package_dir / "mcp_server"
            if not mcp_server_dir.exists():
                raise RuntimeError(f"MCP server package not found: {mcp_server_dir}")

            # Start server as a module (to support relative imports)
            env = dict(os.environ)
            env["PYTHONUNBUFFERED"] = "1"
            self.server_process = subprocess.Popen(
                ["python", "-m", "mcp_server.server"],
                cwd=str(package_dir),  # Run from package directory
                stdout=None,
                stderr=None,
                text=True,
                env=env,
            )

            # Wait for server to be ready
            logger.info("Waiting for server to start...")
            for i in range(60):  # Wait up to 60 seconds
                try:
                    response = requests.get(f"{self.server_url}/ready", timeout=1)
                    if response.status_code == 200 and bool(response.json().get("ready", False)):
                        logger.info("GraphRAG MCP server started successfully")
                        return
                    response = requests.get(f"{self.server_url}/health", timeout=1)
                    if response.status_code == 200:
                        logger.info("GraphRAG MCP server started (health reachable)")
                        return
                except requests.RequestException:
                    pass

                time.sleep(1)

            raise RuntimeError("Server failed to start within 60 seconds")

        except Exception as e:
            logger.error(f"Failed to start MCP server: {e}")
            raise

    def stop_server(self):
        """Stop the MCP server if it was started by this interface"""
        if self.server_process:
            logger.info("Stopping MCP server...")
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=10)
                logger.info("MCP server stopped")
            except subprocess.TimeoutExpired:
                logger.warning("Server did not stop gracefully, killing...")
                self.server_process.kill()
            self.server_process = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop_server()

    def _phase_log(self, message: str) -> None:
        """Emit phase logs to logger and console."""
        line = f"[GraphRAG] {message}"
        logger.info(line)
        print(line, flush=True)

    def _post_with_heartbeat(
        self,
        endpoint: str,
        payload: Dict,
        *,
        timeout: int,
        phase_label: str,
        heartbeat_seconds: int = 20,
    ) -> requests.Response:
        """Run blocking POST with periodic status heartbeats."""
        start = time.time()
        self._phase_log(f"{phase_label}: start")
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                requests.post,
                f"{self.server_url}{endpoint}",
                json=payload,
                timeout=timeout,
            )
            while True:
                try:
                    response = future.result(timeout=heartbeat_seconds)
                    elapsed = time.time() - start
                    self._phase_log(
                        f"{phase_label}: end status={response.status_code} elapsed={elapsed:.1f}s"
                    )
                    return response
                except FutureTimeout:
                    elapsed = time.time() - start
                    meta = self._get_graph_meta()
                    if meta.get("success"):
                        self._phase_log(
                            f"{phase_label}: in_progress elapsed={elapsed:.1f}s "
                            f"graph_identity={meta.get('graph_identity', '')} "
                            f"nodes={int(meta.get('total_nodes', 0) or 0)}"
                        )
                    else:
                        self._phase_log(f"{phase_label}: in_progress elapsed={elapsed:.1f}s")

    def _request_with_retry(
        self,
        method: str,
        endpoint: str,
        *,
        json_payload: Optional[Dict] = None,
        timeout: int = 5,
        attempts: int = 4,
        base_backoff: float = 0.5,
        phase_label: str = "",
    ) -> requests.Response:
        """Request helper with bounded retries and exponential backoff."""
        last_error: Optional[Exception] = None
        url = f"{self.server_url}{endpoint}"
        for attempt in range(1, max(1, attempts) + 1):
            try:
                upper_method = method.upper()
                if upper_method == "GET":
                    response = requests.get(url, timeout=timeout)
                elif upper_method == "POST":
                    response = requests.post(url, json=json_payload, timeout=timeout)
                else:
                    response = requests.request(
                        upper_method,
                        url,
                        json=json_payload,
                        timeout=timeout,
                    )
                if response.status_code >= 500:
                    raise requests.RequestException(
                        f"{method.upper()} {endpoint} server_error={response.status_code}"
                    )
                return response
            except requests.RequestException as e:
                last_error = e
                if attempt >= attempts:
                    break
                sleep_for = base_backoff * (2 ** (attempt - 1))
                if phase_label:
                    self._phase_log(
                        f"{phase_label}: transient_error attempt={attempt}/{attempts} "
                        f"sleep={sleep_for:.1f}s error={e}"
                    )
                time.sleep(min(8.0, sleep_for))
        raise requests.RequestException(str(last_error) if last_error else "request_failed")

    def _poll_build_job(
        self,
        *,
        job_id: str,
        expected_graph_identity: str,
        timeout_seconds: int,
    ) -> Dict:
        """Poll async build job status with heartbeat logging and timeout resilience."""
        start = time.time()
        deadline = start + timeout_seconds
        poll_interval = max(1.0, float(os.getenv("GRAPH_STATUS_POLL_INTERVAL_SEC", "2")))
        max_interval = 10.0
        consecutive_status_failures = 0
        last_stage = ""
        last_progress = -1.0
        last_log_ts = 0.0
        degraded_logged = False

        while True:
            now = time.time()
            if now >= deadline:
                raise requests.RequestException(
                    f"build_job_timeout:{job_id}:>{timeout_seconds}s"
                )

            try:
                prev_stage = last_stage
                prev_progress = last_progress
                status_resp = self._request_with_retry(
                    "GET",
                    f"/jobs/build_code_graph/{job_id}",
                    timeout=6,
                    attempts=2,
                    base_backoff=0.3,
                    phase_label="INDEXING_STATUS",
                )
                if status_resp.status_code == 404:
                    raise RuntimeError("job_endpoint_missing")
                status_resp.raise_for_status()
                status = status_resp.json()
                consecutive_status_failures = 0

                job_status = str(status.get("status", "unknown"))
                stage = str(status.get("stage", "unknown"))
                progress_pct = float(status.get("progress_pct", 0.0) or 0.0)
                files_done = int(status.get("files_done", 0) or 0)
                files_total = int(status.get("files_total", 0) or 0)
                nodes_written = int(status.get("nodes_written", 0) or 0)
                edges_written = int(status.get("edges_written", 0) or 0)
                elapsed = float(status.get("elapsed_sec", time.time() - start) or 0.0)

                should_log = (
                    stage != last_stage
                    or int(progress_pct) != int(last_progress)
                    or (now - last_log_ts) >= 15.0
                )
                if should_log:
                    self._phase_log(
                        "INDEXING_PROGRESS "
                        f"status={job_status} stage={stage} progress={progress_pct:.1f}% "
                        f"files={files_done}/{files_total} nodes={nodes_written} "
                        f"edges={edges_written} elapsed={elapsed:.1f}s "
                        f"graph_identity={expected_graph_identity}"
                    )
                    last_stage = stage
                    last_progress = progress_pct
                    last_log_ts = now

                if job_status == "completed":
                    result = dict(status.get("result") or {})
                    if not result:
                        result = {
                            "success": True,
                            "request_id": job_id,
                            "nodes_created": nodes_written,
                            "relationships_created": edges_written,
                            "duration_seconds": elapsed,
                            "graph_id": expected_graph_identity,
                        }
                    return result

                if job_status == "failed":
                    raise requests.RequestException(
                        f"build_job_failed:{status.get('error', 'unknown_error')}"
                    )

                # Adaptive backoff when no visible progress, otherwise reset cadence.
                if stage == prev_stage and int(progress_pct) == int(prev_progress):
                    poll_interval = min(max_interval, poll_interval * 1.25)
                else:
                    poll_interval = max(1.0, float(os.getenv("GRAPH_STATUS_POLL_INTERVAL_SEC", "2")))

            except requests.RequestException as e:
                consecutive_status_failures += 1
                if consecutive_status_failures >= 3 and not degraded_logged:
                    self._phase_log(
                        "INDEXING_STATUS degraded: repeated timeout/failure on status endpoint; "
                        "continuing with reduced polling cadence"
                    )
                    degraded_logged = True
                self._phase_log(f"INDEXING_STATUS transient_error consecutive={consecutive_status_failures} error={e}")
                poll_interval = min(20.0, poll_interval * 1.5)

            time.sleep(poll_interval)

    # ========================================================================
    # High-level API Methods
    # ========================================================================

    def _resolve_repo_slug(self, repo_path: str, repo_slug: Optional[str] = None) -> str:
        """Resolve stable repo identity (owner/repo) from explicit slug or git remote."""
        if repo_slug:
            return repo_slug
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                remote_url = result.stdout.strip()
                if remote_url.endswith(".git"):
                    remote_url = remote_url[:-4]
                if remote_url.startswith("git@"):
                    path_part = remote_url.split(":", 1)[-1]
                elif "://" in remote_url:
                    host_and_path = remote_url.split("://", 1)[-1]
                    path_part = host_and_path.split("/", 1)[-1]
                else:
                    path_part = remote_url
                parts = [p for p in path_part.strip("/").split("/") if p]
                if len(parts) >= 2:
                    return f"{parts[-2]}/{parts[-1]}"
        except Exception as e:
            logger.debug(f"Failed to resolve repo slug from remote: {e}")
        return Path(repo_path).name

    def _resolve_commit_sha(self, repo_path: str, commit_sha: Optional[str] = None) -> str:
        """Resolve full commit SHA from explicit value or repo HEAD."""
        if commit_sha:
            return commit_sha
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception as e:
            logger.debug(f"Failed to resolve commit sha: {e}")
        return "unknown"

    def _resolve_repo_fingerprint(
        self,
        repo_path: str,
        commit_sha: Optional[str] = None,
    ) -> str:
        """Resolve repo fingerprint as commit + working tree state hash."""
        resolved_commit = self._resolve_commit_sha(repo_path, commit_sha=commit_sha)
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return f"{resolved_commit}:unknown"
            dirty = result.stdout.strip()
            dirty_hash = hashlib.sha1(dirty.encode("utf-8")).hexdigest()[:12] if dirty else "clean"
            return f"{resolved_commit}:{dirty_hash}"
        except Exception as e:
            logger.debug(f"Failed to resolve repo fingerprint: {e}")
            return f"{resolved_commit}:unknown"

    def _get_repo_cache_key(
        self,
        repo_path: str,
        repo_slug: Optional[str] = None,
        commit_sha: Optional[str] = None,
    ) -> str:
        """
        Generate a stable graph cache key by repo slug + commit + fingerprint.
        """
        resolved_repo = self._resolve_repo_slug(repo_path, repo_slug=repo_slug)
        resolved_commit = self._resolve_commit_sha(repo_path, commit_sha=commit_sha)
        repo_fingerprint = self._resolve_repo_fingerprint(repo_path, commit_sha=resolved_commit)
        cache_key = f"{resolved_repo}@{resolved_commit}#{repo_fingerprint}"
        logger.debug(f"Generated cache key: {cache_key}")
        return cache_key

    def _normalize_changed_files(self, repo_path: str, changed_files: List[str]) -> List[str]:
        """Normalize changed files to unique repo-relative Python paths."""
        repo_root = Path(repo_path).resolve()
        normalized: List[str] = []
        seen: set[str] = set()

        for raw_path in changed_files:
            if not raw_path:
                continue
            candidate = Path(raw_path)
            if candidate.is_absolute():
                try:
                    rel_path = str(candidate.resolve().relative_to(repo_root))
                except ValueError:
                    logger.debug(f"Skipping out-of-repo changed path: {raw_path}")
                    continue
            else:
                rel_path = str(candidate)

            if not rel_path.endswith(".py"):
                continue

            if rel_path not in seen:
                seen.add(rel_path)
                normalized.append(rel_path)

        return normalized

    def _get_graph_meta(self) -> Dict:
        """Fetch graph metadata from server."""
        try:
            response = self._request_with_retry(
                "GET",
                "/graph/meta",
                timeout=4,
                attempts=3,
                base_backoff=0.4,
                phase_label="GRAPH_META",
            )
            if response.status_code == 200:
                return response.json()
        except requests.RequestException:
            pass
        return self.get_stats()

    def _get_graph_status(
        self,
        *,
        expected_graph_identity: str,
        expected_repo_fingerprint: Optional[str] = None,
        repo_path: Optional[str] = None,
        strict_graph_identity: bool = True,
    ) -> Dict[str, object]:
        """Get graph availability/freshness status."""
        status: Dict[str, object] = {
            "exists": False,
            "fresh": False,
            "staleness_reason": "missing_graph",
            "graph_identity": "",
            "repo_fingerprint": "",
            "graph_version": "",
            "total_nodes": 0,
        }
        try:
            stats = self._get_graph_meta()
            if not stats.get("success", False):
                status["staleness_reason"] = "metadata_unavailable"
                return status

            node_count = int(stats.get("total_nodes", 0) or 0)
            indexed_identity = str(stats.get("graph_identity", "") or "")
            indexed_fingerprint = str(stats.get("repo_fingerprint", "") or "")
            path_format = str(stats.get("path_format", "") or "")

            status.update(
                {
                    "graph_identity": indexed_identity,
                    "repo_fingerprint": indexed_fingerprint,
                    "graph_version": str(stats.get("graph_version", "") or ""),
                    "total_nodes": node_count,
                }
            )

            if node_count <= 0:
                status["staleness_reason"] = "empty_graph"
                return status
            if path_format and path_format != "relative":
                status["staleness_reason"] = "path_format_not_relative"
                return status

            identity_match = indexed_identity == expected_graph_identity
            if strict_graph_identity and not identity_match:
                status["staleness_reason"] = "graph_identity_mismatch"
                return status
            if (not strict_graph_identity) and (not identity_match):
                if (not repo_path) or str(stats.get("last_indexed_repo", "")) != repo_path:
                    status["staleness_reason"] = "repo_path_mismatch"
                    return status

            status["exists"] = True
            if expected_repo_fingerprint:
                if indexed_fingerprint == expected_repo_fingerprint:
                    status["fresh"] = True
                    status["staleness_reason"] = ""
                else:
                    status["fresh"] = False
                    status["staleness_reason"] = "repo_fingerprint_mismatch"
            else:
                status["fresh"] = True
                status["staleness_reason"] = ""
            return status
        except Exception as e:
            logger.debug(f"Cache check failed: {e}")
            status["staleness_reason"] = f"cache_check_failed:{e}"
            return status

    def _check_graph_exists(
        self,
        cache_key: str,
        repo_path: Optional[str] = None,
        strict_graph_identity: bool = True,
        require_fresh_graph: bool = False,
        expected_repo_fingerprint: Optional[str] = None,
    ) -> bool:
        """
        Backward-compatible boolean graph existence check.

        Args:
            cache_key: Stable identity key "repo_slug@commit"
            repo_path: Repository path fallback for compatibility
            strict_graph_identity: Require exact graph identity match
            require_fresh_graph: Require repo fingerprint match
            expected_repo_fingerprint: Optional repo fingerprint to validate freshness
        """
        status = self._get_graph_status(
            expected_graph_identity=cache_key,
            expected_repo_fingerprint=expected_repo_fingerprint,
            repo_path=repo_path,
            strict_graph_identity=strict_graph_identity,
        )
        self._last_graph_status = status
        if not bool(status.get("exists", False)):
            return False
        if require_fresh_graph and not bool(status.get("fresh", False)):
            return False
        return True

    def build_graph(
        self,
        repo_path: str,
        force_rebuild: bool = False,
        include_tests: bool = True,
        repo_slug: Optional[str] = None,
        commit_sha: Optional[str] = None,
    ) -> Dict:
        """
        Build code-test dependency graph for a repository

        Args:
            repo_path: Path to repository to index
            force_rebuild: Force full rebuild even if index exists
            include_tests: Include test file analysis
            repo_slug: Optional stable repository slug (e.g., owner/repo)
            commit_sha: Optional full commit SHA

        Returns:
            Dict with build results
        """
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
        logger.info(f"Building graph for: {repo_path} (cache_key: {cache_key})")
        self._phase_log(
            "INDEXING_START "
            f"repo={resolved_repo_slug} commit={resolved_commit_sha[:8]} "
            f"force_rebuild={force_rebuild}"
        )

        # Check cache unless force_rebuild
        if not force_rebuild:
            if cache_key in self._indexed_graph_identities and self._check_graph_exists(
                expected_graph_identity,
                repo_path=repo_path,
                strict_graph_identity=True,
                require_fresh_graph=True,
                expected_repo_fingerprint=resolved_repo_fingerprint,
            ):
                logger.info(f"Using in-process cached graph for {cache_key}")
                self._phase_log(
                    "INDEXING_END status=cached source=in_process "
                    f"graph_identity={expected_graph_identity}"
                )
                stats = self.get_stats()
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
                logger.info(f"Using cached graph for {expected_graph_identity}")
                self._phase_log(
                    "INDEXING_END status=cached source=server "
                    f"graph_identity={expected_graph_identity}"
                )
                self._indexed_graph_identities[cache_key] = {
                    "graph_identity": expected_graph_identity,
                    "repo_fingerprint": resolved_repo_fingerprint,
                }
                stats = self.get_stats()
                return {
                    "success": True,
                    "cached": True,
                    "cache_key": cache_key,
                    "graph_identity": expected_graph_identity,
                    "repo_fingerprint": resolved_repo_fingerprint,
                    "nodes_created": stats.get("total_nodes", 0),
                    "relationships_created": stats.get("total_relationships", 0),
                }

        try:
            timeout_seconds = int(os.getenv("GRAPH_BUILD_TIMEOUT_SEC", "1800"))
            trigger_payload = {
                "repo_path": repo_path,
                "force_rebuild": force_rebuild,
                "include_tests": include_tests,
                "repo_slug": resolved_repo_slug,
                "commit_sha": resolved_commit_sha,
                "repo_fingerprint": resolved_repo_fingerprint,
                "async_mode": True,
            }
            self._phase_log(
                "INDEXING_TRIGGER "
                f"repo={resolved_repo_slug} commit={resolved_commit_sha[:8]} timeout={timeout_seconds}s"
            )
            trigger_response = self._request_with_retry(
                "POST",
                "/tools/build_code_graph",
                json_payload=trigger_payload,
                timeout=30,
                attempts=3,
                base_backoff=1.0,
                phase_label="INDEXING_TRIGGER",
            )
            trigger_response.raise_for_status()
            trigger_result = trigger_response.json()

            trigger_message = str(trigger_result.get("message", "") or "").lower()
            trigger_job_id = str(trigger_result.get("request_id", "") or "")
            looks_like_async = bool(
                bool(trigger_result.get("success", False))
                and
                trigger_job_id
                and (
                    "accepted" in trigger_message
                    or "build_job_" in trigger_message
                    or (
                        int(trigger_result.get("nodes_created", 0) or 0) == 0
                        and int(trigger_result.get("relationships_created", 0) or 0) == 0
                    )
                )
            )

            if looks_like_async:
                self._phase_log(
                    "INDEXING_START "
                    f"job_id={trigger_job_id} graph_identity={expected_graph_identity}"
                )
                try:
                    result = self._poll_build_job(
                        job_id=trigger_job_id,
                        expected_graph_identity=expected_graph_identity,
                        timeout_seconds=timeout_seconds,
                    )
                except RuntimeError as e:
                    # Older server without async job endpoint support: fall back to blocking request.
                    if "job_endpoint_missing" not in str(e):
                        raise
                    self._phase_log(
                        "INDEXING_STATUS job endpoint unavailable, falling back to blocking build request"
                    )
                    response = self._post_with_heartbeat(
                        "/tools/build_code_graph",
                        {
                            "repo_path": repo_path,
                            "force_rebuild": force_rebuild,
                            "include_tests": include_tests,
                            "repo_slug": resolved_repo_slug,
                            "commit_sha": resolved_commit_sha,
                            "repo_fingerprint": resolved_repo_fingerprint,
                            "async_mode": False,
                        },
                        timeout=timeout_seconds,
                        phase_label="INDEXING_PROGRESS",
                        heartbeat_seconds=20,
                    )
                    response.raise_for_status()
                    result = response.json()
            else:
                # Server executed synchronously and returned the final build result.
                result = trigger_result

            if result.get("success"):
                logger.info(f"Graph built: {result.get('nodes_created', 0)} nodes, "
                           f"{result.get('relationships_created', 0)} relationships")
                self._indexed_graph_identities[cache_key] = {
                    "graph_identity": expected_graph_identity,
                    "repo_fingerprint": resolved_repo_fingerprint,
                }
                result["cache_key"] = cache_key
                result["graph_identity"] = expected_graph_identity
                result["repo_fingerprint"] = resolved_repo_fingerprint
                self._phase_log(
                    "INDEXING_END status=success "
                    f"graph_identity={expected_graph_identity} "
                    f"nodes={result.get('nodes_created', 0)} "
                    f"rels={result.get('relationships_created', 0)}"
                )
            else:
                logger.error(f"Graph building failed: {result.get('error', 'Unknown error')}")
                self._phase_log(
                    "INDEXING_END status=failed "
                    f"error={result.get('error', 'Unknown error')}"
                )

            return result

        except (requests.RequestException, RuntimeError) as e:
            logger.error(f"Error calling build_graph: {e}")
            self._phase_log(f"INDEXING_END status=request_error error={e}")
            return {
                "success": False,
                "error": str(e),
                "nodes_created": 0,
                "relationships_created": 0,
                "cache_key": cache_key,
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
        """
        Incrementally update graph based on changed files

        Args:
            repo_path: Path to repository
            changed_files: List of changed files (or use git diff)
            base_commit: Git commit to compare against

        Returns:
            Dict with update results
        """
        logger.info(f"Updating graph for: {repo_path}")
        self._phase_log("INDEXING_INCREMENTAL_START")
        resolved_repo_slug = self._resolve_repo_slug(repo_path, repo_slug=repo_slug)
        resolved_commit_sha = self._resolve_commit_sha(repo_path, commit_sha=commit_sha)
        resolved_repo_fingerprint = repo_fingerprint or self._resolve_repo_fingerprint(
            repo_path,
            commit_sha=resolved_commit_sha,
        )

        try:
            response = self._post_with_heartbeat(
                "/tools/incremental_update",
                {
                    "repo_path": repo_path,
                    "changed_files": changed_files,
                    "base_commit": base_commit,
                    "include_tests": bool(include_tests),
                    "repo_slug": resolved_repo_slug,
                    "commit_sha": resolved_commit_sha,
                    "repo_fingerprint": resolved_repo_fingerprint,
                },
                timeout=int(os.getenv("GRAPH_INCREMENTAL_TIMEOUT_SEC", "900")),
                phase_label="INDEXING_INCREMENTAL_PROGRESS",
                heartbeat_seconds=15,
            )

            response.raise_for_status()
            result = response.json()

            if result.get("success"):
                logger.info(f"Graph updated: {result.get('nodes_updated', 0)} nodes, "
                           f"{result.get('relationships_updated', 0)} relationships")
                cache_key = self._get_repo_cache_key(
                    repo_path,
                    repo_slug=resolved_repo_slug,
                    commit_sha=resolved_commit_sha,
                )
                self._indexed_graph_identities[cache_key] = {
                    "graph_identity": f"{resolved_repo_slug}@{resolved_commit_sha}",
                    "repo_fingerprint": resolved_repo_fingerprint,
                }
                self._phase_log(
                    "INDEXING_INCREMENTAL_END status=success "
                    f"nodes={result.get('nodes_updated', 0)} "
                    f"rels={result.get('relationships_updated', 0)}"
                )
            else:
                logger.error(f"Graph update failed: {result.get('error', 'Unknown error')}")
                self._phase_log(
                    "INDEXING_INCREMENTAL_END status=failed "
                    f"error={result.get('error', 'Unknown error')}"
                )

            return result

        except requests.RequestException as e:
            logger.error(f"Error calling incremental_update: {e}")
            self._phase_log(f"INDEXING_INCREMENTAL_END status=request_error error={e}")
            return {
                "success": False,
                "error": str(e),
                "nodes_updated": 0,
                "relationships_updated": 0
            }

    def get_impacted_tests(
        self,
        repo_path: str,
        changed_files: List[str],
        impact_threshold: float = 0.1,
        strategy: Optional[str] = None,
        strict_graph_identity: bool = True,
        require_fresh_graph: bool = True,
    ) -> Dict:
        """
        Get tests impacted by code changes

        Args:
            repo_path: Path to repository
            changed_files: List of changed file paths
            impact_threshold: Minimum impact score (0-1)

        Returns:
            Dict with impacted tests
        """
        chosen_strategy = str(
            strategy or os.getenv("GRAPH_IMPACT_STRATEGY", "hybrid")
        ).strip()
        logger.info(
            "Finding impacted tests for %d changed files (strategy=%s)",
            len(changed_files),
            chosen_strategy,
        )
        normalized_files = self._normalize_changed_files(repo_path, changed_files)
        resolved_repo_slug = self._resolve_repo_slug(repo_path)
        resolved_commit_sha = self._resolve_commit_sha(repo_path)
        resolved_repo_fingerprint = self._resolve_repo_fingerprint(
            repo_path,
            commit_sha=resolved_commit_sha,
        )
        expected_graph_identity = f"{resolved_repo_slug}@{resolved_commit_sha}"

        if not normalized_files:
            logger.info("No changed Python files after normalization; skipping impact query")
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
            status = self._get_graph_status(
                expected_graph_identity=expected_graph_identity,
                expected_repo_fingerprint=resolved_repo_fingerprint if require_fresh_graph else None,
                repo_path=repo_path,
                strict_graph_identity=strict_graph_identity,
            )
            rebuild_triggered = False
            staleness_reason = str(status.get("staleness_reason", ""))

            if not bool(status.get("exists", False)):
                logger.info("Graph missing for impacted test query, triggering build")
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
                    "Graph stale for impacted test query (%s), attempting incremental refresh",
                    staleness_reason or "unknown",
                )
                update_result = self.incremental_update(
                    repo_path=repo_path,
                    changed_files=normalized_files,
                    base_commit="HEAD",
                    repo_slug=resolved_repo_slug,
                    commit_sha=resolved_commit_sha,
                    repo_fingerprint=resolved_repo_fingerprint,
                )
                rebuild_triggered = bool(update_result.get("success", False))
                if not rebuild_triggered:
                    logger.warning("Incremental refresh failed; forcing full graph rebuild")
                    build_result = self.build_graph(
                        repo_path=repo_path,
                        force_rebuild=True,
                        include_tests=True,
                        repo_slug=resolved_repo_slug,
                        commit_sha=resolved_commit_sha,
                    )
                    rebuild_triggered = bool(build_result.get("success", False))

            response = self._request_with_retry(
                "POST",
                "/tools/get_impacted_tests",
                json_payload={
                    "repo_path": repo_path,
                    "changed_files": normalized_files,
                    "impact_threshold": impact_threshold,
                    "strategy": chosen_strategy,
                },
                timeout=60,
                attempts=2,
                base_backoff=0.5,
                phase_label="IMPACT_QUERY",
            )

            response.raise_for_status()
            result = response.json()

            if result.get("success"):
                logger.info(f"Found {result.get('total_tests', 0)} impacted tests")
            else:
                logger.error(f"Impact analysis failed: {result.get('error', 'Unknown error')}")

            tests = list(result.get("tests", []) or [])
            summary = {
                "high": sum(1 for t in tests if float(t.get("impact_score", 0.0)) >= 0.8),
                "medium": sum(1 for t in tests if 0.5 <= float(t.get("impact_score", 0.0)) < 0.8),
                "low": sum(1 for t in tests if float(t.get("impact_score", 0.0)) < 0.5),
            }
            post_status = self._get_graph_status(
                expected_graph_identity=expected_graph_identity,
                expected_repo_fingerprint=resolved_repo_fingerprint if require_fresh_graph else None,
                repo_path=repo_path,
                strict_graph_identity=strict_graph_identity,
            )
            result["graph_id"] = str(
                result.get("graph_id")
                or post_status.get("graph_identity")
                or expected_graph_identity
            )
            result["graph_freshness"] = (
                "fresh"
                if bool(post_status.get("fresh", False))
                else ("stale" if bool(post_status.get("exists", False)) else "missing")
            )
            result["rebuild_triggered"] = rebuild_triggered
            result["staleness_reason"] = staleness_reason
            result["selection_confidence_summary"] = summary

            return result

        except requests.RequestException as e:
            logger.error(f"Error calling get_impacted_tests: {e}")
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
        pytest_args: Optional[List[str]] = None
    ) -> Dict:
        """
        Run tests and get results

        Args:
            repo_path: Path to repository
            tests: List of test identifiers to run (None = all)
            pytest_args: Additional pytest arguments

        Returns:
            Dict with test results
        """
        test_spec = f"{len(tests)} tests" if tests else "all tests"
        logger.info(f"Running {test_spec} for: {repo_path}")

        try:
            response = requests.post(
                f"{self.server_url}/tools/run_tests",
                json={
                    "repo_path": repo_path,
                    "tests": tests,
                    "pytest_args": pytest_args or []
                },
                timeout=600  # 10 minutes
            )

            response.raise_for_status()
            result = response.json()

            if result.get("success"):
                logger.info(f"Tests completed: {result.get('passed', 0)} passed, "
                           f"{result.get('failed', 0)} failed, "
                           f"{result.get('regressions', 0)} regressions")
            else:
                logger.error(f"Test execution failed: {result.get('error', 'Unknown error')}")

            return result

        except requests.RequestException as e:
            logger.error(f"Error calling run_tests: {e}")
            return {
                "success": False,
                "error": str(e),
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "regressions": 0,
                "test_results": []
            }

    def get_stats(self) -> Dict:
        """
        Get graph statistics

        Returns:
            Dict with graph stats
        """
        try:
            response = self._request_with_retry(
                "GET",
                "/stats",
                timeout=4,
                attempts=3,
                base_backoff=0.4,
                phase_label="GRAPH_STATS",
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Error getting stats: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def _normalize_test_nodeid(self, nodeid: str) -> str:
        """Normalize test nodeid for matching pytest outputs with impacted test IDs."""
        normalized = (nodeid or "").replace("\\", "/").strip()
        normalized = normalized.split("|", 1)[0]
        return re.sub(r"\[[^\]]+\]", "", normalized)

    def _build_test_identifier(self, impacted_test: Dict) -> Optional[str]:
        """Build pytest nodeid for an impacted test entry."""
        test_file = str(impacted_test.get("test_file") or "").strip().replace("\\", "/")
        test_name = str(impacted_test.get("test_name") or "").strip()
        if test_file and test_name:
            return f"{test_file}::{test_name}"

        full_name = str(impacted_test.get("full_name") or "").strip()
        if "::" in full_name:
            return full_name.replace("\\", "/")

        # Graph test ids are usually test::<file>::<name>:<line>
        test_id = str(impacted_test.get("test_id") or "").strip()
        if test_id.startswith("test::"):
            parts = test_id.split("::")
            if len(parts) >= 3:
                node_file = parts[1].replace("\\", "/")
                node_name = parts[2].split(":", 1)[0]
                if node_file and node_name:
                    return f"{node_file}::{node_name}"

        return None

    def _graph_useful_thresholds(self) -> tuple[int, float, float]:
        min_selected = 2
        min_ratio = 0.25
        min_precision = 0.30
        try:
            min_selected = max(1, int(os.getenv("GRAPH_USEFUL_MIN_SELECTED", "3")))
        except ValueError:
            pass
        try:
            min_ratio = max(0.0, min(1.0, float(os.getenv("GRAPH_USEFUL_MIN_RUNNABLE_RATIO", "0.35"))))
        except ValueError:
            pass
        try:
            min_precision = max(0.0, min(1.0, float(os.getenv("GRAPH_USEFUL_MIN_PRECISION_SCORE", "0.45"))))
        except ValueError:
            pass
        return min_selected, min_ratio, min_precision

    def _selection_precision_score(self, selected_tests: List[Dict]) -> float:
        if not selected_tests:
            return 0.0
        total = 0.0
        for test in selected_tests:
            confidence = test.get("confidence")
            if confidence is None:
                confidence = test.get("impact_score", 0.0)
            try:
                score = float(confidence or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            total += max(0.0, min(1.0, score))
        return max(0.0, min(1.0, total / max(len(selected_tests), 1)))

    def _evaluate_graph_precision_floor(
        self,
        *,
        selected_tests: List[Dict],
        runnable_count: int,
    ) -> tuple[bool, str, float, float]:
        selected_count = len(selected_tests)
        runnable_ratio = (float(runnable_count) / float(selected_count)) if selected_count > 0 else 0.0
        precision_score = self._selection_precision_score(selected_tests)
        min_selected, min_ratio, min_precision = self._graph_useful_thresholds()

        if selected_count <= 0:
            return False, "zero_selected", runnable_ratio, precision_score

        if selected_count >= min_selected:
            if runnable_ratio < min_ratio:
                return False, "low_runnable_ratio", runnable_ratio, precision_score
            if precision_score < min_precision:
                return False, "low_confidence", runnable_ratio, precision_score
            return True, "", runnable_ratio, precision_score

        high_conf_runnable = False
        for test in selected_tests:
            identifier = self._build_test_identifier(test)
            if not identifier:
                continue
            confidence = test.get("confidence")
            if confidence is None:
                confidence = test.get("impact_score", 0.0)
            try:
                conf_score = float(confidence or 0.0)
            except (TypeError, ValueError):
                conf_score = 0.0
            if conf_score >= 0.8:
                high_conf_runnable = True
                break

        if runnable_count > 0 and high_conf_runnable:
            return True, "", runnable_ratio, precision_score
        if runnable_count <= 0:
            return False, "no_runnable_nodeids", runnable_ratio, precision_score
        return False, "low_confidence", runnable_ratio, precision_score

    # ========================================================================
    # Convenience Methods
    # ========================================================================

    def analyze_and_run_impacted_tests(
        self,
        repo_path: str,
        changed_files: List[str],
        impact_threshold: float = 0.3,
        max_tests: int = 50,
        strategy: Optional[str] = None,
    ) -> Dict:
        """
        Analyze impact and run only the impacted tests

        This is the main workflow method that:
        1. Finds impacted tests
        2. Runs only those tests
        3. Reports regressions

        Args:
            repo_path: Path to repository
            changed_files: List of changed files
            impact_threshold: Minimum impact score
            max_tests: Maximum number of tests to run

        Returns:
            Dict with comprehensive results
        """
        logger.info(f"Analyzing impact and running tests for: {repo_path}")

        # Step 1: Get impacted tests
        impact_result = self.get_impacted_tests(
            repo_path,
            changed_files,
            impact_threshold,
            strategy=strategy,
        )

        if not impact_result.get("success"):
            return {
                "success": False,
                "error": "Failed to analyze impact",
                "impact_result": impact_result
            }

        impacted_tests = impact_result.get("tests", [])

        if not impacted_tests:
            logger.info("No impacted tests found")
            return {
                "success": True,
                "impacted_tests": 0,
                "tests_run": 0,
                "passed": 0,
                "failed": 0,
                "regressions": 0,
                "message": "No tests impacted by changes"
            }

        # Step 2: Select tests to run with confidence tiers
        top_tests = self._select_tiered_tests(impacted_tests, max_tests=max_tests)
        test_identifiers = [
            identifier
            for identifier in (self._build_test_identifier(test) for test in top_tests)
            if identifier
        ]

        logger.info(f"Running {len(test_identifiers)} impacted tests")

        # Step 3: Run tests
        test_result = self.run_tests(repo_path, test_identifiers)

        return {
            "success": test_result.get("success", False),
            "impacted_tests": len(impacted_tests),
            "tests_run": len(test_identifiers),
            "passed": test_result.get("passed", 0),
            "failed": test_result.get("failed", 0),
            "skipped": test_result.get("skipped", 0),
            "regressions": test_result.get("regressions", 0),
            "impact_result": impact_result,
            "test_result": test_result
        }

    def run_impacted_tests_iteratively(
        self,
        repo_path: str,
        changed_files: List[str],
        impact_threshold: float = 0.3,
        max_tests: int = 50,
        strategy: Optional[str] = None,
        require_fresh_graph: bool = True,
    ) -> Dict:
        """
        Run impacted tests and return structured results for iteration.

        This method is designed to support the iterative test-fix loop:
        1. Find impacted tests based on changed files
        2. Run those tests
        3. Return detailed failure information for the agent to fix
        4. Agent fixes failures
        5. Repeat

        Args:
            repo_path: Path to repository
            changed_files: List of changed file paths
            impact_threshold: Minimum impact score (0-1)
            max_tests: Maximum number of tests to run

        Returns:
            Dict with:
            - success: True if all tests pass
            - total_impacted: Number of tests identified as impacted
            - tests_run: Number of tests actually run
            - passed: Number of tests that passed
            - failed: Number of tests that failed
            - failed_tests: List of failed test details for agent
            - stdout: Test output
            - stderr: Test errors
        """
        logger.info(f"Running iterative test loop for: {repo_path}")

        # Get impacted tests
        impact_result = self.get_impacted_tests(
            repo_path,
            changed_files,
            impact_threshold,
            strategy=strategy,
            require_fresh_graph=require_fresh_graph,
        )

        if not impact_result.get("success"):
            return {
                "success": False,
                "error": "Failed to get impacted tests",
                "total_impacted": 0,
                "tests_run": 0,
                "selected_count": 0,
                "runnable_count": 0,
                "runnable_ratio": 0.0,
                "precision_score": 0.0,
                "precision_floor_passed": False,
                "graph_useful_signal": False,
                "graph_fallback_reason": "impact_query_failed",
                "passed": 0,
                "failed": 0,
                "failed_tests": [],
                "stdout": "",
                "stderr": impact_result.get("error", ""),
                "graph_freshness": impact_result.get("graph_freshness", "unknown"),
                "rebuild_triggered": impact_result.get("rebuild_triggered", False),
                "execution_reliable": False,
                "selection_confidence_summary": impact_result.get(
                    "selection_confidence_summary", {"high": 0, "medium": 0, "low": 0}
                ),
                "impact_query_success": False,
                "impact_error": impact_result.get("error", ""),
            }

        impacted_tests = impact_result.get("tests", [])

        if not impacted_tests:
            return {
                "success": True,
                "message": "No impacted tests found",
                "total_impacted": 0,
                "tests_run": 0,
                "selected_count": 0,
                "runnable_count": 0,
                "runnable_ratio": 0.0,
                "precision_score": 0.0,
                "precision_floor_passed": False,
                "graph_useful_signal": False,
                "graph_fallback_reason": "zero_selected",
                "passed": 0,
                "failed": 0,
                "failed_tests": [],
                "stdout": "",
                "stderr": "",
                "graph_freshness": impact_result.get("graph_freshness", "unknown"),
                "rebuild_triggered": impact_result.get("rebuild_triggered", False),
                "execution_reliable": True,
                "selection_confidence_summary": impact_result.get(
                    "selection_confidence_summary", {"high": 0, "medium": 0, "low": 0}
                ),
                "impact_query_success": True,
                "impact_error": "",
            }

        tests_to_run = self._select_tiered_tests(impacted_tests, max_tests=max_tests)
        selected_tests: List[Dict] = list(tests_to_run)
        test_identifiers: List[str] = []
        graph_fallback_reason = ""
        for impacted_test in tests_to_run:
            identifier = self._build_test_identifier(impacted_test)
            if not identifier:
                continue
            test_identifiers.append(identifier)

        # Fallback: if tiered selection produced no runnable nodeids, scan the
        # full impacted set and keep top runnable entries by impact score.
        if not test_identifiers and impacted_tests:
            fallback_runnable: List[Tuple[float, Dict, str]] = []
            seen_nodeids: set[str] = set()
            for impacted_test in impacted_tests:
                identifier = self._build_test_identifier(impacted_test)
                if not identifier:
                    continue
                normalized = self._normalize_test_nodeid(identifier)
                if normalized in seen_nodeids:
                    continue
                seen_nodeids.add(normalized)
                fallback_runnable.append(
                    (float(impacted_test.get("impact_score", 0.0) or 0.0), impacted_test, identifier)
                )

            fallback_runnable.sort(key=lambda row: row[0], reverse=True)
            for _, impacted_test, identifier in fallback_runnable[:max_tests]:
                test_identifiers.append(identifier)

            if test_identifiers:
                graph_fallback_reason = "no_runnable_nodeids_tiered_fallback"
                logger.info(
                    "Tiered impacted selection had no runnable nodeids; "
                    "fallback selected %d runnable tests",
                    len(test_identifiers),
                )

        logger.info(f"Running {len(test_identifiers)} impacted tests (of {len(impacted_tests)} total)")

        if not test_identifiers:
            _, precision_floor_reason, runnable_ratio, precision_score = self._evaluate_graph_precision_floor(
                selected_tests=selected_tests,
                runnable_count=0,
            )
            return {
                "success": False,
                "error": "No runnable pytest nodeids in impacted set",
                "total_impacted": len(impacted_tests),
                "tests_run": 0,
                "selected_count": len(selected_tests),
                "runnable_count": 0,
                "runnable_ratio": runnable_ratio,
                "precision_score": precision_score,
                "precision_floor_passed": False,
                "graph_useful_signal": False,
                "graph_fallback_reason": precision_floor_reason or graph_fallback_reason or "no_runnable_nodeids",
                "passed": 0,
                "failed": 0,
                "failed_tests": [],
                "stdout": "",
                "stderr": "No runnable pytest nodeids in impacted set",
                "graph_freshness": impact_result.get("graph_freshness", "unknown"),
                "rebuild_triggered": impact_result.get("rebuild_triggered", False),
                "execution_reliable": False,
                "selection_confidence_summary": impact_result.get(
                    "selection_confidence_summary", {"high": 0, "medium": 0, "low": 0}
                ),
                "impact_query_success": bool(impact_result.get("success", False)),
                "impact_error": impact_result.get("error", ""),
            }

        # Run tests
        test_result = self.run_tests(repo_path, test_identifiers)

        # Extract failure details for agent
        impact_by_nodeid: Dict[str, Dict] = {}
        for impacted in selected_tests:
            nodeid = self._build_test_identifier(impacted)
            if not nodeid:
                continue
            impact_by_nodeid[self._normalize_test_nodeid(nodeid)] = impacted

        failed_tests = []
        for result in test_result.get("test_results", []):
            if result.get("status") == "failed":
                candidate_nodeids = [
                    result.get("full_name", ""),
                    f"{result.get('file', '')}::{result.get('name', '')}",
                    result.get("name", ""),
                ]
                matched_impact = None
                for candidate in candidate_nodeids:
                    normalized = self._normalize_test_nodeid(str(candidate))
                    if normalized in impact_by_nodeid:
                        matched_impact = impact_by_nodeid[normalized]
                        break
                impact_score = float((matched_impact or {}).get("impact_score", 0.0))

                failed_tests.append({
                    "test_name": result.get("name"),
                    "test_file": result.get("file"),
                    "full_name": result.get("full_name"),
                    "error": result.get("error", ""),
                    "impact_score": impact_score,
                    "impact_reason": (matched_impact or {}).get("impact_reason", ""),
                })

        # Tests must have actually run successfully AND have no failures
        # If pytest fails to run (e.g., missing deps), success=False but failed=0
        test_execution_succeeded = test_result.get("success", False)
        no_failures = test_result.get("failed", 0) == 0
        all_passed = test_execution_succeeded and no_failures
        precision_floor_passed, precision_floor_reason, runnable_ratio, precision_score = (
            self._evaluate_graph_precision_floor(
                selected_tests=selected_tests,
                runnable_count=len(test_identifiers),
            )
        )
        graph_useful_signal = bool(precision_floor_passed and len(test_identifiers) > 0)
        if not graph_useful_signal and not graph_fallback_reason:
            graph_fallback_reason = precision_floor_reason

        return {
            "success": all_passed,
            "total_impacted": len(impacted_tests),
            "tests_run": len(test_identifiers),
            "selected_count": len(selected_tests),
            "runnable_count": len(test_identifiers),
            "runnable_ratio": runnable_ratio,
            "precision_score": precision_score,
            "precision_floor_passed": bool(precision_floor_passed),
            "graph_useful_signal": bool(graph_useful_signal),
            "graph_fallback_reason": str(graph_fallback_reason or ""),
            "passed": test_result.get("passed", 0),
            "failed": test_result.get("failed", 0),
            "skipped": test_result.get("skipped", 0),
            "failed_tests": failed_tests,
            "stdout": test_result.get("stdout", ""),
            "stderr": test_result.get("stderr", ""),
            "test_result": test_result,
            "graph_freshness": impact_result.get("graph_freshness", "unknown"),
            "rebuild_triggered": impact_result.get("rebuild_triggered", False),
            "execution_reliable": bool(test_execution_succeeded),
            "selection_confidence_summary": impact_result.get(
                "selection_confidence_summary", {"high": 0, "medium": 0, "low": 0}
            ),
            "impact_query_success": bool(impact_result.get("success", False)),
            "impact_error": impact_result.get("error", ""),
        }

    def _impacted_test_dedupe_key(self, impacted_test: Dict) -> str:
        """Build stable dedupe key while tolerating missing test_id."""
        test_id = str(impacted_test.get("test_id") or "").strip()
        if test_id:
            return f"id:{test_id}"

        test_file = str(impacted_test.get("test_file") or "").strip().replace("\\", "/")
        test_name = str(impacted_test.get("test_name") or "").strip()
        if test_file and test_name:
            return f"nodeid:{test_file}::{test_name}"

        full_name = str(impacted_test.get("full_name") or "").strip().replace("\\", "/")
        if "::" in full_name:
            return f"full:{self._normalize_test_nodeid(full_name)}"

        return ""

    def _select_tiered_tests(self, impacted_tests: List[Dict], max_tests: int) -> List[Dict]:
        """Prioritize high-confidence impacted tests before medium/low fallbacks."""
        if max_tests <= 0 or not impacted_tests:
            return []

        high = [t for t in impacted_tests if t.get("impact_score", 0) >= 0.8]
        medium = [t for t in impacted_tests if 0.5 <= t.get("impact_score", 0) < 0.8]
        low = [t for t in impacted_tests if t.get("impact_score", 0) < 0.5]

        for band in (high, medium, low):
            band.sort(
                key=lambda t: (
                    1 if self._build_test_identifier(t) else 0,
                    t.get("impact_score", 0.0),
                    t.get("line_change_count", 0),
                    t.get("test_id", ""),
                    t.get("test_name", ""),
                ),
                reverse=True,
            )

        selected: List[Dict] = []
        seen_ids: set[str] = set()
        for band in (high, medium, low):
            for test in band:
                dedupe_key = self._impacted_test_dedupe_key(test)
                if dedupe_key and dedupe_key in seen_ids:
                    continue
                selected.append(test)
                if dedupe_key:
                    seen_ids.add(dedupe_key)
                if len(selected) >= max_tests:
                    return selected

        return selected

    def clear_database(self) -> Dict:
        """
        Clear all data from the Neo4j database.

        This is useful for ensuring each experimental run starts with a clean state.
        Should be called at the beginning of a full benchmark run.

        Returns:
            Dict with operation results
        """
        logger.info("Clearing Neo4j database...")

        try:
            response = requests.post(
                f"{self.server_url}/tools/clear_database",
                timeout=60
            )

            response.raise_for_status()
            result = response.json()

            if result.get("success"):
                logger.info("Database cleared successfully")
                self._indexed_graph_identities.clear()
            else:
                logger.error(f"Database clearing failed: {result.get('error', 'Unknown error')}")

            return result

        except requests.RequestException as e:
            logger.error(f"Error calling clear_database: {e}")
            return {
                "success": False,
                "error": str(e)
            }
