"""
FastAPI MCP Server for GraphRAG Test Impact Analysis

This server provides MCP tools for:
- Building code-test dependency graphs
- Analyzing test impact from code changes
- Running targeted tests to prevent regressions
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

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


class BuildGraphResponse(BaseModel):
    """Response from graph building"""
    success: bool
    graph_id: str
    nodes_created: int
    relationships_created: int
    duration_seconds: float
    message: Optional[str] = None
    error: Optional[str] = None


class IncrementalUpdateRequest(BaseModel):
    """Request to update graph based on changes"""
    repo_path: str = Field(..., description="Path to repository")
    changed_files: Optional[List[str]] = Field(None, description="Specific files changed (or use git diff)")
    base_commit: Optional[str] = Field("HEAD", description="Git commit to compare against")


class IncrementalUpdateResponse(BaseModel):
    """Response from incremental update"""
    success: bool
    nodes_updated: int
    relationships_updated: int
    duration_seconds: float
    error: Optional[str] = None


class GetImpactedTestsRequest(BaseModel):
    """Request to get tests impacted by changes"""
    repo_path: str = Field(..., description="Path to repository")
    changed_files: List[str] = Field(..., description="List of changed file paths")
    impact_threshold: float = Field(0.1, description="Minimum impact score (0-1)")


class GetImpactedTestsResponse(BaseModel):
    """Response with impacted tests"""
    success: bool
    tests: List[Dict[str, any]] = Field(default_factory=list, description="List of impacted tests with scores")
    total_tests: int
    message: Optional[str] = None
    error: Optional[str] = None


class RunTestsRequest(BaseModel):
    """Request to run tests"""
    repo_path: str = Field(..., description="Path to repository")
    tests: Optional[List[str]] = Field(None, description="Specific tests to run (None = all)")
    pytest_args: List[str] = Field(default_factory=list, description="Additional pytest arguments")


class RunTestsResponse(BaseModel):
    """Response from test execution"""
    success: bool
    passed: int
    failed: int
    skipped: int
    regressions: int = Field(0, description="Number of previously passing tests that failed")
    duration_seconds: float
    test_results: List[Dict[str, any]] = Field(default_factory=list)
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

    # TODO: Initialize Neo4j connection
    # TODO: Verify database schema

    yield

    # Shutdown
    logger.info("Shutting down GraphRAG MCP Server...")
    # TODO: Close Neo4j connection


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
    # TODO: Check Neo4j connection
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "neo4j": "connected",  # TODO: actual check
        "embeddings": config.embeddings.provider
    }


@app.get("/stats", response_model=GraphStatsResponse)
async def get_stats():
    """Get graph statistics"""
    try:
        # TODO: Query Neo4j for actual stats
        return GraphStatsResponse(
            success=True,
            total_nodes=0,
            total_relationships=0,
            files=0,
            functions=0,
            classes=0,
            tests=0,
            last_updated=datetime.now()
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
            error=str(e)
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

    try:
        repo_path = Path(request.repo_path)
        if not repo_path.exists():
            raise HTTPException(status_code=404, detail=f"Repository not found: {request.repo_path}")

        logger.info(f"Building graph for: {request.repo_path}")

        # Import and use graph builder
        from .graph_builder import GraphBuilder
        from .test_linker import TestLinker

        builder = GraphBuilder()
        result = builder.build_graph(repo_path, request.force_rebuild)

        # Link tests to code
        if request.include_tests:
            linker = TestLinker()
            test_links = linker.link_tests(repo_path)
            logger.info(f"Created {test_links['total_links']} test-code links")

        duration = (datetime.now() - start_time).total_seconds()

        return BuildGraphResponse(
            success=True,
            graph_id=str(repo_path.name),
            nodes_created=result["nodes_created"],
            relationships_created=result["relationships_created"],
            duration_seconds=duration,
            message=f"Graph built successfully: {result['files_processed']} files processed"
        )

    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds()
        logger.error(f"Error building graph: {e}")
        return BuildGraphResponse(
            success=False,
            graph_id="",
            nodes_created=0,
            relationships_created=0,
            duration_seconds=duration,
            error=str(e)
        )


@app.post("/tools/incremental_update", response_model=IncrementalUpdateResponse)
async def incremental_update(request: IncrementalUpdateRequest):
    """
    Incrementally update graph based on changed files

    Uses git diff to identify changes and updates only affected nodes/edges
    """
    start_time = datetime.now()

    try:
        repo_path = Path(request.repo_path)
        if not repo_path.exists():
            raise HTTPException(status_code=404, detail=f"Repository not found: {request.repo_path}")

        logger.info(f"Incrementally updating graph for: {request.repo_path}")

        # Import and use graph builder
        from .graph_builder import GraphBuilder

        builder = GraphBuilder()
        result = builder.incremental_update(repo_path, request.changed_files, request.base_commit)

        duration = (datetime.now() - start_time).total_seconds()

        return IncrementalUpdateResponse(
            success=True,
            nodes_updated=result["nodes_updated"],
            relationships_updated=result["relationships_updated"],
            duration_seconds=duration
        )

    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds()
        logger.error(f"Error updating graph: {e}")
        return IncrementalUpdateResponse(
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
    try:
        repo_path = Path(request.repo_path)
        if not repo_path.exists():
            raise HTTPException(status_code=404, detail=f"Repository not found: {request.repo_path}")

        logger.info(f"Finding impacted tests for {len(request.changed_files)} changed files")

        # Import and use impact analyzer
        from .impact_analyzer import ImpactAnalyzer

        analyzer = ImpactAnalyzer()
        tests = analyzer.get_impacted_tests(
            repo_path,
            request.changed_files,
            impact_threshold=request.impact_threshold
        )

        return GetImpactedTestsResponse(
            success=True,
            tests=tests,
            total_tests=len(tests),
            message=f"Found {len(tests)} impacted tests"
        )

    except Exception as e:
        logger.error(f"Error finding impacted tests: {e}")
        return GetImpactedTestsResponse(
            success=False,
            tests=[],
            total_tests=0,
            error=str(e)
        )


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
            success=results["success"],
            passed=results["passed"],
            failed=results["failed"],
            skipped=results["skipped"],
            regressions=results["regressions"],
            duration_seconds=duration,
            test_results=results["test_results"]
        )

    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds()
        logger.error(f"Error running tests: {e}")
        return RunTestsResponse(
            success=False,
            passed=0,
            failed=0,
            skipped=0,
            regressions=0,
            duration_seconds=duration,
            test_results=[],
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
        "server:app",
        host=config.server.host,
        port=config.server.port,
        reload=config.server.reload,
        log_level=config.server.log_level
    )
