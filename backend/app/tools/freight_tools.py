"""LangChain tools for freight workflow inspection and operator actions.

Each tool opens its own async DB session. Destructive or outbound actions support dry_run
where the underlying service supports it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from langchain_core.tools import tool
from sqlalchemy import select

from app.config import settings
from app.memory.database import Carrier, Client, EmailThread, Shipment, WorkflowEvent, async_session
from app.schemas import (
    ArchiveReasonCode,
    BidIntakeRequest,
    FreightFoundationResponse,
    MarginPolicy,
    ShipmentStage,
    WorkflowEventType,
)
from app.services.email_correlation import build_correlation_signals, generate_quote_reference
from app.services.freight_execution import (
    evaluate_shipment_bids,
    handoff_to_tms,
    intake_bid,
    send_customer_quote,
)
from app.services.freight_outreach import create_carrier_outreach, send_carrier_followup
from app.services.freight_read import (
    build_freight_overview,
    diagnose_shipment_issue,
    diagnose_shipment_issue_by_token,
    get_archived_shipment_brief_by_token,
    get_shipment_brief,
    get_shipment_brief_by_token,
    get_shipment_thread_transcript,
    get_shipment_thread_transcript_by_token,
    list_shipments_by_city_brief,
    list_shipments_brief,
    list_today_shipments_brief,
    query_shipments_brief,
    search_archived_shipments_brief,
    search_shipments_brief,
    summarize_archived_shipment_case,
    summarize_shipment_case,
)
from app.services.freight_realtime import freight_realtime_hub
from app.services.location_timezone import (
    normalize_delivery_datetime_fields,
    normalize_pickup_datetime_fields,
)
from app.services.outlook_mail_actions import move_shipment_thread_messages_to_archive
from app.services.workflow_event_codec import workflow_event_to_record


def _json(obj) -> str:
    return json.dumps(obj, indent=2, default=str, ensure_ascii=False)


def _parse_tool_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return None
    return parsed


async def _update_shipment_details_impl(
    *,
    shipment: Shipment,
    session,
    client_id: str | None = None,
    origin: str | None = None,
    destination: str | None = None,
    pallets: int | None = None,
    weight_lb: float | None = None,
    equipment_type: str | None = None,
    ready_at_local: str | None = None,
    delivery_at_local: str | None = None,
    notes: str | None = None,
    clear_ready_at: bool = False,
    clear_delivery_at: bool = False,
    clear_notes: bool = False,
) -> dict:
    if shipment.is_archived:
        return {"updated": False, "error": "Shipment is archived and cannot be edited."}

    previous_values = {
        "client_id": str(shipment.client_id) if shipment.client_id else None,
        "origin": shipment.origin,
        "destination": shipment.destination,
        "pallets": shipment.pallets,
        "weight_lb": shipment.weight_lb,
        "equipment_type": shipment.equipment_type,
        "ready_at": shipment.ready_at.isoformat() if shipment.ready_at else None,
        "ready_at_local": shipment.ready_at_local.isoformat() if shipment.ready_at_local else None,
        "delivery_at": shipment.delivery_at.isoformat() if shipment.delivery_at else None,
        "delivery_at_local": shipment.delivery_at_local.isoformat() if shipment.delivery_at_local else None,
        "notes": shipment.notes,
    }

    if client_id is not None:
        normalized_client_id = client_id.strip()
        if not normalized_client_id:
            shipment.client_id = None
        else:
            try:
                cid = UUID(normalized_client_id)
            except ValueError:
                return {"updated": False, "error": "client_id must be a valid UUID."}
            client = await session.get(Client, cid)
            if client is None:
                return {"updated": False, "error": f"Client not found: {client_id}"}
            shipment.client_id = cid

    if origin is not None:
        shipment.origin = origin.strip() or None
    if destination is not None:
        shipment.destination = destination.strip() or None
    if pallets is not None:
        if pallets < 0:
            return {"updated": False, "error": "pallets must be >= 0."}
        shipment.pallets = pallets
    if weight_lb is not None:
        if weight_lb < 0:
            return {"updated": False, "error": "weight_lb must be >= 0."}
        shipment.weight_lb = weight_lb
    if equipment_type is not None:
        shipment.equipment_type = equipment_type.strip() or None

    if clear_ready_at:
        shipment.ready_at = None
        shipment.ready_at_local = None
        shipment.ready_at_timezone = None
        shipment.ready_at_offset_minutes = None
    elif ready_at_local is not None:
        parsed_ready = _parse_tool_datetime(ready_at_local)
        if parsed_ready is None:
            return {
                "updated": False,
                "error": "ready_at_local must be a local ISO datetime without timezone, like 2026-04-25T07:30 or 2026-04-25T07:30:00.",
            }
        shipment.ready_at = None
        shipment.ready_at_local = parsed_ready

    if clear_delivery_at:
        shipment.delivery_at = None
        shipment.delivery_at_local = None
        shipment.delivery_at_timezone = None
        shipment.delivery_at_offset_minutes = None
    elif delivery_at_local is not None:
        parsed_delivery = _parse_tool_datetime(delivery_at_local)
        if parsed_delivery is None:
            return {
                "updated": False,
                "error": "delivery_at_local must be a local ISO datetime without timezone, like 2026-04-26T09:00 or 2026-04-26T09:00:00.",
            }
        shipment.delivery_at = None
        shipment.delivery_at_local = parsed_delivery

    if clear_notes:
        shipment.notes = ""
    elif notes is not None:
        shipment.notes = notes

    (
        shipment.ready_at,
        shipment.ready_at_local,
        shipment.ready_at_timezone,
        shipment.ready_at_offset_minutes,
    ) = normalize_pickup_datetime_fields(
        ready_at=shipment.ready_at,
        ready_at_local=shipment.ready_at_local,
        origin=shipment.origin,
        destination=shipment.destination,
    )
    (
        shipment.delivery_at,
        shipment.delivery_at_local,
        shipment.delivery_at_timezone,
        shipment.delivery_at_offset_minutes,
    ) = normalize_delivery_datetime_fields(
        delivery_at=shipment.delivery_at,
        delivery_at_local=shipment.delivery_at_local,
        origin=shipment.origin,
        destination=shipment.destination,
    )
    shipment.updated_at = datetime.now(timezone.utc)

    current_values = {
        "client_id": str(shipment.client_id) if shipment.client_id else None,
        "origin": shipment.origin,
        "destination": shipment.destination,
        "pallets": shipment.pallets,
        "weight_lb": shipment.weight_lb,
        "equipment_type": shipment.equipment_type,
        "ready_at": shipment.ready_at.isoformat() if shipment.ready_at else None,
        "ready_at_local": shipment.ready_at_local.isoformat() if shipment.ready_at_local else None,
        "delivery_at": shipment.delivery_at.isoformat() if shipment.delivery_at else None,
        "delivery_at_local": shipment.delivery_at_local.isoformat() if shipment.delivery_at_local else None,
        "notes": shipment.notes,
    }
    changed_fields = [
        field for field, value in current_values.items() if previous_values.get(field) != value
    ]
    if not changed_fields:
        return {
            "updated": False,
            "message": "No shipment fields changed.",
            "shipment_id": str(shipment.id),
            "quote_token": shipment.quote_token,
        }

    evt = WorkflowEvent(
        shipment_id=shipment.id,
        event_type=WorkflowEventType.SHIPMENT_FIELDS_UPDATED.value,
        stage=shipment.status,
        payload_json={
            "changed_fields": changed_fields,
            "manual_review_required": False,
            "edited_by": "agent_tool",
        },
    )
    session.add(evt)
    await session.commit()
    await freight_realtime_hub.notify_workflow_event(evt)
    updated = await get_shipment_brief(session, shipment.id)
    return {
        "updated": True,
        "shipment_id": str(shipment.id),
        "quote_token": shipment.quote_token,
        "changed_fields": changed_fields,
        "shipment": updated,
    }


@tool
async def freight_domain_foundation() -> str:
    """Return freight workflow enums, correlation strategy, and default margin policy (JSON).
    Call this first when you need stage names, event types, or correlation rules."""
    ref = generate_quote_reference()
    final_subject = f"New quote request [{ref.subject_token}]"
    signals = build_correlation_signals(subject=final_subject)
    payload = FreightFoundationResponse(
        stages=list(ShipmentStage),
        event_types=list(WorkflowEventType),
        correlation_strategy=[
            "internet_message_id",
            "in_reply_to",
            "references",
            "subject_token",
            "reply_gated_provider_conversation_id",
            "new_customer_quote_creates_new_shipment",
        ],
        margin_defaults=MarginPolicy(
            percent=settings.profit_margin_percent_default,
            floor_amount=settings.profit_margin_floor_default,
        ),
    )
    return _json(
        {
            "foundation": payload.model_dump(mode="json"),
            "reference_example": ref.model_dump(),
            "subject_with_token_example": final_subject,
            "correlation_signals_example": signals.model_dump(mode="json"),
        }
    )


@tool
async def freight_get_overview() -> str:
    """Return JSON overview: entity counts, shipments per stage, status SLA metrics."""
    async with async_session() as session:
        overview = await build_freight_overview(session)
        return overview.model_dump_json(indent=2)


@tool
async def freight_list_shipments(
    date_scope: str = "last_7_days",
    date_field: str = "created_at",
    status: str | None = None,
    limit: int = 50,
) -> str:
    """List active shipments by date scope. date_scope: today, last_2_days, last_7_days, current_month, last_30_days, all. date_field: created_at, updated_at, ready_at_local. limit capped at 200."""
    async with async_session() as session:
        rows = await list_shipments_brief(
            session,
            limit=limit,
            date_scope=date_scope,
            date_field=date_field,
            status=status,
        )
        return _json(rows)


@tool
async def freight_query_shipments(
    date_scope: str = "last_7_days",
    date_field: str = "created_at",
    status: str | None = None,
    city: str | None = None,
    attention_only: bool = False,
    sort_by: str = "date_field",
    limit: int = 50,
) -> str:
    """Query active shipments with filters and summary metadata. date_scope: today, last_2_days, last_7_days, current_month, last_30_days, all. date_field/sort_by: created_at, updated_at, ready_at_local. attention_only limits to review-like shipments."""
    async with async_session() as session:
        result = await query_shipments_brief(
            session,
            date_scope=date_scope,
            date_field=date_field,
            status=status,
            city=city,
            attention_only=attention_only,
            sort_by=sort_by,
            limit=limit,
        )
        return _json(result)


@tool
async def freight_get_shipment(shipment_id: str) -> str:
    """Get one shipment by UUID: core fields and notes (JSON)."""
    try:
        sid = UUID(shipment_id.strip())
    except ValueError:
        return "Error: shipment_id must be a valid UUID."
    async with async_session() as session:
        row = await get_shipment_brief(session, sid)
        if row is None:
            return f"Error: shipment not found: {shipment_id}"
        return _json(row)


@tool
async def freight_get_shipment_by_token(quote_token: str) -> str:
    """Get one active shipment by quote token like Q-87845634 (JSON)."""
    async with async_session() as session:
        row = await get_shipment_brief_by_token(session, quote_token)
        if row is None:
            return f"Error: shipment not found for quote token: {quote_token}"
        return _json(row)


@tool
async def freight_update_shipment_details(
    shipment_id: str,
    client_id: str | None = None,
    origin: str | None = None,
    destination: str | None = None,
    pallets: int | None = None,
    weight_lb: float | None = None,
    equipment_type: str | None = None,
    ready_at_local: str | None = None,
    delivery_at_local: str | None = None,
    notes: str | None = None,
    clear_ready_at: bool = False,
    clear_delivery_at: bool = False,
    clear_notes: bool = False,
) -> str:
    """Update active shipment details by UUID. Date fields accept local wall time only; UTC/timezone are derived automatically from route."""
    try:
        sid = UUID(shipment_id.strip())
    except ValueError:
        return "Error: shipment_id must be a valid UUID."
    async with async_session() as session:
        shipment = await session.get(Shipment, sid)
        if shipment is None or shipment.is_archived:
            return f"Error: active shipment not found: {shipment_id}"
        result = await _update_shipment_details_impl(
            shipment=shipment,
            session=session,
            client_id=client_id,
            origin=origin,
            destination=destination,
            pallets=pallets,
            weight_lb=weight_lb,
            equipment_type=equipment_type,
            ready_at_local=ready_at_local,
            delivery_at_local=delivery_at_local,
            notes=notes,
            clear_ready_at=clear_ready_at,
            clear_delivery_at=clear_delivery_at,
            clear_notes=clear_notes,
        )
        if result.get("error"):
            return f"Error: {result['error']}"
        return _json(result)


@tool
async def freight_update_shipment_details_by_token(
    quote_token: str,
    client_id: str | None = None,
    origin: str | None = None,
    destination: str | None = None,
    pallets: int | None = None,
    weight_lb: float | None = None,
    equipment_type: str | None = None,
    ready_at_local: str | None = None,
    delivery_at_local: str | None = None,
    notes: str | None = None,
    clear_ready_at: bool = False,
    clear_delivery_at: bool = False,
    clear_notes: bool = False,
) -> str:
    """Update active shipment details by quote token like Q-87845634. Date fields accept local wall time only; UTC/timezone are derived automatically from route."""
    async with async_session() as session:
        result = await session.execute(
            select(Shipment).where(Shipment.quote_token == quote_token.strip(), Shipment.is_archived.is_(False))
        )
        shipment = result.scalar_one_or_none()
        if shipment is None:
            return f"Error: active shipment not found for quote token: {quote_token}"
        outcome = await _update_shipment_details_impl(
            shipment=shipment,
            session=session,
            client_id=client_id,
            origin=origin,
            destination=destination,
            pallets=pallets,
            weight_lb=weight_lb,
            equipment_type=equipment_type,
            ready_at_local=ready_at_local,
            delivery_at_local=delivery_at_local,
            notes=notes,
            clear_ready_at=clear_ready_at,
            clear_delivery_at=clear_delivery_at,
            clear_notes=clear_notes,
        )
        if outcome.get("error"):
            return f"Error: {outcome['error']}"
        return _json(outcome)


@tool
async def freight_search_shipments(query: str, status: str | None = None, limit: int = 50) -> str:
    """Search active shipments by token, route/city, equipment, notes, or status."""
    async with async_session() as session:
        rows = await search_shipments_brief(session, query=query, status=status, limit=limit)
        return _json(rows)


@tool
async def freight_list_shipments_by_city(city: str, date_scope: str = "today", limit: int = 50) -> str:
    """List active shipments touching a city in origin/destination. date_scope: today or all."""
    async with async_session() as session:
        rows = await list_shipments_by_city_brief(session, city=city, date_scope=date_scope, limit=limit)
        return _json(rows)


@tool
async def freight_list_today_shipments(status: str | None = None, limit: int = 100) -> str:
    """List today's active shipments using pickup-local date, with created_at fallback."""
    async with async_session() as session:
        rows = await list_today_shipments_brief(session, status=status, limit=limit)
        return _json(rows)


