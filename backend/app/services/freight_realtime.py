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
from uuid import UUID

from fastapi import WebSocket

from app.schemas import WorkflowEventRecord
from app.services.workflow_event_codec import workflow_event_to_record

# Protocol version for hello payload; bump when breaking envelope shape.
PROTOCOL_VERSION = 1


class FreightRealtimeHub:
    """Keeps active WebSocket connections and broadcasts JSON envelopes."""

    def __init__(self, *, overview_stale_min_interval_s: float = 2.0) -> None:
        self._connections: dict[UUID, set[WebSocket]] = {}
        self._socket_organizations: dict[WebSocket, UUID] = {}
        self._lock = asyncio.Lock()
        self._overview_stale_min_interval_s = overview_stale_min_interval_s
        self._last_overview_stale_mono: dict[UUID, float] = {}

    @property
    def connection_count(self) -> int:
        return sum(len(connections) for connections in self._connections.values())

    async def register(self, websocket: WebSocket, *, organization_id: UUID) -> None:
        async with self._lock:
            self._connections.setdefault(organization_id, set()).add(websocket)
            self._socket_organizations[websocket] = organization_id

    async def unregister(self, websocket: WebSocket) -> None:
        async with self._lock:
            organization_id = self._socket_organizations.pop(websocket, None)
            if organization_id is None:
                return
            connections = self._connections.get(organization_id)
            if connections is None:
                return
            connections.discard(websocket)
            if not connections:
                self._connections.pop(organization_id, None)
                self._last_overview_stale_mono.pop(organization_id, None)

    def _now_ts(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    async def publish(self, envelope: dict[str, Any], *, organization_id: UUID | None) -> None:
        """Send JSON to subscribers in one organization; drop broken sockets."""
        if organization_id is None:
            return
        text = json.dumps(envelope, default=str)
        async with self._lock:
            targets = tuple(self._connections.get(organization_id, ()))
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.get(organization_id, set()).discard(ws)
                    self._socket_organizations.pop(ws, None)

    async def publish_workflow_event_record(self, record: WorkflowEventRecord, *, organization_id: UUID | None) -> None:
        """Broadcast one workflow event payload (no overview signal)."""
        await self.publish(
            {
                "v": PROTOCOL_VERSION,
                "type": "workflow_event",
                "ts": self._now_ts(),
                "shipment_id": record.shipment_id,
                "event": record.model_dump(mode="json"),
            },
            organization_id=organization_id,
        )

    async def notify_workflow_event(self, event: Any) -> None:
        """Broadcast a persisted WorkflowEvent ORM row and throttle overview_stale."""
        organization_id = getattr(event, "organization_id", None)
        await self.publish_workflow_event_record(workflow_event_to_record(event), organization_id=organization_id)
        await self.publish_overview_stale_throttled(reason="workflow_event", organization_id=organization_id)

    async def notify_workflow_events(self, events: list[Any]) -> None:
        """Multiple events from the same transaction; one overview_stale signal."""
        touched_organizations: set[UUID] = set()
        for ev in events:
            organization_id = getattr(ev, "organization_id", None)
            await self.publish_workflow_event_record(workflow_event_to_record(ev), organization_id=organization_id)
            if organization_id is not None:
                touched_organizations.add(organization_id)
        for organization_id in touched_organizations:
            await self.publish_overview_stale_throttled(reason="workflow_event", organization_id=organization_id)

    async def publish_overview_stale_throttled(
        self,
        *,
        organization_id: UUID | None,
        reason: str | None = None,
    ) -> None:
        """Signal clients to refetch overview/review queues (rate-limited)."""
        if organization_id is None:
            return
        now = time.monotonic()
        async with self._lock:
            last_sent = self._last_overview_stale_mono.get(organization_id, 0.0)
            if now - last_sent < self._overview_stale_min_interval_s:
                return
            self._last_overview_stale_mono[organization_id] = now
        await self.publish(
            {
                "v": PROTOCOL_VERSION,
                "type": "overview_stale",
                "ts": self._now_ts(),
                "reason": reason,
            },
            organization_id=organization_id,
        )

    async def publish_shipment_updated(
        self,
        *,
        organization_id: UUID | None,
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
            },
            organization_id=organization_id,
        )
        await self.publish_overview_stale_throttled(reason="shipment_updated", organization_id=organization_id)


freight_realtime_hub = FreightRealtimeHub()
