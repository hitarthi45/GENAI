"""Code/Test Runner MCP Server.

Runs shell commands and Python snippets inside WORKSPACE_DIR with a timeout.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import anyio
from mcp.server.mcpserver import MCPServer

WORKSPACE = Path(os.getenv("WORKSPACE_DIR", Path(__file__).resolve().parents[2])).resolve()
MAX_OUTPUT_CHARS = 20_000
MAX_TIMEOUT = 300

mcp = MCPServer("TestingServer")


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kills a process and its children (a shell's children otherwise keep the pipes open)."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        os.killpg(proc.pid, 9)


def _run(args: str | list[str], shell: bool, timeout: int) -> str:
    timeout = max(1, min(timeout, MAX_TIMEOUT))
    proc = subprocess.Popen(
        args,
        shell=shell,
        cwd=WORKSPACE,
        # stdin must not inherit this server's stdin: it carries the MCP protocol.
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=sys.platform != "win32",
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        stdout, stderr = proc.communicate()
        return f"Error: timed out after {timeout} seconds.\n\n{_format(stdout, stderr, None)}"
    return _format(stdout, stderr, proc.returncode)


def _format(stdout: str, stderr: str, returncode: int | None) -> str:
    parts = []
    if returncode is not None:
        parts.append(f"EXIT CODE: {returncode}")
    if stdout and stdout.strip():
        parts.append(f"STDOUT:\n{stdout.strip()}")
    if stderr and stderr.strip():
        parts.append(f"STDERR:\n{stderr.strip()}")
    output = "\n\n".join(parts) if parts else "Completed with no output."
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + "\n\n... [output truncated]"
    return output


@mcp.tool()
async def run_tests(command: str = "python -m pytest -q", timeout: int = 120) -> str:
    """Runs a test command (e.g. 'python -m pytest -q', 'python -m unittest') in the workspace root."""
    try:
        return await anyio.to_thread.run_sync(_run, command, True, timeout)
    except Exception as e:
        return f"Error executing tests: {e}"


@mcp.tool()
async def run_command(command: str, timeout: int = 60) -> str:
    """Runs a shell command in the workspace root and returns exit code, stdout and stderr."""
    try:
        return await anyio.to_thread.run_sync(_run, command, True, timeout)
    except Exception as e:
        return f"Error executing command: {e}"


@mcp.tool()
async def run_python_code(code: str, timeout: int = 30) -> str:
    """Executes a Python snippet in a fresh interpreter (cwd = workspace root) and returns its output."""
    fd, script = tempfile.mkstemp(suffix=".py", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(code)
        return await anyio.to_thread.run_sync(_run, [sys.executable, script], False, timeout)
    except Exception as e:
        return f"Error executing code: {e}"
    finally:
        os.remove(script)


if __name__ == "__main__":
    mcp.run(transport="stdio")
