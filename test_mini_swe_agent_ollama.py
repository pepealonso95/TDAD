#!/usr/bin/env python3
"""Test mini-swe-agent with local Ollama."""

import os
import sys
sys.path.insert(0, "/Users/rafaelalonso/Development/Master/Tesis/mini_swe_agent_fork/src")

from minisweagent.models import get_model
from minisweagent.environments import get_environment
from minisweagent.agents.default import DefaultAgent

# Configure LiteLLM for Ollama
os.environ["MSWEA_COST_TRACKING"] = "ignore_errors"  # Ollama is free, ignore cost tracking

# Create model with Ollama configuration
model = get_model(
    input_model_name="ollama_chat/qwen3-coder:30b",  # LiteLLM format for Ollama
    config={
        "model_kwargs": {
            "api_base": "http://localhost:11434",  # Ollama endpoint
        },
        "model_class": "litellm",  # Use LiteLLM model
        "cost_tracking": "ignore_errors"  # Ignore cost calculation for Ollama
    }
)

# Create local environment
env = get_environment(
    config={"environment_class": "local"},
    default_type="local"
)

# Create agent
agent = DefaultAgent(
    model=model,
    env=env,
    system_template="You are a helpful coding assistant. Use bash commands to complete tasks.",
    instance_template="Task: {{ task }}",
    action_observation_template="Output:\n{{ output['output'] }}",
    format_error_template="Error: Invalid format. Please use ```bash\\n<command>\\n``` blocks.",
    timeout_template="Command timed out.",
    step_limit=5  # Limit to 5 steps for testing
)

# Test with a simple task
print("Testing mini-swe-agent with Ollama...")
print(f"Model: {model.config.model_name}")
print(f"Ollama endpoint: http://localhost:11434")
print()

try:
    status, message = agent.run("List all Python files in the current directory and count them")
    print(f"Status: {status}")
    print(f"Message: {message}")
    print()
    print("✅ SUCCESS: Mini-swe-agent works with Ollama!")
except Exception as e:
    print(f"❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
