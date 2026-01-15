import os
import subprocess
from typing import Dict, List
from dotenv import load_dotenv

load_dotenv()

class CodexCodeInterface:
    """Interface for interacting with GPT-OSS using Codex CLI with Ollama backend."""

    def __init__(self):
        """Ensure Ollama is running and Codex CLI is installed."""
        try:
            # Check if Codex CLI is installed
            try:
                result = subprocess.run([
                    "which", "codex"
                ], capture_output=True, text=True, check=True, timeout=5)
                codex_path = result.stdout.strip()
                print(f"✅ Codex CLI found at: {codex_path}")
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
                raise RuntimeError(
                    "Codex CLI not found. Please install Codex CLI from OpenAI"
                )

            # Check if Ollama is running
            try:
                subprocess.run([
                    "ollama", "list"
                ], capture_output=True, text=True, check=True, timeout=5)
                print("✅ Ollama is ready")
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
                raise RuntimeError(
                    "Ollama is not running. Please start Ollama with: brew services start ollama"
                )

        except FileNotFoundError as e:
            raise RuntimeError(f"Required tool not found: {str(e)}")

    def execute_code_cli(self, prompt: str, cwd: str, model: str = None) -> Dict[str, any]:
        """Execute GPT-OSS using Codex CLI - single call (no iteration).

        Args:
            prompt: The prompt to send to Codex CLI.
            cwd: Working directory to execute in.
            model: Optional model to use (default: gpt-oss:20b).
        """
        try:
            model_name = model if model else "gpt-oss:20b"

            # Construct Codex CLI command
            command = [
                "codex", "exec",
                "--full-auto",  # Enable autonomous mode (non-interactive, allows file edits)
                "--oss",  # Use open source model provider
                "--local-provider", "ollama",  # Explicitly use Ollama as provider
                "-m", model_name,  # Specify model
                "-C", cwd,  # Set working directory
                "--skip-git-repo-check",  # Allow running outside git repo if needed
                prompt  # Pass the prompt
            ]

            # Execute Codex CLI
            print(f"\n{'='*60}")
            print(f"DEBUG: Executing Codex CLI with GPT-OSS/Ollama")
            print(f"Working Directory: {cwd}")
            print(f"Model: {model_name}")
            print(f"Prompt length: {len(prompt)} characters")
            print(f"{'='*60}\n")

            print(f"🚀 Running Codex CLI (single call)...")
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=600  # 10 minute timeout
            )

            # Return result in expected format
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "stdout": "",
                "stderr": "Codex CLI execution timed out after 10 minutes",
                "returncode": -1,
            }
        except Exception as e:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Error executing Codex CLI: {str(e)}",
                "returncode": -1,
            }

    def extract_file_changes(self, response: str) -> List[Dict[str, str]]:
        """Extract file changes from Codex's response (placeholder)."""
        return []
