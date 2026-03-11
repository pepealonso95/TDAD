import signal
import sys
from pathlib import Path
from types import SimpleNamespace

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.local_model_backend import (
    OwnedBackendProcess,
    _default_mlxlm_idle_policy,
    _owned_backend_record_path,
    describe_local_backend_runtime,
    ensure_local_backend_ready,
    resolve_qwen_local_backend,
    set_local_backend_idle_if_owned,
    stop_local_backend_if_owned,
)


def test_resolve_qwen_local_backend_supports_mlxlm_defaults(monkeypatch):
    monkeypatch.setenv("QWEN_MINI_LOCAL_PROVIDER", "mlxlm")

    backend = resolve_qwen_local_backend(prefix="QWEN_MINI")

    assert backend.provider == "mlxlm"
    assert backend.provider_label == "MLX-LM"
    assert backend.model_name == "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2"
    assert backend.api_base == "http://127.0.0.1:8091/v1"
    assert backend.litellm_model_name == f"openai/{backend.model_name}"


def test_resolve_qwen_local_backend_maps_qwen_alias_to_mlx_model(monkeypatch):
    monkeypatch.setenv("QWEN_MINI_LOCAL_PROVIDER", "mlx-lm")

    backend = resolve_qwen_local_backend(
        prefix="QWEN_MINI",
        explicit_model="qwen3-coder:30b",
    )

    assert backend.provider == "mlxlm"
    assert backend.model_name == "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2"


def test_resolve_qwen_local_backend_keeps_llamacpp_default_even_with_mlxlm_env(monkeypatch):
    monkeypatch.delenv("QWEN_MINI_LOCAL_PROVIDER", raising=False)
    monkeypatch.delenv("QWEN_LOCAL_PROVIDER", raising=False)
    monkeypatch.setenv("QWEN_MINI_MLXLM_MODEL", "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2")
    monkeypatch.setenv("QWEN_MINI_MLXLM_API_BASE", "http://127.0.0.1:8091/v1")
    monkeypatch.setenv("QWEN_MINI_LLAMACPP_API_BASE", "http://127.0.0.1:8081/v1")

    backend = resolve_qwen_local_backend(prefix="QWEN_MINI")

    assert backend.provider == "llamacpp"
    assert backend.provider_label == "llama.cpp"
    assert backend.model_name == "qwen3-coder:30b"
    assert backend.api_base == "http://127.0.0.1:8081/v1"


def test_mlxlm_litellm_kwargs_enable_thinking_by_default(monkeypatch):
    monkeypatch.setenv("QWEN_MINI_LOCAL_PROVIDER", "mlxlm")

    backend = resolve_qwen_local_backend(prefix="QWEN_MINI")
    kwargs = backend.build_litellm_kwargs(
        temperature=0.0,
        max_tokens=256,
        timeout=30,
    )

    assert kwargs["extra_body"] == {"chat_template_kwargs": {"enable_thinking": True}}


def test_mlxlm_litellm_kwargs_can_disable_thinking(monkeypatch):
    monkeypatch.setenv("QWEN_MINI_LOCAL_PROVIDER", "mlxlm")
    monkeypatch.setenv("QWEN_MINI_MLXLM_ENABLE_THINKING", "off")

    backend = resolve_qwen_local_backend(prefix="QWEN_MINI")
    kwargs = backend.build_litellm_kwargs(
        temperature=0.0,
        max_tokens=256,
        timeout=30,
    )

    assert "extra_body" not in kwargs


