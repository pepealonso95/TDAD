import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from run_benchmark import BenchmarkRunner, VARIANT_REGISTRY


def _run_and_read_config(runner, monkeypatch):
    monkeypatch.setattr(runner, "_load_instances", lambda: [])
    runner.run()
    config_path = runner.run_dir / "config.json"
    return json.loads(config_path.read_text(encoding="utf-8"))


def test_saved_config_uses_effective_graphrag_profile_controls(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    runner = BenchmarkRunner(
        dataset="dummy",
        variants=[VARIANT_REGISTRY["graphrag_tdd"]],
        limit=1,
        skip_eval=True,
        max_fix_iterations=0,
        max_fix_iterations_explicit=False,
        graphrag_tool_mode="mcp",
    )

    config = _run_and_read_config(runner, monkeypatch)
    effective = config["variants_effective_controls"][0]

    # Raw CLI/requested value is still preserved.
    assert config["max_fix_iterations"] == 0
    # Effective runtime control reflects graphrag_tdd profile override.
    assert effective["name"] == "graphrag_tdd"
    assert effective["step_limit"] == 56
    assert effective["max_fix_iterations"] == 1
    assert effective["test_signal_mode"] == "soft"
    assert effective["retry_policy"] == "adaptive"
    assert effective["enforce_tdd_test_first"] is False
    # Benchmark hardening forces local GraphRAG tool mode at runtime.
    assert effective["graphrag_tool_mode"] == "local"
    assert effective["graph_refresh_policy"] == "auto"


def test_saved_config_respects_explicit_max_fix_iterations(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    runner = BenchmarkRunner(
        dataset="dummy",
        variants=[VARIANT_REGISTRY["graphrag_tdd"]],
        limit=1,
        skip_eval=True,
        max_fix_iterations=7,
        max_fix_iterations_explicit=True,
    )

    config = _run_and_read_config(runner, monkeypatch)
    effective = config["variants_effective_controls"][0]

    # Explicit CLI override takes precedence over graphrag_tdd profile default.
    assert effective["max_fix_iterations"] == 7


def test_saved_config_records_model_override(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    runner = BenchmarkRunner(
        dataset="dummy",
        variants=[VARIANT_REGISTRY["graphrag_tdd"]],
        limit=1,
        skip_eval=True,
        model="qwen-mini-30b",
    )

    config = _run_and_read_config(runner, monkeypatch)

    assert config["model"] == "qwen-mini-30b"


def test_saved_config_uses_auto_eval_workers_when_legacy_max_workers_is_one(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "run_benchmark.default_eval_worker_count",
        lambda instance_count=None: 4,
    )
    runner = BenchmarkRunner(
        dataset="dummy",
        variants=[VARIANT_REGISTRY["vanilla"]],
        limit=1,
        skip_eval=True,
        max_workers=1,
        max_workers_explicit=True,
    )

    config = _run_and_read_config(runner, monkeypatch)

    assert config["max_workers"] == 1
    assert config["eval_max_workers"] is None
    assert config["eval_max_workers_effective"] == 4


def test_saved_config_respects_explicit_eval_max_workers(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    runner = BenchmarkRunner(
        dataset="dummy",
        variants=[VARIANT_REGISTRY["vanilla"]],
        limit=1,
        skip_eval=True,
        max_workers=1,
        eval_max_workers=3,
        max_workers_explicit=True,
    )

    config = _run_and_read_config(runner, monkeypatch)

    assert config["eval_max_workers"] == 3
    assert config["eval_max_workers_effective"] == 3


def test_run_variant_cleans_up_agent_after_generation(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    cleanup_calls = []

    class FakeAgent:
        def __init__(self, *args, **kwargs):
            self.pred_timestamp = "20260306_120000"
            self.pred_file = None
            Path("predictions").mkdir(exist_ok=True)

        def process_instance(self, instance):
            return {
                "instance_id": instance["instance_id"],
                "model": "qwen-mini",
                "prediction": "diff --git a/a.py b/a.py",
            }

        def _save_predictions(self, prediction):
            assert self.pred_file is not None
            with self.pred_file.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(prediction) + "\n")

        def cleanup(self):
            cleanup_calls.append("called")

    monkeypatch.setattr("run_benchmark.CodeSWEAgent", FakeAgent)

    runner = BenchmarkRunner(
        dataset="dummy",
        variants=[VARIANT_REGISTRY["vanilla"]],
        limit=1,
        skip_eval=True,
    )

    vr = runner._run_variant(
        VARIANT_REGISTRY["vanilla"],
        [{"instance_id": "demo__1"}],
    )

    assert vr.generation_count == 1
    assert cleanup_calls == ["called"]


def test_run_variant_persists_prompt_and_mlx_telemetry(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    class FakeAgent:
        def __init__(self, *args, **kwargs):
            self.pred_timestamp = "20260309_000000"
            self.pred_file = None
            Path("predictions").mkdir(exist_ok=True)

        def process_instance(self, instance):
            return {
                "instance_id": instance["instance_id"],
                "model": "qwen-mini-graphrag",
                "prediction": "diff --git a/a.py b/a.py",
                "prompt_trace_id": "trace-123",
                "prompt_estimated_tokens_after": 2085,
                "prompt_trimmed": False,
                "mlx_backend_after": {"pid": 83377, "rss_kb": 416416},
                "mlx_backend_reused_existing": True,
                "mlx_backend_started_now": False,
                "mlx_backend_crash_detected": False,
                "mlx_backend_restarted": False,
                "mlx_backend_failure_reason": "",
            }

        def _save_predictions(self, prediction):
            assert self.pred_file is not None
            with self.pred_file.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(prediction) + "\n")

        def cleanup(self):
            return None

    monkeypatch.setattr("run_benchmark.CodeSWEAgent", FakeAgent)

    runner = BenchmarkRunner(
        dataset="dummy",
        variants=[VARIANT_REGISTRY["vanilla"]],
        limit=1,
        skip_eval=True,
    )

    vr = runner._run_variant(
        VARIANT_REGISTRY["vanilla"],
        [{"instance_id": "demo__telemetry"}],
    )
    runner.results.append(vr)
    runner._save_report([{"instance_id": "demo__telemetry"}])

    instance = vr.instances[0]
    assert instance.prompt_trace_id == "trace-123"
    assert instance.prompt_estimated_tokens_after == 2085
    assert instance.prompt_trimmed is False
    assert instance.mlx_backend_pid == 83377
    assert instance.mlx_backend_rss_kb == 416416
    assert instance.mlx_backend_reused_existing is True
    assert instance.mlx_backend_started_now is False
    assert instance.mlx_backend_crash_detected is False
    assert instance.mlx_backend_restarted is False

    report = json.loads((runner.run_dir / "report.json").read_text())
    report_instance = report["variants"][0]["instances"][0]
    assert report_instance["prompt_trace_id"] == "trace-123"
    assert report_instance["prompt_estimated_tokens_after"] == 2085
    assert report_instance["prompt_trimmed"] is False
    assert report_instance["mlx_backend_pid"] == 83377
    assert report_instance["mlx_backend_rss_kb"] == 416416
    assert report_instance["mlx_backend_reused_existing"] is True


def test_run_instance_with_timeout_uses_spawn_context_in_isolated_mode(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    runner = BenchmarkRunner(
        dataset="dummy",
        variants=[VARIANT_REGISTRY["vanilla"]],
        limit=1,
        skip_eval=True,
        isolate_instances="on",
        instance_timeout_sec=123,
    )

    captured = {}
    events = []

    class FakeQueue:
        def get(self, timeout=None):
            captured["queue_get_timeout"] = timeout
            events.append("get")
            return {
                "ok": True,
                "prediction": {
                    "instance_id": "demo__1",
                    "model": "qwen-mini",
                    "prediction": "diff --git a/a.py b/a.py",
                },
            }

        def close(self):
            return None

    class FakeProcess:
        def __init__(self, target=None, args=None, daemon=None):
            captured["target"] = target
            captured["args"] = args
            captured["daemon"] = daemon
            self.pid = 43210
            self.exitcode = 0

        def start(self):
            captured["started"] = True

        def join(self, timeout=None):
            captured.setdefault("join_timeouts", []).append(timeout)
            events.append(f"join:{timeout}")

        def is_alive(self):
            return False

    class FakeContext:
        def Queue(self, maxsize=0):
            captured["queue_maxsize"] = maxsize
            return FakeQueue()

        def Process(self, target=None, args=None, daemon=None):
            return FakeProcess(target=target, args=args, daemon=daemon)

    def fake_get_context(name):
        captured["context_name"] = name
        return FakeContext()

    monkeypatch.setattr("run_benchmark.mp.get_context", fake_get_context)

    prediction = runner._run_instance_with_timeout(
        None,
        {"instance_id": "demo__1"},
        agent_spec={"backend": "qwen-mini", "use_graphrag": False},
    )

    assert captured["context_name"] == "spawn"
    assert captured["started"] is True
    assert captured["queue_get_timeout"] == 0.25
    assert captured["join_timeouts"] == [5]
    assert captured["args"][0] == {"backend": "qwen-mini", "use_graphrag": False}
    assert events[0] == "get"
    assert prediction["instance_id"] == "demo__1"


def test_evaluate_uses_effective_eval_workers(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "run_benchmark.default_eval_worker_count",
        lambda instance_count=None: 4,
    )
    monkeypatch.setattr(
        "run_benchmark.describe_eval_capacity",
        lambda instance_count=None: {
            "workers": 4,
            "cpu_total": 14,
            "cpu_target": 7,
            "mem_total_gib": 8.0,
            "mem_target": 4,
        },
    )
    monkeypatch.setattr("run_benchmark.cleanup_stale_swebench_eval_containers", lambda: [])
    runner = BenchmarkRunner(
        dataset="dummy",
        variants=[VARIANT_REGISTRY["vanilla"]],
        limit=1,
        skip_eval=False,
        max_workers=1,
        max_workers_explicit=True,
    )

    pred_path = tmp_path / "predictions.jsonl"
    pred_path.write_text("{}\n", encoding="utf-8")
    eval_json = tmp_path / "result.eval.json"
    eval_json.write_text(
        json.dumps(
            {
                "resolved_instances": 1,
                "unresolved_instances": 0,
                "instances": {"demo__1": {"resolved": True}},
            }
        ),
        encoding="utf-8",
    )

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(
            returncode=0,
            stdout=f"EVAL_JSON_PATH: {eval_json}\n",
            stderr="",
        )

    monkeypatch.setattr("run_benchmark.subprocess.run", fake_run)

    vr = runner._evaluate(
        SimpleNamespace(
            name="vanilla",
            predictions_file=str(pred_path),
            eval_file="",
            instances=[SimpleNamespace(instance_id="demo__1", resolved=None, p2p_smoke_failures=None, clean_resolution=None)],
            resolved_count=0,
            unresolved_count=0,
            eval_ran=False,
        )
    )

    assert "--max-workers" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--max-workers") + 1] == "4"
    assert vr.eval_ran is True
    assert vr.resolved_count == 1
