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
    database: str = "tdad_graphrag"
    # For embedded mode
    use_embedded: bool = True
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
    use_coverage: bool = True
    coverage_threshold: float = 0.1  # Minimum 10% coverage to link


class Config:
    """Main configuration holder"""

    def __init__(self):
        self.server = ServerConfig()
        self.neo4j = Neo4jConfig()
        self.embeddings = EmbeddingsConfig()
        self.analysis = AnalysisConfig()

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


# Global config instance
config = Config()
