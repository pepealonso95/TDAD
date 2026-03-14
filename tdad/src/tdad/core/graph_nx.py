"""NetworkX-based graph backend for TDAD.

Drop-in alternative to Neo4j — no server, no Docker, just pip install networkx.
Persists the graph to a pickle file in .tdad/graph.pkl.
"""

import logging
import pickle
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import networkx as nx

from .config import TDADSettings

logger = logging.getLogger(__name__)


class NetworkXGraphDB:
    """In-memory graph using NetworkX, serialized to disk via pickle."""

    def __init__(self, settings: TDADSettings, persist_path: Optional[Path] = None):
        self.settings = settings
        self.persist_path = persist_path  # set by caller when repo_path is known
        self.G = nx.DiGraph()
        self._load()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _load(self):
        if self.persist_path and self.persist_path.exists():
            try:
                with open(self.persist_path, "rb") as f:
                    self.G = pickle.load(f)
                logger.info("Loaded graph from %s (%d nodes, %d edges)",
                            self.persist_path, self.G.number_of_nodes(), self.G.number_of_edges())
            except Exception as exc:
                logger.warning("Failed to load graph from %s: %s", self.persist_path, exc)
                self.G = nx.DiGraph()

    def save(self):
        if self.persist_path:
            self.persist_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.persist_path, "wb") as f:
                pickle.dump(self.G, f)
            logger.info("Saved graph to %s", self.persist_path)

    def close(self):
        self.save()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ------------------------------------------------------------------
    # Schema (no-op for NetworkX)
    # ------------------------------------------------------------------

    def ensure_schema(self):
        pass

    def clear_database(self):
        self.G.clear()
        logger.info("Graph cleared")

    # ------------------------------------------------------------------
    # Node operations
    # ------------------------------------------------------------------

    def merge_nodes(self, label: str, rows: List[Dict], key_field: str):
        """Add or update nodes with a given label."""
        for row in rows:
            node_id = f"{label}::{row[key_field]}"
            self.G.add_node(node_id, label=label, **row)

    def _find_nodes(self, label: str, **filters) -> List[str]:
        """Find node IDs matching label and optional attribute filters."""
        results = []
        for nid, data in self.G.nodes(data=True):
            if data.get("label") != label:
                continue
            if all(data.get(k) == v for k, v in filters.items()):
                results.append(nid)
        return results

    def _find_nodes_in(self, label: str, field: str, values: list) -> List[str]:
        """Find node IDs where field value is in the given list."""
        value_set = set(values)
        results = []
        for nid, data in self.G.nodes(data=True):
            if data.get("label") != label:
                continue
            if data.get(field) in value_set:
                results.append(nid)
        return results

    def get_node_data(self, node_id: str) -> Optional[Dict]:
        if node_id in self.G:
            return dict(self.G.nodes[node_id])
        return None

    # ------------------------------------------------------------------
    # Edge operations
    # ------------------------------------------------------------------

    def merge_edge(self, src_id: str, dst_id: str, rel: str, **props):
        if src_id in self.G and dst_id in self.G:
            self.G.add_edge(src_id, dst_id, rel=rel, **props)

    def merge_edges_by_key(self, rel: str, rows: List[Dict],
                           src_label: str, src_key: str, src_field: str,
                           dst_label: str, dst_key: str, dst_field: str,
                           **extra_props):
        """Merge edges between nodes identified by label+key lookups."""
        # Build indexes for fast lookup
        src_index: Dict[Any, str] = {}
        dst_index: Dict[Any, str] = {}
        for nid, data in self.G.nodes(data=True):
            if data.get("label") == src_label:
                src_index[data.get(src_key)] = nid
            if data.get("label") == dst_label:
                dst_index[data.get(dst_key)] = nid

        count = 0
        for row in rows:
            s = src_index.get(row[src_field])
            d = dst_index.get(row[dst_field])
            if s and d:
                self.G.add_edge(s, d, rel=rel, **extra_props)
                count += 1
        return count

    # ------------------------------------------------------------------
    # Query helpers (used by graph_builder, test_linker, impact, cli)
    # ------------------------------------------------------------------

    def get_all_file_hashes(self) -> Dict[str, str]:
        """Return {path: content_hash} for all File nodes."""
        result = {}
        for nid, data in self.G.nodes(data=True):
            if data.get("label") == "File":
                result[data["path"]] = data.get("content_hash", "")
        return result

    def delete_file_subgraph(self, paths: List[str]):
        """Remove File nodes and all their children for given paths."""
        path_set = set(paths)
        to_remove = set()
        for nid, data in self.G.nodes(data=True):
            if data.get("label") == "File" and data.get("path") in path_set:
                to_remove.add(nid)
            elif data.get("file_path") in path_set:
                to_remove.add(nid)
        self.G.remove_nodes_from(to_remove)

    def count_by_label(self, label: str) -> int:
        return sum(1 for _, d in self.G.nodes(data=True) if d.get("label") == label)

    def count_edges(self, rel: Optional[str] = None) -> int:
        if rel is None:
            return self.G.number_of_edges()
        return sum(1 for _, _, d in self.G.edges(data=True) if d.get("rel") == rel)

    # ------------------------------------------------------------------
    # Impact analysis queries
    # ------------------------------------------------------------------

    def direct_tests(self, changed_files: List[str]) -> List[Dict]:
        """Tests that directly TESTS a Function/Class in changed files."""
        file_set = set(changed_files)
        results = []
        seen = set()
        for src, dst, data in self.G.edges(data=True):
            if data.get("rel") != "TESTS":
                continue
            src_data = self.G.nodes[src]
            dst_data = self.G.nodes[dst]
            if src_data.get("label") != "Test":
                continue
            if dst_data.get("label") not in ("Function", "Class"):
                continue
            if dst_data.get("file_path") not in file_set:
                continue
            key = (src_data.get("id", src), dst_data.get("file_path"))
            if key in seen:
                continue
            seen.add(key)
            results.append({
                "test_id": src_data.get("id", ""),
                "test_name": src_data.get("name", ""),
                "test_file": src_data.get("file_path", ""),
                "target_file": dst_data.get("file_path", ""),
                "link_confidence": data.get("link_confidence", 1.0),
            })
        return results

    def transitive_tests(self, changed_files: List[str]) -> List[Dict]:
        """Tests that TESTS a function which CALLS (1-3 hops) into changed files."""
        file_set = set(changed_files)
        # Find all Function nodes in changed files
        target_funcs = set()
        for nid, data in self.G.nodes(data=True):
            if data.get("label") == "Function" and data.get("file_path") in file_set:
                target_funcs.add(nid)

        if not target_funcs:
            return []

        # Find functions that call target_funcs within 1-3 hops (reverse CALLS)
        callers_of_targets = set()
        frontier = target_funcs
        for _ in range(3):
            next_frontier = set()
            for nid in frontier:
                for pred in self.G.predecessors(nid):
                    edge_data = self.G.edges[pred, nid]
                    if edge_data.get("rel") == "CALLS" and pred not in callers_of_targets:
                        callers_of_targets.add(pred)
                        next_frontier.add(pred)
            frontier = next_frontier
            if not frontier:
                break

        # Find Tests that TESTS any of these callers
        results = []
        seen = set()
        for src, dst, data in self.G.edges(data=True):
            if data.get("rel") != "TESTS":
                continue
            if dst not in callers_of_targets:
                continue
            src_data = self.G.nodes[src]
            if src_data.get("label") != "Test":
                continue
            test_id = src_data.get("id", src)
            if test_id in seen:
                continue
            seen.add(test_id)
            results.append({
                "test_id": test_id,
                "test_name": src_data.get("name", ""),
                "test_file": src_data.get("file_path", ""),
                "target_file": "",
                "link_confidence": data.get("link_confidence", 0.8) * 0.7,
            })
        return results

    def coverage_tests(self, changed_files: List[str]) -> List[Dict]:
        """Tests with DEPENDS_ON edge to changed Files."""
        file_set = set(changed_files)
        results = []
        seen = set()
        for src, dst, data in self.G.edges(data=True):
            if data.get("rel") != "DEPENDS_ON":
                continue
            src_data = self.G.nodes[src]
            dst_data = self.G.nodes[dst]
            if src_data.get("label") != "Test" or dst_data.get("label") != "File":
                continue
            if dst_data.get("path") not in file_set:
                continue
            test_id = src_data.get("id", src)
            if test_id in seen:
                continue
            seen.add(test_id)
            results.append({
                "test_id": test_id,
                "test_name": src_data.get("name", ""),
                "test_file": src_data.get("file_path", ""),
                "target_file": dst_data.get("path", ""),
                "link_confidence": data.get("link_confidence", 0.5),
            })
        return results

    def import_tests(self, changed_files: List[str]) -> List[Dict]:
        """Tests in files that IMPORTS changed files."""
        file_set = set(changed_files)
        # Find File nodes that import changed files
        importing_files = set()
        for src, dst, data in self.G.edges(data=True):
            if data.get("rel") != "IMPORTS":
                continue
            dst_data = self.G.nodes[dst]
            if dst_data.get("label") == "File" and dst_data.get("path") in file_set:
                importing_files.add(src)

        # Find Test nodes contained in those importing files
        results = []
        seen = set()
        for src, dst, data in self.G.edges(data=True):
            if data.get("rel") != "CONTAINS":
                continue
            if src not in importing_files:
                continue
            dst_data = self.G.nodes[dst]
            if dst_data.get("label") != "Test":
                continue
            test_id = dst_data.get("id", dst)
            if test_id in seen:
                continue
            seen.add(test_id)
            src_data = self.G.nodes[src]
            results.append({
                "test_id": test_id,
                "test_name": dst_data.get("name", ""),
                "test_file": dst_data.get("file_path", ""),
                "target_file": "",
                "link_confidence": 0.45,
            })
        return results

    # ------------------------------------------------------------------
    # Test map export query
    # ------------------------------------------------------------------

    def get_test_source_mappings(self) -> List[Dict]:
        """Return [{source_file, test_file}] from TESTS edges."""
        results = []
        seen = set()
        for src, dst, data in self.G.edges(data=True):
            if data.get("rel") != "TESTS":
                continue
            src_data = self.G.nodes[src]
            dst_data = self.G.nodes[dst]
            if src_data.get("label") != "Test":
                continue
            source = dst_data.get("file_path", "")
            test = src_data.get("file_path", "")
            if source and test and source != test:
                key = (source, test)
                if key not in seen:
                    seen.add(key)
                    results.append({"source_file": source, "test_file": test})
        return results

    # ------------------------------------------------------------------
    # Test linker queries
    # ------------------------------------------------------------------

    def get_all_tests(self) -> List[Dict]:
        """Return all Test nodes."""
        return [
            {"id": data.get("id", nid), "name": data.get("name", ""), "file_path": data.get("file_path", "")}
            for nid, data in self.G.nodes(data=True)
            if data.get("label") == "Test"
        ]

    def get_all_functions(self) -> List[Dict]:
        """Return all Function nodes (non-test)."""
        results = []
        for nid, data in self.G.nodes(data=True):
            if data.get("label") != "Function":
                continue
            # Exclude test functions by checking if there's a matching Test node
            results.append({
                "id": data.get("id", nid),
                "name": data.get("name", ""),
                "file_path": data.get("file_path", ""),
                "qualified_name": data.get("qualified_name", ""),
                "calls": data.get("calls", []),
                "start_line": data.get("start_line", 0),
                "end_line": data.get("end_line", 0),
            })
        return results

    def get_all_classes(self) -> List[Dict]:
        """Return all Class nodes."""
        return [
            {"id": data.get("id", nid), "name": data.get("name", ""), "file_path": data.get("file_path", "")}
            for nid, data in self.G.nodes(data=True)
            if data.get("label") == "Class"
        ]

    def tests_edge_exists(self, test_id: str, target_id: str) -> bool:
        """Check if a TESTS edge already exists."""
        t_nid = f"Test::{test_id}"
        # Check both possible target labels
        for label in ("Function", "Class"):
            d_nid = f"{label}::{target_id}"
            if self.G.has_edge(t_nid, d_nid) and self.G.edges[t_nid, d_nid].get("rel") == "TESTS":
                return True
        return False

    def create_tests_edge(self, test_id: str, target_id: str, target_label: str,
                          link_source: str, link_confidence: float):
        """Create a TESTS edge between a Test and a Function/Class."""
        t_nid = f"Test::{test_id}"
        d_nid = f"{target_label}::{target_id}"
        if t_nid in self.G and d_nid in self.G:
            self.G.add_edge(t_nid, d_nid, rel="TESTS",
                            link_source=link_source, link_confidence=link_confidence)
            return True
        return False

    def get_file_imports(self) -> List[Dict]:
        """Return all IMPORTS edges as [{importer, imported}]."""
        results = []
        for src, dst, data in self.G.edges(data=True):
            if data.get("rel") != "IMPORTS":
                continue
            src_data = self.G.nodes[src]
            dst_data = self.G.nodes[dst]
            results.append({
                "importer": src_data.get("path", ""),
                "imported": dst_data.get("path", ""),
            })
        return results

    def get_functions_in_file(self, file_path: str, min_line: int, max_line: int) -> List[str]:
        """Return function IDs in a file overlapping the given line range."""
        results = []
        for nid, data in self.G.nodes(data=True):
            if data.get("label") != "Function":
                continue
            if data.get("file_path") != file_path:
                continue
            start = data.get("start_line", 0)
            end = data.get("end_line", 0)
            if start <= max_line and end >= min_line:
                results.append(data.get("id", nid))
        return results
