"""Carrier outreach flow for freight shipments."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.database import Carrier, CarrierBid, Client, EmailMessage, EmailThread, Shipment, WorkflowEvent
from app.schemas import (
    CarrierFollowupResponse,
    CarrierOutreachItem,
    CarrierOutreachResponse,
    ShipmentStage,
    WorkflowEventType,
)
from app.services.email_correlation import attach_quote_token, generate_quote_reference, normalize_subject
from app.services.freight_realtime import freight_realtime_hub
from app.services.location_timezone import format_ready_at_wall_display
from app.services.outlook_organization import (
    build_outlook_graph_client_for_shipment,
    organization_outlook_mailbox,
)


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


async def _find_carrier_reply_anchor(
    session: AsyncSession,
    *,
    shipment: Shipment,
    carrier_email: str,
) -> EmailMessage | None:
    """Find the first inbound carrier message that can anchor a real reply."""
    if not shipment.email_thread_id:
        return None
    normalized_email = carrier_email.strip().lower()
    if not normalized_email:
        return None
    return await session.scalar(
        select(EmailMessage)
        .where(
            EmailMessage.thread_id == shipment.email_thread_id,
            EmailMessage.direction == "inbound",
            EmailMessage.provider_message_id.is_not(None),
            EmailMessage.provider_message_id != "",
            func.lower(EmailMessage.sender) == normalized_email,
        )
        .order_by(EmailMessage.received_at.asc(), EmailMessage.created_at.asc())
    )


async def deliver_carrier_thread_email(
    session: AsyncSession,
    *,
    shipment: Shipment,
    carrier_email: str,
    subject: str,
    body: str,
    dry_run: bool,
) -> dict:
    """Send carrier follow-up as a reply after the first carrier contact exists."""
    anchor = await _find_carrier_reply_anchor(
        session,
        shipment=shipment,
        carrier_email=carrier_email,
    )
    delivery_payload = {
        "delivery_mode": "reply" if anchor is not None else "send_mail_fallback",
        "reply_to_provider_message_id": (
            anchor.provider_message_id if anchor is not None else None
        ),
    }
    if dry_run:
        return delivery_payload

    outlook = await build_outlook_graph_client_for_shipment(session, shipment)
    if anchor is not None:
        await outlook.reply_to_message(
            message_id=anchor.provider_message_id,
            body=body,
            recipients=[carrier_email],
        )
    else:
        await outlook.send_mail(subject=subject, body=body, recipients=[carrier_email])
    return delivery_payload


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
    thread_mailbox = await organization_outlook_mailbox(session, shipment.organization_id)
    thread = EmailThread(
        organization_id=shipment.organization_id,
        provider="outlook",
        mailbox=thread_mailbox,
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
    *,
    shipment: Shipment,
) -> list[Carrier]:
    if carrier_ids:
        uuids = [UUID(carrier_id) for carrier_id in carrier_ids]
        result = await session.execute(
            select(Carrier)
            .where(
                Carrier.organization_id == shipment.organization_id,
                Carrier.id.in_(uuids),
                Carrier.is_active.is_(True),
            )
            .order_by(Carrier.rating.desc(), Carrier.created_at.desc())
        )
        return list(result.scalars().all())

    result = await session.execute(
        select(Carrier)
        .where(Carrier.organization_id == shipment.organization_id, Carrier.is_active.is_(True))
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

    carriers = await _load_target_carriers(session, carrier_ids, shipment=shipment)
    if not carriers:
        raise RuntimeError("No active carriers available for outreach")

    thread = await _ensure_thread(session, shipment)
    subject = _build_outreach_subject(shipment, thread)
    body = _build_outreach_body(shipment, custom_message)
    outlook = await build_outlook_graph_client_for_shipment(session, shipment)

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
            "delivery_mode": "new_thread",
            "reply_to_provider_message_id": None,
        }
        if not dry_run:
            await outlook.send_mail(subject=subject, body=body, recipients=[carrier.email])

        outbound_message = EmailMessage(
            organization_id=shipment.organization_id,
            thread_id=thread.id,
            sender=await organization_outlook_mailbox(session, shipment.organization_id),
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
            organization_id=shipment.organization_id,
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
                delivery_mode="new_thread",
            )
        )

    shipment.status = ShipmentStage.WAITING_BIDS.value if not dry_run else ShipmentStage.OUTREACHING.value
    shipment.updated_at = now
    thread.subject = subject
    thread.last_message_at = now

    workflow_event = WorkflowEvent(
        organization_id=shipment.organization_id,
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


async def send_carrier_followup(
    session: AsyncSession,
    *,
    shipment_id: UUID,
    carrier_id: str | None,
    carrier_email: str | None,
    dry_run: bool,
    subject: str | None,
    message: str,
) -> CarrierFollowupResponse:
    """Send a follow-up to one carrier, replying in-thread when a carrier reply exists."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise RuntimeError("Shipment not found")

    carrier: Carrier | None = None
    if carrier_id:
        try:
            carrier_uuid = UUID(carrier_id)
        except ValueError as exc:
            raise RuntimeError("carrier_id must be a valid UUID") from exc
        carrier = await session.get(Carrier, carrier_uuid)
    elif carrier_email:
        carrier = await session.scalar(
            select(Carrier).where(func.lower(Carrier.email) == carrier_email.strip().lower())
        )
    if carrier is None:
        raise RuntimeError("Carrier not found")

    thread = await _ensure_thread(session, shipment)
    body = message.strip()
    if not body:
        raise RuntimeError("Carrier follow-up message cannot be empty")
    followup_subject = subject.strip() if subject and subject.strip() else attach_quote_token(
        f"Follow-up {shipment.origin or 'Origin'} to {shipment.destination or 'Destination'}",
        thread.quote_token or shipment.quote_token or "Q-UNKNOWN",
    )
    delivery_payload = await deliver_carrier_thread_email(
        session,
        shipment=shipment,
        carrier_email=carrier.email,
        subject=followup_subject,
        body=body,
        dry_run=dry_run,
    )

    outbound_message: EmailMessage | None = None
    if shipment.email_thread_id:
        outbound_message = EmailMessage(
            organization_id=shipment.organization_id,
            thread_id=shipment.email_thread_id,
            sender=await organization_outlook_mailbox(session, shipment.organization_id),
            recipients_json=[carrier.email],
            direction="outbound",
            subject=followup_subject,
            body_preview=body[:1000],
            raw_payload_json={
                "type": "carrier_followup",
                "provider": "outlook",
                "dry_run": dry_run,
                "carrier_id": str(carrier.id),
                "carrier_email": carrier.email,
                **delivery_payload,
            },
            received_at=datetime.now(timezone.utc),
        )
        session.add(outbound_message)
        await session.flush()

    shipment.updated_at = datetime.now(timezone.utc)
    thread.last_message_at = shipment.updated_at
    workflow_event = WorkflowEvent(
        organization_id=shipment.organization_id,
        shipment_id=shipment.id,
        event_type=WorkflowEventType.CARRIER_FOLLOWUP_SENT.value,
        stage=shipment.status,
        payload_json={
            "dry_run": dry_run,
            "subject": followup_subject,
            "carrier_id": str(carrier.id),
            "carrier_email": carrier.email,
            **delivery_payload,
        },
    )
    session.add(workflow_event)
    await session.commit()
    await freight_realtime_hub.notify_workflow_event(workflow_event)

    return CarrierFollowupResponse(
        shipment_id=str(shipment.id),
        carrier_id=str(carrier.id),
        carrier_email=carrier.email,
        subject=followup_subject,
        body=body,
        dry_run=dry_run,
        email_message_id=str(outbound_message.id) if outbound_message is not None else None,
        **delivery_payload,
    )


