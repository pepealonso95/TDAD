from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _read_int_env(name: str, default: int, *, minimum: int = 0) -> int:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return max(minimum, int(default))
    try:
        return max(minimum, int(raw))
    except ValueError:
        return max(minimum, int(default))


def get_docker_info() -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{json .}}"],
            capture_output=True,
            text=True,
            check=True,
        )
        payload = str(result.stdout or "").strip()
        if not payload:
            return {}
        data = json.loads(payload)
        if isinstance(data, dict):
            return data
    except Exception:
        return {}
    return {}


def describe_eval_capacity(*, instance_count: Optional[int] = None) -> dict[str, Any]:
    docker_info = get_docker_info()
    cpu_total = max(1, int(docker_info.get("NCPU") or os.cpu_count() or 1))
    cpu_cap = _read_int_env("DOCKER_EVAL_MAX_WORKERS_CAP", 8, minimum=1)
    cpu_target = 1 if cpu_total == 1 else max(2, min(cpu_cap, cpu_total // 2))

    mem_total_bytes = max(0, int(docker_info.get("MemTotal") or 0))
    mem_per_worker_gib = _read_int_env("DOCKER_EVAL_MEM_PER_WORKER_GB", 2, minimum=1)
    bytes_per_worker = mem_per_worker_gib * 1024 * 1024 * 1024
    mem_target = cpu_target
    if mem_total_bytes > 0 and bytes_per_worker > 0:
        mem_target = max(1, mem_total_bytes // bytes_per_worker)

    workers = max(1, min(cpu_target, mem_target))
    if instance_count is not None:
        workers = min(workers, max(1, int(instance_count)))

    return {
        "workers": max(1, int(workers)),
        "cpu_total": cpu_total,
        "cpu_target": cpu_target,
        "mem_total_bytes": mem_total_bytes,
        "mem_total_gib": round(mem_total_bytes / (1024 ** 3), 2) if mem_total_bytes else 0.0,
        "mem_per_worker_gib": mem_per_worker_gib,
        "mem_target": max(1, int(mem_target)),
        "docker_info_available": bool(docker_info),
    }


def default_eval_worker_count(*, instance_count: Optional[int] = None) -> int:
    return int(describe_eval_capacity(instance_count=instance_count)["workers"])


def cleanup_stale_swebench_eval_containers(
    *,
    current_run_id: Optional[str] = None,
) -> list[str]:
    max_age_seconds = _read_int_env("DOCKER_EVAL_STALE_CONTAINER_MAX_AGE_SEC", 1800, minimum=0)
    if max_age_seconds <= 0:
        return []

    try:
        result = subprocess.run(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                "name=sweb.eval.",
                "--format",
                "{{.ID}}\t{{.Names}}",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception:
        return []

    now = datetime.now(timezone.utc)
    removable: list[tuple[str, str]] = []
    for line in (result.stdout or "").splitlines():
        parts = [part.strip() for part in line.split("\t") if part.strip()]
        if len(parts) != 2:
            continue
        container_id, name = parts
        if current_run_id and current_run_id in name:
            continue
        try:
            inspect = subprocess.run(
                [
                    "docker",
                    "inspect",
                    container_id,
                    "--format",
                    "{{.Created}}\t{{.State.Status}}",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
        except Exception:
            continue
        inspect_parts = [part.strip() for part in str(inspect.stdout or "").split("\t") if part.strip()]
        if len(inspect_parts) != 2:
            continue
        created_raw, _status = inspect_parts
        try:
            created_at = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        age_seconds = (now - created_at.astimezone(timezone.utc)).total_seconds()
        if age_seconds >= max_age_seconds:
            removable.append((container_id, name))

    if not removable:
        return []

    container_ids = [container_id for container_id, _name in removable]
    try:
        subprocess.run(
            ["docker", "rm", "-f", *container_ids],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return []
    return [name for _container_id, name in removable]
