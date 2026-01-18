import re
import os
import subprocess
from typing import List, Dict, Optional, Tuple
from unidiff import PatchSet
import tempfile
import difflib

class PatchExtractor:
    """Extract patches from Claude Code's responses and file changes."""
    
    def __init__(self):
        self.file_edit_pattern = re.compile(
            r"(?:Creating|Editing|Modifying|Writing to) file: (.*?)$",
            re.MULTILINE
        )
        self.diff_pattern = re.compile(
            r"```diff\n(.*?)```",
            re.DOTALL
        )
        
    def extract_from_cli_output(self, output: str, repo_path: str, created_files: List[str] = None) -> str:
        """Extract patch from Claude Code CLI output by analyzing git diff.

        Args:
            output: CLI output (for compatibility, not currently used)
            repo_path: Path to the repository
            created_files: List of files that were created (not just modified).
                          These need to be staged with git add -N to appear in diff.
        """
        try:
            # Change to repo directory
            original_cwd = os.getcwd()
            os.chdir(repo_path)

            # Stage created files so they appear in git diff
            # Use "git add -N" (intent to add) to make them show up as new files
            if created_files:
                print(f"  📁 Staging {len(created_files)} created file(s) for diff...")
                for filepath in created_files:
                    add_result = subprocess.run(
                        ["git", "add", "-N", filepath],
                        capture_output=True,
                        text=True
                    )
                    if add_result.returncode == 0:
                        print(f"    ✓ Staged: {filepath}")
                    else:
                        print(f"    ✗ Failed to stage {filepath}: {add_result.stderr}")

            # DEBUG: Check git status before extracting patch
            status_result = subprocess.run(
                ["git", "status", "--short"],
                capture_output=True,
                text=True
            )
            print(f"\n{'='*60}")
            print(f"DEBUG: Git status before patch extraction:")
            print(status_result.stdout if status_result.stdout else "(no changes)")
            print(f"{'='*60}\n")

            # Diff all tracked files (including intent-to-add files)
            result = subprocess.run(
                ["git", "diff", "HEAD", "--no-color", "--no-ext-diff"],
                capture_output=True,
                text=True
            )

            # DEBUG: Log patch extraction result
            print(f"\n{'='*60}")
            print(f"DEBUG: Patch extraction result")
            print(f"Git diff return code: {result.returncode}")
            print(f"Patch length: {len(result.stdout)} characters")
            if result.stdout:
                print(f"Patch preview (first 500 chars):\n{result.stdout[:500]}")
            else:
                print("WARNING: No patch generated (empty diff)")
            print(f"{'='*60}\n")

            os.chdir(original_cwd)

            if result.returncode == 0:
                return result.stdout
            else:
                print(f"Git diff failed: {result.stderr}")
                return ""

        except Exception as e:
            print(f"Error extracting patch: {e}")
            return ""
            
    def extract_from_response(self, response: str) -> List[Dict[str, str]]:
        """Extract file changes from Claude's response text."""
        changes = []
        
        # Look for diff blocks
        diff_matches = self.diff_pattern.findall(response)
        for diff in diff_matches:
            changes.append({
                "type": "diff",
                "content": diff
            })
            
        # Look for file edits mentioned in the response
        file_mentions = self.file_edit_pattern.findall(response)
        for file_path in file_mentions:
            changes.append({
                "type": "file_mention",
                "path": file_path.strip()
            })
            
        return changes
    
    def create_patch_from_changes(self, before_state: Dict[str, str],
                                after_state: Dict[str, str]) -> str:
        """Create a unified diff patch from before/after file states."""
        patch_lines = []

        # Find all files that changed
        all_files = set(before_state.keys()) | set(after_state.keys())

        for file_path in sorted(all_files):
            before_content = before_state.get(file_path, "").splitlines(keepends=True)
            after_content = after_state.get(file_path, "").splitlines(keepends=True)

            if before_content == after_content:
                continue

            diff_output = difflib.unified_diff(
                before_content,
                after_content,
                fromfile=f"a/{file_path}",
                tofile=f"b/{file_path}",
            )

            patch_lines.extend(diff_output)

        return "".join(patch_lines)
    
    def validate_patch(self, patch: str) -> Tuple[bool, Optional[str]]:
        """Validate that a patch is well-formed."""
        if not patch or not patch.strip():
            return False, "Empty patch"
            
        try:
            # Try to parse the patch
            patchset = PatchSet(patch)
            
            # Check if patch has any files
            if not patchset:
                return False, "Patch contains no file changes"
                
            # Basic validation passed
            return True, None
            
        except Exception as e:
            return False, f"Invalid patch format: {str(e)}"
            
    def apply_patch_test(self, patch: str, repo_path: str) -> Tuple[bool, str]:
        """Test if a patch can be applied cleanly."""
        try:
            # Save patch to temporary file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.patch', delete=False) as f:
                f.write(patch)
                patch_file = f.name
                
            original_cwd = os.getcwd()
            os.chdir(repo_path)
            
            # Test patch application
            result = subprocess.run(
                ["git", "apply", "--check", patch_file],
                capture_output=True,
                text=True
            )
            
            os.chdir(original_cwd)
            os.unlink(patch_file)
            
            if result.returncode == 0:
                return True, "Patch can be applied cleanly"
            else:
                return False, f"Patch application failed: {result.stderr}"
                
        except Exception as e:
            return False, f"Error testing patch: {str(e)}"
            
    def format_for_swebench(self, patch: str, instance_id: str, model_name: str = "claude-code") -> Dict:
        """Format patch for SWE-bench submission."""
        return {
            "instance_id": instance_id,
            "model": model_name,
            "prediction": patch
        }