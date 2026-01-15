#!/usr/bin/env python3
"""
Minimal test for QwenAgent - asks it to make a small edit to a real file.
"""

import os
import sys

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.qwen_agent import QwenAgent

# Create a simple test file to edit
TEST_FILE = "/tmp/test_qwen_target.py"
ORIGINAL_CONTENT = '''"""A simple calculator module."""

def add(a, b):
    return a + b

def subtract(a, b):
    return a - b

# TODO: Add multiply function
'''

def main():
    # Create the test file
    print(f"Creating test file: {TEST_FILE}")
    with open(TEST_FILE, 'w') as f:
        f.write(ORIGINAL_CONTENT)

    print(f"\n--- Original content ---")
    print(ORIGINAL_CONTENT)
    print("------------------------\n")

    # Initialize agent
    print("Initializing QwenAgent...")
    agent = QwenAgent(model="qwen3-coder:30b")
    agent.max_iterations = 5  # Limit iterations for quick test

    # Simple task: add the multiply function
    task = f"""Add a multiply function to the file {TEST_FILE}.

The function should:
- Be named 'multiply'
- Take two parameters (a, b)
- Return a * b

Read the file, add the function after subtract, and save it.
When done, say TASK COMPLETE."""

    print(f"Task: Add multiply function to {TEST_FILE}\n")

    # Run the agent
    result = agent.run_task(task, working_dir="/tmp")

    # Show results
    print(f"\n--- Final content ---")
    with open(TEST_FILE, 'r') as f:
        final_content = f.read()
    print(final_content)
    print("---------------------\n")

    # Check if multiply was added
    if "def multiply" in final_content:
        print("✅ SUCCESS: multiply function was added!")
    else:
        print("❌ FAILED: multiply function not found in file")

    print(f"\nIterations used: {result.get('iterations', 'unknown')}")

if __name__ == "__main__":
    main()
