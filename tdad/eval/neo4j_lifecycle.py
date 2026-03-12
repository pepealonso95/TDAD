"""Neo4j container lifecycle helpers for TDAD evaluation."""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

COMPOSE_FILE = Path(__file__).resolve().parent.parent / "docker-compose.yml"


def ensure_running() -> None:
    """Start Neo4j via docker compose if not already running."""
    logger.info("Ensuring Neo4j is running (compose file: %s)", COMPOSE_FILE)
    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d"],
        check=True,
        capture_output=True,
        text=True,
    )
    # Wait for bolt port to be ready
    _wait_for_bolt()
    logger.info("Neo4j is ready")


def clear() -> None:
    """Clear all nodes and relationships from the Neo4j database."""
    from tdad.core.config import get_settings
    from tdad.core.graph_db import GraphDB

    settings = get_settings()
    with GraphDB(settings) as db:
        db.clear_database()
    logger.info("Neo4j database cleared")


def stop() -> None:
    """Stop the Neo4j container."""
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
