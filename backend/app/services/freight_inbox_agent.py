"""Freight-specific inbox orchestrator for email-driven workflows."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.memory.database import Carrier, CarrierBid, Client, EmailMessage, Shipment, WorkflowEvent
from app.schemas import (
    BidIntakeRequest,
    CarrierBidExtractionResult,
    IntentResult,
    ShipmentExtractionResult,
    ShipmentStage,
    WorkflowDecisionResult,
    WorkflowEventType,
)
from app.services.freight_ai import (
    classify_email_intent,
    extract_carrier_bid,
    extract_shipment_details,
)
from app.services.freight_execution import (
    evaluate_shipment_bids,
    intake_bid,
    send_client_acknowledgement,
    send_customer_quote,
)
from app.services.freight_outreach import create_carrier_outreach

CRITICAL_SHIPMENT_FIELDS = {"origin", "destination"}
AUTO_INTENT_CONFIDENCE = 0.6
AUTO_PARSE_CONFIDENCE = 0.65
AUTO_BID_CONFIDENCE = 0.6


async def run_freight_inbox_orchestrator(
    session: AsyncSession,
    *,
    email_message_id: str | UUID,
) -> WorkflowDecisionResult:
    """Run inbox decisioning for a saved inbound email."""
    email_uuid = UUID(str(email_message_id))
    email_message = await session.get(EmailMessage, email_uuid)
    if email_message is None:
        raise RuntimeError("Email message not found")

    shipment = await session.scalar(
        select(Shipment).where(Shipment.email_thread_id == email_message.thread_id)
    )
    client = await session.scalar(select(Client).where(Client.email == email_message.sender))
    carrier = await session.scalar(select(Carrier).where(Carrier.email == email_message.sender))

    email_context = {
        "sender_email": email_message.sender,
        "sender_role": "carrier" if carrier is not None else "client" if client is not None else "unknown",
        "subject": email_message.subject,
        "body_preview": email_message.body_preview,
        "thread_subject": email_message.subject,
        "shipment_status": shipment.status if shipment else "",
        "known_client": client.email if client else "",
        "known_carrier": carrier.email if carrier else "",
    }
    intent_result = await classify_email_intent(email_context)

    if shipment is None:
        await _log_event(
            session,
            None,
            WorkflowEventType.MANUAL_REVIEW_REQUIRED.value,
            ShipmentStage.RECEIVED.value,
            {"reason": "No shipment linked to inbound email", "intent": intent_result.intent},
        )
        return WorkflowDecisionResult(
            email_message_id=str(email_message.id),
            intent=intent_result.intent,
            confidence=intent_result.confidence,
            next_action="manual_review",
            manual_review_required=True,
        )

    if intent_result.confidence < AUTO_INTENT_CONFIDENCE:
        await _log_manual_review(
            session,
            shipment.id,
            f"Low intent confidence for {intent_result.intent}",
            intent_result=intent_result,
        )
        return WorkflowDecisionResult(
            email_message_id=str(email_message.id),
            shipment_id=str(shipment.id),
            intent=intent_result.intent,
            confidence=intent_result.confidence,
            next_action="manual_review",
            manual_review_required=True,
        )

    if intent_result.intent == "new_quote_request":
        return await _handle_new_quote_request(
            session,
            email_message=email_message,
            shipment=shipment,
            client=client,
            intent_result=intent_result,
            email_context=email_context,
        )
    if intent_result.intent == "carrier_bid_reply":
        return await _handle_carrier_bid_reply(
            session,
            email_message=email_message,
            shipment=shipment,
            carrier=carrier,
            intent_result=intent_result,
            email_context=email_context,
        )
    if intent_result.intent == "customer_clarification":
        return await _handle_customer_clarification(
            session,
            email_message=email_message,
            shipment=shipment,
            client=client,
            intent_result=intent_result,
            email_context=email_context,
        )
    if intent_result.intent == "customer_quote_confirmation":
        await _log_event(
            session,
            shipment.id,
            WorkflowEventType.CUSTOMER_CONFIRMED.value,
            shipment.status,
            {
                "source_email_id": str(email_message.id),
                "intent": intent_result.intent,
                "confidence": intent_result.confidence,
                "next_action": "phase_2_booking_pending",
                "manual_review_required": False,
            },
        )
        return WorkflowDecisionResult(
            email_message_id=str(email_message.id),
            shipment_id=str(shipment.id),
            intent=intent_result.intent,
            confidence=intent_result.confidence,
            next_action="phase_2_booking_pending",
        )

    return WorkflowDecisionResult(
        email_message_id=str(email_message.id),
        shipment_id=str(shipment.id),
        intent=intent_result.intent,
        confidence=intent_result.confidence,
        next_action="no_action",
    )


async def evaluate_expired_quote_windows(session: AsyncSession) -> list[WorkflowDecisionResult]:
    """Evaluate shipments whose bid collection windows are already expired."""
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(Shipment)
        .where(Shipment.status == ShipmentStage.WAITING_BIDS.value)
        .order_by(Shipment.updated_at.asc())
    )
    decisions: list[WorkflowDecisionResult] = []
    for shipment in result.scalars().all():
        outreach_event = await session.scalar(
            select(WorkflowEvent)
            .where(
                WorkflowEvent.shipment_id == shipment.id,
                WorkflowEvent.event_type == WorkflowEventType.CARRIER_OUTREACH_SENT.value,
            )
            .order_by(WorkflowEvent.created_at.desc())
        )
        if outreach_event is None:
            continue
        if outreach_event.created_at + timedelta(minutes=settings.quote_wait_minutes_default) > now:
            continue
        if await _has_event(session, shipment.id, WorkflowEventType.CLIENT_QUOTE_SENT.value):
            continue
        priced_bids = await session.scalar(
            select(CarrierBid).where(
                CarrierBid.shipment_id == shipment.id,
                CarrierBid.amount.is_not(None),
            )
        )
        if priced_bids is None:
            continue
        await evaluate_shipment_bids(session, shipment.id)
        await send_customer_quote(
            session,
            shipment_id=shipment.id,
            bid_id=None,
            dry_run=False,
            custom_message=None,
        )
        decisions.append(
            WorkflowDecisionResult(
                email_message_id="",
                shipment_id=str(shipment.id),
                intent="system_evaluation",
                confidence=1.0,
                next_action="customer_quote_sent",
                evaluation_triggered=True,
                quote_auto_sent=True,
            )
        )
    return decisions


async def _handle_new_quote_request(
    session: AsyncSession,
    *,
    email_message: EmailMessage,
    shipment: Shipment,
    client: Client | None,
    intent_result: IntentResult,
    email_context: dict,
) -> WorkflowDecisionResult:
    extraction = await extract_shipment_details(email_context)
    _apply_shipment_extraction(shipment, extraction)
    await _log_event(
        session,
        shipment.id,
        WorkflowEventType.SHIPMENT_PARSED.value,
        ShipmentStage.PARSING.value,
        {
            "intent": intent_result.intent,
            "confidence": extraction.confidence,
            "missing_fields": extraction.missing_fields,
            "next_action": "parse_complete",
            "manual_review_required": False,
            "origin": extraction.origin,
            "destination": extraction.destination,
            "pallets": extraction.pallets,
            "weight_lb": extraction.weight_lb,
            "equipment_type": extraction.equipment_type,
        },
    )
    await session.commit()

    manual_review = extraction.confidence < AUTO_PARSE_CONFIDENCE
    critical_missing = [field for field in extraction.missing_fields if field in CRITICAL_SHIPMENT_FIELDS]
    if critical_missing:
        shipment.status = ShipmentStage.WAITING_CUSTOMER_DETAILS.value
        shipment.updated_at = datetime.now(timezone.utc)
        await _log_event(
            session,
            shipment.id,
            WorkflowEventType.SHIPMENT_PARSE_FAILED.value,
            shipment.status,
            {
                "reason": "Missing critical shipment fields",
                "missing_fields": extraction.missing_fields,
                "confidence": extraction.confidence,
                "intent": intent_result.intent,
                "next_action": "request_missing_info",
                "manual_review_required": manual_review,
            },
        )
        if client is not None:
            await send_customer_clarification(
                session,
                shipment_id=shipment.id,
                missing_fields=extraction.missing_fields,
            )
        else:
            await _log_manual_review(
                session,
                shipment.id,
                "Shipment missing client mapping for clarification",
                intent_result=intent_result,
            )
            manual_review = True
        return WorkflowDecisionResult(
            email_message_id=str(email_message.id),
            shipment_id=str(shipment.id),
            intent=intent_result.intent,
            confidence=extraction.confidence,
            next_action="request_missing_info",
            shipment_extracted=True,
            missing_fields=extraction.missing_fields,
            manual_review_required=manual_review,
        )

    if manual_review or client is None:
        await _log_manual_review(
            session,
            shipment.id,
            "Low parse confidence or unresolved client",
            intent_result=intent_result,
        )
        return WorkflowDecisionResult(
            email_message_id=str(email_message.id),
            shipment_id=str(shipment.id),
            intent=intent_result.intent,
            confidence=extraction.confidence,
            next_action="manual_review",
            shipment_extracted=True,
            missing_fields=extraction.missing_fields,
            manual_review_required=True,
        )

    ack = await send_client_acknowledgement(
        session,
        shipment_id=shipment.id,
        dry_run=False,
        custom_message=None,
    )
    outreach = await create_carrier_outreach(
        session,
        shipment_id=shipment.id,
        carrier_ids=[],
        dry_run=False,
        custom_message=None,
    )
    return WorkflowDecisionResult(
        email_message_id=str(email_message.id),
        shipment_id=str(shipment.id),
        intent=intent_result.intent,
        confidence=extraction.confidence,
        next_action="waiting_bids",
        shipment_extracted=True,
        missing_fields=extraction.missing_fields,
        acknowledgement_drafted=True,
        acknowledgement_subject=ack.subject,
        outreach_drafted=True,
        outreach_subject=outreach.subject,
        outreach_targeted=outreach.targeted,
    )


async def _handle_customer_clarification(
    session: AsyncSession,
    *,
    email_message: EmailMessage,
    shipment: Shipment,
    client: Client | None,
    intent_result: IntentResult,
    email_context: dict,
) -> WorkflowDecisionResult:
    extraction = await extract_shipment_details(email_context)
    _apply_shipment_extraction(shipment, extraction)
    await session.commit()
    if extraction.confidence >= AUTO_PARSE_CONFIDENCE and not [
        field for field in extraction.missing_fields if field in CRITICAL_SHIPMENT_FIELDS
    ] and client is not None:
        ack_sent = await _has_event(session, shipment.id, WorkflowEventType.CLIENT_ACK_SENT.value)
        outreach_sent = await _has_event(session, shipment.id, WorkflowEventType.CARRIER_OUTREACH_SENT.value)
        ack_subject = None
        outreach_subject = None
        outreach_targeted = 0
        if not ack_sent:
            ack = await send_client_acknowledgement(session, shipment_id=shipment.id, dry_run=False, custom_message=None)
            ack_subject = ack.subject
        if not outreach_sent:
            outreach = await create_carrier_outreach(
                session,
                shipment_id=shipment.id,
                carrier_ids=[],
                dry_run=False,
                custom_message=None,
            )
            outreach_subject = outreach.subject
            outreach_targeted = outreach.targeted
        return WorkflowDecisionResult(
            email_message_id=str(email_message.id),
            shipment_id=str(shipment.id),
            intent=intent_result.intent,
            confidence=extraction.confidence,
            next_action="waiting_bids",
            shipment_extracted=True,
            missing_fields=extraction.missing_fields,
            acknowledgement_drafted=ack_subject is not None,
            acknowledgement_subject=ack_subject,
            outreach_drafted=outreach_subject is not None,
            outreach_subject=outreach_subject,
            outreach_targeted=outreach_targeted,
        )
    await _log_manual_review(
        session,
        shipment.id,
        "Customer clarification still incomplete",
        intent_result=intent_result,
    )
    return WorkflowDecisionResult(
        email_message_id=str(email_message.id),
        shipment_id=str(shipment.id),
        intent=intent_result.intent,
        confidence=extraction.confidence,
        next_action="manual_review",
        shipment_extracted=True,
        missing_fields=extraction.missing_fields,
        manual_review_required=True,
    )


async def _handle_carrier_bid_reply(
    session: AsyncSession,
    *,
    email_message: EmailMessage,
    shipment: Shipment,
    carrier: Carrier | None,
    intent_result: IntentResult,
    email_context: dict,
) -> WorkflowDecisionResult:
    if carrier is None:
        await _log_manual_review(
            session,
            shipment.id,
            "Carrier reply could not be mapped to known carrier",
            intent_result=intent_result,
        )
        return WorkflowDecisionResult(
            email_message_id=str(email_message.id),
            shipment_id=str(shipment.id),
            intent=intent_result.intent,
            confidence=intent_result.confidence,
            next_action="manual_review",
            manual_review_required=True,
        )

    extraction = await extract_carrier_bid(email_context)
    if extraction.amount is None or extraction.confidence < AUTO_BID_CONFIDENCE:
        await _log_event(
            session,
            shipment.id,
            WorkflowEventType.BID_PARSE_FAILED.value,
            shipment.status,
            {
                "carrier_id": str(carrier.id),
                "confidence": extraction.confidence,
                "notes": extraction.notes,
            },
        )
        await _log_manual_review(
            session,
            shipment.id,
            "Carrier bid parsing confidence too low",
            intent_result=intent_result,
        )
        return WorkflowDecisionResult(
            email_message_id=str(email_message.id),
            shipment_id=str(shipment.id),
            intent=intent_result.intent,
            confidence=extraction.confidence,
            next_action="manual_review",
            manual_review_required=True,
        )

    bid = await intake_bid(
        session,
        BidIntakeRequest(
            shipment_id=str(shipment.id),
            carrier_id=str(carrier.id),
            carrier_email=carrier.email,
            email_message_id=str(email_message.id),
            subject=email_message.subject,
            amount=float(extraction.amount),
            currency=extraction.currency or "USD",
            eta_text=extraction.eta_text,
            raw_email=email_message.body_preview,
            create_carrier_if_missing=False,
        ),
    )

    evaluation_triggered = False
    quote_auto_sent = False
    outreach_event = await session.scalar(
        select(WorkflowEvent)
        .where(
            WorkflowEvent.shipment_id == shipment.id,
            WorkflowEvent.event_type == WorkflowEventType.CARRIER_OUTREACH_SENT.value,
        )
        .order_by(WorkflowEvent.created_at.desc())
    )
    if (
        outreach_event is not None
        and outreach_event.created_at + timedelta(minutes=settings.quote_wait_minutes_default)
        <= datetime.now(timezone.utc)
        and not await _has_event(session, shipment.id, WorkflowEventType.CLIENT_QUOTE_SENT.value)
    ):
        await evaluate_shipment_bids(session, shipment.id)
        await send_customer_quote(
            session,
            shipment_id=shipment.id,
            bid_id=None,
            dry_run=False,
            custom_message=None,
        )
        evaluation_triggered = True
        quote_auto_sent = True

    return WorkflowDecisionResult(
        email_message_id=str(email_message.id),
        shipment_id=str(shipment.id),
        intent=intent_result.intent,
        confidence=extraction.confidence,
        next_action="waiting_bids" if not quote_auto_sent else "customer_quote_sent",
        bid_intaken=True,
        bid_id=bid.bid.id,
        bid_amount=bid.bid.amount,
        evaluation_triggered=evaluation_triggered,
        quote_auto_sent=quote_auto_sent,
    )


def _apply_shipment_extraction(shipment: Shipment, extraction: ShipmentExtractionResult) -> None:
    shipment.status = ShipmentStage.PARSING.value
    shipment.updated_at = datetime.now(timezone.utc)
    shipment.origin = extraction.origin or shipment.origin
    shipment.destination = extraction.destination or shipment.destination
    shipment.pallets = extraction.pallets if extraction.pallets is not None else shipment.pallets
    shipment.weight_lb = extraction.weight_lb if extraction.weight_lb is not None else shipment.weight_lb
    shipment.equipment_type = extraction.equipment_type or shipment.equipment_type
    shipment.ready_at = extraction.ready_at or shipment.ready_at
    if extraction.notes:
        shipment.notes = extraction.notes


async def send_customer_clarification(
    session: AsyncSession,
    *,
    shipment_id: UUID,
    missing_fields: list[str],
) -> None:
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None or shipment.client_id is None or shipment.email_thread_id is None:
        raise RuntimeError("Shipment is not ready for customer clarification")
    client = await session.get(Client, shipment.client_id)
    if client is None:
        raise RuntimeError("Client not found for clarification")
    body = (
        "We need a few more details before we can price this load.\n\n"
        f"Missing fields: {', '.join(missing_fields)}\n\n"
        "Please reply with the missing information and we will continue right away."
    )
    from app.services.outlook import OutlookGraphClient

    subject = f"Need more details for your quote [{shipment.quote_token or 'Q-UNKNOWN'}]"
    outlook = OutlookGraphClient()
    await outlook.send_mail(subject=subject, body=body, recipients=[client.email])
    session.add(
        EmailMessage(
            thread_id=shipment.email_thread_id,
            sender=settings.microsoft_mailbox or "unknown",
            recipients_json=[client.email],
            direction="outbound",
            subject=subject,
            body_preview=body[:1000],
            raw_payload_json={"type": "customer_clarification", "missing_fields": missing_fields},
            received_at=datetime.now(timezone.utc),
        )
    )
    shipment.status = ShipmentStage.WAITING_CUSTOMER_DETAILS.value
    shipment.updated_at = datetime.now(timezone.utc)
    await session.commit()


async def _has_event(session: AsyncSession, shipment_id: UUID, event_type: str) -> bool:
    event = await session.scalar(
        select(WorkflowEvent).where(
            WorkflowEvent.shipment_id == shipment_id,
            WorkflowEvent.event_type == event_type,
        )
    )
    return event is not None


async def _log_event(
    session: AsyncSession,
    shipment_id: UUID | None,
    event_type: str,
    stage: str,
    payload: dict,
) -> None:
    if shipment_id is None:
        return
    session.add(
        WorkflowEvent(
            shipment_id=shipment_id,
            event_type=event_type,
            stage=stage,
            payload_json=payload,
        )
    )
    await session.commit()


async def _log_manual_review(
    session: AsyncSession,
    shipment_id: UUID,
    reason: str,
    *,
    intent_result: IntentResult,
) -> None:
    await _log_event(
        session,
        shipment_id,
        WorkflowEventType.MANUAL_REVIEW_REQUIRED.value,
        ShipmentStage.PARSING.value,
        {
            "reason": reason,
            "intent": intent_result.intent,
            "confidence": intent_result.confidence,
            "next_action": "manual_review",
            "manual_review_required": True,
        },
    )
