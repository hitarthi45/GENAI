"""Documentation MCP Server.

Serves a small built-in knowledge base plus live Python docs via pydoc.
"""

import pydoc
import re

import anyio
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("DocumentationServer")

MAX_DOC_CHARS = 12_000
DOTTED_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")

DOCS_DB = {
    "fastapi": "FastAPI is a modern web framework for building APIs with Python based on standard type hints. "
    "Routes are declared with decorators like @app.get('/path'); request bodies are Pydantic models; "
    "APIRouter groups routes and is mounted with app.include_router(router). Run with: uvicorn app.main:app --reload.",
    "mcp": "Model Context Protocol (MCP) connects AI models to tools, resources and prompts through a standard "
    "JSON-RPC interface. A server exposes tools (e.g. with MCPServer and @mcp.tool()); a client connects over "
    "stdio or HTTP with ClientSession, calls initialize(), list_tools() and call_tool(name, arguments).",
    "gemini": "The Google GenAI SDK (google-genai) calls Gemini models: client = genai.Client(api_key=...); "
    "client.models.generate_content(model=..., contents=..., config=types.GenerateContentConfig(tools=[...])). "
    "Function calling returns response.function_calls; send results back as function_response parts.",
    "react": "React builds UIs from components. State lives in useState, side effects in useEffect, and lists "
    "need a stable key prop. Vite serves a React app with 'npm run dev'.",
    "pytest": "pytest discovers test_*.py files and test_* functions. Use plain assert statements, fixtures via "
    "@pytest.fixture, and parametrize with @pytest.mark.parametrize. Run 'python -m pytest -q'.",
    "pydantic": "Pydantic validates data with type hints: class Item(BaseModel): name: str. Use model_dump() to "
    "convert to dict and model_validate() to parse input.",
    "asyncio": "asyncio runs coroutines on an event loop: async def functions are awaited; asyncio.gather runs "
    "them concurrently; blocking calls should go through asyncio.to_thread.",
    "git": "Common git commands: git status, git add <file>, git commit -m 'msg', git log --oneline, "
    "git diff, git switch -c <branch>.",
}


@mcp.tool()
def list_documentation_topics() -> str:
    """Lists the topics available in the built-in documentation knowledge base."""
    return ", ".join(sorted(DOCS_DB))


@mcp.tool()
def search_documentation(query: str) -> str:
    """Searches the built-in technical documentation for a topic or keyword."""
    words = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) >= 3}
    scored = []
    for topic, text in DOCS_DB.items():
        text_words = set(re.findall(r"[a-z0-9]+", text.lower()))
        score = (10 if topic in query.lower() else 0) + len(words & text_words)
        if score:
            scored.append((score, f"## {topic}\n{text}"))
    if scored:
        scored.sort(key=lambda item: item[0], reverse=True)
        return "\n\n".join(entry for _, entry in scored[:3])
    return f"No documentation found for '{query}'. Available topics: {list_documentation_topics()}."


@mcp.tool()
async def get_python_help(name: str) -> str:
    """Returns the official docstring/help for a Python module, class or function, e.g. 'json.dumps'."""
    if not DOTTED_NAME.match(name):
        return "Error: provide a dotted Python name such as 'os.path.join'."
    try:
        text = await anyio.to_thread.run_sync(pydoc.render_doc, name, "Help on %s", None, pydoc.plaintext)
    except Exception as e:
        return f"No Python documentation found for '{name}': {e}"
    return text[:MAX_DOC_CHARS] + ("\n\n... [truncated]" if len(text) > MAX_DOC_CHARS else "")


if __name__ == "__main__":
    mcp.run(transport="stdio")
