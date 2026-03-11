import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from code_swe_agent_graphrag import GraphRAGCodeSWEAgent


def test_qwen_mini_process_instance_forwards_prompt_and_mlx_telemetry():
    agent = GraphRAGCodeSWEAgent.__new__(GraphRAGCodeSWEAgent)
    agent.backend = "qwen-mini"
    agent.use_graphrag = True
    agent.tdd_mode = True
    agent.mcp = None

    class FakeInterface:
        def execute_code_cli(self, **kwargs):
            return {
                "prediction": "diff --git a/a.py b/a.py",
                "attempts_used": 2,
                "prompt_trace_id": "trace-live",
                "prompt_budget_chars": 48000,
                "prompt_chars_before": 6579,
                "prompt_chars_after": 6579,
                "prompt_estimated_tokens_before": 1645,
                "prompt_estimated_tokens_after": 1645,
                "prompt_section_sizes_before": {"task": 6579},
                "prompt_section_sizes_after": {"task": 6579},
                "prompt_trimmed": False,
                "prompt_trimmed_sections": [],
                "mlx_backend_ready": True,
                "mlx_backend_started_now": False,
                "mlx_backend_reused_existing": True,
                "mlx_backend_before": {"pid": 83377, "rss_kb": 76928},
                "mlx_backend_after": {"pid": 83377, "rss_kb": 80123},
                "mlx_backend_crash_detected": False,
                "mlx_backend_restarted": False,
                "mlx_backend_failure_reason": "",
                "attempt_summaries": [],
                "graphrag_metadata": {},
            }

    agent.interface = FakeInterface()

    instance = {
        "instance_id": "demo__1",
        "repo": "demo/repo",
        "base_commit": "abcdef1234567890",
        "problem_statement": "fix it",
        "hints_text": "",
        "FAIL_TO_PASS": [],
        "PASS_TO_PASS": [],
    }

    result = agent.process_instance(instance)

    assert result["prediction"] == "diff --git a/a.py b/a.py"
    assert result["prompt_trace_id"] == "trace-live"
    assert result["prompt_budget_chars"] == 48000
    assert result["prompt_chars_before"] == 6579
    assert result["prompt_chars_after"] == 6579
    assert result["prompt_estimated_tokens_before"] == 1645
    assert result["prompt_estimated_tokens_after"] == 1645
    assert result["prompt_section_sizes_before"] == {"task": 6579}
    assert result["prompt_section_sizes_after"] == {"task": 6579}
    assert result["prompt_trimmed"] is False
    assert result["prompt_trimmed_sections"] == []
    assert result["mlx_backend_ready"] is True
    assert result["mlx_backend_started_now"] is False
    assert result["mlx_backend_reused_existing"] is True
    assert result["mlx_backend_before"] == {"pid": 83377, "rss_kb": 76928}
    assert result["mlx_backend_after"] == {"pid": 83377, "rss_kb": 80123}
    assert result["mlx_backend_crash_detected"] is False
    assert result["mlx_backend_restarted"] is False
    assert result["mlx_backend_failure_reason"] == ""
