#!/usr/bin/env python3
"""Test mini-swe-agent with a real SWE-bench instance.

Uses the same configuration as qwen_mini_interface.py (default templates,
correct cwd parameter, env vars, drop_params) so this script is a faithful
standalone reproduction of what the full pipeline does.
"""

import os
import sys
import time
import tempfile
import subprocess
from pathlib import Path

# Add mini-swe-agent to path
sys.path.insert(0, "/Users/rafaelalonso/Development/Master/Tesis/mini_swe_agent_fork/src")

from minisweagent.models import get_model
from minisweagent.environments import get_environment
from minisweagent.agents.default import DefaultAgent

# Reuse the proven templates from the adapter
sys.path.insert(0, str(Path(__file__).parent))
from utils.qwen_mini_interface import (
    SYSTEM_TEMPLATE,
    INSTANCE_TEMPLATE,
    ACTION_OBSERVATION_TEMPLATE,
    FORMAT_ERROR_TEMPLATE,
    TIMEOUT_TEMPLATE,
    DEFAULT_ENV_VARS,
)
from code_swe_agent import load_cached_dataset

os.environ["MSWEA_COST_TRACKING"] = "ignore_errors"


def setup_repository(instance, work_dir):
    """Clone and checkout repository to base commit."""
    repo_path = work_dir / "repo"
    repo_url = f"https://github.com/{instance['repo']}"

    print(f"Cloning {repo_url}...")
    result = subprocess.run(
        ["git", "clone", "--depth", "1", "--single-branch", repo_url, str(repo_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("Shallow clone failed, retrying full clone...")
        subprocess.run(
            ["git", "clone", repo_url, str(repo_path)],
            check=True,
            capture_output=True,
            text=True,
        )

    # Unshallow so we can checkout base_commit
    subprocess.run(
        ["git", "fetch", "--unshallow"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )

    print(f"Checking out {instance['base_commit'][:8]}...")
    subprocess.run(
        ["git", "checkout", instance["base_commit"]],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    return repo_path


def extract_patch(repo_path):
    """Extract git diff as patch."""
    result = subprocess.run(
        ["git", "diff", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def main():
    print("=" * 80)
    print("Testing Mini-SWE-Agent with SWE-bench Instance")
    print("=" * 80)
    print()

    # Load one instance from SWE-bench Verified (uses local cache if available)
    print("Loading SWE-bench Verified dataset (1 instance)...")
    dataset = load_cached_dataset("princeton-nlp/SWE-bench_Verified", limit=1)
    instance = dataset[0]

    print(f"Instance ID: {instance['instance_id']}")
    print(f"Repository:  {instance['repo']}")
    print(f"Base commit: {instance['base_commit'][:8]}")
    print()

    # Create temporary working directory
    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)

        # Setup repository
        repo_path = setup_repository(instance, work_dir)
        print(f"Repository cloned to: {repo_path}")
        print()

        # Create model — local Qwen 30B via Ollama
        print("Creating Ollama model (qwen3-coder:30b)...")
        model = get_model(
            input_model_name="ollama_chat/qwen3-coder:30b",
            config={
                "model_kwargs": {
                    "api_base": "http://localhost:11434",
                    "drop_params": True,
                },
                "model_class": "litellm",
                "cost_tracking": "ignore_errors",
            },
        )

        # Create environment — CRITICAL: Use 'cwd', not 'working_dir'
        print(f"Creating local environment (cwd={repo_path})...")
        env = get_environment(
            config={
                "environment_class": "local",
                "cwd": str(repo_path),
                "env": DEFAULT_ENV_VARS,
            },
            default_type="local",
        )

        # Validate CWD immediately (resolve symlinks — macOS /var -> /private/var)
        cwd_check = env.execute("pwd")
        actual_cwd = Path(cwd_check["output"].strip()).resolve()
        expected_cwd = repo_path.resolve()
        print(f"CWD validation: {actual_cwd}")
        assert actual_cwd == expected_cwd, f"CWD MISMATCH! Expected {expected_cwd}, got {actual_cwd}"
        print("CWD OK")
        print()

        # Create agent with default templates
        print("Creating agent (step_limit=100)...")
        agent = DefaultAgent(
            model=model,
            env=env,
            system_template=SYSTEM_TEMPLATE,
            instance_template=INSTANCE_TEMPLATE,
            action_observation_template=ACTION_OBSERVATION_TEMPLATE,
            format_error_template=FORMAT_ERROR_TEMPLATE,
            timeout_template=TIMEOUT_TEMPLATE,
            step_limit=100,
            cost_limit=0,
        )

        # Verbose logging hook
        format_errors = [0]
        timeouts = [0]
        step_counter = [0]

        original_add_message = agent.add_message
        def verbose_add_message(role, content="", **kwargs):
            if role == "assistant":
                step_counter[0] += 1
                preview = content[:600] + ("..." if len(content) > 600 else "")
                print(f"\n{'='*60}")
                print(f"STEP {step_counter[0]}  (model call {agent.model.n_calls})")
                print(f"{'='*60}")
                print(preview)
            elif role == "user":
                if "EXACTLY ONE action" in content:
                    format_errors[0] += 1
                    print(f"\n  !! FORMAT_ERROR #{format_errors[0]}")
                elif "timed out" in content:
                    timeouts[0] += 1
                    print(f"\n  !! TIMEOUT #{timeouts[0]}")
                elif "returncode" in content:
                    # Extract returncode from XML
                    import re
                    rc_match = re.search(r"<returncode>(\d+)</returncode>", content)
                    rc = rc_match.group(1) if rc_match else "?"
                    # Show first 200 chars of output
                    out_match = re.search(r"<output>\s*(.*?)\s*</output>", content, re.DOTALL)
                    out_preview = ""
                    if out_match:
                        out_preview = out_match.group(1)[:200]
                    print(f"\n  => rc={rc}  output: {out_preview}")
                else:
                    print(f"\n  [user] {content[:150]}")
            original_add_message(role, content, **kwargs)

        agent.add_message = verbose_add_message

        # Format task
        task = instance.get("problem_statement", "No description provided")

        print("=" * 80)
        print("Starting agent run...")
        print("=" * 80)
        print()

        # Run agent
        t0 = time.time()
        try:
            status, message = agent.run(task)
            elapsed = time.time() - t0

            print()
            print("=" * 80)
            print(f"Agent finished: {status}")
            print(f"Elapsed: {elapsed:.1f}s")
            print(f"Steps: {model.n_calls}")
            print(f"Format errors: {format_errors[0]}")
            print(f"Timeouts: {timeouts[0]}")
            print("=" * 80)
            print(f"Final message: {message[:300]}")
            print()

            # Extract patch
            patch = extract_patch(repo_path)

            if patch:
                print("Generated patch:")
                print("-" * 80)
                print(patch[:1000] + "..." if len(patch) > 1000 else patch)
                print("-" * 80)
                print(f"Total patch size: {len(patch)} characters")
                print()
                print("SUCCESS: Mini-swe-agent generated a patch!")
            else:
                print("WARNING: No changes made (empty patch)")

        except Exception as e:
            elapsed = time.time() - t0
            print(f"\nERROR after {elapsed:.1f}s: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
