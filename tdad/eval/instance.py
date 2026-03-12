"""Per-instance processing: clone, prompt, patch extraction."""

import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional

from . import opencode_interface, neo4j_lifecycle

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "swe_bench.txt"
SKILL_SOURCE_PATH = Path(__file__).resolve().parent.parent / "SKILL.md"

TDAD_SKILL_EXTRA = "\nUse the @tdad skill for this task.\n"

# MLX VLM local model configuration
MODEL_PATH = os.path.expanduser("~/.lmstudio/models/mlx-community/Qwen3.5-35B-A3B-4bit")
MODEL_ID = MODEL_PATH  # mlx_vlm.server uses the local path as model ID
MODEL_SERVER_BASE_URL = "http://127.0.0.1:7778/v1"
PROVIDER_ID = "mlx-local"


def process_instance(
    instance: dict,
    mode: str,
    timeout: int = 600,
) -> Dict[str, Any]:
    """Process a single SWE-bench instance.

    Args:
        instance: Dict with instance_id, repo, base_commit, problem_statement.
        mode: "baseline" or "tdad".
        timeout: Agent execution timeout in seconds.

    Returns:
        Prediction dict: {instance_id, model_name_or_path, model_patch}
    """
    instance_id = instance["instance_id"]
    repo = instance["repo"]
    base_commit = instance["base_commit"]
    problem_statement = instance["problem_statement"]

    prediction = {
        "instance_id": instance_id,
        "model_name_or_path": f"opencode-qwen3.5-35B-A3B-{mode}",
        "model_patch": "",
    }

    work_dir = None
    try:
        # 1. Clone and checkout
        work_dir = _clone_repo(repo, base_commit, instance_id)
        logger.info("[%s] Cloned %s @ %s → %s", instance_id, repo, base_commit, work_dir)

        # 2. Write opencode.jsonc for permissive tool access
        _write_opencode_config(work_dir)

        # 3. TDAD-specific setup
        if mode == "tdad":
            logger.info("[%s] Running TDAD setup (clear + index + skill)", instance_id)
            neo4j_lifecycle.clear()
            _run_tdad_index(work_dir)
            _install_skill(work_dir)

        # 4. Build prompt
        prompt = _build_prompt(instance, mode)

        # 5. Execute opencode
        result = opencode_interface.execute(prompt, cwd=str(work_dir), timeout=timeout)
        logger.info(
            "[%s] opencode result: success=%s rc=%d",
            instance_id, result["success"], result["returncode"],
        )
        if result["stderr"]:
            logger.info("[%s] opencode stderr:\n%s", instance_id, result["stderr"][:2000])
        if result["stdout"]:
            logger.info("[%s] opencode stdout:\n%s", instance_id, result["stdout"][:5000])

        # 6. Extract patch
        patch = _extract_patch(work_dir)
        prediction["model_patch"] = patch
        if patch:
            logger.info("[%s] Patch extracted (%d bytes)", instance_id, len(patch))
        else:
            logger.warning("[%s] Empty patch", instance_id)

    except Exception as exc:
        logger.error("[%s] Failed: %s", instance_id, exc, exc_info=True)

    finally:
        # 7. Cleanup
        if work_dir and os.path.exists(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)

    return prediction


def _clone_repo(repo: str, base_commit: str, instance_id: str) -> str:
    """Clone a GitHub repo and checkout the base commit."""
    work_dir = os.path.join(tempfile.gettempdir(), f"swe_eval_{instance_id}")

    # Clean up if exists from a previous run
    if os.path.exists(work_dir):
        shutil.rmtree(work_dir)

    repo_url = f"https://github.com/{repo}.git"
    subprocess.run(
        ["git", "clone", "--quiet", repo_url, work_dir],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "checkout", "--quiet", base_commit],
        check=True,
        capture_output=True,
        text=True,
        cwd=work_dir,
    )
    return work_dir


def _write_opencode_config(work_dir: str) -> None:
    """Write opencode.json with Ollama local model and permissive permissions."""
    model_ref = f"{PROVIDER_ID}/{MODEL_ID}"
    config = {
        "$schema": "https://opencode.ai/config.json",
        "provider": {
            PROVIDER_ID: {
                "npm": "@ai-sdk/openai-compatible",
                "name": "MLX Local (Qwen3.5-35B-A3B)",
                "options": {
                    "baseURL": MODEL_SERVER_BASE_URL,
                },
                "models": {
                    MODEL_ID: {
                        "name": "Qwen3.5-35B-A3B-4bit (MLX)",
                    },
                },
            },
        },
        "model": model_ref,
        "small_model": model_ref,
    }
    config_path = os.path.join(work_dir, "opencode.json")
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)


def _run_tdad_index(work_dir: str) -> None:
    """Run tdad index on the repo."""
    subprocess.run(
        ["tdad", "index", work_dir, "--force"],
        check=True,
        capture_output=True,
        text=True,
    )
    logger.info("tdad index completed for %s", work_dir)


def _install_skill(work_dir: str) -> None:
    """Copy the TDAD SKILL.md into the opencode skills directory.

    opencode expects: .opencode/skills/<name>/SKILL.md
    """
    skill_dir = os.path.join(work_dir, ".opencode", "skills", "tdad")
    os.makedirs(skill_dir, exist_ok=True)

    dest = os.path.join(skill_dir, "SKILL.md")
    shutil.copy2(str(SKILL_SOURCE_PATH), dest)
    logger.info("Installed TDAD skill at %s", dest)


def _build_prompt(instance: dict, mode: str) -> str:
    """Format the SWE-bench prompt template."""
    template = PROMPT_TEMPLATE_PATH.read_text()

    prompt = template.format(
        repo=instance["repo"],
        instance_id=instance["instance_id"],
        base_commit=instance["base_commit"],
        problem_statement=instance["problem_statement"],
    )

    if mode == "tdad":
        prompt += TDAD_SKILL_EXTRA

    return prompt


def _extract_patch(work_dir: str) -> str:
    """Extract the git diff from the work directory."""
    result = subprocess.run(
        ["git", "diff", "HEAD"],
        capture_output=True,
        text=True,
        cwd=work_dir,
    )
    return result.stdout.strip()
