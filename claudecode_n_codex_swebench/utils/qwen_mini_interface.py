#!/usr/bin/env python3
"""QwenMiniInterface: Adapter for mini-swe-agent with Ollama + GraphRAG integration.

Uses mini-swe-agent's battle-tested default templates (74% SWE-bench Verified)
with local Qwen 30B via Ollama.
"""

import os
import sys
import time
import tempfile
import subprocess
import shutil
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

# Add mini-swe-agent to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "mini_swe_agent_fork" / "src"))

from minisweagent.models import get_model
from minisweagent.environments import get_environment
from minisweagent.agents.default import DefaultAgent

# --------------------------------------------------------------------------- #
# Mini-swe-agent default templates (from config/default.yaml)                  #
# These scored 74% on SWE-bench Verified — do NOT simplify them.              #
# --------------------------------------------------------------------------- #

SYSTEM_TEMPLATE = """\
You are a helpful assistant that can interact with a computer.

Your response must contain exactly ONE bash code block with ONE command (or commands connected with && or ||).
Include a THOUGHT section before your command where you explain your reasoning process.
Format your response as shown in <format_example>.

<format_example>
Your reasoning and analysis here. Explain why you want to perform the action.

```bash
your_command_here
```
</format_example>

Failure to follow these rules will cause your response to be rejected.
"""

INSTANCE_TEMPLATE = """\
Please solve this issue: {{task}}

You can execute bash commands and edit files to implement the necessary changes.

## Quality Requirements (Critical)

1. Minimal Scope: ONLY modify files directly related to the failing behavior.
2. No Public API Changes: Avoid changing public function or class signatures.
3. Test First: Reproduce the issue before editing code.
4. Targeted Fixes: Prefer the smallest change that resolves the issue.
5. No Repetition: If an edit command fails repeatedly, switch strategy.
6. Self-Check Before Submit:
   - No accidental signature changes
   - No duplicated code blocks
   - No placeholder/incomplete code

## Recommended Workflow

This workflows should be done step-by-step so that you can iterate on your changes and any possible problems.

1. Analyze the codebase by finding and reading relevant files
2. Create a script to reproduce the issue
3. Edit the source code to resolve the issue
4. Verify your fix works by running your script again
5. Test edge cases to ensure your fix is robust
6. Submit your changes and finish your work by issuing the following command: `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`.
   Do not combine it with any other command. <important>After this command, you cannot continue working on this task.</important>

## Important Rules

1. Every response must contain exactly one action
2. The action must be enclosed in triple backticks
3. Directory or environment variable changes are not persistent. Every action is executed in a new subshell.
   However, you can prefix any action with `MY_ENV_VAR=MY_VALUE cd /path/to/working/dir && ...` or write/load environment variables from files

<system_information>
{{system}} {{release}} {{version}} {{machine}}
</system_information>

## Formatting your response

Here is an example of a correct response:

<example_response>
THOUGHT: I need to understand the structure of the repository first. Let me check what files are in the current directory to get a better understanding of the codebase.

```bash
ls -la
```
</example_response>

## Useful command examples

### Create a new file:

```bash
cat <<'EOF' > newfile.py
import numpy as np
hello = "world"
print(hello)
EOF
```

### Edit files with python (PREFERRED method):

```bash
python3 -c "
import pathlib
p = pathlib.Path('filename.py')
content = p.read_text()
content = content.replace('old_string', 'new_string')
p.write_text(content)
print('Done')
"
```

### Delete a specific line by number:

```bash
python3 -c "
import pathlib
p = pathlib.Path('filename.py')
lines = p.read_text().splitlines(keepends=True)
del lines[LINE_NUMBER - 1]  # 1-indexed
p.write_text(''.join(lines))
print('Done')
"
```

### Edit files with sed:

{% if system == "Darwin" -%}
<important>
You are on MacOS. You MUST use `sed -i '' 's/...'` (with a space between -i and '').
Using `sed -i's/...'` or `sed -i 's/...'` WITHOUT the space WILL FAIL.
</important>

```bash
# Replace all occurrences (MacOS syntax - note the space after -i)
sed -i '' 's/old_string/new_string/g' filename.py

# Delete line 253
sed -i '' '253d' filename.py
```
{% else -%}
```bash
sed -i 's/old_string/new_string/g' filename.py
```
{% endif -%}

### View file content:

```bash
# View specific lines with numbers
nl -ba filename.py | sed -n '10,20p'
```

### Any other command you want to run

```bash
anything
```
"""

