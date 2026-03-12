"""opencode subprocess wrapper."""

import logging
import subprocess
from typing import Dict, Any

logger = logging.getLogger(__name__)


def check_installed() -> None:
    """Verify that the opencode CLI is on PATH."""
    try:
        result = subprocess.run(
            ["opencode", "--version"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "opencode CLI returned non-zero. "
                "Ensure 'opencode' is installed and in PATH."
            )
    except FileNotFoundError:
        raise RuntimeError(
            "opencode CLI not found. "
            "Ensure 'opencode' is installed and in PATH."
        )


def execute(prompt: str, cwd: str, timeout: int = 600) -> Dict[str, Any]:
    """Run opencode with the given prompt via stdin.

    Args:
        prompt: The full prompt text to pipe into opencode.
        cwd: Working directory (the cloned repo).
        timeout: Seconds before killing the process.

    Returns:
        dict with keys: success, stdout, stderr, returncode
    """
    cmd = ["opencode", "run"]

    logger.info(
        "Executing opencode | cwd=%s | prompt_len=%d | timeout=%ds",
        cwd, len(prompt), timeout,
    )

    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )

        logger.info(
            "opencode finished | rc=%d | stdout_len=%d | stderr_len=%d",
            result.returncode, len(result.stdout), len(result.stderr),
        )

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }

    except subprocess.TimeoutExpired:
        logger.warning("opencode timed out after %ds", timeout)
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Command timed out after {timeout} seconds",
            "returncode": -1,
        }
    except Exception as exc:
        logger.error("opencode execution failed: %s", exc)
        return {
            "success": False,
            "stdout": "",
            "stderr": str(exc),
            "returncode": -1,
        }
