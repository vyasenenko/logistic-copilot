"""
In-process real-time hub for Freight dashboard WebSocket clients.

Envelope (JSON text frames), version v=1:
- Common: v (int), type (str), ts (UTC ISO-8601 string).
- hello: protocol (int, same as v).
- heartbeat: no extra fields.
- workflow_event: shipment_id (str), event (WorkflowEventRecord dict: id, shipment_id,
  event_type, stage, payload, created_at).
- overview_stale: reason (str | null) — clients refetch /api/freight/overview and queues.
- shipment_updated: shipment_id (str), fields (str[], optional) — local row changed without
  a new workflow_events row.

Multi-worker: replace publish with Redis pub/sub when scaling beyond one uvicorn process.
Reverse-proxy: ensure Upgrade and Connection headers pass through for /ws/events.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

from app.schemas import WorkflowEventRecord
from app.services.workflow_event_codec import workflow_event_to_record

# Protocol version for hello payload; bump when breaking envelope shape.
PROTOCOL_VERSION = 1


class FreightRealtimeHub:
    """Keeps active WebSocket connections and broadcasts JSON envelopes."""

    def __init__(self, *, overview_stale_min_interval_s: float = 2.0) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._overview_stale_min_interval_s = overview_stale_min_interval_s
        self._last_overview_stale_mono: float = 0.0

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    async def register(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.add(websocket)

    async def unregister(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)

    def _now_ts(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    async def publish(self, envelope: dict[str, Any]) -> None:
        """Send JSON to all subscribers; drop broken sockets."""
        text = json.dumps(envelope, default=str)
        async with self._lock:
            targets = tuple(self._connections)
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.discard(ws)

    async def publish_workflow_event_record(self, record: WorkflowEventRecord) -> None:
        """Broadcast one workflow event payload (no overview signal)."""
        await self.publish(
            {
                "v": PROTOCOL_VERSION,
                "type": "workflow_event",
                "ts": self._now_ts(),
                "shipment_id": record.shipment_id,
                "event": record.model_dump(mode="json"),
            }
        )

    async def notify_workflow_event(self, event: Any) -> None:
        """Broadcast a persisted WorkflowEvent ORM row and throttle overview_stale."""
        await self.publish_workflow_event_record(workflow_event_to_record(event))
        await self.publish_overview_stale_throttled(reason="workflow_event")

    async def notify_workflow_events(self, events: list[Any]) -> None:
        """Multiple events from the same transaction; one overview_stale signal."""
        for ev in events:
            await self.publish_workflow_event_record(workflow_event_to_record(ev))
        if events:
            await self.publish_overview_stale_throttled(reason="workflow_event")

    async def publish_overview_stale_throttled(self, *, reason: str | None = None) -> None:
        """Signal clients to refetch overview/review queues (rate-limited)."""
        now = time.monotonic()
        async with self._lock:
            if now - self._last_overview_stale_mono < self._overview_stale_min_interval_s:
                return
            self._last_overview_stale_mono = now
        await self.publish(
            {
                "v": PROTOCOL_VERSION,
                "type": "overview_stale",
                "ts": self._now_ts(),
                "reason": reason,
            }
        )

    async def publish_shipment_updated(
        self,
        *,
        shipment_id: str,
        fields: list[str] | None = None,
    ) -> None:
        """When shipment row changed without a new WorkflowEvent row."""
        await self.publish(
            {
                "v": PROTOCOL_VERSION,
                "type": "shipment_updated",
                "ts": self._now_ts(),
                "shipment_id": shipment_id,
                "fields": fields or [],
            }
        )
        await self.publish_overview_stale_throttled(reason="shipment_updated")


freight_realtime_hub = FreightRealtimeHub()