ACTION_OBSERVATION_TEMPLATE = """\
<returncode>{{output.returncode}}</returncode>
{% if output.output | length < 10000 -%}
<output>
{{ output.output -}}
</output>
{%- else -%}
<warning>
The output of your last command was too long.
Please try a different command that produces less output.
If you're looking at a file you can try use head, tail or sed to view a smaller number of lines selectively.
If you're using grep or find and it produced too much output, you can use a more selective search pattern.
If you really need to see something from the full command's output, you can redirect output to a file and then search in that file.
</warning>
{%- set elided_chars = output.output | length - 10000 -%}
<output_head>
{{ output.output[:5000] }}
</output_head>
<elided_chars>
{{ elided_chars }} characters elided
</elided_chars>
<output_tail>
{{ output.output[-5000:] }}
</output_tail>
{%- endif -%}
"""

FORMAT_ERROR_TEMPLATE = """\
Please always provide EXACTLY ONE action in triple backticks, found {{actions|length}} actions.
If you want to end the task, please issue the following command: `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`
without any other command.
Else, please format your response exactly as follows:

<response_example>
Here are some thoughts about why you want to perform the action.

```bash
<action>
```
</response_example>

Note: In rare cases, if you need to reference a similar format in your command, you might have
to proceed in two steps, first writing TRIPLEBACKTICKSBASH, then replacing them with ```bash.
"""

TIMEOUT_TEMPLATE = """\
The last command <command>{{action['action']}}</command> timed out and has been killed.
The output of the command was:
{% if output | length < 10000 -%}
<output>
{{output}}
</output>
{%- else -%}
<warning>Output was too long and has been truncated.</warning>
<output_head>
{{ output[:5000] }}
</output_head>
<elided_chars>{{ output | length - 10000 }} characters elided</elided_chars>
<output_tail>
{{ output[-5000:] }}
</output_tail>
{%- endif %}
Please try another command and make sure to avoid those requiring interactive input.
"""

# Environment variables to prevent interactive hangs and noisy output
DEFAULT_ENV_VARS = {
    "PAGER": "cat",
    "MANPAGER": "cat",
    "LESS": "-R",
    "PIP_PROGRESS_BAR": "off",
    "TQDM_DISABLE": "1",
}


