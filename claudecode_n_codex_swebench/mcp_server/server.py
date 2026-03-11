"""
FastAPI MCP Server for GraphRAG Test Impact Analysis

This server provides MCP tools for:
- Building code-test dependency graphs
- Analyzing test impact from code changes
- Running targeted tests to prevent regressions
"""
import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .config import config

# Setup logging
logging.basicConfig(
    level=getattr(logging, config.server.log_level.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# Request/Response Models
# ============================================================================

class BuildGraphRequest(BaseModel):
    """Request to build code-test dependency graph"""
    repo_path: str = Field(..., description="Path to repository to index")
    force_rebuild: bool = Field(False, description="Force full rebuild even if index exists")
    include_tests: bool = Field(True, description="Include test file analysis")
    repo_slug: Optional[str] = Field(None, description="Stable repo slug (e.g., owner/repo)")
    commit_sha: Optional[str] = Field(None, description="Commit SHA for this graph index")
    repo_fingerprint: Optional[str] = Field(None, description="Repo fingerprint (commit + dirty hash)")
    async_mode: bool = Field(False, description="Queue build and return immediately")


class BuildGraphResponse(BaseModel):
    """Response from graph building"""
    request_id: str
    success: bool
    graph_id: str
    nodes_created: int
    relationships_created: int
    duration_seconds: float
    warnings: List[str] = Field(default_factory=list)
    message: Optional[str] = None
    error: Optional[str] = None


class BuildGraphJobStatusResponse(BaseModel):
    """Status response for queued graph build jobs."""
    success: bool
    job_id: str
    status: str
    stage: str
    progress_pct: float = 0.0
    files_done: int = 0
    files_total: int = 0
    nodes_written: int = 0
    edges_written: int = 0
    elapsed_sec: float = 0.0
    eta_sec: Optional[float] = None
    warnings: List[str] = Field(default_factory=list)
    message: Optional[str] = None
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None


class IncrementalUpdateRequest(BaseModel):
    """Request to update graph based on changes"""
    repo_path: str = Field(..., description="Path to repository")
    changed_files: Optional[List[str]] = Field(None, description="Specific files changed (or use git diff)")
    base_commit: Optional[str] = Field("HEAD", description="Git commit to compare against")
    include_tests: bool = Field(True, description="Re-link tests after incremental graph update")
    repo_slug: Optional[str] = Field(None, description="Stable repo slug (e.g., owner/repo)")
    commit_sha: Optional[str] = Field(None, description="Commit SHA for this graph index")
    repo_fingerprint: Optional[str] = Field(None, description="Repo fingerprint (commit + dirty hash)")


class IncrementalUpdateResponse(BaseModel):
    """Response from incremental update"""
    request_id: str
    success: bool
    nodes_updated: int
    relationships_updated: int
    duration_seconds: float
    warnings: List[str] = Field(default_factory=list)
    error: Optional[str] = None


class GetImpactedTestsRequest(BaseModel):
    """Request to get tests impacted by changes"""
    repo_path: str = Field(..., description="Path to repository")
    changed_files: List[str] = Field(..., description="List of changed file paths")
    impact_threshold: float = Field(0.1, description="Minimum impact score (0-1)")
    strategy: str = Field(
        "balanced",
        description=(
            "Impact strategy: conservative|balanced|aggressive|coverage_diff|hybrid "
            "(hybrid merges graph traversal and runtime coverage-diff)"
        ),
    )


class GetImpactedTestsResponse(BaseModel):
    """Response with impacted tests"""
    request_id: str
    success: bool
    tests: List[Dict[str, Any]] = Field(default_factory=list, description="List of impacted tests with scores")
    total_tests: int
    graph_id: Optional[str] = None
    graph_freshness: str = "unknown"
    warnings: List[str] = Field(default_factory=list)
    diagnostics: Dict[str, Any] = Field(default_factory=dict)
    message: Optional[str] = None
    error: Optional[str] = None


class RunTestsRequest(BaseModel):
    """Request to run tests"""
    repo_path: str = Field(..., description="Path to repository")
    tests: Optional[List[str]] = Field(None, description="Specific tests to run (None = all)")
    pytest_args: List[str] = Field(default_factory=list, description="Additional pytest arguments")


class RunTestsResponse(BaseModel):
    """Response from test execution"""
    request_id: str
    success: bool
    passed: int
    failed: int
    skipped: int
    regressions: int = Field(0, description="Number of previously passing tests that failed")
    duration_seconds: float
    test_results: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    error: Optional[str] = None


class ClearDatabaseResponse(BaseModel):
    """Response from database clearing"""
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None


class GraphStatsResponse(BaseModel):
    """Response with graph statistics"""
    success: bool
    total_nodes: int
    total_relationships: int
    files: int
    functions: int
    classes: int
    tests: int
    last_indexed_repo: Optional[str] = None
    path_format: Optional[str] = None
    repo_slug: Optional[str] = None
    last_indexed_commit: Optional[str] = None
    graph_identity: Optional[str] = None
    repo_fingerprint: Optional[str] = None
    build_mode: Optional[str] = None
    graph_version: Optional[str] = None
    symbol_identity_scheme: Optional[str] = None
    build_warnings_count: int = 0
    index_job_id: Optional[str] = None
    index_status: Optional[str] = None
    index_stage: Optional[str] = None
    progress_pct: float = 0.0
    files_done: int = 0
    files_total: int = 0
    nodes_written: int = 0
    edges_written: int = 0
    elapsed_sec: float = 0.0
    eta_sec: Optional[float] = None
    last_updated: Optional[datetime] = None
    error: Optional[str] = None


class GraphMetaResponse(BaseModel):
    """Response with graph metadata for cache/freshness validation."""
    success: bool
    graph_identity: Optional[str] = None
    repo_slug: Optional[str] = None
    last_indexed_commit: Optional[str] = None
    repo_fingerprint: Optional[str] = None
    graph_version: Optional[str] = None
    build_mode: Optional[str] = None
    symbol_identity_scheme: Optional[str] = None
    build_warnings_count: int = 0
    path_format: Optional[str] = None
    total_nodes: int = 0
    total_relationships: int = 0
    index_job_id: Optional[str] = None
    index_status: Optional[str] = None
    index_stage: Optional[str] = None
    progress_pct: float = 0.0
    files_done: int = 0
    files_total: int = 0
    nodes_written: int = 0
    edges_written: int = 0
    elapsed_sec: float = 0.0
    eta_sec: Optional[float] = None
    last_updated: Optional[datetime] = None
    error: Optional[str] = None


# ============================================================================
# Application Lifecycle
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for the FastAPI application"""
    logger.info("Starting GraphRAG MCP Server...")
    logger.info(f"Neo4j mode: {'embedded' if config.neo4j.use_embedded else 'standalone'}")
    logger.info(f"Embeddings: {config.embeddings.provider}/{config.embeddings.model}")

    # Initialize Neo4j connection
    try:
        from .graph_db import get_db, close_db
        db = get_db()

        # Verify connection by running a simple query
        with db.driver.session(database=config.neo4j.database) as session:
            result = session.run("RETURN 1 as num")
            _ = result.single()

        logger.info("Neo4j connection verified")

        # Ensure schema exists
        db.create_schema()
        logger.info("Neo4j schema verified")

    except Exception as e:
        logger.error(f"Failed to initialize Neo4j: {e}")
        logger.warning("Server starting without Neo4j - some features will not work")

    yield

    # Shutdown
    logger.info("Shutting down GraphRAG MCP Server...")
    try:
        from .graph_db import close_db
        close_db()
        logger.info("Neo4j connection closed")
    except Exception as e:
        logger.warning(f"Error closing Neo4j: {e}")


# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(
    title="TDAD GraphRAG MCP Server",
    description="Test Impact Analysis with GraphRAG for TDAD Thesis",
    version="0.1.0",
    lifespan=lifespan
)


# ============================================================================
# In-memory job and cache state
# ============================================================================

_state_lock = Lock()
_index_jobs: Dict[str, Dict[str, Any]] = {}
_active_build_jobs: Dict[str, str] = {}
_stats_cache: Dict[str, Any] = {"data": None, "expires_at": 0.0}
_stats_cache_ttl_seconds = float(max(1, int(config.graph_index.status_poll_interval_seconds or 2)))


def _build_graph_id(repo_path: Path, request: BuildGraphRequest) -> str:
    return f"{request.repo_slug or repo_path.name}@{request.commit_sha or 'unknown'}"


def _build_job_key(repo_path: Path, request: BuildGraphRequest) -> str:
    resolved_path = str(repo_path.resolve())
    resolved_commit = request.commit_sha or "HEAD"
    return f"{resolved_path}::{resolved_commit}"


def _job_eta_seconds(elapsed_sec: float, progress_pct: float) -> Optional[float]:
    if progress_pct <= 0.0 or progress_pct >= 100.0:
        return None
    remaining = elapsed_sec * ((100.0 / progress_pct) - 1.0)
    return max(0.0, float(remaining))


def _get_job_view(job: Dict[str, Any]) -> Dict[str, Any]:
    now = time.time()
    started_ts = float(job.get("started_ts") or now)
    ended_ts = float(job.get("ended_ts") or 0.0)
    is_done = bool(ended_ts)
    elapsed_sec = (ended_ts - started_ts) if is_done else (now - started_ts)
    progress_pct = float(job.get("progress_pct", 0.0) or 0.0)
    return {
        "success": True,
        "job_id": str(job.get("job_id", "")),
        "status": str(job.get("status", "unknown")),
        "stage": str(job.get("stage", "unknown")),
        "progress_pct": progress_pct,
        "files_done": int(job.get("files_done", 0) or 0),
        "files_total": int(job.get("files_total", 0) or 0),
        "nodes_written": int(job.get("nodes_written", 0) or 0),
        "edges_written": int(job.get("edges_written", 0) or 0),
        "elapsed_sec": max(0.0, float(elapsed_sec)),
        "eta_sec": _job_eta_seconds(max(0.0, float(elapsed_sec)), progress_pct),
        "warnings": list(job.get("warnings", []) or []),
        "message": job.get("message"),
        "error": job.get("error"),
        "result": job.get("result"),
    }


def _invalidate_stats_cache() -> None:
    with _state_lock:
        _stats_cache["expires_at"] = 0.0


def _get_stats_cached(force_refresh: bool = False) -> Dict[str, Any]:
    now = time.time()
    with _state_lock:
        if not force_refresh and _stats_cache.get("data") is not None and now < float(_stats_cache.get("expires_at", 0.0) or 0.0):
            return dict(_stats_cache["data"])

    from .graph_db import get_db

    db = get_db()
    stats = db.get_stats()
    with _state_lock:
        _stats_cache["data"] = dict(stats)
        _stats_cache["expires_at"] = now + _stats_cache_ttl_seconds
    return dict(stats)


def _current_active_job_view() -> Optional[Dict[str, Any]]:
    with _state_lock:
        active_jobs = [
            _index_jobs[job_id]
            for job_id in _active_build_jobs.values()
            if job_id in _index_jobs
        ]
        if not active_jobs:
            return None
        # Most recent running/queued job.
        active_jobs.sort(key=lambda item: float(item.get("created_ts", 0.0) or 0.0), reverse=True)
        return _get_job_view(active_jobs[0])


def _progress_callback_for_job(job_id: str) -> Callable[[Dict[str, Any]], None]:
    def _callback(update: Dict[str, Any]) -> None:
        with _state_lock:
            job = _index_jobs.get(job_id)
            if not job:
                return
            job["updated_ts"] = time.time()
            if "stage" in update:
                job["stage"] = str(update["stage"])
            if "progress_pct" in update:
                job["progress_pct"] = max(0.0, min(100.0, float(update["progress_pct"])))
            if "files_done" in update:
                job["files_done"] = int(update["files_done"] or 0)
            if "files_total" in update:
                job["files_total"] = int(update["files_total"] or 0)
            if "nodes_written" in update:
                job["nodes_written"] = int(update["nodes_written"] or 0)
            if "edges_written" in update:
                job["edges_written"] = int(update["edges_written"] or 0)
            if "message" in update:
                job["message"] = update["message"]
    return _callback


async def _run_build_graph_job(job_id: str, request: BuildGraphRequest, job_key: str) -> None:
    start_ts = time.time()
    with _state_lock:
        job = _index_jobs.get(job_id)
        if not job:
            return
        job["status"] = "running"
        job["stage"] = "starting"
        job["started_ts"] = start_ts
        job["updated_ts"] = start_ts
        job["message"] = "Indexing started"

    repo_path = Path(request.repo_path)
    try:
        from .graph_builder import GraphBuilder
        from .test_linker import TestLinker

        progress_callback = _progress_callback_for_job(job_id)
        builder = GraphBuilder()
        result = await asyncio.to_thread(
            builder.build_graph,
            repo_path=repo_path,
            force_rebuild=request.force_rebuild,
            repo_slug=request.repo_slug,
            commit_sha=request.commit_sha,
            repo_fingerprint=request.repo_fingerprint,
            progress_callback=progress_callback,
        )

        warnings: List[str] = []
        build_warnings = int(result.get("build_warnings_count", 0) or 0)
        if build_warnings > 0:
            warnings.append(f"Graph build completed with {build_warnings} ambiguous symbol resolutions")

        if request.include_tests:
            progress_callback(
                {
                    "stage": "link_tests",
                    "progress_pct": 97.0,
                    "message": "Linking tests",
                }
            )
            linker = TestLinker()
            test_links = await asyncio.to_thread(linker.link_tests, repo_path)
            warnings.extend(test_links.get("warnings", []))
            progress_callback(
                {
                    "stage": "link_tests",
                    "progress_pct": 99.0,
                    "message": f"Linked {test_links.get('total_links', 0)} test-code edges",
                }
            )

        duration = time.time() - start_ts
        response_payload = {
            "request_id": job_id,
            "success": True,
            "graph_id": _build_graph_id(repo_path, request),
            "nodes_created": int(result.get("nodes_created", 0) or 0),
            "relationships_created": int(result.get("relationships_created", 0) or 0),
            "duration_seconds": duration,
            "warnings": warnings,
            "message": f"Graph built successfully: {result.get('files_processed', 0)} files processed",
        }
        with _state_lock:
            job = _index_jobs.get(job_id)
            if job:
                job["status"] = "completed"
                job["stage"] = "completed"
                job["progress_pct"] = 100.0
                job["nodes_written"] = response_payload["nodes_created"]
                job["edges_written"] = response_payload["relationships_created"]
                job["warnings"] = warnings
                job["message"] = response_payload["message"]
                job["error"] = None
                job["result"] = response_payload
                job["updated_ts"] = time.time()
                job["ended_ts"] = time.time()
        _invalidate_stats_cache()
    except Exception as e:
        logger.error(f"Error in build graph job {job_id}: {e}")
        with _state_lock:
            job = _index_jobs.get(job_id)
            if job:
                job["status"] = "failed"
                job["stage"] = "failed"
                job["error"] = str(e)
                job["message"] = "Graph build failed"
                job["updated_ts"] = time.time()
                job["ended_ts"] = time.time()
    finally:
        with _state_lock:
            current = _active_build_jobs.get(job_key)
            if current == job_id:
                _active_build_jobs.pop(job_key, None)


# ============================================================================
# Health & Status Endpoints
# ============================================================================

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": "TDAD GraphRAG MCP Server",
        "version": "0.1.0",
        "status": "running",
        "docs": "/docs"
    }


@app.get("/health")
async def health():
    """Health check endpoint"""
    from .graph_db import get_db

    neo4j_connected = False
    error: Optional[str] = None
    try:
        db = get_db()
        neo4j_connected = db.check_connection()
    except Exception as e:
        error = str(e)

    status = "healthy" if neo4j_connected else "degraded"
    return {
        "status": status,
        "timestamp": datetime.now().isoformat(),
        "neo4j": "connected" if neo4j_connected else "disconnected",
        "embeddings": config.embeddings.provider,
        "error": error,
    }


@app.get("/ready")
async def ready():
    """Readiness check endpoint (strict DB + schema availability)."""
    from .graph_db import get_db

    try:
        db = get_db()
        if not db.check_connection():
            return {
                "ready": False,
                "status": "not_ready",
                "reason": "neo4j_disconnected",
                "timestamp": datetime.now().isoformat(),
            }
        db.create_schema()
        return {
            "ready": True,
            "status": "ready",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {
            "ready": False,
            "status": "not_ready",
            "reason": str(e),
            "timestamp": datetime.now().isoformat(),
        }


@app.get("/stats", response_model=GraphStatsResponse)
async def get_stats():
    """Get graph statistics"""
    try:
        stats = _get_stats_cached()
        by_type = stats.get("by_type", {})
        active_job = _current_active_job_view() or {}

        return GraphStatsResponse(
            success=True,
            total_nodes=int(stats.get("total_nodes", 0) or 0),
            total_relationships=int(stats.get("total_relationships", 0) or 0),
            files=int(by_type.get("File", 0) or 0),
            functions=int(by_type.get("Function", 0) or 0),
            classes=int(by_type.get("Class", 0) or 0),
            tests=int(by_type.get("Test", 0) or 0),
            last_indexed_repo=stats.get("last_indexed_repo"),
            path_format=stats.get("path_format"),
            repo_slug=stats.get("repo_slug"),
            last_indexed_commit=stats.get("last_indexed_commit"),
            graph_identity=stats.get("graph_identity"),
            repo_fingerprint=stats.get("repo_fingerprint"),
            build_mode=stats.get("build_mode"),
            graph_version=stats.get("graph_version"),
            symbol_identity_scheme=stats.get("symbol_identity_scheme"),
            build_warnings_count=int(stats.get("build_warnings_count", 0) or 0),
            index_job_id=active_job.get("job_id"),
            index_status=active_job.get("status"),
            index_stage=active_job.get("stage"),
            progress_pct=float(active_job.get("progress_pct", 0.0) or 0.0),
            files_done=int(active_job.get("files_done", 0) or 0),
            files_total=int(active_job.get("files_total", 0) or 0),
            nodes_written=int(active_job.get("nodes_written", 0) or 0),
            edges_written=int(active_job.get("edges_written", 0) or 0),
            elapsed_sec=float(active_job.get("elapsed_sec", 0.0) or 0.0),
            eta_sec=(
                float(active_job.get("eta_sec"))
                if active_job.get("eta_sec") is not None
                else None
            ),
            last_updated=stats.get("last_updated"),
        )
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return GraphStatsResponse(
            success=False,
            total_nodes=0,
            total_relationships=0,
            files=0,
            functions=0,
            classes=0,
            tests=0,
            last_indexed_repo=None,
            path_format=None,
            repo_slug=None,
            last_indexed_commit=None,
            graph_identity=None,
            repo_fingerprint=None,
            build_mode=None,
            graph_version=None,
            symbol_identity_scheme=None,
            build_warnings_count=0,
            index_job_id=None,
            index_status=None,
            index_stage=None,
            progress_pct=0.0,
            files_done=0,
            files_total=0,
            nodes_written=0,
            edges_written=0,
            elapsed_sec=0.0,
            eta_sec=None,
            error=str(e)
        )


@app.get("/graph/meta", response_model=GraphMetaResponse)
async def get_graph_meta():
    """Expose graph metadata for identity/freshness checks."""
    try:
        stats = _get_stats_cached()
        active_job = _current_active_job_view() or {}
        return GraphMetaResponse(
            success=True,
            graph_identity=stats.get("graph_identity"),
            repo_slug=stats.get("repo_slug"),
            last_indexed_commit=stats.get("last_indexed_commit"),
            repo_fingerprint=stats.get("repo_fingerprint"),
            graph_version=stats.get("graph_version"),
            build_mode=stats.get("build_mode"),
            symbol_identity_scheme=stats.get("symbol_identity_scheme"),
            build_warnings_count=int(stats.get("build_warnings_count", 0) or 0),
            path_format=stats.get("path_format"),
            total_nodes=int(stats.get("total_nodes", 0) or 0),
            total_relationships=int(stats.get("total_relationships", 0) or 0),
            index_job_id=active_job.get("job_id"),
            index_status=active_job.get("status"),
            index_stage=active_job.get("stage"),
            progress_pct=float(active_job.get("progress_pct", 0.0) or 0.0),
            files_done=int(active_job.get("files_done", 0) or 0),
            files_total=int(active_job.get("files_total", 0) or 0),
            nodes_written=int(active_job.get("nodes_written", 0) or 0),
            edges_written=int(active_job.get("edges_written", 0) or 0),
            elapsed_sec=float(active_job.get("elapsed_sec", 0.0) or 0.0),
            eta_sec=(
                float(active_job.get("eta_sec"))
                if active_job.get("eta_sec") is not None
                else None
            ),
            last_updated=stats.get("last_updated"),
        )
    except Exception as e:
        logger.error(f"Error getting graph metadata: {e}")
        return GraphMetaResponse(
            success=False,
            error=str(e),
        )


# ============================================================================
# MCP Tool Endpoints
# ============================================================================

@app.post("/tools/build_code_graph", response_model=BuildGraphResponse)
async def build_code_graph(request: BuildGraphRequest):
    """
    Build code-test dependency graph for a repository

    This tool:
    1. Parses Python files using AST
    2. Extracts functions, classes, and their relationships
    3. Identifies test files and links them to code
    4. Stores everything in Neo4j graph database
    """
    start_time = datetime.now()
    request_id = str(uuid4())

    try:
        repo_path = Path(request.repo_path)
        if not repo_path.exists():
            raise HTTPException(status_code=404, detail=f"Repository not found: {request.repo_path}")

        logger.info(
            "Building graph request received: repo=%s async_mode=%s",
            request.repo_path,
            request.async_mode,
        )

        if request.async_mode:
            job_key = _build_job_key(repo_path, request)
            with _state_lock:
                active_job_id = _active_build_jobs.get(job_key)
                if active_job_id and active_job_id in _index_jobs:
                    active_job = _index_jobs[active_job_id]
                    active_view = _get_job_view(active_job)
                    return BuildGraphResponse(
                        request_id=active_job_id,
                        success=True,
                        graph_id=_build_graph_id(repo_path, request),
                        nodes_created=int(active_view.get("nodes_written", 0) or 0),
                        relationships_created=int(active_view.get("edges_written", 0) or 0),
                        duration_seconds=float(active_view.get("elapsed_sec", 0.0) or 0.0),
                        warnings=list(active_view.get("warnings", []) or []),
                        message=f"build_job_{active_view.get('status', 'running')}",
                    )

                queued_job = {
                    "job_id": request_id,
                    "job_key": job_key,
                    "repo_path": str(repo_path.resolve()),
                    "status": "queued",
                    "stage": "queued",
                    "progress_pct": 0.0,
                    "files_done": 0,
                    "files_total": 0,
                    "nodes_written": 0,
                    "edges_written": 0,
                    "warnings": [],
                    "message": "Build job accepted",
                    "error": None,
                    "result": None,
                    "created_ts": time.time(),
                    "updated_ts": time.time(),
                    "started_ts": None,
                    "ended_ts": None,
                }
                _index_jobs[request_id] = queued_job
                _active_build_jobs[job_key] = request_id

            asyncio.create_task(_run_build_graph_job(request_id, request, job_key))
            return BuildGraphResponse(
                request_id=request_id,
                success=True,
                graph_id=_build_graph_id(repo_path, request),
                nodes_created=0,
                relationships_created=0,
                duration_seconds=0.0,
                warnings=[],
                message="accepted",
            )

        # Import and use graph builder
        from .graph_builder import GraphBuilder
        from .test_linker import TestLinker

        builder = GraphBuilder()
        result = builder.build_graph(
            repo_path,
            request.force_rebuild,
            repo_slug=request.repo_slug,
            commit_sha=request.commit_sha,
            repo_fingerprint=request.repo_fingerprint,
        )
        _invalidate_stats_cache()

        # Link tests to code
        warnings: List[str] = []
        build_warnings = int(result.get("build_warnings_count", 0) or 0)
        if build_warnings > 0:
            warnings.append(f"Graph build completed with {build_warnings} ambiguous symbol resolutions")
        if request.include_tests:
            linker = TestLinker()
            test_links = linker.link_tests(repo_path)
            logger.info(f"Created {test_links['total_links']} test-code links")
            warnings.extend(test_links.get("warnings", []))

        duration = (datetime.now() - start_time).total_seconds()

        return BuildGraphResponse(
            request_id=request_id,
            success=True,
            graph_id=f"{request.repo_slug or repo_path.name}@{request.commit_sha or 'unknown'}",
            nodes_created=result["nodes_created"],
            relationships_created=result["relationships_created"],
            duration_seconds=duration,
            warnings=warnings,
            message=f"Graph built successfully: {result['files_processed']} files processed"
        )

    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds()
        logger.error(f"Error building graph: {e}")
        return BuildGraphResponse(
            request_id=request_id,
            success=False,
            graph_id="",
            nodes_created=0,
            relationships_created=0,
            duration_seconds=duration,
            error=str(e)
        )


@app.get("/jobs/build_code_graph/{job_id}", response_model=BuildGraphJobStatusResponse)
async def get_build_graph_job_status(job_id: str):
    """Get status for an async build_code_graph job."""
    with _state_lock:
        job = _index_jobs.get(job_id)
        if not job:
            return BuildGraphJobStatusResponse(
                success=False,
                job_id=job_id,
                status="missing",
                stage="missing",
                error="job_not_found",
            )
        job_view = _get_job_view(job)
    return BuildGraphJobStatusResponse(**job_view)


@app.post("/tools/incremental_update", response_model=IncrementalUpdateResponse)
async def incremental_update(request: IncrementalUpdateRequest):
    """
    Incrementally update graph based on changed files

    Uses git diff to identify changes and updates only affected nodes/edges
    """
    start_time = datetime.now()
    request_id = str(uuid4())

    try:
        repo_path = Path(request.repo_path)
        if not repo_path.exists():
            raise HTTPException(status_code=404, detail=f"Repository not found: {request.repo_path}")

        logger.info(f"Incrementally updating graph for: {request.repo_path}")

        # Import and use graph builder
        from .graph_builder import GraphBuilder
        from .test_linker import TestLinker

        builder = GraphBuilder()
        result = builder.incremental_update(
            repo_path,
            request.changed_files,
            request.base_commit,
            repo_slug=request.repo_slug,
            commit_sha=request.commit_sha,
            repo_fingerprint=request.repo_fingerprint,
        )
        _invalidate_stats_cache()
        warnings: List[str] = []

        if request.include_tests:
            linker = TestLinker()
            test_links = linker.link_tests(repo_path)
            logger.info(f"Incremental relink created {test_links.get('total_links', 0)} test-code links")
            warnings.extend(test_links.get("warnings", []))

        duration = (datetime.now() - start_time).total_seconds()

        return IncrementalUpdateResponse(
            request_id=request_id,
            success=True,
            nodes_updated=result["nodes_updated"],
            relationships_updated=result["relationships_updated"],
            duration_seconds=duration,
            warnings=(
                [f"Incremental update had {int(result.get('build_warnings_count', 0) or 0)} ambiguous resolutions"]
                if int(result.get("build_warnings_count", 0) or 0) > 0
                else []
            )
            + warnings,
        )

    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds()
        logger.error(f"Error updating graph: {e}")
        return IncrementalUpdateResponse(
            request_id=request_id,
            success=False,
            nodes_updated=0,
            relationships_updated=0,
            duration_seconds=duration,
            error=str(e)
        )


@app.post("/tools/get_impacted_tests", response_model=GetImpactedTestsResponse)
async def get_impacted_tests(request: GetImpactedTestsRequest):
    """
    Get tests impacted by changed files

    Queries the graph to find:
    1. Direct test coverage of changed functions
    2. Tests covering functions that call changed functions
    3. Tests affected by changed imports/dependencies
    """
    request_id = str(uuid4())
    try:
        repo_path = Path(request.repo_path)
        if not repo_path.exists():
            raise HTTPException(status_code=404, detail=f"Repository not found: {request.repo_path}")

        logger.info(
            "Finding impacted tests for %d changed files (strategy=%s)",
            len(request.changed_files),
            request.strategy,
        )

        strategy = str(request.strategy or "balanced").strip().lower()
        if strategy == "coverage_diff":
            from .test_linker import TestLinker

            linker = TestLinker()
            tests = linker.get_impacted_tests_by_coverage(
                repo_path=repo_path,
                changed_files=request.changed_files,
                impact_threshold=request.impact_threshold,
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
        elif strategy == "hybrid":
            from .impact_analyzer import ImpactAnalyzer
            from .test_linker import TestLinker

            graph_tests: List[Dict[str, Any]] = []
            coverage_tests: List[Dict[str, Any]] = []
            warnings = []
            diagnostics: Dict[str, Any] = {}

            graph_strategy = str(
                os.getenv("GRAPH_IMPACT_GRAPH_STRATEGY", "balanced")
            ).strip().lower()
            graph_error: Optional[str] = None
            coverage_error: Optional[str] = None

            analyzer = ImpactAnalyzer()
            try:
                graph_tests = analyzer.get_impacted_tests(
                    repo_path,
                    request.changed_files,
                    impact_threshold=request.impact_threshold,
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
                    repo_path=repo_path,
                    changed_files=request.changed_files,
                    impact_threshold=request.impact_threshold,
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
        else:
            # Graph-based impact analysis (default path)
            from .impact_analyzer import ImpactAnalyzer

            analyzer = ImpactAnalyzer()
            tests = analyzer.get_impacted_tests(
                repo_path,
                request.changed_files,
                impact_threshold=request.impact_threshold,
                strategy=request.strategy,
            )
            diagnostics = analyzer.get_last_diagnostics()
            warnings = list(diagnostics.get("warnings", []))
        from .graph_db import get_db
        graph_stats = get_db().get_stats()

        return GetImpactedTestsResponse(
            request_id=request_id,
            success=True,
            tests=tests,
            total_tests=len(tests),
            graph_id=graph_stats.get("graph_identity"),
            graph_freshness="unknown",
            warnings=warnings,
            diagnostics=diagnostics,
            message=f"Found {len(tests)} impacted tests"
        )

    except Exception as e:
        logger.error(f"Error finding impacted tests: {e}")
        return GetImpactedTestsResponse(
            request_id=request_id,
            success=False,
            tests=[],
            total_tests=0,
            graph_id=None,
            graph_freshness="unknown",
            warnings=[],
            diagnostics={},
            error=str(e)
        )


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
    """
    Merge graph-traversal and coverage-diff impacted tests.

    Priority:
    1) Keep union of tests from both sources.
    2) Boost tests corroborated by both signals.
    3) Preserve graph traversal metadata and coverage file-hit metadata.
    """
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

        # Fill missing identity fields from whichever source has them.
        for field in ("test_id", "test_name", "test_file"):
            if not row.get(field) and test.get(field):
                row[field] = test.get(field)

        # Preserve strongest score-bearing record fields.
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


@app.post("/tools/run_tests", response_model=RunTestsResponse)
async def run_tests(request: RunTestsRequest):
    """
    Run tests and track results

    Executes pytest and:
    1. Captures test results
    2. Identifies regressions (PASS_TO_FAIL)
    3. Updates graph with test outcomes
    """
    start_time = datetime.now()
    request_id = str(uuid4())

    try:
        repo_path = Path(request.repo_path)
        if not repo_path.exists():
            raise HTTPException(status_code=404, detail=f"Repository not found: {request.repo_path}")

        test_spec = f"{len(request.tests)} specific tests" if request.tests else "all tests"
        logger.info(f"Running {test_spec} for: {request.repo_path}")

        # Import and use test runner
        from .test_linker import TestRunner

        runner = TestRunner()
        results = runner.run_tests(repo_path, request.tests, request.pytest_args)

        duration = (datetime.now() - start_time).total_seconds()

        return RunTestsResponse(
            request_id=request_id,
            success=results["success"],
            passed=results["passed"],
            failed=results["failed"],
            skipped=results["skipped"],
            regressions=results["regressions"],
            duration_seconds=duration,
            test_results=results["test_results"],
            warnings=[],
        )

    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds()
        logger.error(f"Error running tests: {e}")
        return RunTestsResponse(
            request_id=request_id,
            success=False,
            passed=0,
            failed=0,
            skipped=0,
            regressions=0,
            duration_seconds=duration,
            test_results=[],
            warnings=[],
            error=str(e)
        )


@app.post("/tools/clear_database", response_model=ClearDatabaseResponse)
async def clear_database():
    """
    Clear all data from the Neo4j database.

    This is useful for ensuring each experimental run starts with a clean state.
    Should be called at the beginning of a full benchmark run.
    """
    try:
        logger.info("Clearing Neo4j database...")

        from .graph_db import get_db

        db = get_db()
        db.clear_database()
        _invalidate_stats_cache()

        logger.info("Database cleared successfully")

        return ClearDatabaseResponse(
            success=True,
            message="Database cleared successfully"
        )

    except Exception as e:
        logger.error(f"Error clearing database: {e}")
        return ClearDatabaseResponse(
            success=False,
            error=str(e)
        )


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    logger.info(f"Starting server on {config.server.host}:{config.server.port}")

    uvicorn.run(
        "mcp_server.server:app",
        host=config.server.host,
        port=config.server.port,
        reload=config.server.reload,
        log_level=config.server.log_level
    )
