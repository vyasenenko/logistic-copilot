"""WebSocket /ws/events smoke tests."""

import asyncio
import json

from fastapi.testclient import TestClient

from app.main import app
from app.services.freight_realtime import freight_realtime_hub


def test_ws_events_accepts_and_sends_hello_with_version() -> None:
    client = TestClient(app)
    with client.websocket_connect("/ws/events") as ws:
        first = ws.receive_json()
        assert first.get("v") == 1
        assert first.get("type") == "hello"
        assert "protocol" in first or "ts" in first


def test_freight_realtime_hub_broadcast_reaches_open_ws() -> None:
    client = TestClient(app)
    with client.websocket_connect("/ws/events") as ws:
        ws.receive_json()  # hello
        asyncio.run(
            freight_realtime_hub.publish(
                {"v": 1, "type": "unit_test_ping", "ts": "2099-01-01T00:00:00+00:00"}
            )
        )
        raw = ws.receive_text()
        msg = json.loads(raw)
        assert msg.get("type") == "unit_test_ping"
