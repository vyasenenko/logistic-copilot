"""Shared read-only freight queries for API routes and agent tools."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, or_, select
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


def _shipment_brief_row(shipment: Shipment) -> dict:
    origin = shipment.origin or "Origin TBD"
    destination = shipment.destination or "Destination TBD"
    return {
        "id": str(shipment.id),
        "status": shipment.status,
        "origin": shipment.origin,
        "destination": shipment.destination,
        "route": f"{origin} -> {destination}",
        "client_id": str(shipment.client_id) if shipment.client_id else None,
        "email_thread_id": str(shipment.email_thread_id) if shipment.email_thread_id else None,
        "quote_token": shipment.quote_token,
        "equipment_type": shipment.equipment_type,
        "pallets": shipment.pallets,
        "weight_lb": shipment.weight_lb,
        "ready_at": shipment.ready_at.isoformat() if shipment.ready_at else None,
        "ready_at_local": shipment.ready_at_local.isoformat() if shipment.ready_at_local else None,
        "ready_at_display": shipment.ready_at_local.isoformat(timespec="minutes") if shipment.ready_at_local else None,
        "delivery_at": shipment.delivery_at.isoformat() if shipment.delivery_at else None,
        "delivery_at_local": shipment.delivery_at_local.isoformat() if shipment.delivery_at_local else None,
        "delivery_at_display": shipment.delivery_at_local.isoformat(timespec="minutes") if shipment.delivery_at_local else None,
        "notes": shipment.notes,
        "margin_policy": dict(shipment.margin_policy_json or {}),
        "is_archived": bool(shipment.is_archived),
        "archive_reason_code": shipment.archive_reason_code or ("other" if shipment.is_archived else None),
        "archive_reason_note": shipment.archive_reason_note or shipment.archived_reason,
        "archived_reason": shipment.archived_reason,
        "archived_at": shipment.archived_at.isoformat() if shipment.archived_at else None,
        "created_at": shipment.created_at.isoformat() if shipment.created_at else None,
        "updated_at": shipment.updated_at.isoformat() if shipment.updated_at else None,
    }


async def get_shipment_brief(session: AsyncSession, shipment_id: UUID) -> dict | None:
    """Single shipment core fields (no enrichment)."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None or shipment.is_archived:
        return None
    return _shipment_brief_row(shipment)


async def get_archived_shipment_brief(session: AsyncSession, shipment_id: UUID) -> dict | None:
    """Single archived shipment core fields."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None or not shipment.is_archived:
        return None
    return _shipment_brief_row(shipment)


async def get_shipment_brief_by_token(session: AsyncSession, quote_token: str) -> dict | None:
    """Single shipment core fields by quote token."""
    normalized = quote_token.strip().upper()
    if not normalized:
        return None
    shipment = await session.scalar(
        select(Shipment).where(
            Shipment.is_archived.is_(False),
            func.upper(Shipment.quote_token) == normalized,
        )
    )
    return _shipment_brief_row(shipment) if shipment else None


async def search_shipments_brief(
    session: AsyncSession,
    *,
    query: str,
    status: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Search active shipments by token, lane, equipment, notes, or status."""
    lim = max(1, min(limit, 200))
    q = f"%{query.strip()}%" if query.strip() else "%"
    conditions = [
        Shipment.is_archived.is_(False),
        or_(
            Shipment.quote_token.ilike(q),
            Shipment.origin.ilike(q),
            Shipment.destination.ilike(q),
            Shipment.equipment_type.ilike(q),
            Shipment.notes.ilike(q),
            Shipment.status.ilike(q),
        ),
    ]
    if status:
        conditions.append(Shipment.status == status)
    result = await session.execute(
        select(Shipment)
        .where(*conditions)
        .order_by(Shipment.updated_at.desc(), Shipment.created_at.desc())
        .limit(lim)
    )
    return [_shipment_brief_row(shipment) for shipment in result.scalars().all()]


def _matches_today_window(shipment: Shipment, *, now: datetime) -> bool:
    reference = shipment.ready_at_local or shipment.created_at
    if reference is None:
        return False
    return reference.date() == now.date()


