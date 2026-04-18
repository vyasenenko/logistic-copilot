"""Core freight workflow execution helpers beyond carrier outreach."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.memory.database import Carrier, CarrierBid, Client, EmailMessage, EmailThread, Shipment, WorkflowEvent
from app.schemas import (
    BidIntakeRequest,
    BidIntakeResponse,
    BidRecord,
    ClientAcknowledgementResponse,
    CustomerQuoteResponse,
    ShipmentEvaluationResponse,
    ShipmentStage,
    TmsHandoffResponse,
    WorkflowEventType,
)
from app.services.email_correlation import attach_quote_token, extract_quote_token
from app.services.outlook import OutlookGraphClient
from app.services.tms_connector import TmsConnector


def _display_name_from_email(email: str) -> str:
    local_part = email.split("@", 1)[0]
    return local_part.replace(".", " ").replace("_", " ").title() or email


def _serialize_bid(bid: CarrierBid, carrier: Carrier) -> BidRecord:
    return BidRecord(
        id=str(bid.id),
        shipment_id=str(bid.shipment_id),
        carrier_id=str(carrier.id),
        carrier_name=carrier.name,
        carrier_email=carrier.email,
        amount=bid.amount,
        currency=bid.currency,
        eta_text=bid.eta_text,
        status=bid.status,
        score=dict(bid.score_json or {}),
        received_at=bid.received_at,
    )


async def _resolve_shipment(session: AsyncSession, request: BidIntakeRequest) -> Shipment:
    shipment = None
    if request.shipment_id:
        shipment = await session.get(Shipment, UUID(request.shipment_id))
    elif request.subject:
        quote_token = extract_quote_token(request.subject)
        if quote_token:
            shipment = await session.scalar(select(Shipment).where(Shipment.quote_token == quote_token))

    if shipment is None:
        raise RuntimeError("Shipment not found for bid intake")
    return shipment


async def _resolve_carrier(session: AsyncSession, request: BidIntakeRequest) -> tuple[Carrier, bool]:
    carrier = None
    created = False
    if request.carrier_id:
        carrier = await session.get(Carrier, UUID(request.carrier_id))
    elif request.carrier_email:
        carrier = await session.scalar(
            select(Carrier).where(Carrier.email == request.carrier_email.lower())
        )

    if carrier is None and request.create_carrier_if_missing and request.carrier_email:
        carrier = Carrier(
            name=_display_name_from_email(request.carrier_email),
            email=request.carrier_email.lower(),
            rating=0,
            is_active=True,
            regions_json=[],
            equipment_json=[],
            metadata_json={"source": "bid_intake"},
        )
        session.add(carrier)
        await session.flush()
        created = True

    if carrier is None:
        raise RuntimeError("Carrier not found for bid intake")

    return carrier, created


async def intake_bid(session: AsyncSession, request: BidIntakeRequest) -> BidIntakeResponse:
    """Create or update a carrier bid from a reply/manual intake payload."""
    shipment = await _resolve_shipment(session, request)
    carrier, created_carrier = await _resolve_carrier(session, request)

    created_email_message = False
    email_message_id = UUID(request.email_message_id) if request.email_message_id else None
    if email_message_id is None and shipment.email_thread_id:
        email_message = EmailMessage(
            thread_id=shipment.email_thread_id,
            sender=carrier.email,
            recipients_json=[settings.microsoft_mailbox or "unknown"],
            direction="inbound",
            subject=request.subject or attach_quote_token("Carrier bid response", shipment.quote_token or "Q-UNKNOWN"),
            body_preview=request.raw_email[:1000],
            raw_payload_json={
                "source": "bid_intake",
                "carrier_email": carrier.email,
            },
            received_at=datetime.now(timezone.utc),
        )
        session.add(email_message)
        await session.flush()
        email_message_id = email_message.id
        created_email_message = True

    bid = await session.scalar(
        select(CarrierBid).where(
            CarrierBid.shipment_id == shipment.id,
            CarrierBid.carrier_id == carrier.id,
        )
    )
    now = datetime.now(timezone.utc)
    if bid is None:
        bid = CarrierBid(
            shipment_id=shipment.id,
            carrier_id=carrier.id,
            email_message_id=email_message_id,
            amount=request.amount,
            currency=request.currency,
            eta_text=request.eta_text,
            status="received",
            raw_email=request.raw_email,
            received_at=now,
        )
        session.add(bid)
        await session.flush()
    else:
        bid.email_message_id = email_message_id or bid.email_message_id
        bid.amount = request.amount
        bid.currency = request.currency
        bid.eta_text = request.eta_text
        bid.status = "received"
        bid.raw_email = request.raw_email or bid.raw_email
        bid.received_at = now

    shipment.status = ShipmentStage.WAITING_BIDS.value
    shipment.updated_at = now
    session.add(
        WorkflowEvent(
            shipment_id=shipment.id,
            event_type=WorkflowEventType.BID_RECEIVED.value,
            stage=shipment.status,
            payload_json={
                "carrier_id": str(carrier.id),
                "amount": request.amount,
                "currency": request.currency,
                "eta_text": request.eta_text,
            },
        )
    )
    await session.commit()
    await session.refresh(bid)

    return BidIntakeResponse(
        shipment_id=str(shipment.id),
        bid=_serialize_bid(bid, carrier),
        created_carrier=created_carrier,
        created_email_message=created_email_message,
    )


def _score_bid(bid: CarrierBid, carrier: Carrier, cheapest_amount: float) -> dict:
    amount = bid.amount or 0
    price_score = 100.0 if cheapest_amount <= 0 else max(0.0, 100 - ((amount - cheapest_amount) / cheapest_amount) * 100)
    rating_score = min(carrier.rating * 20, 100)
    eta_score = 15 if bid.eta_text else 0
    total = round(price_score * 0.65 + rating_score * 0.25 + eta_score * 0.10, 2)
    return {
        "price_score": round(price_score, 2),
        "rating_score": round(rating_score, 2),
        "eta_score": eta_score,
        "total": total,
    }


def _margin_amount(base_amount: float, margin_policy: dict) -> float:
    percent = float(margin_policy.get("percent", settings.profit_margin_percent_default))
    floor_amount = float(margin_policy.get("floor_amount", settings.profit_margin_floor_default))
    return round(max(base_amount * (percent / 100), floor_amount), 2)


async def send_client_acknowledgement(
    session: AsyncSession,
    *,
    shipment_id: UUID,
    dry_run: bool,
    custom_message: str | None,
) -> ClientAcknowledgementResponse:
    """Build and optionally send the initial customer acknowledgement."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise RuntimeError("Shipment not found")
    if shipment.client_id is None:
        raise RuntimeError("Shipment has no linked client")

    client = await session.get(Client, shipment.client_id)
    if client is None:
        raise RuntimeError("Client not found for shipment")

    thread = await session.get(EmailThread, shipment.email_thread_id) if shipment.email_thread_id else None
    subject_token = shipment.quote_token or (thread.quote_token if thread else None) or "Q-UNKNOWN"
    subject = attach_quote_token(
        thread.subject if thread and thread.subject else "Quote request received",
        subject_token,
    )

    wait_window = settings.quote_wait_minutes_default
    body_lines = [
        f"Hi {client.name},",
        "",
        "Thanks for sending this quote request. We're reviewing the shipment now.",
        f"We'll be back with pricing within about {wait_window} minutes.",
        "",
        f"Route: {shipment.origin or 'TBD'} to {shipment.destination or 'TBD'}",
        f"Equipment: {shipment.equipment_type or 'TBD'}",
        f"Pallets: {shipment.pallets if shipment.pallets is not None else 'TBD'}",
        f"Weight (lb): {shipment.weight_lb if shipment.weight_lb is not None else 'TBD'}",
    ]
    if shipment.ready_at:
        body_lines.append(
            f"Requested ready time: {shipment.ready_at.astimezone(timezone.utc).isoformat()}"
        )
    if custom_message:
        body_lines.extend(["", custom_message.strip()])
    body_lines.extend(["", "We'll follow up shortly with the best option available."])
    body = "\n".join(body_lines)

    if not dry_run:
        outlook = OutlookGraphClient()
        await outlook.send_mail(subject=subject, body=body, recipients=[client.email])

    if shipment.email_thread_id:
        session.add(
            EmailMessage(
                thread_id=shipment.email_thread_id,
                sender=settings.microsoft_mailbox or "unknown",
                recipients_json=[client.email],
                direction="outbound",
                subject=subject,
                body_preview=body[:1000],
                raw_payload_json={"type": "customer_ack", "dry_run": dry_run},
                received_at=datetime.now(timezone.utc),
            )
        )

    shipment.status = ShipmentStage.CLIENT_ACKNOWLEDGED.value
    shipment.updated_at = datetime.now(timezone.utc)
    session.add(
        WorkflowEvent(
            shipment_id=shipment.id,
            event_type=WorkflowEventType.CLIENT_ACK_SENT.value,
            stage=shipment.status,
            payload_json={
                "client_email": client.email,
                "dry_run": dry_run,
                "wait_window_minutes": wait_window,
            },
        )
    )
    await session.commit()

    return ClientAcknowledgementResponse(
        shipment_id=str(shipment.id),
        client_email=client.email,
        subject=subject,
        body=body,
        dry_run=dry_run,
    )


