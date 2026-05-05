"""Shared read-only freight queries for API routes and agent tools."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
import html
import re
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
    NotificationFeedItem,
    NotificationFeedResponse,
    ShipmentThreadMessageRecord,
    ShipmentThreadResponse,
    ShipmentStage,
    WorkflowEventType,
)

STATUS_ACTIVE_SHIPMENT_STATES = {
    ShipmentStage.BOOKED.value,
    ShipmentStage.BOOKING_IN_PROGRESS.value,
    ShipmentStage.AWAITING_CONFIRMATION.value,
}

NOTIFICATION_EVENT_TYPES = {
    WorkflowEventType.EMAIL_RECEIVED.value,
    WorkflowEventType.SHIPMENT_PARSED.value,
    WorkflowEventType.PARSING_COMPLETED.value,
    WorkflowEventType.BID_RECEIVED.value,
    WorkflowEventType.MANUAL_REVIEW_REQUIRED.value,
    WorkflowEventType.CUSTOMER_STATUS_SENT.value,
    WorkflowEventType.TMS_STATUS_INGESTED.value,
    WorkflowEventType.TMS_STATUS_UPDATED.value,
    WorkflowEventType.SHIPMENT_ARCHIVED.value,
    WorkflowEventType.EXCEPTION_RAISED.value,
}


def _clean_message_excerpt(value: str | None) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _message_display_body(message: EmailMessage) -> str:
    payload = dict(message.raw_payload_json or {})
    body = payload.get("body")
    if isinstance(body, dict):
        content = body.get("content")
        if isinstance(content, str) and content.strip():
            return _clean_message_excerpt(content)
    unique_body = payload.get("uniqueBody")
    if isinstance(unique_body, dict):
        content = unique_body.get("content")
        if isinstance(content, str) and content.strip():
            return _clean_message_excerpt(content)
    for key in ("bodyPreview", "content", "textBody"):
        candidate = payload.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return _clean_message_excerpt(candidate)
    return _clean_message_excerpt(message.body_preview)


def _serialize_thread_message(message: EmailMessage) -> ShipmentThreadMessageRecord:
    return ShipmentThreadMessageRecord(
        id=str(message.id),
        thread_id=str(message.thread_id),
        provider_message_id=message.provider_message_id,
        direction=message.direction,
        sender=message.sender,
        recipients=list(message.recipients_json or []),
        subject=message.subject,
        received_at=message.received_at,
        body_preview=message.body_preview or "",
        display_body=_message_display_body(message),
        has_raw_payload=bool(message.raw_payload_json),
    )


def _is_system_thread_message(message: EmailMessage) -> bool:
    sender = (message.sender or "").lower()
    recipients = " ".join(str(item).lower() for item in (message.recipients_json or []))
    combined = f"{sender} {recipients}"
    return any(
        marker in combined
        for marker in ("mailer-daemon", "postmaster", "microsoftexchange", "delivery")
    )


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


async def status_metrics_summary(session: AsyncSession, *, organization_id: UUID | None = None) -> FreightStatusMetrics:
    shipment_filters = [Shipment.is_archived.is_(False)]
    if organization_id is not None:
        shipment_filters.append(Shipment.organization_id == organization_id)
    result = await session.execute(
        select(WorkflowEvent.event_type, WorkflowEvent.payload_json, WorkflowEvent.created_at, Shipment.id, Shipment.status)
        .join(Shipment, Shipment.id == WorkflowEvent.shipment_id)
        .where(*shipment_filters)
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

    shipment_result = await session.execute(select(Shipment.id, Shipment.status).where(*shipment_filters))
    for shipment_id, shipment_status in shipment_result.all():
        if is_status_stale(
            shipment_status=shipment_status,
            last_status_event_at=latest_status_event_at.get(shipment_id),
            now=now,
        ):
            metrics.stale_shipments += 1

    return metrics


async def build_freight_overview(session: AsyncSession, *, organization_id: UUID | None = None) -> FreightOverviewResponse:
    """Return current freight data footprint and shipment stage distribution."""
    client_filters = []
    carrier_filters = []
    thread_filters = []
    message_filters = []
    shipment_filters = [Shipment.is_archived.is_(False)]
    bid_filters = []
    event_filters = []
    if organization_id is not None:
        client_filters.append(Client.organization_id == organization_id)
        carrier_filters.append(Carrier.organization_id == organization_id)
        thread_filters.append(EmailThread.organization_id == organization_id)
        message_filters.append(EmailMessage.organization_id == organization_id)
        shipment_filters.append(Shipment.organization_id == organization_id)
        bid_filters.append(CarrierBid.organization_id == organization_id)
        event_filters.append(WorkflowEvent.organization_id == organization_id)
    counts = FreightOverviewCounts(
        clients=await session.scalar(select(func.count()).select_from(Client).where(*client_filters)) or 0,
        carriers=await session.scalar(select(func.count()).select_from(Carrier).where(*carrier_filters)) or 0,
        email_threads=await session.scalar(select(func.count()).select_from(EmailThread).where(*thread_filters)) or 0,
        email_messages=await session.scalar(select(func.count()).select_from(EmailMessage).where(*message_filters)) or 0,
        shipments=await session.scalar(select(func.count()).select_from(Shipment).where(*shipment_filters)) or 0,
        bids=await session.scalar(select(func.count()).select_from(CarrierBid).where(*bid_filters)) or 0,
        workflow_events=await session.scalar(select(func.count()).select_from(WorkflowEvent).where(*event_filters)) or 0,
    )

    result = await session.execute(
        select(Shipment.status, func.count(Shipment.id))
        .where(*shipment_filters)
        .group_by(Shipment.status)
        .order_by(Shipment.status)
    )
    active_stages = {str(status): total for status, total in result.all()}
    status_metrics = await status_metrics_summary(session, organization_id=organization_id)

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


async def list_notification_feed(
    session: AsyncSession,
    *,
    limit: int = 20,
    offset: int = 0,
    organization_id: UUID | None = None,
) -> NotificationFeedResponse:
    """Build a paginated notification feed from persisted workflow events."""
    safe_limit = max(1, min(limit, 100))
    safe_offset = max(0, offset)

    base_stmt = (
        select(WorkflowEvent, Shipment)
        .join(Shipment, Shipment.id == WorkflowEvent.shipment_id, isouter=True)
        .where(WorkflowEvent.event_type.in_(NOTIFICATION_EVENT_TYPES))
        .order_by(WorkflowEvent.created_at.desc())
    )
    total_stmt = select(func.count()).select_from(WorkflowEvent).where(WorkflowEvent.event_type.in_(NOTIFICATION_EVENT_TYPES))
    if organization_id is not None:
        base_stmt = base_stmt.where(WorkflowEvent.organization_id == organization_id)
        total_stmt = total_stmt.where(WorkflowEvent.organization_id == organization_id)
    total = await session.scalar(total_stmt) or 0
    result = await session.execute(base_stmt.offset(safe_offset).limit(safe_limit + 1))

    rows = result.all()
    items: list[NotificationFeedItem] = []
    for event, shipment in rows[:safe_limit]:
        item = _notification_from_event(event, shipment)
        if item is not None:
            items.append(item)

    return NotificationFeedResponse(
        items=items,
        total=total,
        limit=safe_limit,
        offset=safe_offset,
        has_more=len(rows) > safe_limit,
    )


SHIPMENT_LIST_DATE_SCOPES = {"today", "last_2_days", "last_7_days", "current_month", "last_30_days", "all"}
SHIPMENT_LIST_DATE_FIELDS = {"created_at", "updated_at", "ready_at_local"}
SHIPMENT_QUERY_SORT_FIELDS = {"created_at", "updated_at", "ready_at_local", "date_field"}


def normalize_shipment_date_scope(date_scope: str | None) -> str:
    scope = (date_scope or "last_7_days").strip().lower()
    return scope if scope in SHIPMENT_LIST_DATE_SCOPES else "last_7_days"


def normalize_shipment_date_field(date_field: str | None) -> str:
    field = (date_field or "created_at").strip().lower()
    return field if field in SHIPMENT_LIST_DATE_FIELDS else "created_at"


def normalize_shipment_sort_field(sort_by: str | None) -> str:
    field = (sort_by or "date_field").strip().lower()
    return field if field in SHIPMENT_QUERY_SORT_FIELDS else "date_field"


def shipment_list_window(*, date_scope: str, now: datetime | None = None) -> tuple[datetime | None, datetime | None]:
    scope = normalize_shipment_date_scope(date_scope)
    if scope == "all":
        return None, None

    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    reference = reference.astimezone(timezone.utc)

    if scope == "today":
        start = datetime.combine(reference.date(), time.min, tzinfo=timezone.utc)
    elif scope == "last_2_days":
        start = reference - timedelta(days=2)
    elif scope == "last_7_days":
        start = reference - timedelta(days=7)
    elif scope == "current_month":
        start = datetime(reference.year, reference.month, 1, tzinfo=timezone.utc)
    else:
        start = reference - timedelta(days=30)
    return start, reference


def _shipment_list_date_column(date_field: str):
    field = normalize_shipment_date_field(date_field)
    if field == "updated_at":
        return Shipment.updated_at
    if field == "ready_at_local":
        return Shipment.ready_at_local
    return Shipment.created_at


def _shipment_query_sort_column(*, sort_by: str, date_field: str):
    field = normalize_shipment_sort_field(sort_by)
    return _shipment_list_date_column(date_field if field == "date_field" else field)


def _shipment_attention_condition():
    manual_review_exists = (
        select(WorkflowEvent.id)
        .where(
            WorkflowEvent.shipment_id == Shipment.id,
            WorkflowEvent.event_type == WorkflowEventType.MANUAL_REVIEW_REQUIRED.value,
        )
        .exists()
    )
    return or_(Shipment.status == ShipmentStage.WAITING_CUSTOMER_DETAILS.value, manual_review_exists)


def _shipment_date_conditions(*, date_scope: str, date_field: str):
    normalized_date_field = normalize_shipment_date_field(date_field)
    column = _shipment_list_date_column(normalized_date_field)
    start, end = shipment_list_window(date_scope=date_scope)
    conditions = []
    if start is not None:
        conditions.append(column >= start.replace(tzinfo=None) if normalized_date_field == "ready_at_local" else column >= start)
    if end is not None:
        conditions.append(column <= end.replace(tzinfo=None) if normalized_date_field == "ready_at_local" else column <= end)
    return column, conditions


async def list_shipments_brief(
    session: AsyncSession,
    *,
    limit: int = 80,
    date_scope: str = "all",
    date_field: str = "created_at",
    status: str | None = None,
    organization_id: UUID | None = None,
) -> list[dict]:
    """Lightweight shipment rows for agents (no enrichment join fan-out)."""
    lim = max(1, min(limit, 200))
    column, date_conditions = _shipment_date_conditions(date_scope=date_scope, date_field=date_field)
    conditions = [Shipment.is_archived.is_(False)]
    if organization_id is not None:
        conditions.append(Shipment.organization_id == organization_id)
    if status:
        conditions.append(Shipment.status == status)
    conditions.extend(date_conditions)
    result = await session.execute(
        select(Shipment)
        .where(*conditions)
        .order_by(column.desc(), Shipment.updated_at.desc(), Shipment.created_at.desc())
        .limit(lim)
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


async def query_shipments_brief(
    session: AsyncSession,
    *,
    date_scope: str = "last_7_days",
    date_field: str = "created_at",
    status: str | None = None,
    city: str | None = None,
    attention_only: bool = False,
    sort_by: str = "date_field",
    limit: int = 50,
    organization_id: UUID | None = None,
) -> dict:
    """Agent-friendly shipment query with metadata and bounded results."""
    lim = max(1, min(limit, 200))
    normalized_date_scope = normalize_shipment_date_scope(date_scope)
    normalized_date_field = normalize_shipment_date_field(date_field)
    normalized_sort_by = normalize_shipment_sort_field(sort_by)
    _date_column, date_conditions = _shipment_date_conditions(
        date_scope=normalized_date_scope,
        date_field=normalized_date_field,
    )
    sort_column = _shipment_query_sort_column(sort_by=normalized_sort_by, date_field=normalized_date_field)
    conditions = [Shipment.is_archived.is_(False), *date_conditions]
    if organization_id is not None:
        conditions.append(Shipment.organization_id == organization_id)
    if status:
        conditions.append(Shipment.status == status)
    if city and city.strip():
        q = f"%{city.strip()}%"
        conditions.append(or_(Shipment.origin.ilike(q), Shipment.destination.ilike(q)))
    if attention_only:
        conditions.append(_shipment_attention_condition())

    result = await session.execute(
        select(Shipment)
        .where(*conditions)
        .order_by(sort_column.desc(), Shipment.updated_at.desc(), Shipment.created_at.desc())
        .limit(lim + 1)
    )
    shipments = result.scalars().all()
    rows = [_shipment_brief_row(shipment) for shipment in shipments[:lim]]
    match_reasons = []
    if normalized_date_scope != "all":
        match_reasons.append(f"{normalized_date_field} in {normalized_date_scope}")
    if status:
        match_reasons.append(f"status is {status}")
    if city and city.strip():
        match_reasons.append(f"origin or destination contains {city.strip()}")
    if attention_only:
        match_reasons.append("requires operator attention")
    for row in rows:
        row["match_reason"] = "; ".join(match_reasons) if match_reasons else "active shipment"

    return {
        "summary": {
            "returned": len(rows),
            "limit": lim,
            "has_more": len(shipments) > lim,
            "date_scope": normalized_date_scope,
            "date_field": normalized_date_field,
            "status": status,
            "city": city,
            "attention_only": attention_only,
            "sort_by": normalized_sort_by,
        },
        "items": rows,
    }


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


def _notification_from_event(event: WorkflowEvent, shipment: Shipment | None) -> NotificationFeedItem | None:
    payload = dict(event.payload_json or {})
    route = f"{shipment.origin or 'Origin TBD'} -> {shipment.destination or 'Destination TBD'}" if shipment else "Shipment"
    quote_token = shipment.quote_token if shipment else None
    sender = str(payload.get("sender") or "").strip() or None

    kind = "system"
    title = "Workflow event"
    detail = quote_token and f"{route} · {quote_token}" or route

    if event.event_type == WorkflowEventType.EMAIL_RECEIVED.value:
        kind = "email"
        title = f"New email from {sender}" if sender else "New inbound email"
    elif event.event_type in {WorkflowEventType.SHIPMENT_PARSED.value, WorkflowEventType.PARSING_COMPLETED.value}:
        kind = "shipment"
        title = "Shipment captured from inbox"
    elif event.event_type == WorkflowEventType.BID_RECEIVED.value:
        kind = "bid"
        title = "Carrier bid received"
    elif event.event_type == WorkflowEventType.MANUAL_REVIEW_REQUIRED.value:
        kind = "review"
        title = "Needs operator review"
        detail = str(payload.get("reason") or route)
    elif event.event_type in {
        WorkflowEventType.CUSTOMER_STATUS_SENT.value,
        WorkflowEventType.TMS_STATUS_INGESTED.value,
        WorkflowEventType.TMS_STATUS_UPDATED.value,
    }:
        kind = "status"
        title = "Status update available"
    elif event.event_type == WorkflowEventType.SHIPMENT_ARCHIVED.value:
        kind = "archive"
        title = "Shipment archived"
    elif event.event_type == WorkflowEventType.EXCEPTION_RAISED.value:
        kind = "system"
        title = "Workflow exception raised"
        detail = str(payload.get("reason") or route)
    else:
        return None

    return NotificationFeedItem(
        id=str(event.id),
        shipment_id=str(shipment.id) if shipment else str(event.shipment_id),
        quote_token=quote_token,
        route=route,
        status=shipment.status if shipment else None,
        event_type=event.event_type,
        stage=event.stage,
        kind=kind,
        title=title,
        detail=detail,
        archived=bool(shipment.is_archived) if shipment else False,
        created_at=event.created_at,
    )


async def get_shipment_brief(
    session: AsyncSession,
    shipment_id: UUID,
    *,
    organization_id: UUID | None = None,
) -> dict | None:
    """Single shipment core fields (no enrichment)."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None or shipment.is_archived:
        return None
    if organization_id is not None and shipment.organization_id != organization_id:
        return None
    return _shipment_brief_row(shipment)


