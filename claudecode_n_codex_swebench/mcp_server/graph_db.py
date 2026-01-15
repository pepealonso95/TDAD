"""
Neo4j Graph Database Manager

Handles Neo4j connections and provides graph database operations for
the code-test dependency graph.
"""
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, AuthError

from .config import config

logger = logging.getLogger(__name__)


class GraphDB:
    """Neo4j Graph Database Manager"""

    def __init__(self):
        self.driver = None
        self._connect()

    def _connect(self):
        """Establish Neo4j connection"""
        try:
            logger.info(f"Connecting to Neo4j at {config.neo4j.uri}")

            self.driver = GraphDatabase.driver(
                config.neo4j.uri,
                auth=(config.neo4j.user, config.neo4j.password)
            )

            # Verify connection
            with self.driver.session(database=config.neo4j.database) as session:
                result = session.run("RETURN 1 as num")
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
                "CREATE INDEX class_name IF NOT EXISTS FOR (c:Class) ON (c.name)",
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
        """Clear all nodes and relationships (use with caution!)"""
        with self.driver.session(database=config.neo4j.database) as session:
            logger.warning("Clearing entire database...")
            session.run("MATCH (n) DETACH DELETE n")
            logger.info("Database cleared")

    # ========================================================================
    # Node Creation
    # ========================================================================

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
        embedding: Optional[List[float]] = None
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
                embedding=embedding
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
        embedding: Optional[List[float]] = None
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
                    c.updated_at = datetime()
                RETURN c.id as id
                """,
                class_id=class_id,
                name=name,
                file_path=file_path,
                start_line=start_line,
                end_line=end_line,
                docstring=docstring,
                embedding=embedding
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

    # ========================================================================
    # Relationship Creation
    # ========================================================================

    def create_contains_relationship(self, file_path: str, node_id: str, node_type: str):
        """Create CONTAINS relationship from File to Function/Class"""
        with self.driver.session(database=config.neo4j.database) as session:
            session.run(
                f"""
                MATCH (f:File {{path: $file_path}})
                MATCH (n:{node_type} {{id: $node_id}})
                MERGE (f)-[:CONTAINS]->(n)
                """,
                file_path=file_path,
                node_id=node_id
            )

    def create_calls_relationship(self, caller_id: str, callee_id: str):
        """Create CALLS relationship between Functions"""
        with self.driver.session(database=config.neo4j.database) as session:
            session.run(
                """
                MATCH (caller:Function {id: $caller_id})
                MATCH (callee:Function {id: $callee_id})
                MERGE (caller)-[:CALLS]->(callee)
                """,
                caller_id=caller_id,
                callee_id=callee_id
            )

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

    def create_tests_relationship(self, test_id: str, target_id: str, target_type: str, coverage: float = 1.0):
        """Create TESTS relationship from Test to Function/Class"""
        with self.driver.session(database=config.neo4j.database) as session:
            session.run(
                f"""
                MATCH (t:Test {{id: $test_id}})
                MATCH (target:{target_type} {{id: $target_id}})
                MERGE (t)-[r:TESTS]->(target)
                SET r.coverage = $coverage,
                    r.updated_at = datetime()
                """,
                test_id=test_id,
                target_id=target_id,
                coverage=coverage
            )

    def create_inherits_relationship(self, child_class_id: str, parent_class_id: str):
        """Create INHERITS relationship between Classes"""
        with self.driver.session(database=config.neo4j.database) as session:
            session.run(
                """
                MATCH (child:Class {id: $child_class_id})
                MATCH (parent:Class {id: $parent_class_id})
                MERGE (child)-[:INHERITS]->(parent)
                """,
                child_class_id=child_class_id,
                parent_class_id=parent_class_id
            )

    def create_depends_on_relationship(self, test_id: str, file_path: str, coverage_pct: float):
        """Create DEPENDS_ON relationship from Test to File (from coverage data)"""
        with self.driver.session(database=config.neo4j.database) as session:
            session.run(
                """
                MATCH (t:Test {id: $test_id})
                MATCH (f:File {path: $file_path})
                MERGE (t)-[r:DEPENDS_ON]->(f)
                SET r.coverage_pct = $coverage_pct,
                    r.updated_at = datetime()
                """,
                test_id=test_id,
                file_path=file_path,
                coverage_pct=coverage_pct
            )

    # ========================================================================
    # Query Operations
    # ========================================================================

    def get_stats(self) -> Dict:
        """Get graph statistics"""
        with self.driver.session(database=config.neo4j.database) as session:
            result = session.run(
                """
                MATCH (n)
                RETURN
                    count(n) as total_nodes,
                    count(DISTINCT labels(n)) as node_types,
                    size((n)--()) as total_relationships
                """
            )
            stats = result.single()

            # Count by type
            type_counts = session.run(
                """
                MATCH (n)
                RETURN labels(n)[0] as type, count(n) as count
                """
            ).data()

            return {
                "total_nodes": stats["total_nodes"],
                "total_relationships": stats["total_relationships"],
                "by_type": {item["type"]: item["count"] for item in type_counts}
            }

    def find_impacted_tests(self, changed_files: List[str]) -> List[Dict]:
        """Find tests impacted by changed files"""
        with self.driver.session(database=config.neo4j.database) as session:
            result = session.run(
                """
                // Find tests that directly test changed files
                MATCH (t:Test)-[:TESTS]->(fn:Function)-[:CONTAINED_IN]->(f:File)
                WHERE f.path IN $changed_files
                RETURN DISTINCT t.id as test_id, t.name as test_name, t.file_path as test_file, 1.0 as impact_score

                UNION

                // Find tests that test functions calling changed functions
                MATCH (t:Test)-[:TESTS]->(fn1:Function)-[:CALLS]->(fn2:Function)-[:CONTAINED_IN]->(f:File)
                WHERE f.path IN $changed_files
                RETURN DISTINCT t.id as test_id, t.name as test_name, t.file_path as test_file, 0.7 as impact_score

                UNION

                // Find tests with coverage dependencies on changed files
                MATCH (t:Test)-[r:DEPENDS_ON]->(f:File)
                WHERE f.path IN $changed_files
                RETURN DISTINCT t.id as test_id, t.name as test_name, t.file_path as test_file, r.coverage_pct as impact_score
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
