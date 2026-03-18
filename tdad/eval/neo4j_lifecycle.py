"""Graph DB lifecycle helpers for TDAD evaluation.

Supports both Neo4j (docker) and NetworkX (in-process) backends
based on the TDAD_BACKEND setting.
"""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

COMPOSE_FILE = Path(__file__).resolve().parent.parent / "docker-compose.yml"


def ensure_running() -> None:
    """Start the graph backend. No-op for NetworkX."""
    from tdad.core.config import get_settings

    settings = get_settings()
    if settings.backend == "neo4j":
        logger.info("Ensuring Neo4j is running (compose file: %s)", COMPOSE_FILE)
        subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d"],
            check=True,
            capture_output=True,
            text=True,
        )
        _wait_for_bolt()
        logger.info("Neo4j is ready")
    else:
        logger.info("Using %s backend — no server to start", settings.backend)


def clear(repo_path=None) -> None:
    """Clear the graph database."""
    from tdad.core.config import get_settings, get_db

    settings = get_settings()
    with get_db(settings, repo_path=repo_path) as db:
        db.clear_database()
    logger.info("Graph database cleared (backend=%s)", settings.backend)


def stop() -> None:
    """Stop the graph backend. No-op for NetworkX."""
    from tdad.core.config import get_settings

    settings = get_settings()
    if settings.backend == "neo4j":
        logger.info("Stopping Neo4j")
        subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "down"],
            check=True,
            capture_output=True,
            text=True,
        )
        logger.info("Neo4j stopped")


def _wait_for_bolt(max_attempts: int = 30, interval: float = 2.0) -> None:
    """Poll the bolt port until Neo4j is accepting connections."""
    import time

    for attempt in range(1, max_attempts + 1):
        try:
            from tdad.core.config import get_settings
            from tdad.core.graph_db import GraphDB

            settings = get_settings()
            with GraphDB(settings) as db:
                with db.session() as session:
                    session.run("RETURN 1")
            return
        except Exception:
            if attempt == max_attempts:
                raise RuntimeError(
                    f"Neo4j not ready after {max_attempts * interval}s"
                )
            time.sleep(interval)