async def get_archived_shipment_brief(
    session: AsyncSession,
    shipment_id: UUID,
    *,
    organization_id: UUID | None = None,
) -> dict | None:
    """Single archived shipment core fields."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None or not shipment.is_archived:
        return None
    if organization_id is not None and shipment.organization_id != organization_id:
        return None
    return _shipment_brief_row(shipment)


async def get_shipment_brief_by_token(
    session: AsyncSession,
    quote_token: str,
    *,
    organization_id: UUID | None = None,
) -> dict | None:
    """Single shipment core fields by quote token."""
    normalized = quote_token.strip().upper()
    if not normalized:
        return None
    conditions = [
        Shipment.is_archived.is_(False),
        func.upper(Shipment.quote_token) == normalized,
    ]
    if organization_id is not None:
        conditions.append(Shipment.organization_id == organization_id)
    shipment = await session.scalar(select(Shipment).where(*conditions))
    return _shipment_brief_row(shipment) if shipment else None


async def search_shipments_brief(
    session: AsyncSession,
    *,
    query: str,
    status: str | None = None,
    limit: int = 50,
    organization_id: UUID | None = None,
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
    if organization_id is not None:
        conditions.append(Shipment.organization_id == organization_id)
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
    organization_id: UUID | None = None,
) -> list[dict]:
    """List shipments for today's board using pickup-local date with created_at fallback."""
    lim = max(1, min(limit, 200))
    conditions = [Shipment.is_archived.is_(False)]
    if organization_id is not None:
        conditions.append(Shipment.organization_id == organization_id)
    result = await session.execute(
        select(Shipment)
        .where(*conditions)
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
    organization_id: UUID | None = None,
) -> list[dict]:
    """List shipments whose origin or destination contains a city string."""
    lim = max(1, min(limit, 200))
    q = f"%{city.strip()}%"
    conditions = [Shipment.is_archived.is_(False), or_(Shipment.origin.ilike(q), Shipment.destination.ilike(q))]
    if organization_id is not None:
        conditions.append(Shipment.organization_id == organization_id)
    result = await session.execute(
        select(Shipment)
        .where(*conditions)
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


async def summarize_shipment_case(
    session: AsyncSession,
    quote_token: str,
    *,
    organization_id: UUID | None = None,
) -> dict | None:
    """Compact case summary for agent answers."""
    normalized = quote_token.strip().upper()
    conditions = [
        Shipment.is_archived.is_(False),
        func.upper(Shipment.quote_token) == normalized,
    ]
    if organization_id is not None:
        conditions.append(Shipment.organization_id == organization_id)
    shipment = await session.scalar(select(Shipment).where(*conditions))
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


async def get_shipment_thread_transcript(
    session: AsyncSession,
    shipment_id: UUID,
    *,
    limit: int = 24,
    organization_id: UUID | None = None,
) -> dict | None:
    """Return active shipment thread transcript in chronological order."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None or shipment.is_archived:
        return None
    if organization_id is not None and shipment.organization_id != organization_id:
        return None
    if not shipment.email_thread_id:
        return {
            "shipment_id": str(shipment.id),
            "quote_token": shipment.quote_token,
            "route": f"{shipment.origin or 'Origin TBD'} -> {shipment.destination or 'Destination TBD'}",
            "status": shipment.status,
            "thread_id": None,
            "thread_subject": None,
            "messages": [],
        }

    thread = await session.get(EmailThread, shipment.email_thread_id)
    result = await session.execute(
        select(EmailMessage)
        .where(
            EmailMessage.organization_id == shipment.organization_id,
            EmailMessage.thread_id == shipment.email_thread_id,
        )
        .order_by(EmailMessage.received_at.desc())
        .limit(max(1, min(limit, 100)))
    )
    messages = list(reversed(result.scalars().all()))
    return {
        "shipment_id": str(shipment.id),
        "quote_token": shipment.quote_token,
        "route": f"{shipment.origin or 'Origin TBD'} -> {shipment.destination or 'Destination TBD'}",
        "status": shipment.status,
        "thread_id": str(shipment.email_thread_id),
        "thread_subject": thread.subject if thread else None,
        "messages": [_serialize_thread_message(message).model_dump(mode="json") for message in messages],
    }


async def get_shipment_thread_transcript_by_token(
    session: AsyncSession,
    quote_token: str,
    *,
    limit: int = 24,
    organization_id: UUID | None = None,
) -> dict | None:
    """Return active shipment transcript by quote token."""
    normalized = quote_token.strip().upper()
    if not normalized:
        return None
    conditions = [
        Shipment.is_archived.is_(False),
        func.upper(Shipment.quote_token) == normalized,
    ]
    if organization_id is not None:
        conditions.append(Shipment.organization_id == organization_id)
    shipment = await session.scalar(select(Shipment).where(*conditions))
    if shipment is None:
        return None
    return await get_shipment_thread_transcript(session, shipment.id, limit=limit, organization_id=organization_id)


async def diagnose_shipment_issue(
    session: AsyncSession,
    shipment_id: UUID,
    *,
    thread_limit: int = 12,
    event_limit: int = 12,
    organization_id: UUID | None = None,
) -> dict | None:
    """Deterministic shipment diagnosis summary for agent troubleshooting."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None or shipment.is_archived:
        return None
    if organization_id is not None and shipment.organization_id != organization_id:
        return None

    transcript = await get_shipment_thread_transcript(
        session,
        shipment_id,
        limit=thread_limit,
        organization_id=organization_id,
    )
    events_result = await session.execute(
        select(WorkflowEvent)
        .where(
            WorkflowEvent.organization_id == shipment.organization_id,
            WorkflowEvent.shipment_id == shipment.id,
        )
        .order_by(WorkflowEvent.created_at.desc())
        .limit(max(1, min(event_limit, 30)))
    )
    events = events_result.scalars().all()
    bids_result = await session.execute(
        select(CarrierBid, Carrier)
        .join(Carrier, Carrier.id == CarrierBid.carrier_id)
        .where(CarrierBid.shipment_id == shipment.id)
        .order_by(CarrierBid.amount.asc().nullslast(), CarrierBid.received_at.desc())
    )
    bid_rows = bids_result.all()

    client = await session.get(Client, shipment.client_id) if shipment.client_id else None
    message_rows_result = await session.execute(
        select(EmailMessage)
        .where(
            EmailMessage.organization_id == shipment.organization_id,
            EmailMessage.thread_id == shipment.email_thread_id,
        )
        .order_by(EmailMessage.received_at.desc())
        .limit(max(1, min(thread_limit, 30)))
    ) if shipment.email_thread_id else None
    thread_messages = message_rows_result.scalars().all() if message_rows_result is not None else []

    customer_signal = None
    carrier_signal = None
    for message in thread_messages:
        if _is_system_thread_message(message):
            continue
        sender = (message.sender or "").strip().lower()
        if customer_signal is None and client and sender == (client.email or "").strip().lower():
            customer_signal = {
                "sender": message.sender,
                "received_at": message.received_at.isoformat() if message.received_at else None,
                "subject": message.subject,
                "excerpt": _message_display_body(message)[:500],
            }
            continue
        if carrier_signal is None and message.direction == "inbound":
            carrier_signal = {
                "sender": message.sender,
                "received_at": message.received_at.isoformat() if message.received_at else None,
                "subject": message.subject,
                "excerpt": _message_display_body(message)[:500],
            }

    current_blockers: list[str] = []
    if shipment.status in {ShipmentStage.RECEIVED.value, ShipmentStage.PARSING.value}:
        current_blockers.append("Shipment is still in intake/parsing stage.")
    if shipment.status == ShipmentStage.WAITING_CUSTOMER_DETAILS.value:
        current_blockers.append("Customer details are still missing.")
    if shipment.status in {ShipmentStage.OUTREACHING.value, ShipmentStage.WAITING_BIDS.value} and not bid_rows:
        current_blockers.append("Carrier bids have not been collected yet.")
    if shipment.status == ShipmentStage.EVALUATING.value:
        current_blockers.append("Bid evaluation is pending.")
    if shipment.status == ShipmentStage.AWAITING_CONFIRMATION.value:
        current_blockers.append("Waiting for customer booking confirmation.")
    if shipment.status == ShipmentStage.BOOKING_FAILED.value:
        current_blockers.append("Booking failed and needs operator follow-up.")

    likely_root_causes: list[str] = []
    recommended_next_steps: list[str] = []
    supporting_evidence: list[dict] = []

    for event in events:
        payload = dict(event.payload_json or {})
        if event.event_type == WorkflowEventType.MANUAL_REVIEW_REQUIRED.value:
            reason = str(payload.get("reason") or "Manual review required.")
            if reason not in likely_root_causes:
                likely_root_causes.append(reason)
        if event.event_type == WorkflowEventType.SHIPMENT_PARSE_FAILED.value:
            reason = str(payload.get("reason") or "Shipment parsing failed.")
            if reason not in likely_root_causes:
                likely_root_causes.append(reason)
        if event.event_type == WorkflowEventType.BID_PARSE_FAILED.value:
            reason = str(payload.get("reason") or "Carrier bid parsing failed.")
            if reason not in likely_root_causes:
                likely_root_causes.append(reason)
        if event.event_type == WorkflowEventType.EXCEPTION_RAISED.value:
            reason = str(payload.get("reason") or "Workflow exception raised.")
            if reason not in likely_root_causes:
                likely_root_causes.append(reason)
        if len(supporting_evidence) < 6:
            supporting_evidence.append(
                {
                    "event_type": event.event_type,
                    "stage": event.stage,
                    "created_at": event.created_at.isoformat() if event.created_at else None,
                    "summary": payload.get("reason")
                    or payload.get("message")
                    or payload.get("next_action")
                    or payload.get("intent")
                    or payload,
                }
            )

    if not likely_root_causes and current_blockers:
        likely_root_causes.extend(current_blockers[:3])

    if shipment.status in {ShipmentStage.RECEIVED.value, ShipmentStage.PARSING.value, ShipmentStage.WAITING_CUSTOMER_DETAILS.value}:
        recommended_next_steps.append("Review parsed shipment fields and missing details from the linked email thread.")
    if shipment.status in {ShipmentStage.OUTREACHING.value, ShipmentStage.WAITING_BIDS.value}:
        recommended_next_steps.append("Check carrier outreach and inbound carrier replies for missing or failed bid intake.")
    if shipment.status == ShipmentStage.EVALUATING.value:
        recommended_next_steps.append("Inspect collected bids and rerun evaluation if enough bids exist.")
    if shipment.status == ShipmentStage.AWAITING_CONFIRMATION.value:
        recommended_next_steps.append("Check whether the customer replied with booking confirmation or clarification.")
    if shipment.status == ShipmentStage.BOOKING_FAILED.value:
        recommended_next_steps.append("Review booking handoff errors and retry only after resolving the blocking issue.")
    if not recommended_next_steps:
        recommended_next_steps.append("Inspect the latest workflow events and email thread for the next blocked step.")

    priced_bids = [bid for bid, _carrier in bid_rows if bid.amount is not None]
    best_bid = priced_bids[0] if priced_bids else None

    problem_summary = current_blockers[0] if current_blockers else likely_root_causes[0] if likely_root_causes else "No clear blocker detected from current shipment state."
    return {
        "shipment_id": str(shipment.id),
        "quote_token": shipment.quote_token,
        "route": f"{shipment.origin or 'Origin TBD'} -> {shipment.destination or 'Destination TBD'}",
        "status": shipment.status,
        "problem_summary": problem_summary,
        "current_blockers": current_blockers,
        "likely_root_causes": likely_root_causes,
        "latest_customer_signal": customer_signal,
        "latest_carrier_signal": carrier_signal,
        "recommended_operator_next_steps": recommended_next_steps,
        "supporting_evidence": supporting_evidence,
        "thread_excerpt": transcript,
        "bid_snapshot": {
            "count": len(bid_rows),
            "priced_count": len(priced_bids),
            "best_bid": {
                "amount": best_bid.amount,
                "currency": best_bid.currency,
                "received_at": best_bid.received_at.isoformat() if best_bid and best_bid.received_at else None,
            } if best_bid else None,
        },
    }


async def diagnose_shipment_issue_by_token(
    session: AsyncSession,
    quote_token: str,
    *,
    thread_limit: int = 12,
    event_limit: int = 12,
    organization_id: UUID | None = None,
) -> dict | None:
    """Deterministic shipment diagnosis summary by quote token."""
    normalized = quote_token.strip().upper()
    if not normalized:
        return None
    conditions = [
        Shipment.is_archived.is_(False),
        func.upper(Shipment.quote_token) == normalized,
    ]
    if organization_id is not None:
        conditions.append(Shipment.organization_id == organization_id)
    shipment = await session.scalar(select(Shipment).where(*conditions))
    if shipment is None:
        return None
    return await diagnose_shipment_issue(
        session,
        shipment.id,
        thread_limit=thread_limit,
        event_limit=event_limit,
        organization_id=organization_id,
    )


async def search_archived_shipments_brief(
    session: AsyncSession,
    *,
    query: str | None = None,
    reason_code: str | None = None,
    limit: int = 50,
    organization_id: UUID | None = None,
) -> list[dict]:
    """Search archived shipments only."""
    lim = max(1, min(limit, 200))
    conditions = [Shipment.is_archived.is_(True)]
    if organization_id is not None:
        conditions.append(Shipment.organization_id == organization_id)
    result = await session.execute(
        select(Shipment)
        .where(*conditions)
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


async def get_archived_shipment_brief_by_token(
    session: AsyncSession,
    quote_token: str,
    *,
    organization_id: UUID | None = None,
) -> dict | None:
    """Single archived shipment by quote token."""
    normalized = quote_token.strip().upper()
    if not normalized:
        return None
    conditions = [
        Shipment.is_archived.is_(True),
        func.upper(Shipment.quote_token) == normalized,
    ]
    if organization_id is not None:
        conditions.append(Shipment.organization_id == organization_id)
    shipment = await session.scalar(select(Shipment).where(*conditions))
    return _shipment_brief_row(shipment) if shipment else None


async def summarize_archived_shipment_case(
    session: AsyncSession,
    quote_token: str,
    *,
    organization_id: UUID | None = None,
) -> dict | None:
    """Compact archived case summary for agent answers."""
    normalized = quote_token.strip().upper()
    conditions = [
        Shipment.is_archived.is_(True),
        func.upper(Shipment.quote_token) == normalized,
    ]
    if organization_id is not None:
        conditions.append(Shipment.organization_id == organization_id)
    shipment = await session.scalar(select(Shipment).where(*conditions))
    if shipment is None:
        return None
    events_result = await session.execute(
        select(WorkflowEvent)
        .where(
            WorkflowEvent.organization_id == shipment.organization_id,
            WorkflowEvent.shipment_id == shipment.id,
        )
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