async def send_carrier_award_confirmation(
    session: AsyncSession,
    *,
    shipment_id: UUID,
    bid_id: str | None,
    dry_run: bool,
) -> CarrierFollowupResponse:
    """Notify the selected carrier that the customer accepted their bid."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise RuntimeError("Shipment not found")

    result = await session.execute(
        select(CarrierBid, Carrier)
        .join(Carrier, Carrier.id == CarrierBid.carrier_id)
        .where(CarrierBid.shipment_id == shipment.id)
    )
    rows = result.all()
    if not rows:
        raise RuntimeError("No bids found for shipment")

    selected: tuple[CarrierBid, Carrier] | None = None
    if bid_id:
        for bid, carrier in rows:
            if str(bid.id) == bid_id:
                selected = (bid, carrier)
                break
        if selected is None:
            raise RuntimeError("Selected bid not found")
    else:
        selected_rows = [row for row in rows if row[0].status == "selected"]
        selected = selected_rows[0] if selected_rows else max(
            rows,
            key=lambda row: row[0].score_json.get("total", 0),
        )

    bid, carrier = selected
    client = await session.get(Client, shipment.client_id) if shipment.client_id else None
    if client is not None and carrier.email.strip().lower() == client.email.strip().lower():
        raise RuntimeError("Carrier award email matches customer email; manual review required.")

    existing = await session.scalar(
        select(WorkflowEvent)
        .where(
            WorkflowEvent.shipment_id == shipment.id,
            WorkflowEvent.event_type == WorkflowEventType.CARRIER_AWARD_SENT.value,
        )
        .order_by(WorkflowEvent.created_at.desc())
    )
    existing_payload = dict(existing.payload_json or {}) if existing is not None else {}
    if (
        existing is not None
        and existing_payload.get("bid_id") == str(bid.id)
        and (dry_run or not existing_payload.get("dry_run"))
    ):
        return CarrierFollowupResponse(
            shipment_id=str(shipment.id),
            carrier_id=str(carrier.id),
            carrier_email=carrier.email,
            subject=str(existing_payload.get("subject") or "Carrier award confirmation"),
            body=str(existing_payload.get("body") or ""),
            dry_run=bool(existing_payload.get("dry_run", False)),
            delivery_mode=existing_payload.get("delivery_mode") or "already_sent",
            reply_to_provider_message_id=existing_payload.get("reply_to_provider_message_id"),
            email_message_id=existing_payload.get("email_message_id"),
        )

    thread = await _ensure_thread(session, shipment)
    subject = attach_quote_token(
        f"Customer confirmed {shipment.origin or 'Origin'} to {shipment.destination or 'Destination'}",
        thread.quote_token or shipment.quote_token or "Q-UNKNOWN",
    )
    body_lines = [
        "Customer confirmed this load, and your bid was selected.",
        f"Route: {shipment.origin or 'TBD'} to {shipment.destination or 'TBD'}",
        f"Equipment: {shipment.equipment_type or 'TBD'}",
        f"Carrier rate: ${float(bid.amount or 0):.2f} {bid.currency or 'USD'}",
    ]
    if shipment.ready_at_local:
        body_lines.append(
            f"Ready at: {format_ready_at_wall_display(shipment.ready_at_local, shipment.ready_at_timezone)}"
        )
    body_lines.extend(["", "We are moving this load to booking and will follow up with next steps."])
    body = "\n".join(body_lines)

    delivery_payload = await deliver_carrier_thread_email(
        session,
        shipment=shipment,
        carrier_email=carrier.email,
        subject=subject,
        body=body,
        dry_run=dry_run,
    )

    outbound_message: EmailMessage | None = None
    if shipment.email_thread_id and not dry_run:
        outbound_message = EmailMessage(
            organization_id=shipment.organization_id,
            thread_id=shipment.email_thread_id,
            sender=await organization_outlook_mailbox(session, shipment.organization_id),
            recipients_json=[carrier.email],
            direction="outbound",
            subject=subject,
            body_preview=body[:1000],
            raw_payload_json={
                "type": "carrier_award_confirmation",
                "provider": "outlook",
                "dry_run": dry_run,
                "bid_id": str(bid.id),
                "carrier_id": str(carrier.id),
                "carrier_email": carrier.email,
                **delivery_payload,
            },
            received_at=datetime.now(timezone.utc),
        )
        session.add(outbound_message)
        await session.flush()

    shipment.updated_at = datetime.now(timezone.utc)
    thread.last_message_at = shipment.updated_at
    workflow_event = WorkflowEvent(
        organization_id=shipment.organization_id,
        shipment_id=shipment.id,
        event_type=WorkflowEventType.CARRIER_AWARD_SENT.value,
        stage=shipment.status,
        payload_json={
            "dry_run": dry_run,
            "subject": subject,
            "body": body,
            "bid_id": str(bid.id),
            "carrier_id": str(carrier.id),
            "carrier_email": carrier.email,
            "email_message_id": str(outbound_message.id) if outbound_message is not None else None,
            **delivery_payload,
        },
    )
    session.add(workflow_event)
    await session.commit()
    await freight_realtime_hub.notify_workflow_event(workflow_event)

    return CarrierFollowupResponse(
        shipment_id=str(shipment.id),
        carrier_id=str(carrier.id),
        carrier_email=carrier.email,
        subject=subject,
        body=body,
        dry_run=dry_run,
        delivery_mode=delivery_payload["delivery_mode"],
        reply_to_provider_message_id=delivery_payload.get("reply_to_provider_message_id"),
        email_message_id=str(outbound_message.id) if outbound_message is not None else None,
    )
