import os
import json
import subprocess
from typing import Dict, List, Optional
from dotenv import load_dotenv

load_dotenv()

class ClaudeCodeInterface:
    """Interface for interacting with Claude Code CLI."""

    def __init__(self):
        """Ensure the Claude CLI is available on the system."""
        try:
            result = subprocess.run([
                "claude", "--version"
            ], capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(
                    "Claude CLI not found. Please ensure 'claude' is installed and in PATH"
                )
        except FileNotFoundError:
            raise RuntimeError(
                "Claude CLI not found. Please ensure 'claude' is installed and in PATH"
            )

    def execute_code_cli(self, prompt: str, cwd: str, model: str = None) -> Dict[str, any]:
        """Execute Claude Code via CLI and capture the response.

        Args:
            prompt: The prompt to send to Claude.
            cwd: Working directory to execute in.
            model: Optional model to use (e.g., 'opus-4.1', 'sonnet-3.7').
        """
        try:
            # Save the current directory
            original_cwd = os.getcwd()

            # Change to the working directory
            os.chdir(cwd)

            # Build command with optional model parameter
            cmd = ["claude", "--dangerously-skip-permissions"]
            if model:
                cmd.extend(["--model", model])

            # DEBUG: Log command and prompt details
            print(f"\n{'='*60}")
            print(f"DEBUG: Executing Claude Code")
            print(f"Command: {' '.join(cmd)}")
            print(f"Working Directory: {cwd}")
            print(f"Prompt length: {len(prompt)} characters")
            print(f"Prompt preview (first 500 chars):\n{prompt[:500]}")
            print(f"{'='*60}\n")

            # Execute claude command with the prompt via stdin
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=600,  # 10 minute timeout
            )

            # DEBUG: Log result
            print(f"\n{'='*60}")
            print(f"DEBUG: Claude Code Execution Result")
            print(f"Return code: {result.returncode}")
            print(f"Stdout length: {len(result.stdout)} characters")
            print(f"Stderr length: {len(result.stderr)} characters")
            if result.stdout:
                print(f"Stdout preview (first 500 chars):\n{result.stdout[:500]}")
            if result.stderr:
                print(f"Stderr preview (first 500 chars):\n{result.stderr[:500]}")
            print(f"{'='*60}\n")

            # Restore original directory
            os.chdir(original_cwd)

            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }

        except subprocess.TimeoutExpired:
            # Try to restore directory, but don't fail if it doesn't exist
            try:
                os.chdir(original_cwd)
            except:
                pass
            return {
                "success": False,
                "stdout": "",
                "stderr": "Command timed out after 10 minutes",
                "returncode": -1,
            }
        except Exception as e:
            # Try to restore directory, but don't fail if it doesn't exist
            try:
                os.chdir(original_cwd)
            except:
                pass
            return {
                "success": False,
                "stdout": "",
                "stderr": str(e),
                "returncode": -1,
            }

    def extract_file_changes(self, response: str) -> List[Dict[str, str]]:
        """Extract file changes from Claude's response."""
        # This will be implemented by patch_extractor.py
        # For now, return empty list
        return []