"""
Configuration for GraphRAG Test Impact Analysis MCP Server
"""
import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel


class ServerConfig(BaseModel):
    """Server configuration settings"""
    host: str = "0.0.0.0"
    port: int = 8080
    reload: bool = False
    log_level: str = "info"


class Neo4jConfig(BaseModel):
    """Neo4j database configuration"""
    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str = "password"
    database: str = "neo4j"  # Community edition only supports default database
    # For embedded mode
    use_embedded: bool = False  # Use standalone Neo4j container
    embedded_path: Optional[str] = None


class EmbeddingsConfig(BaseModel):
    """Embeddings configuration"""
    provider: str = "anthropic"  # "anthropic" or "local"
    model: str = "claude-3-haiku-20240307"  # Haiku for speed
    anthropic_api_key: Optional[str] = None
    batch_size: int = 10
    max_tokens: int = 512


class AnalysisConfig(BaseModel):
    """Code analysis configuration"""
    chunk_level: str = "function"  # "function", "class", or "file"
    include_docstrings: bool = True
    include_comments: bool = False
    min_function_lines: int = 3  # Ignore trivial functions
    max_function_lines: int = 1000  # Split very large functions

    # Test detection
    test_file_patterns: list[str] = ["test_*.py", "*_test.py", "tests.py"]
    test_function_patterns: list[str] = ["test_*"]
    test_class_patterns: list[str] = ["Test*"]

    # Coverage
    use_coverage: bool = False
    coverage_threshold: float = 0.1  # Minimum 10% coverage to link
    coverage_timeout_seconds: int = 600
    coverage_fail_open: bool = True
    # Bound coverage runtime/cost for large repositories.
    coverage_max_test_files: int = 80  # 0 => all discovered test files
    coverage_max_link_rows: int = 250000  # 0 => unlimited
    coverage_test_sample_mode: str = "spread"  # "spread" or "head"
    coverage_pytest_extra_args: str = ""
    coverage_diff_max_tests: int = 200


class GraphIndexConfig(BaseModel):
    """Graph index build/performance configuration."""
    workers: int = 4
    node_batch_size: int = 1000
    edge_batch_size: int = 2000
    status_poll_interval_seconds: int = 2


class Config:
    """Main configuration holder"""

    def __init__(self):
        self.server = ServerConfig()
        self.neo4j = Neo4jConfig()
        self.embeddings = EmbeddingsConfig()
        self.analysis = AnalysisConfig()
        self.graph_index = GraphIndexConfig()

        # Load from environment
        self._load_from_env()

        # Setup embedded Neo4j path
        if self.neo4j.use_embedded and not self.neo4j.embedded_path:
            base_dir = Path(__file__).parent.parent
            self.neo4j.embedded_path = str(base_dir / ".neo4j_embedded")

    def _load_from_env(self):
        """Load configuration from environment variables"""
        # Server
        if host := os.getenv("MCP_SERVER_HOST"):
            self.server.host = host
        if port := os.getenv("MCP_SERVER_PORT"):
            self.server.port = int(port)

        # Neo4j
        if uri := os.getenv("NEO4J_URI"):
            self.neo4j.uri = uri
        if user := os.getenv("NEO4J_USER"):
            self.neo4j.user = user
        if password := os.getenv("NEO4J_PASSWORD"):
            self.neo4j.password = password
        if embedded := os.getenv("NEO4J_EMBEDDED"):
            self.neo4j.use_embedded = embedded.lower() in ("true", "1", "yes")

        # Embeddings
        if api_key := os.getenv("ANTHROPIC_API_KEY"):
            self.embeddings.anthropic_api_key = api_key
        if provider := os.getenv("EMBEDDINGS_PROVIDER"):
            self.embeddings.provider = provider
        if model := os.getenv("EMBEDDINGS_MODEL"):
            self.embeddings.model = model

        if use_coverage := os.getenv("GRAPH_LINK_USE_COVERAGE"):
            self.analysis.use_coverage = use_coverage.lower() in ("true", "1", "yes")
        if coverage_threshold := os.getenv("GRAPH_COVERAGE_THRESHOLD"):
            self.analysis.coverage_threshold = max(0.0, min(1.0, float(coverage_threshold)))
        if coverage_timeout := os.getenv("GRAPH_COVERAGE_TIMEOUT_SECONDS"):
            self.analysis.coverage_timeout_seconds = max(30, int(coverage_timeout))
        if coverage_max_test_files := os.getenv("GRAPH_COVERAGE_MAX_TEST_FILES"):
            self.analysis.coverage_max_test_files = max(0, int(coverage_max_test_files))
        if coverage_max_link_rows := os.getenv("GRAPH_COVERAGE_MAX_LINK_ROWS"):
            self.analysis.coverage_max_link_rows = max(0, int(coverage_max_link_rows))
        if coverage_sample_mode := os.getenv("GRAPH_COVERAGE_TEST_SAMPLE_MODE"):
            mode = coverage_sample_mode.strip().lower()
            if mode in ("spread", "head"):
                self.analysis.coverage_test_sample_mode = mode
        if coverage_extra_args := os.getenv("GRAPH_COVERAGE_PYTEST_EXTRA_ARGS"):
            self.analysis.coverage_pytest_extra_args = coverage_extra_args.strip()
        if coverage_diff_max_tests := os.getenv("GRAPH_COVERAGE_DIFF_MAX_TESTS"):
            self.analysis.coverage_diff_max_tests = max(1, int(coverage_diff_max_tests))

        # Graph index performance tuning
        if workers := os.getenv("GRAPH_INDEX_WORKERS"):
            self.graph_index.workers = max(1, int(workers))
        if node_batch := os.getenv("GRAPH_DB_BATCH_SIZE_NODES"):
            self.graph_index.node_batch_size = max(100, int(node_batch))
        if edge_batch := os.getenv("GRAPH_DB_BATCH_SIZE_EDGES"):
            self.graph_index.edge_batch_size = max(100, int(edge_batch))
        if poll_interval := os.getenv("GRAPH_STATUS_POLL_INTERVAL_SEC"):
            self.graph_index.status_poll_interval_seconds = max(1, int(poll_interval))


# Global config instance
config = Config()
