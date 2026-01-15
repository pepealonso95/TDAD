"""
Simple single-shot interface for Qwen using Ollama.

This follows the same pattern as claude_interface.py - a single call
that gives the model all context and expects a complete solution.
No complex agent loops or iteration management.
"""

import os
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional
import requests
from dotenv import load_dotenv

load_dotenv()


class QwenCodeInterface:
    """Simple interface for Qwen via Ollama - single-shot approach."""

    def __init__(self):
        """Ensure Ollama is running."""
        try:
            subprocess.run(
                ["ollama", "list"],
                capture_output=True, text=True, check=True, timeout=5
            )
            print("✅ Ollama is ready")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            raise RuntimeError(
                "Ollama is not running. Please start with: ollama serve"
            )

    def _gather_repo_context(self, cwd: str, max_files: int = 10) -> str:
        """Gather relevant files from the repo for context."""
        context_parts = []

        # Get directory structure (limited depth)
        try:
            result = subprocess.run(
                ["find", ".", "-type", "f", "-name", "*.py", "-maxdepth", "4"],
                cwd=cwd, capture_output=True, text=True, timeout=10
            )
            py_files = [f for f in result.stdout.strip().split('\n') if f][:50]
            context_parts.append(f"Python files in repo:\n{chr(10).join(py_files[:30])}")
        except:
            pass

        return "\n\n".join(context_parts)

    def _extract_patch_from_response(self, response: str) -> Optional[str]:
        """Extract unified diff patch from model response."""
        # Look for diff blocks
        diff_pattern = r'```(?:diff)?\n(---\s+a/.*?```)'
        matches = re.findall(diff_pattern, response, re.DOTALL)
        if matches:
            return matches[0].rstrip('`').strip()

        # Look for raw diff format
        lines = response.split('\n')
        diff_lines = []
        in_diff = False

        for line in lines:
            if line.startswith('--- a/') or line.startswith('--- '):
                in_diff = True
            if in_diff:
                diff_lines.append(line)
                if line.startswith('+++ ') and len(diff_lines) > 1:
                    # Continue until we hit non-diff content
                    continue
            if in_diff and not (line.startswith('+') or line.startswith('-') or
                               line.startswith('@') or line.startswith(' ') or
                               line.startswith('---') or line.startswith('+++')):
                if diff_lines:
                    break

        if diff_lines:
            return '\n'.join(diff_lines)

        return None

    def _apply_file_changes(self, cwd: str, response: str) -> bool:
        """Parse response for file changes and apply them directly."""
        applied = False

        # Pattern 1: <<<FILE: path>>> format (END FILE marker optional)
        file_pattern1 = r'<<<FILE:\s*([^\s>]+\.py)>>>\s*```(?:python)?\s*\n(.*?)```'
        matches = re.findall(file_pattern1, response, re.DOTALL)

        # Pattern 2: FILE: path followed by code block
        if not matches:
            file_pattern2 = r'FILE:\s*([^\s`\n]+\.py)\s*\n```(?:python)?\n(.*?)```'
            matches = re.findall(file_pattern2, response, re.DOTALL)

        # Pattern 3: **path** or `path` followed by code block
        if not matches:
            file_pattern3 = r'(?:\*\*|`)([^\s*`]+\.py)(?:\*\*|`)\s*(?::|)\s*\n```(?:python)?\n(.*?)```'
            matches = re.findall(file_pattern3, response, re.DOTALL)

        print(f"  📄 Found {len(matches)} file change(s) in response")

        for filepath, content in matches:
            # Clean up filepath
            filepath = filepath.strip().lstrip('./')
            full_path = Path(cwd) / filepath

            print(f"  📝 Attempting to update: {filepath}")

            if full_path.exists():
                try:
                    with open(full_path, 'w') as f:
                        f.write(content.strip() + '\n')
                    print(f"  ✅ Updated: {filepath}")
                    applied = True
                except Exception as e:
                    print(f"  ❌ Failed to update {filepath}: {e}")
            else:
                print(f"  ⚠️ File not found: {filepath}")

        return applied

    def execute_code_cli(self, prompt: str, cwd: str, model: str = None, tdd_mode: bool = False) -> Dict[str, any]:
        """Execute single-shot Qwen call via Ollama.

        Args:
            prompt: The SWE-bench prompt with issue description
            cwd: Working directory (cloned repo)
            model: Optional model override (default: qwen3-coder:30b)
            tdd_mode: If True, use TDD-focused prompt engineering
        """
        model = model or "qwen3-coder:30b"

        # Gather repo context
        print(f"\n{'='*60}")
        print(f"DEBUG: Single-shot Qwen execution via Ollama")
        print(f"Model: {model}")
        print(f"Working Directory: {cwd}")
        print(f"TDD Mode: {tdd_mode}")
        print(f"Prompt length: {len(prompt)} characters")
        print(f"{'='*60}\n")

        repo_context = self._gather_repo_context(cwd)

        # Build prompt based on mode
        if tdd_mode:
            # TDD-focused prompt: test first, then implementation
            full_prompt = f"""{prompt}

YOU MUST FIX THIS BUG USING TEST-DRIVEN DEVELOPMENT (TDD).

Follow this STRICT order:

## STEP 1: WRITE TEST FIRST
First, output a test file that:
- Reproduces the bug (test should FAIL before your fix)
- Verifies the fix works (test should PASS after your fix)
- Uses the repository's existing test patterns

<<<FILE: tests/test_bugfix.py>>>
```python
# Test case that proves the bug exists and verifies the fix
# Import from the module being fixed
# Write specific test methods for the issue
```
<<<END FILE>>>

## STEP 2: IMPLEMENT THE FIX
Then, output the COMPLETE fixed implementation file(s):

<<<FILE: path/to/file.py>>>
```python
# The COMPLETE file content with the bug fix
# Include ALL imports, ALL classes, ALL functions
```
<<<END FILE>>>

## TDD RULES:
- Output test file FIRST, implementation SECOND
- Test must specifically target the bug described in the issue
- Implementation should be minimal - just enough to make tests pass
- Include COMPLETE files, not snippets
- Use the exact <<<FILE:>>> markers

## IMPORTANT:
- The test file path should match the repo's test directory structure
- Look for existing test files to understand naming conventions
- Your test should fail on the original code, pass on the fixed code

START WITH THE TEST FILE. NO EXPLANATIONS."""
        else:
            # Standard prompt: just fix the bug
            full_prompt = f"""{prompt}

YOU MUST FIX THIS BUG. Output the COMPLETE fixed file(s).

CRITICAL: Use this EXACT format for EACH file you change:

<<<FILE: path/to/file.py>>>
```python
# The COMPLETE file content goes here
# Include ALL imports, ALL classes, ALL functions
# This replaces the entire file
```
<<<END FILE>>>

RULES:
- Output ONLY code, no explanations
- Include the COMPLETE file, not snippets
- Use the exact <<<FILE:>>> and <<<END FILE>>> markers
- The path must be relative to repo root (e.g., astropy/modeling/separable.py)

START YOUR RESPONSE WITH THE FILE MARKER. DO NOT EXPLAIN."""

        try:
            # Single API call to Ollama
            print("📡 Calling Ollama API (this may take a few minutes)...")

            response = requests.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": model,
                    "prompt": full_prompt,
                    "stream": False,
                    "options": {
                        "num_ctx": 262144,  # 256K context
                        "temperature": 0.1,
                        "num_predict": 8192,  # Allow long responses
                    }
                },
                timeout=600  # 10 minute timeout
            )
            response.raise_for_status()

            result = response.json()
            model_response = result.get("response", "")

            print(f"\n{'='*60}")
            print(f"DEBUG: Ollama Response")
            print(f"Response length: {len(model_response)} characters")
            print(f"Preview (first 500 chars):\n{model_response[:500]}")
            print(f"{'='*60}\n")

            # Try to apply changes from response
            changes_applied = self._apply_file_changes(cwd, model_response)

            # Also try patch extraction as fallback
            if not changes_applied:
                patch = self._extract_patch_from_response(model_response)
                if patch:
                    print("Found patch in response, attempting to apply...")
                    try:
                        subprocess.run(
                            ["git", "apply", "--verbose"],
                            input=patch,
                            cwd=cwd,
                            capture_output=True,
                            text=True,
                            check=True
                        )
                        changes_applied = True
                        print("  ✅ Patch applied successfully")
                    except subprocess.CalledProcessError as e:
                        print(f"  ⚠️ Patch failed to apply: {e.stderr}")

            return {
                "success": True,
                "stdout": model_response,
                "stderr": "",
                "returncode": 0,
                "changes_applied": changes_applied
            }

        except requests.exceptions.Timeout:
            return {
                "success": False,
                "stdout": "",
                "stderr": "Ollama API timed out after 10 minutes",
                "returncode": -1,
            }
        except Exception as e:
            print(f"\n{'='*60}")
            print(f"ERROR: Qwen execution failed: {e}")
            print(f"{'='*60}\n")
            return {
                "success": False,
                "stdout": "",
                "stderr": str(e),
                "returncode": -1,
            }

    def extract_file_changes(self, response: str) -> List[Dict[str, str]]:
        """Extract file changes from response (for compatibility)."""
        return []
