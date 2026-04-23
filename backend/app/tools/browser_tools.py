"""Read-only browser page context tools for the agent."""

from __future__ import annotations

import json

from langchain_core.tools import tool

from app.agent.runtime import get_current_conversation_id
from app.memory.database import async_session
from app.services.browser_context import (
    build_browser_context_excerpt,
    get_browser_context_by_conversation_id,
)


def _json(obj) -> str:
    return json.dumps(obj, indent=2, default=str, ensure_ascii=False)


async def _load_context() -> dict | None:
    conversation_id = get_current_conversation_id()
    if conversation_id is None:
        return None
    async with async_session() as session:
        return await get_browser_context_by_conversation_id(session, conversation_id)


@tool
async def browser_get_current_page_context() -> str:
    """Get the latest stored browser page context for the current conversation."""
    context = await _load_context()
    if context is None:
        return _json({"available": False, "reason": "No browser page context stored for this conversation."})
    snapshot = context.get("page_snapshot")
    if not isinstance(snapshot, dict):
        return _json({"available": False, "reason": "Browser page context is unavailable."})
    return _json(
        {
            "available": True,
            "page_snapshot": snapshot,
            "attach_hint": bool(context.get("attach_hint")),
            "updated_at": context.get("updated_at"),
        }
    )


@tool
async def browser_get_current_page_excerpt() -> str:
    """Get a compact excerpt of the latest stored browser page context for the current conversation."""
    context = await _load_context()
    return _json(build_browser_context_excerpt(context))


def get_browser_tools():
    return [
        browser_get_current_page_context,
        browser_get_current_page_excerpt,
    ]
