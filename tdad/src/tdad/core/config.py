"""TDAD configuration via pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class TDADSettings(BaseSettings):
    """All TDAD settings, loaded from environment with TDAD_ prefix."""

    model_config = SettingsConfigDict(env_prefix="TDAD_")

    # Backend: "neo4j" or "networkx"
    backend: str = "networkx"

    # Neo4j connection (only used when backend=neo4j)
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"
    neo4j_database: str = "neo4j"

    # Coverage-based linking (opt-in)
    use_coverage: bool = False
    coverage_threshold: float = 0.1

    # Performance
    index_workers: int = 4
    query_timeout: float = 20.0


def get_settings() -> TDADSettings:
    """Return a settings instance (reads env vars on each call)."""
    return TDADSettings()


def get_db(settings: TDADSettings, repo_path=None):
    """Factory: return the right graph DB backend based on settings.backend."""
    if settings.backend == "networkx":
        from .graph_nx import NetworkXGraphDB
        from pathlib import Path
        persist = Path(repo_path) / ".tdad" / "graph.pkl" if repo_path else None
        return NetworkXGraphDB(settings, persist_path=persist)
    elif settings.backend == "neo4j":
        from .graph_db import GraphDB
        return GraphDB(settings)
    else:
        raise ValueError(f"Unknown backend: {settings.backend!r} (expected 'networkx' or 'neo4j')")
