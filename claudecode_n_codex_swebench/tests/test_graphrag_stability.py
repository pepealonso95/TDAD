import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from mcp_server.graph_builder import GraphBuilder
from mcp_server.impact_analyzer import ImpactAnalyzer
from mcp_server.server import _merge_impacted_tests
from mcp_server.test_linker import TestLinker
from utils.graphrag_interface import create_graphrag_interface
from utils.graphrag_local_interface import GraphRAGLocalInterface
from utils.mcp_graphrag_interface import GraphRAGMCPInterface
from utils.qwen_mini_interface import QwenMiniInterface
from utils.qwen_mini_interface_graphrag_tdd import QwenMiniInterfaceGraphRAGTDD
from utils.test_runtime_manager import TestRuntimeManager


def test_impact_analyzer_normalize_changed_files():
    analyzer = object.__new__(ImpactAnalyzer)

    changed = analyzer._normalize_changed_files(
        Path("/tmp/repo"),
        [
            "/tmp/repo/pkg/a.py",
            "pkg/b.py",
            "./pkg/c.py",
            "/tmp/other/outside.py",
            "README.md",
            "pkg/b.py",
        ],
    )

    assert changed == ["pkg/a.py", "pkg/b.py", "pkg/c.py"]


def test_impact_analyzer_applies_line_boost(monkeypatch):
    analyzer = object.__new__(ImpactAnalyzer)

    monkeypatch.setattr(
        analyzer,
        "_find_directly_tested_functions",
        lambda changed_files: [
            {
                "test_id": "t1",
                "test_name": "test_alpha",
                "test_file": "tests/test_alpha.py",
                "target_file": "pkg/a.py",
            }
        ],
    )
    monkeypatch.setattr(analyzer, "_find_transitive_dependencies", lambda changed_files: [])
    monkeypatch.setattr(analyzer, "_find_coverage_dependencies", lambda changed_files: [])
    monkeypatch.setattr(analyzer, "_find_import_dependencies", lambda changed_files: [])
    monkeypatch.setattr(
        analyzer,
        "_resolve_changed_symbols",
        lambda **kwargs: ([], list(kwargs.get("changed_files") or [])),
    )
    monkeypatch.setattr(
        analyzer,
        "_get_changed_lines",
        lambda repo_path, changed_files, base_commit: {"pkg/a.py": set(range(1, 51))},
    )

    impacted = analyzer.get_impacted_tests(
        repo_path=Path("/tmp/repo"),
        changed_files=["pkg/a.py"],
        impact_threshold=0.0,
    )

    assert len(impacted) == 1
    assert impacted[0]["impact_score"] == 1.0
    assert impacted[0]["line_change_count"] == 50
    assert "score_components" in impacted[0]
    assert impacted[0]["confidence"] >= 0.0


def test_impact_analyzer_includes_diagnostics_and_traversal(monkeypatch):
    analyzer = object.__new__(ImpactAnalyzer)

    monkeypatch.setattr(
        analyzer,
        "_find_directly_tested_functions",
        lambda changed_files: [
            {
                "test_id": "t2",
                "test_name": "test_beta",
                "test_file": "tests/test_beta.py",
                "target_file": "pkg/b.py",
                "link_confidence": 0.9,
                "traversal_path": ["pkg/b.py::beta:10"],
            }
        ],
    )
    monkeypatch.setattr(analyzer, "_find_transitive_dependencies", lambda changed_files: [])
    monkeypatch.setattr(analyzer, "_find_coverage_dependencies", lambda changed_files: [])
    monkeypatch.setattr(analyzer, "_find_import_dependencies", lambda changed_files: [])
    monkeypatch.setattr(
        analyzer,
        "_resolve_changed_symbols",
        lambda **kwargs: ([], list(kwargs.get("changed_files") or [])),
    )
    monkeypatch.setattr(
        analyzer,
        "_get_changed_lines",
        lambda repo_path, changed_files, base_commit: {"pkg/b.py": {1, 2, 3}},
    )

    impacted = analyzer.get_impacted_tests(
        repo_path=Path("/tmp/repo"),
        changed_files=["pkg/b.py"],
        impact_threshold=0.0,
        strategy="conservative",
    )
    diagnostics = analyzer.get_last_diagnostics()

    assert len(impacted) == 1
    assert impacted[0]["traversal_path"] == ["pkg/b.py::beta:10"]
    assert diagnostics["strategy"] == "conservative"
    assert diagnostics["selected_count"] == 1


def test_graphrag_cache_check_uses_graph_identity(monkeypatch):
    interface = object.__new__(GraphRAGMCPInterface)
    interface.server_url = "http://unused"

    def fake_get(*args, **kwargs):
        return SimpleNamespace(
            status_code=200,
            json=lambda: {
                "success": True,
                "total_nodes": 123,
                "graph_identity": "owner/repo@abc123",
                "path_format": "relative",
            },
        )

    monkeypatch.setattr("utils.mcp_graphrag_interface.requests.get", fake_get)
    assert interface._check_graph_exists("owner/repo@abc123")
    assert not interface._check_graph_exists("owner/repo@different")


def test_graphrag_cache_check_can_require_fresh_fingerprint(monkeypatch):
    interface = object.__new__(GraphRAGMCPInterface)
    interface.server_url = "http://unused"

    def fake_get(*args, **kwargs):
        return SimpleNamespace(
            status_code=200,
            json=lambda: {
                "success": True,
                "total_nodes": 42,
                "graph_identity": "owner/repo@abc123",
                "repo_fingerprint": "abc123:dirty123",
                "path_format": "relative",
            },
        )

    monkeypatch.setattr("utils.mcp_graphrag_interface.requests.get", fake_get)
    assert interface._check_graph_exists("owner/repo@abc123")
    assert not interface._check_graph_exists(
        "owner/repo@abc123",
        require_fresh_graph=True,
        expected_repo_fingerprint="abc123:clean",
    )
    assert interface._check_graph_exists(
        "owner/repo@abc123",
        require_fresh_graph=True,
        expected_repo_fingerprint="abc123:dirty123",
    )


def test_graphrag_tiered_selection_prefers_high_impact():
    interface = object.__new__(GraphRAGMCPInterface)

    selected = interface._select_tiered_tests(
        impacted_tests=[
            {"test_id": "low", "impact_score": 0.2},
            {"test_id": "mid", "impact_score": 0.6},
            {"test_id": "high", "impact_score": 0.95},
        ],
        max_tests=2,
    )

    assert [t["test_id"] for t in selected] == ["high", "mid"]


def test_graphrag_tiered_selection_handles_missing_test_id_dedup():
    interface = object.__new__(GraphRAGMCPInterface)
    selected = interface._select_tiered_tests(
        impacted_tests=[
            {"test_file": "tests/test_mod.py", "test_name": "test_alpha", "impact_score": 0.9},
            {"test_file": "tests/test_mod.py", "test_name": "test_alpha", "impact_score": 0.8},
            {"test_file": "tests/test_other.py", "test_name": "test_beta", "impact_score": 0.7},
        ],
        max_tests=5,
    )
    assert len(selected) == 2
    assert interface._build_test_identifier(selected[0]) == "tests/test_mod.py::test_alpha"
    assert interface._build_test_identifier(selected[1]) == "tests/test_other.py::test_beta"


def test_test_linker_context_mapping_and_param_strip():
    linker = object.__new__(TestLinker)
    test_nodes = [
        {"test_id": "t1", "test_name": "test_alpha", "test_file": "tests/test_mod.py"},
    ]
    nodeid_index = linker._build_test_nodeid_index(test_nodes)

    context_map = linker._map_contexts_to_test_ids(
        contexts={
            "tests/test_mod.py::test_alpha[param]|run",
            "tests/test_mod.py::test_alpha[param]|teardown",
        },
        repo_path=Path("/tmp/repo"),
        nodeid_to_test_id=nodeid_index,
    )

    assert context_map["tests/test_mod.py::test_alpha[param]|run"] == "t1"
    assert context_map["tests/test_mod.py::test_alpha[param]|teardown"] == "t1"


def test_test_linker_extract_per_test_coverage():
    linker = object.__new__(TestLinker)

    class FakeCoverageData:
        def measured_contexts(self):
            return {"tests/test_mod.py::test_alpha|run"}

        def measured_files(self):
            return {"pkg/a.py", "tests/test_mod.py"}

        def lines(self, file_path):
            if file_path == "pkg/a.py":
                return [1, 2, 3, 4]
            return [1]

        def contexts_by_lineno(self, file_path):
            if file_path == "pkg/a.py":
                return {
                    1: ["tests/test_mod.py::test_alpha|run"],
                    2: ["tests/test_mod.py::test_alpha|run"],
                }
            return {}

    # Patch DB-driven call to avoid real Neo4j dependency in unit test.
    linker._get_test_nodes = lambda: [
        {"test_id": "t1", "test_name": "test_alpha", "test_file": "tests/test_mod.py"},
    ]

    coverage = linker._extract_per_test_coverage(Path("/tmp/repo"), FakeCoverageData())
    assert "t1" in coverage
    assert "pkg/a.py" in coverage["t1"]
    assert coverage["t1"]["pkg/a.py"] == 0.5


def test_merge_impacted_tests_hybrid_corroboration_bonus():
    graph = [
        {
            "test_id": "t1",
            "test_name": "test_alpha",
            "test_file": "tests/test_alpha.py",
            "impact_score": 0.80,
            "impact_reason": "Graph traversal impact",
        }
    ]
    coverage = [
        {
            "test_id": "t1",
            "test_name": "test_alpha",
            "test_file": "tests/test_alpha.py",
            "impact_score": 0.70,
            "impact_reason": "coverage_diff",
            "matched_changed_files": ["pkg/a.py"],
        },
        {
            "test_id": "t2",
            "test_name": "test_beta",
            "test_file": "tests/test_beta.py",
            "impact_score": 0.65,
            "impact_reason": "coverage_diff",
        },
    ]

    merged = _merge_impacted_tests(graph, coverage)
    assert len(merged) == 2
    assert merged[0]["test_id"] == "t1"
    assert merged[0]["impact_source"] == "graph+coverage"
    assert merged[0]["impact_score"] > 0.80


def test_graphrag_build_test_identifier_from_graph_test_id():
    interface = object.__new__(GraphRAGMCPInterface)
    identifier = interface._build_test_identifier(
        {"test_id": "test::tests/test_mod.py::test_alpha:42"}
    )
    assert identifier == "tests/test_mod.py::test_alpha"


def test_graphrag_iterative_forwards_strategy_and_uses_identifier_fallback(monkeypatch):
    interface = object.__new__(GraphRAGMCPInterface)
    captured = {}

    def fake_get_impacted_tests(repo_path, changed_files, impact_threshold=0.3, strategy=None, **kwargs):
        captured["strategy"] = strategy
        return {
            "success": True,
            "tests": [
                {
                    "test_id": "test::tests/test_mod.py::test_alpha:1",
                    "impact_score": 0.9,
                    "impact_reason": "coverage_diff",
                }
            ],
            "total_tests": 1,
            "graph_freshness": "fresh",
            "rebuild_triggered": False,
            "selection_confidence_summary": {"high": 1, "medium": 0, "low": 0},
        }

    def fake_run_tests(repo_path, tests):
        captured["tests"] = tests
        return {
            "success": True,
            "passed": 1,
            "failed": 0,
            "skipped": 0,
            "test_results": [
                {
                    "status": "passed",
                    "file": "tests/test_mod.py",
                    "name": "test_alpha",
                    "full_name": "tests/test_mod.py::test_alpha",
                }
            ],
            "stdout": "",
            "stderr": "",
        }

    monkeypatch.setattr(interface, "get_impacted_tests", fake_get_impacted_tests)
    monkeypatch.setattr(interface, "run_tests", fake_run_tests)

    result = interface.run_impacted_tests_iteratively(
        repo_path="/tmp/repo",
        changed_files=["pkg/a.py"],
        impact_threshold=0.2,
        max_tests=10,
        strategy="hybrid",
    )

    assert captured["strategy"] == "hybrid"
    assert captured["tests"] == ["tests/test_mod.py::test_alpha"]
    assert result["success"] is True
    assert result["tests_run"] == 1


def test_graphrag_iterative_runnable_fallback_when_tiered_has_none(monkeypatch):
    interface = object.__new__(GraphRAGMCPInterface)
    captured = {}

    impacted_tests = [
        {"test_id": "", "test_name": "", "test_file": "", "impact_score": 0.95},
        {
            "test_id": "test::tests/test_mod.py::test_alpha:1",
            "impact_score": 0.7,
            "impact_reason": "coverage_diff",
        },
    ]

    monkeypatch.setattr(
        interface,
        "get_impacted_tests",
        lambda *args, **kwargs: {
            "success": True,
            "tests": impacted_tests,
            "total_tests": 2,
            "graph_freshness": "fresh",
            "rebuild_triggered": False,
            "selection_confidence_summary": {"high": 1, "medium": 1, "low": 0},
        },
    )
    monkeypatch.setattr(interface, "_select_tiered_tests", lambda tests, max_tests: [tests[0]])

    def fake_run_tests(repo_path, tests):
        captured["tests"] = tests
        return {
            "success": True,
            "passed": 1,
            "failed": 0,
            "skipped": 0,
            "test_results": [],
            "stdout": "",
            "stderr": "",
        }

    monkeypatch.setattr(interface, "run_tests", fake_run_tests)

    result = interface.run_impacted_tests_iteratively(
        repo_path="/tmp/repo",
        changed_files=["pkg/a.py"],
        max_tests=5,
        strategy="hybrid",
    )
    assert captured["tests"] == ["tests/test_mod.py::test_alpha"]
    assert result["tests_run"] == 1
    assert result["success"] is True


