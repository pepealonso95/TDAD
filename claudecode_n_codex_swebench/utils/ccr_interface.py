"""
Interface for Claude Code Router (CCR) which routes Claude Code requests to local LLMs.
CCR allows using local models like Qwen3 through the Claude Code interface.

Requires:
- npm install -g @musistudio/claude-code-router
- ~/.claude-code-router/config.json configured for Ollama
- Ollama running with qwen3-coder:30b (or configured model)
"""

import os
import subprocess
from typing import Dict, List

class CCRCodeInterface:
    """Interface for interacting with Claude Code via Claude Code Router."""

    def __init__(self):
        """Ensure CCR is available on the system."""
        try:
            result = subprocess.run(
                ["ccr", "-v"],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                raise RuntimeError(
                    "Claude Code Router (CCR) not found. "
                    "Install with: npm install -g @musistudio/claude-code-router"
                )
            print(f"✅ CCR version: {result.stdout.strip()}")
        except FileNotFoundError:
            raise RuntimeError(
                "Claude Code Router (CCR) not found. "
                "Install with: npm install -g @musistudio/claude-code-router"
            )

    def execute_code_cli(self, prompt: str, cwd: str, model: str = None) -> Dict[str, any]:
        """Execute Claude Code via CCR and capture the response.

        Args:
            prompt: The prompt to send to the model.
            cwd: Working directory to execute in.
            model: Optional model override (ignored, uses CCR config).
        """
        try:
            # Save the current directory
            original_cwd = os.getcwd()

            # Change to the working directory
            os.chdir(cwd)

            # Build command - CCR handles model routing via config
            # Use --print and pass prompt via stdin (required by CCR)
            cmd = ["ccr", "code", "--print"]

            # DEBUG: Log command and prompt details
            print(f"\n{'='*60}")
            print(f"DEBUG: Executing via Claude Code Router")
            print(f"Command: ccr code --print (prompt via stdin)")
            print(f"Working Directory: {cwd}")
            print(f"Prompt length: {len(prompt)} characters")
            print(f"Prompt preview (first 500 chars):\n{prompt[:500]}")
            print(f"{'='*60}\n")

            # Execute CCR command with prompt via stdin
            result = subprocess.run(
                cmd,
                input=prompt,  # Pass prompt via stdin
                capture_output=True,
                text=True,
                timeout=600,  # 10 minute timeout
            )

            # DEBUG: Log result
            print(f"\n{'='*60}")
            print(f"DEBUG: CCR Execution Result")
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
            try:
                os.chdir(original_cwd)
            except Exception:
                pass
            return {
                "success": False,
                "stdout": "",
                "stderr": "Command timed out after 10 minutes",
                "returncode": -1,
            }
        except Exception as e:
            try:
                os.chdir(original_cwd)
            except Exception:
                pass
            return {
                "success": False,
                "stdout": "",
                "stderr": str(e),
                "returncode": -1,
            }

    def extract_file_changes(self, response: str) -> List[Dict[str, str]]:
        """Extract file changes from response."""
        # This will be implemented by patch_extractor.py
        return []
