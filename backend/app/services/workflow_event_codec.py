"""Serialize WorkflowEvent ORM rows to API records (shared by HTTP and WebSocket)."""

from __future__ import annotations

from app.memory.database import WorkflowEvent
from app.schemas import WorkflowEventRecord


def workflow_event_to_record(event: WorkflowEvent) -> WorkflowEventRecord:
    """Map SQLAlchemy WorkflowEvent to WorkflowEventRecord."""
    return WorkflowEventRecord(
        id=str(event.id),
        shipment_id=str(event.shipment_id),
        event_type=event.event_type,
        stage=event.stage,
        payload=dict(event.payload_json or {}),
        created_at=event.created_at,
    )
