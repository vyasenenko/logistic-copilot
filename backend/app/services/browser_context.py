"""Conversation-scoped browser page context storage and normalization."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.database import Conversation

PAGE_TEXT_LIMIT = 6000
SELECTION_LIMIT = 1200
HEADINGS_LIMIT = 12
ACTION_LABELS_LIMIT = 24


def _clean_text(value: Any, *, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    text = " ".join(value.replace("\u00a0", " ").split())
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}…"


def _clean_list(values: Any, *, limit: int, item_limit: int) -> list[str]:
    if not isinstance(values, Iterable) or isinstance(values, (str, bytes, dict)):
        return []
    cleaned: list[str] = []
    for value in values:
        item = _clean_text(value, limit=item_limit)
        if item and item not in cleaned:
            cleaned.append(item)
        if len(cleaned) >= limit:
            break
    return cleaned


def _derive_page_type_hint(snapshot: dict[str, Any]) -> str | None:
    hint = _clean_text(snapshot.get("page_type_hint"), limit=80)
    if hint:
        return hint
    action_labels = snapshot.get("action_labels") or []
    headings = snapshot.get("headings") or []
    if action_labels and len(action_labels) >= 3:
        return "interactive_app"
    if headings and len(headings) >= 5:
        return "content_heavy"
    if snapshot.get("selection_text"):
        return "selected_text_focus"
    return None


def normalize_page_snapshot(raw_snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(raw_snapshot, dict):
        return None
    url = _clean_text(raw_snapshot.get("url"), limit=1000)
    title = _clean_text(raw_snapshot.get("title"), limit=300)
    origin = _clean_text(raw_snapshot.get("origin"), limit=300)
    unavailable_reason = _clean_text(raw_snapshot.get("unavailable_reason"), limit=400)
    snapshot: dict[str, Any] = {
        "url": url,
        "title": title,
        "origin": origin,
        "captured_at": _clean_text(raw_snapshot.get("captured_at"), limit=80)
        or datetime.now(timezone.utc).isoformat(),
        "selection_text": _clean_text(raw_snapshot.get("selection_text"), limit=SELECTION_LIMIT),
        "visible_text_excerpt": _clean_text(raw_snapshot.get("visible_text_excerpt"), limit=PAGE_TEXT_LIMIT),
        "headings": _clean_list(raw_snapshot.get("headings"), limit=HEADINGS_LIMIT, item_limit=180),
        "meta_description": _clean_text(raw_snapshot.get("meta_description"), limit=500),
        "action_labels": _clean_list(raw_snapshot.get("action_labels"), limit=ACTION_LABELS_LIMIT, item_limit=120),
        "page_type_hint": None,
        "unavailable_reason": unavailable_reason or None,
    }
    snapshot["page_type_hint"] = _derive_page_type_hint(snapshot)
    if not any(
        [
            snapshot["url"],
            snapshot["title"],
            snapshot["selection_text"],
            snapshot["visible_text_excerpt"],
            snapshot["headings"],
            snapshot["action_labels"],
            snapshot["unavailable_reason"],
        ]
    ):
        return None
    return snapshot


def normalize_browser_context(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    snapshot = normalize_page_snapshot(payload.get("page_snapshot"))
    if snapshot is None:
        return None
    attach_hint = bool(payload.get("attach_hint"))
    return {
        "page_snapshot": snapshot,
        "attach_hint": attach_hint,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


async def save_browser_context(
    session: AsyncSession,
    conversation: Conversation,
    payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    normalized = normalize_browser_context(payload)
    if normalized is None:
        return None
    metadata = dict(conversation.metadata_json or {})
    metadata["browser_context"] = normalized
    conversation.metadata_json = metadata
    conversation.updated_at = datetime.now(timezone.utc)
    await session.commit()
    return normalized


def get_browser_context(conversation: Conversation | None) -> dict[str, Any] | None:
    if conversation is None:
        return None
    metadata = dict(conversation.metadata_json or {})
    context = metadata.get("browser_context")
    return context if isinstance(context, dict) else None


async def get_browser_context_by_conversation_id(
    session: AsyncSession,
    conversation_id: UUID,
) -> dict[str, Any] | None:
    conversation = await session.get(Conversation, conversation_id)
    return get_browser_context(conversation)


def browser_context_hint_text(context: dict[str, Any] | None) -> str | None:
    if not isinstance(context, dict) or not context.get("attach_hint"):
        return None
    snapshot = context.get("page_snapshot") or {}
    if not isinstance(snapshot, dict):
        return "Current browser page context is available via tools for this conversation."
    title = snapshot.get("title") or "current page"
    url = snapshot.get("url") or ""
    if url:
        return (
            "Current browser page context is available via tools for this conversation. "
            f"Active page: {title} ({url})."
        )
    return f"Current browser page context is available via tools for this conversation. Active page: {title}."


def build_browser_context_excerpt(context: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(context, dict):
        return {"available": False, "reason": "No browser page context stored for this conversation."}
    snapshot = context.get("page_snapshot") or {}
    if not isinstance(snapshot, dict):
        return {"available": False, "reason": "Browser page context is malformed."}
    excerpt = {
        "available": True,
        "title": snapshot.get("title"),
        "url": snapshot.get("url"),
        "origin": snapshot.get("origin"),
        "captured_at": snapshot.get("captured_at"),
        "page_type_hint": snapshot.get("page_type_hint"),
        "selection_text": snapshot.get("selection_text"),
        "visible_text_excerpt": snapshot.get("visible_text_excerpt"),
        "headings": list(snapshot.get("headings") or [])[:8],
        "action_labels": list(snapshot.get("action_labels") or [])[:12],
        "meta_description": snapshot.get("meta_description"),
        "unavailable_reason": snapshot.get("unavailable_reason"),
        "stale": False,
    }
    captured_at_raw = snapshot.get("captured_at")
    try:
        captured_at = datetime.fromisoformat(str(captured_at_raw).replace("Z", "+00:00"))
        if captured_at.tzinfo is None:
            captured_at = captured_at.replace(tzinfo=timezone.utc)
        excerpt["stale"] = (datetime.now(timezone.utc) - captured_at).total_seconds() > 300
    except Exception:
        excerpt["stale"] = True
    return excerpt