@tool
async def freight_summarize_shipment_case(quote_token: str) -> str:
    """Summarize one shipment case by quote token: shipment, recent events, and bid snapshot."""
    async with async_session() as session:
        summary = await summarize_shipment_case(session, quote_token)
        if summary is None:
            return f"Error: shipment not found for quote token: {quote_token}"
        return _json(summary)


@tool
async def freight_get_shipment_thread(shipment_id: str, limit: int = 24) -> str:
    """Get the linked email thread transcript for one active shipment by UUID."""
    try:
        sid = UUID(shipment_id.strip())
    except ValueError:
        return "Error: shipment_id must be a valid UUID."
    async with async_session() as session:
        row = await get_shipment_thread_transcript(session, sid, limit=limit)
        if row is None:
            return f"Error: active shipment thread not found: {shipment_id}"
        return _json(row)


@tool
async def freight_get_shipment_thread_by_token(quote_token: str, limit: int = 24) -> str:
    """Get the linked email thread transcript for one active shipment by quote token."""
    async with async_session() as session:
        row = await get_shipment_thread_transcript_by_token(session, quote_token, limit=limit)
        if row is None:
            return f"Error: active shipment thread not found for quote token: {quote_token}"
        return _json(row)


@tool
async def freight_diagnose_shipment_issue(shipment_id: str) -> str:
    """Return a deterministic diagnosis summary for one active shipment by UUID."""
    try:
        sid = UUID(shipment_id.strip())
    except ValueError:
        return "Error: shipment_id must be a valid UUID."
    async with async_session() as session:
        row = await diagnose_shipment_issue(session, sid)
        if row is None:
            return f"Error: active shipment diagnosis not available: {shipment_id}"
        return _json(row)


