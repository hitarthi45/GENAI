import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

try:
    from dotenv import load_dotenv  # type: ignore[import-not-found]
except ImportError:
    def load_dotenv(*args, **kwargs):
        return False

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

from fastapi import FastAPI, HTTPException, Query, Request  # type: ignore[reportMissingImports]  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # type: ignore[reportMissingImports]  # noqa: E402

from app.mcp_client import MCPClientManager  # noqa: E402
from app.routers import chat  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".idea", ".vscode"}
MAX_TREE_ENTRIES = 3000
MAX_FILE_BYTES = 1_000_000


@asynccontextmanager
async def lifespan(app: FastAPI):
    manager = MCPClientManager()
    await manager.start()
    app.state.mcp = manager
    try:
        yield
    finally:
        await manager.stop()


app = FastAPI(title="MCP Coding Assistant", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)


def _workspace(request: Request) -> Path:
    return request.app.state.mcp.workspace


def _safe_path(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    if target != root and root not in target.parents:
        raise HTTPException(status_code=400, detail="Path is outside the workspace.")
    return target


@app.get("/")
def read_root():
    return {"status": "MCP Assistant API is running"}


@app.get("/api/health")
def health(request: Request):
    manager = request.app.state.mcp
    return {
        "status": "ok",
        "model": manager.model_name,
        "llm_configured": manager.client is not None,
        "workspace": str(manager.workspace),
        "servers": manager.server_status,
        "tool_count": len(manager.tools),
    }


@app.get("/api/files/tree")
def file_tree(request: Request):
    """Returns the workspace as a nested tree: {name, path, type, children?}."""
    root = _workspace(request)
    count = 0

    def build(directory: Path) -> list[dict]:
        nonlocal count
        try:
            entries = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except (PermissionError, OSError):
            return []
        nodes = []
        for entry in entries:
            if entry.name in IGNORED_DIRS or count >= MAX_TREE_ENTRIES:
                continue
            count += 1
            node = {"name": entry.name, "path": entry.relative_to(root).as_posix()}
            if entry.is_dir():
                node.update(type="directory", children=build(entry))
            else:
                node["type"] = "file"
            nodes.append(node)
        return nodes

    return {"name": root.name, "path": "", "type": "directory", "children": build(root)}


@app.get("/api/files/content")
def file_content(request: Request, path: str = Query(..., min_length=1)):
    target = _safe_path(_workspace(request), path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    if target.stat().st_size > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="File is too large to display.")
    data = target.read_bytes()
    if b"\x00" in data[:8000]:
        raise HTTPException(status_code=415, detail="Binary files cannot be displayed.")
    return {"path": path, "content": data.decode("utf-8", errors="replace")}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        reload=True,
        reload_dirs=[str(BACKEND_DIR / "app"), str(BACKEND_DIR / "mcp_servers")],
    )
