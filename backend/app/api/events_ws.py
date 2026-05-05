"""WebSocket endpoint for live Freight dashboard updates.

Deploying behind a reverse proxy: forward Upgrade and Connection headers and disable buffering
for this path. Multiple uvicorn workers require a shared pub/sub (e.g. Redis); see freight_realtime hub.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import settings
from app.memory.database import async_session
from app.services.freight_realtime import PROTOCOL_VERSION, freight_realtime_hub
from app.services.auth import get_current_user_context_for_token

router = APIRouter()


def _origin_allowed(origin: str | None) -> bool:
    """Match browser Origin header to the same list used for HTTP CORS."""
    if not origin:
        return True
    allowed = settings.cors_origins
    if not allowed:
        return False
    return "*" in allowed or origin in allowed


@router.websocket("/ws/events")
async def websocket_events(websocket: WebSocket) -> None:
    """Accept dashboard/event streams; keeps connection alive with JSON heartbeats."""
    origin = websocket.headers.get("origin")
    if not _origin_allowed(origin):
        await websocket.close(code=1008, reason="origin not allowed")
        return
    raw_token = (websocket.query_params.get("token") or "").strip()
    if not raw_token:
        await websocket.close(code=1008, reason="authentication required")
        return
    try:
        async with async_session() as session:
            context = await get_current_user_context_for_token(raw_token, session)
    except Exception:
        await websocket.close(code=1008, reason="invalid session")
        return

    await websocket.accept()
    await freight_realtime_hub.register(websocket, organization_id=context.organization_id)
    await websocket.send_text(
        json.dumps(
            {
                "v": PROTOCOL_VERSION,
                "type": "hello",
                "ts": datetime.now(timezone.utc).isoformat(),
                "protocol": PROTOCOL_VERSION,
                "organization_id": str(context.organization_id),
            }
        )
    )
    try:
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive(), timeout=30.0)
            except TimeoutError:
                await websocket.send_text(
                    json.dumps(
                        {
                            "v": PROTOCOL_VERSION,
                            "type": "heartbeat",
                            "ts": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                )
                continue
            if msg.get("type") == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        pass
    finally:
        await freight_realtime_hub.unregister(websocket)
