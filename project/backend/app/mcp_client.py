"""MCP client & LLM orchestration engine.

Starts each MCP server as a stdio subprocess, discovers its tools, exposes them
to Gemini as function declarations, and runs the tool-calling loop.
"""

import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anyio
from google import genai
from google.genai import types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent
SERVERS_DIR = BACKEND_DIR / "mcp_servers"
MCP_SERVERS = {
    "filesystem": SERVERS_DIR / "filesystem_server.py",
    "testing": SERVERS_DIR / "testing_server.py",
    "docs": SERVERS_DIR / "docs_server.py",
}
MAX_TOOL_STEPS = 10
UI_PREVIEW_CHARS = 4_000

SYSTEM_PROMPT = """You are an expert AI coding assistant connected to a developer's project through \
Model Context Protocol (MCP) tools. The project workspace root is: {workspace}
All tool paths are relative to that root.

Guidelines:
- Inspect the real code with the filesystem tools before answering questions about the project.
- When generating code, give complete, runnable code in fenced blocks with a language tag.
- When debugging, reproduce with run_tests / run_command / run_python_code when possible, explain the root cause, then give the fix.
- Only write files when the user asks you to create or change them.
- Use the documentation tools for library/API questions.
- Be concise and use Markdown."""


@dataclass
class ToolBinding:
    server: str
    session: ClientSession
    tool: Any


