import os
import json
import subprocess
from typing import Dict, List, Optional
from dotenv import load_dotenv
from utils.gptoss_agent import GPTOSSAgent

load_dotenv()

class GPTOSSCodeInterface:
    """Interface for interacting with GPT-OSS using Ollama with custom agent loop."""

    def __init__(self):
        """Ensure Ollama is running and initialize agent."""
        try:
            # Check if Ollama is running
            try:
                subprocess.run([
                    "ollama", "list"
                ], capture_output=True, text=True, check=True, timeout=5)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
                raise RuntimeError(
                    "Ollama is not running. Please start Ollama with: brew services start ollama"
                )

            print("✅ Ollama is ready")

        except FileNotFoundError:
            raise RuntimeError(
                "Ollama not found. Please ensure 'ollama' is installed and in PATH"
            )

    def execute_code_cli(self, prompt: str, cwd: str, model: str = None) -> Dict[str, any]:
        """Execute GPT-OSS agent with custom tool loop.

        Args:
            prompt: The prompt to send to GPT-OSS.
            cwd: Working directory to execute in.
            model: Optional model to use (default: gpt-oss:20b).
        """
        try:
            # DEBUG: Log execution details
            print(f"\n{'='*60}")
            print(f"DEBUG: Executing GPT-OSS Agent with Ollama")
            print(f"Working Directory: {cwd}")
            print(f"Model: {model if model else 'gpt-oss:20b'}")
            print(f"Prompt length: {len(prompt)} characters")
            print(f"Prompt preview (first 500 chars):\n{prompt[:500]}")
            print(f"{'='*60}\n")

            # Initialize agent
            agent = GPTOSSAgent(model=model if model else "gpt-oss:20b")

            # Run the task
            result = agent.run_task(prompt, cwd)

            # DEBUG: Log result
            print(f"\n{'='*60}")
            print(f"DEBUG: GPT-OSS Agent Execution Result")
            print(f"Success: {result['success']}")
            print(f"Iterations: {result['iterations']}")
            print(f"{'='*60}\n")

            # Convert agent result to expected format
            return {
                "success": result["success"],
                "stdout": f"Completed in {result['iterations']} iterations",
                "stderr": "",
                "returncode": 0 if result["success"] else 1,
            }

        except Exception as e:
            print(f"\n{'='*60}")
            print(f"ERROR: GPT-OSS Agent failed")
            print(f"Error: {str(e)}")
            print(f"{'='*60}\n")
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Error executing GPT-OSS Agent: {str(e)}",
                "returncode": -1,
            }

    def extract_file_changes(self, response: str) -> List[Dict[str, str]]:
        """Extract file changes from GPT-OSS's response."""
        # This will be implemented by patch_extractor.py
        # For now, return empty list
        return []