@tool
async def freight_diagnose_shipment_issue_by_token(quote_token: str) -> str:
    """Return a deterministic diagnosis summary for one active shipment by quote token."""
    async with async_session() as session:
        row = await diagnose_shipment_issue_by_token(session, quote_token)
        if row is None:
            return f"Error: active shipment diagnosis not available for quote token: {quote_token}"
        return _json(row)


@tool
async def freight_search_archived_shipments(query: str = "", reason_code: str | None = None, limit: int = 50) -> str:
    """Search archived shipments only. Use only when user asks about archive/ignored/deleted shipments."""
    async with async_session() as session:
        rows = await search_archived_shipments_brief(session, query=query, reason_code=reason_code, limit=limit)
        return _json(rows)


@tool
async def freight_get_archived_shipment_by_token(quote_token: str) -> str:
    """Get one archived shipment by quote token. Use only for archive lookup."""
    async with async_session() as session:
        row = await get_archived_shipment_brief_by_token(session, quote_token)
        if row is None:
            return f"Error: archived shipment not found for quote token: {quote_token}"
        return _json(row)


@tool
async def freight_summarize_archived_shipment(quote_token: str) -> str:
    """Summarize one archived shipment case by quote token."""
    async with async_session() as session:
        summary = await summarize_archived_shipment_case(session, quote_token)
        if summary is None:
            return f"Error: archived shipment not found for quote token: {quote_token}"
        return _json(summary)


