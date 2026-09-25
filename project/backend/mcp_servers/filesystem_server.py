"""File Operations MCP Server.

Exposes read/write/search tools over stdio. Every path is resolved relative to
WORKSPACE_DIR and may not escape it.
"""

import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer

WORKSPACE = Path(os.getenv("WORKSPACE_DIR", Path(__file__).resolve().parents[2])).resolve()
IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".idea", ".vscode"}
MAX_READ_BYTES = 200_000
MAX_RESULTS = 200

mcp = MCPServer("FileSystemServer")


def _resolve(path: str) -> Path:
    """Resolves a workspace-relative path and rejects anything outside the workspace."""
    target = (WORKSPACE / (path or ".")).resolve()
    if target != WORKSPACE and WORKSPACE not in target.parents:
        raise ValueError(f"Path '{path}' is outside the workspace.")
    return target


def _rel(path: Path) -> str:
    return path.relative_to(WORKSPACE).as_posix() or "."


@mcp.tool()
def list_directory(path: str = ".") -> str:
    """Lists files and subdirectories at a workspace-relative path. Directories end with '/'."""
    try:
        target = _resolve(path)
        if not target.is_dir():
            return f"Error: '{path}' is not a directory."
        entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        lines = [f"{e.name}/" if e.is_dir() else e.name for e in entries if e.name not in IGNORED_DIRS]
        return "\n".join(lines) if lines else "(empty directory)"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def get_project_tree(path: str = ".", max_depth: int = 4) -> str:
    """Returns an indented tree of the project structure, skipping dependency and build folders."""
    try:
        root = _resolve(path)
        lines = [f"{_rel(root)}/"]

        def walk(directory: Path, depth: int) -> None:
            if depth > max_depth or len(lines) > 1000:
                return
            try:
                entries = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            except PermissionError:
                return
            for entry in entries:
                if entry.name in IGNORED_DIRS:
                    continue
                lines.append(f"{'  ' * depth}{entry.name}{'/' if entry.is_dir() else ''}")
                if entry.is_dir():
                    walk(entry, depth + 1)

        walk(root, 1)
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def read_file(file_path: str) -> str:
    """Reads and returns the text contents of a workspace file."""
    try:
        target = _resolve(file_path)
        if not target.is_file():
            return f"Error: '{file_path}' does not exist or is not a file."
        data = target.read_bytes()
        truncated = len(data) > MAX_READ_BYTES
        text = data[:MAX_READ_BYTES].decode("utf-8", errors="replace")
        return text + ("\n\n... [truncated]" if truncated else "")
    except Exception as e:
        return f"Error reading '{file_path}': {e}"


@mcp.tool()
def write_file(file_path: str, content: str) -> str:
    """Creates or overwrites a workspace file with the given content. Parent folders are created."""
    try:
        target = _resolve(file_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} characters to '{_rel(target)}'."
    except Exception as e:
        return f"Error writing '{file_path}': {e}"


@mcp.tool()
def search_files(directory: str = ".", extension: str = ".py") -> str:
    """Finds files under a directory whose names end with the given extension."""
    try:
        root = _resolve(directory)
        matches = []
        for current, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            matches.extend(_rel(Path(current) / f) for f in files if f.endswith(extension))
            if len(matches) >= MAX_RESULTS:
                break
        return "\n".join(matches[:MAX_RESULTS]) if matches else f"No '{extension}' files found."
    except Exception as e:
        return f"Search error: {e}"


@mcp.tool()
def search_in_files(query: str, directory: str = ".", extension: str = "") -> str:
    """Searches file contents for a case-insensitive text query. Returns 'path:line: text' matches."""
    try:
        root = _resolve(directory)
        needle = query.lower()
        results = []
        for current, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            for name in files:
                if extension and not name.endswith(extension):
                    continue
                path = Path(current) / name
                try:
                    if path.stat().st_size > MAX_READ_BYTES:
                        continue
                    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                        if needle in line.lower():
                            results.append(f"{_rel(path)}:{number}: {line.strip()[:200]}")
                            if len(results) >= MAX_RESULTS:
                                return "\n".join(results)
                except (UnicodeDecodeError, OSError):
                    continue
        return "\n".join(results) if results else f"No matches for '{query}'."
    except Exception as e:
        return f"Search error: {e}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
