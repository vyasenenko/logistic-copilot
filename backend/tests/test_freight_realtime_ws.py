"""WebSocket /ws/events smoke tests."""

import asyncio
import json
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api import events_ws
from app.main import app
from app.services.freight_realtime import freight_realtime_hub
from app.services.auth import CurrentUserContext


def _context_for_org(organization_id: UUID) -> CurrentUserContext:
    return CurrentUserContext(
        user_id=uuid4(),
        organization_id=organization_id,
        role="admin",
        permissions=("dashboard:read", "freight:read", "members:invite"),
        session_id=uuid4(),
        email="admin@example.com",
    )


def test_ws_events_rejects_missing_token() -> None:
    client = TestClient(app)
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/events"):
            pass


def test_ws_events_accepts_token_and_sends_org_hello(monkeypatch) -> None:
    organization_id = uuid4()

    async def fake_context_for_token(raw_token, session):
        assert raw_token == "test-token"
        return _context_for_org(organization_id)

    monkeypatch.setattr(events_ws, "get_current_user_context_for_token", fake_context_for_token)
    client = TestClient(app)
    with client.websocket_connect("/ws/events?token=test-token") as ws:
        first = ws.receive_json()
        assert first.get("v") == 1
        assert first.get("type") == "hello"
        assert first.get("organization_id") == str(organization_id)
        assert "protocol" in first or "ts" in first


def test_freight_realtime_hub_broadcast_reaches_same_org_ws(monkeypatch) -> None:
    organization_id = uuid4()

    async def fake_context_for_token(raw_token, session):
        return _context_for_org(organization_id)

    monkeypatch.setattr(events_ws, "get_current_user_context_for_token", fake_context_for_token)
    client = TestClient(app)
    with client.websocket_connect("/ws/events?token=test-token") as ws:
        ws.receive_json()  # hello
        asyncio.run(
            freight_realtime_hub.publish(
                {"v": 1, "type": "unit_test_ping", "ts": "2099-01-01T00:00:00+00:00"},
                organization_id=organization_id,
            )
        )
        raw = ws.receive_text()
        msg = json.loads(raw)
        assert msg.get("type") == "unit_test_ping"
