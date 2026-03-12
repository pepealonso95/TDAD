"""TDAD configuration via pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class TDADSettings(BaseSettings):
    """All TDAD settings, loaded from environment with TDAD_ prefix."""

    model_config = SettingsConfigDict(env_prefix="TDAD_")

    # Neo4j connection
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"
    neo4j_database: str = "neo4j"

    # Coverage-based linking (opt-in)
    use_coverage: bool = False
    coverage_threshold: float = 0.1

    # Performance
    index_workers: int = 4
    query_timeout: float = 120.0


def get_settings() -> TDADSettings:
    """Return a settings instance (reads env vars on each call)."""
    return TDADSettings()
