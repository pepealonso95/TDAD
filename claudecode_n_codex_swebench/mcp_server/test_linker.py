"""
Test Linker - Links unit tests to source code

Uses multiple strategies:
1. Naming conventions (test_function_name -> function_name)
2. Coverage data (coverage.py results)
3. Static analysis (imports and calls from test files)
"""
import logging
import os
import re
import shlex
import subprocess
import sys
import time
from collections import defaultdict
from fnmatch import fnmatch
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from coverage import Coverage, CoverageData

from .config import config
from .graph_db import get_db

logger = logging.getLogger(__name__)


class TestLinker:
    """Links tests to source code using multiple strategies"""

    def __init__(self):
        self.db = get_db()
        self._warnings: List[str] = []

    def _warn(self, message: str) -> None:
        """Record linker warnings for diagnostics."""
        self._warnings.append(message)
        logger.warning(message)

    def get_warnings(self) -> List[str]:
        """Return collected warnings from the last operation."""
        return list(self._warnings)

    def _run_query(self, session, query: str, **params):
        run_query = getattr(self.db, "run_query", None)
        if callable(run_query):
            return run_query(session, query, **params)
        return session.run(query, **params)

    def link_tests(self, repo_path: Path) -> Dict:
        """Link all tests to source code"""
        logger.info(f"Linking tests to code for: {repo_path}")
        self._warnings = []

        total_links = 0

        # Strategy 1: Naming conventions
        naming_links = self._link_by_naming_convention(repo_path)
        total_links += naming_links
        logger.info(f"Created {naming_links} links via naming conventions")

        # Strategy 2: Coverage data
        coverage_links = 0
        if config.analysis.use_coverage:
            try:
                coverage_links = self._link_by_coverage(repo_path)
                total_links += coverage_links
                logger.info(f"Created {coverage_links} links via coverage data")
            except Exception as e:
                msg = f"Coverage linking failed: {e}"
                self._warn(msg)
                if not getattr(config.analysis, "coverage_fail_open", True):
                    raise
        else:
            self._warn("Coverage linking disabled for fast indexing (set GRAPH_LINK_USE_COVERAGE=1 to enable)")

        # Strategy 3: Static analysis
        static_links = self._link_by_static_analysis(repo_path)
        total_links += static_links
        logger.info(f"Created {static_links} links via static analysis")

        return {
            "total_links": total_links,
            "naming_convention": naming_links,
            "coverage": coverage_links if config.analysis.use_coverage else 0,
            "static_analysis": static_links,
            "warnings": list(self._warnings),
        }

    def _link_by_naming_convention(self, repo_path: Path) -> int:
        """Link tests to functions based on naming conventions"""
        link_rows: List[Dict[str, object]] = []
        linked_pairs: Set[Tuple[str, str]] = set()

        tests = self._get_test_nodes()
        function_rows = self._get_function_nodes_for_naming()
        candidate_index = self._build_function_candidate_index(function_rows)
        candidate_cache: Dict[str, List[Dict[str, str]]] = {}
        max_candidates = max(
            8,
            int(os.getenv("GRAPH_NAMING_MAX_CANDIDATES_PER_TARGET", "192")),
        )
        progress_every = max(
            100,
            int(os.getenv("GRAPH_NAMING_PROGRESS_EVERY_TESTS", "500")),
        )

        logger.info(
            "Naming linker index ready: tests=%d functions=%d max_candidates=%d",
            len(tests),
            len(function_rows),
            max_candidates,
        )

        for idx, test in enumerate(tests, start=1):
            test_name = test["test_name"]
            test_id = test["test_id"]
            test_file = test.get("test_file", "")

            # Try to infer function name from test name
            # Common patterns:
            # test_function_name -> function_name
            # test_class_method -> Class.method
            # TestClass.test_method -> Class.method

            target_names = self._infer_target_names(test_name)

            for target_name in target_names:
                if target_name not in candidate_cache:
                    candidate_cache[target_name] = self._find_function_candidates_from_index(
                        target_name=target_name,
                        candidate_index=candidate_index,
                        max_candidates=max_candidates,
                    )

                for candidate in candidate_cache[target_name]:
                    function_id = str(candidate["function_id"])
                    pair = (test_id, function_id)
                    if pair in linked_pairs:
                        continue

                    confidence = self._score_naming_candidate(
                        target_name=target_name,
                        test_file=test_file,
                        function_name=str(candidate["function_name"]),
                        function_file=str(candidate["function_file"]),
                    )
                    if confidence < 0.45:
                        continue

                    linked_pairs.add(pair)
                    link_rows.append(
                        {
                            "test_id": test_id,
                            "target_id": function_id,
                            "target_type": "Function",
                            "coverage": confidence,
                            "link_source": "naming",
                            "link_confidence": confidence,
                        }
                    )
                    logger.debug(
                        f"Naming link: {test_name} -> {candidate['function_name']} "
                        f"(confidence={confidence:.2f})"
                    )

            if idx % progress_every == 0:
                logger.info(
                    "Naming linker progress: %d/%d tests (%d links, %d cached targets)",
                    idx,
                    len(tests),
                    len(link_rows),
                    len(candidate_cache),
                )

        self.db.create_tests_relationships_batch(link_rows)
        return len(link_rows)

    def _infer_target_names(self, test_name: str) -> List[str]:
        """Infer possible target function names from test name"""
        target_names = []

        # Pattern 1: test_function_name -> function_name
        if test_name.startswith("test_"):
            target_name = test_name[5:]  # Remove "test_" prefix
            target_names.append(target_name)

        # Pattern 2: test_class_method -> method
        parts = test_name.split("_")
        if len(parts) > 2 and parts[0] == "test":
            # Try each part as potential method name
            for i in range(1, len(parts)):
                target_names.append("_".join(parts[i:]))

        # Pattern 3: TestClass.test_method -> method
        if "." in test_name:
            parts = test_name.split(".")
            if len(parts) == 2:
                method_name = parts[1]
                if method_name.startswith("test_"):
                    target_names.append(method_name[5:])

        min_plain_len = max(2, int(os.getenv("GRAPH_NAMING_MIN_PLAIN_TARGET_LEN", "3")))
        filtered: List[str] = []
        seen: Set[str] = set()
        for name in target_names:
            if not name or name in seen:
                continue
            # Drop very short single-token targets (e.g., "at", "_") that explode candidate sets.
            if "." not in name and "_" not in name and len(name) < min_plain_len:
                continue
            seen.add(name)
            filtered.append(name)

        return filtered

    def _get_function_nodes_for_naming(self) -> List[Dict[str, str]]:
        """Fetch function nodes needed for naming-based linking."""
        with self.db.driver.session(database=config.neo4j.database) as session:
            result = self._run_query(
                session,
                """
                MATCH (fn:Function)
                RETURN
                    fn.id as function_id,
                    fn.name as function_name,
                    fn.file_path as function_file,
                    fn.qualified_name as qualified_name
                """
            )
            return result.data()

    def _build_function_candidate_index(
        self,
        function_rows: List[Dict[str, str]],
    ) -> Dict[str, Dict[str, List[Dict[str, str]]]]:
        """Build in-memory lookup indexes for naming candidates."""
        by_exact_name: Dict[str, List[Dict[str, str]]] = defaultdict(list)
        by_name_tail: Dict[str, List[Dict[str, str]]] = defaultdict(list)
        by_qualified_tail: Dict[str, List[Dict[str, str]]] = defaultdict(list)
        by_token: Dict[str, List[Dict[str, str]]] = defaultdict(list)

        for row in function_rows:
            function_name = str(row.get("function_name") or "")
            qualified_name = str(row.get("qualified_name") or "")
            if not function_name:
                continue

            by_exact_name[function_name].append(row)
            by_name_tail[function_name.rsplit(".", 1)[-1]].append(row)

            if qualified_name:
                by_qualified_tail[qualified_name.rsplit(".", 1)[-1]].append(row)

            tokens = set()
            tokens.update(self._tokenize_name(function_name))
            tokens.update(self._tokenize_name(qualified_name))
            for token in tokens:
                by_token[token].append(row)

        return {
            "exact": dict(by_exact_name),
            "tail": dict(by_name_tail),
            "qualified_tail": dict(by_qualified_tail),
            "token": dict(by_token),
        }

    def _tokenize_name(self, value: str) -> Set[str]:
        """Tokenize symbol-like names into searchable lowercase terms."""
        if not value:
            return set()
        normalized = value.replace("::", ".")
        parts = re.split(r"[^A-Za-z0-9]+", normalized)
        return {part.lower() for part in parts if part}

    def _find_function_candidates_from_index(
        self,
        *,
        target_name: str,
        candidate_index: Dict[str, Dict[str, List[Dict[str, str]]]],
        max_candidates: int,
    ) -> List[Dict[str, str]]:
        """Resolve plausible function candidates from in-memory indexes."""
        normalized = target_name.strip()
        if not normalized:
            return []

        ranked: Dict[str, Tuple[int, Dict[str, str]]] = {}

        def add_candidates(candidates: List[Dict[str, str]], score: int) -> None:
            for candidate in candidates:
                function_id = str(candidate.get("function_id") or "")
                if not function_id:
                    continue
                previous = ranked.get(function_id)
                if previous is None or score > previous[0]:
                    ranked[function_id] = (score, candidate)

        tail = normalized.rsplit(".", 1)[-1]
        add_candidates(candidate_index["exact"].get(normalized, []), 100)
        add_candidates(candidate_index["tail"].get(normalized, []), 90)
        add_candidates(candidate_index["tail"].get(tail, []), 85)
        add_candidates(candidate_index["qualified_tail"].get(normalized, []), 80)
        add_candidates(candidate_index["qualified_tail"].get(tail, []), 75)

        min_token_len = max(2, int(os.getenv("GRAPH_NAMING_MIN_TOKEN_LEN", "3")))
        for token in self._tokenize_name(normalized):
            if len(token) < min_token_len:
                continue
            add_candidates(candidate_index["token"].get(token, []), 40)

        sorted_candidates = sorted(
            ranked.values(),
            key=lambda item: (
                -item[0],
                len(str(item[1].get("function_name") or "")),
                str(item[1].get("function_name") or ""),
            ),
        )
        return [candidate for _, candidate in sorted_candidates[:max_candidates]]

    def _score_naming_candidate(
        self,
        *,
        target_name: str,
        test_file: str,
        function_name: str,
        function_file: str,
    ) -> float:
        """Score naming-based candidate confidence."""
        if function_name == target_name:
            base = 0.75
        elif function_name.endswith(f".{target_name}"):
            base = 0.7
        elif target_name in function_name:
            base = 0.58
        else:
            base = 0.45

        if test_file and function_file:
            test_dirs = Path(test_file).parts[:-1]
            fn_dirs = Path(function_file).parts[:-1]
            common_prefix = 0
            for left, right in zip(test_dirs, fn_dirs):
                if left != right:
                    break
                common_prefix += 1
            base += min(0.2, common_prefix * 0.05)

        return max(0.0, min(0.9, base))

    def _link_by_coverage(self, repo_path: Path) -> int:
        """Link tests to code using coverage.py data"""
        try:
            # Run coverage
            logger.info("Running pytest with coverage...")
            coverage_data = self._run_coverage(repo_path)

            if not coverage_data:
                logger.warning("No coverage data obtained")
                return 0

        except Exception as e:
            self._warn(f"Error running coverage: {e}")
            raise

        links_created, _ = self._persist_coverage_links(
            coverage_data=coverage_data,
            link_source="coverage",
            max_files_per_test=max(
                1,
                int(os.getenv("GRAPH_COVERAGE_MAX_FILES_PER_TEST", "20")),
            ),
            max_link_rows=max(
                0,
                int(getattr(config.analysis, "coverage_max_link_rows", 250000)),
            ),
            coverage_threshold=float(config.analysis.coverage_threshold),
        )
        return links_created

    def link_selected_tests_by_coverage(self, repo_path: Path, tests: List[str]) -> Dict[str, object]:
        """Persist bounded coverage links for already-selected targeted tests."""
        self._warnings = []
        selected_tests = self._normalize_selected_tests(tests)
        if not selected_tests:
            return {
                "success": True,
                "links_created": 0,
                "tests_considered": 0,
                "tests_with_coverage": 0,
                "warnings": [],
            }

        max_tests = max(1, int(os.getenv("GRAPH_TARGETED_COVERAGE_MAX_TESTS", "12")))
        bounded_tests = selected_tests[:max_tests]
        if len(selected_tests) > len(bounded_tests):
            self._warn(
                "Targeted coverage test cap reached at "
                f"{len(bounded_tests)} tests (GRAPH_TARGETED_COVERAGE_MAX_TESTS={max_tests})"
            )

        coverage_timeout = max(
            30,
            int(
                os.getenv(
                    "GRAPH_TARGETED_COVERAGE_TIMEOUT_SECONDS",
                    str(min(int(getattr(config.analysis, "coverage_timeout_seconds", 600)), 240)),
                )
            ),
        )
        coverage_data = self._run_coverage(
            repo_path,
            selected_tests=bounded_tests,
            coverage_timeout=coverage_timeout,
        )
        if not coverage_data:
            return {
                "success": True,
                "links_created": 0,
                "tests_considered": len(bounded_tests),
                "tests_with_coverage": 0,
                "warnings": self.get_warnings(),
            }

        links_created, tests_with_coverage = self._persist_coverage_links(
            coverage_data=coverage_data,
            link_source="targeted_coverage",
            max_files_per_test=max(
                1,
                int(
                    os.getenv(
                        "GRAPH_TARGETED_COVERAGE_MAX_FILES_PER_TEST",
                        os.getenv("GRAPH_COVERAGE_MAX_FILES_PER_TEST", "12"),
                    )
                ),
            ),
            max_link_rows=max(
                0,
                int(os.getenv("GRAPH_TARGETED_COVERAGE_MAX_LINK_ROWS", "2000")),
            ),
            coverage_threshold=max(
                0.0,
                min(
                    1.0,
                    float(
                        os.getenv(
                            "GRAPH_TARGETED_COVERAGE_THRESHOLD",
                            str(getattr(config.analysis, "coverage_threshold", 0.1)),
                        )
                    ),
                ),
            ),
        )
        return {
            "success": True,
            "links_created": links_created,
            "tests_considered": len(bounded_tests),
            "tests_with_coverage": tests_with_coverage,
            "warnings": self.get_warnings(),
        }

    def _persist_coverage_links(
        self,
        *,
        coverage_data: Dict[str, Dict[str, float]],
        link_source: str,
        max_files_per_test: int,
        max_link_rows: int,
        coverage_threshold: float,
    ) -> Tuple[int, int]:
        """Persist bounded test-to-file coverage links into the graph."""
        link_rows: List[Dict[str, object]] = []
        tests_with_coverage = 0
        hit_link_cap = False

        for test_id, covered_files in coverage_data.items():
            ranked_files = sorted(
                covered_files.items(),
                key=lambda item: float(item[1]),
                reverse=True,
            )[:max_files_per_test]
            added_for_test = False
            for file_path, coverage_pct in ranked_files:
                coverage_ratio = float(coverage_pct)
                if coverage_ratio < coverage_threshold:
                    continue
                link_confidence = min(1.0, 0.7 + (coverage_ratio * 0.3))
                link_rows.append(
                    {
                        "test_id": test_id,
                        "file_path": file_path,
                        "coverage_pct": coverage_ratio,
                        "link_source": link_source,
                        "link_confidence": link_confidence,
                    }
                )
                added_for_test = True
                if max_link_rows and len(link_rows) >= max_link_rows:
                    hit_link_cap = True
                    break
            if added_for_test:
                tests_with_coverage += 1
            if hit_link_cap:
                break

        if hit_link_cap:
            self._warn(
                f"Coverage link row cap reached at {len(link_rows)} rows "
                f"(max_link_rows={max_link_rows}, source={link_source})"
            )
        if link_rows:
            self.db.create_depends_on_relationships_batch(link_rows)
        return len(link_rows), tests_with_coverage

    def _normalize_selected_tests(self, tests: List[str]) -> List[str]:
        """Normalize and deduplicate targeted pytest selection arguments."""
        normalized: List[str] = []
        seen: Set[str] = set()
        for raw_test in tests:
            test_ref = str(raw_test or "").strip()
            if not test_ref:
                continue
            normalized_ref = test_ref.replace("\\", "/")
            if normalized_ref.startswith("./"):
                normalized_ref = normalized_ref[2:]
            if normalized_ref in seen:
                continue
            seen.add(normalized_ref)
            normalized.append(normalized_ref)
        return normalized

    def _normalized_pytest_env(
        self,
        repo_path: Path,
        *,
        ignore_import_mismatch: bool = False,
    ) -> Dict[str, str]:
        """Build a repo-local pytest environment with stable import paths."""
        env = dict(os.environ)
        extra_paths = [str(repo_path.resolve())]
        for candidate in ("src", "lib"):
            path = repo_path / candidate
            if path.exists() and path.is_dir():
                extra_paths.append(str(path))
        existing = env.get("PYTHONPATH", "")
        if existing:
            extra_paths.append(existing)

        deduped: List[str] = []
        seen: Set[str] = set()
        for entry in extra_paths:
            if entry and entry not in seen:
                seen.add(entry)
                deduped.append(entry)
        env["PYTHONPATH"] = os.pathsep.join(deduped)

        if ignore_import_mismatch:
            env["PY_IGNORE_IMPORTMISMATCH"] = "1"
        else:
            env.pop("PY_IGNORE_IMPORTMISMATCH", None)
        return env

    def _should_retry_coverage_importlib(self, result: subprocess.CompletedProcess) -> bool:
        """Heuristic for retrying coverage collection with safer pytest flags."""
        if result.returncode == 0:
            return False
        output = f"{result.stdout}\n{result.stderr}".lower()
        return (
            result.returncode in {2, 4}
            or "import file mismatch" in output
            or "importerror while loading conftest" in output
            or "pytest-warnings plugin did not import" in output
            or "cannot disable warnings logging" in output
            or "modulenotfounderror" in output
            or "no module named" in output
        )

    def _resolve_selected_test_id(
        self,
        selected_test: str,
        *,
        repo_path: Path,
        nodeid_to_test_id: Dict[str, str],
    ) -> str:
        """Resolve a selected pytest nodeid to a graph test id."""
        normalized = self._normalize_nodeid_path(selected_test.replace("\\", "/"), repo_path.resolve())
        base = self._strip_param_suffix(normalized)
        return str(
            nodeid_to_test_id.get(normalized)
            or nodeid_to_test_id.get(base)
            or nodeid_to_test_id.get(Path(base.split("::", 1)[0]).name + ("::" + base.split("::", 1)[1] if "::" in base else ""))
            or ""
        )

    def _expand_selected_tests_for_coverage(
        self,
        *,
        selected_tests: List[str],
        test_nodes: List[Dict],
    ) -> List[str]:
        """Expand file-path test selections into runnable pytest nodeids."""
        expanded: List[str] = []
        seen: Set[str] = set()
        nodeids_by_file: Dict[str, List[str]] = defaultdict(list)

        for test in test_nodes:
            test_file = str(test.get("test_file") or "").strip().replace("\\", "/")
            test_name = str(test.get("test_name") or "").strip()
            if not test_file or not test_name:
                continue
            nodeids_by_file[test_file].append(f"{test_file}::{test_name}")

        max_expanded_per_file = max(
            1,
            int(os.getenv("GRAPH_TARGETED_COVERAGE_MAX_EXPANDED_TESTS_PER_FILE", "8")),
        )

        for selected_test in self._normalize_selected_tests(selected_tests):
            if "::" in selected_test:
                if selected_test not in seen:
                    seen.add(selected_test)
                    expanded.append(selected_test)
                continue

            matching_nodeids = list(nodeids_by_file.get(selected_test, []))
            if not matching_nodeids:
                normalized_path = selected_test.lstrip("./")
                matching_nodeids = list(nodeids_by_file.get(normalized_path, []))

            if not matching_nodeids:
                if selected_test not in seen:
                    seen.add(selected_test)
                    expanded.append(selected_test)
                continue

            if len(matching_nodeids) > max_expanded_per_file:
                self._warn(
                    "Targeted coverage expansion capped for "
                    f"{selected_test} at {max_expanded_per_file} tests"
                )
            for nodeid in matching_nodeids[:max_expanded_per_file]:
                if nodeid in seen:
                    continue
                seen.add(nodeid)
                expanded.append(nodeid)

        return expanded

    def _extract_single_test_coverage_from_data_file(
        self,
        *,
        repo_path: Path,
        coverage_file: Path,
    ) -> Dict[str, float]:
        """Extract file coverage ratios from a single-test coverage data file."""
        repo_root = Path(repo_path).resolve()
        cov_data = CoverageData(basename=str(coverage_file))
        cov_data.read()
        cov = Coverage(data_file=str(coverage_file))
        cov.load()

        per_file: Dict[str, float] = {}
        for measured_file in cov_data.measured_files():
            rel_path = self._to_repo_relative_path(measured_file, repo_root)
            if not rel_path or not rel_path.endswith(".py") or self._is_test_path(rel_path):
                continue

            executed_lines = set(cov_data.lines(measured_file) or [])
            if not executed_lines:
                continue

            try:
                _, statements, _, _, _ = cov.analysis2(measured_file)
                executable_lines = set(statements or [])
            except Exception:
                executable_lines = set()

            denominator = len(executable_lines) if executable_lines else len(executed_lines)
            if denominator <= 0:
                continue

            covered_count = len(executed_lines & executable_lines) if executable_lines else len(executed_lines)
            coverage_ratio = covered_count / float(denominator)
            if coverage_ratio > 0.0:
                per_file[rel_path] = max(float(per_file.get(rel_path, 0.0) or 0.0), coverage_ratio)

        return per_file

    def _run_targeted_coverage_fallback(
        self,
        repo_path: Path,
        *,
        selected_tests: List[str],
        coverage_timeout: int,
        extra_args: str = "",
    ) -> Dict[str, Dict[str, float]]:
        """
        Collect bounded per-test coverage without pytest-cov.

        This is slower than the shared pytest-cov path but more robust for the
        small targeted regression-test sets used inside the GraphRAG loop.
        """
        normalized_selected_tests = self._normalize_selected_tests(selected_tests or [])
        if not normalized_selected_tests:
            return {}

        repo_root = Path(repo_path).resolve()
        test_nodes = self._get_test_nodes()
        nodeid_to_test_id = self._build_test_nodeid_index(test_nodes)
        expanded_selected_tests = self._expand_selected_tests_for_coverage(
            selected_tests=normalized_selected_tests,
            test_nodes=test_nodes,
        )
        coverage_by_test: Dict[str, Dict[str, float]] = {}
        deadline = time.monotonic() + max(1, int(coverage_timeout))

        attempt_specs = [
            {
                "label": "default",
                "extra_args": [],
                "ignore_import_mismatch": False,
            },
            {
                "label": "importlib_retry",
                "extra_args": ["--import-mode=importlib", "--cache-clear"],
                "ignore_import_mismatch": True,
            },
            {
                "label": "warnings_importlib_retry",
                "extra_args": ["-p", "no:warnings", "--import-mode=importlib", "--cache-clear"],
                "ignore_import_mismatch": True,
            },
        ]

        for index, selected_test in enumerate(expanded_selected_tests, start=1):
            remaining = int(deadline - time.monotonic())
            if remaining <= 0:
                self._warn(f"Coverage run timed out after {coverage_timeout}s")
                break

            test_id = self._resolve_selected_test_id(
                selected_test,
                repo_path=repo_root,
                nodeid_to_test_id=nodeid_to_test_id,
            )
            if not test_id:
                self._warn(f"Skipping targeted coverage for unmapped test: {selected_test}")
                continue

            data_file = repo_root / f".coverage.graphrag_targeted_{os.getpid()}_{index}"
            if data_file.exists():
                data_file.unlink()

            result: Optional[subprocess.CompletedProcess] = None
            produced_data = False
            try:
                for attempt_index, attempt in enumerate(attempt_specs):
                    remaining = int(deadline - time.monotonic())
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(cmd=["coverage", "run"], timeout=coverage_timeout)

                    cmd = [
                        sys.executable,
                        "-m",
                        "coverage",
                        "run",
                        f"--data-file={data_file}",
                        "-m",
                        "pytest",
                        "-q",
                    ]
                    if attempt["extra_args"]:
                        cmd.extend(list(attempt["extra_args"]))
                    if extra_args:
                        cmd.extend(shlex.split(extra_args))
                    cmd.append(selected_test)

                    result = subprocess.run(
                        cmd,
                        cwd=repo_root,
                        capture_output=True,
                        text=True,
                        timeout=remaining,
                        check=False,
                        env=self._normalized_pytest_env(
                            repo_root,
                            ignore_import_mismatch=bool(attempt["ignore_import_mismatch"]),
                        ),
                    )

                    if data_file.exists():
                        file_coverage = self._extract_single_test_coverage_from_data_file(
                            repo_path=repo_root,
                            coverage_file=data_file,
                        )
                        if file_coverage:
                            coverage_by_test.setdefault(test_id, {})
                            for rel_path, coverage_ratio in file_coverage.items():
                                prev = float(coverage_by_test[test_id].get(rel_path, 0.0) or 0.0)
                                coverage_by_test[test_id][rel_path] = max(prev, float(coverage_ratio))
                        produced_data = True
                        break

                    has_retry = attempt_index + 1 < len(attempt_specs)
                    if not has_retry or result is None or not self._should_retry_coverage_importlib(result):
                        break

                    self._warn(
                        "targeted coverage fallback pytest exited with code "
                        f"{result.returncode}; retrying with safer pytest flags"
                    )
            finally:
                try:
                    if data_file.exists():
                        data_file.unlink()
                except OSError:
                    pass

            if result is not None and result.returncode != 0 and not produced_data:
                self._warn(
                    "targeted coverage fallback failed for "
                    f"{selected_test} (exit={result.returncode})"
                )

        return coverage_by_test

    def _run_coverage(
        self,
        repo_path: Path,
        *,
        selected_tests: Optional[List[str]] = None,
        coverage_timeout: Optional[int] = None,
    ) -> Dict[str, Dict[str, float]]:
        """Run pytest with coverage contexts and return per-test file coverage ratios."""
        coverage_file = repo_path / ".coverage"
        effective_timeout = int(
            coverage_timeout
            if coverage_timeout is not None
            else getattr(config.analysis, "coverage_timeout_seconds", 600)
        )
        max_test_files = max(0, int(getattr(config.analysis, "coverage_max_test_files", 80)))
        sample_mode = str(getattr(config.analysis, "coverage_test_sample_mode", "spread") or "spread")
        extra_args = str(getattr(config.analysis, "coverage_pytest_extra_args", "") or "")

        try:
            if coverage_file.exists():
                coverage_file.unlink()

            normalized_selected_tests = self._normalize_selected_tests(selected_tests or [])
            selected_scope: List[str] = []
            if normalized_selected_tests:
                selected_scope = normalized_selected_tests
                logger.info(
                    "Coverage scope bounded to %d targeted tests",
                    len(normalized_selected_tests),
                )
            else:
                selected_test_paths = self._select_coverage_test_paths(
                    repo_path=repo_path,
                    max_test_files=max_test_files,
                    sample_mode=sample_mode,
                )
                if selected_test_paths:
                    selected_scope = selected_test_paths
                    logger.info(
                        "Coverage scope bounded to %d test files (mode=%s, max=%d)",
                        len(selected_test_paths),
                        sample_mode,
                        max_test_files,
                    )
                else:
                    logger.info("Coverage scope uses full test discovery")

            base_cmd = [
                sys.executable,
                "-m",
                "pytest",
                "--cov=.",
                "--cov-context=test",
                "--cov-report=",
                "-q",
            ]
            if extra_args:
                base_cmd.extend(shlex.split(extra_args))
            base_cmd.extend(selected_scope)

            attempt_specs = [
                {
                    "label": "default",
                    "extra_args": [],
                    "ignore_import_mismatch": False,
                },
                {
                    "label": "importlib_retry",
                    "extra_args": ["--import-mode=importlib", "--cache-clear"],
                    "ignore_import_mismatch": True,
                },
                {
                    "label": "warnings_importlib_retry",
                    "extra_args": ["-p", "no:warnings", "--import-mode=importlib", "--cache-clear"],
                    "ignore_import_mismatch": True,
                },
            ]
            deadline = time.monotonic() + max(1, effective_timeout)
            result: Optional[subprocess.CompletedProcess] = None
            for attempt_index, attempt in enumerate(attempt_specs):
                remaining = int(deadline - time.monotonic())
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(
                        cmd=base_cmd,
                        timeout=effective_timeout,
                    )

                attempt_cmd = list(base_cmd)
                if attempt["extra_args"]:
                    insertion_index = 3
                    attempt_cmd[insertion_index:insertion_index] = attempt["extra_args"]

                result = subprocess.run(
                    attempt_cmd,
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=remaining,
                    check=False,
                    env=self._normalized_pytest_env(
                        repo_path,
                        ignore_import_mismatch=bool(attempt["ignore_import_mismatch"])
                    ),
                )

                if result.returncode == 0 or coverage_file.exists():
                    break

                has_retry = attempt_index + 1 < len(attempt_specs)
                if not has_retry or not self._should_retry_coverage_importlib(result):
                    break

                self._warn(
                    "pytest --cov exited with code "
                    f"{result.returncode}; retrying with safer pytest flags"
                )

            if result is not None and result.returncode != 0:
                self._warn(f"pytest --cov exited with code {result.returncode}")

            if not coverage_file.exists():
                if normalized_selected_tests:
                    self._warn(
                        "No .coverage file produced by pytest-cov; "
                        "falling back to targeted per-test coverage"
                    )
                    fallback_coverage = self._run_targeted_coverage_fallback(
                        repo_path,
                        selected_tests=normalized_selected_tests,
                        coverage_timeout=effective_timeout,
                        extra_args=extra_args,
                    )
                    if fallback_coverage:
                        return fallback_coverage
                self._warn("No .coverage file produced by pytest-cov")
                return {}

            cov_data = CoverageData(basename=str(coverage_file))
            cov_data.read()

            return self._extract_per_test_coverage(repo_path, cov_data)

        except subprocess.TimeoutExpired:
            self._warn(f"Coverage run timed out after {effective_timeout}s")
        except Exception as e:
            self._warn(f"Error running coverage: {e}")

        return {}

    def get_impacted_tests_by_coverage(
        self,
        repo_path: Path,
        changed_files: List[str],
        impact_threshold: float = 0.05,
        max_tests: int = 200,
    ) -> List[Dict[str, object]]:
        """
        Find impacted tests by runtime coverage intersection against changed files.

        This strategy bypasses graph relation traversal and uses coverage contexts:
        test -> covered files. Any test touching a changed file is considered impacted.
        """
        self._warnings = []
        normalized_changed = self._normalize_changed_files(repo_path, changed_files)
        if not normalized_changed:
            return []

        coverage_data = self._run_coverage(repo_path)
        if not coverage_data:
            return []

        test_nodes = {str(t.get("test_id")): t for t in self._get_test_nodes() if t.get("test_id")}
        impacted: List[Dict[str, object]] = []

        for test_id, file_coverage in coverage_data.items():
            matched = [
                (file_path, float(coverage_ratio))
                for file_path, coverage_ratio in file_coverage.items()
                if file_path in normalized_changed
            ]
            if not matched:
                continue

            matched.sort(key=lambda item: item[1], reverse=True)
            max_cov = matched[0][1]
            if max_cov < impact_threshold:
                continue

            node = test_nodes.get(test_id, {})
            test_name = str(node.get("test_name") or "")
            test_file = str(node.get("test_file") or "")
            if not test_name:
                # test_id format fallback: test::<file>::<function>:<line>
                test_name = str(test_id).split("::")[-1]

            impacted.append(
                {
                    "test_id": test_id,
                    "test_name": test_name,
                    "test_file": test_file,
                    "impact_score": max_cov,
                    "impact_reason": "coverage_diff",
                    "matched_changed_files": [path for path, _ in matched[:5]],
                    "coverage_hits": len(matched),
                }
            )

        impacted.sort(
            key=lambda row: (
                float(row.get("impact_score", 0.0)),
                int(row.get("coverage_hits", 0)),
            ),
            reverse=True,
        )
        if max_tests > 0:
            impacted = impacted[:max_tests]
        return impacted

    def _normalize_changed_files(self, repo_path: Path, changed_files: List[str]) -> Set[str]:
        """Normalize changed file paths to repository-relative Python paths."""
        repo_root = Path(repo_path).resolve()
        normalized: Set[str] = set()
        for raw in changed_files:
            if not raw:
                continue
            path = Path(raw)
            if path.is_absolute():
                try:
                    rel = path.resolve().relative_to(repo_root)
                    rel_path = str(rel)
                except ValueError:
                    continue
            else:
                rel_path = str(path).lstrip("./")
            rel_path = rel_path.replace("\\", "/")
            if rel_path.endswith(".py"):
                normalized.add(rel_path)
        return normalized

    def _select_coverage_test_paths(
        self,
        *,
        repo_path: Path,
        max_test_files: int,
        sample_mode: str,
    ) -> List[str]:
        """Select repository-relative test file paths to bound coverage runtime."""
        if max_test_files <= 0:
            return []

        test_nodes = self._get_test_nodes()
        unique_files = sorted(
            {
                str(test.get("test_file") or "").replace("\\", "/")
                for test in test_nodes
                if test.get("test_file")
            }
        )
        if not unique_files:
            return []

        existing_files: List[str] = []
        for rel_path in unique_files:
            candidate = (repo_path / rel_path).resolve()
            try:
                if candidate.is_file():
                    existing_files.append(rel_path)
            except Exception:
                continue

        if len(existing_files) <= max_test_files:
            return existing_files

        if sample_mode == "head":
            return existing_files[:max_test_files]

        # spread mode: sample evenly across the sorted test-file list for better breadth.
        selected: List[str] = []
        step = len(existing_files) / float(max_test_files)
        cursor = 0.0
        for _ in range(max_test_files):
            idx = min(len(existing_files) - 1, int(cursor))
            selected.append(existing_files[idx])
            cursor += step
        return list(dict.fromkeys(selected))

    def _extract_per_test_coverage(self, repo_path: Path, cov_data: CoverageData) -> Dict[str, Dict[str, float]]:
        """
        Extract per-test coverage from coverage.py dynamic contexts.

        Returns mapping:
            test_id -> {relative_source_file: coverage_ratio_0_1}
        """
        test_nodes = self._get_test_nodes()
        if not test_nodes:
            return {}

        nodeid_to_test_id = self._build_test_nodeid_index(test_nodes)
        context_to_test_id = self._map_contexts_to_test_ids(
            contexts=cov_data.measured_contexts() or set(),
            repo_path=repo_path,
            nodeid_to_test_id=nodeid_to_test_id,
        )

        repo_root = Path(repo_path).resolve()
        test_coverage: Dict[str, Dict[str, float]] = {}

        for measured_file in cov_data.measured_files():
            rel_path = self._to_repo_relative_path(measured_file, repo_root)
            if not rel_path or not rel_path.endswith(".py"):
                continue
            if self._is_test_path(rel_path):
                continue

            all_lines = set(cov_data.lines(measured_file) or [])
            if not all_lines:
                continue

            contexts_by_line = cov_data.contexts_by_lineno(measured_file) or {}
            per_test_lines: Dict[str, Set[int]] = {}

            for line_no, contexts in contexts_by_line.items():
                for ctx in contexts:
                    test_id = context_to_test_id.get(ctx)
                    if not test_id:
                        # Fallback for cases where coverage includes expanded context labels
                        root_ctx = ctx.split("|", 1)[0]
                        test_id = context_to_test_id.get(root_ctx)
                    if test_id:
                        per_test_lines.setdefault(test_id, set()).add(line_no)

            for test_id, lines in per_test_lines.items():
                coverage_ratio = len(lines) / max(1, len(all_lines))
                if coverage_ratio <= 0:
                    continue
                if test_id not in test_coverage:
                    test_coverage[test_id] = {}
                prev = test_coverage[test_id].get(rel_path, 0.0)
                test_coverage[test_id][rel_path] = max(prev, coverage_ratio)

        return test_coverage

    def _get_test_nodes(self) -> List[Dict]:
        """Fetch test nodes from graph."""
        with self.db.driver.session(database=config.neo4j.database) as session:
            result = self._run_query(
                session,
                """
                MATCH (t:Test)
                RETURN t.id as test_id, t.name as test_name, t.file_path as test_file
                """
            )
            return result.data()

    def _build_test_nodeid_index(self, test_nodes: List[Dict]) -> Dict[str, str]:
        """Build lookup from pytest nodeid to graph test id."""
        nodeid_map: Dict[str, str] = {}

        for test in test_nodes:
            test_id = test.get("test_id")
            test_name = (test.get("test_name") or "").strip()
            test_file = (test.get("test_file") or "").strip().replace("\\", "/")
            if not test_id or not test_name or not test_file:
                continue

            nodeid = f"{test_file}::{test_name}"
            nodeid_map[nodeid] = test_id
            nodeid_map[self._strip_param_suffix(nodeid)] = test_id

            file_name = Path(test_file).name
            short_nodeid = f"{file_name}::{test_name}"
            nodeid_map.setdefault(short_nodeid, test_id)
            nodeid_map.setdefault(self._strip_param_suffix(short_nodeid), test_id)

        return nodeid_map

    def _map_contexts_to_test_ids(
        self,
        contexts: Set[str],
        repo_path: Path,
        nodeid_to_test_id: Dict[str, str],
    ) -> Dict[str, str]:
        """Map coverage contexts to known test ids."""
        context_map: Dict[str, str] = {}
        repo_root = Path(repo_path).resolve()

        for ctx in contexts:
            if not ctx:
                continue
            # pytest-cov context format: <nodeid>|<phase>
            root = ctx.split("|", 1)[0].strip()
            if not root:
                continue

            normalized_root = root.replace("\\", "/")
            normalized_root = self._normalize_nodeid_path(normalized_root, repo_root)
            base_root = self._strip_param_suffix(normalized_root)

            test_id = (
                nodeid_to_test_id.get(normalized_root)
                or nodeid_to_test_id.get(base_root)
            )
            if test_id:
                context_map[ctx] = test_id
                context_map[root] = test_id
                context_map[normalized_root] = test_id
                context_map[base_root] = test_id

        return context_map

    def _normalize_nodeid_path(self, nodeid: str, repo_root: Path) -> str:
        """Normalize pytest nodeid path component to repo-relative path."""
        if "::" not in nodeid:
            return nodeid
        file_part, rest = nodeid.split("::", 1)
        file_path = Path(file_part)

        if file_path.is_absolute():
            try:
                rel = file_path.resolve().relative_to(repo_root)
                file_part = str(rel)
            except ValueError:
                return nodeid

        return f"{str(file_part).replace('\\\\', '/')}::{rest}"

    def _to_repo_relative_path(self, path_str: str, repo_root: Path) -> Optional[str]:
        """Convert coverage file path to repository-relative path."""
        path = Path(path_str)
        if path.is_absolute():
            try:
                rel = path.resolve().relative_to(repo_root)
                return str(rel).replace("\\", "/")
            except ValueError:
                return None

        return str(path).replace("\\", "/")

    def _is_test_path(self, relative_path: str) -> bool:
        """Heuristic check for test files based on config patterns and path segments."""
        file_name = Path(relative_path).name
        if any(fnmatch(file_name, pattern) for pattern in config.analysis.test_file_patterns):
            return True
        parts = [part.lower() for part in Path(relative_path).parts]
        return "tests" in parts or file_name.startswith("test_")

    def _strip_param_suffix(self, nodeid: str) -> str:
        """Strip pytest parametrization suffix from nodeid."""
        return re.sub(r"\[[^\]]+\]$", "", nodeid)

    def _link_by_static_analysis(self, repo_path: Path) -> int:
        """Link tests to code by analyzing function calls from test files.

        Strategy: Find Test functions that CALL production Functions.
        Since Test nodes are created alongside Function nodes for test functions,
        we match them by name/file_path and trace CALLS relationships.
        """
        link_rows: List[Dict[str, object]] = []

        with self.db.driver.session(database=config.neo4j.database) as session:
            # Find Test functions that CALL production Functions
            # Test nodes share function_name and file_path with their Function nodes
            result = self._run_query(
                session,
                """
                MATCH (t:Test)
                MATCH (tf:Function)
                WHERE tf.name = t.function_name AND tf.file_path = t.file_path
                MATCH (tf)-[:CALLS]->(pf:Function)
                WHERE NOT pf.file_path CONTAINS 'test'
                RETURN DISTINCT t.id as test_id, pf.id as function_id, pf.name as function_name
                """
            )

            for record in result:
                link_rows.append(
                    {
                        "test_id": record["test_id"],
                        "target_id": record["function_id"],
                        "target_type": "Function",
                        "coverage": 0.8,
                        "link_source": "static",
                        "link_confidence": 0.8,
                    }
                )
                logger.debug(f"Static link: {record['test_id']} -> {record['function_name']}")

        self.db.create_tests_relationships_batch(link_rows)
        return len(link_rows)


