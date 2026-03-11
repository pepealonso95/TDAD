#!/usr/bin/env python3
"""Per-repository runtime bootstrap for local pytest execution.

This manager provides an optional cached-venv isolation layer so local test
signals are less affected by host environment package collisions.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from typing import Any, Callable, Optional


def _bool_env(raw_value: str, default: bool) -> bool:
    value = str(raw_value or "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "on", "yes"}


class TestRuntimeManager:
    """Creates and reuses repo-scoped Python runtimes for pytest probes."""

    def __init__(
        self,
        *,
        isolation_mode: str = "off",
        cache_dir: Optional[str] = None,
        bootstrap_timeout_sec: int = 240,
        auto_editable_install: bool = True,
    ) -> None:
        mode = str(isolation_mode or "off").strip().lower()
        if mode not in {"off", "repo_cached_venv"}:
            mode = "off"
        self.isolation_mode = mode
        default_cache = Path.home() / ".cache" / "swebench_test_runtime"
        self.cache_dir = Path(cache_dir) if cache_dir else default_cache
        self.bootstrap_timeout_sec = max(30, int(bootstrap_timeout_sec or 240))
        self.bootstrap_attempt_timeout_sec = self.bootstrap_timeout_sec
        self.bootstrap_max_total_sec = max(self.bootstrap_timeout_sec, self.bootstrap_timeout_sec * 2)
        self.fallback_depth = "medium"
        self.auto_editable_install = bool(auto_editable_install)
        self._repo_slug = ""
        self._commit_sha = ""
        self._repo_runtime_cache: dict[str, dict[str, Any]] = {}

    def configure_from_env(self) -> None:
        """Refresh runtime settings from environment variables."""
        mode = str(os.getenv("TEST_RUNTIME_ISOLATION", self.isolation_mode or "off")).strip().lower()
        if mode not in {"off", "repo_cached_venv"}:
            mode = "off"
        self.isolation_mode = mode

        cache_dir = str(os.getenv("TEST_RUNTIME_CACHE_DIR", "")).strip()
        if cache_dir:
            self.cache_dir = Path(cache_dir)

        timeout_raw = str(
            os.getenv(
                "TEST_RUNTIME_BOOTSTRAP_ATTEMPT_TIMEOUT_SEC",
                os.getenv("TEST_RUNTIME_BOOTSTRAP_TIMEOUT_SEC", str(self.bootstrap_attempt_timeout_sec)),
            )
        ).strip()
        try:
            self.bootstrap_attempt_timeout_sec = max(30, int(timeout_raw or self.bootstrap_attempt_timeout_sec))
            self.bootstrap_timeout_sec = self.bootstrap_attempt_timeout_sec
        except ValueError:
            pass
        max_total_raw = str(
            os.getenv("TEST_RUNTIME_BOOTSTRAP_MAX_TOTAL_SEC", str(self.bootstrap_max_total_sec))
        ).strip()
        try:
            self.bootstrap_max_total_sec = max(
                self.bootstrap_attempt_timeout_sec,
                int(max_total_raw or self.bootstrap_max_total_sec),
            )
        except ValueError:
            pass
        fallback_depth = str(os.getenv("TEST_RUNTIME_FALLBACK_DEPTH", self.fallback_depth)).strip().lower()
        if fallback_depth not in {"minimal", "medium", "full"}:
            fallback_depth = "medium"
        self.fallback_depth = fallback_depth

        self.auto_editable_install = _bool_env(
            os.getenv("TEST_RUNTIME_AUTO_EDITABLE_INSTALL", "on"),
            self.auto_editable_install,
        )

    def set_context(self, *, repo_slug: str, commit_sha: str) -> None:
        """Set active benchmark repository context."""
        self._repo_slug = str(repo_slug or "").strip()
        self._commit_sha = str(commit_sha or "").strip()
        self._repo_runtime_cache.clear()

    def clear_repo_cache(self) -> None:
        self._repo_runtime_cache.clear()

    def get_runtime(self, repo_path: Path, log: Optional[Callable[[str], None]] = None) -> dict[str, Any]:
        """Return runtime handle for a repository checkout."""
        repo_root = Path(repo_path).resolve()
        repo_key = str(repo_root)
        if repo_key in self._repo_runtime_cache:
            return dict(self._repo_runtime_cache[repo_key])

        if self.isolation_mode != "repo_cached_venv":
            runtime = self._build_host_runtime(repo_root)
            self._repo_runtime_cache[repo_key] = runtime
            return dict(runtime)

        runtime = self._build_repo_cached_runtime(repo_root, log=log)
        self._repo_runtime_cache[repo_key] = runtime
        return dict(runtime)

    def _build_host_runtime(self, repo_root: Path) -> dict[str, Any]:
        env = dict(os.environ)
        env["PYTHONPATH"] = self._compose_pythonpath(repo_root, env.get("PYTHONPATH", ""))
        return {
            "runtime_env_id": "host",
            "python_executable": sys.executable,
            "env": env,
            "runtime_ready": True,
            "bootstrap_actions": [],
            "runtime_bootstrap_attempts": [],
            "bootstrap_error": "",
            "bootstrap_error_reason": "",
            "runtime_install_mode": "host",
            "isolation_mode": "off",
            "cache_path": "",
        }

    def _build_repo_cached_runtime(
        self,
        repo_root: Path,
        *,
        log: Optional[Callable[[str], None]] = None,
    ) -> dict[str, Any]:
        logger = log if callable(log) else (lambda _: None)
        runtime_key = self._runtime_key()
        venv_dir = self.cache_dir / runtime_key
        python_bin = venv_dir / "bin" / "python"
        bootstrap_actions: list[str] = []
        bootstrap_error = ""
        bootstrap_error_reason = ""
        runtime_install_mode = "source"
        runtime_bootstrap_attempts: list[dict[str, Any]] = []
        bootstrap_started_at = time.time()

        self.cache_dir.mkdir(parents=True, exist_ok=True)

        def _remaining_bootstrap_budget() -> int:
            elapsed = int(time.time() - bootstrap_started_at)
            return max(0, int(self.bootstrap_max_total_sec) - elapsed)

        def _record_attempt(
            *,
            step: str,
            cmd: list[str],
            returncode: int,
            output: str,
            elapsed_sec: float,
            timeout_sec: int,
        ) -> None:
            runtime_bootstrap_attempts.append({
                "step": str(step),
                "command": " ".join(cmd),
                "returncode": int(returncode),
                "elapsed_sec": round(float(elapsed_sec), 2),
                "timeout_sec": int(timeout_sec),
                "output": self._compact_error(output, limit=500),
            })

        def _run_bootstrap_cmd(
            *,
            step: str,
            cmd: list[str],
            env: Optional[dict[str, str]] = None,
        ) -> tuple[int, str]:
            remaining = _remaining_bootstrap_budget()
            if remaining <= 0:
                _record_attempt(
                    step=step,
                    cmd=cmd,
                    returncode=124,
                    output="bootstrap_budget_exhausted",
                    elapsed_sec=0.0,
                    timeout_sec=0,
                )
                return 124, "bootstrap_budget_exhausted"
            timeout_sec = max(30, min(self.bootstrap_attempt_timeout_sec, remaining))
            started = time.time()
            rc, out = self._run_cmd(cmd, timeout=timeout_sec, env=env)
            _record_attempt(
                step=step,
                cmd=cmd,
                returncode=rc,
                output=out,
                elapsed_sec=time.time() - started,
                timeout_sec=timeout_sec,
            )
            return rc, out

        if not python_bin.exists():
            logger(f"Test runtime bootstrap: creating venv {venv_dir}")
            rc, out = _run_bootstrap_cmd(
                step="venv_create",
                cmd=[sys.executable, "-m", "venv", str(venv_dir)],
            )
            if rc != 0:
                bootstrap_error = f"venv_create_failed: {self._compact_error(out)}"
                bootstrap_error_reason = self._classify_bootstrap_error(
                    step="venv_create",
                    output=out,
                    returncode=rc,
                )
                return self._runtime_payload(
                    runtime_key=runtime_key,
                    python_bin=python_bin,
                    repo_root=repo_root,
                    ready=False,
                    bootstrap_actions=bootstrap_actions,
                    runtime_bootstrap_attempts=runtime_bootstrap_attempts,
                    bootstrap_error=bootstrap_error,
                    bootstrap_error_reason=bootstrap_error_reason,
                    runtime_install_mode=runtime_install_mode,
                    cache_path=venv_dir,
                )
            bootstrap_actions.append("venv_created")

        base_ready_marker = venv_dir / ".base_bootstrap_ready"
        if not base_ready_marker.exists():
            logger("Test runtime bootstrap: installing pip/wheel/pytest")
            bootstrap_cmds = [
                ["-m", "pip", "install", "--upgrade", "pip", "wheel"],
                ["-m", "pip", "install", "pytest"],
            ]
            for cmd_suffix in bootstrap_cmds:
                rc, out = _run_bootstrap_cmd(
                    step="bootstrap_base_packages",
                    cmd=[str(python_bin), *cmd_suffix],
                )
                if rc != 0:
                    bootstrap_error = f"runtime_bootstrap_failed: {self._compact_error(out)}"
                    bootstrap_error_reason = self._classify_bootstrap_error(
                        step="bootstrap_base_packages",
                        output=out,
                        returncode=rc,
                    )
                    return self._runtime_payload(
                        runtime_key=runtime_key,
                        python_bin=python_bin,
                        repo_root=repo_root,
                        ready=False,
                        bootstrap_actions=bootstrap_actions,
                        runtime_bootstrap_attempts=runtime_bootstrap_attempts,
                        bootstrap_error=bootstrap_error,
                        bootstrap_error_reason=bootstrap_error_reason,
                        runtime_install_mode=runtime_install_mode,
                        cache_path=venv_dir,
                    )
            base_ready_marker.write_text(f"{int(time.time())}\n", encoding="utf-8")
            bootstrap_actions.append("base_packages_ready")

        if self.auto_editable_install:
            target_marker = venv_dir / ".editable_target"
            mode_marker = venv_dir / ".runtime_install_mode"
            target_path = str(repo_root)
            previous_target = ""
            if target_marker.exists():
                try:
                    previous_target = target_marker.read_text(encoding="utf-8").strip()
                except OSError:
                    previous_target = ""
            if previous_target != target_path:
                logger("Test runtime bootstrap: pip install -e .")
                install_ok = False
                constrained_env: Optional[dict[str, str]] = None
                rc, out = _run_bootstrap_cmd(
                    step="editable_install",
                    cmd=[str(python_bin), "-m", "pip", "install", "-e", str(repo_root)],
                )
                if rc == 0:
                    install_ok = True
                    runtime_install_mode = "editable"
                    bootstrap_actions.append("editable_install_ready")
                else:
                    bootstrap_error_reason = self._classify_bootstrap_error(
                        step="editable_install",
                        output=out,
                        returncode=rc,
                    )
                    bootstrap_error = f"runtime_bootstrap_failed: {self._compact_error(out)}"
                    if (
                        self.fallback_depth in {"medium", "full"}
                        and self._should_try_constraints_fallback(bootstrap_error_reason, out)
                    ):
                        logger("Test runtime bootstrap: constrained editable fallback (setuptools<70)")
                        bootstrap_actions.append("editable_fallback_constraints")
                        constraints_file = venv_dir / ".bootstrap_constraints.txt"
                        constraints_file.write_text("setuptools<70\n", encoding="utf-8")
                        constrained_env = dict(os.environ)
                        constrained_env["PIP_CONSTRAINT"] = str(constraints_file)
                        pin_rc, pin_out = _run_bootstrap_cmd(
                            step="setuptools_constraint_pin",
                            cmd=[str(python_bin), "-m", "pip", "install", "--upgrade", "setuptools<70"],
                            env=constrained_env,
                        )
                        if pin_rc == 0:
                            retry_rc, retry_out = _run_bootstrap_cmd(
                                step="editable_install_constrained",
                                cmd=[str(python_bin), "-m", "pip", "install", "-e", str(repo_root)],
                                env=constrained_env,
                            )
                            if retry_rc == 0:
                                install_ok = True
                                runtime_install_mode = "editable_constrained"
                                bootstrap_actions.append("editable_install_ready_constrained")
                            else:
                                bootstrap_error_reason = self._classify_bootstrap_error(
                                    step="editable_install_constrained",
                                    output=retry_out,
                                    returncode=retry_rc,
                                )
                                bootstrap_error = f"runtime_bootstrap_failed: {self._compact_error(retry_out)}"
                        else:
                            bootstrap_error_reason = self._classify_bootstrap_error(
                                step="setuptools_constraint_pin",
                                output=pin_out,
                                returncode=pin_rc,
                            )
                            bootstrap_error = f"runtime_bootstrap_failed: {self._compact_error(pin_out)}"
                    if (
                        not install_ok
                        and self.fallback_depth in {"medium", "full"}
                        and self._should_try_no_build_isolation_fallback(bootstrap_error_reason, out)
                    ):
                        build_requires = self._load_build_system_requires(repo_root)
                        if build_requires:
                            logger(
                                "Test runtime bootstrap: build requirements preinstall "
                                "for no-build-isolation editable fallback"
                            )
                            bootstrap_actions.append("build_requirements_preinstall_attempted")
                            build_rc, build_out = _run_bootstrap_cmd(
                                step="build_requirements_install",
                                cmd=[str(python_bin), "-m", "pip", "install", *build_requires],
                                env=constrained_env,
                            )
                            if build_rc == 0:
                                bootstrap_actions.append("build_requirements_preinstalled")
                                no_iso_rc, no_iso_out = _run_bootstrap_cmd(
                                    step="editable_install_no_build_isolation",
                                    cmd=[
                                        str(python_bin),
                                        "-m",
                                        "pip",
                                        "install",
                                        "--no-build-isolation",
                                        "-e",
                                        str(repo_root),
                                    ],
                                    env=constrained_env,
                                )
                                if no_iso_rc == 0:
                                    install_ok = True
                                    runtime_install_mode = "editable_no_build_isolation"
                                    bootstrap_actions.append("editable_no_build_isolation_ready")
                                    bootstrap_error = ""
                                    bootstrap_error_reason = ""
                                else:
                                    bootstrap_error_reason = self._classify_bootstrap_error(
                                        step="editable_install_no_build_isolation",
                                        output=no_iso_out,
                                        returncode=no_iso_rc,
                                    )
                                    bootstrap_error = (
                                        f"runtime_bootstrap_failed: {self._compact_error(no_iso_out)}"
                                    )
                            else:
                                bootstrap_error_reason = self._classify_bootstrap_error(
                                    step="build_requirements_install",
                                    output=build_out,
                                    returncode=build_rc,
                                )
                                bootstrap_error = (
                                    f"runtime_bootstrap_failed: {self._compact_error(build_out)}"
                                )
                    if not install_ok and self.fallback_depth == "full":
                        logger("Test runtime bootstrap: non-editable fallback install")
                        bootstrap_actions.append("non_editable_fallback_attempted")
                        non_editable_rc, non_editable_out = _run_bootstrap_cmd(
                            step="non_editable_install",
                            cmd=[str(python_bin), "-m", "pip", "install", "--no-deps", str(repo_root)],
                        )
                        if non_editable_rc == 0:
                            install_ok = True
                            runtime_install_mode = "non_editable"
                            bootstrap_actions.append("non_editable_install_ready")
                        else:
                            bootstrap_error_reason = self._classify_bootstrap_error(
                                step="non_editable_install",
                                output=non_editable_out,
                                returncode=non_editable_rc,
                            )
                            bootstrap_error = (
                                f"runtime_bootstrap_failed: {self._compact_error(non_editable_out)}"
                            )
                    if not install_ok and self._allow_source_mode_partial_ready(bootstrap_error_reason):
                        runtime_install_mode = "source_partial"
                        bootstrap_actions.append("source_mode_partial_ready")
                        bootstrap_actions.append(f"source_mode_reason:{bootstrap_error_reason}")
                        return self._runtime_payload(
                            runtime_key=runtime_key,
                            python_bin=python_bin,
                            repo_root=repo_root,
                            ready=True,
                            bootstrap_actions=bootstrap_actions,
                            runtime_bootstrap_attempts=runtime_bootstrap_attempts,
                            bootstrap_error=bootstrap_error,
                            bootstrap_error_reason=bootstrap_error_reason,
                            runtime_install_mode=runtime_install_mode,
                            cache_path=venv_dir,
                        )
                    if not install_ok:
                        return self._runtime_payload(
                            runtime_key=runtime_key,
                            python_bin=python_bin,
                            repo_root=repo_root,
                            ready=False,
                            bootstrap_actions=bootstrap_actions,
                            runtime_bootstrap_attempts=runtime_bootstrap_attempts,
                            bootstrap_error=bootstrap_error,
                            bootstrap_error_reason=bootstrap_error_reason,
                            runtime_install_mode=runtime_install_mode,
                            cache_path=venv_dir,
                        )
                target_marker.write_text(target_path + "\n", encoding="utf-8")
                try:
                    mode_marker.write_text(runtime_install_mode + "\n", encoding="utf-8")
                except OSError:
                    pass
            else:
                runtime_install_mode = "editable_cached"
                mode_marker = venv_dir / ".runtime_install_mode"
                if mode_marker.exists():
                    try:
                        persisted_mode = mode_marker.read_text(encoding="utf-8").strip()
                        if persisted_mode:
                            runtime_install_mode = persisted_mode
                    except OSError:
                        runtime_install_mode = "editable_cached"
                bootstrap_actions.append("editable_install_cached")
        else:
            runtime_install_mode = "source"
            bootstrap_actions.append("editable_install_disabled")

        return self._runtime_payload(
            runtime_key=runtime_key,
            python_bin=python_bin,
            repo_root=repo_root,
            ready=True,
            bootstrap_actions=bootstrap_actions,
            runtime_bootstrap_attempts=runtime_bootstrap_attempts,
            bootstrap_error="",
            bootstrap_error_reason="",
            runtime_install_mode=runtime_install_mode,
            cache_path=venv_dir,
        )

    def _runtime_payload(
        self,
        *,
        runtime_key: str,
        python_bin: Path,
        repo_root: Path,
        ready: bool,
        bootstrap_actions: list[str],
        runtime_bootstrap_attempts: list[dict[str, Any]],
        bootstrap_error: str,
        bootstrap_error_reason: str,
        runtime_install_mode: str,
        cache_path: Path,
    ) -> dict[str, Any]:
        env = dict(os.environ)
        env["PYTHONPATH"] = self._compose_pythonpath(repo_root, env.get("PYTHONPATH", ""))
        env["VIRTUAL_ENV"] = str(cache_path)
        env["PATH"] = f"{cache_path / 'bin'}{os.pathsep}{env.get('PATH', '')}"
        env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        return {
            "runtime_env_id": runtime_key,
            "python_executable": str(python_bin),
            "env": env,
            "runtime_ready": bool(ready),
            "bootstrap_actions": list(bootstrap_actions),
            "runtime_bootstrap_attempts": list(runtime_bootstrap_attempts),
            "bootstrap_error": self._compact_error(bootstrap_error),
            "bootstrap_error_reason": str(bootstrap_error_reason or ""),
            "runtime_install_mode": str(runtime_install_mode or "source"),
            "isolation_mode": "repo_cached_venv",
            "cache_path": str(cache_path),
        }

    def _runtime_key(self) -> str:
        repo_slug = self._repo_slug or "repo"
        commit_sha = self._commit_sha or "unknown"
        py_tag = f"py{sys.version_info.major}{sys.version_info.minor}"
        raw = f"{repo_slug}@{commit_sha}:{py_tag}"
        digest = hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:12]
        safe_repo = repo_slug.replace("/", "__")
        return f"{safe_repo}_{commit_sha[:12]}_{py_tag}_{digest}"

    def _compose_pythonpath(self, repo_root: Path, existing: str) -> str:
        paths = [str(repo_root)]
        for candidate in ("src", "lib"):
            candidate_path = repo_root / candidate
            if candidate_path.exists() and candidate_path.is_dir():
                paths.append(str(candidate_path))
        if existing:
            paths.append(existing)
        seen: set[str] = set()
        ordered: list[str] = []
        for value in paths:
            if value and value not in seen:
                seen.add(value)
                ordered.append(value)
        return os.pathsep.join(ordered)

    def _run_cmd(
        self,
        cmd: list[str],
        *,
        timeout: int,
        env: Optional[dict[str, str]] = None,
    ) -> tuple[int, str]:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
                env=env,
            )
            combined = f"{result.stdout}\n{result.stderr}".strip()
            return result.returncode, combined
        except subprocess.TimeoutExpired:
            return 124, "command_timeout"
        except Exception as exc:  # pragma: no cover - defensive
            return 1, str(exc)

    def _is_legacy_setuptools_error(self, output: str) -> bool:
        text = str(output or "").lower()
        return "setuptools.dep_util" in text or "no module named 'setuptools.dep_util'" in text

    def _should_try_constraints_fallback(self, reason: str, output: str) -> bool:
        if self.fallback_depth == "minimal":
            return False
        if reason in {
            "legacy_build_backend_incompat",
            "editable_build_backend_failure",
            "package_build_failed",
            "wheel_build_failed",
        }:
            return True
        return self._is_legacy_setuptools_error(output)

    def _allow_source_mode_partial_ready(self, reason: str) -> bool:
        if self.fallback_depth not in {"medium", "full"}:
            return False
        full_allowed = {
            "legacy_build_backend_incompat",
            "editable_build_backend_failure",
            "source_checkout_unbuilt_extensions",
            "package_build_failed",
            "wheel_build_failed",
        }
        if self.fallback_depth == "medium":
            return reason in {
                "legacy_build_backend_incompat",
                "editable_build_backend_failure",
            }
        return reason in full_allowed

    def _should_try_no_build_isolation_fallback(self, reason: str, output: str) -> bool:
        if self.fallback_depth not in {"medium", "full"}:
            return False
        if reason in {
            "legacy_build_backend_incompat",
            "editable_build_backend_failure",
            "module_not_found",
        }:
            return True
        text = str(output or "").lower()
        return "extension_helpers" in text or "pyproject.toml" in text

    def _load_build_system_requires(self, repo_root: Path) -> list[str]:
        pyproject_path = Path(repo_root) / "pyproject.toml"
        if not pyproject_path.exists():
            return []
        try:
            payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        build_system = payload.get("build-system")
        if not isinstance(build_system, dict):
            return []
        requires = build_system.get("requires")
        if not isinstance(requires, list):
            return []
        normalized: list[str] = []
        seen: set[str] = set()
        for item in requires:
            value = str(item or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            normalized.append(value)
        return normalized

    def _classify_bootstrap_error(self, *, step: str, output: str, returncode: int) -> str:
        text = str(output or "").lower()
        if returncode == 124 or "command_timeout" in text or "bootstrap_budget_exhausted" in text:
            return "bootstrap_timeout"
        if "setuptools.dep_util" in text or "no module named 'setuptools.dep_util'" in text:
            return "legacy_build_backend_incompat"
        if (
            "source checkout without building extension modules" in text
            or "cannot import astropy from source checkout" in text
        ):
            return "source_checkout_unbuilt_extensions"
        if "temporary failure in name resolution" in text or "connection timed out" in text:
            return "network_error"
        if "no matching distribution found" in text:
            return "dependency_resolution_failed"
        if "could not build wheels" in text:
            return "wheel_build_failed"
        if "subprocess-exited-with-error" in text:
            if "building editable for" in text or "getting requirements to build editable" in text:
                return "editable_build_backend_failure"
            if "building wheel for" in text:
                return "package_build_failed"
            return "build_backend_failure"
        if "modulenotfounderror" in text or "no module named" in text:
            return "module_not_found"
        if step == "venv_create":
            return "venv_create_failed"
        if "bootstrap_base_packages" in step:
            return "base_bootstrap_failed"
        if "editable" in step:
            return "editable_install_failed"
        return "runtime_bootstrap_failed"

    def _compact_error(self, output: str, *, limit: int = 1200) -> str:
        text = str(output or "").strip()
        if len(text) <= limit:
            return text
        return text[:limit] + "...<truncated>"
