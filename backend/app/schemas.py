"""AI Agent Backend — Pydantic schemas for API."""

from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Role(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class MessageRequest(BaseModel):
    """Incoming message from the user."""

    content: str = Field(..., min_length=1, max_length=50_000)
    conversation_id: UUID | None = None


class ToolCall(BaseModel):
    """A tool call made by the agent during reasoning."""

    tool_name: str
    tool_input: dict
    tool_output: str | None = None


class MessageResponse(BaseModel):
    """Response message from the agent."""

    id: UUID = Field(default_factory=uuid4)
    conversation_id: UUID
    role: Role = Role.ASSISTANT
    content: str
    tool_calls: list[ToolCall] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)


class StreamEvent(BaseModel):
    """Server-sent event during streaming."""

    event: str  # "token", "tool_start", "tool_end", "done", "error"
    data: str
    conversation_id: UUID | None = None


class ConversationInfo(BaseModel):
    """Summary of a conversation."""

    id: UUID
    title: str
    created_at: datetime
    message_count: int


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
