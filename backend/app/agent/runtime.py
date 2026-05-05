"""Runtime-scoped context shared with agent tools."""

from __future__ import annotations

from contextvars import ContextVar
from uuid import UUID

from app.services.auth import CurrentUserContext

_current_conversation_id: ContextVar[UUID | None] = ContextVar("current_conversation_id", default=None)
_current_user_context: ContextVar[CurrentUserContext | None] = ContextVar("current_user_context", default=None)


def set_current_conversation_id(conversation_id: UUID | None):
    return _current_conversation_id.set(conversation_id)


def reset_current_conversation_id(token) -> None:
    _current_conversation_id.reset(token)


def get_current_conversation_id() -> UUID | None:
    return _current_conversation_id.get()


def set_current_user_context(context: CurrentUserContext | None):
    return _current_user_context.set(context)


def reset_current_user_context(token) -> None:
    _current_user_context.reset(token)


def get_current_user_context() -> CurrentUserContext | None:
    return _current_user_context.get()