async def evaluate_shipment_bids(session: AsyncSession, shipment_id: UUID) -> ShipmentEvaluationResponse:
    """Score bids for a shipment and select the recommended option."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise RuntimeError("Shipment not found")

    result = await session.execute(
        select(CarrierBid, Carrier)
        .join(Carrier, Carrier.id == CarrierBid.carrier_id)
        .where(CarrierBid.shipment_id == shipment.id, CarrierBid.amount.is_not(None))
    )
    rows = result.all()
    if not rows:
        raise RuntimeError("No priced bids available for evaluation")

    cheapest_amount = min((bid.amount or 0) for bid, _carrier in rows if bid.amount is not None)
    scored: list[tuple[CarrierBid, Carrier]] = []
    for bid, carrier in rows:
        bid.score_json = _score_bid(bid, carrier, cheapest_amount)
        scored.append((bid, carrier))

    winner_bid, winner_carrier = max(scored, key=lambda pair: pair[0].score_json.get("total", 0))
    for bid, _carrier in scored:
        bid.status = "selected" if bid.id == winner_bid.id else "received"

    shipment.status = ShipmentStage.EVALUATING.value
    shipment.updated_at = datetime.now(timezone.utc)
    margin_amount = _margin_amount(winner_bid.amount or 0, dict(shipment.margin_policy_json or {}))
    recommended_quote = round((winner_bid.amount or 0) + margin_amount, 2)
    session.add(
        WorkflowEvent(
            shipment_id=shipment.id,
            event_type=WorkflowEventType.EVALUATION_COMPLETED.value,
            stage=shipment.status,
            payload_json={
                "selected_bid_id": str(winner_bid.id),
                "selected_carrier_id": str(winner_carrier.id),
                "recommended_quote_amount": recommended_quote,
                "margin_amount": margin_amount,
            },
        )
    )
    await session.commit()

    return ShipmentEvaluationResponse(
        shipment_id=str(shipment.id),
        selected_bid_id=str(winner_bid.id),
        selected_carrier_id=str(winner_carrier.id),
        selected_amount=float(winner_bid.amount or 0),
        recommended_quote_amount=recommended_quote,
        margin_amount=margin_amount,
        results=[_serialize_bid(bid, carrier) for bid, carrier in scored],
    )


async def _get_selected_bid(session: AsyncSession, shipment: Shipment, bid_id: str | None) -> tuple[CarrierBid, Carrier]:
    result = await session.execute(
        select(CarrierBid, Carrier)
        .join(Carrier, Carrier.id == CarrierBid.carrier_id)
        .where(CarrierBid.shipment_id == shipment.id)
    )
    rows = result.all()
    if not rows:
        raise RuntimeError("No bids found for shipment")

    if bid_id:
        for bid, carrier in rows:
            if str(bid.id) == bid_id:
                return bid, carrier
        raise RuntimeError("Selected bid not found")

    selected = [row for row in rows if row[0].status == "selected"]
    if selected:
        return selected[0]

    best = max(rows, key=lambda row: row[0].score_json.get("total", 0))
    return best


async def send_customer_quote(
    session: AsyncSession,
    *,
    shipment_id: UUID,
    bid_id: str | None,
    dry_run: bool,
    custom_message: str | None,
) -> CustomerQuoteResponse:
    """Send or preview the customer quote based on the winning bid."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise RuntimeError("Shipment not found")
    if shipment.client_id is None:
        raise RuntimeError("Shipment has no linked client")

    client = await session.get(Client, shipment.client_id)
    if client is None:
        raise RuntimeError("Client not found for shipment")

    bid, _carrier = await _get_selected_bid(session, shipment, bid_id)
    base_amount = float(bid.amount or 0)
    margin_amount = _margin_amount(base_amount, dict(shipment.margin_policy_json or {}))
    final_amount = round(base_amount + margin_amount, 2)
    subject = attach_quote_token(
        f"Quote {shipment.origin or 'Origin'} to {shipment.destination or 'Destination'}",
        shipment.quote_token or "Q-UNKNOWN",
    )
    body_lines = [
        f"We can cover this load for ${final_amount:.2f}.",
        f"Base carrier cost: ${base_amount:.2f}",
        f"Margin applied: ${margin_amount:.2f}",
        f"Route: {shipment.origin or 'TBD'} to {shipment.destination or 'TBD'}",
    ]
    if shipment.ready_at:
        body_lines.append(f"Ready at: {shipment.ready_at.astimezone(timezone.utc).isoformat()}")
    if custom_message:
        body_lines.extend(["", custom_message.strip()])
    body_lines.extend(["", "Reply OK to confirm booking."])
    body = "\n".join(body_lines)

    if not dry_run:
        outlook = OutlookGraphClient()
        await outlook.send_mail(subject=subject, body=body, recipients=[client.email])

    if shipment.email_thread_id:
        session.add(
            EmailMessage(
                thread_id=shipment.email_thread_id,
                sender=settings.microsoft_mailbox or "unknown",
                recipients_json=[client.email],
                direction="outbound",
                subject=subject,
                body_preview=body[:1000],
                raw_payload_json={"type": "customer_quote", "dry_run": dry_run},
                received_at=datetime.now(timezone.utc),
            )
        )

    shipment.status = (
        ShipmentStage.AWAITING_CONFIRMATION.value if not dry_run else ShipmentStage.QUOTED.value
    )
    shipment.updated_at = datetime.now(timezone.utc)
    session.add(
        WorkflowEvent(
            shipment_id=shipment.id,
            event_type=WorkflowEventType.CLIENT_QUOTE_SENT.value,
            stage=shipment.status,
            payload_json={
                "bid_id": str(bid.id),
                "client_email": client.email,
                "final_amount": final_amount,
                "dry_run": dry_run,
            },
        )
    )
    await session.commit()

    return CustomerQuoteResponse(
        shipment_id=str(shipment.id),
        bid_id=str(bid.id),
        client_email=client.email,
        subject=subject,
        body=body,
        base_amount=base_amount,
        margin_amount=margin_amount,
        final_amount=final_amount,
        dry_run=dry_run,
    )


