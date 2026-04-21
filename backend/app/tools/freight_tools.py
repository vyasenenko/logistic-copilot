"""LangChain tools for freight workflow inspection and operator actions.

Each tool opens its own async DB session. Destructive or outbound actions support dry_run
where the underlying service supports it.
"""

from __future__ import annotations

import json
from uuid import UUID

from langchain_core.tools import tool
from sqlalchemy import select

from app.config import settings
from app.memory.database import Carrier, Client, Shipment, WorkflowEvent, async_session
from app.schemas import (
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
from app.services.freight_outreach import create_carrier_outreach
from app.services.freight_read import (
    build_freight_overview,
    get_shipment_brief,
    list_shipments_brief,
)
from app.services.workflow_event_codec import workflow_event_to_record


def _json(obj) -> str:
    return json.dumps(obj, indent=2, default=str, ensure_ascii=False)


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
            "provider_conversation_id",
            "subject_token",
            "normalized_subject_fallback",
            "sender_time_window_fallback",
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
async def freight_list_shipments(limit: int = 50) -> str:
    """List recent shipments (id, status, lane, equipment, timestamps). limit capped at 200."""
    async with async_session() as session:
        rows = await list_shipments_brief(session, limit=limit)
        return _json(rows)


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
async def freight_list_workflow_events(shipment_id: str, limit: int = 40) -> str:
    """Return recent workflow events for a shipment (newest first) as JSON."""
    try:
        sid = UUID(shipment_id.strip())
    except ValueError:
        return "Error: shipment_id must be a valid UUID."
    lim = max(1, min(limit, 100))
    async with async_session() as session:
        shipment = await session.get(Shipment, sid)
        if shipment is None:
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


def get_freight_tools():
    """Tools registered for the freight-capable agent."""
    return [
        freight_domain_foundation,
        freight_get_overview,
        freight_list_shipments,
        freight_get_shipment,
        freight_list_workflow_events,
        freight_list_clients,
        freight_list_carriers,
        freight_evaluate_shipment_bids,
        freight_intake_carrier_bid,
        freight_send_customer_quote,
        freight_handoff_shipment_to_tms,
        freight_send_carrier_outreach,
    ]