class TestRunner:
    """Runs tests and tracks results"""

    def __init__(self):
        self.db = get_db()

    def run_tests(
        self,
        repo_path: Path,
        tests: Optional[List[str]] = None,
        pytest_args: Optional[List[str]] = None
    ) -> Dict:
        """Run tests and return results"""
        logger.info(f"Running tests in: {repo_path}")

        if pytest_args is None:
            pytest_args = []

        # Build pytest command
        cmd = ["pytest", "-v", "--tb=short"]
        cmd.extend(pytest_args)

        if tests:
            # Run specific tests
            cmd.extend(tests)
            logger.info(f"Running {len(tests)} specific tests")
        else:
            logger.info("Running all tests")

        # Run tests
        try:
            result = subprocess.run(
                cmd,
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=600
            )

            # Parse results
            test_results = self._parse_pytest_output(result.stdout)

            passed = sum(1 for t in test_results if t["status"] == "passed")
            failed = sum(1 for t in test_results if t["status"] == "failed")
            skipped = sum(1 for t in test_results if t["status"] == "skipped")
            # In this pipeline, tests passed into run_tests are expected to pass after the patch.
            # A failing executed test is treated as a regression signal for iteration scoring.
            regressions = failed

            return {
                "success": result.returncode == 0,
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "regressions": regressions,
                "test_results": test_results,
                "stdout": result.stdout,
                "stderr": result.stderr,
                # Include error info when pytest fails (returncode != 0)
                "error": result.stderr if result.returncode != 0 else None
            }

        except subprocess.TimeoutExpired:
            logger.error("Test run timed out")
            return {
                "success": False,
                "passed": 0,
                "failed": len(tests or []),
                "skipped": 0,
                "regressions": len(tests or []),
                "test_results": [],
                "error": "Timeout"
            }
        except Exception as e:
            logger.error(f"Error running tests: {e}")
            return {
                "success": False,
                "passed": 0,
                "failed": len(tests or []),
                "skipped": 0,
                "regressions": len(tests or []),
                "test_results": [],
                "error": str(e)
            }

    def _parse_pytest_output(self, output: str) -> List[Dict]:
        """Parse pytest output to extract test results"""
        test_results = []

        # Simple regex parsing (could be improved with pytest-json-report plugin)
        lines = output.splitlines()
        for line in lines:
            # Match lines like: "tests/test_foo.py::test_bar PASSED"
            match = re.match(r"^(.+?)::(test_\S+)\s+(PASSED|FAILED|SKIPPED)", line)
            if match:
                test_file, test_name, status = match.groups()
                test_results.append({
                    "file": test_file,
                    "name": test_name,
                    "status": status.lower(),
                    "full_name": f"{test_file}::{test_name}"
                })

        return test_results