@tool
async def freight_archive_shipment(
    shipment_id: str,
    reason_code: str = "other",
    reason_note: str | None = None,
    suppress_source_thread: bool = True,
    dry_run: bool = True,
) -> str:
    """Archive an active shipment and optionally suppress its source thread. Prefer dry_run=True unless user explicitly asks to archive."""
    try:
        sid = UUID(shipment_id.strip())
    except ValueError:
        return "Error: shipment_id must be a valid UUID."
    try:
        code = ArchiveReasonCode(reason_code)
    except ValueError:
        allowed = ", ".join(item.value for item in ArchiveReasonCode)
        return f"Error: reason_code must be one of: {allowed}"

    async with async_session() as session:
        shipment = await session.get(Shipment, sid)
        if shipment is None or shipment.is_archived:
            return f"Error: active shipment not found: {shipment_id}"
        thread = await session.get(EmailThread, shipment.email_thread_id) if shipment.email_thread_id else None
        if dry_run:
            return _json(
                {
                    "dry_run": True,
                    "would_archive": str(shipment.id),
                    "quote_token": shipment.quote_token,
                    "route": f"{shipment.origin or 'Origin TBD'} -> {shipment.destination or 'Destination TBD'}",
                    "reason_code": code.value,
                    "reason_note": reason_note,
                    "would_suppress_thread": bool(thread is not None and suppress_source_thread),
                    "thread_id": str(thread.id) if thread else None,
                }
            )

        now = datetime.now(timezone.utc)
        note = (reason_note or "").strip() or None
        legacy_reason = note or code.value
        shipment.is_archived = True
        shipment.archive_reason_code = code.value
        shipment.archive_reason_note = note
        shipment.archived_reason = legacy_reason
        shipment.archived_at = now
        shipment.updated_at = now
        session.add(
            WorkflowEvent(
                shipment_id=shipment.id,
                event_type=WorkflowEventType.SHIPMENT_ARCHIVED.value,
                stage=shipment.status,
                payload_json={
                    "reason": legacy_reason,
                    "reason_code": code.value,
                    "reason_note": note,
                    "suppress_source_thread": suppress_source_thread,
                    "source": "agent_tool",
                },
            )
        )
        if suppress_source_thread and thread is not None:
            thread.shipment_ingest_suppressed = True
            thread.shipment_ingest_suppressed_reason = legacy_reason
            thread.shipment_ingest_suppressed_at = now
            session.add(
                WorkflowEvent(
                    shipment_id=shipment.id,
                    event_type=WorkflowEventType.SHIPMENT_SOURCE_SUPPRESSED.value,
                    stage=shipment.status,
                    payload_json={
                        "reason": legacy_reason,
                        "reason_code": code.value,
                        "reason_note": note,
                        "email_thread_id": str(thread.id),
                        "suppressed": True,
                        "source": "agent_tool",
                    },
                )
            )
        await session.commit()
        archive_mail_result = await move_shipment_thread_messages_to_archive(
            session,
            shipment=shipment,
            reason=legacy_reason,
        )
        return _json(
            {
                "archived": True,
                "shipment_id": str(shipment.id),
                "quote_token": shipment.quote_token,
                "reason_code": code.value,
                "reason_note": note,
                "suppression_applied": bool(thread is not None and suppress_source_thread),
                "suppressed_thread_id": str(thread.id) if thread is not None and suppress_source_thread else None,
                "archive_mail_result": archive_mail_result,
            }
        )


