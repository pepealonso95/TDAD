"""Thin Neo4j driver wrapper for TDAD."""

import logging
from typing import Any

from neo4j import GraphDatabase, Query
from neo4j.exceptions import AuthError, ServiceUnavailable

from .config import TDADSettings
from .schema import CONSTRAINTS, INDEXES

logger = logging.getLogger(__name__)


class GraphDB:
    """Manages a single Neo4j driver and provides helper methods."""

    def __init__(self, settings: TDADSettings):
        self.settings = settings
        self.driver = None
        self._connect()

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def _connect(self):
        try:
            self.driver = GraphDatabase.driver(
                self.settings.neo4j_uri,
                auth=(self.settings.neo4j_user, self.settings.neo4j_password),
                connection_timeout=10.0,
                max_transaction_retry_time=self.settings.query_timeout,
            )
            with self.driver.session(database=self.settings.neo4j_database) as session:
                session.run("RETURN 1")
            logger.info("Connected to Neo4j at %s", self.settings.neo4j_uri)
        except (ServiceUnavailable, AuthError) as exc:
            logger.error("Failed to connect to Neo4j: %s", exc)
            raise

    def close(self):
        if self.driver:
            self.driver.close()
            logger.info("Neo4j connection closed")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def run_query(self, session, text: str, **params) -> Any:
        timeout = self.settings.query_timeout
        q = Query(text, timeout=timeout) if timeout > 0 else text
        return session.run(q, **params)

    def session(self):
        return self.driver.session(database=self.settings.neo4j_database)

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def ensure_schema(self):
        with self.session() as session:
            for stmt in CONSTRAINTS + INDEXES:
                try:
                    session.run(stmt)
                except Exception as exc:
                    if "already exists" not in str(exc).lower():
                        logger.warning("Schema statement failed: %s", exc)

    def clear_database(self):
        with self.session() as session:
            session.run("MATCH ()-[r]-() DELETE r")
            session.run("MATCH (n) DELETE n")
            logger.info("Database cleared")
