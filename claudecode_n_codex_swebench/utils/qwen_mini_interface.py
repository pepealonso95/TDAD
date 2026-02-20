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
from typing import Any, Optional

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

After each command result, briefly reflect on what you learned and whether it moved you closer to solving the issue.
Keep iterating until you have verified the fix works. Do not submit prematurely.

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

## Critical: Working Directory and File Location

<important>
- Your current working directory IS the cloned repository. Use `pwd` to confirm.
- NEVER hardcode paths like `/Users/runner/...` or `/opt/miniconda3/...`.
- NEVER try `python3 -c "import <package>"` — the package is unbuilt source code, not installed.
- To find files: `grep -r "pattern" . --include="*.py" -l`
- To read source: use `cat`, `head`, or `sed -n 'START,ENDp'` directly.
- Start with `ls` and `find . -type f -name "*.py" | head -20`.
</important>

## Recommended Workflow

This workflows should be done step-by-step so that you can iterate on your changes and any possible problems.

1. Run pwd and ls to orient yourself. Use grep -r "keyword" . --include="*.py" -l to find relevant files. NEVER import the package.
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

## Common Pitfalls

- NEVER import the package (`python3 -c "import ..."`) — it is unbuilt source. Use cat/grep.
- NEVER search in /opt/, /usr/lib/, or site-packages/ — the code is in the current directory.
- If a command fails, try a DIFFERENT approach instead of repeating it.

## Editing Files

Use `python3 -c "import pathlib; p = pathlib.Path('file.py'); c = p.read_text(); c = c.replace('old', 'new'); p.write_text(c); print('Done')"` for edits.
{% if system == "Darwin" -%}
For sed on MacOS: `sed -i '' 's/old/new/g' file.py` (note space after -i).
{% else -%}
For sed: `sed -i 's/old/new/g' file.py`
{% endif -%}
View lines: `nl -ba file.py | sed -n '10,20p'`
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
{%- endif %}
<step>{{n_model_calls}}/{{step_limit}}</step>{% if n_model_calls >= step_limit - 5 %} <warning>You are almost out of steps. Submit now with: echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT</warning>{% endif %}
<reminder>When done, submit with ONLY this command (no other commands): echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT</reminder>
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


class LoopAbortError(RuntimeError):
    """Raised when strict loop controls detect a stuck trajectory."""