def test_graphrag_iterative_precision_floor_rejects_low_runnable_ratio(monkeypatch):
    interface = object.__new__(GraphRAGMCPInterface)

    impacted_tests = [
        {"test_file": "tests/test_mod.py", "test_name": "test_alpha", "impact_score": 0.95, "confidence": 0.95},
        {"test_file": "", "test_name": "", "impact_score": 0.9, "confidence": 0.9},
        {"test_file": "", "test_name": "", "impact_score": 0.8, "confidence": 0.8},
        {"test_file": "", "test_name": "", "impact_score": 0.7, "confidence": 0.7},
    ]
    monkeypatch.setattr(
        interface,
        "get_impacted_tests",
        lambda *args, **kwargs: {
            "success": True,
            "tests": impacted_tests,
            "total_tests": len(impacted_tests),
            "graph_freshness": "fresh",
            "rebuild_triggered": False,
            "selection_confidence_summary": {"high": 4, "medium": 0, "low": 0},
        },
    )
    monkeypatch.setattr(interface, "_select_tiered_tests", lambda tests, max_tests: list(tests))
    monkeypatch.setattr(
        interface,
        "run_tests",
        lambda repo_path, tests: {
            "success": True,
            "passed": len(tests),
            "failed": 0,
            "skipped": 0,
            "test_results": [],
            "stdout": "",
            "stderr": "",
        },
    )

    result = interface.run_impacted_tests_iteratively(
        repo_path="/tmp/repo",
        changed_files=["pkg/a.py"],
        max_tests=10,
        strategy="hybrid",
    )
    assert result["tests_run"] == 1
    assert result["selected_count"] == 4
    assert result["runnable_ratio"] < 0.35
    assert result["precision_floor_passed"] is False
    assert result["graph_useful_signal"] is False
    assert result["graph_fallback_reason"] == "low_runnable_ratio"


def test_graphrag_local_get_impacted_tests_skips_refresh_when_freshness_not_required(monkeypatch):
    interface = GraphRAGLocalInterface()

    monkeypatch.setattr(interface, "_resolve_repo_slug", lambda repo_path: "owner/repo")
    monkeypatch.setattr(interface, "_resolve_commit_sha", lambda repo_path: "abc123")
    monkeypatch.setattr(
        interface,
        "_resolve_repo_fingerprint",
        lambda repo_path, commit_sha=None: "abc123:dirty",
    )
    monkeypatch.setattr(interface, "_normalize_changed_files", lambda repo_path, changed: list(changed or []))
    monkeypatch.setattr(
        interface,
        "_get_graph_status",
        lambda **kwargs: {
            "exists": True,
            "fresh": False,
            "staleness_reason": "repo_fingerprint_mismatch",
            "graph_identity": "owner/repo@abc123",
        },
    )
    monkeypatch.setattr(
        interface,
        "_run_impact_query_locally",
        lambda **kwargs: {"tests": [], "warnings": [], "diagnostics": {}},
    )
    monkeypatch.setattr(
        interface,
        "incremental_update",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("incremental refresh should be skipped")),
    )
    monkeypatch.setattr(
        interface,
        "build_graph",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("graph rebuild should be skipped")),
    )

    result = interface.get_impacted_tests(
        repo_path="/tmp/repo",
        changed_files=["pkg/a.py"],
        require_fresh_graph=False,
    )

    assert result["success"] is True
    assert result["rebuild_triggered"] is False
    assert result["graph_freshness"] == "stale"


def test_qwen_score_candidate_penalizes_unreliable_graphrag_execution():
    interface = QwenMiniInterface()

    base_candidate = {
        "prediction": "diff --git a/a.py b/a.py",
        "clean_resolution": False,
        "status": "Submitted",
        "patch_gate_severity": "info",
        "patch_gate_valid": True,
        "patch_gate_reason": "ok",
        "loop_abort_reason": "",
        "changed_lines_total": 4,
        "attempt": 1,
        "f2p_pass_rate": 0.0,
        "p2p_smoke_failures": 0,
        "test_signal_confidence": 1.0,
        "test_signal_reliable": True,
        "format_errors": 0,
        "timeouts": 0,
        "steps": 5,
    }

    reliable = dict(base_candidate)
    reliable["graphrag_metadata"] = {
        "indexed_search_used": True,
        "impacted_total": 10,
        "impacted_run": 5,
        "impacted_success": True,
    }
    unreliable = dict(base_candidate)
    unreliable["graphrag_metadata"] = {
        "indexed_search_used": True,
        "impacted_total": 10,
        "impacted_run": 0,
        "impacted_success": False,
    }

    assert interface._score_candidate(reliable) > interface._score_candidate(unreliable)


def test_qwen_score_candidate_penalizes_non_useful_graph_signal():
    interface = QwenMiniInterface()

    base_candidate = {
        "prediction": "diff --git a/a.py b/a.py",
        "clean_resolution": False,
        "status": "Submitted",
        "patch_gate_severity": "info",
        "patch_gate_valid": True,
        "patch_gate_reason": "ok",
        "loop_abort_reason": "",
        "changed_lines_total": 4,
        "attempt": 1,
        "f2p_pass_rate": 0.0,
        "p2p_smoke_failures": 0,
        "test_signal_confidence": 1.0,
        "test_signal_reliable": True,
        "format_errors": 0,
        "timeouts": 0,
        "steps": 5,
    }

    useful = dict(base_candidate)
    useful["graphrag_metadata"] = {
        "indexed_search_used": True,
        "impacted_total": 4,
        "impacted_run": 2,
        "impacted_success": True,
        "impacted_precision_floor_passed": True,
        "graph_useful_signal": True,
    }
    not_useful = dict(base_candidate)
    not_useful["graphrag_metadata"] = {
        "indexed_search_used": True,
        "impacted_total": 4,
        "impacted_run": 2,
        "impacted_success": True,
        "impacted_precision_floor_passed": False,
        "graph_useful_signal": False,
        "graph_fallback_reason": "low_runnable_ratio",
    }

    assert interface._score_candidate(useful) > interface._score_candidate(not_useful)


def test_graph_builder_clears_when_identity_changes(monkeypatch, tmp_path):
    builder = object.__new__(GraphBuilder)
    builder.repo_root = None
    builder._build_warnings = 0

    class FakeDB:
        def __init__(self):
            self.clear_calls = 0
            self.updated = None

        def get_index_metadata(self):
            return {"graph_identity": "old/repo@abc123"}

        def clear_database(self):
            self.clear_calls += 1

        def create_schema(self):
            return None

        def update_index_metadata(self, **kwargs):
            self.updated = kwargs

    fake_db = FakeDB()
    builder.db = fake_db

    monkeypatch.setattr(builder, "_find_python_files", lambda repo_path: [])
    monkeypatch.setattr(builder, "_parse_files_parallel", lambda python_files, progress_callback=None: [])
    monkeypatch.setattr(builder, "_build_node_payloads", lambda file_infos, repo_path: ([], 0, 0))
    monkeypatch.setattr(builder, "_persist_node_payloads", lambda payloads: None)
    monkeypatch.setattr(builder, "_create_relationships", lambda file_infos: (0, 0))

    result = builder.build_graph(
        repo_path=tmp_path,
        force_rebuild=False,
        repo_slug="new/repo",
        commit_sha="deadbeef",
        repo_fingerprint="deadbeef:clean",
    )

    assert fake_db.clear_calls == 1
    assert result["repo_fingerprint"] == "deadbeef:clean"
    assert fake_db.updated["graph_identity"] == "new/repo@deadbeef"