class QwenMiniInterface:
    """Adapter for mini-swe-agent with Ollama + GraphRAG integration."""

    def __init__(self):
        self.step_limit = 100
        self.cost_limit = 0  # Free local Ollama
        os.environ["MSWEA_COST_TRACKING"] = "ignore_errors"

    # ------------------------------------------------------------------ #
    # Main entry point                                                    #
    # ------------------------------------------------------------------ #

    def execute_code_cli(
        self,
        instance_id: str,
        problem_statement: str,
        repo: str,
        base_commit: str,
        hints_text: str = "",
        tdd_mode: bool = False,
        graphrag_enabled: bool = False,
        graphrag_mcp=None,
    ) -> dict:
        """Run mini-swe-agent on a SWE-bench instance. Returns prediction dict."""
        repo_path = None
        log_lines: list[str] = []

        def log(msg: str):
            ts = datetime.now().strftime("%H:%M:%S")
            line = f"[{ts}] {msg}"
            print(line)
            log_lines.append(line)

        try:
            log(f"=== START {instance_id} ===")
            log(f"Repo: {repo}  Commit: {base_commit[:8]}")

            # 1. Clone repo
            repo_path = self._setup_repository(repo, base_commit, log)
            log(f"Repo cloned to: {repo_path}")

            # 2. Create agent
            agent = self._create_agent(repo_path, tdd_mode)
            log(f"Agent created  step_limit={self.step_limit}")

            # 3. Validate CWD (resolve symlinks — macOS /var -> /private/var)
            cwd_check = agent.env.execute("pwd")
            actual_cwd = Path(cwd_check["output"].strip()).resolve()
            expected_cwd = repo_path.resolve()
            log(f"CWD check: {actual_cwd}")
            if actual_cwd != expected_cwd:
                log(f"CWD MISMATCH! Expected {expected_cwd}, got {actual_cwd}")

            # 4. GraphRAG
            affected_tests = []
            if graphrag_enabled and graphrag_mcp:
                log("Running GraphRAG test impact analysis...")
                try:
                    result = graphrag_mcp.analyze_test_impact(repo_path)
                    affected_tests = result.get("affected_tests", [])
                    log(f"GraphRAG found {len(affected_tests)} affected tests")
                except Exception as e:
                    log(f"GraphRAG failed: {e}")

            # 5. Format task
            task = self._format_task(problem_statement, hints_text, affected_tests, tdd_mode)

            # 6. Attach logging hook
            format_errors = [0]
            timeouts = [0]
            step_counter = [0]

            original_add_message = agent.add_message
            def logging_add_message(role, content="", **kwargs):
                if role == "assistant":
                    step_counter[0] += 1
                    # Show THOUGHT + command (truncated)
                    preview = content[:500] + ("..." if len(content) > 500 else "")
                    log(f"--- Step {step_counter[0]} (model call {agent.model.n_calls}) ---")
                    log(f"AGENT:\n{preview}")
                elif role == "user":
                    # Detect format errors / timeouts
                    if "EXACTLY ONE action" in content:
                        format_errors[0] += 1
                        log(f"  FORMAT_ERROR #{format_errors[0]}")
                    elif "timed out" in content:
                        timeouts[0] += 1
                        log(f"  TIMEOUT #{timeouts[0]}")
                    else:
                        # Show observation (truncated)
                        preview = content[:300] + ("..." if len(content) > 300 else "")
                        log(f"  OBS: {preview}")
                original_add_message(role, content, **kwargs)

            agent.add_message = logging_add_message

            # 7. Run agent
            log("Starting agent run...")
            t0 = time.time()
            status, message = agent.run(task)
            elapsed = time.time() - t0

            log(f"Agent finished: status={status}  elapsed={elapsed:.1f}s  steps={agent.model.n_calls}")
            log(f"Format errors: {format_errors[0]}  Timeouts: {timeouts[0]}")

            # 8. Extract patch
            patch = self._extract_patch(repo_path, log=log)
            log(f"Patch: {len(patch)} chars")
            if patch:
                # Show first 10 lines
                first_lines = "\n".join(patch.splitlines()[:10])
                log(f"Patch preview:\n{first_lines}")

            result = {
                "instance_id": instance_id,
                "prediction": patch,
                "status": status,
                "message": message,
                "steps": agent.model.n_calls,
                "cost": agent.model.cost,
                "elapsed": elapsed,
                "format_errors": format_errors[0],
                "timeouts": timeouts[0],
            }

            log(f"=== END {instance_id} ===")
            self._save_log(instance_id, log_lines)
            return result

        except Exception as e:
            log(f"EXCEPTION: {e}")
            import traceback
            log(traceback.format_exc())
            self._save_log(instance_id, log_lines)
            return {
                "instance_id": instance_id,
                "prediction": "",
                "error": str(e),
                "status": "error",
            }

        finally:
            if repo_path and repo_path.exists():
                try:
                    shutil.rmtree(repo_path.parent, ignore_errors=True)
                except Exception:
                    pass

    # ------------------------------------------------------------------ #
    # Repository setup                                                    #
    # ------------------------------------------------------------------ #

    def _setup_repository(self, repo: str, base_commit: str, log=print) -> Path:
        """Clone repository and checkout base commit."""
        tmpdir = tempfile.mkdtemp(prefix="swe_qwen_")
        repo_path = Path(tmpdir) / "repo"
        repo_url = f"https://github.com/{repo}"

        log(f"Cloning {repo_url}...")
        result = subprocess.run(
            ["git", "clone", "--depth", "1", "--single-branch", repo_url, str(repo_path)],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            log("Shallow clone failed, retrying full clone...")
            subprocess.run(
                ["git", "clone", repo_url, str(repo_path)],
                check=True,
                capture_output=True,
                text=True,
            )

        # Fetch full history so we can checkout base_commit
        subprocess.run(
            ["git", "fetch", "--unshallow"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )

        log(f"Checking out {base_commit[:8]}...")
        subprocess.run(
            ["git", "checkout", base_commit],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True,
        )

        return repo_path

    # ------------------------------------------------------------------ #
    # Agent creation                                                      #
    # ------------------------------------------------------------------ #

    def _create_agent(self, repo_path: Path, tdd_mode: bool = False) -> DefaultAgent:
        """Instantiate mini-swe-agent with Ollama config and default templates."""

        # Model — local Qwen 30B via Ollama
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

        # Environment — MUST use 'cwd' (not 'working_dir')
        env = get_environment(
            config={
                "environment_class": "local",
                "cwd": str(repo_path),
                "env": DEFAULT_ENV_VARS,
            },
            default_type="local",
        )

        # Build instance template — default + optional TDD appendix
        instance_tpl = INSTANCE_TEMPLATE
        if tdd_mode:
            instance_tpl += """
## Additional Requirement: Test-Driven Development

Before fixing the code, you MUST:
1. Write a failing test that reproduces the issue
2. Run it to confirm it fails
3. Then fix the code
4. Re-run the test to confirm it passes

Use existing test frameworks (pytest, unittest) found in the repository.
"""

        agent = DefaultAgent(
            model=model,
            env=env,
            system_template=SYSTEM_TEMPLATE,
            instance_template=instance_tpl,
            action_observation_template=ACTION_OBSERVATION_TEMPLATE,
            format_error_template=FORMAT_ERROR_TEMPLATE,
            timeout_template=TIMEOUT_TEMPLATE,
            step_limit=self.step_limit,
            cost_limit=self.cost_limit,
        )

        return agent

    # ------------------------------------------------------------------ #
    # Task formatting                                                     #
    # ------------------------------------------------------------------ #

    def _format_task(
        self,
        problem_statement: str,
        hints_text: str,
        affected_tests: list = None,
        tdd_mode: bool = False,
    ) -> str:
        """Format SWE-bench instance as agent task prompt."""
        task = problem_statement

        if hints_text:
            task += f"\n\n## Hints\n\n{hints_text}"

        if affected_tests:
            task += "\n\n## Affected Tests (from GraphRAG analysis)\n\nThe following tests are likely affected by this issue:\n"
            for test in affected_tests[:10]:
                task += f"- {test}\n"
            task += "\nConsider these tests when implementing your fix.\n"

        return task

    # ------------------------------------------------------------------ #
    # Patch extraction                                                    #
    # ------------------------------------------------------------------ #

    def _validate_patch_quality(self, repo_path: Path) -> dict:
        """Validate patch quality and return decision metadata."""
        result = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        diff = result.stdout

        fail_reasons = []
        warn_reasons = []

        if not diff.strip():
            fail_reasons.append("empty_diff")

        files_changed = len(re.findall(r"^diff --git ", diff, flags=re.MULTILINE))
        if files_changed > 3:
            fail_reasons.append(f"too_many_files:{files_changed}")

        added_lines = re.findall(r"^\+(?!\+\+\+)(.*)$", diff, flags=re.MULTILINE)
        normalized_added = [line.strip() for line in added_lines if line.strip()]
        repeated_lines = Counter(normalized_added)
        duplicate_line_max_count = max(repeated_lines.values(), default=0)
        if duplicate_line_max_count >= 4:
            fail_reasons.append(f"repetitive_code:max_repeat={duplicate_line_max_count}")

        placeholder_markers = ("TODO", "FIXME", "Placeholder", "NotImplementedError")
        if any(marker in line for line in added_lines for marker in placeholder_markers):
            fail_reasons.append("placeholder_code")

        removed_defs = re.findall(
            r"^-def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*:",
            diff,
            flags=re.MULTILINE,
        )
        added_defs = re.findall(
            r"^\+def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*:",
            diff,
            flags=re.MULTILINE,
        )

        signature_change_detected = False
        removed_map: dict[str, list[str]] = {}
        for name, params in removed_defs:
            removed_map.setdefault(name, []).append("".join(params.split()))
        for name, params in added_defs:
            normalized_params = "".join(params.split())
            previous = removed_map.get(name, [])
            if previous and normalized_params not in previous:
                signature_change_detected = True
                break
        if not signature_change_detected and (removed_defs and not added_defs):
            signature_change_detected = True
        if not signature_change_detected and (added_defs and not removed_defs):
            signature_change_detected = True
        if signature_change_detected:
            warn_reasons.append("potential_signature_change")

        metrics = {
            "files_changed": files_changed,
            "added_lines": len(added_lines),
            "duplicate_line_max_count": duplicate_line_max_count,
            "signature_change_detected": signature_change_detected,
        }

        if fail_reasons:
            return {
                "valid": False,
                "severity": "fail",
                "reason": ",".join(fail_reasons),
                "fail_reasons": fail_reasons,
                "warn_reasons": warn_reasons,
                "metrics": metrics,
                "diff": diff,
            }

        if warn_reasons:
            return {
                "valid": True,
                "severity": "warn",
                "reason": ",".join(warn_reasons),
                "fail_reasons": fail_reasons,
                "warn_reasons": warn_reasons,
                "metrics": metrics,
                "diff": diff,
            }

        return {
            "valid": True,
            "severity": "info",
            "reason": "ok",
            "fail_reasons": fail_reasons,
            "warn_reasons": warn_reasons,
            "metrics": metrics,
            "diff": diff,
        }

    def _extract_patch(self, repo_path: Path, log=print) -> str:
        """Extract git diff with quality-gate validation."""
        validation = self._validate_patch_quality(repo_path)
        log(
            "PATCH_GATE_RESULT "
            f"valid={validation['valid']} "
            f"severity={validation['severity']} "
            f"reason={validation['reason']} "
            f"metrics={validation['metrics']}"
        )

        if not validation["valid"]:
            log("PATCH_GATE_REJECT returning empty patch")
            return ""

        if validation["severity"] == "warn":
            log("PATCH_GATE_WARN accepted patch with warnings")

        return validation["diff"]

    # ------------------------------------------------------------------ #
    # Logging                                                             #
    # ------------------------------------------------------------------ #

    def _save_log(self, instance_id: str, log_lines: list[str]):
        """Write log to logs/{instance_id}.log."""
        log_dir = Path(__file__).parent.parent / "logs"
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / f"{instance_id}.log"
        log_file.write_text("\n".join(log_lines) + "\n")
        print(f"[QwenMini] Log saved to {log_file}")
