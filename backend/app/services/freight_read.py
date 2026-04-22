"""Shared read-only freight queries for API routes and agent tools."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.memory.database import (
    Carrier,
    CarrierBid,
    Client,
    EmailMessage,
    EmailThread,
    Shipment,
    WorkflowEvent,
)
from app.schemas import (
    FreightOverviewCounts,
    FreightOverviewResponse,
    FreightSlaSummary,
    FreightStatusMetrics,
    ShipmentStage,
    WorkflowEventType,
)

STATUS_ACTIVE_SHIPMENT_STATES = {
    ShipmentStage.BOOKED.value,
    ShipmentStage.BOOKING_IN_PROGRESS.value,
    ShipmentStage.AWAITING_CONFIRMATION.value,
}


def _status_event_cutoff(*, now: datetime) -> datetime:
    return now - timedelta(hours=settings.status_sla_hours_default)


def is_status_stale(
    *,
    shipment_status: str,
    last_status_event_at: datetime | None,
    now: datetime,
) -> bool:
    if shipment_status not in STATUS_ACTIVE_SHIPMENT_STATES:
        return False
    if last_status_event_at is None:
        return True
    return last_status_event_at < _status_event_cutoff(now=now)


async def status_metrics_summary(session: AsyncSession) -> FreightStatusMetrics:
    result = await session.execute(
        select(WorkflowEvent.event_type, WorkflowEvent.payload_json, WorkflowEvent.created_at, Shipment.id, Shipment.status)
        .join(Shipment, Shipment.id == WorkflowEvent.shipment_id)
        .where(Shipment.is_archived.is_(False))
        .order_by(WorkflowEvent.created_at.desc())
    )
    metrics = FreightStatusMetrics()
    latest_status_event_at: dict[UUID, datetime] = {}
    now = datetime.now(timezone.utc)

    for event_type, payload_json, created_at, shipment_id, shipment_status in result.all():
        payload = dict(payload_json or {})
        audit_kind = str(payload.get("status_audit_kind") or "")
        if event_type == WorkflowEventType.TMS_STATUS_LOOKUP.value:
            metrics.lookups += 1
        elif event_type == WorkflowEventType.CUSTOMER_STATUS_SENT.value:
            if payload.get("dry_run"):
                metrics.replies_drafted += 1
            else:
                metrics.replies_sent += 1
        elif event_type == WorkflowEventType.TMS_STATUS_UPDATED.value:
            if audit_kind == "carrier_update_parsed":
                metrics.carrier_updates_parsed += 1
            else:
                metrics.carrier_updates_pushed += 1
        elif event_type == WorkflowEventType.MANUAL_REVIEW_REQUIRED.value and "status" in str(payload.get("review_type") or ""):
            metrics.review_required += 1

        if shipment_id not in latest_status_event_at and event_type in {
            WorkflowEventType.TMS_STATUS_LOOKUP.value,
            WorkflowEventType.CUSTOMER_STATUS_SENT.value,
            WorkflowEventType.TMS_STATUS_UPDATED.value,
        }:
            latest_status_event_at[shipment_id] = created_at

    shipment_result = await session.execute(select(Shipment.id, Shipment.status).where(Shipment.is_archived.is_(False)))
    for shipment_id, shipment_status in shipment_result.all():
        if is_status_stale(
            shipment_status=shipment_status,
            last_status_event_at=latest_status_event_at.get(shipment_id),
            now=now,
        ):
            metrics.stale_shipments += 1

    return metrics


async def build_freight_overview(session: AsyncSession) -> FreightOverviewResponse:
    """Return current freight data footprint and shipment stage distribution."""
    counts = FreightOverviewCounts(
        clients=await session.scalar(select(func.count()).select_from(Client)) or 0,
        carriers=await session.scalar(select(func.count()).select_from(Carrier)) or 0,
        email_threads=await session.scalar(select(func.count()).select_from(EmailThread)) or 0,
        email_messages=await session.scalar(select(func.count()).select_from(EmailMessage)) or 0,
        shipments=await session.scalar(select(func.count()).select_from(Shipment).where(Shipment.is_archived.is_(False))) or 0,
        bids=await session.scalar(select(func.count()).select_from(CarrierBid)) or 0,
        workflow_events=await session.scalar(select(func.count()).select_from(WorkflowEvent)) or 0,
    )

    result = await session.execute(
        select(Shipment.status, func.count(Shipment.id))
        .where(Shipment.is_archived.is_(False))
        .group_by(Shipment.status)
        .order_by(Shipment.status)
    )
    active_stages = {str(status): total for status, total in result.all()}
    status_metrics = await status_metrics_summary(session)

    return FreightOverviewResponse(
        counts=counts,
        active_stages=active_stages,
        status_metrics=status_metrics,
        sla=FreightSlaSummary(status_stale_after_hours=settings.status_sla_hours_default),
        integrations={
            "email_provider": "outlook",
            "quote_wait_minutes_default": str(settings.quote_wait_minutes_default),
        },
    )


async def list_shipments_brief(session: AsyncSession, *, limit: int = 80) -> list[dict]:
    """Lightweight shipment rows for agents (no enrichment join fan-out)."""
    lim = max(1, min(limit, 200))
    result = await session.execute(
        select(Shipment).where(Shipment.is_archived.is_(False)).order_by(Shipment.created_at.desc()).limit(lim)
    )
    rows: list[dict] = []
    for s in result.scalars().all():
        rows.append(
            {
                "id": str(s.id),
                "status": s.status,
                "origin": s.origin,
                "destination": s.destination,
                "client_id": str(s.client_id) if s.client_id else None,
                "quote_token": s.quote_token,
                "equipment_type": s.equipment_type,
                "pallets": s.pallets,
                "weight_lb": s.weight_lb,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            }
        )
    return rows


async def get_shipment_brief(session: AsyncSession, shipment_id: UUID) -> dict | None:
    """Single shipment core fields (no enrichment)."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        return None
    return {
        "id": str(shipment.id),
        "status": shipment.status,
        "origin": shipment.origin,
        "destination": shipment.destination,
        "client_id": str(shipment.client_id) if shipment.client_id else None,
        "email_thread_id": str(shipment.email_thread_id) if shipment.email_thread_id else None,
        "quote_token": shipment.quote_token,
        "equipment_type": shipment.equipment_type,
        "pallets": shipment.pallets,
        "weight_lb": shipment.weight_lb,
        "ready_at": shipment.ready_at.isoformat() if shipment.ready_at else None,
        "ready_at_local": shipment.ready_at_local.isoformat() if shipment.ready_at_local else None,
        "delivery_at": shipment.delivery_at.isoformat() if shipment.delivery_at else None,
        "delivery_at_local": shipment.delivery_at_local.isoformat() if shipment.delivery_at_local else None,
        "notes": shipment.notes,
        "margin_policy": dict(shipment.margin_policy_json or {}),
        "created_at": shipment.created_at.isoformat() if shipment.created_at else None,
        "updated_at": shipment.updated_at.isoformat() if shipment.updated_at else None,
    }