@tool
async def freight_list_workflow_events(shipment_id: str, limit: int = 40) -> str:
    """Return recent workflow events for a shipment (newest first) as JSON."""
    try:
        sid = UUID(shipment_id.strip())
    except ValueError:
        return "Error: shipment_id must be a valid UUID."
    lim = max(1, min(limit, 100))
    async with async_session() as session:
        shipment = await session.get(Shipment, sid)
        if shipment is None or shipment.is_archived:
            return f"Error: shipment not found: {shipment_id}"
        result = await session.execute(
            select(WorkflowEvent)
            .where(WorkflowEvent.shipment_id == sid)
            .order_by(WorkflowEvent.created_at.desc())
            .limit(lim)
        )
        records = [workflow_event_to_record(ev).model_dump(mode="json") for ev in result.scalars().all()]
        return _json(records)


@tool
async def freight_list_clients() -> str:
    """List all freight clients (JSON)."""
    async with async_session() as session:
        result = await session.execute(select(Client).order_by(Client.created_at.desc()))
        rows = [
            {
                "id": str(c.id),
                "name": c.name,
                "email": c.email,
                "is_active": c.is_active,
                "default_margin_percent": c.default_margin_percent,
                "default_margin_floor": c.default_margin_floor,
            }
            for c in result.scalars().all()
        ]
        return _json(rows)


