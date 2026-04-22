"""Carrier outreach flow for freight shipments."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.memory.database import Carrier, CarrierBid, EmailMessage, EmailThread, Shipment, WorkflowEvent
from app.schemas import CarrierOutreachItem, CarrierOutreachResponse, ShipmentStage, WorkflowEventType
from app.services.email_correlation import attach_quote_token, generate_quote_reference, normalize_subject
from app.services.freight_realtime import freight_realtime_hub
from app.services.location_timezone import format_ready_at_wall_display
from app.services.outlook import OutlookGraphClient


def _build_outreach_subject(shipment: Shipment, thread: EmailThread) -> str:
    lane = "Freight quote request"
    if shipment.origin and shipment.destination:
        lane = f"Quote request {shipment.origin} to {shipment.destination}"
    return attach_quote_token(lane, thread.quote_token)


def _build_outreach_body(shipment: Shipment, custom_message: str | None = None) -> str:
    parts = [
        "Need quote on the following load:",
        f"Origin: {shipment.origin or 'TBD'}",
        f"Destination: {shipment.destination or 'TBD'}",
        f"Pallets: {shipment.pallets if shipment.pallets is not None else 'TBD'}",
        f"Weight (lb): {shipment.weight_lb if shipment.weight_lb is not None else 'TBD'}",
        f"Equipment: {shipment.equipment_type or 'TBD'}",
        (
            f"Ready at: {format_ready_at_wall_display(shipment.ready_at_local, shipment.ready_at_timezone)}"
            if shipment.ready_at_local
            else "Ready at: TBD"
        ),
    ]
    if shipment.notes:
        parts.append(f"Notes: {shipment.notes}")
    if custom_message:
        parts.extend(["", custom_message.strip()])
    parts.extend(["", "Reply with your best rate and ETA."])
    return "\n".join(parts)


async def _ensure_thread(session: AsyncSession, shipment: Shipment) -> EmailThread:
    if shipment.email_thread_id:
        thread = await session.get(EmailThread, shipment.email_thread_id)
        if thread is not None:
            if not thread.quote_token:
                reference = generate_quote_reference()
                thread.quote_token = reference.subject_token
            return thread

    reference = generate_quote_reference()
    quote_token = shipment.quote_token or reference.subject_token
    thread = EmailThread(
        provider="outlook",
        mailbox=settings.microsoft_mailbox or "unknown",
        quote_token=quote_token,
        subject=attach_quote_token("Freight quote request", quote_token),
        normalized_subject=normalize_subject("Freight quote request"),
        last_message_at=datetime.now(timezone.utc),
    )
    session.add(thread)
    await session.flush()
    shipment.email_thread_id = thread.id
    shipment.quote_token = quote_token
    return thread


async def _load_target_carriers(
    session: AsyncSession,
    carrier_ids: list[str],
) -> list[Carrier]:
    if carrier_ids:
        uuids = [UUID(carrier_id) for carrier_id in carrier_ids]
        result = await session.execute(
            select(Carrier)
            .where(Carrier.id.in_(uuids), Carrier.is_active.is_(True))
            .order_by(Carrier.rating.desc(), Carrier.created_at.desc())
        )
        return list(result.scalars().all())

    result = await session.execute(
        select(Carrier)
        .where(Carrier.is_active.is_(True))
        .order_by(Carrier.rating.desc(), Carrier.created_at.desc())
    )
    return list(result.scalars().all())


async def create_carrier_outreach(
    session: AsyncSession,
    *,
    shipment_id: UUID,
    carrier_ids: list[str],
    dry_run: bool,
    custom_message: str | None,
) -> CarrierOutreachResponse:
    """Create and optionally send carrier outreach emails for a shipment."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise RuntimeError("Shipment not found")

    carriers = await _load_target_carriers(session, carrier_ids)
    if not carriers:
        raise RuntimeError("No active carriers available for outreach")

    thread = await _ensure_thread(session, shipment)
    subject = _build_outreach_subject(shipment, thread)
    body = _build_outreach_body(shipment, custom_message)
    outlook = OutlookGraphClient()

    created_bids = 0
    results: list[CarrierOutreachItem] = []
    now = datetime.now(timezone.utc)

    for carrier in carriers:
        existing_bid = await session.scalar(
            select(CarrierBid).where(
                CarrierBid.shipment_id == shipment.id,
                CarrierBid.carrier_id == carrier.id,
            )
        )
        if existing_bid is not None:
            results.append(
                CarrierOutreachItem(
                    carrier_id=str(carrier.id),
                    carrier_email=carrier.email,
                    carrier_name=carrier.name,
                    bid_id=str(existing_bid.id),
                    status="already_exists",
                )
            )
            continue

        send_payload = {
            "provider": "outlook",
            "subject": subject,
            "body": body,
            "recipient": carrier.email,
            "dry_run": dry_run,
        }
        if not dry_run:
            await outlook.send_mail(subject=subject, body=body, recipients=[carrier.email])

        outbound_message = EmailMessage(
            thread_id=thread.id,
            sender=settings.microsoft_mailbox or "unknown",
            recipients_json=[carrier.email],
            direction="outbound",
            subject=subject,
            body_preview=body[:1000],
            raw_payload_json=send_payload,
            received_at=now,
        )
        session.add(outbound_message)
        await session.flush()

        bid = CarrierBid(
            shipment_id=shipment.id,
            carrier_id=carrier.id,
            email_message_id=outbound_message.id,
            status="requested" if not dry_run else "drafted",
            raw_email=body,
            received_at=now,
        )
        session.add(bid)
        await session.flush()
        created_bids += 1

        results.append(
            CarrierOutreachItem(
                carrier_id=str(carrier.id),
                carrier_email=carrier.email,
                carrier_name=carrier.name,
                bid_id=str(bid.id),
                email_message_id=str(outbound_message.id),
                status="queued" if dry_run else "sent",
            )
        )

    shipment.status = ShipmentStage.WAITING_BIDS.value if not dry_run else ShipmentStage.OUTREACHING.value
    shipment.updated_at = now
    thread.subject = subject
    thread.last_message_at = now

    workflow_event = WorkflowEvent(
        shipment_id=shipment.id,
        event_type=WorkflowEventType.CARRIER_OUTREACH_SENT.value,
        stage=shipment.status,
        payload_json={
            "dry_run": dry_run,
            "subject": subject,
            "carrier_ids": [str(carrier.id) for carrier in carriers],
            "created_bids": created_bids,
        },
    )
    session.add(workflow_event)
    await session.commit()
    await freight_realtime_hub.notify_workflow_event(workflow_event)

    return CarrierOutreachResponse(
        shipment_id=str(shipment.id),
        thread_id=str(thread.id),
        quote_token=thread.quote_token or shipment.quote_token or "",
        subject=subject,
        body=body,
        dry_run=dry_run,
        targeted=len(carriers),
        created_bids=created_bids,
        results=results,
    )
