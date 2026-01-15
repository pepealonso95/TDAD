"""
Simple agent loop for GPT-OSS using Ollama API directly.

This implements a basic ReAct-style agent that can:
- Read files
- Write/edit files
- Run bash commands
- Iterate until task completion
"""

import os
import json
import re
import subprocess
import time
from typing import Dict, List, Optional, Tuple
import requests

class GptOssAgent:
    """Simple agent that uses Ollama API with tool-calling for GPT-OSS."""

    def __init__(self, model: str = "gpt-oss:20b", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url
        self.api_url = f"{base_url}/api/chat"
        self.conversation_history = []
        self.max_iterations = 20  # Prevent infinite loops
        self.max_retries = 3  # Retry on API errors

    def _call_ollama(self, messages: List[Dict], retry_count: int = 0) -> Dict:
        """Call Ollama API and get response with retry logic.

        Returns the full message dict including content, thinking, and tool_calls.
        """
        # Debug: Log conversation state
        total_chars = sum(len(str(msg.get("content", ""))) for msg in messages)
        print(f"  📊 Conversation: {len(messages)} messages, {total_chars} chars")

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0.2,  # Lower temperature for more focused responses
                "num_predict": 2048,  # Limit response length
                "num_ctx": 16384,  # Context window (2x minimum for gpt-oss:20b)
                "num_batch": 256,  # Batch size for memory efficiency
            }
        }

        try:
            response = requests.post(self.api_url, json=payload, timeout=300)
            response.raise_for_status()

            result = response.json()
            # Return the full message dict, not just content
            return result["message"]

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 500 and retry_count < self.max_retries:
                # Retry on 500 errors with exponential backoff
                wait_time = 2 ** retry_count
                print(f"  ⚠️  API error 500, retrying in {wait_time}s... (attempt {retry_count + 1}/{self.max_retries})")
                time.sleep(wait_time)
                return self._call_ollama(messages, retry_count + 1)
            else:
                raise

    def _read_file(self, path: str) -> str:
        """Read a file and return its contents."""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            # Limit file size for context
            if len(content) > 10000:
                content = content[:10000] + f"\n\n... (truncated, {len(content)} total chars)"
            return f"File content of {path}:\n```\n{content}\n```"
        except Exception as e:
            return f"Error reading {path}: {str(e)}"

    def _write_file(self, path: str, content: str) -> str:
        """Write content to a file."""
        try:
            # Create parent directories if they don't exist
            os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            return f"Successfully wrote to {path}"
        except Exception as e:
            return f"Error writing to {path}: {str(e)}"

    def _run_bash(self, command: str) -> str:
        """Run a bash command and return output."""
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60
            )
            output = f"Return code: {result.returncode}\n"
            if result.stdout:
                stdout_preview = result.stdout[:1000]
                if len(result.stdout) > 1000:
                    stdout_preview += f"\n... (truncated, {len(result.stdout)} total chars)"
                output += f"Stdout:\n{stdout_preview}\n"
            if result.stderr:
                stderr_preview = result.stderr[:1000]
                if len(result.stderr) > 1000:
                    stderr_preview += f"\n... (truncated, {len(result.stderr)} total chars)"
                output += f"Stderr:\n{stderr_preview}\n"
            return output
        except Exception as e:
            return f"Error running command: {str(e)}"

    def _extract_tool_calls(self, message: Dict) -> List[Tuple[str, Dict]]:
        """
        Extract tool calls from GPT-OSS's response message.

        The message can contain:
        1. Native tool_calls (from GPT-OSS function calling) - Handle these!
        2. Text-based tool calls in content (XML or TOOL: format)
        """
        tool_calls = []

        # First, check for native tool_calls (GPT-OSS function calling)
        if "tool_calls" in message and message["tool_calls"]:
            print(f"  📞 Found {len(message['tool_calls'])} native function calls")
            # Parse native function calls and convert to our format
            for native_call in message["tool_calls"]:
                try:
                    function_info = native_call.get("function", {})
                    function_name = function_info.get("name", "")

                    # Parse arguments (might be string or dict)
                    args = function_info.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            print(f"  ⚠️  Failed to parse arguments: {args}")
                            continue

                    # Map GPT-OSS's native functions to our tools
                    if "exec" in function_name or "bash" in function_name:
                        # Extract bash command from arguments
                        if isinstance(args, dict):
                            cmd = args.get("cmd", args.get("command", ""))

                            # Handle LIST format: ["bash", "-lc", "actual command"]
                            if isinstance(cmd, list):
                                if len(cmd) > 0 and cmd[0] in ["bash", "sh"]:
                                    # Skip bash wrapper, get the actual command
                                    if len(cmd) == 3 and cmd[1] in ["-c", "-lc"]:
                                        cmd = cmd[2]  # The actual command
                                    else:
                                        # Join everything after bash/-c flag
                                        cmd = " ".join(cmd[2:]) if len(cmd) > 2 and cmd[1] in ["-c", "-lc"] else " ".join(cmd[1:])
                                else:
                                    cmd = " ".join(cmd)

                            # Handle STRING format: "bash -lc actual command" or "bash -c actual command"
                            elif isinstance(cmd, str):
                                # Use regex to extract command after bash wrapper
                                # Match: bash/sh + optional -lc/-c + command
                                bash_pattern = r'^(?:bash|sh)\s+(?:-l?c\s+)?(.+)$'
                                match = re.match(bash_pattern, cmd.strip())
                                if match:
                                    cmd = match.group(1)  # Extract the actual command

                            if cmd:
                                tool_calls.append(("bash", {"command": cmd}))

                    elif "read" in function_name or "cat" in function_name:
                        # Map to read_file
                        if isinstance(args, dict):
                            path = args.get("path", args.get("file", ""))
                            if path:
                                tool_calls.append(("read_file", {"path": path}))

                    elif "write" in function_name or "edit" in function_name:
                        # Map to write_file
                        if isinstance(args, dict):
                            path = args.get("path", args.get("file", ""))
                            content = args.get("content", args.get("data", ""))
                            if path:
                                tool_calls.append(("write_file", {"path": path, "content": content}))

                except Exception as e:
                    print(f"  ⚠️  Error parsing native call: {e}")
                    continue

            # If we successfully parsed native calls, return them
            if tool_calls:
                print(f"  ✅ Converted {len(tool_calls)} native calls to our format")
                return tool_calls

        # Check text content for XML or TOOL: format
        text = message.get("content", "") or message.get("thinking", "")

        if not text:
            return tool_calls

        # Try XML-style format first
        xml_pattern = r'<tool_call>(.*?)</tool_call>'
        matches = re.findall(xml_pattern, text, re.DOTALL)

        for match in matches:
            tool_match = re.search(r'<tool>(.*?)</tool>', match)
            if not tool_match:
                continue

            tool_name = tool_match.group(1).strip()
            params = {}

            # Extract parameters
            for param in ['path', 'content', 'command']:
                param_match = re.search(f'<{param}>(.*?)</{param}>', match, re.DOTALL)
                if param_match:
                    params[param] = param_match.group(1).strip()

            tool_calls.append((tool_name, params))

        # Try simple TOOL: format if no XML found
        if not tool_calls:
            simple_pattern = r'TOOL:\s*(\w+)\((.*?)\)'
            matches = re.findall(simple_pattern, text)

            for tool_name, args_str in matches:
                params = {}
                if tool_name == 'read_file':
                    params['path'] = args_str.strip('"\'')
                elif tool_name == 'write_file':
                    # Split on first comma outside quotes
                    parts = re.split(r',\s*(?=["\'])', args_str, 1)
                    if len(parts) == 2:
                        params['path'] = parts[0].strip().strip('"\'')
                        params['content'] = parts[1].strip().strip('"\'')
                elif tool_name == 'bash':
                    params['command'] = args_str.strip('"\'')

                if params:
                    tool_calls.append((tool_name, params))

        return tool_calls

    def _execute_tool(self, tool_name: str, params: Dict) -> str:
        """Execute a tool and return the result."""
        if tool_name == 'read_file':
            return self._read_file(params.get('path', ''))
        elif tool_name == 'write_file':
            return self._write_file(params.get('path', ''), params.get('content', ''))
        elif tool_name == 'bash':
            return self._run_bash(params.get('command', ''))
        else:
            return f"Unknown tool: {tool_name}"

    def _is_task_complete(self, text: str) -> bool:
        """Check if GPT-OSS indicates the task is complete."""
        completion_markers = [
            "task is complete",
            "task complete",
            "finished the task",
            "completed the fix",
            "fix is complete",
            "changes have been applied",
            "done with",
            "fix has been implemented",
            "successfully fixed",
            "<task_complete/>",
            "<complete/>",
            "TASK COMPLETE",
        ]

        text_lower = text.lower()
        return any(marker in text_lower for marker in completion_markers)

    def _apply_sliding_window(self, messages: List[Dict], max_pairs: int = 4) -> List[Dict]:
        """Apply sliding window to keep conversation manageable.

        Keeps system prompt (first message) and last N message pairs (assistant + user).

        Args:
            messages: List of conversation messages
            max_pairs: Maximum number of assistant+user pairs to keep (default 4 = 8 messages + system)

        Returns:
            Trimmed message list
        """
        if len(messages) <= (1 + max_pairs * 2):
            return messages  # No need to trim

        # Always keep the system prompt (first message)
        system_msg = messages[0]

        # Keep last N pairs of messages (assistant + user responses)
        # messages[1:] are the conversation after system prompt
        conversation = messages[1:]

        # Keep last max_pairs * 2 messages (each pair is assistant + user)
        recent_messages = conversation[-(max_pairs * 2):]

        result = [system_msg] + recent_messages
        dropped = len(messages) - len(result)
        if dropped > 0:
            print(f"  🗑️  Dropped {dropped} old messages (sliding window)")

        return result

    def run_task(self, prompt: str, working_dir: str) -> Dict:
        """
        Run a task using the agent loop.

        Args:
            prompt: The task description
            working_dir: Directory to work in

        Returns:
            Dict with success status and conversation log
        """
        # Change to working directory
        original_dir = os.getcwd()
        os.chdir(working_dir)

        try:
            # Initialize conversation with system prompt
            system_prompt = f"""You are an expert software engineer working on fixing bugs in code.

You have access to these tools:
1. read_file(path) - Read a file
2. write_file(path, content) - Write/overwrite a file with content
3. bash(command) - Run a bash command

To use a tool, format it like this:
<tool_call>
<tool>read_file</tool>
<path>path/to/file.py</path>
</tool_call>

Or use this simpler format:
TOOL: read_file("path/to/file.py")
TOOL: write_file("path/to/file.py", "new content here")
TOOL: bash("ls -la")

Work step by step:
1. Read the relevant files to understand the issue
2. Identify the root cause of the bug
3. Make the necessary changes to fix it
4. Test your changes if possible

When you've completed the task, say "TASK COMPLETE" or "<task_complete/>".

Current working directory: {working_dir}

Your task:
{prompt}
"""

            messages = [{"role": "user", "content": system_prompt}]

            print(f"\n🤖 Starting GPT-OSS agent loop (max {self.max_iterations} iterations)...")
            print(f"⚠️  Note: GPT-OSS has native function calling which we need to work around\n")

            for iteration in range(self.max_iterations):
                print(f"\n--- Iteration {iteration + 1}/{self.max_iterations} ---")

                # Apply sliding window to manage conversation size
                messages = self._apply_sliding_window(messages, max_pairs=4)

                # Get response from GPT-OSS (returns full message dict)
                message = self._call_ollama(messages)

                # Extract content and thinking for display
                content = message.get("content", "")
                thinking = message.get("thinking", "")

                # Display response
                if thinking:
                    print(f"Thinking: {thinking[:300]}..." if len(thinking) > 300 else f"Thinking: {thinking}")
                if content:
                    print(f"Content: {content[:300]}..." if len(content) > 300 else f"Content: {content}")

                # Add to conversation (use content for conversation history)
                messages.append({"role": "assistant", "content": content if content else thinking})

                # Check if task is complete in both content and thinking
                full_text = f"{content} {thinking}"
                if self._is_task_complete(full_text):
                    print("\n✅ Task completed!")
                    break

                # Extract and execute tool calls
                tool_calls = self._extract_tool_calls(message)

                if not tool_calls:
                    # No tools called, ask GPT-OSS to proceed
                    # Be more explicit since it wants to use native function calling
                    messages.append({
                        "role": "user",
                        "content": """Please proceed with the fix using the text-based tool format:
TOOL: read_file("path/to/file")
TOOL: write_file("path/to/file", "content")
TOOL: bash("command")

When done, say TASK COMPLETE."""
                    })
                    continue

                # Execute tools and collect results
                tool_results = []
                for tool_name, params in tool_calls:
                    print(f"  🔧 Executing: {tool_name}({params})")
                    result = self._execute_tool(tool_name, params)

                    # Truncate very long results to avoid context overflow
                    max_result_len = 8000  # Increased from 2000 to allow full file reads
                    if len(result) > max_result_len:
                        result_preview = result[:max_result_len]
                        result = f"{result_preview}\n\n... (truncated, {len(result)} total characters)"

                    tool_results.append(f"Tool: {tool_name}\nResult: {result}")

                # Send tool results back to GPT-OSS
                tool_response = "\n\n".join(tool_results)
                # Also truncate total response if needed
                max_total_len = 12000  # Increased from 4000 to allow multiple file reads
                if len(tool_response) > max_total_len:
                    tool_response = tool_response[:max_total_len] + f"\n\n... (truncated, {len(tool_response)} total characters)"

                messages.append({"role": "user", "content": f"Tool results:\n{tool_response}\n\nContinue with the task."})

            else:
                print(f"\n⚠️  Reached maximum iterations ({self.max_iterations})")

            return {
                "success": True,
                "conversation": messages,
                "iterations": iteration + 1
            }

        finally:
            # Restore original directory
            os.chdir(original_dir)