@tool
async def freight_list_carriers() -> str:
    """List active-oriented carriers (JSON)."""
    async with async_session() as session:
        result = await session.execute(select(Carrier).order_by(Carrier.rating.desc(), Carrier.created_at.desc()))
        rows = [
            {
                "id": str(c.id),
                "name": c.name,
                "email": c.email,
                "rating": c.rating,
                "is_active": c.is_active,
                "regions": list(c.regions_json or []),
                "equipment": list(c.equipment_json or []),
            }
            for c in result.scalars().all()
        ]
        return _json(rows)


@tool
async def freight_evaluate_shipment_bids(shipment_id: str) -> str:
    """Score priced bids for a shipment and select a recommended carrier (persists evaluation)."""
    try:
        sid = UUID(shipment_id.strip())
    except ValueError:
        return "Error: shipment_id must be a valid UUID."
    async with async_session() as session:
        try:
            out = await evaluate_shipment_bids(session, sid)
            return out.model_dump_json(indent=2)
        except RuntimeError as e:
            return f"Error: {e}"


@tool
async def freight_intake_carrier_bid(
    shipment_id: str,
    carrier_email: str,
    amount: float,
    subject: str = "",
    raw_email: str = "",
    currency: str = "USD",
    eta_text: str | None = None,
    create_carrier_if_missing: bool = False,
) -> str:
    """Record a carrier bid from email context (amount, carrier email, optional raw email body)."""
    try:
        sid = UUID(shipment_id.strip())
    except ValueError:
        return "Error: shipment_id must be a valid UUID."
    req = BidIntakeRequest(
        shipment_id=str(sid),
        carrier_email=carrier_email.lower().strip(),
        subject=subject,
        amount=amount,
        currency=currency,
        eta_text=eta_text,
        raw_email=raw_email,
        create_carrier_if_missing=create_carrier_if_missing,
    )
    async with async_session() as session:
        try:
            out = await intake_bid(session, req)
            return out.model_dump_json(indent=2)
        except RuntimeError as e:
            return f"Error: {e}"