async def handoff_to_tms(
    session: AsyncSession,
    *,
    shipment_id: UUID,
    bid_id: str | None,
    dry_run: bool,
) -> TmsHandoffResponse:
    """Preview or submit the selected load to the TMS."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise RuntimeError("Shipment not found")

    bid, carrier = await _get_selected_bid(session, shipment, bid_id)
    client = await session.get(Client, shipment.client_id) if shipment.client_id else None
    payload = {
        "shipment_id": str(shipment.id),
        "quote_token": shipment.quote_token,
        "client": {
            "id": str(client.id) if client else None,
            "name": client.name if client else None,
            "email": client.email if client else None,
        },
        "carrier": {
            "id": str(carrier.id),
            "name": carrier.name,
            "email": carrier.email,
        },
        "lane": {
            "origin": shipment.origin,
            "destination": shipment.destination,
            "pallets": shipment.pallets,
            "weight_lb": shipment.weight_lb,
            "equipment_type": shipment.equipment_type,
            "ready_at": shipment.ready_at.astimezone(timezone.utc).isoformat() if shipment.ready_at else None,
        },
        "bid": {
            "id": str(bid.id),
            "amount": bid.amount,
            "currency": bid.currency,
            "eta_text": bid.eta_text,
        },
    }

    connector = TmsConnector()
    response_payload: dict = {}
    status = "preview"
    if not dry_run:
        response_payload = await connector.request("POST", "/loads", json=payload)
        status = "submitted"
        shipment.status = ShipmentStage.BOOKED.value
    else:
        shipment.status = ShipmentStage.AWAITING_CONFIRMATION.value

    shipment.updated_at = datetime.now(timezone.utc)
    session.add(
        WorkflowEvent(
            shipment_id=shipment.id,
            event_type=WorkflowEventType.TMS_HANDOFF_SENT.value,
            stage=shipment.status,
            payload_json={
                "bid_id": str(bid.id),
                "carrier_id": str(carrier.id),
                "dry_run": dry_run,
            },
        )
    )
    await session.commit()

    return TmsHandoffResponse(
        shipment_id=str(shipment.id),
        bid_id=str(bid.id),
        status=status,
        dry_run=dry_run,
        payload=payload,
        response=response_payload,
    )
