import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.mcp_client import MCPClientManager

router = APIRouter(prefix="/api", tags=["Chat"])


class HistoryMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[HistoryMessage] = Field(default_factory=list)


class ToolCall(BaseModel):
    name: str
    args: dict


class ChatResponse(BaseModel):
    response: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def get_manager(request: Request) -> MCPClientManager:
    return request.app.state.mcp


def _validate(body: ChatRequest) -> None:
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Query message cannot be empty.")


@router.post("/chat", response_model=ChatResponse)
async def chat_with_assistant(body: ChatRequest, request: Request):
    """Returns the complete answer in one JSON response."""
    _validate(body)
    result = await get_manager(request).process_user_query(
        body.message, [m.model_dump() for m in body.history]
    )
    return ChatResponse(**result)


@router.post("/chat/stream")
async def chat_stream(body: ChatRequest, request: Request):
    """Streams the answer as newline-delimited JSON events (text / tool_call / tool_result / error / done)."""
    _validate(body)
    manager = get_manager(request)
    history = [m.model_dump() for m in body.history]

    async def events():
        async for event in manager.stream_chat(body.message, history):
            yield json.dumps(event) + "\n"

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/tools")
async def list_tools(request: Request):
    manager = get_manager(request)
    return {"servers": manager.server_status, "tools": manager.describe_tools()}