def test_qwen_changed_files_include_untracked(monkeypatch):
    interface = object.__new__(QwenMiniInterface)

    def fake_run(*args, **kwargs):
        cmd = args[0] if args else []
        if isinstance(cmd, list) and cmd[:3] == ["git", "diff", "--name-only"]:
            return SimpleNamespace(returncode=0, stdout="pkg/a.py\nREADME.md\n", stderr="")
        if isinstance(cmd, list) and cmd[:3] == ["git", "ls-files", "--others"]:
            return SimpleNamespace(returncode=0, stdout="new_script.py\nnotes.txt\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("utils.qwen_mini_interface.subprocess.run", fake_run)
    changed = interface._get_changed_files_any(Path("/tmp/repo"))
    changed_py = interface._get_changed_files(Path("/tmp/repo"))

    assert "pkg/a.py" in changed
    assert "new_script.py" in changed
    assert changed_py == ["pkg/a.py", "new_script.py"]


def test_qwen_graph_guard_signal_shape_classification():
    interface = object.__new__(QwenMiniInterface)
    assert (
        interface._classify_graph_guard_signal_shape(
            indexed_search_used=True,
            unit_test_changed=True,
        )
        == "both"
    )
    assert (
        interface._classify_graph_guard_signal_shape(
            indexed_search_used=True,
            unit_test_changed=False,
        )
        == "either_indexed"
    )
    assert (
        interface._classify_graph_guard_signal_shape(
            indexed_search_used=False,
            unit_test_changed=True,
        )
        == "either_test_change"
    )
    assert (
        interface._classify_graph_guard_signal_shape(
            indexed_search_used=False,
            unit_test_changed=False,
        )
        == "none"
    )


def test_qwen_runtime_reliability_for_test_contract():
    interface = object.__new__(QwenMiniInterface)
    assert interface._is_runtime_reliable_for_test_contract(
        pre_edit_repro={"command": "pytest tests/test_mod.py::test_alpha", "infra_unreliable": False},
        test_metrics={
            "f2p_reliable": True,
            "p2p_reliable": True,
            "test_signal_reliable": True,
        },
    )
    assert not interface._is_runtime_reliable_for_test_contract(
        pre_edit_repro={"command": "pytest tests/test_mod.py::test_alpha", "infra_unreliable": True},
        test_metrics={
            "f2p_reliable": True,
            "p2p_reliable": True,
            "test_signal_reliable": True,
        },
    )
    assert not interface._is_runtime_reliable_for_test_contract(
        pre_edit_repro={"command": "", "infra_unreliable": False},
        test_metrics={},
    )


def test_qwen_resolve_test_change_requirement_balanced_gate():
    interface = object.__new__(QwenMiniInterface)
    assert interface._resolve_test_change_requirement(
        tdd_mode=False,
        graphrag_enabled=True,
        runtime_reliable_for_test_contract=True,
    ) == (False, "not_applicable")
    assert interface._resolve_test_change_requirement(
        tdd_mode=True,
        graphrag_enabled=True,
        runtime_reliable_for_test_contract=True,
    ) == (True, "required_reliable_runtime")
    assert interface._resolve_test_change_requirement(
        tdd_mode=True,
        graphrag_enabled=True,
        runtime_reliable_for_test_contract=False,
    ) == (False, "waived_unreliable_runtime")


def test_graphrag_tdd_profile_inherits_tdd_prompt_defaults():
    interface = QwenMiniInterfaceGraphRAGTDD()
    # GraphRAG TDD inherits TDD prompt defaults (the 31% baseline).
    # GraphRAG TDD keeps deterministic decoding, restores soft issue-test
    # ranking, enables one graph regression fix round, and relaxes the
    # edit/timing profile for MLX-backed reasoning.
    assert interface.max_fix_iterations == 1
    assert interface.test_signal_mode == "soft"
    assert interface.test_runtime_isolation == "off"
    assert interface.no_diff_streak_limit == 8
    assert interface.retry_policy == "adaptive"
    assert interface.step_limit == 56
    assert interface.search_streak_limit == 12
    assert interface.max_read_only_steps_before_edit == 18
    assert interface.require_first_edit_by_step == 24
    assert interface.no_edit_progress_step_limit == 24
    assert interface.compile_valid_submit_stop is False
    assert interface.temperature == 0.0


def test_graphrag_tdd_repair_profiles_follow_base_controller_policy():
    base = QwenMiniInterface()
    graphrag = QwenMiniInterfaceGraphRAGTDD()

    for mode in ("retry_refine", "test_repair", "regression_repair", "compile_repair"):
        base_profile = base._resolve_round_control_profile(mode)
        graphrag_profile = graphrag._resolve_round_control_profile(mode)
        assert graphrag_profile["search_streak_limit"] == base_profile["search_streak_limit"]
        assert graphrag_profile["max_read_only_steps_before_edit"] == base_profile["max_read_only_steps_before_edit"]
        assert graphrag_profile["require_first_edit_by_step"] == base_profile["require_first_edit_by_step"]
        assert graphrag_profile["exploratory_pre_edit_limit"] == base_profile["exploratory_pre_edit_limit"]
        assert graphrag_profile["require_direct_edit_first"] == base_profile["require_direct_edit_first"]


def test_qwen_pytest_subset_treats_warnings_hook_conflict_with_counts_as_reliable(monkeypatch):
    interface = QwenMiniInterface()
    interface.pytest_timeout = 30

    monkeypatch.setattr(
        interface.test_runtime_manager,
        "get_runtime",
        lambda repo_root, log=None: {
            "runtime_env_id": "host",
            "python_executable": "python",
            "env": {},
            "runtime_ready": True,
            "bootstrap_actions": [],
            "runtime_bootstrap_attempts": [],
            "bootstrap_error": "",
            "bootstrap_error_reason": "",
            "runtime_install_mode": "host",
        },
    )

    class FakeCompleted:
        def __init__(self):
            self.returncode = 1
            self.stdout = "1 passed, 1 failed in 0.42s\n"
            self.stderr = "pytest-warnings plugin did not import\n"

    monkeypatch.setattr(
        "utils.qwen_mini_interface.subprocess.run",
        lambda *args, **kwargs: FakeCompleted(),
    )

    result = interface._run_pytest_subset(
        repo_path=Path("."),
        tests=["tests/test_mod.py::test_alpha", "tests/test_mod.py::test_beta"],
        timeout=30,
        log=lambda *_args, **_kwargs: None,
    )

    assert result["passed"] == 1
    assert result["failed"] == 1
    assert result["infra_unreliable"] is False
    assert result["infra_reason"] == ""


def test_qwen_run_graphrag_impact_query_prefers_coverage_fallback_when_hybrid_empty():
    interface = QwenMiniInterface()

    class FakeMCP:
        def __init__(self):
            self.calls = []

        def run_impacted_tests_iteratively(self, **kwargs):
            strategy = kwargs.get("strategy")
            self.calls.append(strategy)
            if strategy == "hybrid":
                return {
                    "success": False,
                    "total_impacted": 0,
                    "tests_run": 0,
                }
            return {
                "success": True,
                "total_impacted": 3,
                "tests_run": 2,
            }

    fake_mcp = FakeMCP()
    impacted, effective = interface._run_graphrag_impact_query(
        graphrag_mcp=fake_mcp,
        repo_path=Path("."),
        impact_input_files=["pkg/a.py"],
        impact_threshold=0.3,
        max_tests=20,
        strategy="hybrid",
        require_fresh_graph=False,
        log=lambda *_args, **_kwargs: None,
    )

    assert fake_mcp.calls == ["hybrid", "coverage_diff"]
    assert int(impacted.get("total_impacted", 0) or 0) == 3
    assert effective == "coverage_diff_fallback"


def test_qwen_run_graphrag_impact_query_forwards_refresh_policy():
    interface = QwenMiniInterface()

    class FakeMCP:
        def __init__(self):
            self.calls = []

        def run_impacted_tests_iteratively(self, **kwargs):
            self.calls.append(dict(kwargs))
            return {
                "success": True,
                "total_impacted": 1,
                "tests_run": 1,
            }

    fake_mcp = FakeMCP()
    impacted, effective = interface._run_graphrag_impact_query(
        graphrag_mcp=fake_mcp,
        repo_path=Path("."),
        impact_input_files=["pkg/a.py"],
        impact_threshold=0.3,
        max_tests=20,
        strategy="graph",
        require_fresh_graph=False,
        log=lambda *_args, **_kwargs: None,
    )

    assert effective == "graph"
    assert impacted["success"] is True
    assert fake_mcp.calls[0]["require_fresh_graph"] is False


def test_qwen_extract_source_file_changes_excludes_repo_tests():
    interface = QwenMiniInterface()

    source_files = interface._extract_source_file_changes(
        [
            "pkg/a.py",
            "tests/test_a.py",
            "pkg/test_helpers.py",
            "src/module.py",
            "docs/readme.md",
        ],
        policy="repo_tests_only",
    )

    assert source_files == ["pkg/a.py", "pkg/test_helpers.py", "src/module.py"]


def test_runtime_manager_medium_partial_ready_is_bounded_to_legacy_editable_failures():
    manager = TestRuntimeManager(isolation_mode="repo_cached_venv")
    manager.fallback_depth = "medium"

    assert manager._allow_source_mode_partial_ready("legacy_build_backend_incompat")
    assert manager._allow_source_mode_partial_ready("editable_build_backend_failure")
    assert not manager._allow_source_mode_partial_ready("source_checkout_unbuilt_extensions")

    manager.fallback_depth = "full"
    assert manager._allow_source_mode_partial_ready("source_checkout_unbuilt_extensions")


def test_runtime_manager_loads_build_system_requires(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        "[build-system]\n"
        "requires = [\n"
        '  "setuptools",\n'
        '  "wheel",\n'
        '  "extension-helpers",\n'
        '  "wheel"\n'
        "]\n",
        encoding="utf-8",
    )
    manager = TestRuntimeManager(isolation_mode="repo_cached_venv")

    assert manager._load_build_system_requires(repo) == [
        "setuptools",
        "wheel",
        "extension-helpers",
    ]


def test_runtime_manager_tries_no_build_isolation_after_legacy_editable_failure(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        "[build-system]\n"
        'requires = ["setuptools", "extension-helpers"]\n',
        encoding="utf-8",
    )

    cache_dir = tmp_path / "cache"
    manager = TestRuntimeManager(isolation_mode="repo_cached_venv", cache_dir=str(cache_dir))
    manager.set_context(repo_slug="astropy/astropy", commit_sha="abc123")

    runtime_key = manager._runtime_key()
    venv_dir = cache_dir / runtime_key
    bin_dir = venv_dir / "bin"
    bin_dir.mkdir(parents=True)
    python_bin = bin_dir / "python"
    python_bin.write_text("", encoding="utf-8")
    (venv_dir / ".base_bootstrap_ready").write_text("ready\n", encoding="utf-8")

    calls: list[tuple[str, list[str], dict[str, str] | None]] = []

    def fake_run_cmd(cmd, *, timeout, env=None):
        calls.append((cmd[3] if len(cmd) > 3 else "", list(cmd), env))
        if cmd[:3] == [str(python_bin), "-m", "pip"] and cmd[3:] == ["install", "-e", str(repo)]:
            return 1, "ModuleNotFoundError: No module named 'setuptools.dep_util'"
        if cmd[:3] == [str(python_bin), "-m", "pip"] and cmd[3:] == ["install", "--upgrade", "setuptools<70"]:
            return 0, "ok"
        if (
            cmd[:3] == [str(python_bin), "-m", "pip"]
            and cmd[3:] == ["install", "setuptools", "extension-helpers"]
        ):
            return 0, "ok"
        if (
            cmd[:3] == [str(python_bin), "-m", "pip"]
            and cmd[3:] == ["install", "--no-build-isolation", "-e", str(repo)]
        ):
            return 0, "ok"
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(manager, "_run_cmd", fake_run_cmd)

    runtime = manager.get_runtime(repo)

    assert runtime["runtime_ready"] is True
    assert runtime["runtime_install_mode"] == "editable_no_build_isolation"
    assert "build_requirements_preinstalled" in runtime["bootstrap_actions"]
    assert "editable_no_build_isolation_ready" in runtime["bootstrap_actions"]
    assert any(
        cmd[3:] == ["install", "setuptools", "extension-helpers"]
        for _, cmd, _ in calls
        if len(cmd) >= 4
    )
    assert any(
        cmd[3:] == ["install", "--no-build-isolation", "-e", str(repo)]
        for _, cmd, _ in calls
        if len(cmd) >= 4
    )


def test_graph_builder_incremental_preserves_file_node_for_modified_files(monkeypatch, tmp_path):
    builder = object.__new__(GraphBuilder)
    builder.repo_root = None
    builder._build_warnings = 0
    modified = tmp_path / "pkg" / "a.py"
    modified.parent.mkdir(parents=True, exist_ok=True)
    modified.write_text("def x():\n    return 1\n", encoding="utf-8")

    delete_calls: list[tuple[str, bool]] = []

    monkeypatch.setattr(builder, "_normalize_changed_files", lambda repo_path, changed: list(changed or []))
    monkeypatch.setattr(
        builder,
        "_parse_file",
        lambda file_path, repo_path: SimpleNamespace(relative_path="pkg/a.py"),
    )
    monkeypatch.setattr(
        builder,
        "_delete_file_subgraph",
        lambda relative_path, drop_file_node=True: delete_calls.append((relative_path, bool(drop_file_node))),
    )
    monkeypatch.setattr(
        builder,
        "_build_node_payloads",
        lambda file_infos, repo_path: ({"files": [], "functions": [], "classes": [], "tests": [], "contains": []}, 0, 0),
    )
    monkeypatch.setattr(builder, "_persist_node_payloads", lambda payloads: None)
    monkeypatch.setattr(builder, "_create_relationships_incremental", lambda file_infos: (0, 0))
    monkeypatch.setattr(builder, "_resolve_repo_slug", lambda repo_path, repo_slug=None: "owner/repo")
    monkeypatch.setattr(builder, "_resolve_commit_sha", lambda repo_path, commit_sha=None: "abc123")
    monkeypatch.setattr(
        builder,
        "_resolve_repo_fingerprint",
        lambda repo_path, commit_sha=None, repo_fingerprint=None: "abc123:clean",
    )
    builder.db = SimpleNamespace(update_index_metadata=lambda **kwargs: None)

    result = builder.incremental_update(
        repo_path=tmp_path,
        changed_files=["pkg/a.py", "pkg/deleted.py"],
        base_commit="HEAD",
        repo_slug="owner/repo",
        commit_sha="abc123",
        repo_fingerprint="abc123:clean",
    )

    assert ("pkg/a.py", False) in delete_calls
    assert ("pkg/deleted.py", True) in delete_calls
    assert result["nodes_updated"] == 0


def test_qwen_resolve_indexed_signal_successful_query_prefers_useful_signal():
    interface = object.__new__(QwenMiniInterface)
    interface.indexed_signal_mode = "successful_query"

    assert (
        interface._resolve_indexed_signal(
            {
                "indexed_search_attempted": True,
                "indexed_search_success": True,
                "graph_useful_signal": False,
            },
            mode="successful_query",
        )
        is False
    )
    assert (
        interface._resolve_indexed_signal(
            {
                "indexed_search_attempted": True,
                "indexed_search_success": False,
                "graph_useful_signal": True,
            },
            mode="successful_query",
        )
        is True
    )
    assert (
        interface._resolve_indexed_signal(
            {
                "indexed_search_attempted": True,
                "indexed_search_success": False,
                "graph_useful_signal": False,
            },
            mode="attempted_query",
        )
        is True
    )


def test_qwen_compute_tdd_evidence_requires_repo_test_change_only_when_enforced():
    interface = object.__new__(QwenMiniInterface)
    interface.strict_tdd_infra_policy = "fail_open"

    base_kwargs = {
        "tdd_mode": True,
        "strict_tdd_evidence": True,
        "fail_to_pass_tests": ["tests/test_mod.py::test_alpha"],
        "pass_to_pass_tests": ["tests/test_mod.py::test_smoke"],
        "pre_edit_repro": {"command": "pytest tests/test_mod.py::test_alpha -q", "failed": True},
        "test_metrics": {
            "f2p_total": 1,
            "f2p_all_passed": True,
            "f2p_reliable": True,
            "p2p_smoke_total": 1,
            "p2p_smoke_failures": 0,
            "p2p_reliable": True,
        },
        "patch_gate_valid": True,
        "strict_tdd_infra_policy": "fail_open",
    }

    waived = interface._compute_tdd_evidence(
        require_test_change=False,
        unit_test_changed=False,
        **base_kwargs,
    )
    assert waived["required_test_added"] is True
    assert waived["tdd_evidence_complete"] is True

    required = interface._compute_tdd_evidence(
        require_test_change=True,
        unit_test_changed=False,
        **base_kwargs,
    )
    assert required["required_test_added"] is False
    assert required["tdd_evidence_complete"] is False
    assert "missing_repo_test_change" in required["evidence_reason"]


def test_graphrag_factory_defaults_to_local_tool():
    tool = create_graphrag_interface(mode="local")
    assert isinstance(tool, GraphRAGLocalInterface)
    assert getattr(tool, "transport_mode", "") == "local"


def test_graphrag_factory_auto_falls_back_to_mcp(monkeypatch):
    import utils.graphrag_interface as graphrag_factory

    class FakeMCP:
        def __init__(self, server_url: str):
            self.server_url = server_url
            self.transport_mode = "mcp"

    def _raise_local():
        raise RuntimeError("local unavailable")

    monkeypatch.setattr(graphrag_factory, "GraphRAGLocalInterface", _raise_local)
    monkeypatch.setattr(graphrag_factory, "GraphRAGMCPInterface", FakeMCP)

    tool = graphrag_factory.create_graphrag_interface(
        mode="auto",
        server_url="http://localhost:8080",
    )
    assert isinstance(tool, FakeMCP)
    assert tool.transport_mode == "mcp"


def test_graphrag_local_get_impacted_tests_handles_non_python_change_without_db():
    interface = GraphRAGLocalInterface()
    result = interface.get_impacted_tests(
        repo_path="/tmp/non_repo_path",
        changed_files=["README.md"],
        impact_threshold=0.3,
    )
    assert result["success"] is True
    assert result["total_tests"] == 0
    assert result["staleness_reason"] == "no_changed_python_files"


def test_graphrag_local_transport_methods_fail_fast():
    interface = GraphRAGLocalInterface()

    for method_name in (
        "_verify_server",
        "_start_server",
        "_post_with_heartbeat",
        "_request_with_retry",
        "_poll_build_job",
    ):
        try:
            getattr(interface, method_name)()
        except RuntimeError as exc:
            assert "local GraphRAG mode" in str(exc)
        else:
            raise AssertionError(f"{method_name} should fail fast in local mode")


def test_graphrag_local_run_tests_records_targeted_coverage(monkeypatch):
    interface = GraphRAGLocalInterface()
    captured = {}

    class FakeRunner:
        def run_tests(self, repo_path, tests=None, pytest_args=None):
            captured["repo_path"] = repo_path
            captured["tests"] = list(tests or [])
            captured["pytest_args"] = list(pytest_args or [])
            return {
                "success": True,
                "passed": 1,
                "failed": 0,
                "skipped": 0,
                "test_results": [],
                "stdout": "",
                "stderr": "",
            }

    monkeypatch.setattr("utils.graphrag_local_interface.TestRunner", FakeRunner)
    monkeypatch.setattr(
        interface,
        "record_targeted_test_coverage",
        lambda *, repo_path, tests: captured.setdefault(
            "coverage_call",
            {"repo_path": repo_path, "tests": list(tests)},
        ),
    )

    result = interface.run_tests(
        repo_path="/tmp/repo",
        tests=["tests/test_mod.py::test_alpha"],
    )

    assert result["success"] is True
    assert captured["tests"] == ["tests/test_mod.py::test_alpha"]
    assert captured["coverage_call"] == {
        "repo_path": "/tmp/repo",
        "tests": ["tests/test_mod.py::test_alpha"],
    }


def test_test_linker_link_selected_tests_by_coverage_persists_bounded_rows(monkeypatch):
    linker = object.__new__(TestLinker)
    created = {}
    linker.db = SimpleNamespace(
        create_depends_on_relationships_batch=lambda rows: created.setdefault("rows", list(rows))
    )
    linker._warnings = []

    monkeypatch.setattr(
        linker,
        "_run_coverage",
        lambda repo_path, selected_tests=None, coverage_timeout=None: {
            "t1": {"pkg/a.py": 0.6, "pkg/b.py": 0.2},
        },
    )

    result = linker.link_selected_tests_by_coverage(
        repo_path=Path("/tmp/repo"),
        tests=["tests/test_mod.py::test_alpha", "./tests/test_mod.py::test_alpha"],
    )

    assert result["success"] is True
    assert result["tests_considered"] == 1
    assert result["links_created"] == 2
    assert len(created["rows"]) == 2
    assert {row["file_path"] for row in created["rows"]} == {"pkg/a.py", "pkg/b.py"}


def test_test_linker_run_coverage_uses_python_module_pytest_and_repo_env(monkeypatch, tmp_path):
    linker = object.__new__(TestLinker)
    linker._warnings = []
    calls = []

    class FakeCoverageData:
        def __init__(self, basename):
            self.basename = basename

        def read(self):
            return None

    monkeypatch.setattr("mcp_server.test_linker.CoverageData", FakeCoverageData)
    monkeypatch.setattr(
        linker,
        "_extract_per_test_coverage",
        lambda repo_path, cov_data: {"t1": {"pkg/a.py": 0.5}},
    )

    (tmp_path / "src").mkdir(parents=True, exist_ok=True)

    def fake_run(cmd, **kwargs):
        calls.append(
            {
                "cmd": list(cmd),
                "env": dict(kwargs.get("env") or {}),
                "timeout": kwargs.get("timeout"),
            }
        )
        (Path(kwargs["cwd"]) / ".coverage").write_text("fake", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("mcp_server.test_linker.subprocess.run", fake_run)

    coverage = linker._run_coverage(
        repo_path=tmp_path,
        selected_tests=["tests/test_mod.py::test_alpha"],
        coverage_timeout=45,
    )

    assert coverage == {"t1": {"pkg/a.py": 0.5}}
    assert len(calls) == 1
    assert calls[0]["cmd"][:3] == [sys.executable, "-m", "pytest"]
    assert "--cov=." in calls[0]["cmd"]
    assert "tests/test_mod.py::test_alpha" in calls[0]["cmd"]
    assert str(tmp_path.resolve()) in calls[0]["env"]["PYTHONPATH"]
    assert str((tmp_path / "src").resolve()) in calls[0]["env"]["PYTHONPATH"]
    assert calls[0]["timeout"] <= 45


def test_test_linker_run_coverage_retries_on_exit_code_4_import_mismatch(monkeypatch, tmp_path):
    linker = object.__new__(TestLinker)
    linker._warnings = []
    calls = []
    attempts = {"count": 0}

    class FakeCoverageData:
        def __init__(self, basename):
            self.basename = basename

        def read(self):
            return None

    monkeypatch.setattr("mcp_server.test_linker.CoverageData", FakeCoverageData)
    monkeypatch.setattr(
        linker,
        "_extract_per_test_coverage",
        lambda repo_path, cov_data: {"t2": {"pkg/b.py": 0.4}},
    )

    def fake_run(cmd, **kwargs):
        attempts["count"] += 1
        calls.append(
            {
                "cmd": list(cmd),
                "env": dict(kwargs.get("env") or {}),
                "timeout": kwargs.get("timeout"),
            }
        )
        if attempts["count"] == 1:
            return SimpleNamespace(
                returncode=4,
                stdout="",
                stderr="Import file mismatch",
            )
        (Path(kwargs["cwd"]) / ".coverage").write_text("fake", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("mcp_server.test_linker.subprocess.run", fake_run)

    coverage = linker._run_coverage(
        repo_path=tmp_path,
        selected_tests=["tests/test_mod.py::test_alpha"],
        coverage_timeout=30,
    )

    assert coverage == {"t2": {"pkg/b.py": 0.4}}
    assert len(calls) == 2
    assert "--import-mode=importlib" not in calls[0]["cmd"]
    assert "--import-mode=importlib" in calls[1]["cmd"]
    assert "--cache-clear" in calls[1]["cmd"]
    assert calls[1]["env"].get("PY_IGNORE_IMPORTMISMATCH") == "1"
    assert calls[0]["timeout"] <= 30
    assert calls[1]["timeout"] <= 30


def test_test_linker_run_coverage_falls_back_when_pytest_cov_produces_no_file(monkeypatch, tmp_path):
    linker = object.__new__(TestLinker)
    linker._warnings = []
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return SimpleNamespace(returncode=4, stdout="", stderr="Import file mismatch")

    monkeypatch.setattr("mcp_server.test_linker.subprocess.run", fake_run)
    monkeypatch.setattr(
        linker,
        "_run_targeted_coverage_fallback",
        lambda repo_path, selected_tests, coverage_timeout, extra_args="": {
            "t3": {"pkg/c.py": 0.7},
        },
    )

    coverage = linker._run_coverage(
        repo_path=tmp_path,
        selected_tests=["tests/test_mod.py::test_alpha"],
        coverage_timeout=30,
    )

    assert coverage == {"t3": {"pkg/c.py": 0.7}}
    assert len(calls) == 3
    assert any("falling back to targeted per-test coverage" in warning for warning in linker._warnings)


def test_test_linker_targeted_coverage_fallback_uses_coverage_run(monkeypatch, tmp_path):
    linker = object.__new__(TestLinker)
    linker._warnings = []
    calls = []

    (tmp_path / "src").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        linker,
        "_get_test_nodes",
        lambda: [
            {
                "test_id": "t1",
                "test_name": "test_alpha",
                "test_file": "tests/test_mod.py",
            }
        ],
    )
    monkeypatch.setattr(
        linker,
        "_extract_single_test_coverage_from_data_file",
        lambda *, repo_path, coverage_file: {"pkg/a.py": 0.5},
    )

    def fake_run(cmd, **kwargs):
        calls.append(
            {
                "cmd": list(cmd),
                "env": dict(kwargs.get("env") or {}),
                "timeout": kwargs.get("timeout"),
            }
        )
        data_arg = next(part for part in cmd if str(part).startswith("--data-file="))
        Path(data_arg.split("=", 1)[1]).write_text("fake", encoding="utf-8")
        return SimpleNamespace(returncode=1, stdout="1 failed\n", stderr="")

    monkeypatch.setattr("mcp_server.test_linker.subprocess.run", fake_run)

    coverage = linker._run_targeted_coverage_fallback(
        repo_path=tmp_path,
        selected_tests=["tests/test_mod.py::test_alpha"],
        coverage_timeout=45,
    )

    assert coverage == {"t1": {"pkg/a.py": 0.5}}
    assert len(calls) == 1
    assert calls[0]["cmd"][:4] == [sys.executable, "-m", "coverage", "run"]
    assert "tests/test_mod.py::test_alpha" in calls[0]["cmd"]
    assert str(tmp_path.resolve()) in calls[0]["env"]["PYTHONPATH"]
    assert str((tmp_path / "src").resolve()) in calls[0]["env"]["PYTHONPATH"]


def test_test_linker_targeted_coverage_fallback_expands_test_file_to_nodeids(monkeypatch, tmp_path):
    linker = object.__new__(TestLinker)
    linker._warnings = []
    calls = []

    monkeypatch.setattr(
        linker,
        "_get_test_nodes",
        lambda: [
            {
                "test_id": "t1",
                "test_name": "test_alpha",
                "test_file": "tests/test_mod.py",
            },
            {
                "test_id": "t2",
                "test_name": "test_beta",
                "test_file": "tests/test_mod.py",
            },
        ],
    )
    monkeypatch.setattr(
        linker,
        "_extract_single_test_coverage_from_data_file",
        lambda *, repo_path, coverage_file: {"pkg/a.py": 0.4},
    )

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        data_arg = next(part for part in cmd if str(part).startswith("--data-file="))
        Path(data_arg.split("=", 1)[1]).write_text("fake", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("mcp_server.test_linker.subprocess.run", fake_run)

    coverage = linker._run_targeted_coverage_fallback(
        repo_path=tmp_path,
        selected_tests=["tests/test_mod.py"],
        coverage_timeout=45,
    )

    assert set(coverage) == {"t1", "t2"}
    assert len(calls) == 2
    assert calls[0][-1] == "tests/test_mod.py::test_alpha"
    assert calls[1][-1] == "tests/test_mod.py::test_beta"


def test_qwen_regression_repair_signal_accepts_reliable_named_fallback_failures():
    interface = object.__new__(QwenMiniInterface)

    continue_fix, graph_execution_failed, regression_source = interface._get_regression_repair_signal(
        {
            "graph_useful_signal": False,
            "regression_source": "bounded_fallback_smoke",
            "impacted_run": 3,
            "impacted_failed": 2,
            "impacted_execution_reliable": True,
            "impacted_failed_tests": [
                {"test_name": "tests/test_mod.py::test_alpha", "error": "failed"},
            ],
        }
    )

    assert continue_fix is True
    assert graph_execution_failed is False
    assert regression_source == "bounded_fallback_smoke"


def test_qwen_regression_repair_signal_rejects_unnamed_fallback_failures():
    interface = object.__new__(QwenMiniInterface)

    continue_fix, graph_execution_failed, regression_source = interface._get_regression_repair_signal(
        {
            "graph_useful_signal": False,
            "regression_source": "bounded_fallback_smoke",
            "impacted_run": 3,
            "impacted_failed": 2,
            "impacted_execution_reliable": True,
            "impacted_failed_tests": [],
        }
    )

    assert continue_fix is False


def test_qwen_apply_regression_fallback_result_sets_bounded_fallback_metadata():
    interface = QwenMiniInterface()
    graphrag_meta = {
        "impacted_run": 0,
        "impacted_failed": 0,
        "impacted_success": False,
        "impacted_execution_reliable": False,
        "impact_empty_reason": "",
        "graph_fallback_reason": "",
    }

    applied = interface._apply_regression_fallback_result(
        graphrag_meta=graphrag_meta,
        fallback_result={
            "tests_run": 4,
            "failed": 1,
            "success": False,
            "execution_reliable": True,
            "selected_tests": ["tests/test_mod.py::test_alpha", "tests/test_mod.py::test_beta"],
            "failed_tests": [{"test_name": "tests/test_mod.py::test_alpha", "error": "failed"}],
        },
        regression_source="bounded_fallback_smoke",
        impact_empty_reason="no_non_empty_patch_for_impact_query",
        graph_fallback_reason="no_non_empty_patch_bounded_fallback",
    )

    assert applied is True
    assert graphrag_meta["regression_source"] == "bounded_fallback_smoke"
    assert graphrag_meta["regression_tests_selected"] == 2
    assert graphrag_meta["regression_tests_run"] == 4
    assert graphrag_meta["regression_tests_failed"] == 1
    assert graphrag_meta["regression_signal_reliable"] is True
    assert graphrag_meta["impact_empty_reason"] == "no_non_empty_patch_for_impact_query"
    assert graphrag_meta["graph_fallback_reason"] == "no_non_empty_patch_bounded_fallback"


def test_qwen_can_enter_intra_attempt_repair_requires_patch_for_graphrag():
    interface = QwenMiniInterface()

    allowed, reason = interface._can_enter_intra_attempt_repair(
        graphrag_enabled=True,
        patch="",
        source_changed_files=["pkg/mod.py"],
    )

    assert allowed is False
    assert reason == "no_non_empty_patch_candidate"

    allowed, reason = interface._can_enter_intra_attempt_repair(
        graphrag_enabled=True,
        patch="diff --git a/pkg/mod.py b/pkg/mod.py\n+fix\n",
        source_changed_files=[],
    )

    assert allowed is False
    assert reason == "no_source_patch_candidate"

    allowed, reason = interface._can_enter_intra_attempt_repair(
        graphrag_enabled=True,
        patch="diff --git a/pkg/mod.py b/pkg/mod.py\n+fix\n",
        source_changed_files=["pkg/mod.py"],
    )

    assert allowed is True
    assert reason == ""


def test_qwen_has_semantic_code_change_rejects_comment_only_diffs():
    interface = QwenMiniInterface()

    assert not interface._has_semantic_code_change(
        added_lines=["    # explanatory comment", '    """'],
        removed_lines=[""],
    )
    assert interface._has_semantic_code_change(
        added_lines=["        cright[-right.shape[0]:, -right.shape[1]:] = right"],
        removed_lines=["        cright[-right.shape[0]:, -right.shape[1]:] = 1"],
    )


def test_qwen_update_post_edit_no_diff_streak_aborts_default_round_after_patch_churn():
    interface = QwenMiniInterface()

    streak, abort = interface._update_post_edit_no_diff_streak(
        round_mode="default",
        edit_seen=True,
        seen_nonempty=True,
        cmd_flags={"is_edit": False, "is_test": False, "is_exploratory": True},
        current_sig="sig1",
        prev_sig="sig1",
        streak=1,
    )

    assert streak == 2
    assert abort is True

    streak, abort = interface._update_post_edit_no_diff_streak(
        round_mode="regression_repair",
        edit_seen=True,
        seen_nonempty=True,
        cmd_flags={"is_edit": False, "is_test": False, "is_exploratory": True},
        current_sig="sig1",
        prev_sig="sig1",
        streak=1,
    )

    assert streak == 0
    assert abort is False


def test_qwen_is_noop_first_edit_attempt_requires_real_diff():
    interface = QwenMiniInterface()

    assert interface._is_noop_first_edit_attempt(
        cmd_flags={"is_edit": True, "is_test": False, "is_exploratory": False},
        seen_nonempty=False,
        prev_sig="EMPTY",
        current_sig="EMPTY",
    ) is True

    assert interface._is_noop_first_edit_attempt(
        cmd_flags={"is_edit": True, "is_test": False, "is_exploratory": False},
        seen_nonempty=True,
        prev_sig="sig1",
        current_sig="sig1",
    ) is False

    assert interface._is_noop_first_edit_attempt(
        cmd_flags={"is_edit": False, "is_test": False, "is_exploratory": True},
        seen_nonempty=False,
        prev_sig="EMPTY",
        current_sig="EMPTY",
    ) is False


def test_qwen_round_control_profile_is_stricter_for_repair_rounds():
    interface = QwenMiniInterface()

    default_profile = interface._resolve_round_control_profile("default")
    retry_refine_profile = interface._resolve_round_control_profile("retry_refine")
    repair_profile = interface._resolve_round_control_profile("test_repair")
    regression_profile = interface._resolve_round_control_profile("regression_repair")
    compile_profile = interface._resolve_round_control_profile("compile_repair")

    assert default_profile["round_mode"] == "default"
    assert retry_refine_profile["round_mode"] == "retry_refine"
    assert retry_refine_profile["require_first_edit_by_step"] < default_profile["require_first_edit_by_step"]
    assert retry_refine_profile["exploratory_pre_edit_limit"] == 0
    assert retry_refine_profile["require_direct_edit_first"] is True
    assert repair_profile["round_mode"] == "test_repair"
    assert repair_profile["search_streak_limit"] < default_profile["search_streak_limit"]
    assert (
        repair_profile["max_read_only_steps_before_edit"]
        < default_profile["max_read_only_steps_before_edit"]
    )
    assert (
        repair_profile["require_first_edit_by_step"]
        < default_profile["require_first_edit_by_step"]
    )
    assert repair_profile["exploratory_pre_edit_limit"] == 0
    assert repair_profile["require_direct_edit_first"] is True
    assert regression_profile["round_mode"] == "regression_repair"
    assert regression_profile["require_first_edit_by_step"] <= repair_profile["require_first_edit_by_step"]
    assert regression_profile["search_streak_limit"] <= repair_profile["search_streak_limit"]
    assert regression_profile["exploratory_pre_edit_limit"] == 0
    assert regression_profile["require_direct_edit_first"] is True
    assert regression_profile["blocked_guard_abort_limit"] == 2
    assert compile_profile["round_mode"] == "compile_repair"
    assert compile_profile["search_streak_limit"] <= repair_profile["search_streak_limit"]
    assert compile_profile["exploratory_pre_edit_limit"] == 0
    assert compile_profile["require_direct_edit_first"] is True
    assert compile_profile["blocked_guard_abort_limit"] == 2


def test_qwen_round_control_profile_allows_repair_override_envs(monkeypatch):
    interface = QwenMiniInterface()

    monkeypatch.setenv("QWEN_MINI_RETRY_REFINE_EXPLORATORY_PRE_EDIT_LIMIT", "1")
    monkeypatch.setenv("QWEN_MINI_RETRY_REFINE_BLOCKED_GUARD_ABORT_LIMIT", "3")
    monkeypatch.setenv("QWEN_MINI_TEST_REPAIR_EXPLORATORY_PRE_EDIT_LIMIT", "1")
    monkeypatch.setenv("QWEN_MINI_TEST_REPAIR_BLOCKED_GUARD_ABORT_LIMIT", "3")
    monkeypatch.setenv("QWEN_MINI_REGRESSION_REPAIR_EXPLORATORY_PRE_EDIT_LIMIT", "1")
    monkeypatch.setenv("QWEN_MINI_REGRESSION_REPAIR_BLOCKED_GUARD_ABORT_LIMIT", "3")
    monkeypatch.setenv("QWEN_MINI_COMPILE_REPAIR_EXPLORATORY_PRE_EDIT_LIMIT", "1")
    monkeypatch.setenv("QWEN_MINI_COMPILE_REPAIR_BLOCKED_GUARD_ABORT_LIMIT", "3")

    for mode in ("retry_refine", "test_repair", "regression_repair", "compile_repair"):
        profile = interface._resolve_round_control_profile(mode)
        assert profile["exploratory_pre_edit_limit"] == 1
        assert profile["blocked_guard_abort_limit"] == 3
        assert profile["require_direct_edit_first"] is True


def test_qwen_derive_repair_focus_files_infers_source_from_test_path(tmp_path):
    interface = QwenMiniInterface()
    source_dir = tmp_path / "pkg"
    tests_dir = source_dir / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (tests_dir / "test_mod.py").write_text("def test_f():\n    assert True\n", encoding="utf-8")

    focus_files = interface._derive_repair_focus_files(
        repo_path=tmp_path,
        problem_statement="Investigate pkg/mod.py and failing test pkg/tests/test_mod.py",
        fail_to_pass_tests=["pkg/tests/test_mod.py::test_f"],
        failed_tests=[{"test_file": "pkg/tests/test_mod.py", "test_name": "test_f"}],
    )

    assert "pkg/tests/test_mod.py" in focus_files
    assert "pkg/mod.py" in focus_files
    assert focus_files.index("pkg/mod.py") < focus_files.index("pkg/tests/test_mod.py")


def test_qwen_derive_repair_focus_files_skips_top_level_repro_scripts(tmp_path):
    interface = QwenMiniInterface()
    source_dir = tmp_path / "pkg"
    tests_dir = source_dir / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (tests_dir / "test_mod.py").write_text("def test_f():\n    assert True\n", encoding="utf-8")
    (tmp_path / "reproduce_issue.py").write_text("print('debug')\n", encoding="utf-8")

    focus_files = interface._derive_repair_focus_files(
        repo_path=tmp_path,
        problem_statement="Investigate pkg/mod.py and failing test pkg/tests/test_mod.py",
        fail_to_pass_tests=["pkg/tests/test_mod.py::test_f"],
        changed_files=["reproduce_issue.py", "pkg/mod.py"],
        failed_tests=[{"test_file": "pkg/tests/test_mod.py", "test_name": "test_f"}],
    )

    assert "reproduce_issue.py" not in focus_files
    assert "pkg/mod.py" in focus_files
    assert "pkg/tests/test_mod.py" in focus_files


def test_qwen_prioritize_focus_files_prefers_source_files():
    interface = QwenMiniInterface()

    prioritized = interface._prioritize_focus_files(
        [
            "pkg/tests/test_mod.py",
            "pkg/mod.py",
            "reproduce_issue.py",
        ]
    )

    assert prioritized[0] == "pkg/mod.py"
    assert prioritized[1] == "pkg/tests/test_mod.py"
    assert "reproduce_issue.py" not in prioritized


def test_qwen_prioritize_focus_files_demotes_package_init_modules():
    interface = QwenMiniInterface()

    prioritized = interface._prioritize_focus_files(
        [
            "astropy/modeling/__init__.py",
            "astropy/modeling/separable.py",
            "astropy/modeling/tests/test_separable.py",
        ]
    )

    assert prioritized[0] == "astropy/modeling/separable.py"
    assert prioritized[1] == "astropy/modeling/__init__.py"


def test_qwen_should_continue_compile_fix_round_allows_loopaborted_nonempty_patch():
    interface = QwenMiniInterface()

    should_continue, reason = interface._should_continue_compile_fix_round(
        run_status="LoopAborted",
        compile_failed=1,
        patch="diff --git a/x.py b/x.py",
        current_round=0,
        max_rounds=2,
    )

    assert should_continue is True
    assert reason == "compile_failures_present"


def test_qwen_compile_repair_patch_source_uses_raw_diff_when_gate_rejects_patch():
    interface = QwenMiniInterface()

    patch = interface._compile_repair_patch_source(
        patch="",
        last_patch_gate={
            "diff": "diff --git a/pkg/mod.py b/pkg/mod.py\n+broken\n",
            "compile_gate": {"compile_failed": 1},
        },
    )

    assert "diff --git a/pkg/mod.py b/pkg/mod.py" in patch


def test_qwen_should_start_regression_fix_round_allows_reliable_fallback_signal_when_tdd_red():
    interface = QwenMiniInterface()

    should_continue, reason = interface._should_start_regression_fix_round(
        tdd_gate_passed=False,
        continue_regression_fix=True,
        regression_source="bounded_fallback_smoke",
        regression_signal_reliable=True,
        fail_to_pass_tests=["tests/test_mod.py::test_alpha"],
        current_round=0,
        max_rounds=1,
    )

    assert should_continue is True
    assert reason == "fallback_signal_guided_red_repro"


def test_qwen_repair_round_scratch_python_target_blocks_top_level_scripts(tmp_path):
    interface = QwenMiniInterface()

    blocked = interface._repair_round_scratch_python_target(
        command="cat > test_issue_repro.py <<'EOF'\nprint('x')\nEOF",
        repo_path=tmp_path,
        focus_files=["pkg/mod.py"],
    )

    assert blocked == "test_issue_repro.py"


def test_qwen_repair_round_scratch_python_target_blocks_repro_scripts_even_if_focus_file(tmp_path):
    interface = QwenMiniInterface()

    blocked = interface._repair_round_scratch_python_target(
        command="cat > reproduce_issue.py <<'EOF'\nprint('x')\nEOF",
        repo_path=tmp_path,
        focus_files=["reproduce_issue.py", "pkg/mod.py"],
    )

    assert blocked == "reproduce_issue.py"


def test_qwen_rewrite_macos_sed_inplace_adds_empty_suffix(monkeypatch):
    interface = QwenMiniInterface()
    monkeypatch.setattr(sys, "platform", "darwin")

    rewritten, changed = interface._rewrite_macos_sed_inplace(
        "sed -i 's/old/new/g' pkg/mod.py"
    )

    assert changed is True
    assert rewritten == "sed -i '' 's/old/new/g' pkg/mod.py"


def test_qwen_rewrite_multiline_python_c_handles_inline_path_quotes():
    interface = QwenMiniInterface()

    rewritten, changed = interface._rewrite_multiline_python_c(
        "python -c 'from pathlib import Path\np = Path(\"pkg/mod.py\")\ntext = p.read_text()\np.write_text(text)\n'"
    )

    assert changed is True
    assert rewritten.startswith("python - <<'PY'\nfrom pathlib import Path\n")
    assert 'Path("pkg/mod.py")' in rewritten
    assert rewritten.endswith("\nPY")


def test_qwen_build_repair_edit_required_message_includes_focus_file_example():
    interface = QwenMiniInterface()

    message = interface._build_repair_edit_required_message(
        focus_files=["pkg/mod.py", "pkg/tests/test_mod.py"]
    )

    assert "Your next command MUST be a direct edit" in message
    assert "- pkg/mod.py" in message
    assert "python3 - <<'PY'" in message
    assert "Path('pkg/mod.py')" in message


def test_qwen_build_repair_edit_required_message_uses_diff_anchor_when_available():
    interface = QwenMiniInterface()

    message = interface._build_repair_edit_required_message(
        focus_files=["pkg/mod.py"],
        diff_excerpt="diff --git a/pkg/mod.py b/pkg/mod.py\n@@\n-old_value = 1\n+old_value = 2\n",
    )

    assert "old = 'old_value = 1'" in message
    assert "assert old in text" in message


def test_qwen_build_minimal_fix_guidance_tightens_after_large_patch_reject():
    interface = QwenMiniInterface()

    guidance = interface._build_minimal_fix_guidance(
        diff_excerpt="diff --git a/pkg/mod.py b/pkg/mod.py\n@@\n-old_value = 1\n+old_value = 2\n",
        patch_gate_reason="too_many_changed_lines:252_limit_200,repetitive_code:max_repeat=14",
    )

    assert "1-5 executable changed lines" in guidance
    assert "Do not add explanatory comments" in guidance
    assert "old_value = 1" in guidance
    assert "Refine the shown hunk directly" in guidance


def test_qwen_extract_diff_anchor_line_ignores_diff_headers():
    interface = QwenMiniInterface()

    anchor = interface._extract_diff_anchor_line(
        "diff --git a/pkg/mod.py b/pkg/mod.py\n"
        "--- a/pkg/mod.py\n"
        "+++ b/pkg/mod.py\n"
        "@@ -10 +10 @@\n"
        "-old_value = 1\n"
        "+old_value = 2\n"
    )

    assert anchor == "old_value = 1"


def test_qwen_build_edit_required_message_can_include_verify_and_source_excerpt():
    interface = QwenMiniInterface()

    message = interface._build_edit_required_message(
        round_label="Repair rounds",
        focus_files=["pkg/mod.py"],
        diff_excerpt="diff --git a/pkg/mod.py b/pkg/mod.py\n@@ -10 +10 @@\n-old = 1\n+old = 2\n",
        source_excerpt="  10: old = 2",
        verify_command="python -m pytest -q pkg/tests/test_mod.py::test_bug",
    )

    assert "Relevant source excerpt:" in message
    assert "After the edit, verify with:" in message
    assert "python -m pytest -q pkg/tests/test_mod.py::test_bug" in message


def test_qwen_command_guard_rejections_do_not_count_toward_loop_metrics():
    interface = QwenMiniInterface()

    assert interface._command_guard_counts_toward_loop_metrics("") is True
    assert interface._command_guard_counts_toward_loop_metrics("focus_round_inline_python_probe") is False
    assert interface._command_guard_counts_toward_loop_metrics("repair_round_edit_required") is False


def test_qwen_build_edit_required_message_supports_default_round_label():
    interface = QwenMiniInterface()

    message = interface._build_edit_required_message(
        round_label="Default round",
        focus_files=["pkg/mod.py"],
        exploratory_limit=5,
    )

    assert "Default round allows at most 5 exploratory commands" in message
    assert "Your next command MUST be a direct edit" in message
    assert "- pkg/mod.py" in message
    assert "python3 - <<'PY'" in message


def test_qwen_build_repair_edit_required_message_can_require_immediate_edit():
    interface = QwenMiniInterface()

    message = interface._build_repair_edit_required_message(
        focus_files=["pkg/mod.py"],
    )

    assert "Repair rounds: no exploratory commands are allowed before the next edit." in message
    assert "Your next command MUST be a direct edit" in message


def test_qwen_inline_python_runtime_probe_blocks_runtime_but_not_edit_commands():
    interface = QwenMiniInterface()

    assert interface._is_inline_python_runtime_probe(
        "python -c \"from astropy.modeling import models as m\nprint(m.Linear1D)\""
    )
    assert not interface._is_inline_python_runtime_probe(
        "python -c \"from pathlib import Path\np = Path('pkg/mod.py')\ntext = p.read_text()\np.write_text(text)\"",
        cmd_flags={"is_edit": True, "is_test": False, "is_exploratory": False},
    )


def test_qwen_is_compound_exploratory_command_blocks_chained_reads_not_edits():
    interface = QwenMiniInterface()

    assert interface._is_compound_exploratory_command("pwd && find . -name 'x.py'")
    assert not interface._is_compound_exploratory_command(
        "python3 -c \"from pathlib import Path; p = Path('pkg/mod.py'); p.write_text('x')\"",
        cmd_flags={"is_edit": True, "is_test": False, "is_exploratory": False},
    )


def test_qwen_classify_command_treats_python_heredoc_as_edit_only_when_writing_files():
    interface = QwenMiniInterface()

    runtime_flags = interface._classify_command("python - <<'PY'\nprint('x')\nPY")
    edit_flags = interface._classify_command(
        "python - <<'PY'\nfrom pathlib import Path\nPath('pkg/mod.py').write_text('x')\nPY"
    )

    assert runtime_flags["is_edit"] is False
    assert edit_flags["is_edit"] is True


def test_qwen_select_format_salvage_action_prefers_edit_block():
    interface = QwenMiniInterface()

    content = (
        "THOUGHT: inspect then fix\n\n"
        "```bash\n"
        "grep -n \"needle\" pkg/mod.py\n"
        "```\n\n"
        "```bash\n"
        "sed -i '' 's/old/new/' pkg/mod.py\n"
        "```"
    )

    salvage = interface._select_format_salvage_action(content)

    assert salvage is not None
    assert salvage["reason"] == "multiple_blocks_first_edit"
    assert salvage["action"] == "sed -i '' 's/old/new/' pkg/mod.py"


def test_qwen_select_format_salvage_action_falls_back_to_first_exploratory_block():
    interface = QwenMiniInterface()

    content = (
        "THOUGHT: inspect the likely area\n\n"
        "```bash\n"
        "grep -n \"needle\" pkg/mod.py\n"
        "```\n\n"
        "```bash\n"
        "sed -n '10,30p' pkg/mod.py\n"
        "```"
    )

    salvage = interface._select_format_salvage_action(content)

    assert salvage is not None
    assert salvage["reason"] == "multiple_blocks_first_exploratory"
    assert salvage["action"] == "grep -n \"needle\" pkg/mod.py"


def test_qwen_select_format_salvage_action_ignores_fenced_output_and_prefers_first_real_command():
    interface = QwenMiniInterface()

    content = (
        "THOUGHT: reproduce then inspect\n\n"
        "```bash\n"
        "pwd && find . -name \"separable.py\" -type f\n"
        "```\n\n"
        "```bash\n"
        "/usr/local/lib/python3.11/site-packages/astropy/modeling\n"
        "```\n\n"
        "```bash\n"
        "find . -name \"separable.py\" -type f | head -5\n"
        "```\n\n"
        "```bash\n"
        "python3 -c \"from pathlib import Path; Path('pkg/mod.py').write_text('bad')\"\n"
        "```"
    )

    salvage = interface._select_format_salvage_action(content)

    assert salvage is not None
    assert salvage["reason"] == "multiple_blocks_first_edit"
    assert salvage["block_count"] == 3
    assert salvage["action"] == 'python3 -c "from pathlib import Path; Path(\'pkg/mod.py\').write_text(\'bad\')"'


def test_qwen_select_format_salvage_action_ignores_noop_echo_blocks():
    interface = QwenMiniInterface()

    content = (
        "THOUGHT: explain then act\n\n"
        "```bash\n"
        "echo \"The issue requires updating the transform implementation\"\n"
        "```\n\n"
        "```bash\n"
        "grep -n \"NdarrayMixin\" astropy/table/table.py\n"
        "```"
    )

    salvage = interface._select_format_salvage_action(content)

    assert salvage is not None
    assert salvage["reason"] == "multiple_blocks_first_exploratory"
    assert salvage["block_count"] == 1
    assert salvage["action"] == 'grep -n "NdarrayMixin" astropy/table/table.py'


def test_qwen_select_format_salvage_action_skips_outside_repo_candidates(tmp_path):
    interface = object.__new__(QwenMiniInterface)
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")

    content = (
        "THOUGHT: inspect then fix\n\n"
        "```bash\n"
        "cd /Users/runner/work/repo && grep -n \"needle\" pkg/mod.py\n"
        "```\n\n"
        "```bash\n"
        "grep -n \"needle\" pkg/mod.py\n"
        "```"
    )

    salvage = interface._select_format_salvage_action(
        content,
        repo_path=repo,
        round_profile={"round_mode": "default", "block_scratch_python_before_edit": False},
        focus_files=["pkg/mod.py"],
    )

    assert salvage is not None
    assert salvage["action"] == 'grep -n "needle" pkg/mod.py'


def test_qwen_select_format_salvage_action_skips_focused_round_cat_dump(tmp_path):
    interface = object.__new__(QwenMiniInterface)
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")

    content = (
        "THOUGHT: inspect the file\n\n"
        "```bash\n"
        "cat pkg/mod.py\n"
        "```\n\n"
        "```bash\n"
        "sed -n '1,20p' pkg/mod.py\n"
        "```"
    )

    salvage = interface._select_format_salvage_action(
        content,
        repo_path=repo,
        round_profile={"round_mode": "default", "block_scratch_python_before_edit": False},
        focus_files=["pkg/mod.py"],
    )

    assert salvage is not None
    assert salvage["action"] == "sed -n '1,20p' pkg/mod.py"


def test_qwen_select_format_salvage_action_returns_none_when_all_candidates_blocked(tmp_path):
    interface = object.__new__(QwenMiniInterface)
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")

    content = (
        "THOUGHT: inspect\n\n"
        "```bash\n"
        "cd /Users/runner/work/repo && grep -n \"needle\" pkg/mod.py\n"
        "```\n\n"
        "```bash\n"
        "cat pkg/mod.py\n"
        "```"
    )

    salvage = interface._select_format_salvage_action(
        content,
        repo_path=repo,
        round_profile={"round_mode": "default", "block_scratch_python_before_edit": False},
        focus_files=["pkg/mod.py"],
    )

    assert salvage is None


def test_qwen_select_format_salvage_action_returns_rewritten_preflight_command(tmp_path):
    interface = object.__new__(QwenMiniInterface)
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")

    content = (
        "THOUGHT: inspect\n\n"
        "```bash\n"
        "cd /repo && grep -n \"needle\" pkg/mod.py\n"
        "```"
    )

    salvage = interface._select_format_salvage_action(
        content,
        repo_path=repo,
        round_profile={"round_mode": "default", "block_scratch_python_before_edit": False},
        focus_files=["pkg/mod.py"],
    )

    assert salvage is not None
    assert salvage["action"].startswith(f"cd {repo}")


def test_qwen_select_format_salvage_action_skips_test_command_after_pre_edit_infra_noise(tmp_path):
    interface = object.__new__(QwenMiniInterface)
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")

    content = (
        "THOUGHT: inspect and verify\n\n"
        "```bash\n"
        "python -m pytest pkg/tests/test_mod.py -q\n"
        "```\n\n"
        "```bash\n"
        "grep -n \"x\" pkg/mod.py\n"
        "```"
    )

    salvage = interface._select_format_salvage_action(
        content,
        repo_path=repo,
        round_profile={"round_mode": "default", "block_scratch_python_before_edit": False},
        focus_files=["pkg/mod.py"],
        env_bootstrap_fail_streak=1,
    )

    assert salvage is not None
    assert salvage["reason"] == "multiple_blocks_first_exploratory"
    assert salvage["action"] == 'grep -n "x" pkg/mod.py'


def test_qwen_apply_round_command_guard_blocks_first_exploratory_command_in_repair_round(tmp_path):
    interface = QwenMiniInterface()
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")

    guard = interface._apply_round_command_guard(
        command='grep -n "x" pkg/mod.py',
        repo_path=repo,
        round_profile={
            "round_mode": "test_repair",
            "require_direct_edit_first": True,
            "exploratory_pre_edit_limit": 0,
            "block_scratch_python_before_edit": True,
        },
        focus_files=["pkg/mod.py"],
        edit_seen=False,
    )

    assert guard["blocked"] is True
    assert guard["reason"] == "repair_round_edit_required"
    assert "no exploratory commands are allowed before the next edit" in guard["message"]


def test_qwen_prepare_prompt_for_agent_run_reports_section_sizes():
    interface = object.__new__(QwenMiniInterface)
    interface.prompt_budget_chars = 20000
    interface.prompt_token_estimate_divisor = 4

    task = (
        "Fix the bug.\n\n## Retry Guidance\nRetry details.\n"
        "\nCurrent diff excerpt:\n```diff\n- old\n+ new\n```\n"
        "\nCurrent source excerpt:\n```python\nprint('x')\n```\n"
        "Known failing target tests:\n- tests/test_mod.py::test_alpha\n"
        "Preferred verification command: `python -m pytest -q tests/test_mod.py::test_alpha`\n"
    )
    logs: list[str] = []

    prepared, telemetry = interface._prepare_prompt_for_agent_run(
        task=task,
        round_mode="test_repair",
        focus_files=["pkg/mod.py"],
        log=logs.append,
    )

    assert prepared == task
    assert telemetry["trimmed"] is False
    assert telemetry["section_sizes_after"]["retry_text"] > 0
    assert telemetry["section_sizes_after"]["diff_excerpt"] > 0
    assert telemetry["section_sizes_after"]["source_excerpt"] > 0
    assert telemetry["focus_file_count"] == 1
    assert any(line.startswith("PROMPT_TRACE ") for line in logs)


def test_qwen_prepare_prompt_for_agent_run_trims_when_budget_exceeded():
    interface = object.__new__(QwenMiniInterface)
    interface.prompt_budget_chars = 4000
    interface.prompt_budget_tokens = 0
    interface.prompt_token_estimate_divisor = 4

    task = (
        "Fix the bug.\n\n## Retry Guidance\n"
        + ("retry text\n" * 80)
        + "\nCurrent diff excerpt:\n```diff\n"
        + ("+ diff line\n" * 180)
        + "```\n"
        + "\nCurrent source excerpt:\n```python\n"
        + ("value = 1\n" * 180)
        + "```\n"
        + "Known failing target tests:\n"
        + "".join(f"- tests/test_mod.py::test_{idx}\n" for idx in range(10))
    )

    prepared, telemetry = interface._prepare_prompt_for_agent_run(
        task=task,
        round_mode="retry_refine",
        focus_files=["pkg/mod.py"],
        log=lambda *_args, **_kwargs: None,
    )

    assert len(prepared) <= interface.prompt_budget_chars
    assert telemetry["trimmed"] is True
    assert telemetry["estimated_tokens_after"] <= telemetry["estimated_tokens_before"]
    assert any(item["section"] == "retry_text" for item in telemetry["trimmed_sections"])


def test_qwen_prepare_prompt_for_agent_run_uses_backend_context_window_budget(monkeypatch):
    interface = object.__new__(QwenMiniInterface)
    interface.prompt_budget_chars = 120000
    interface.prompt_budget_tokens = 0
    interface.prompt_token_estimate_divisor = 4
    interface.model_max_tokens = 2048
    interface.local_backend = SimpleNamespace(provider="llamacpp", env_prefix="QWEN_MINI")

    monkeypatch.delenv("QWEN_MINI_PROMPT_BUDGET_CHARS", raising=False)
    monkeypatch.setenv("QWEN_MINI_LLAMACPP_CTX_SIZE", "16384")

    task = (
        "Fix the bug.\n\n## Retry Guidance\n"
        + ("retry text\n" * 1200)
        + "\nCurrent diff excerpt:\n```diff\n"
        + ("+ diff line\n" * 900)
        + "```\n"
        + "\nCurrent source excerpt:\n```python\n"
        + ("value = 1\n" * 900)
        + "```\n"
    )

    prepared, telemetry = interface._prepare_prompt_for_agent_run(
        task=task,
        round_mode="retry_refine",
        focus_files=["astropy/modeling/separable.py"],
        log=lambda *_args, **_kwargs: None,
    )

    assert telemetry["budget_source"] == "backend_context_window"
    assert telemetry["context_window_tokens"] == 16384
    assert telemetry["budget_tokens"] == 10444
    assert telemetry["budget_chars"] == 31332
    assert len(prepared) <= telemetry["budget_chars"]
    assert telemetry["estimated_tokens_after"] <= telemetry["budget_tokens"]
    assert telemetry["trimmed"] is True


def test_qwen_format_task_includes_focus_files_workflow_guidance():
    interface = QwenMiniInterface()

    task = interface._format_task(
        "Fix the bug",
        "",
        [],
        True,
        focus_files=["pkg/mod.py", "pkg/tests/test_mod.py"],
    )

    assert "## Likely Focus Files" in task
    assert "- pkg/mod.py" in task
    assert "Do not create standalone repro/debug scripts before the first edit." in task
    assert "Do not use inline python runtime probes before the first edit." in task
    assert "Prefer the smallest localized change in the likely source file." in task
    assert "Prefer a single-line `python3 -c` pathlib edit or `sed -i` over multiline heredoc edits." in task
    assert "## TDD Workflow" in task


def test_qwen_format_task_includes_extra_env_guidance(monkeypatch):
    interface = QwenMiniInterface()
    monkeypatch.setenv(
        "QWEN_MINI_EXTRA_TASK_GUIDANCE",
        "Prefer a minimal helper-level executable fix before broad rewrites.",
    )

    task = interface._format_task(
        "Fix the bug",
        "",
        [],
        True,
        focus_files=["pkg/mod.py"],
    )

    assert "## Additional Task Guidance" in task
    assert "Prefer a minimal helper-level executable fix before broad rewrites." in task


def test_qwen_format_retry_task_includes_extra_retry_env_guidance(monkeypatch):
    interface = QwenMiniInterface()
    monkeypatch.setenv(
        "QWEN_MINI_EXTRA_RETRY_GUIDANCE",
        "Stay on the current helper and refine the existing executable hunk.",
    )

    task = interface._format_retry_task(
        problem_statement="Fix the bug",
        hints_text="",
        tdd_mode=True,
        attempt_idx=2,
        prev_attempt={"loop_abort_reason": "repair_blocked_streak:2", "patch_gate_reason": "ok"},
        prev_candidate={"changed_files": ["pkg/mod.py"], "changed_lines_total": 2, "prediction": ""},
        best_candidate={"changed_files": ["pkg/mod.py"], "prediction": "diff --git a/pkg/mod.py b/pkg/mod.py"},
        focus_files=["pkg/mod.py"],
        existing_diff_excerpt="diff --git a/pkg/mod.py b/pkg/mod.py\n@@ -1 +1 @@\n-x = 1\n+x = 2",
        source_excerpt="1: def helper():\n2:     return 1",
        verify_command="python -m pytest -q pkg/tests/test_mod.py::test_bug",
        memory_guidance="Avoid the previous broad rewrite.",
    )

    assert "Stay on the current helper and refine the existing executable hunk." in task


def test_graphrag_tdd_format_task_includes_controller_rules():
    interface = QwenMiniInterfaceGraphRAGTDD()

    task = interface._format_task(
        "Fix the bug",
        "",
        ["pkg/tests/test_mod.py::test_bug"],
        True,
        focus_files=["pkg/mod.py"],
        graphrag_summary={
            "success": True,
            "seed_files": ["pkg/mod.py"],
            "focus_files": ["pkg/mod.py"],
            "affected_tests": ["pkg/tests/test_mod.py::test_bug"],
            "total_tests": 1,
        },
    )

    assert "## GraphRAG Start Context" in task
    assert "Graph-derived repository context was prepared before this attempt." in task
    assert "## Controller Rules" in task
    assert "Keep exactly one root-cause hypothesis per attempt." in task
    assert "If no FAIL_TO_PASS test improves and the failure shape stays the same for 2 attempts" in task
    assert "## GraphRAG Context" in task
    assert "The GraphRAG start context above is mandatory attempt input." in task


def test_qwen_format_graphrag_failure_task_requires_edit_first():
    interface = QwenMiniInterface()

    task = interface._format_graphrag_failure_task(
        "Fix the bug",
        "",
        [{"full_name": "pkg/tests/test_mod.py::test_bug", "error": "AssertionError"}],
        regression_source="bounded_fallback_smoke",
        focus_files=["pkg/mod.py", "pkg/tests/test_mod.py"],
        existing_patch_files=["pkg/mod.py"],
        existing_diff_excerpt="diff --git a/pkg/mod.py b/pkg/mod.py\n@@\n-old\n+new",
    )

    assert "First command in this round must be a direct edit to a focus file." in task
    assert "Do not run read/search before first edit in this round." in task
    assert "Likely files to inspect/edit first:" in task
    assert "## Existing Candidate Patch" in task
    assert "Modify that patch directly instead of rediscovering the repository." in task
    assert "Current diff excerpt:" in task
    assert "Suggested first command shape:" in task


def test_qwen_format_compile_failure_task_includes_syntax_context():
    interface = QwenMiniInterface()

    task = interface._format_compile_failure_task(
        "Fix syntax",
        "",
        {
            "compile_failed_files": ["pkg/mod.py"],
            "details": [{"file": "pkg/mod.py", "current_error": "SyntaxError:bad@12:4"}],
        },
        focus_files=["pkg/mod.py"],
        existing_diff_excerpt="diff --git a/pkg/mod.py b/pkg/mod.py\n@@ -12 +12 @@\n-old\n+new",
        source_excerpt="  12: new",
        verify_command="python -m py_compile pkg/mod.py",
    )

    assert "This is a syntax-repair round only." in task
    assert "Current rejected diff excerpt:" in task
    assert "Compile-error source excerpt:" in task
    assert "Preferred verification command:" in task
    assert "First command in this round must be a direct edit to a failing focus file" in task
    assert "Do not run read/search before first edit in this round." in task


def test_qwen_format_test_failure_task_requires_edit_first():
    interface = QwenMiniInterface()

    task = interface._format_test_failure_task(
        "Fix failing test",
        "",
        {"f2p_passed": 0, "f2p_total": 2, "f2p_reliable": True},
        fail_to_pass_tests=["pkg/tests/test_mod.py::test_bug"],
        focus_files=["pkg/mod.py"],
        existing_diff_excerpt="diff --git a/pkg/mod.py b/pkg/mod.py\n@@ -12 +12 @@\n-old\n+new",
    )

    assert "First command in this round must be a direct edit to a focus file." in task
    assert "Do not run read/search or inline python probes before first edit in this round." in task
    assert "Likely files to inspect/edit first:" in task
    assert "Suggested first command shape:" in task


def test_qwen_format_retry_task_includes_previous_bounded_fallback_signal():
    interface = QwenMiniInterface()
    task = interface._format_retry_task(
        problem_statement="Fix the bug",
        hints_text="",
        tdd_mode=True,
        attempt_idx=2,
        prev_attempt={
            "regression_source": "bounded_fallback_smoke",
            "regression_tests_run": 4,
            "regression_tests_failed": 1,
            "regression_signal_reliable": True,
            "loop_abort_reason": "no_diff_streak:4",
        },
        prev_candidate={
            "graphrag_metadata": {
                "impacted_failed_tests": [
                    {"test_name": "pkg/tests/test_mod.py::test_bug", "error": "failed"},
                ]
            }
        },
        focus_files=["pkg/mod.py"],
    )

    assert "Previous bounded regression signal (bounded_fallback_smoke) ran 4 tests with 1 failures." in task
    assert "Use that existing regression signal after your next edit instead of rediscovering regression scope." in task
    assert "Previously failing regression tests: pkg/tests/test_mod.py::test_bug." in task


def test_qwen_format_retry_task_keeps_strategy_shift_anchored_to_best_file():
    interface = QwenMiniInterface()

    task = interface._format_retry_task(
        problem_statement="Fix the bug",
        hints_text="",
        tdd_mode=True,
        attempt_idx=2,
        prev_attempt={"loop_abort_reason": "post_edit_no_diff_streak:2"},
        prev_candidate={"changed_files": ["pkg/mod.py"], "changed_lines_total": 8},
        best_candidate={"changed_files": ["pkg/mod.py"]},
        force_strategy_shift=True,
        focus_files=["pkg/mod.py"],
    )

    assert "Change the fix mechanism now, but stay anchored to the best-so-far file unless there is strong evidence the file is wrong." in task
    assert "Best-so-far changed files: pkg/mod.py" in task
    assert "Do not rediscover repository structure before editing" in task
    assert "First command in this retry must be a direct edit to a carried-over focus file." in task
    assert "Do not run read/search or inline python probes before first edit in this retry." in task
    assert "Likely files to inspect/edit first:" in task
    assert "Do not run read/search before first edit in this round." in task


def test_qwen_format_retry_task_switches_to_patch_refinement_when_diff_exists():
    interface = QwenMiniInterface()

    task = interface._format_retry_task(
        problem_statement="Fix the bug",
        hints_text="",
        tdd_mode=True,
        attempt_idx=2,
        prev_attempt={"loop_abort_reason": "post_edit_no_diff_streak:2", "patch_gate_reason": "ok"},
        prev_candidate={"changed_files": ["pkg/mod.py"], "changed_lines_total": 4},
        best_candidate={"changed_files": ["pkg/mod.py"]},
        force_strategy_shift=True,
        focus_files=["pkg/mod.py"],
        existing_diff_excerpt="diff --git a/pkg/mod.py b/pkg/mod.py\n@@ -10 +10 @@\n-old_value = 1\n+old_value = right\n",
        source_excerpt="  9: def helper_two():\n 10:     old_value = right\n",
    )

    assert "Stay in patch-refinement mode." in task
    assert "Modify the shown diff hunk or adjacent executable lines before widening scope." in task
    assert "Do not restart repository discovery or re-open the file header to understand it." in task
    assert "Change the fix mechanism inside the same hunk before widening scope" in task
    assert "Refine the shown diff hunk directly." in task


def test_qwen_validate_patch_quality_rejects_comment_only_diff(tmp_path):
    interface = QwenMiniInterface()
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    file_path = repo / "mod.py"
    file_path.write_text("def f():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "mod.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

    file_path.write_text("def f():\n    # comment only\n    return 1\n", encoding="utf-8")

    decision = interface._validate_patch_quality(repo)

    assert decision["valid"] is False
    assert decision["reason"] == "comment_only_diff"


def test_qwen_apply_round_command_guard_blocks_submit_for_comment_only_diff(tmp_path):
    interface = QwenMiniInterface()
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    file_path = repo / "mod.py"
    file_path.write_text("def f():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "mod.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

    file_path.write_text("def f():\n    # comment only\n    return 1\n", encoding="utf-8")

    guard = interface._apply_round_command_guard(
        command="echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT",
        repo_path=repo,
        round_profile={"round_mode": "default", "block_scratch_python_before_edit": False},
        focus_files=["mod.py"],
        edit_seen=True,
    )

    assert guard["blocked"] is True
    assert guard["reason"] == "submit_requires_semantic_patch"
    assert "Comments alone will not be accepted" in guard["message"]


def test_qwen_summarize_previous_wrong_hypothesis_uses_files_and_functions():
    interface = QwenMiniInterface()

    summary = interface._summarize_previous_wrong_hypothesis(
        {
            "changed_files": ["pkg/mod.py"],
            "prediction": "diff --git a/pkg/mod.py b/pkg/mod.py\n@@\n-def _cdot(x):\n+def _cdot(x):\n",
        }
    )

    assert "changed pkg/mod.py" in summary
    assert "touched _cdot" in summary


def test_qwen_evaluate_monotonic_progress_detects_stagnant_failure_signature():
    interface = QwenMiniInterface()
    prev_candidate = {
        "patch_gate_reason": "ok",
        "loop_abort_reason": "",
        "changed_files": ["pkg/mod.py"],
        "f2p_passed": 0,
        "f2p_failed": 2,
        "p2p_smoke_failures": 1,
        "regression_tests_failed": 1,
        "graphrag_metadata": {"impacted_failed_tests": []},
        "progress_gate_stagnation_count": 1,
    }
    prev_candidate["failure_signature"] = interface._build_failure_signature(prev_candidate)

    current = {
        "patch_gate_reason": "ok",
        "loop_abort_reason": "",
        "changed_files": ["pkg/mod.py"],
        "f2p_passed": 0,
        "f2p_failed": 2,
        "p2p_smoke_failures": 1,
        "regression_tests_failed": 1,
        "graphrag_metadata": {"impacted_failed_tests": []},
    }

    progress = interface._evaluate_monotonic_progress(
        candidate=current,
        prev_candidate=prev_candidate,
    )

    assert progress["progress_gate_passed"] is False
    assert progress["progress_gate_reason"] == "stagnant_failure_signature"
    assert progress["progress_gate_stagnation_count"] == 2
    assert progress["progress_gate_relocalize"] is True


def test_qwen_build_verify_command_prefers_failing_tests_then_py_compile():
    interface = QwenMiniInterface()

    assert (
        interface._build_verify_command(
            round_mode="regression_repair",
            focus_files=["pkg/mod.py", "pkg/tests/test_mod.py"],
            failing_tests=["pkg/tests/test_mod.py::test_bug"],
        )
        == "python -m pytest -q pkg/tests/test_mod.py::test_bug"
    )
    assert (
        interface._build_verify_command(
            round_mode="compile_repair",
            focus_files=["pkg/mod.py"],
            compile_failed_files=["pkg/mod.py"],
        )
        == "python -m py_compile pkg/mod.py"
    )


def test_qwen_prioritize_focus_files_keeps_pinned_changed_file_first():
    interface = QwenMiniInterface()

    prioritized = interface._prioritize_focus_files(
        ["pkg/core.py", "pkg/separable.py", "pkg/tests/test_mod.py"],
        pinned_files=["pkg/separable.py"],
    )

    assert prioritized[0] == "pkg/separable.py"


def test_qwen_build_focus_source_excerpt_prefers_anchor_file(tmp_path):
    interface = QwenMiniInterface()
    repo = tmp_path / "repo"
    pkg = repo / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "core.py").write_text("def core():\n    return 1\n", encoding="utf-8")
    (pkg / "separable.py").write_text("def sep():\n    return 2\n", encoding="utf-8")

    excerpt = interface._build_focus_source_excerpt(
        repo,
        focus_files=["pkg/core.py", "pkg/separable.py"],
        anchor_file="pkg/separable.py",
    )

    assert "return 2" in excerpt
    assert "return 1" not in excerpt


def test_qwen_build_focus_source_excerpt_prefers_hunk_local_function_context(tmp_path):
    interface = QwenMiniInterface()
    repo = tmp_path / "repo"
    pkg = repo / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "mod.py").write_text(
        "def helper_one():\n"
        "    return 1\n\n"
        "def helper_two():\n"
        "    old_value = 2\n"
        "    return old_value\n",
        encoding="utf-8",
    )

    context = interface._build_focus_source_excerpt(
        repo,
        focus_files=["pkg/mod.py"],
        diff_excerpt="diff --git a/pkg/mod.py b/pkg/mod.py\n@@ -5 +5 @@\n-    old_value = 2\n+    old_value = right\n",
        include_meta=True,
    )

    assert context["source_kind"] == "diff_hunk"
    assert context["symbol_name"] == "helper_two"
    assert "def helper_two" in context["excerpt"]
    assert "def helper_one" not in context["excerpt"]


def test_qwen_retry_carryover_uses_best_candidate_diff_hunk_when_repo_is_clean(tmp_path):
    interface = QwenMiniInterface()
    repo = tmp_path / "repo"
    pkg = repo / "pkg"
    pkg.mkdir(parents=True)
    (repo / ".git").mkdir()
    (pkg / "mod.py").write_text(
        "def helper_one():\n"
        "    return 1\n\n"
        "def helper_two():\n"
        "    old_value = 2\n"
        "    return old_value\n",
        encoding="utf-8",
    )

    patch_text = (
        "diff --git a/pkg/mod.py b/pkg/mod.py\n"
        "index 1111111..2222222 100644\n"
        "--- a/pkg/mod.py\n"
        "+++ b/pkg/mod.py\n"
        "@@ -5 +5 @@ def helper_two():\n"
        "-    old_value = 2\n"
        "+    old_value = right\n"
    )

    diff_excerpt = interface._build_current_diff_excerpt(repo, changed_files=["pkg/mod.py"])
    assert diff_excerpt == ""

    diff_excerpt = interface._build_diff_excerpt_from_patch_text(patch_text)
    context = interface._build_focus_source_excerpt(
        repo,
        focus_files=["pkg/mod.py"],
        diff_excerpt=diff_excerpt,
        anchor_file="pkg/mod.py",
        include_meta=True,
    )

    assert diff_excerpt.startswith("diff --git a/pkg/mod.py b/pkg/mod.py")
    assert context["source_kind"] == "diff_hunk"
    assert context["symbol_name"] == "helper_two"
    assert "def helper_two" in context["excerpt"]
    assert "def helper_one" not in context["excerpt"]


def test_qwen_runtime_verify_command_uses_runtime_pytest_fallback(monkeypatch, tmp_path):
    interface = QwenMiniInterface()
    repo = tmp_path / "repo"
    repo.mkdir()

    monkeypatch.setattr(
        interface.test_runtime_manager,
        "get_runtime",
        lambda repo_root, log=None: {
            "runtime_env_id": "venv",
            "python_executable": "python-runtime",
            "env": {},
            "runtime_ready": True,
            "bootstrap_actions": [],
            "runtime_bootstrap_attempts": [],
            "bootstrap_error": "",
            "bootstrap_error_reason": "",
            "runtime_install_mode": "editable",
        },
    )

    def fake_run(cmd, **kwargs):
        assert cmd[:3] == ["python-runtime", "-m", "pytest"]
        return SimpleNamespace(
            returncode=2,
            stdout="",
            stderr="ImportPathMismatchError: pkg/tests/test_mod.py",
        )

    monkeypatch.setattr("utils.qwen_mini_interface.subprocess.run", fake_run)
    monkeypatch.setattr(
        interface,
        "_run_pytest_subset",
        lambda repo_path, tests, timeout, log=print: {
            "output": "1 passed",
            "returncode": 0,
        },
    )

    result = interface._maybe_execute_runtime_verify_command(
        command="pytest -q pkg/tests/test_mod.py::test_bug",
        repo_path=repo,
        timeout=45,
    )

    assert result == {
        "output": (
            "Normalized runtime pytest fallback used after import_path_mismatch.\n"
            "Original command: pytest -q pkg/tests/test_mod.py::test_bug\n"
            "1 passed"
        ),
        "returncode": 0,
    }


def test_graphrag_tdd_profile_caps_model_completion_tokens(monkeypatch):
    monkeypatch.delenv("QWEN_MINI_MODEL_MAX_TOKENS", raising=False)
    monkeypatch.delenv("QWEN_MINI_GRAPHRAG_TDD_MODEL_MAX_TOKENS", raising=False)

    interface = QwenMiniInterfaceGraphRAGTDD()

    assert interface.model_max_tokens == 2048


def test_qwen_validate_patch_quality_rejects_removed_function_without_replacement(tmp_path):
    interface = QwenMiniInterface()
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    file_path = repo / "mod.py"
    file_path.write_text("def f():\n    return 1\n\ndef g():\n    return 2\n", encoding="utf-8")
    subprocess.run(["git", "add", "mod.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

    file_path.write_text("def f():\n    return 1\n", encoding="utf-8")

    decision = interface._validate_patch_quality(repo)

    assert decision["valid"] is False
    assert "removed_function_without_replacement:mod.py:g" in decision["reason"]


def test_qwen_preflight_blocks_git_revert_commands(tmp_path):
    interface = QwenMiniInterface()

    blocked = interface._preflight_command(
        command="git checkout astropy/modeling/separable.py",
        repo_path=tmp_path,
    )
    assert blocked["blocked"] is True
    assert blocked["reason"] == "git_revert_blocked"

    blocked = interface._preflight_command(
        command="git restore astropy/modeling/separable.py",
        repo_path=tmp_path,
    )
    assert blocked["blocked"] is True
    assert blocked["reason"] == "git_revert_blocked"


def test_qwen_preflight_blocks_noop_echo_commands(tmp_path):
    interface = QwenMiniInterface()

    blocked = interface._preflight_command(
        command='echo "The fix requires adding a transform function"',
        repo_path=tmp_path,
    )

    assert blocked["blocked"] is True
    assert blocked["reason"] == "lint_noop_echo"


def test_qwen_preflight_blocks_brittle_python_sed_rewrites(tmp_path):
    interface = QwenMiniInterface()

    blocked = interface._preflight_command(
        command=(
            "sed -i '' 's/if isinstance(model, CompoundModel):/if isinstance(model, CompoundModel):\\\n"
            "        # nested fix\\\n"
            "        # more text/' astropy/modeling/separable.py"
        ),
        repo_path=tmp_path,
    )

    assert blocked["blocked"] is True
    assert blocked["reason"] == "lint_brittle_sed_edit"


def test_qwen_detects_full_python_cat_dump():
    interface = QwenMiniInterface()

    assert interface._is_full_python_cat_dump("cat astropy/modeling/separable.py")
    assert not interface._is_full_python_cat_dump("sed -n '1,40p' astropy/modeling/separable.py")


def test_qwen_derive_source_candidate_from_test_file_uses_imported_modules(tmp_path):
    interface = QwenMiniInterface()
    repo = tmp_path / "repo"
    (repo / "astropy/coordinates/tests").mkdir(parents=True)
    (repo / "astropy/coordinates/builtin_frames").mkdir(parents=True)
    test_file = repo / "astropy/coordinates/tests/test_intermediate_transformations.py"
    test_file.write_text(
        "from astropy.coordinates.builtin_frames import AltAz, ITRS, HADec\n",
        encoding="utf-8",
    )
    for rel_path in (
        "astropy/coordinates/builtin_frames/__init__.py",
        "astropy/coordinates/builtin_frames/altaz.py",
        "astropy/coordinates/builtin_frames/itrs.py",
        "astropy/coordinates/builtin_frames/hadec.py",
    ):
        path = repo / rel_path
        path.write_text("", encoding="utf-8")

    candidates = interface._derive_source_candidate_from_test_file(
        repo,
        "astropy/coordinates/tests/test_intermediate_transformations.py",
    )

    assert "astropy/coordinates/builtin_frames/altaz.py" in candidates
    assert "astropy/coordinates/builtin_frames/itrs.py" in candidates
    assert "astropy/coordinates/builtin_frames/hadec.py" in candidates


def test_qwen_test_change_requirement_waived_when_existing_fail_to_pass_tests_present():
    interface = QwenMiniInterface()

    required, reason = interface._resolve_test_change_requirement(
        tdd_mode=True,
        graphrag_enabled=True,
        runtime_reliable_for_test_contract=True,
        fail_to_pass_tests=["pkg/tests/test_mod.py::test_bug"],
    )

    assert required is False
    assert reason == "waived_existing_repo_fail_to_pass"


def test_qwen_best_candidate_prefers_verification_progress_over_non_empty_red_patch():
    interface = QwenMiniInterface()

    red_candidate = {
        "prediction": "diff --git a/a.py b/a.py",
        "clean_resolution": False,
        "verify_pass_after_edit": False,
        "smoke_pass_after_edit": False,
        "tdd_gate_passed": True,
        "regression_gate_passed": True,
        "status": "Submitted",
        "patch_gate_severity": "info",
        "patch_gate_valid": True,
        "patch_gate_reason": "ok",
        "loop_abort_reason": "",
        "changed_lines_total": 4,
        "attempt": 1,
        "f2p_pass_rate": 0.0,
        "p2p_smoke_failures": 1,
        "test_signal_confidence": 1.0,
        "test_signal_reliable": True,
        "format_errors": 0,
        "timeouts": 0,
        "steps": 5,
    }
    green_candidate = dict(red_candidate)
    green_candidate["verify_pass_after_edit"] = True
    green_candidate["f2p_pass_rate"] = 1.0

    assert interface._should_replace_best_candidate(
        green_candidate,
        interface._score_candidate(green_candidate),
        red_candidate,
        interface._score_candidate(red_candidate),
    )


def test_qwen_should_continue_tdd_fix_round_requires_reliable_signal():
    interface = object.__new__(QwenMiniInterface)
    interface.iter_fix_require_reliable_signal = True
    interface.iter_fix_min_remaining_sec = 180

    should_continue, reason = interface._should_continue_tdd_fix_round(
        require_test_checks=True,
        f2p_total=2,
        f2p_all_passed=False,
        f2p_reliable=False,
        current_round=0,
        max_rounds=1,
        remaining_budget_sec=600,
    )

    assert should_continue is False
    assert reason == "infra_unreliable"


def test_qwen_should_continue_tdd_fix_round_honors_budget_and_round_limit():
    interface = object.__new__(QwenMiniInterface)
    interface.iter_fix_require_reliable_signal = True
    interface.iter_fix_min_remaining_sec = 180

    should_continue, reason = interface._should_continue_tdd_fix_round(
        require_test_checks=True,
        f2p_total=2,
        f2p_all_passed=False,
        f2p_reliable=True,
        current_round=1,
        max_rounds=1,
        remaining_budget_sec=600,
    )
    assert should_continue is False
    assert reason == "round_limit_reached"

    should_continue, reason = interface._should_continue_tdd_fix_round(
        require_test_checks=True,
        f2p_total=2,
        f2p_all_passed=False,
        f2p_reliable=True,
        current_round=0,
        max_rounds=1,
        remaining_budget_sec=60,
    )
    assert should_continue is False
    assert reason == "low_remaining_budget"


def test_qwen_compile_valid_stop_requires_tdd_and_regression_gates():
    interface = object.__new__(QwenMiniInterface)
    interface.compile_valid_submit_stop = True

    candidate = {
        "tdd_gate_passed": False,
        "regression_gate_passed": True,
    }
    assert not interface._should_stop_on_compile_valid_submission(
        candidate=candidate,
        tdd_mode=True,
        graphrag_enabled=True,
    )

    candidate = {
        "tdd_gate_passed": True,
        "regression_gate_passed": False,
    }
    assert not interface._should_stop_on_compile_valid_submission(
        candidate=candidate,
        tdd_mode=True,
        graphrag_enabled=True,
    )

    candidate = {
        "tdd_gate_passed": True,
        "regression_gate_passed": True,
    }
    assert interface._should_stop_on_compile_valid_submission(
        candidate=candidate,
        tdd_mode=True,
        graphrag_enabled=True,
    )


def test_qwen_timeout_checkpoint_roundtrip(tmp_path):
    interface = object.__new__(QwenMiniInterface)
    interface.timeout_recover_best_patch = True

    checkpoint = tmp_path / "timeout_checkpoint.json"
    interface._timeout_checkpoint_path = lambda instance_id, worker_pid: checkpoint

    candidate = {
        "prediction": "diff --git a/a.py b/a.py\n+pass\n",
        "patch_gate_valid": True,
        "status": "Submitted",
        "attempt": 1,
    }
    interface._write_timeout_checkpoint(
        instance_id="repo__issue-1",
        worker_pid=1234,
        candidate=candidate,
    )

    recovered = interface.recover_timeout_prediction("repo__issue-1", 1234)
    assert recovered is not None
    assert "diff --git" in recovered["prediction"]
    assert recovered["timeout_recovered"] is True


def test_qwen_build_direct_edit_command_example_uses_heredoc():
    interface = object.__new__(QwenMiniInterface)

    command = interface._build_direct_edit_command_example(
        primary_file="pkg/example.py",
        diff_excerpt="@@ -10 +10 @@\n-    result : ndarray\n+    if isinstance(right, Model):",
    )

    assert "python3 - <<'PY'" in command
    assert "Path('pkg/example.py')" in command


def test_qwen_extract_diff_anchor_line_prefers_executable_code():
    interface = object.__new__(QwenMiniInterface)

    anchor = interface._extract_diff_anchor_line(
        "@@ -10,3 +10,3 @@\n-    result : ndarray\n-        Result from this operation.\n+    if isinstance(right, Model):\n+        cright = _coord_matrix(right, 'right', noutp)"
    )

    assert anchor == "if isinstance(right, Model):"


def test_graphrag_local_meta_uses_status_metadata(monkeypatch):
    interface = GraphRAGLocalInterface()

    class FakeDB:
        def get_status_metadata(self):
            return {
                "total_nodes": 1,
                "graph_identity": "owner/repo@abc123",
                "repo_fingerprint": "abc123:clean",
                "path_format": "relative",
            }

    monkeypatch.setattr("utils.graphrag_local_interface.get_db", lambda: FakeDB())

    meta = interface._get_graph_meta()

    assert meta["success"] is True
    assert meta["graph_identity"] == "owner/repo@abc123"
    assert meta["total_nodes"] == 1