async def list_today_shipments_brief(
    session: AsyncSession,
    *,
    status: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """List shipments for today's board using pickup-local date with created_at fallback."""
    lim = max(1, min(limit, 200))
    result = await session.execute(
        select(Shipment)
        .where(Shipment.is_archived.is_(False))
        .order_by(Shipment.updated_at.desc(), Shipment.created_at.desc())
        .limit(500)
    )
    now = datetime.now(timezone.utc)
    rows: list[dict] = []
    for shipment in result.scalars().all():
        if status and shipment.status != status:
            continue
        if not _matches_today_window(shipment, now=now):
            continue
        rows.append(_shipment_brief_row(shipment))
        if len(rows) >= lim:
            break
    return rows


async def list_shipments_by_city_brief(
    session: AsyncSession,
    *,
    city: str,
    date_scope: str = "today",
    limit: int = 50,
) -> list[dict]:
    """List shipments whose origin or destination contains a city string."""
    lim = max(1, min(limit, 200))
    q = f"%{city.strip()}%"
    result = await session.execute(
        select(Shipment)
        .where(
            Shipment.is_archived.is_(False),
            or_(Shipment.origin.ilike(q), Shipment.destination.ilike(q)),
        )
        .order_by(Shipment.updated_at.desc(), Shipment.created_at.desc())
        .limit(500)
    )
    now = datetime.now(timezone.utc)
    rows: list[dict] = []
    for shipment in result.scalars().all():
        if date_scope == "today" and not _matches_today_window(shipment, now=now):
            continue
        rows.append(_shipment_brief_row(shipment))
        if len(rows) >= lim:
            break
    return rows


async def summarize_shipment_case(session: AsyncSession, quote_token: str) -> dict | None:
    """Compact case summary for agent answers."""
    normalized = quote_token.strip().upper()
    shipment = await session.scalar(
        select(Shipment).where(
            Shipment.is_archived.is_(False),
            func.upper(Shipment.quote_token) == normalized,
        )
    )
    if shipment is None:
        return None
    events_result = await session.execute(
        select(WorkflowEvent)
        .where(WorkflowEvent.shipment_id == shipment.id)
        .order_by(WorkflowEvent.created_at.desc())
        .limit(8)
    )
    bids_result = await session.execute(
        select(CarrierBid)
        .where(CarrierBid.shipment_id == shipment.id)
        .order_by(CarrierBid.amount.asc().nullslast(), CarrierBid.received_at.desc())
    )
    bids = bids_result.scalars().all()
    priced_bids = [bid for bid in bids if bid.amount is not None]
    best_bid = priced_bids[0] if priced_bids else None
    return {
        "shipment": _shipment_brief_row(shipment),
        "bids": {
            "count": len(bids),
            "priced_count": len(priced_bids),
            "best_bid": {
                "id": str(best_bid.id),
                "carrier_id": str(best_bid.carrier_id),
                "amount": best_bid.amount,
                "currency": best_bid.currency,
                "eta_text": best_bid.eta_text,
                "status": best_bid.status,
                "received_at": best_bid.received_at.isoformat() if best_bid.received_at else None,
            }
            if best_bid
            else None,
        },
        "recent_events": [
            {
                "event_type": event.event_type,
                "stage": event.stage,
                "created_at": event.created_at.isoformat() if event.created_at else None,
                "payload": event.payload_json or {},
            }
            for event in events_result.scalars().all()
        ],
    }


async def search_archived_shipments_brief(
    session: AsyncSession,
    *,
    query: str | None = None,
    reason_code: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Search archived shipments only."""
    lim = max(1, min(limit, 200))
    result = await session.execute(
        select(Shipment)
        .where(Shipment.is_archived.is_(True))
        .order_by(Shipment.archived_at.desc().nullslast(), Shipment.created_at.desc())
        .limit(500)
    )
    q = (query or "").strip().lower()
    rows: list[dict] = []
    for shipment in result.scalars().all():
        code = shipment.archive_reason_code or "other"
        if reason_code and code != reason_code:
            continue
        if q:
            haystack = " ".join(
                [
                    shipment.origin or "",
                    shipment.destination or "",
                    shipment.quote_token or "",
                    str(shipment.email_thread_id or ""),
                    shipment.archived_reason or "",
                    shipment.archive_reason_note or "",
                    code,
                ]
            ).lower()
            if q not in haystack:
                continue
        rows.append(_shipment_brief_row(shipment))
        if len(rows) >= lim:
            break
    return rows


async def get_archived_shipment_brief_by_token(session: AsyncSession, quote_token: str) -> dict | None:
    """Single archived shipment by quote token."""
    normalized = quote_token.strip().upper()
    if not normalized:
        return None
    shipment = await session.scalar(
        select(Shipment).where(
            Shipment.is_archived.is_(True),
            func.upper(Shipment.quote_token) == normalized,
        )
    )
    return _shipment_brief_row(shipment) if shipment else None


async def summarize_archived_shipment_case(session: AsyncSession, quote_token: str) -> dict | None:
    """Compact archived case summary for agent answers."""
    normalized = quote_token.strip().upper()
    shipment = await session.scalar(
        select(Shipment).where(
            Shipment.is_archived.is_(True),
            func.upper(Shipment.quote_token) == normalized,
        )
    )
    if shipment is None:
        return None
    events_result = await session.execute(
        select(WorkflowEvent)
        .where(WorkflowEvent.shipment_id == shipment.id)
        .order_by(WorkflowEvent.created_at.desc())
        .limit(8)
    )
    return {
        "shipment": _shipment_brief_row(shipment),
        "recent_events": [
            {
                "event_type": event.event_type,
                "stage": event.stage,
                "created_at": event.created_at.isoformat() if event.created_at else None,
                "payload": event.payload_json or {},
            }
            for event in events_result.scalars().all()
        ],
    }