@tool
async def freight_send_customer_quote(
    shipment_id: str,
    dry_run: bool = True,
    bid_id: str | None = None,
    custom_message: str | None = None,
) -> str:
    """Preview or send the customer quote email from the selected bid. Prefer dry_run=True first."""
    try:
        sid = UUID(shipment_id.strip())
    except ValueError:
        return "Error: shipment_id must be a valid UUID."
    async with async_session() as session:
        try:
            out = await send_customer_quote(
                session,
                shipment_id=sid,
                bid_id=bid_id,
                dry_run=dry_run,
                custom_message=custom_message,
            )
            return out.model_dump_json(indent=2)
        except RuntimeError as e:
            return f"Error: {e}"


@tool
async def freight_handoff_shipment_to_tms(
    shipment_id: str,
    dry_run: bool = True,
    bid_id: str | None = None,
) -> str:
    """Preview or submit the booked load payload to the configured TMS (dry_run recommended first)."""
    try:
        sid = UUID(shipment_id.strip())
    except ValueError:
        return "Error: shipment_id must be a valid UUID."
    async with async_session() as session:
        try:
            out = await handoff_to_tms(session, shipment_id=sid, bid_id=bid_id, dry_run=dry_run)
            return out.model_dump_json(indent=2)
        except RuntimeError as e:
            return f"Error: {e}"


@tool
async def freight_send_carrier_outreach(
    shipment_id: str,
    dry_run: bool = True,
    carrier_ids: str = "",
    custom_message: str | None = None,
) -> str:
    """Email active carriers for quotes. carrier_ids: comma-separated UUIDs, or empty string for all active."""
    try:
        sid = UUID(shipment_id.strip())
    except ValueError:
        return "Error: shipment_id must be a valid UUID."
    ids: list[str] = [x.strip() for x in carrier_ids.split(",") if x.strip()]
    async with async_session() as session:
        try:
            out = await create_carrier_outreach(
                session,
                shipment_id=sid,
                carrier_ids=ids,
                dry_run=dry_run,
                custom_message=custom_message,
            )
            return out.model_dump_json(indent=2)
        except RuntimeError as e:
            return f"Error: {e}"


@tool
async def freight_send_carrier_followup(
    shipment_id: str,
    message: str,
    dry_run: bool = True,
    carrier_id: str | None = None,
    carrier_email: str | None = None,
    subject: str | None = None,
) -> str:
    """Send a follow-up to one carrier. First outreach stays new; follow-ups reply in thread when possible."""
    try:
        sid = UUID(shipment_id.strip())
    except ValueError:
        return "Error: shipment_id must be a valid UUID."
    if not carrier_id and not carrier_email:
        return "Error: carrier_id or carrier_email is required."
    async with async_session() as session:
        try:
            out = await send_carrier_followup(
                session,
                shipment_id=sid,
                carrier_id=carrier_id,
                carrier_email=carrier_email,
                dry_run=dry_run,
                subject=subject,
                message=message,
            )
            return out.model_dump_json(indent=2)
        except RuntimeError as e:
            return f"Error: {e}"


def get_freight_tools():
    """Tools registered for the freight-capable agent."""
    return [
        freight_domain_foundation,
        freight_get_overview,
        freight_list_shipments,
        freight_query_shipments,
        freight_get_shipment,
        freight_get_shipment_by_token,
        freight_update_shipment_details,
        freight_update_shipment_details_by_token,
        freight_get_shipment_thread,
        freight_get_shipment_thread_by_token,
        freight_search_shipments,
        freight_list_shipments_by_city,
        freight_list_today_shipments,
        freight_summarize_shipment_case,
        freight_diagnose_shipment_issue,
        freight_diagnose_shipment_issue_by_token,
        freight_search_archived_shipments,
        freight_get_archived_shipment_by_token,
        freight_summarize_archived_shipment,
        freight_archive_shipment,
        freight_list_workflow_events,
        freight_list_clients,
        freight_list_carriers,
        freight_evaluate_shipment_bids,
        freight_intake_carrier_bid,
        freight_send_customer_quote,
        freight_handoff_shipment_to_tms,
        freight_send_carrier_outreach,
        freight_send_carrier_followup,
    ]
