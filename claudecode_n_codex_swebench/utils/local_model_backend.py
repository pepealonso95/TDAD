"""Helpers for configuring local Qwen backends.

Defaults to llama.cpp via an OpenAI-compatible endpoint while preserving
explicit legacy Ollama overrides. MLX-LM is supported as a dedicated
OpenAI-compatible runtime with optional local server autostart.
"""

from __future__ import annotations

import os
import signal
import json
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlparse

import requests


DEFAULT_LLAMACPP_API_BASE = "http://127.0.0.1:8081/v1"
DEFAULT_OLLAMA_API_BASE = "http://127.0.0.1:11434"
DEFAULT_MLXLM_API_BASE = "http://127.0.0.1:8091/v1"
DEFAULT_MLXLM_MODEL = "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2"
DEFAULT_LLAMACPP_HF_REPO = "lmstudio-community/Qwen3-Coder-30B-A3B-Instruct-GGUF"
DEFAULT_LLAMACPP_HF_FILE = "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf"

MLXLM_MODEL_ALIASES = {
    "qwen-mini": DEFAULT_MLXLM_MODEL,
    "qwen-mini-30b": DEFAULT_MLXLM_MODEL,
    "qwen3-mini": DEFAULT_MLXLM_MODEL,
    "qwen3-coder:30b": DEFAULT_MLXLM_MODEL,
}


@dataclass
class OwnedBackendProcess:
    pid: int
    log_path: Path
    process: Optional[subprocess.Popen] = None
    state: str = "running"
    started_at: float = 0.0
    model_name: str = ""
    provider: str = ""
    api_base: str = ""
    port: int = 0
    origin: str = "unknown"


_OWNED_BACKEND_PROCESSES: dict[str, OwnedBackendProcess] = {}


def _first_non_empty(values: Iterable[Optional[str]]) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _default_mlxlm_idle_policy() -> str:
    # Suspending MLX-LM on macOS keeps the Python server resident and can pin
    # large allocations in memory even after a benchmark finishes. Default to a
    # real stop; callers can still opt into suspension explicitly via env.
    return "stop"


def _default_llamacpp_hf_repo(model_name: str) -> str:
    if str(model_name or "").strip().lower() == "qwen3-coder:30b":
        return DEFAULT_LLAMACPP_HF_REPO
    return ""


def _default_llamacpp_hf_file(model_name: str) -> str:
    if str(model_name or "").strip().lower() == "qwen3-coder:30b":
        return DEFAULT_LLAMACPP_HF_FILE
    return ""


def normalize_local_provider(raw_value: Optional[str]) -> str:
    value = str(raw_value or "").strip().lower()
    if not value:
        return "llamacpp"
    if value in {"llamacpp", "llama.cpp", "llama-cpp", "llama_cpp", "openai", "openai_compat"}:
        return "llamacpp"
    if value in {"ollama", "ollama_chat"}:
        return "ollama"
    if value in {"mlxlm", "mlx-lm", "mlx_lm", "mlx"}:
        return "mlxlm"
    raise ValueError(f"Unsupported local Qwen provider: {raw_value}")


def _normalize_openai_api_base(raw_value: Optional[str]) -> str:
    base = str(raw_value or DEFAULT_LLAMACPP_API_BASE).strip().rstrip("/")
    if not base:
        base = DEFAULT_LLAMACPP_API_BASE
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    return base


def _normalize_ollama_api_base(raw_value: Optional[str]) -> str:
    base = str(raw_value or DEFAULT_OLLAMA_API_BASE).strip().rstrip("/")
    return base or DEFAULT_OLLAMA_API_BASE


def _normalize_mlxlm_api_base(raw_value: Optional[str]) -> str:
    return _normalize_openai_api_base(raw_value or DEFAULT_MLXLM_API_BASE)


def _normalize_mlxlm_model_name(raw_value: Optional[str]) -> str:
    value = str(raw_value or "").strip()
    if not value:
        return DEFAULT_MLXLM_MODEL
    return MLXLM_MODEL_ALIASES.get(value.lower(), value)


@dataclass(frozen=True)
class LocalModelBackendConfig:
    env_prefix: str
    provider: str
    provider_label: str
    model_name: str
    litellm_model_name: str
    api_base: str
    api_key: str

    @property
    def healthcheck_url(self) -> str:
        if self.provider == "ollama":
            return f"{self.api_base}/api/tags"
        return f"{self.api_base}/models"

    @property
    def chat_completions_url(self) -> str:
        return f"{self.api_base}/chat/completions"

    @property
    def ollama_generate_url(self) -> str:
        return f"{self.api_base}/api/generate"

    @property
    def ollama_chat_url(self) -> str:
        return f"{self.api_base}/api/chat"

    def build_litellm_kwargs(
        self,
        *,
        temperature: float,
        max_tokens: int,
        timeout: int,
        num_ctx: Optional[int] = None,
    ) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "api_base": self.api_base,
            "drop_params": True,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": timeout,
        }
        if self.provider == "ollama":
            if num_ctx is not None:
                kwargs["num_ctx"] = num_ctx
        else:
            kwargs["api_key"] = self.api_key
            kwargs["custom_llm_provider"] = "openai"
        if self.provider == "mlxlm":
            thinking_enabled = _first_non_empty(
                [
                    os.getenv(f"{self.env_prefix}_MLXLM_ENABLE_THINKING"),
                    os.getenv("QWEN_MLXLM_ENABLE_THINKING"),
                    "on",
                ]
            ).strip().lower() in {"1", "true", "on", "yes"}
            if thinking_enabled:
                kwargs["extra_body"] = {
                    "chat_template_kwargs": {
                        "enable_thinking": True,
                    }
                }
        return kwargs

    def build_request_headers(self) -> dict[str, str]:
        if self.provider in {"llamacpp", "mlxlm"} and self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        return {}


