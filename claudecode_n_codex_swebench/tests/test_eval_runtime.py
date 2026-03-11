import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.eval_runtime import describe_eval_capacity


def test_describe_eval_capacity_respects_docker_memory(monkeypatch):
    monkeypatch.setattr(
        "utils.eval_runtime.get_docker_info",
        lambda: {"NCPU": 14, "MemTotal": 8 * 1024 * 1024 * 1024},
    )
    monkeypatch.delenv("DOCKER_EVAL_MEM_PER_WORKER_GB", raising=False)

    capacity = describe_eval_capacity(instance_count=10)

    assert capacity["cpu_target"] == 7
    assert capacity["mem_target"] == 4
    assert capacity["workers"] == 4


def test_describe_eval_capacity_caps_to_instance_count(monkeypatch):
    monkeypatch.setattr(
        "utils.eval_runtime.get_docker_info",
        lambda: {"NCPU": 14, "MemTotal": 16 * 1024 * 1024 * 1024},
    )

    capacity = describe_eval_capacity(instance_count=3)

    assert capacity["workers"] == 3