def test_ensure_local_backend_ready_autostarts_llamacpp(monkeypatch, tmp_path):
    monkeypatch.setenv("QWEN_MINI_LOCAL_PROVIDER", "llamacpp")
    monkeypatch.setenv("QWEN_MINI_LLAMACPP_API_BASE", "http://127.0.0.1:8089/v1")
    monkeypatch.setenv("QWEN_MINI_LLAMACPP_LOG_DIR", str(tmp_path))
    server_bin = tmp_path / "llama-server"
    server_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    server_bin.chmod(0o755)
    monkeypatch.setenv("QWEN_MINI_LLAMACPP_SERVER_BIN", str(server_bin))
    monkeypatch.delenv("QWEN_MINI_LLAMACPP_MODEL_FILE", raising=False)
    monkeypatch.delenv("QWEN_MINI_LLAMACPP_HF_REPO", raising=False)
    monkeypatch.delenv("QWEN_MINI_LLAMACPP_HF_FILE", raising=False)

    backend = resolve_qwen_local_backend(prefix="QWEN_MINI")
    call_state = {"count": 0, "spawned": None}

    class FakeResponse:
        def raise_for_status(self):
            return None

    def fake_get(*args, **kwargs):
        call_state["count"] += 1
        if call_state["count"] == 1:
            raise requests.exceptions.ConnectionError("not ready")
        return FakeResponse()

    class FakeProcess:
        pid = 5251
        returncode = None

        def poll(self):
            return None

        def terminate(self):
            self.returncode = 0

        def kill(self):
            self.returncode = -9

    def fake_popen(command, **kwargs):
        call_state["spawned"] = command
        return FakeProcess()

    monkeypatch.setattr("utils.local_model_backend.requests.get", fake_get)
    monkeypatch.setattr("utils.local_model_backend.subprocess.Popen", fake_popen)
    monkeypatch.setattr("utils.local_model_backend.time.sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("utils.local_model_backend.os.killpg", lambda _pid, _sig: None)
    monkeypatch.setattr("utils.local_model_backend.os.kill", lambda _pid, _sig: None)
    monkeypatch.setattr("utils.local_model_backend._discover_llamacpp_server_process", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "utils.local_model_backend.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout=" 8192 S 00:01\n", returncode=0),
    )

    ready = ensure_local_backend_ready(backend, prefix="QWEN_MINI", healthcheck_timeout=0.01)

    assert call_state["spawned"] is not None
    assert call_state["spawned"][0] == str(server_bin)
    assert "--hf-repo" in call_state["spawned"]
    assert "lmstudio-community/Qwen3-Coder-30B-A3B-Instruct-GGUF" in call_state["spawned"]
    assert "--hf-file" in call_state["spawned"]
    assert "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf" in call_state["spawned"]
    assert "--alias" in call_state["spawned"]
    assert backend.model_name in call_state["spawned"]
    assert "--api-prefix" in call_state["spawned"]
    assert "/v1" in call_state["spawned"]
    assert ready["started_now"] is True
    assert ready["reused_existing"] is False
    assert ready["snapshot"]["pid"] == 5251
    assert ready["snapshot"]["provider"] == "llamacpp"
    assert stop_local_backend_if_owned(backend, prefix="QWEN_MINI") is True


def test_ensure_local_backend_ready_autostarts_mlxlm(monkeypatch, tmp_path):
    monkeypatch.setenv("QWEN_MINI_LOCAL_PROVIDER", "mlxlm")
    monkeypatch.setenv("QWEN_MINI_MLXLM_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("QWEN_MINI_MLXLM_API_BASE", "http://127.0.0.1:8092/v1")

    backend = resolve_qwen_local_backend(prefix="QWEN_MINI")

    call_state = {"count": 0, "spawned": None}

    class FakeResponse:
        def raise_for_status(self):
            return None

    def fake_get(*args, **kwargs):
        call_state["count"] += 1
        if call_state["count"] == 1:
            raise requests.exceptions.ConnectionError("not ready")
        return FakeResponse()

    class FakeProcess:
        pid = 4241
        returncode = None

        def poll(self):
            return None

        def terminate(self):
            self.returncode = 0

        def kill(self):
            self.returncode = -9

    def fake_popen(command, **kwargs):
        call_state["spawned"] = command
        return FakeProcess()

    monkeypatch.setattr("utils.local_model_backend.requests.get", fake_get)
    monkeypatch.setattr("utils.local_model_backend.subprocess.Popen", fake_popen)
    monkeypatch.setattr("utils.local_model_backend.time.sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("utils.local_model_backend.os.killpg", lambda _pid, _sig: None)
    monkeypatch.setattr("utils.local_model_backend.os.kill", lambda _pid, _sig: None)

    monkeypatch.setattr(
        "utils.local_model_backend.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout=" 2048 S 00:01\n", returncode=0),
    )

    ready = ensure_local_backend_ready(backend, prefix="QWEN_MINI", healthcheck_timeout=0.01)

    assert call_state["spawned"] is not None
    assert call_state["spawned"][:4] == [sys.executable, "-m", "mlx_lm", "server"]
    assert "--model" in call_state["spawned"]
    assert backend.model_name in call_state["spawned"]
    assert ready["started_now"] is True
    assert ready["reused_existing"] is False
    assert ready["snapshot"]["pid"] == 4241
    record = _owned_backend_record_path(backend, prefix="QWEN_MINI")
    payload = record.read_text(encoding="utf-8")
    assert '"origin": "autostart"' in payload
    assert f'"model_name": "{backend.model_name}"' in payload
    assert stop_local_backend_if_owned(backend, prefix="QWEN_MINI") is True


def test_stop_local_backend_if_owned_terminates_autostarted_mlxlm(monkeypatch, tmp_path):
    monkeypatch.setenv("QWEN_MINI_LOCAL_PROVIDER", "mlxlm")
    monkeypatch.setenv("QWEN_MINI_MLXLM_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("QWEN_MINI_MLXLM_API_BASE", "http://127.0.0.1:8093/v1")

    backend = resolve_qwen_local_backend(prefix="QWEN_MINI")
    state = {"count": 0}

    class FakeResponse:
        def raise_for_status(self):
            return None

    class FakeProcess:
        pid = 4242

        def __init__(self):
            self.alive = True
            self.returncode = None

        def poll(self):
            return None if self.alive else 0

        def terminate(self):
            self.alive = False
            self.returncode = 0

        def kill(self):
            self.alive = False
            self.returncode = -9

    fake_process = FakeProcess()

    def fake_get(*args, **kwargs):
        state["count"] += 1
        if state["count"] == 1:
            raise requests.exceptions.ConnectionError("not ready")
        return FakeResponse()

    monkeypatch.setattr("utils.local_model_backend.requests.get", fake_get)
    monkeypatch.setattr("utils.local_model_backend.subprocess.Popen", lambda *args, **kwargs: fake_process)
    monkeypatch.setattr("utils.local_model_backend.time.sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("utils.local_model_backend.os.killpg", lambda _pid, _sig: fake_process.terminate())
    monkeypatch.setattr("utils.local_model_backend.os.kill", lambda _pid, _sig: None)

    ensure_local_backend_ready(backend, prefix="QWEN_MINI", healthcheck_timeout=0.01)

    assert stop_local_backend_if_owned(backend, prefix="QWEN_MINI") is True
    assert fake_process.alive is False
    assert stop_local_backend_if_owned(backend, prefix="QWEN_MINI") is False


def test_set_local_backend_idle_if_owned_suspends_autostarted_mlxlm(monkeypatch, tmp_path):
    monkeypatch.setenv("QWEN_MINI_LOCAL_PROVIDER", "mlxlm")
    monkeypatch.setenv("QWEN_MINI_MLXLM_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("QWEN_MINI_MLXLM_API_BASE", "http://127.0.0.1:8094/v1")
    monkeypatch.setenv("QWEN_MINI_MLXLM_IDLE_POLICY", "suspend")

    backend = resolve_qwen_local_backend(prefix="QWEN_MINI")
    state = {"count": 0, "signals": []}

    class FakeResponse:
        def raise_for_status(self):
            return None

    class FakeProcess:
        pid = 4243

        def __init__(self):
            self.alive = True
            self.returncode = None

        def poll(self):
            return None if self.alive else 0

    fake_process = FakeProcess()

    def fake_get(*args, **kwargs):
        state["count"] += 1
        if state["count"] == 1:
            raise requests.exceptions.ConnectionError("not ready")
        return FakeResponse()

    def fake_killpg(_pid, sig):
        state["signals"].append(sig)

    monkeypatch.setattr("utils.local_model_backend.requests.get", fake_get)
    monkeypatch.setattr("utils.local_model_backend.subprocess.Popen", lambda *args, **kwargs: fake_process)
    monkeypatch.setattr("utils.local_model_backend.time.sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("utils.local_model_backend.os.killpg", fake_killpg)
    monkeypatch.setattr("utils.local_model_backend.os.kill", lambda _pid, _sig: None)
    monkeypatch.setattr("utils.local_model_backend._discover_mlxlm_server_process", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "utils.local_model_backend.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout="", returncode=0),
    )

    ensure_local_backend_ready(backend, prefix="QWEN_MINI", healthcheck_timeout=0.01)

    assert set_local_backend_idle_if_owned(backend, prefix="QWEN_MINI") is True
    assert signal.SIGSTOP in state["signals"]


def test_default_mlxlm_idle_policy_stops_on_darwin(monkeypatch):
    monkeypatch.setattr("utils.local_model_backend.sys.platform", "darwin")

    assert _default_mlxlm_idle_policy() == "stop"


def test_set_local_backend_idle_if_owned_stops_by_default(monkeypatch):
    monkeypatch.setenv("QWEN_MINI_LOCAL_PROVIDER", "mlxlm")
    monkeypatch.delenv("QWEN_MINI_MLXLM_IDLE_POLICY", raising=False)
    monkeypatch.delenv("QWEN_MLXLM_IDLE_POLICY", raising=False)

    backend = resolve_qwen_local_backend(prefix="QWEN_MINI")
    stop_calls: list[tuple[str, float]] = []

    def fake_stop(config, *, prefix, wait_timeout_sec=15.0):
        stop_calls.append((prefix, wait_timeout_sec))
        return True

    monkeypatch.setattr("utils.local_model_backend.stop_local_backend_if_owned", fake_stop)

    assert set_local_backend_idle_if_owned(backend, prefix="QWEN_MINI") is True
    assert stop_calls == [("QWEN_MINI", 15.0)]


def test_describe_local_backend_runtime_reports_alive_process(monkeypatch):
    monkeypatch.setenv("QWEN_MINI_LOCAL_PROVIDER", "mlxlm")
    monkeypatch.setenv("QWEN_MINI_MLXLM_API_BASE", "http://127.0.0.1:8095/v1")

    backend = resolve_qwen_local_backend(prefix="QWEN_MINI")
    owned = OwnedBackendProcess(
        pid=5151,
        log_path=Path("/tmp/qwen_mlxlm_8095.log"),
        state="running",
        started_at=123.0,
        model_name=backend.model_name,
        provider=backend.provider,
        api_base=backend.api_base,
        port=8095,
        origin="autostart",
    )
    monkeypatch.setattr("utils.local_model_backend._refresh_owned_backend", lambda *args, **kwargs: owned)
    monkeypatch.setattr(
        "utils.local_model_backend.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout=" 4096 S 01:23\n", returncode=0),
    )
    monkeypatch.setattr("utils.local_model_backend._process_exists", lambda pid: pid == 5151)

    snapshot = describe_local_backend_runtime(backend, prefix="QWEN_MINI")

    assert snapshot["pid"] == 5151
    assert snapshot["alive"] is True
    assert snapshot["rss_kb"] == 4096
    assert snapshot["origin"] == "autostart"
    assert snapshot["started_at"] == 123.0


def test_describe_local_backend_runtime_handles_missing_process(monkeypatch):
    monkeypatch.setenv("QWEN_MINI_LOCAL_PROVIDER", "mlxlm")
    monkeypatch.setenv("QWEN_MINI_MLXLM_API_BASE", "http://127.0.0.1:8096/v1")

    backend = resolve_qwen_local_backend(prefix="QWEN_MINI")
    monkeypatch.setattr("utils.local_model_backend._refresh_owned_backend", lambda *args, **kwargs: None)

    snapshot = describe_local_backend_runtime(backend, prefix="QWEN_MINI")

    assert snapshot["pid"] == 0
    assert snapshot["alive"] is False
    assert snapshot["owned"] is False
