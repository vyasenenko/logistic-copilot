"""Runtime-scoped context shared with agent tools."""

from __future__ import annotations

from contextvars import ContextVar
from uuid import UUID

_current_conversation_id: ContextVar[UUID | None] = ContextVar("current_conversation_id", default=None)


def set_current_conversation_id(conversation_id: UUID | None):
    return _current_conversation_id.set(conversation_id)


def reset_current_conversation_id(token) -> None:
    _current_conversation_id.reset(token)


def get_current_conversation_id() -> UUID | None:
    return _current_conversation_id.get()