class MCPClientManager:
    def __init__(self) -> None:
        self.workspace = Path(os.getenv("WORKSPACE_DIR", BACKEND_DIR.parent)).resolve()
        self.model_name = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
        api_key = os.getenv("GEMINI_API_KEY")
        self.client = genai.Client(api_key=api_key) if api_key else None
        self.tools: dict[str, ToolBinding] = {}
        self.server_status: dict[str, str] = {}
        self._stack = AsyncExitStack()

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        """Launches every MCP server. A server that fails is logged and skipped."""
        env = {
            **get_default_environment(),
            "WORKSPACE_DIR": str(self.workspace),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }
        for name, script in MCP_SERVERS.items():
            server_stack = AsyncExitStack()
            try:
                params = StdioServerParameters(command=sys.executable, args=[str(script)], env=env, cwd=str(BACKEND_DIR))
                read, write = await server_stack.enter_async_context(stdio_client(params))
                session = await server_stack.enter_async_context(ClientSession(read, write))
                with anyio.fail_after(30):
                    await session.initialize()
                    listed = await session.list_tools()
                for tool in listed.tools:
                    self.tools[tool.name] = ToolBinding(name, session, tool)
                self.server_status[name] = "connected"
                await self._stack.enter_async_context(server_stack)
                logger.info("MCP server '%s' connected with %d tools", name, len(listed.tools))
            except Exception as e:
                self.server_status[name] = f"error: {e}"
                logger.exception("Failed to start MCP server '%s'", name)
                await server_stack.aclose()

    async def stop(self) -> None:
        await self._stack.aclose()

    # ------------------------------------------------------------------ tools

    def describe_tools(self) -> list[dict]:
        return [
            {"name": name, "server": b.server, "description": b.tool.description or ""}
            for name, b in self.tools.items()
        ]

    def _gemini_tools(self) -> list[types.Tool]:
        if not self.tools:
            return []
        declarations = [
            types.FunctionDeclaration(
                name=name,
                description=b.tool.description or name,
                parameters_json_schema=b.tool.input_schema,
            )
            for name, b in self.tools.items()
        ]
        return [types.Tool(function_declarations=declarations)]

    async def call_tool(self, name: str, args: dict) -> tuple[str, bool]:
        """Calls an MCP tool. Returns (text result, is_error)."""
        binding = self.tools.get(name)
        if binding is None:
            return f"Error: tool '{name}' is not available.", True
        try:
            result = await binding.session.call_tool(name, args)
        except Exception as e:
            return f"Tool '{name}' failed: {e}", True

        texts = [c.text for c in getattr(result, "content", None) or [] if getattr(c, "type", None) == "text"]
        if not texts and getattr(result, "structured_content", None) is not None:
            texts = [str(result.structured_content)]
        return "\n".join(texts) or "(no output)", bool(getattr(result, "is_error", False))

    # ------------------------------------------------------------------ chat

    @staticmethod
    def _history_to_contents(history: list[dict]) -> list[types.Content]:
        contents = []
        for item in history:
            text = (item.get("content") or "").strip()
            if not text:
                continue
            role = "model" if item.get("role") == "assistant" else "user"
            contents.append(types.Content(role=role, parts=[types.Part.from_text(text=text)]))
        return contents

    async def stream_chat(self, message: str, history: list[dict] | None = None) -> AsyncIterator[dict]:
        """Runs the agent loop, yielding events:
        {"type": "text", "content": ...}        streamed answer text
        {"type": "tool_call", "name", "args"}   the model invoked an MCP tool
        {"type": "tool_result", "name", "result", "is_error"}
        {"type": "error", "content": ...}
        {"type": "done"}
        """
        if self.client is None:
            yield {"type": "error", "content": "GEMINI_API_KEY is missing. Add it to backend/.env and restart the server."}
            yield {"type": "done"}
            return

        config = types.GenerateContentConfig(
            temperature=0.2,
            system_instruction=SYSTEM_PROMPT.format(workspace=self.workspace),
            tools=self._gemini_tools() or None,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        contents = self._history_to_contents(history or [])
        contents.append(types.Content(role="user", parts=[types.Part.from_text(text=message)]))

        try:
            for _ in range(MAX_TOOL_STEPS):
                model_parts: list[types.Part] = []
                stream = await self.client.aio.models.generate_content_stream(
                    model=self.model_name, contents=contents, config=config
                )
                async for chunk in stream:
                    candidate = chunk.candidates[0] if chunk.candidates else None
                    if not candidate or not candidate.content or not candidate.content.parts:
                        continue
                    for part in candidate.content.parts:
                        model_parts.append(part)
                        if part.text and not part.thought:
                            yield {"type": "text", "content": part.text}

                calls = [p.function_call for p in model_parts if p.function_call]
                if not model_parts:
                    yield {"type": "error", "content": "The model returned an empty response. Try rephrasing."}
                    break
                # Keep the model turn verbatim (it carries thought signatures needed for tool calling).
                contents.append(types.Content(role="model", parts=model_parts))
                if not calls:
                    break

                response_parts = []
                for call in calls:
                    args = dict(call.args or {})
                    yield {"type": "tool_call", "name": call.name, "args": args}
                    result, is_error = await self.call_tool(call.name, args)
                    preview = result if len(result) <= UI_PREVIEW_CHARS else result[:UI_PREVIEW_CHARS] + "\n... [truncated]"
                    yield {"type": "tool_result", "name": call.name, "result": preview, "is_error": is_error}
                    response_parts.append(
                        types.Part(
                            function_response=types.FunctionResponse(
                                id=call.id,
                                name=call.name,
                                response={"error": result} if is_error else {"result": result},
                            )
                        )
                    )
                contents.append(types.Content(role="user", parts=response_parts))
            else:
                yield {"type": "error", "content": f"Stopped after {MAX_TOOL_STEPS} tool steps."}
        except Exception as e:
            logger.exception("Chat failed")
            yield {"type": "error", "content": f"LLM error: {e}"}

        yield {"type": "done"}

    async def process_user_query(self, message: str, history: list[dict] | None = None) -> dict:
        """Non-streaming wrapper: returns the full answer plus the tool calls that were made."""
        text, tool_calls, errors = [], [], []
        async for event in self.stream_chat(message, history):
            if event["type"] == "text":
                text.append(event["content"])
            elif event["type"] == "tool_call":
                tool_calls.append({"name": event["name"], "args": event["args"]})
            elif event["type"] == "error":
                errors.append(event["content"])
        return {"response": "".join(text) or "\n".join(errors), "tool_calls": tool_calls, "errors": errors}