def _owned_backend_key(config: LocalModelBackendConfig, *, prefix: str) -> str:
    normalized_prefix = str(prefix or config.env_prefix or "QWEN").strip().upper()
    return "|".join(
        [
            normalized_prefix,
            config.provider,
            config.api_base.rstrip("/"),
            config.model_name,
        ]
    )


def _owned_backend_registry_dir() -> Path:
    path = Path(tempfile.gettempdir()) / "qwen_mlxlm_registry"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _owned_backend_record_path(config: LocalModelBackendConfig, *, prefix: str) -> Path:
    api = urlparse(config.api_base)
    host = api.hostname or "127.0.0.1"
    port = api.port or 80
    filename = f"{str(prefix or config.env_prefix).strip().lower()}_{host}_{port}.json".replace("/", "_")
    return _owned_backend_registry_dir() / filename


def _backend_port_from_config(config: LocalModelBackendConfig) -> int:
    api = urlparse(config.api_base)
    if api.port is not None:
        return int(api.port)
    if api.scheme == "https":
        return 443
    return 80


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_state(pid: int) -> str:
    if pid <= 0:
        return ""
    try:
        result = subprocess.run(
            ["ps", "-o", "state=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return ""
    return str(result.stdout or "").strip()


def _process_is_stopped(pid: int) -> bool:
    return "T" in _process_state(pid)


def _load_owned_backend_record(
    config: LocalModelBackendConfig,
    *,
    prefix: str,
) -> Optional[OwnedBackendProcess]:
    path = _owned_backend_record_path(config, prefix=prefix)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    pid = int(payload.get("pid") or 0)
    if not _process_exists(pid):
        try:
            path.unlink()
        except OSError:
            pass
        return None
    state = str(payload.get("state") or "running")
    if state == "suspended" and not _process_is_stopped(pid):
        state = "running"
    log_path_raw = str(payload.get("log_path") or "")
    log_path = Path(log_path_raw) if log_path_raw else Path(tempfile.gettempdir()) / "qwen_mlxlm_unknown.log"
    return OwnedBackendProcess(
        pid=pid,
        log_path=log_path,
        process=None,
        state=state,
        started_at=float(payload.get("started_at") or 0.0),
        model_name=str(payload.get("model_name") or config.model_name),
        provider=str(payload.get("provider") or config.provider),
        api_base=str(payload.get("api_base") or config.api_base),
        port=int(payload.get("port") or _backend_port_from_config(config)),
        origin=str(payload.get("origin") or "record"),
    )


def _save_owned_backend_record(
    config: LocalModelBackendConfig,
    *,
    prefix: str,
    owned: OwnedBackendProcess,
) -> None:
    path = _owned_backend_record_path(config, prefix=prefix)
    payload = {
        "pid": int(owned.pid),
        "log_path": str(owned.log_path),
        "state": owned.state,
        "started_at": float(owned.started_at or 0.0),
        "api_base": config.api_base,
        "model_name": config.model_name,
        "provider": config.provider,
        "port": int(owned.port or _backend_port_from_config(config)),
        "origin": str(owned.origin or "unknown"),
        "prefix": str(prefix or config.env_prefix).strip().upper(),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _clear_owned_backend_record(config: LocalModelBackendConfig, *, prefix: str) -> None:
    path = _owned_backend_record_path(config, prefix=prefix)
    try:
        path.unlink()
    except OSError:
        pass


def _register_owned_backend(
    config: LocalModelBackendConfig,
    *,
    prefix: str,
    owned: OwnedBackendProcess,
) -> OwnedBackendProcess:
    if not owned.model_name:
        owned.model_name = config.model_name
    if not owned.provider:
        owned.provider = config.provider
    if not owned.api_base:
        owned.api_base = config.api_base
    if not int(owned.port or 0):
        owned.port = _backend_port_from_config(config)
    if not float(owned.started_at or 0.0):
        owned.started_at = time.time()
    key = _owned_backend_key(config, prefix=prefix)
    _OWNED_BACKEND_PROCESSES[key] = owned
    _save_owned_backend_record(config, prefix=prefix, owned=owned)
    return owned


def _refresh_owned_backend(
    config: LocalModelBackendConfig,
    *,
    prefix: str,
) -> Optional[OwnedBackendProcess]:
    key = _owned_backend_key(config, prefix=prefix)
    owned = _OWNED_BACKEND_PROCESSES.get(key)
    if owned is not None and _process_exists(int(owned.pid)):
        return owned
    if owned is not None:
        _OWNED_BACKEND_PROCESSES.pop(key, None)
    owned = _load_owned_backend_record(config, prefix=prefix)
    if owned is not None:
        _OWNED_BACKEND_PROCESSES[key] = owned
        return owned
    discovered = _discover_owned_backend_process(config, prefix=prefix)
    if discovered is not None:
        return _register_owned_backend(config, prefix=prefix, owned=discovered)
    return None


def _discover_owned_backend_process(
    config: LocalModelBackendConfig,
    *,
    prefix: str,
) -> Optional[OwnedBackendProcess]:
    if config.provider == "mlxlm":
        return _discover_mlxlm_server_process(config, prefix=prefix)
    if config.provider == "llamacpp":
        return _discover_llamacpp_server_process(config, prefix=prefix)
    return None


def _discover_mlxlm_server_process(
    config: LocalModelBackendConfig,
    *,
    prefix: str,
) -> Optional[OwnedBackendProcess]:
    if config.provider != "mlxlm":
        return None
    try:
        api = urlparse(config.api_base)
        port = str(api.port or 80)
        result = subprocess.run(
            ["pgrep", "-fal", "mlx_lm server"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return None
    for line in (result.stdout or "").splitlines():
        text = str(line or "").strip()
        if not text:
            continue
        parts = text.split(None, 1)
        if len(parts) != 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        command = parts[1]
        if f"--port {port}" not in command:
            continue
        if config.model_name not in command:
            continue
        return OwnedBackendProcess(
            pid=pid,
            log_path=Path(tempfile.gettempdir()) / f"{str(prefix).lower()}_mlxlm_{port}.log",
            process=None,
            state="running",
            started_at=0.0,
            model_name=config.model_name,
            provider=config.provider,
            api_base=config.api_base,
            port=int(port),
            origin="discovered",
        )
    return None


def _discover_llamacpp_server_process(
    config: LocalModelBackendConfig,
    *,
    prefix: str,
) -> Optional[OwnedBackendProcess]:
    if config.provider != "llamacpp":
        return None
    try:
        api = urlparse(config.api_base)
        port = str(api.port or 80)
        result = subprocess.run(
            ["pgrep", "-fal", "llama-server"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return None
    for line in (result.stdout or "").splitlines():
        text = str(line or "").strip()
        if not text:
            continue
        parts = text.split(None, 1)
        if len(parts) != 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        command = parts[1]
        if f"--port {port}" not in command:
            continue
        if f"--alias {config.model_name}" not in command and config.model_name not in command:
            continue
        return OwnedBackendProcess(
            pid=pid,
            log_path=Path(tempfile.gettempdir()) / f"{str(prefix).lower()}_llamacpp_{port}.log",
            process=None,
            state="running",
            started_at=0.0,
            model_name=config.model_name,
            provider=config.provider,
            api_base=config.api_base,
            port=int(port),
            origin="discovered",
        )
    return None


def _collect_process_snapshot(pid: int) -> dict[str, object]:
    snapshot: dict[str, object] = {
        "pid": int(pid or 0),
        "alive": False,
        "state": "",
        "stopped": False,
        "rss_kb": None,
        "elapsed": "",
    }
    if pid <= 0:
        return snapshot
    snapshot["alive"] = _process_exists(pid)
    if not bool(snapshot["alive"]):
        return snapshot
    try:
        result = subprocess.run(
            ["ps", "-o", "rss=,state=,etime=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        )
        line = str(result.stdout or "").strip().splitlines()
        if line:
            parts = line[0].split()
            if len(parts) >= 1:
                try:
                    snapshot["rss_kb"] = int(parts[0])
                except ValueError:
                    snapshot["rss_kb"] = None
            if len(parts) >= 2:
                snapshot["state"] = parts[1]
                snapshot["stopped"] = "T" in str(parts[1])
            if len(parts) >= 3:
                snapshot["elapsed"] = parts[2]
    except Exception:
        return snapshot
    return snapshot


def describe_local_backend_runtime(
    config: LocalModelBackendConfig,
    *,
    prefix: str,
) -> dict[str, object]:
    """Return a best-effort runtime snapshot for the configured local backend."""
    prefix = str(prefix or config.env_prefix or "QWEN").strip().upper()
    owned = _refresh_owned_backend(config, prefix=prefix) if config.provider in {"mlxlm", "llamacpp"} else None
    snapshot = (
        _collect_process_snapshot(int(owned.pid))
        if owned is not None
        else {
            "pid": 0,
            "alive": False,
            "state": "",
            "stopped": False,
            "rss_kb": None,
            "elapsed": "",
        }
    )
    return {
        "provider": config.provider,
        "provider_label": config.provider_label,
        "api_base": config.api_base,
        "healthcheck_url": config.healthcheck_url,
        "model_name": config.model_name,
        "owned": owned is not None,
        "pid": int(snapshot.get("pid") or 0),
        "alive": bool(snapshot.get("alive")),
        "state": str(snapshot.get("state") or (owned.state if owned is not None else "")),
        "stopped": bool(snapshot.get("stopped")),
        "rss_kb": snapshot.get("rss_kb"),
        "elapsed": str(snapshot.get("elapsed") or ""),
        "log_path": str(owned.log_path) if owned is not None else "",
        "started_at": float(owned.started_at or 0.0) if owned is not None else 0.0,
        "origin": str(owned.origin or "unknown") if owned is not None else "none",
        "port": int(owned.port or _backend_port_from_config(config)) if owned is not None else _backend_port_from_config(config),
    }


def _send_process_group_signal(pid: int, sig: int) -> None:
    if hasattr(os, "killpg"):
        os.killpg(pid, sig)
    else:
        os.kill(pid, sig)


def _mark_backend_state(
    config: LocalModelBackendConfig,
    *,
    prefix: str,
    owned: OwnedBackendProcess,
    state: str,
) -> None:
    owned.state = state
    _register_owned_backend(config, prefix=prefix, owned=owned)


def _best_effort_demote_macos_process(pid: int) -> None:
    if sys.platform != "darwin" or pid <= 0:
        return
    for cmd in (
        ["renice", "20", "-p", str(pid)],
        ["taskpolicy", "-b", "-p", str(pid)],
    ):
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=False)
        except Exception:
            continue


def set_local_backend_idle_if_owned(
    config: LocalModelBackendConfig,
    *,
    prefix: str,
    wait_timeout_sec: float = 15.0,
) -> bool:
    if config.provider == "llamacpp":
        return stop_local_backend_if_owned(config, prefix=prefix, wait_timeout_sec=wait_timeout_sec)
    if config.provider != "mlxlm":
        return False

    policy = _first_non_empty(
        [
            os.getenv(f"{str(prefix or config.env_prefix).strip().upper()}_MLXLM_IDLE_POLICY"),
            os.getenv("QWEN_MLXLM_IDLE_POLICY"),
            _default_mlxlm_idle_policy(),
        ]
    ).strip().lower()
    if policy not in {"stop", "suspend"}:
        policy = _default_mlxlm_idle_policy()
    if policy == "stop":
        return stop_local_backend_if_owned(config, prefix=prefix, wait_timeout_sec=wait_timeout_sec)

    owned = _refresh_owned_backend(config, prefix=prefix)
    if owned is None or not _process_exists(int(owned.pid)):
        return False
    if owned.state == "suspended" and _process_is_stopped(int(owned.pid)):
        return True
    try:
        _send_process_group_signal(int(owned.pid), signal.SIGSTOP)
    except ProcessLookupError:
        _clear_owned_backend_record(config, prefix=prefix)
        return False
    _best_effort_demote_macos_process(int(owned.pid))
    _mark_backend_state(config, prefix=prefix, owned=owned, state="suspended")
    return True


def stop_local_backend_if_owned(
    config: LocalModelBackendConfig,
    *,
    prefix: str,
    wait_timeout_sec: float = 15.0,
) -> bool:
    """Stop an autostarted backend process if this process owns it."""
    if config.provider not in {"mlxlm", "llamacpp"}:
        return False

    key = _owned_backend_key(config, prefix=prefix)
    owned = _refresh_owned_backend(config, prefix=prefix)
    if owned is None:
        return False
    _OWNED_BACKEND_PROCESSES.pop(key, None)

    process = owned.process
    if not _process_exists(int(owned.pid)):
        _clear_owned_backend_record(config, prefix=prefix)
        return True
    if owned.state == "suspended":
        try:
            _send_process_group_signal(int(owned.pid), signal.SIGCONT)
        except Exception:
            pass

    try:
        if process is not None:
            if hasattr(os, "killpg"):
                os.killpg(int(owned.pid), signal.SIGTERM)
            else:
                process.terminate()
        else:
            _send_process_group_signal(int(owned.pid), signal.SIGTERM)
    except ProcessLookupError:
        _clear_owned_backend_record(config, prefix=prefix)
        return True
    except Exception:
        if process is not None:
            process.terminate()
        else:
            try:
                os.kill(int(owned.pid), signal.SIGTERM)
            except Exception:
                pass

    deadline = time.time() + max(1.0, float(wait_timeout_sec))
    while time.time() < deadline:
        if not _process_exists(int(owned.pid)) or (process is not None and process.poll() is not None):
            _clear_owned_backend_record(config, prefix=prefix)
            return True
        time.sleep(0.2)

    try:
        if process is not None:
            if hasattr(os, "killpg"):
                os.killpg(int(owned.pid), signal.SIGKILL)
            else:
                process.kill()
        else:
            _send_process_group_signal(int(owned.pid), signal.SIGKILL)
    except ProcessLookupError:
        _clear_owned_backend_record(config, prefix=prefix)
        return True
    except Exception:
        if process is not None:
            process.kill()
        else:
            try:
                os.kill(int(owned.pid), signal.SIGKILL)
            except Exception:
                pass

    _clear_owned_backend_record(config, prefix=prefix)
    return True


def _healthcheck_local_backend(
    config: LocalModelBackendConfig,
    *,
    timeout: float,
) -> None:
    response = requests.get(
        config.healthcheck_url,
        headers=config.build_request_headers(),
        timeout=timeout,
    )
    response.raise_for_status()


def _ensure_llamacpp_backend_ready(
    config: LocalModelBackendConfig,
    *,
    prefix: str,
    healthcheck_timeout: float,
) -> dict[str, object]:
    prefix = str(prefix or "QWEN").strip().upper()
    owned = _refresh_owned_backend(config, prefix=prefix)
    started_now = False
    reused_existing = owned is not None

    try:
        _healthcheck_local_backend(config, timeout=healthcheck_timeout)
        if owned is not None:
            _register_owned_backend(config, prefix=prefix, owned=owned)
        return {
            "provider": config.provider,
            "ready": True,
            "started_now": started_now,
            "reused_existing": reused_existing,
            "snapshot": describe_local_backend_runtime(config, prefix=prefix),
        }
    except Exception as exc:
        last_error = exc

    autostart = _first_non_empty(
        [
            os.getenv(f"{prefix}_LLAMACPP_AUTOSTART"),
            os.getenv("QWEN_LLAMACPP_AUTOSTART"),
            "on",
        ]
    ).strip().lower() in {"1", "true", "on", "yes"}
    if not autostart:
        raise RuntimeError(
            f"llama.cpp server is not reachable at {config.api_base} and autostart is disabled. "
            f"Last error: {last_error}"
        ) from last_error

    try:
        startup_timeout_sec = max(
            60,
            int(
                _first_non_empty(
                    [
                        os.getenv(f"{prefix}_LLAMACPP_STARTUP_TIMEOUT_SEC"),
                        os.getenv("QWEN_LLAMACPP_STARTUP_TIMEOUT_SEC"),
                        "3600",
                    ]
                )
            ),
        )
    except ValueError:
        startup_timeout_sec = 3600

    api = urlparse(config.api_base)
    host = api.hostname or "127.0.0.1"
    if api.port is not None:
        port = api.port
    elif api.scheme == "https":
        port = 443
    else:
        port = 80

    log_dir = Path(
        _first_non_empty(
            [
                os.getenv(f"{prefix}_LLAMACPP_LOG_DIR"),
                os.getenv("QWEN_LLAMACPP_LOG_DIR"),
                str(Path(tempfile.gettempdir()) / "qwen_llamacpp_logs"),
            ]
        )
    )
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{prefix.lower()}_llamacpp_{port}.log"

    key = _owned_backend_key(config, prefix=prefix)
    owned = _refresh_owned_backend(config, prefix=prefix)
    if owned is not None and not _process_exists(int(owned.pid)):
        _OWNED_BACKEND_PROCESSES.pop(key, None)
        _clear_owned_backend_record(config, prefix=prefix)
        owned = None

    if owned is None:
        server_bin = _first_non_empty(
            [
                os.getenv(f"{prefix}_LLAMACPP_SERVER_BIN"),
                os.getenv("QWEN_LLAMACPP_SERVER_BIN"),
                shutil.which("llama-server"),
                "/opt/homebrew/bin/llama-server",
            ]
        )
        if not server_bin or not Path(server_bin).exists():
            raise RuntimeError(
                "llama.cpp autostart requested, but `llama-server` was not found. "
                "Install llama.cpp or set QWEN_MINI_LLAMACPP_SERVER_BIN."
            ) from last_error

        model_file = _first_non_empty(
            [
                os.getenv(f"{prefix}_LLAMACPP_MODEL_FILE"),
                os.getenv("QWEN_LLAMACPP_MODEL_FILE"),
            ]
        )
        hf_repo = _first_non_empty(
            [
                os.getenv(f"{prefix}_LLAMACPP_HF_REPO"),
                os.getenv("QWEN_LLAMACPP_HF_REPO"),
                _default_llamacpp_hf_repo(config.model_name),
            ]
        )
        hf_file = _first_non_empty(
            [
                os.getenv(f"{prefix}_LLAMACPP_HF_FILE"),
                os.getenv("QWEN_LLAMACPP_HF_FILE"),
                _default_llamacpp_hf_file(config.model_name),
            ]
        )
        if model_file:
            model_path = Path(model_file).expanduser()
            if not model_path.exists():
                raise RuntimeError(
                    f"Configured llama.cpp model file does not exist: {model_path}"
                ) from last_error
            model_file = str(model_path)
        elif not hf_repo:
            raise RuntimeError(
                "llama.cpp autostart requires either a local GGUF file "
                "(QWEN_MINI_LLAMACPP_MODEL_FILE) or an HF repo "
                "(QWEN_MINI_LLAMACPP_HF_REPO / QWEN_LLAMACPP_HF_REPO)."
            ) from last_error

        ctx_size = _first_non_empty(
            [
                os.getenv(f"{prefix}_LLAMACPP_CTX_SIZE"),
                os.getenv("QWEN_LLAMACPP_CTX_SIZE"),
                "16384",
            ]
        )
        parallel = _first_non_empty(
            [
                os.getenv(f"{prefix}_LLAMACPP_PARALLEL"),
                os.getenv("QWEN_LLAMACPP_PARALLEL"),
                "1",
            ]
        )
        timeout_sec = _first_non_empty(
            [
                os.getenv(f"{prefix}_LLAMACPP_TIMEOUT_SEC"),
                os.getenv("QWEN_LLAMACPP_TIMEOUT_SEC"),
                "600",
            ]
        )
        gpu_layers = _first_non_empty(
            [
                os.getenv(f"{prefix}_LLAMACPP_GPU_LAYERS"),
                os.getenv("QWEN_LLAMACPP_GPU_LAYERS"),
                "auto",
            ]
        )

        command = [
            server_bin,
            "--host",
            host,
            "--port",
            str(port),
            "--api-prefix",
            "/v1",
            "--alias",
            config.model_name,
            "--ctx-size",
            str(ctx_size),
            "--parallel",
            str(parallel),
            "--timeout",
            str(timeout_sec),
            "--gpu-layers",
            str(gpu_layers),
            "--no-webui",
        ]
        if config.api_key:
            command.extend(["--api-key", config.api_key])
        if model_file:
            command.extend(["--model", model_file])
        else:
            command.extend(["--hf-repo", hf_repo])
            if hf_file:
                command.extend(["--hf-file", hf_file])

        with log_path.open("a", encoding="utf-8") as log_handle:
            process = subprocess.Popen(
                command,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=os.environ.copy(),
            )
        owned = _register_owned_backend(
            config,
            prefix=prefix,
            owned=OwnedBackendProcess(
                pid=int(process.pid),
                process=process,
                log_path=log_path,
                started_at=time.time(),
                model_name=config.model_name,
                provider=config.provider,
                api_base=config.api_base,
                port=port,
                origin="autostart",
            ),
        )
        started_now = True
        reused_existing = False

    process = owned.process
    deadline = time.time() + startup_timeout_sec
    while time.time() < deadline:
        if process is not None and process.poll() is not None:
            log_tail = ""
            if log_path.exists():
                log_tail = log_path.read_text(encoding="utf-8", errors="ignore")[-2000:]
            raise RuntimeError(
                f"llama.cpp server exited during startup (code {process.returncode}) for "
                f"{config.model_name}. Log: {log_path}\n{log_tail}"
            )
        try:
            _healthcheck_local_backend(config, timeout=healthcheck_timeout)
            _mark_backend_state(config, prefix=prefix, owned=owned, state="running")
            return {
                "provider": config.provider,
                "ready": True,
                "started_now": started_now,
                "reused_existing": reused_existing,
                "snapshot": describe_local_backend_runtime(config, prefix=prefix),
            }
        except Exception as exc:
            last_error = exc
            time.sleep(2)

    _OWNED_BACKEND_PROCESSES.pop(key, None)
    _clear_owned_backend_record(config, prefix=prefix)
    raise RuntimeError(
        f"llama.cpp server did not become ready at {config.healthcheck_url} within "
        f"{startup_timeout_sec}s. Log: {log_path}. Last error: {last_error}"
    )


def ensure_local_backend_ready(
    config: LocalModelBackendConfig,
    *,
    prefix: str,
    healthcheck_timeout: float = 5.0,
) -> dict[str, object]:
    """Ensure the configured local backend is reachable.

    For MLX-LM, the helper can auto-start `python -m mlx_lm server` against the
    configured model if the endpoint is not already serving requests.
    """
    if config.provider == "llamacpp":
        return _ensure_llamacpp_backend_ready(
            config,
            prefix=prefix,
            healthcheck_timeout=healthcheck_timeout,
        )
    if config.provider != "mlxlm":
        return {
            "provider": config.provider,
            "ready": True,
            "started_now": False,
            "reused_existing": False,
            "snapshot": describe_local_backend_runtime(config, prefix=prefix),
        }

    prefix = str(prefix or "QWEN").strip().upper()
    owned = _refresh_owned_backend(config, prefix=prefix)
    started_now = False
    reused_existing = owned is not None
    if owned is not None and owned.state == "suspended":
        try:
            _send_process_group_signal(int(owned.pid), signal.SIGCONT)
            _mark_backend_state(config, prefix=prefix, owned=owned, state="running")
            time.sleep(0.5)
        except Exception:
            _clear_owned_backend_record(config, prefix=prefix)
            _OWNED_BACKEND_PROCESSES.pop(_owned_backend_key(config, prefix=prefix), None)

    try:
        response = requests.get(
            config.healthcheck_url,
            headers=config.build_request_headers(),
            timeout=healthcheck_timeout,
        )
        response.raise_for_status()
        if owned is not None:
            _register_owned_backend(config, prefix=prefix, owned=owned)
        return {
            "provider": config.provider,
            "ready": True,
            "started_now": started_now,
            "reused_existing": reused_existing,
            "snapshot": describe_local_backend_runtime(config, prefix=prefix),
        }
    except Exception as exc:
        last_error = exc

    key = _owned_backend_key(config, prefix=prefix)
    autostart = _first_non_empty(
        [
            os.getenv(f"{prefix}_MLXLM_AUTOSTART"),
            os.getenv("QWEN_MLXLM_AUTOSTART"),
            "on",
        ]
    ).strip().lower() in {"1", "true", "on", "yes"}
    if not autostart:
        raise RuntimeError(
            f"MLX-LM server is not reachable at {config.api_base} and autostart is disabled. "
            f"Last error: {last_error}"
        ) from last_error

    try:
        startup_timeout_sec = max(
            30,
            int(
                _first_non_empty(
                    [
                        os.getenv(f"{prefix}_MLXLM_STARTUP_TIMEOUT_SEC"),
                        os.getenv("QWEN_MLXLM_STARTUP_TIMEOUT_SEC"),
                        "900",
                    ]
                )
            ),
        )
    except ValueError:
        startup_timeout_sec = 900

    api = urlparse(config.api_base)
    host = api.hostname or "127.0.0.1"
    if api.port is not None:
        port = api.port
    elif api.scheme == "https":
        port = 443
    else:
        port = 80

    log_dir = Path(
        _first_non_empty(
            [
                os.getenv(f"{prefix}_MLXLM_LOG_DIR"),
                os.getenv("QWEN_MLXLM_LOG_DIR"),
                str(Path(tempfile.gettempdir()) / "qwen_mlxlm_logs"),
            ]
        )
    )
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{prefix.lower()}_mlxlm_{port}.log"

    owned = _refresh_owned_backend(config, prefix=prefix)
    if owned is not None and not _process_exists(int(owned.pid)):
        _OWNED_BACKEND_PROCESSES.pop(key, None)
        _clear_owned_backend_record(config, prefix=prefix)
        owned = None

    if owned is None:
        command = [
            sys.executable,
            "-m",
            "mlx_lm",
            "server",
            "--model",
            config.model_name,
            "--host",
            host,
            "--port",
            str(port),
            "--temp",
            "0.0",
        ]
        trust_remote_code = _first_non_empty(
            [
                os.getenv(f"{prefix}_MLXLM_TRUST_REMOTE_CODE"),
                os.getenv("QWEN_MLXLM_TRUST_REMOTE_CODE"),
            ]
        ).strip().lower() in {"1", "true", "on", "yes"}
        if trust_remote_code:
            command.append("--trust-remote-code")

        chat_template_args = _first_non_empty(
            [
                os.getenv(f"{prefix}_MLXLM_CHAT_TEMPLATE_ARGS"),
                os.getenv("QWEN_MLXLM_CHAT_TEMPLATE_ARGS"),
            ]
        )
        if chat_template_args:
            command.extend(["--chat-template-args", chat_template_args])

        with log_path.open("a", encoding="utf-8") as log_handle:
            process = subprocess.Popen(
                command,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=os.environ.copy(),
            )
        owned = _register_owned_backend(
            config,
            prefix=prefix,
            owned=OwnedBackendProcess(
                pid=int(process.pid),
                process=process,
                log_path=log_path,
                started_at=time.time(),
                model_name=config.model_name,
                provider=config.provider,
                api_base=config.api_base,
                port=port,
                origin="autostart",
            ),
        )
        started_now = True
        reused_existing = False

    process = owned.process
    log_path = owned.log_path

    deadline = time.time() + startup_timeout_sec
    while time.time() < deadline:
        if process is not None and process.poll() is not None:
            log_tail = ""
            if log_path.exists():
                log_tail = log_path.read_text(encoding="utf-8", errors="ignore")[-2000:]
            raise RuntimeError(
                f"MLX-LM server exited during startup (code {process.returncode}) for "
                f"{config.model_name}. Log: {log_path}\n{log_tail}"
            )
        try:
            response = requests.get(
                config.healthcheck_url,
                headers=config.build_request_headers(),
                timeout=healthcheck_timeout,
            )
            response.raise_for_status()
            _mark_backend_state(config, prefix=prefix, owned=owned, state="running")
            return {
                "provider": config.provider,
                "ready": True,
                "started_now": started_now,
                "reused_existing": reused_existing,
                "snapshot": describe_local_backend_runtime(config, prefix=prefix),
            }
        except Exception as exc:
            last_error = exc
            time.sleep(2)

    _OWNED_BACKEND_PROCESSES.pop(key, None)
    _clear_owned_backend_record(config, prefix=prefix)
    raise RuntimeError(
        f"MLX-LM server did not become ready at {config.healthcheck_url} within "
        f"{startup_timeout_sec}s. Log: {log_path}. Last error: {last_error}"
    )


def resolve_qwen_local_backend(
    *,
    prefix: str,
    explicit_model: Optional[str] = None,
    default_model: str = "qwen3-coder:30b",
) -> LocalModelBackendConfig:
    prefix = str(prefix or "QWEN").strip().upper()
    provider_hint = _first_non_empty(
        [
            os.getenv(f"{prefix}_LOCAL_PROVIDER"),
            os.getenv("QWEN_LOCAL_PROVIDER"),
        ]
    )
    if not provider_hint and _first_non_empty(
        [
            os.getenv(f"{prefix}_OLLAMA_MODEL"),
            os.getenv(f"{prefix}_OLLAMA_API_BASE"),
            os.getenv(f"{prefix}_OLLAMA_API_KEY"),
        ]
    ):
        provider_hint = "ollama"
    provider = normalize_local_provider(provider_hint or "llamacpp")

    shared_model_hint = _first_non_empty(
        [
            explicit_model,
            os.getenv(f"{prefix}_LOCAL_MODEL"),
            os.getenv("QWEN_LOCAL_MODEL"),
        ]
    )

    if provider == "ollama":
        model_name = _first_non_empty(
            [
                shared_model_hint,
                os.getenv(f"{prefix}_OLLAMA_MODEL"),
                os.getenv("QWEN_OLLAMA_MODEL"),
                default_model,
            ]
        )
        api_base = _normalize_ollama_api_base(
            _first_non_empty(
                [
                    os.getenv(f"{prefix}_API_BASE"),
                    os.getenv("QWEN_LOCAL_API_BASE"),
                    os.getenv(f"{prefix}_OLLAMA_API_BASE"),
                ]
            )
        )
        api_key = _first_non_empty(
            [
                os.getenv(f"{prefix}_API_KEY"),
                os.getenv("QWEN_LOCAL_API_KEY"),
                os.getenv(f"{prefix}_OLLAMA_API_KEY"),
                "ollama",
            ]
        )
        litellm_model_name = _first_non_empty(
            [
                os.getenv(f"{prefix}_LITELLM_MODEL"),
                os.getenv("QWEN_LOCAL_LITELLM_MODEL"),
                f"ollama_chat/{model_name}",
            ]
        )
        return LocalModelBackendConfig(
            env_prefix=prefix,
            provider="ollama",
            provider_label="Ollama",
            model_name=model_name,
            litellm_model_name=litellm_model_name,
            api_base=api_base,
            api_key=api_key,
        )

    if provider == "mlxlm":
        model_name = _first_non_empty(
            [
                shared_model_hint,
                os.getenv(f"{prefix}_MLXLM_MODEL"),
                os.getenv("QWEN_MLXLM_MODEL"),
                default_model,
            ]
        )
        model_name = _normalize_mlxlm_model_name(model_name)
        api_base = _normalize_mlxlm_api_base(
            _first_non_empty(
                [
                    os.getenv(f"{prefix}_API_BASE"),
                    os.getenv("QWEN_LOCAL_API_BASE"),
                    os.getenv(f"{prefix}_MLXLM_API_BASE"),
                    os.getenv("QWEN_MLXLM_API_BASE"),
                ]
            )
        )
        api_key = _first_non_empty(
            [
                os.getenv(f"{prefix}_API_KEY"),
                os.getenv("QWEN_LOCAL_API_KEY"),
                os.getenv(f"{prefix}_MLXLM_API_KEY"),
                os.getenv("QWEN_MLXLM_API_KEY"),
                "local",
            ]
        )
        litellm_model_name = _first_non_empty(
            [
                os.getenv(f"{prefix}_LITELLM_MODEL"),
                os.getenv("QWEN_LOCAL_LITELLM_MODEL"),
                f"openai/{model_name}",
            ]
        )
        return LocalModelBackendConfig(
            env_prefix=prefix,
            provider="mlxlm",
            provider_label="MLX-LM",
            model_name=model_name,
            litellm_model_name=litellm_model_name,
            api_base=api_base,
            api_key=api_key,
        )

    model_name = _first_non_empty(
        [
            shared_model_hint,
            os.getenv(f"{prefix}_LLAMACPP_MODEL"),
            os.getenv("QWEN_LLAMACPP_MODEL"),
            default_model,
        ]
    )
    api_base = _normalize_openai_api_base(
        _first_non_empty(
            [
                os.getenv(f"{prefix}_API_BASE"),
                os.getenv("QWEN_LOCAL_API_BASE"),
                os.getenv(f"{prefix}_LLAMACPP_API_BASE"),
                os.getenv("LLAMA_CPP_API_BASE"),
            ]
        )
    )
    api_key = _first_non_empty(
        [
            os.getenv(f"{prefix}_API_KEY"),
            os.getenv("QWEN_LOCAL_API_KEY"),
            os.getenv(f"{prefix}_LLAMACPP_API_KEY"),
            os.getenv("LLAMA_CPP_API_KEY"),
            "local",
        ]
    )
    litellm_model_name = _first_non_empty(
        [
            os.getenv(f"{prefix}_LITELLM_MODEL"),
            os.getenv("QWEN_LOCAL_LITELLM_MODEL"),
            f"openai/{model_name}",
        ]
    )
    return LocalModelBackendConfig(
        env_prefix=prefix,
        provider="llamacpp",
        provider_label="llama.cpp",
        model_name=model_name,
        litellm_model_name=litellm_model_name,
        api_base=api_base,
        api_key=api_key,
    )