class QwenMiniInterface:
    """Adapter for mini-swe-agent with Ollama + GraphRAG integration."""

    def __init__(self):
        # Vanilla defaults
        self.step_limit = 30
        self.max_attempts = 3
        self.max_fix_iterations = 0
        self.loop_policy = "strict"  # off | warn | strict
        self.search_streak_limit = 8
        self.no_diff_streak_limit = 8
        self.repeated_fail_limit = 3
        self.sed_fail_limit = 2
        self.p2p_smoke_count = 10
        self.pytest_timeout = 180
        self.patch_compile_gate = True
        self.max_compile_fix_iterations = 2
        self.max_changed_lines = 200
        self.cost_limit = 0  # Free local Ollama
        self._last_patch_gate_decision: dict[str, Any] = {}
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
        fail_to_pass_tests: Optional[list[str]] = None,
        pass_to_pass_tests: Optional[list[str]] = None,
    ) -> dict:
        """Run mini-swe-agent on a SWE-bench instance. Returns prediction dict."""
        fail_to_pass_tests = fail_to_pass_tests or []
        pass_to_pass_tests = pass_to_pass_tests or []
        all_logs: list[str] = []
        attempt_summaries: list[dict[str, Any]] = []
        best_candidate: Optional[dict[str, Any]] = None
        best_score: Optional[tuple] = None

        for attempt_idx in range(1, self.max_attempts + 1):
            repo_path = None
            attempt_logs: list[str] = []

            def log(msg: str):
                ts = datetime.now().strftime("%H:%M:%S")
                line = f"[{ts}] [attempt {attempt_idx}/{self.max_attempts}] {msg}"
                print(line)
                attempt_logs.append(line)
                all_logs.append(line)

            graphrag_meta = {
                "graph_built": False,
                "graph_nodes": 0,
                "graph_rels": 0,
                "impacted_total": 0,
                "impacted_run": 0,
                "impacted_failed": 0,
                "impacted_failed_tests": [],
            }

            try:
                log(f"=== START {instance_id} ===")
                log(f"Repo: {repo}  Commit: {base_commit[:8]}")
                repo_path = self._setup_repository(repo, base_commit, log)
                log(f"Repo cloned to: {repo_path}")

                if graphrag_enabled and graphrag_mcp:
                    try:
                        log("Building GraphRAG index...")
                        graph_result = graphrag_mcp.build_graph(str(repo_path), force_rebuild=False, include_tests=True)
                        graphrag_meta["graph_built"] = bool(graph_result.get("success"))
                        graphrag_meta["graph_nodes"] = int(graph_result.get("nodes_created", 0))
                        graphrag_meta["graph_rels"] = int(graph_result.get("relationships_created", 0))
                        log(
                            "GraphRAG build "
                            f"success={graph_result.get('success')} "
                            f"nodes={graphrag_meta['graph_nodes']} rels={graphrag_meta['graph_rels']}"
                        )
                    except Exception as e:
                        log(f"GraphRAG build failed: {e}")

                prev_attempt = attempt_summaries[-1] if attempt_summaries else None
                task = self._format_retry_task(
                    problem_statement=problem_statement,
                    hints_text=hints_text,
                    tdd_mode=tdd_mode,
                    attempt_idx=attempt_idx,
                    prev_attempt=prev_attempt,
                )
                fix_round = 0
                max_fix_rounds = self.max_fix_iterations if (tdd_mode or graphrag_enabled) else 0
                compile_fix_round = 0
                max_compile_fix_rounds = self.max_compile_fix_iterations if self.patch_compile_gate else 0

                run_result: dict[str, Any] = {}
                patch = ""
                test_metrics: dict[str, Any] = {}
                last_patch_gate: dict[str, Any] = {}

                while True:
                    agent = self._create_agent(repo_path, tdd_mode)
                    run_result = self._run_agent_with_controls(agent, task, repo_path, log)
                    patch = self._extract_patch(repo_path, log=log)
                    last_patch_gate = dict(self._last_patch_gate_decision)
                    log(f"Patch: {len(patch)} chars")
                    compile_gate = last_patch_gate.get("compile_gate", {})
                    compile_failed = int(compile_gate.get("compile_failed", 0) or 0)

                    if compile_failed > 0:
                        if compile_fix_round < max_compile_fix_rounds:
                            compile_fix_round += 1
                            task = self._format_compile_failure_task(
                                problem_statement,
                                hints_text,
                                compile_gate,
                            )
                            log(
                                f"Continuing with compile-repair round "
                                f"{compile_fix_round}/{max_compile_fix_rounds}"
                            )
                            continue
                        log(
                            f"Compile-repair rounds exhausted "
                            f"({compile_fix_round}/{max_compile_fix_rounds})"
                        )

                    require_test_checks = bool(tdd_mode or graphrag_enabled)
                    test_metrics = self._evaluate_candidate(
                        repo_path,
                        fail_to_pass_tests,
                        pass_to_pass_tests,
                        require_test_checks=require_test_checks,
                        log=log,
                    )

                    if graphrag_enabled and graphrag_mcp and patch:
                        try:
                            changed_files = self._get_changed_files(repo_path)
                            if changed_files:
                                impacted = graphrag_mcp.run_impacted_tests_iteratively(
                                    repo_path=str(repo_path),
                                    changed_files=changed_files,
                                    impact_threshold=0.3,
                                    max_tests=50,
                                )
                                graphrag_meta["impacted_total"] = int(impacted.get("total_impacted", 0))
                                graphrag_meta["impacted_run"] = int(impacted.get("tests_run", 0))
                                graphrag_meta["impacted_failed"] = int(impacted.get("failed", 0))
                                graphrag_meta["impacted_failed_tests"] = impacted.get("failed_tests", [])
                                log(
                                    "GraphRAG iterative tests: "
                                    f"run={graphrag_meta['impacted_run']} failed={graphrag_meta['impacted_failed']}"
                                )

                                if graphrag_meta["impacted_failed"] > 0 and fix_round < max_fix_rounds:
                                    fix_round += 1
                                    task = self._format_graphrag_failure_task(
                                        problem_statement,
                                        hints_text,
                                        graphrag_meta["impacted_failed_tests"],
                                    )
                                    log(f"Continuing with GraphRAG repair round {fix_round}/{max_fix_rounds}")
                                    continue
                        except Exception as e:
                            log(f"GraphRAG impacted test loop failed: {e}")

                    if (
                        require_test_checks
                        and fix_round < max_fix_rounds
                        and test_metrics.get("f2p_total", 0) > 0
                        and not test_metrics.get("f2p_all_passed", False)
                    ):
                        fix_round += 1
                        task = self._format_test_failure_task(
                            problem_statement,
                            hints_text,
                            test_metrics,
                        )
                        log(f"Continuing with test-fix round {fix_round}/{max_fix_rounds}")
                        continue

                    break

                candidate = {
                    "attempt": attempt_idx,
                    "prediction": patch,
                    "status": run_result.get("status", "unknown"),
                    "message": run_result.get("message", ""),
                    "steps": run_result.get("steps", 0),
                    "cost": run_result.get("cost", 0.0),
                    "elapsed": run_result.get("elapsed", 0.0),
                    "format_errors": run_result.get("format_errors", 0),
                    "timeouts": run_result.get("timeouts", 0),
                    "loop_abort_reason": run_result.get("loop_abort_reason", ""),
                    "f2p_pass_rate": test_metrics.get("f2p_pass_rate"),
                    "p2p_smoke_failures": test_metrics.get("p2p_smoke_failures"),
                    "clean_resolution": test_metrics.get("clean_resolution"),
                    "patch_gate_valid": bool(last_patch_gate.get("valid", False)),
                    "patch_gate_reason": str(last_patch_gate.get("reason", "")),
                    "patch_gate_severity": str(last_patch_gate.get("severity", "")),
                    "compile_fix_rounds": compile_fix_round,
                    "graphrag_metadata": graphrag_meta,
                }
                attempt_summaries.append({
                    "attempt": candidate["attempt"],
                    "status": candidate["status"],
                    "patch_chars": len(candidate["prediction"]),
                    "steps": candidate["steps"],
                    "loop_abort_reason": candidate["loop_abort_reason"],
                    "f2p_pass_rate": candidate["f2p_pass_rate"],
                    "p2p_smoke_failures": candidate["p2p_smoke_failures"],
                    "clean_resolution": candidate["clean_resolution"],
                    "patch_gate_valid": candidate["patch_gate_valid"],
                    "patch_gate_reason": candidate["patch_gate_reason"],
                    "patch_gate_severity": candidate["patch_gate_severity"],
                    "compile_fix_rounds": candidate["compile_fix_rounds"],
                })

                score = self._score_candidate(candidate)
                if best_score is None or score > best_score:
                    best_score = score
                    best_candidate = candidate
                    log(f"New best candidate selected with score={score}")

                if candidate.get("clean_resolution") is True and len(candidate["prediction"]) > 0:
                    log("Early stop: clean candidate found.")
                    break

                compile_valid_submitted = (
                    candidate.get("status") == "Submitted"
                    and len(candidate.get("prediction", "")) > 0
                    and bool(candidate.get("patch_gate_valid"))
                    and "syntax_compile_failed" not in str(candidate.get("patch_gate_reason", ""))
                )
                if compile_valid_submitted:
                    log("Early stop: compile-valid submitted patch found.")
                    break

            except Exception as e:
                log(f"EXCEPTION: {e}")
                import traceback
                log(traceback.format_exc())
            finally:
                if repo_path and repo_path.exists():
                    try:
                        shutil.rmtree(repo_path.parent, ignore_errors=True)
                    except Exception:
                        pass

        self._save_log(instance_id, all_logs)

        if not best_candidate:
            return {
                "instance_id": instance_id,
                "prediction": "",
                "error": "No successful attempt",
                "status": "error",
                "attempts_used": len(attempt_summaries),
                "patch_gate_valid": False,
                "patch_gate_reason": "no_attempt_completed",
                "patch_gate_severity": "fail",
                "attempt_summaries": attempt_summaries,
            }

        return {
            "instance_id": instance_id,
            "prediction": best_candidate.get("prediction", ""),
            "status": best_candidate.get("status", "unknown"),
            "message": best_candidate.get("message", ""),
            "steps": best_candidate.get("steps", 0),
            "cost": best_candidate.get("cost", 0.0),
            "elapsed": best_candidate.get("elapsed", 0.0),
            "format_errors": best_candidate.get("format_errors", 0),
            "timeouts": best_candidate.get("timeouts", 0),
            "attempts_used": len(attempt_summaries),
            "loop_abort_reason": best_candidate.get("loop_abort_reason", ""),
            "f2p_pass_rate": best_candidate.get("f2p_pass_rate"),
            "p2p_smoke_failures": best_candidate.get("p2p_smoke_failures"),
            "clean_resolution": best_candidate.get("clean_resolution"),
            "patch_gate_valid": best_candidate.get("patch_gate_valid"),
            "patch_gate_reason": best_candidate.get("patch_gate_reason"),
            "patch_gate_severity": best_candidate.get("patch_gate_severity"),
            "compile_fix_rounds": best_candidate.get("compile_fix_rounds", 0),
            "attempt_summaries": attempt_summaries,
            "graphrag_metadata": best_candidate.get("graphrag_metadata", {}),
        }

    def _run_agent_with_controls(self, agent: DefaultAgent, task: str, repo_path: Path, log=print) -> dict[str, Any]:
        """Run a single agent task with hard loop controls."""
        format_errors = [0]
        timeouts = [0]
        command_history: list[str] = []
        last_cmd = [""]
        loop_abort_reason = [""]
        diff_state = {
            "prev_sig": self._compute_diff_signature(repo_path),
            "seen_nonempty": False,
            "no_diff_streak": 0,
            "search_streak": 0,
            "failed_cmd_streak": 0,
            "failed_cmd_norm": "",
            "sed_fail_streak": 0,
        }
        max_retries = 2

        original_add_message = agent.add_message

        def logging_add_message(role, content="", **kwargs):
            if role == "assistant":
                preview = content[:500] + ("..." if len(content) > 500 else "")
                log(f"--- Step {agent.model.n_calls} ---")
                log(f"AGENT:\n{preview}")
                cmds = re.findall(r"```bash\s*\n(.*?)\n```", content, re.DOTALL)
                if cmds:
                    cmd = cmds[0].strip()
                    last_cmd[0] = cmd
                    command_history.append(cmd)

            elif role == "user":
                if "EXACTLY ONE action" in content:
                    format_errors[0] += 1
                    log(f"  FORMAT_ERROR #{format_errors[0]}")
                elif "timed out" in content:
                    timeouts[0] += 1
                    log(f"  TIMEOUT #{timeouts[0]}")
                else:
                    preview = content[:300] + ("..." if len(content) > 300 else "")
                    log(f"  OBS: {preview}")

                if self.loop_policy == "off":
                    original_add_message(role, content, **kwargs)
                    return

                rc = self._extract_return_code(content)
                cmd = last_cmd[0]
                cmd_norm = self._normalize_command(cmd)
                base_cmd = cmd.split()[0] if cmd.split() else ""
                loop_warnings: list[str] = []
                abort_reason = ""

                if rc != 0 and cmd_norm:
                    if diff_state["failed_cmd_norm"] == cmd_norm:
                        diff_state["failed_cmd_streak"] += 1
                    else:
                        diff_state["failed_cmd_norm"] = cmd_norm
                        diff_state["failed_cmd_streak"] = 1
                    if diff_state["failed_cmd_streak"] >= self.repeated_fail_limit:
                        abort_reason = (
                            f"repeated_failing_command:{base_cmd} x{diff_state['failed_cmd_streak']}"
                        )
                else:
                    diff_state["failed_cmd_norm"] = ""
                    diff_state["failed_cmd_streak"] = 0

                if base_cmd in {"find", "grep", "rg", "ls"}:
                    diff_state["search_streak"] += 1
                else:
                    diff_state["search_streak"] = 0
                if diff_state["search_streak"] >= self.search_streak_limit and not abort_reason:
                    abort_reason = f"search_only_streak:{diff_state['search_streak']}"

                if "sed -i" in cmd and rc != 0:
                    diff_state["sed_fail_streak"] += 1
                    if "sed -i ''" not in cmd and sys.platform == "darwin":
                        loop_warnings.append(
                            "<warning>macOS sed requires `sed -i '' ...`. "
                            "Prefer python-based edits if sed keeps failing.</warning>"
                        )
                    if diff_state["sed_fail_streak"] >= self.sed_fail_limit and not abort_reason:
                        abort_reason = f"sed_fail_streak:{diff_state['sed_fail_streak']}"
                else:
                    diff_state["sed_fail_streak"] = 0

                current_sig = self._compute_diff_signature(repo_path)
                if current_sig != "EMPTY":
                    diff_state["seen_nonempty"] = True

                if diff_state["seen_nonempty"]:
                    if current_sig == diff_state["prev_sig"]:
                        diff_state["no_diff_streak"] += 1
                    else:
                        diff_state["no_diff_streak"] = 0
                    if diff_state["no_diff_streak"] >= self.no_diff_streak_limit and not abort_reason:
                        abort_reason = f"no_diff_streak:{diff_state['no_diff_streak']}"
                diff_state["prev_sig"] = current_sig

                import_cmds = [
                    c for c in command_history[-3:]
                    if "python3 -c" in c and "import " in c
                ]
                if len(import_cmds) >= 2:
                    loop_warnings.append(
                        "<warning>STOP importing package modules. Use source files directly (`cat`, `grep`, `nl`).</warning>"
                    )

                if abort_reason:
                    loop_abort_reason[0] = abort_reason
                    loop_warnings.append(
                        "<warning>Trajectory aborted due to repeated low-signal behavior. "
                        "Submit and restart with a different strategy.</warning>"
                    )

                if loop_warnings:
                    warning_text = "\n".join(loop_warnings)
                    content = warning_text + "\n" + content
                    log(f"  LOOP_WARNING injected: {warning_text[:220]}")

            original_add_message(role, content, **kwargs)

            if role == "user" and loop_abort_reason[0] and self.loop_policy == "strict":
                raise LoopAbortError(loop_abort_reason[0])

        agent.add_message = logging_add_message

        status = "error"
        message = ""
        t0 = time.time()
        for attempt in range(max_retries + 1):
            try:
                status, message = agent.run(task)
                break
            except LoopAbortError as e:
                status = "LoopAborted"
                message = str(e)
                break
            except (ConnectionError, OSError) as e:
                if attempt < max_retries:
                    log(f"Ollama connection error (attempt {attempt + 1}/{max_retries + 1}): {e}")
                    log("Waiting 30s before retry...")
                    time.sleep(30)
                else:
                    raise
        elapsed = time.time() - t0

        log(f"Agent finished: status={status}  elapsed={elapsed:.1f}s  steps={agent.model.n_calls}")
        log(f"Format errors: {format_errors[0]}  Timeouts: {timeouts[0]}")
        if loop_abort_reason[0]:
            log(f"Loop abort reason: {loop_abort_reason[0]}")

        return {
            "status": status,
            "message": message,
            "steps": agent.model.n_calls,
            "cost": agent.model.cost,
            "elapsed": elapsed,
            "format_errors": format_errors[0],
            "timeouts": timeouts[0],
            "loop_abort_reason": loop_abort_reason[0],
        }

    def _extract_return_code(self, observation: str) -> int:
        m = re.search(r"<returncode>(-?\d+)</returncode>", observation)
        if not m:
            return 0
        try:
            return int(m.group(1))
        except ValueError:
            return 0

    def _normalize_command(self, command: str) -> str:
        if not command:
            return ""
        norm = " ".join(command.strip().split())
        norm = re.sub(r"\b\d+\b", "<N>", norm)
        return norm[:400]

    def _compute_diff_signature(self, repo_path: Path) -> str:
        try:
            result = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=False,
            )
            diff = result.stdout.strip()
            if not diff:
                return "EMPTY"
            return f"LEN:{len(diff)}|HASH:{hash(diff[:5000])}"
        except Exception:
            return "DIFF_ERR"

    def _evaluate_candidate(
        self,
        repo_path: Path,
        fail_to_pass_tests: list[str],
        pass_to_pass_tests: list[str],
        require_test_checks: bool,
        log=print,
    ) -> dict[str, Any]:
        metrics: dict[str, Any] = {
            "f2p_total": len(fail_to_pass_tests),
            "f2p_passed": None,
            "f2p_failed": None,
            "f2p_pass_rate": None,
            "f2p_all_passed": False,
            "p2p_smoke_total": None,
            "p2p_smoke_failures": None,
            "clean_resolution": None,
        }
        if not require_test_checks:
            return metrics

        if fail_to_pass_tests:
            f2p = self._run_pytest_subset(repo_path, fail_to_pass_tests, timeout=self.pytest_timeout, log=log)
            metrics["f2p_passed"] = f2p["passed"]
            metrics["f2p_failed"] = f2p["failed"]
            total = max(len(fail_to_pass_tests), 1)
            metrics["f2p_pass_rate"] = f2p["passed"] / total
            metrics["f2p_all_passed"] = f2p["failed"] == 0
            log(
                "F2P check: "
                f"passed={metrics['f2p_passed']} failed={metrics['f2p_failed']} total={len(fail_to_pass_tests)}"
            )

        smoke_tests = pass_to_pass_tests[:self.p2p_smoke_count]
        if smoke_tests:
            p2p = self._run_pytest_subset(repo_path, smoke_tests, timeout=self.pytest_timeout, log=log)
            metrics["p2p_smoke_total"] = len(smoke_tests)
            metrics["p2p_smoke_failures"] = p2p["failed"]
            log(
                "P2P smoke: "
                f"failed={metrics['p2p_smoke_failures']} total={metrics['p2p_smoke_total']}"
            )

        if metrics["f2p_all_passed"] and metrics["p2p_smoke_failures"] is not None:
            metrics["clean_resolution"] = metrics["p2p_smoke_failures"] == 0
        return metrics

    def _run_pytest_subset(self, repo_path: Path, tests: list[str], timeout: int, log=print) -> dict[str, Any]:
        cmd = ["pytest", "-q"] + list(tests)
        try:
            result = subprocess.run(
                cmd,
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            output = f"{result.stdout}\n{result.stderr}"
            passed, failed = self._parse_pytest_counts(output)
            if passed + failed == 0:
                if result.returncode == 0:
                    passed = len(tests)
                else:
                    failed = max(1, len(tests))
            passed = min(passed, len(tests))
            failed = min(max(failed, 0), len(tests))
            return {"passed": passed, "failed": failed, "returncode": result.returncode, "output": output[:2000]}
        except subprocess.TimeoutExpired:
            log(f"pytest timeout on {len(tests)} test(s)")
            return {"passed": 0, "failed": len(tests), "returncode": 124, "output": "timeout"}
        except Exception as e:
            log(f"pytest execution error: {e}")
            return {"passed": 0, "failed": len(tests), "returncode": 1, "output": str(e)}

    def _parse_pytest_counts(self, output: str) -> tuple[int, int]:
        passed = 0
        failed = 0
        pm = re.search(r"(\d+)\s+passed", output)
        fm = re.search(r"(\d+)\s+failed", output)
        if pm:
            passed = int(pm.group(1))
        if fm:
            failed = int(fm.group(1))
        return passed, failed

    def _score_candidate(self, candidate: dict[str, Any]) -> tuple:
        patch_chars = len(candidate.get("prediction", ""))
        non_empty = 1 if patch_chars > 0 else 0
        f2p_rate = candidate.get("f2p_pass_rate")
        f2p_score = float(f2p_rate) if f2p_rate is not None else 0.0
        p2p_fail = candidate.get("p2p_smoke_failures")
        p2p_penalty = int(p2p_fail) if p2p_fail is not None else 0
        loop_penalty = 1 if candidate.get("loop_abort_reason") else 0
        return (non_empty, f2p_score, -p2p_penalty, -loop_penalty, -patch_chars)

    def _format_test_failure_task(self, problem_statement: str, hints_text: str, metrics: dict[str, Any]) -> str:
        task = problem_statement
        if hints_text:
            task += f"\n\n## Hints\n\n{hints_text}"
        task += (
            "\n\n## Repair Round\n\n"
            "Your previous patch did not pass the required target tests.\n"
            f"- FAIL_TO_PASS passed: {metrics.get('f2p_passed')}/{metrics.get('f2p_total')}\n"
            "Produce a minimal correction patch and re-verify before submission.\n"
            "If an edit command fails repeatedly, switch to a different editing method immediately.\n"
        )
        return task

    def _format_graphrag_failure_task(
        self,
        problem_statement: str,
        hints_text: str,
        failed_tests: list[dict[str, Any]],
    ) -> str:
        task = problem_statement
        if hints_text:
            task += f"\n\n## Hints\n\n{hints_text}"
        task += "\n\n## GraphRAG Impacted Test Failures\n"
        task += "The following impacted tests are failing. Fix regressions with minimal code edits.\n"
        for ft in failed_tests[:10]:
            task += (
                f"- {ft.get('full_name') or ft.get('test_name')}: "
                f"{(ft.get('error') or '')[:200]}\n"
            )
        return task

    def _format_compile_failure_task(
        self,
        problem_statement: str,
        hints_text: str,
        compile_gate: dict[str, Any],
    ) -> str:
        task = problem_statement
        if hints_text:
            task += f"\n\n## Hints\n\n{hints_text}"

        failed_files = compile_gate.get("compile_failed_files", []) or []
        details = compile_gate.get("details", []) or []
        failed_detail_map = {
            d.get("file", ""): d for d in details if d.get("file") in failed_files
        }

        task += (
            "\n\n## Compile Repair Round\n\n"
            "Your previous patch failed Python syntax compile checks.\n"
            "Fix the compile errors first, with minimal targeted edits, then submit again.\n"
        )
        if failed_files:
            task += "\nFailing files:\n"
            for file_path in failed_files[:10]:
                detail = failed_detail_map.get(file_path, {})
                current_error = detail.get("current_error", "unknown")
                task += f"- {file_path}: {current_error}\n"

        task += (
            "\nRequirements:\n"
            "1. Do not add placeholders.\n"
            "2. Keep public signatures stable.\n"
            "3. Make only minimal edits needed to restore compilable Python syntax.\n"
            "4. First, edit one failing file directly; do not spend steps on broad repo searches.\n"
            "5. Before submitting, run `python3 -m py_compile <failing_file.py>` for the changed failing files.\n"
        )
        return task

    def _format_retry_task(
        self,
        problem_statement: str,
        hints_text: str,
        tdd_mode: bool,
        attempt_idx: int,
        prev_attempt: Optional[dict[str, Any]],
    ) -> str:
        task = self._format_task(problem_statement, hints_text, [], tdd_mode)
        if attempt_idx <= 1:
            return task

        task += "\n\n## Retry Guidance\n"
        task += f"Retry attempt {attempt_idx}/{self.max_attempts}. Use a different edit strategy than before.\n"
        task += "Keep commands short and avoid repeating previously failing command patterns.\n"

        if not prev_attempt:
            return task

        loop_abort_reason = str(prev_attempt.get("loop_abort_reason", ""))
        patch_gate_reason = str(prev_attempt.get("patch_gate_reason", ""))
        if patch_gate_reason:
            task += f"Previous patch gate result: {patch_gate_reason}.\n"
        if loop_abort_reason:
            task += f"Previous loop abort: {loop_abort_reason}. Change approach immediately.\n"

        if "syntax_compile_failed" in patch_gate_reason:
            task += (
                "If syntax failed, first fix the reported failing file(s), then run py_compile before submit.\n"
            )

        return task

    def _get_changed_files(self, repo_path: Path) -> list[str]:
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=False,
            )
            return [line.strip() for line in result.stdout.splitlines() if line.strip().endswith(".py")]
        except Exception:
            return []

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
                    "temperature": 0.0,
                    "max_tokens": 8192,
                    "num_ctx": 32768,
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

    def _compile_python_source(self, source: str, filename: str) -> Optional[str]:
        """Compile Python source and return None if valid, else an error string."""
        try:
            compile(source, filename, "exec")
            return None
        except SyntaxError as e:
            return f"SyntaxError:{e.msg}@{e.lineno}:{e.offset}"
        except Exception as e:
            return f"{type(e).__name__}:{e}"

    def _check_compile_gate(self, repo_path: Path) -> dict[str, Any]:
        """Compile changed Python files and classify syntax failures."""
        changed_py_files = self._get_changed_files(repo_path)
        failed_files: list[str] = []
        preexisting_failures: list[str] = []
        details: list[dict[str, str]] = []
        checked = 0

        for rel_path in changed_py_files:
            abs_path = repo_path / rel_path
            if not abs_path.exists() or not abs_path.is_file():
                continue

            checked += 1
            try:
                current_src = abs_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                current_src = abs_path.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                failed_files.append(rel_path)
                details.append(
                    {
                        "file": rel_path,
                        "current_error": f"ReadError:{e}",
                        "baseline_error": "unknown",
                    }
                )
                continue

            current_err = self._compile_python_source(current_src, rel_path)
            if current_err is None:
                continue

            baseline = subprocess.run(
                ["git", "show", f"HEAD:{rel_path}"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=False,
            )
            if baseline.returncode != 0:
                failed_files.append(rel_path)
                details.append(
                    {
                        "file": rel_path,
                        "current_error": current_err,
                        "baseline_error": "missing",
                    }
                )
                continue

            baseline_err = self._compile_python_source(baseline.stdout, f"HEAD:{rel_path}")
            if baseline_err is None:
                failed_files.append(rel_path)
                details.append(
                    {
                        "file": rel_path,
                        "current_error": current_err,
                        "baseline_error": "ok",
                    }
                )
            else:
                preexisting_failures.append(rel_path)
                details.append(
                    {
                        "file": rel_path,
                        "current_error": current_err,
                        "baseline_error": baseline_err,
                    }
                )

        return {
            "enabled": True,
            "python_files_changed": len(changed_py_files),
            "compile_checked": checked,
            "compile_failed": len(failed_files),
            "compile_failed_files": failed_files,
            "compile_skipped_preexisting": len(preexisting_failures),
            "compile_preexisting_files": preexisting_failures,
            "details": details,
        }

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

        removed_lines_count = len(re.findall(r"^-(?!--).", diff, flags=re.MULTILINE))
        added_lines = re.findall(r"^\+(?!\+\+\+)(.*)$", diff, flags=re.MULTILINE)
        added_lines_count = len(added_lines)
        changed_lines_total = removed_lines_count + added_lines_count
        if self.max_changed_lines > 0 and changed_lines_total > self.max_changed_lines:
            fail_reasons.append(
                f"too_many_changed_lines:{changed_lines_total}_limit_{self.max_changed_lines}"
            )
        if removed_lines_count > 50 and added_lines_count > 0 and removed_lines_count > 5 * added_lines_count:
            fail_reasons.append(f"catastrophic_deletion:{removed_lines_count}_removed_vs_{added_lines_count}_added")

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

        compile_gate = {
            "enabled": False,
            "python_files_changed": 0,
            "compile_checked": 0,
            "compile_failed": 0,
            "compile_failed_files": [],
            "compile_skipped_preexisting": 0,
            "compile_preexisting_files": [],
            "details": [],
        }
        if self.patch_compile_gate:
            compile_gate = self._check_compile_gate(repo_path)
            failed_files = compile_gate.get("compile_failed_files", [])
            if failed_files:
                fail_reasons.append(f"syntax_compile_failed:{'|'.join(failed_files)}")
            if compile_gate.get("compile_skipped_preexisting", 0) > 0:
                warn_reasons.append(
                    f"compile_preexisting_failures:{compile_gate['compile_skipped_preexisting']}"
                )

        metrics = {
            "files_changed": files_changed,
            "added_lines": len(added_lines),
            "removed_lines": removed_lines_count,
            "changed_lines_total": changed_lines_total,
            "changed_lines_limit": self.max_changed_lines,
            "duplicate_line_max_count": duplicate_line_max_count,
            "signature_change_detected": signature_change_detected,
            "python_files_changed": compile_gate.get("python_files_changed", 0),
            "compile_checked": compile_gate.get("compile_checked", 0),
            "compile_failed": compile_gate.get("compile_failed", 0),
            "compile_skipped_preexisting": compile_gate.get("compile_skipped_preexisting", 0),
        }

        if fail_reasons:
            return {
                "valid": False,
                "severity": "fail",
                "reason": ",".join(fail_reasons),
                "fail_reasons": fail_reasons,
                "warn_reasons": warn_reasons,
                "metrics": metrics,
                "compile_gate": compile_gate,
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
                "compile_gate": compile_gate,
                "diff": diff,
            }

        return {
            "valid": True,
            "severity": "info",
            "reason": "ok",
            "fail_reasons": fail_reasons,
            "warn_reasons": warn_reasons,
            "metrics": metrics,
            "compile_gate": compile_gate,
            "diff": diff,
        }

    def _extract_patch(self, repo_path: Path, log=print) -> str:
        """Extract git diff with quality-gate validation."""
        validation = self._validate_patch_quality(repo_path)
        self._last_patch_gate_decision = validation
        log(
            "PATCH_GATE_RESULT "
            f"valid={validation['valid']} "
            f"severity={validation['severity']} "
            f"reason={validation['reason']} "
            f"metrics={validation['metrics']}"
        )
        compile_gate = validation.get("compile_gate", {})
        if compile_gate.get("enabled"):
            log(
                "PATCH_GATE_COMPILE "
                f"checked={compile_gate.get('compile_checked', 0)} "
                f"failed={compile_gate.get('compile_failed', 0)} "
                f"preexisting={compile_gate.get('compile_skipped_preexisting', 0)} "
                f"failed_files={compile_gate.get('compile_failed_files', [])}"
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
