"""
Neo4j Graph Database Manager

Handles Neo4j connections and provides graph database operations for
the code-test dependency graph.
"""
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from neo4j import GraphDatabase, Query
from neo4j.exceptions import ServiceUnavailable, AuthError

from .config import config

logger = logging.getLogger(__name__)


class GraphDB:
    """Neo4j Graph Database Manager"""

    def __init__(self):
        self.driver = None
        self.query_timeout_seconds = max(
            1.0,
            float(os.getenv("GRAPH_NEO4J_QUERY_TIMEOUT_SEC", "20")),
        )
        self.connect_timeout_seconds = max(
            1.0,
            float(os.getenv("GRAPH_NEO4J_CONNECT_TIMEOUT_SEC", "10")),
        )
        self._connect()

    def _wrap_query(self, text: str):
        timeout = float(self.query_timeout_seconds or 0.0)
        if timeout > 0:
            return Query(text, timeout=timeout)
        return text

    def run_query(self, session, text: str, **params):
        return session.run(self._wrap_query(text), **params)

    def _connect(self):
        """Establish Neo4j connection"""
        try:
            logger.info(f"Connecting to Neo4j at {config.neo4j.uri}")

            self.driver = GraphDatabase.driver(
                config.neo4j.uri,
                auth=(config.neo4j.user, config.neo4j.password),
                connection_timeout=self.connect_timeout_seconds,
                max_transaction_retry_time=self.query_timeout_seconds,
            )

            # Verify connection
            with self.driver.session(database=config.neo4j.database) as session:
                result = self.run_query(session, "RETURN 1 as num")
                _ = result.single()

            logger.info("Successfully connected to Neo4j")

        except (ServiceUnavailable, AuthError) as e:
            logger.error(f"Failed to connect to Neo4j: {e}")
            logger.info("Make sure Neo4j is running or configure embedded mode")
            raise

    def close(self):
        """Close database connection"""
        if self.driver:
            self.driver.close()
            logger.info("Neo4j connection closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # ========================================================================
    # Schema Management
    # ========================================================================

    def create_schema(self):
        """Create graph schema (constraints and indexes)"""
        with self.driver.session(database=config.neo4j.database) as session:
            logger.info("Creating graph schema...")

            # Constraints (ensure uniqueness)
            constraints = [
                "CREATE CONSTRAINT file_path IF NOT EXISTS FOR (f:File) REQUIRE f.path IS UNIQUE",
                "CREATE CONSTRAINT function_id IF NOT EXISTS FOR (fn:Function) REQUIRE fn.id IS UNIQUE",
                "CREATE CONSTRAINT class_id IF NOT EXISTS FOR (c:Class) REQUIRE c.id IS UNIQUE",
                "CREATE CONSTRAINT test_id IF NOT EXISTS FOR (t:Test) REQUIRE t.id IS UNIQUE",
                "CREATE CONSTRAINT graph_index_meta_id IF NOT EXISTS FOR (m:GraphIndexMetadata) REQUIRE m.id IS UNIQUE",
            ]

            for constraint in constraints:
                try:
                    session.run(constraint)
                    logger.debug(f"Created: {constraint}")
                except Exception as e:
                    if "already exists" not in str(e).lower():
                        logger.warning(f"Constraint creation failed: {e}")

            # Indexes (for faster queries)
            indexes = [
                "CREATE INDEX file_name IF NOT EXISTS FOR (f:File) ON (f.name)",
                "CREATE INDEX function_name IF NOT EXISTS FOR (fn:Function) ON (fn.name)",
                "CREATE INDEX function_symbol_key IF NOT EXISTS FOR (fn:Function) ON (fn.symbol_key)",
                "CREATE INDEX function_qualified_name IF NOT EXISTS FOR (fn:Function) ON (fn.qualified_name)",
                "CREATE INDEX class_name IF NOT EXISTS FOR (c:Class) ON (c.name)",
                "CREATE INDEX class_symbol_key IF NOT EXISTS FOR (c:Class) ON (c.symbol_key)",
                "CREATE INDEX class_qualified_name IF NOT EXISTS FOR (c:Class) ON (c.qualified_name)",
                "CREATE INDEX test_name IF NOT EXISTS FOR (t:Test) ON (t.name)",
            ]

            for index in indexes:
                try:
                    session.run(index)
                    logger.debug(f"Created: {index}")
                except Exception as e:
                    if "already exists" not in str(e).lower():
                        logger.warning(f"Index creation failed: {e}")

            logger.info("Schema creation completed")

    def clear_database(self):
        """Clear all nodes and relationships (use with caution!)."""
        rel_batch = max(1000, int(os.getenv("GRAPH_CLEAR_REL_BATCH", "5000")))
        node_batch = max(1000, int(os.getenv("GRAPH_CLEAR_NODE_BATCH", "5000")))

        with self.driver.session(database=config.neo4j.database) as session:
            logger.warning("Clearing entire database...")
            rel_deleted_total = 0
            while True:
                record = session.run(
                    "MATCH ()-[r]-() WITH r LIMIT $batch DELETE r RETURN count(r) AS deleted",
                    batch=rel_batch,
                ).single()
                deleted = int(record["deleted"] if record and record["deleted"] is not None else 0)
                rel_deleted_total += deleted
                if deleted == 0:
                    break

            node_deleted_total = 0
            while True:
                record = session.run(
                    "MATCH (n) WITH n LIMIT $batch DELETE n RETURN count(n) AS deleted",
                    batch=node_batch,
                ).single()
                deleted = int(record["deleted"] if record and record["deleted"] is not None else 0)
                node_deleted_total += deleted
                if deleted == 0:
                    break

            logger.info(
                "Database cleared: nodes_deleted=%d relationships_deleted=%d",
                node_deleted_total,
                rel_deleted_total,
            )

    def check_connection(self) -> bool:
        """Check if Neo4j is reachable."""
        try:
            with self.driver.session(database=config.neo4j.database) as session:
                result = session.run("RETURN 1 as ok")
                record = result.single()
                return bool(record and record.get("ok") == 1)
        except Exception:
            return False

    # ========================================================================
    # Node Creation
    # ========================================================================

    def _iter_batches(self, rows: List[Dict[str, Any]], batch_size: int):
        """Yield row chunks for batched writes."""
        safe_size = max(1, int(batch_size))
        for i in range(0, len(rows), safe_size):
            yield rows[i:i + safe_size]

    def create_file_node(
        self,
        path: str,
        name: str,
        content_hash: str,
        repo_path: str,
        last_modified: Optional[datetime] = None
    ) -> str:
        """Create or update a File node"""
        with self.driver.session(database=config.neo4j.database) as session:
            result = session.run(
                """
                MERGE (f:File {path: $path})
                SET f.name = $name,
                    f.content_hash = $content_hash,
                    f.repo_path = $repo_path,
                    f.last_modified = $last_modified,
                    f.updated_at = datetime()
                RETURN f.path as path
                """,
                path=path,
                name=name,
                content_hash=content_hash,
                repo_path=repo_path,
                last_modified=last_modified.isoformat() if last_modified else None
            )
            return result.single()["path"]

    def create_function_node(
        self,
        function_id: str,
        name: str,
        file_path: str,
        start_line: int,
        end_line: int,
        signature: str,
        docstring: Optional[str] = None,
        embedding: Optional[List[float]] = None,
        symbol_key: Optional[str] = None,
        module_name: Optional[str] = None,
        qualified_name: Optional[str] = None,
    ) -> str:
        """Create or update a Function node"""
        with self.driver.session(database=config.neo4j.database) as session:
            result = session.run(
                """
                MERGE (fn:Function {id: $function_id})
                SET fn.name = $name,
                    fn.file_path = $file_path,
                    fn.start_line = $start_line,
                    fn.end_line = $end_line,
                    fn.signature = $signature,
                    fn.docstring = $docstring,
                    fn.embedding = $embedding,
                    fn.symbol_key = $symbol_key,
                    fn.module_name = $module_name,
                    fn.qualified_name = $qualified_name,
                    fn.updated_at = datetime()
                RETURN fn.id as id
                """,
                function_id=function_id,
                name=name,
                file_path=file_path,
                start_line=start_line,
                end_line=end_line,
                signature=signature,
                docstring=docstring,
                embedding=embedding,
                symbol_key=symbol_key,
                module_name=module_name,
                qualified_name=qualified_name,
            )
            return result.single()["id"]

    def create_class_node(
        self,
        class_id: str,
        name: str,
        file_path: str,
        start_line: int,
        end_line: int,
        docstring: Optional[str] = None,
        embedding: Optional[List[float]] = None,
        symbol_key: Optional[str] = None,
        module_name: Optional[str] = None,
        qualified_name: Optional[str] = None,
    ) -> str:
        """Create or update a Class node"""
        with self.driver.session(database=config.neo4j.database) as session:
            result = session.run(
                """
                MERGE (c:Class {id: $class_id})
                SET c.name = $name,
                    c.file_path = $file_path,
                    c.start_line = $start_line,
                    c.end_line = $end_line,
                    c.docstring = $docstring,
                    c.embedding = $embedding,
                    c.symbol_key = $symbol_key,
                    c.module_name = $module_name,
                    c.qualified_name = $qualified_name,
                    c.updated_at = datetime()
                RETURN c.id as id
                """,
                class_id=class_id,
                name=name,
                file_path=file_path,
                start_line=start_line,
                end_line=end_line,
                docstring=docstring,
                embedding=embedding,
                symbol_key=symbol_key,
                module_name=module_name,
                qualified_name=qualified_name,
            )
            return result.single()["id"]

    def create_test_node(
        self,
        test_id: str,
        name: str,
        file_path: str,
        function_name: str,
        test_type: str = "pytest"
    ) -> str:
        """Create or update a Test node"""
        with self.driver.session(database=config.neo4j.database) as session:
            result = session.run(
                """
                MERGE (t:Test {id: $test_id})
                SET t.name = $name,
                    t.file_path = $file_path,
                    t.function_name = $function_name,
                    t.test_type = $test_type,
                    t.updated_at = datetime()
                RETURN t.id as id
                """,
                test_id=test_id,
                name=name,
                file_path=file_path,
                function_name=function_name,
                test_type=test_type
            )
            return result.single()["id"]

    def upsert_file_nodes_batch(self, rows: List[Dict[str, Any]]) -> int:
        """Bulk upsert File nodes using UNWIND."""
        if not rows:
            return 0
        batch_size = config.graph_index.node_batch_size
        with self.driver.session(database=config.neo4j.database) as session:
            for chunk in self._iter_batches(rows, batch_size):
                session.run(
                    """
                    UNWIND $rows AS row
                    MERGE (f:File {path: row.path})
                    SET f.name = row.name,
                        f.content_hash = row.content_hash,
                        f.repo_path = row.repo_path,
                        f.last_modified = row.last_modified,
                        f.updated_at = datetime()
                    """,
                    rows=chunk,
                )
        return len(rows)

    def upsert_function_nodes_batch(self, rows: List[Dict[str, Any]]) -> int:
        """Bulk upsert Function nodes using UNWIND."""
        if not rows:
            return 0
        batch_size = config.graph_index.node_batch_size
        with self.driver.session(database=config.neo4j.database) as session:
            for chunk in self._iter_batches(rows, batch_size):
                session.run(
                    """
                    UNWIND $rows AS row
                    MERGE (fn:Function {id: row.function_id})
                    SET fn.name = row.name,
                        fn.file_path = row.file_path,
                        fn.start_line = row.start_line,
                        fn.end_line = row.end_line,
                        fn.signature = row.signature,
                        fn.docstring = row.docstring,
                        fn.embedding = row.embedding,
                        fn.symbol_key = row.symbol_key,
                        fn.module_name = row.module_name,
                        fn.qualified_name = row.qualified_name,
                        fn.updated_at = datetime()
                    """,
                    rows=chunk,
                )
        return len(rows)

    def upsert_class_nodes_batch(self, rows: List[Dict[str, Any]]) -> int:
        """Bulk upsert Class nodes using UNWIND."""
        if not rows:
            return 0
        batch_size = config.graph_index.node_batch_size
        with self.driver.session(database=config.neo4j.database) as session:
            for chunk in self._iter_batches(rows, batch_size):
                session.run(
                    """
                    UNWIND $rows AS row
                    MERGE (c:Class {id: row.class_id})
                    SET c.name = row.name,
                        c.file_path = row.file_path,
                        c.start_line = row.start_line,
                        c.end_line = row.end_line,
                        c.docstring = row.docstring,
                        c.embedding = row.embedding,
                        c.symbol_key = row.symbol_key,
                        c.module_name = row.module_name,
                        c.qualified_name = row.qualified_name,
                        c.updated_at = datetime()
                    """,
                    rows=chunk,
                )
        return len(rows)

    def upsert_test_nodes_batch(self, rows: List[Dict[str, Any]]) -> int:
        """Bulk upsert Test nodes using UNWIND."""
        if not rows:
            return 0
        batch_size = config.graph_index.node_batch_size
        with self.driver.session(database=config.neo4j.database) as session:
            for chunk in self._iter_batches(rows, batch_size):
                session.run(
                    """
                    UNWIND $rows AS row
                    MERGE (t:Test {id: row.test_id})
                    SET t.name = row.name,
                        t.file_path = row.file_path,
                        t.function_name = row.function_name,
                        t.test_type = row.test_type,
                        t.updated_at = datetime()
                    """,
                    rows=chunk,
                )
        return len(rows)

    # ========================================================================
    # Relationship Creation
    # ========================================================================

    def create_contains_relationship(self, parent_id: str, node_id: str, node_type: str):
        """Create CONTAINS relationship from File(path) or Class(id) to a target node."""
        with self.driver.session(database=config.neo4j.database) as session:
            session.run(
                f"""
                MATCH (n:{node_type} {{id: $node_id}})
                OPTIONAL MATCH (f:File {{path: $parent_id}})
                OPTIONAL MATCH (c:Class {{id: $parent_id}})
                WITH n, coalesce(f, c) as parent
                WHERE parent IS NOT NULL
                MERGE (parent)-[:CONTAINS]->(n)
                """,
                parent_id=parent_id,
                node_id=node_id
            )

    def create_contains_relationships_batch(self, rows: List[Dict[str, str]]) -> int:
        """
        Bulk create CONTAINS relationships.

        Each row must include:
        - parent_type: "File" or "Class"
        - parent_id
        - node_id
        - node_type: "Function" | "Class" | "Test" (optional but recommended)
        """
        if not rows:
            return 0

        parent_key_by_type = {"File": "path", "Class": "id"}
        grouped_rows: Dict[Tuple[str, str], List[Dict[str, str]]] = {}
        skipped_rows = 0

        for row in rows:
            parent_type = str(row.get("parent_type") or "")
            if parent_type not in parent_key_by_type:
                skipped_rows += 1
                continue
            node_type = str(row.get("node_type") or "").strip()
            key = (parent_type, node_type)
            grouped_rows.setdefault(key, []).append(row)

        if skipped_rows:
            logger.warning("Skipped %d CONTAINS rows with invalid parent_type", skipped_rows)

        batch_size = config.graph_index.edge_batch_size
        with self.driver.session(database=config.neo4j.database) as session:
            for (parent_type, node_type), rows_for_group in grouped_rows.items():
                parent_key = parent_key_by_type[parent_type]
                node_label = ""
                if node_type in {"Function", "Class", "Test"}:
                    node_label = f":{node_type}"

                query = (
                    f"UNWIND $rows AS row\n"
                    f"MATCH (p:{parent_type} {{{parent_key}: row.parent_id}})\n"
                    f"MATCH (n{node_label} {{id: row.node_id}})\n"
                    f"MERGE (p)-[:CONTAINS]->(n)\n"
                )

                for chunk in self._iter_batches(rows_for_group, batch_size):
                    session.run(query, rows=chunk)
        return len(rows)

    def create_calls_relationship(
        self,
        caller_id: str,
        callee_id: str,
        resolution_method: str = "exact",
        resolution_confidence: float = 1.0,
    ):
        """Create CALLS relationship between Functions"""
        with self.driver.session(database=config.neo4j.database) as session:
            session.run(
                """
                MATCH (caller:Function {id: $caller_id})
                MATCH (callee:Function {id: $callee_id})
                MERGE (caller)-[r:CALLS]->(callee)
                SET r.resolution_method = CASE
                        WHEN r.resolution_confidence IS NULL OR $resolution_confidence >= r.resolution_confidence
                        THEN $resolution_method
                        ELSE r.resolution_method
                    END,
                    r.resolution_confidence = CASE
                        WHEN r.resolution_confidence IS NULL THEN $resolution_confidence
                        WHEN $resolution_confidence > r.resolution_confidence THEN $resolution_confidence
                        ELSE r.resolution_confidence
                    END,
                    r.updated_at = datetime()
                """,
                caller_id=caller_id,
                callee_id=callee_id,
                resolution_method=resolution_method,
                resolution_confidence=resolution_confidence,
            )

    def create_calls_relationships_batch(self, rows: List[Dict[str, Any]]) -> int:
        """Bulk create CALLS relationships with confidence-aware upserts."""
        if not rows:
            return 0
        batch_size = config.graph_index.edge_batch_size
        with self.driver.session(database=config.neo4j.database) as session:
            for chunk in self._iter_batches(rows, batch_size):
                session.run(
                    """
                    UNWIND $rows AS row
                    MATCH (caller:Function {id: row.caller_id})
                    MATCH (callee:Function {id: row.callee_id})
                    MERGE (caller)-[r:CALLS]->(callee)
                    SET r.resolution_method = CASE
                            WHEN r.resolution_confidence IS NULL OR row.resolution_confidence >= r.resolution_confidence
                            THEN row.resolution_method
                            ELSE r.resolution_method
                        END,
                        r.resolution_confidence = CASE
                            WHEN r.resolution_confidence IS NULL THEN row.resolution_confidence
                            WHEN row.resolution_confidence > r.resolution_confidence THEN row.resolution_confidence
                            ELSE r.resolution_confidence
                        END,
                        r.updated_at = datetime()
                    """,
                    rows=chunk,
                )
        return len(rows)

    def create_imports_relationship(self, from_file: str, to_file: str):
        """Create IMPORTS relationship between Files"""
        with self.driver.session(database=config.neo4j.database) as session:
            session.run(
                """
                MATCH (f1:File {path: $from_file})
                MATCH (f2:File {path: $to_file})
                MERGE (f1)-[:IMPORTS]->(f2)
                """,
                from_file=from_file,
                to_file=to_file
            )

    def create_imports_relationships_batch(self, rows: List[Dict[str, str]]) -> int:
        """Bulk create IMPORTS relationships between files."""
        if not rows:
            return 0
        batch_size = config.graph_index.edge_batch_size
        with self.driver.session(database=config.neo4j.database) as session:
            for chunk in self._iter_batches(rows, batch_size):
                session.run(
                    """
                    UNWIND $rows AS row
                    MATCH (f1:File {path: row.from_file})
                    MATCH (f2:File {path: row.to_file})
                    MERGE (f1)-[:IMPORTS]->(f2)
                    """,
                    rows=chunk,
                )
        return len(rows)

    def create_tests_relationship(
        self,
        test_id: str,
        target_id: str,
        target_type: str,
        coverage: float = 1.0,
        link_source: str = "unknown",
        link_confidence: Optional[float] = None,
    ):
        """Create TESTS relationship from Test to Function/Class"""
        effective_confidence = coverage if link_confidence is None else link_confidence
        with self.driver.session(database=config.neo4j.database) as session:
            session.run(
                f"""
                MATCH (t:Test {{id: $test_id}})
                MATCH (target:{target_type} {{id: $target_id}})
                MERGE (t)-[r:TESTS]->(target)
                SET r.coverage = CASE
                        WHEN r.coverage IS NULL OR $coverage > r.coverage THEN $coverage
                        ELSE r.coverage
                    END,
                    r.link_source = CASE
                        WHEN r.link_confidence IS NULL OR $link_confidence >= r.link_confidence THEN $link_source
                        ELSE r.link_source
                    END,
                    r.link_confidence = CASE
                        WHEN r.link_confidence IS NULL THEN $link_confidence
                        WHEN $link_confidence > r.link_confidence THEN $link_confidence
                        ELSE r.link_confidence
                    END,
                    r.updated_at = datetime()
                """,
                test_id=test_id,
                target_id=target_id,
                coverage=coverage,
                link_source=link_source,
                link_confidence=effective_confidence,
            )

    def create_tests_relationships_batch(self, rows: List[Dict[str, Any]]) -> int:
        """Bulk create TESTS relationships from Test to Function/Class."""
        if not rows:
            return 0
        batch_size = config.graph_index.edge_batch_size
        with self.driver.session(database=config.neo4j.database) as session:
            for chunk in self._iter_batches(rows, batch_size):
                session.run(
                    """
                    UNWIND $rows AS row
                    MATCH (t:Test {id: row.test_id})
                    CALL (t, row) {
                        WITH t, row
                        WHERE row.target_type = 'Function'
                        MATCH (target:Function {id: row.target_id})
                        MERGE (t)-[r:TESTS]->(target)
                        SET r.coverage = CASE
                                WHEN r.coverage IS NULL OR row.coverage > r.coverage THEN row.coverage
                                ELSE r.coverage
                            END,
                            r.link_source = CASE
                                WHEN r.link_confidence IS NULL OR row.link_confidence >= r.link_confidence THEN row.link_source
                                ELSE r.link_source
                            END,
                            r.link_confidence = CASE
                                WHEN r.link_confidence IS NULL THEN row.link_confidence
                                WHEN row.link_confidence > r.link_confidence THEN row.link_confidence
                                ELSE r.link_confidence
                            END,
                            r.updated_at = datetime()
                        RETURN 1 AS created
                        UNION
                        WITH t, row
                        WHERE row.target_type = 'Class'
                        MATCH (target:Class {id: row.target_id})
                        MERGE (t)-[r:TESTS]->(target)
                        SET r.coverage = CASE
                                WHEN r.coverage IS NULL OR row.coverage > r.coverage THEN row.coverage
                                ELSE r.coverage
                            END,
                            r.link_source = CASE
                                WHEN r.link_confidence IS NULL OR row.link_confidence >= r.link_confidence THEN row.link_source
                                ELSE r.link_source
                            END,
                            r.link_confidence = CASE
                                WHEN r.link_confidence IS NULL THEN row.link_confidence
                                WHEN row.link_confidence > r.link_confidence THEN row.link_confidence
                                ELSE r.link_confidence
                            END,
                            r.updated_at = datetime()
                        RETURN 1 AS created
                    }
                    RETURN sum(created) AS created_total
                    """,
                    rows=chunk,
                )
        return len(rows)

    def create_inherits_relationship(
        self,
        child_class_id: str,
        parent_class_id: str,
        resolution_method: str = "exact",
        resolution_confidence: float = 1.0,
    ):
        """Create INHERITS relationship between Classes"""
        with self.driver.session(database=config.neo4j.database) as session:
            session.run(
                """
                MATCH (child:Class {id: $child_class_id})
                MATCH (parent:Class {id: $parent_class_id})
                MERGE (child)-[r:INHERITS]->(parent)
                SET r.resolution_method = CASE
                        WHEN r.resolution_confidence IS NULL OR $resolution_confidence >= r.resolution_confidence
                        THEN $resolution_method
                        ELSE r.resolution_method
                    END,
                    r.resolution_confidence = CASE
                        WHEN r.resolution_confidence IS NULL THEN $resolution_confidence
                        WHEN $resolution_confidence > r.resolution_confidence THEN $resolution_confidence
                        ELSE r.resolution_confidence
                    END,
                    r.updated_at = datetime()
                """,
                child_class_id=child_class_id,
                parent_class_id=parent_class_id,
                resolution_method=resolution_method,
                resolution_confidence=resolution_confidence,
            )

    def create_inherits_relationships_batch(self, rows: List[Dict[str, Any]]) -> int:
        """Bulk create INHERITS relationships with confidence-aware upserts."""
        if not rows:
            return 0
        batch_size = config.graph_index.edge_batch_size
        with self.driver.session(database=config.neo4j.database) as session:
            for chunk in self._iter_batches(rows, batch_size):
                session.run(
                    """
                    UNWIND $rows AS row
                    MATCH (child:Class {id: row.child_class_id})
                    MATCH (parent:Class {id: row.parent_class_id})
                    MERGE (child)-[r:INHERITS]->(parent)
                    SET r.resolution_method = CASE
                            WHEN r.resolution_confidence IS NULL OR row.resolution_confidence >= r.resolution_confidence
                            THEN row.resolution_method
                            ELSE r.resolution_method
                        END,
                        r.resolution_confidence = CASE
                            WHEN r.resolution_confidence IS NULL THEN row.resolution_confidence
                            WHEN row.resolution_confidence > r.resolution_confidence THEN row.resolution_confidence
                            ELSE r.resolution_confidence
                        END,
                        r.updated_at = datetime()
                    """,
                    rows=chunk,
                )
        return len(rows)

    def create_depends_on_relationship(
        self,
        test_id: str,
        file_path: str,
        coverage_pct: float,
        link_source: str = "coverage",
        link_confidence: Optional[float] = None,
    ):
        """Create DEPENDS_ON relationship from Test to File (from coverage data)"""
        effective_confidence = coverage_pct if link_confidence is None else link_confidence
        with self.driver.session(database=config.neo4j.database) as session:
            session.run(
                """
                MATCH (t:Test {id: $test_id})
                MATCH (f:File {path: $file_path})
                MERGE (t)-[r:DEPENDS_ON]->(f)
                SET r.coverage_pct = CASE
                        WHEN r.coverage_pct IS NULL OR $coverage_pct > r.coverage_pct THEN $coverage_pct
                        ELSE r.coverage_pct
                    END,
                    r.link_source = CASE
                        WHEN r.link_confidence IS NULL OR $link_confidence >= r.link_confidence THEN $link_source
                        ELSE r.link_source
                    END,
                    r.link_confidence = CASE
                        WHEN r.link_confidence IS NULL THEN $link_confidence
                        WHEN $link_confidence > r.link_confidence THEN $link_confidence
                        ELSE r.link_confidence
                    END,
                    r.updated_at = datetime()
                """,
                test_id=test_id,
                file_path=file_path,
                coverage_pct=coverage_pct,
                link_source=link_source,
                link_confidence=effective_confidence,
            )

    def create_depends_on_relationships_batch(self, rows: List[Dict[str, Any]]) -> int:
        """Bulk create DEPENDS_ON relationships from Test to File."""
        if not rows:
            return 0
        batch_size = config.graph_index.edge_batch_size
        with self.driver.session(database=config.neo4j.database) as session:
            for chunk in self._iter_batches(rows, batch_size):
                session.run(
                    """
                    UNWIND $rows AS row
                    MATCH (t:Test {id: row.test_id})
                    MATCH (f:File {path: row.file_path})
                    MERGE (t)-[r:DEPENDS_ON]->(f)
                    SET r.coverage_pct = CASE
                            WHEN r.coverage_pct IS NULL OR row.coverage_pct > r.coverage_pct THEN row.coverage_pct
                            ELSE r.coverage_pct
                        END,
                        r.link_source = CASE
                            WHEN r.link_confidence IS NULL OR row.link_confidence >= r.link_confidence THEN row.link_source
                            ELSE r.link_source
                        END,
                        r.link_confidence = CASE
                            WHEN r.link_confidence IS NULL THEN row.link_confidence
                            WHEN row.link_confidence > r.link_confidence THEN row.link_confidence
                            ELSE r.link_confidence
                        END,
                        r.updated_at = datetime()
                    """,
                    rows=chunk,
                )
        return len(rows)

    # ========================================================================
    # Query Operations
    # ========================================================================

    def get_stats(self) -> Dict:
        """Get graph statistics"""
        with self.driver.session(database=config.neo4j.database) as session:
            counts = self.run_query(
                session,
                """
                CALL () {
                    MATCH (f:File) RETURN count(f) AS files
                }
                CALL () {
                    MATCH (fn:Function) RETURN count(fn) AS functions
                }
                CALL () {
                    MATCH (c:Class) RETURN count(c) AS classes
                }
                CALL () {
                    MATCH (t:Test) RETURN count(t) AS tests
                }
                CALL () {
                    MATCH ()-[r]-() RETURN count(r) AS rels
                }
                RETURN files, functions, classes, tests, rels
                """
            ).single()

            metadata = self.get_index_metadata()
            files = int((counts or {}).get("files", 0) or 0)
            functions = int((counts or {}).get("functions", 0) or 0)
            classes = int((counts or {}).get("classes", 0) or 0)
            tests = int((counts or {}).get("tests", 0) or 0)
            total_nodes = files + functions + classes + tests

            return {
                "total_nodes": total_nodes,
                "total_relationships": int((counts or {}).get("rels", 0) or 0),
                "by_type": {
                    "File": files,
                    "Function": functions,
                    "Class": classes,
                    "Test": tests,
                },
                **metadata,
            }

    def get_status_metadata(self) -> Dict:
        """Read lightweight metadata for freshness checks without global counts."""
        metadata = self.get_index_metadata()
        with self.driver.session(database=config.neo4j.database) as session:
            has_node = self.run_query(
                session,
                """
                MATCH (n)
                WHERE n:File OR n:Function OR n:Class OR n:Test
                RETURN 1 AS has_node
                LIMIT 1
                """,
            ).single()
        return {
            "total_nodes": 1 if has_node else 0,
            "total_relationships": 0,
            **metadata,
        }

    def update_index_metadata(
        self,
        *,
        repo_path: str,
        path_format: str = "relative",
        repo_slug: Optional[str] = None,
        commit_sha: Optional[str] = None,
        graph_identity: Optional[str] = None,
        repo_fingerprint: Optional[str] = None,
        build_mode: str = "full",
        graph_version: str = "v2",
        symbol_identity_scheme: str = "module::class::function",
        build_warnings_count: int = 0,
    ) -> None:
        """Persist active graph index metadata used by cache validation."""
        with self.driver.session(database=config.neo4j.database) as session:
            self.run_query(
                session,
                """
                MERGE (m:GraphIndexMetadata {id: 'active'})
                SET m.last_indexed_repo = $repo_path,
                    m.path_format = $path_format,
                    m.repo_slug = $repo_slug,
                    m.last_indexed_commit = $commit_sha,
                    m.graph_identity = $graph_identity,
                    m.repo_fingerprint = $repo_fingerprint,
                    m.build_mode = $build_mode,
                    m.graph_version = $graph_version,
                    m.symbol_identity_scheme = $symbol_identity_scheme,
                    m.build_warnings_count = $build_warnings_count,
                    m.updated_at = datetime()
                """,
                repo_path=repo_path,
                path_format=path_format,
                repo_slug=repo_slug,
                commit_sha=commit_sha,
                graph_identity=graph_identity,
                repo_fingerprint=repo_fingerprint,
                build_mode=build_mode,
                graph_version=graph_version,
                symbol_identity_scheme=symbol_identity_scheme,
                build_warnings_count=build_warnings_count,
            )

    def get_index_metadata(self) -> Dict:
        """Read active graph index metadata."""
        with self.driver.session(database=config.neo4j.database) as session:
            record = self.run_query(
                session,
                """
                MATCH (m:GraphIndexMetadata {id: 'active'})
                RETURN
                    m.last_indexed_repo as last_indexed_repo,
                    m.path_format as path_format,
                    m.repo_slug as repo_slug,
                    m.last_indexed_commit as last_indexed_commit,
                    m.graph_identity as graph_identity,
                    m.repo_fingerprint as repo_fingerprint,
                    m.build_mode as build_mode,
                    m.graph_version as graph_version,
                    m.symbol_identity_scheme as symbol_identity_scheme,
                    m.build_warnings_count as build_warnings_count,
                    m.updated_at as last_updated
                """
            ).single()

        if not record:
            return {
                "last_indexed_repo": None,
                "path_format": None,
                "repo_slug": None,
                "last_indexed_commit": None,
                "graph_identity": None,
                "repo_fingerprint": None,
                "build_mode": None,
                "graph_version": None,
                "symbol_identity_scheme": None,
                "build_warnings_count": 0,
                "last_updated": None,
            }

        last_updated = record.get("last_updated")
        if hasattr(last_updated, "iso_format"):
            last_updated = last_updated.iso_format()
        elif hasattr(last_updated, "isoformat"):
            last_updated = last_updated.isoformat()

        return {
            "last_indexed_repo": record.get("last_indexed_repo"),
            "path_format": record.get("path_format"),
            "repo_slug": record.get("repo_slug"),
            "last_indexed_commit": record.get("last_indexed_commit"),
            "graph_identity": record.get("graph_identity"),
            "repo_fingerprint": record.get("repo_fingerprint"),
            "build_mode": record.get("build_mode"),
            "graph_version": record.get("graph_version"),
            "symbol_identity_scheme": record.get("symbol_identity_scheme"),
            "build_warnings_count": int(record.get("build_warnings_count") or 0),
            "last_updated": last_updated,
        }

    def find_impacted_tests(self, changed_files: List[str]) -> List[Dict]:
        """Find tests impacted by changed files"""
        with self.driver.session(database=config.neo4j.database) as session:
            result = session.run(
                """
                // Find tests that directly test changed files
                MATCH (t:Test)-[:TESTS]->(target)-[:CONTAINED_IN]->(f:File)
                WHERE (target:Function OR target:Class) AND f.path IN $changed_files
                RETURN DISTINCT t.id as test_id, t.name as test_name, t.file_path as test_file, 1.0 as impact_score

                UNION

                // Find tests that test functions calling changed functions
                MATCH (t:Test)-[:TESTS]->(fn1:Function)
                MATCH path = (fn1)-[:CALLS*1..3]->(fn2:Function)
                MATCH (fn2)-[:CONTAINED_IN]->(f:File)
                WHERE f.path IN $changed_files
                WITH DISTINCT t, path, length(path) as traversal_depth
                RETURN DISTINCT
                    t.id as test_id,
                    t.name as test_name,
                    t.file_path as test_file,
                    (0.7 / toFloat(traversal_depth)) as impact_score

                UNION

                // Find tests with coverage dependencies on changed files
                MATCH (t:Test)-[r]->(f:File)
                WHERE type(r) = 'DEPENDS_ON' AND f.path IN $changed_files
                RETURN DISTINCT
                    t.id as test_id,
                    t.name as test_name,
                    t.file_path as test_file,
                    toFloat(coalesce(r.link_confidence, 0.0)) as impact_score

                UNION

                // Fallback import dependency when coverage is unavailable
                MATCH (test_file:File)-[:IMPORTS]->(changed_file:File)
                WHERE changed_file.path IN $changed_files
                MATCH (test_file)-[:CONTAINS]->(t:Test)
                RETURN DISTINCT t.id as test_id, t.name as test_name, t.file_path as test_file, 0.45 as impact_score
                """,
                changed_files=changed_files
            )

            return result.data()


# Global database instance
_db_instance: Optional[GraphDB] = None


def get_db() -> GraphDB:
    """Get or create the global database instance"""
    global _db_instance
    if _db_instance is None:
        _db_instance = GraphDB()
    return _db_instance


def close_db():
    """Close the global database instance"""
    global _db_instance
    if _db_instance is not None:
        _db_instance.close()
        _db_instance = None
