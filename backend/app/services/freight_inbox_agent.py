"""Freight-specific inbox orchestrator for email-driven workflows."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.memory.database import Carrier, CarrierBid, Client, EmailMessage, Shipment, WorkflowEvent
from app.schemas import (
    AutomationPolicy,
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
    extract_carrier_status_update,
    extract_carrier_bid,
    extract_shipment_details,
    extract_status_request,
)
from app.services.freight_execution import (
    confirm_booking_and_handoff,
    evaluate_shipment_bids,
    fetch_tms_shipment_status,
    intake_bid,
    push_carrier_status_to_tms,
    send_client_acknowledgement,
    send_customer_status_reply,
    send_customer_quote,
)
from app.services.freight_realtime import freight_realtime_hub
from app.services.location_timezone import normalize_delivery_datetime_fields, normalize_pickup_datetime_fields
from app.services.freight_outreach import create_carrier_outreach

CRITICAL_SHIPMENT_FIELDS = {"origin", "destination"}
RECOMMENDED_SHIPMENT_FIELDS = {"pallets", "weight_lb", "equipment_type", "ready_at"}
AUTO_INTENT_CONFIDENCE = 0.6
AUTO_PARSE_CONFIDENCE = 0.65
AUTO_BID_CONFIDENCE = 0.6


async def run_freight_inbox_orchestrator(
    session: AsyncSession,
    *,
    email_message_id: str | UUID,
    policy: AutomationPolicy | None = None,
) -> WorkflowDecisionResult:
    """Run inbox decisioning for a saved inbound email."""
    policy = policy or AutomationPolicy()
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
            policy=policy,
        )
    if intent_result.intent == "carrier_bid_reply":
        return await _handle_carrier_bid_reply(
            session,
            email_message=email_message,
            shipment=shipment,
            carrier=carrier,
            intent_result=intent_result,
            email_context=email_context,
            policy=policy,
        )
    if intent_result.intent == "customer_clarification":
        return await _handle_customer_clarification(
            session,
            email_message=email_message,
            shipment=shipment,
            client=client,
            intent_result=intent_result,
            email_context=email_context,
            policy=policy,
        )
    if intent_result.intent == "customer_status_request":
        return await _handle_customer_status_request(
            session,
            email_message=email_message,
            shipment=shipment,
            client=client,
            intent_result=intent_result,
            email_context=email_context,
        )
    if intent_result.intent == "carrier_status_update":
        return await _handle_carrier_status_update(
            session,
            email_message=email_message,
            shipment=shipment,
            carrier=carrier,
            intent_result=intent_result,
            email_context=email_context,
            policy=policy,
        )
    if intent_result.intent == "exception_or_issue":
        await _log_manual_review(
            session,
            shipment.id,
            "Exception or issue email requires operator review",
            intent_result=intent_result,
            review_type="customer_status_request_review" if client is not None else "carrier_status_update_review",
            next_action="manual_review",
            source_email_id=str(email_message.id),
            allow_repeat=policy.allow_repeat_manual_review,
        )
        return WorkflowDecisionResult(
            email_message_id=str(email_message.id),
            shipment_id=str(shipment.id),
            intent=intent_result.intent,
            confidence=intent_result.confidence,
            next_action="manual_review",
            manual_review_required=True,
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
                "next_action": "booking_in_progress" if policy.auto_book else "booking_ready_for_review",
                "manual_review_required": False,
            },
        )
        if not policy.auto_book:
            return WorkflowDecisionResult(
                email_message_id=str(email_message.id),
                shipment_id=str(shipment.id),
                intent=intent_result.intent,
                confidence=intent_result.confidence,
                next_action="booking_ready_for_review",
            )
        if shipment.status == ShipmentStage.BOOKED.value or await _has_event(
            session,
            shipment.id,
            WorkflowEventType.TMS_HANDOFF_SENT.value,
        ):
            return WorkflowDecisionResult(
                email_message_id=str(email_message.id),
                shipment_id=str(shipment.id),
                intent=intent_result.intent,
                confidence=intent_result.confidence,
                next_action="already_booked",
                booking_triggered=True,
                booking_confirmation_sent=True,
                tms_handoff_status="submitted",
            )

        handoff, confirmation = await confirm_booking_and_handoff(
            session,
            shipment_id=shipment.id,
            bid_id=None,
            dry_run=policy.booking_dry_run,
            custom_message=None,
        )
        return WorkflowDecisionResult(
            email_message_id=str(email_message.id),
            shipment_id=str(shipment.id),
            intent=intent_result.intent,
            confidence=intent_result.confidence,
            next_action="booked" if not policy.booking_dry_run else "booking_preview_ready",
            booking_triggered=True,
            booking_confirmation_sent=not confirmation.dry_run,
            tms_handoff_status=handoff.status,
        )

    return WorkflowDecisionResult(
        email_message_id=str(email_message.id),
        shipment_id=str(shipment.id),
        intent=intent_result.intent,
        confidence=intent_result.confidence,
        next_action="no_action",
    )


async def evaluate_expired_quote_windows(
    session: AsyncSession,
    *,
    policy: AutomationPolicy | None = None,
) -> list[WorkflowDecisionResult]:
    """Evaluate shipments whose bid collection windows are already expired."""
    policy = policy or AutomationPolicy()
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
        if not policy.auto_quote:
            decisions.append(
                WorkflowDecisionResult(
                    email_message_id="",
                    shipment_id=str(shipment.id),
                    intent="system_evaluation",
                    confidence=1.0,
                    next_action="quote_ready_for_review",
                    evaluation_triggered=True,
                )
            )
            continue
        await send_customer_quote(
            session,
            shipment_id=shipment.id,
            bid_id=None,
            dry_run=policy.quote_dry_run,
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
                quote_auto_sent=not policy.quote_dry_run,
            )
        )
    return decisions


async def continue_phase1_workflow(
    session: AsyncSession,
    *,
    shipment_id: str | UUID,
    policy: AutomationPolicy | None = None,
) -> WorkflowDecisionResult:
    """Continue a shipment workflow from its current persisted state."""
    policy = policy or AutomationPolicy()
    shipment_uuid = UUID(str(shipment_id))
    shipment = await session.get(Shipment, shipment_uuid)
    if shipment is None:
        raise RuntimeError("Shipment not found")

    missing_fields = [
        field
        for field, value in (
            ("origin", shipment.origin),
            ("destination", shipment.destination),
            ("pallets", shipment.pallets),
            ("weight_lb", shipment.weight_lb),
            ("equipment_type", shipment.equipment_type),
            ("ready_at", shipment.ready_at_local or shipment.ready_at),
        )
        if value in (None, "")
    ]

    if shipment.client_id is None or shipment.origin is None or shipment.destination is None:
        await _log_event(
            session,
            shipment.id,
            WorkflowEventType.MANUAL_REVIEW_REQUIRED.value,
            shipment.status,
            {
                "reason": "Operator attempted to continue incomplete shipment",
                "missing_fields": missing_fields,
                "next_action": "manual_review",
                "manual_review_required": True,
            },
        )
        return WorkflowDecisionResult(
            email_message_id="",
            shipment_id=str(shipment.id),
            intent="operator_continue",
            confidence=1.0,
            next_action="manual_review",
            missing_fields=missing_fields,
            manual_review_required=True,
        )

    ack_subject = None
    outreach_subject = None
    outreach_targeted = 0
    evaluation_triggered = False
    quote_auto_sent = False

    if policy.auto_acknowledgement and not await _has_event(session, shipment.id, WorkflowEventType.CLIENT_ACK_SENT.value):
        ack = await send_client_acknowledgement(
            session,
            shipment_id=shipment.id,
            dry_run=policy.acknowledgement_dry_run,
            custom_message=None,
        )
        ack_subject = ack.subject

    if policy.auto_outreach and not await _has_event(session, shipment.id, WorkflowEventType.CARRIER_OUTREACH_SENT.value):
        outreach = await create_carrier_outreach(
            session,
            shipment_id=shipment.id,
            carrier_ids=[],
            dry_run=policy.outreach_dry_run,
            custom_message=None,
        )
        outreach_subject = outreach.subject
        outreach_targeted = outreach.targeted

    priced_bid = await session.scalar(
        select(CarrierBid).where(
            CarrierBid.shipment_id == shipment.id,
            CarrierBid.amount.is_not(None),
        )
    )
    quote_sent = await _has_event(session, shipment.id, WorkflowEventType.CLIENT_QUOTE_SENT.value)
    if priced_bid is not None and not quote_sent:
        await evaluate_shipment_bids(session, shipment.id)
        evaluation_triggered = True
        if policy.auto_quote:
            await send_customer_quote(
                session,
                shipment_id=shipment.id,
                bid_id=None,
                dry_run=policy.quote_dry_run,
                custom_message=None,
            )
            quote_auto_sent = not policy.quote_dry_run

    next_action = "waiting_bids"
    if quote_auto_sent:
        next_action = "customer_quote_sent"
    elif evaluation_triggered and not quote_auto_sent:
        next_action = "quote_ready_for_review"
    elif outreach_subject is None and ack_subject is None:
        next_action = "workflow_already_current"

    return WorkflowDecisionResult(
        email_message_id="",
        shipment_id=str(shipment.id),
        intent="operator_continue",
        confidence=1.0,
        next_action=next_action,
        missing_fields=missing_fields,
        acknowledgement_drafted=ack_subject is not None,
        acknowledgement_subject=ack_subject,
        outreach_drafted=outreach_subject is not None,
        outreach_subject=outreach_subject,
        outreach_targeted=outreach_targeted,
        evaluation_triggered=evaluation_triggered,
        quote_auto_sent=quote_auto_sent,
    )


async def _handle_new_quote_request(
    session: AsyncSession,
    *,
    email_message: EmailMessage,
    shipment: Shipment,
    client: Client | None,
    intent_result: IntentResult,
    email_context: dict,
    policy: AutomationPolicy,
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
            "ambiguity_reasons": extraction.ambiguity_reasons,
            "next_action": "parse_complete",
            "manual_review_required": False,
            "source_email_id": str(email_message.id),
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
    recommended_missing = [field for field in extraction.missing_fields if field in RECOMMENDED_SHIPMENT_FIELDS]
    ambiguous = bool(extraction.ambiguity_reasons)
    clarification_needed = bool(critical_missing or (recommended_missing and not ambiguous))
    if ambiguous:
        await _log_event(
            session,
            shipment.id,
            WorkflowEventType.SHIPMENT_PARSE_FAILED.value,
            shipment.status,
            {
                "reason": "Ambiguous shipment details",
                "missing_fields": extraction.missing_fields,
                "ambiguity_reasons": extraction.ambiguity_reasons,
                "confidence": extraction.confidence,
                "intent": intent_result.intent,
                "next_action": "manual_review",
                "manual_review_required": True,
                "source_email_id": str(email_message.id),
            },
        )
        await _log_manual_review(
            session,
            shipment.id,
            f"Ambiguous shipment details: {', '.join(extraction.ambiguity_reasons)}",
            intent_result=intent_result,
            allow_repeat=policy.allow_repeat_manual_review,
        )
        return WorkflowDecisionResult(
            email_message_id=str(email_message.id),
            shipment_id=str(shipment.id),
            intent=intent_result.intent,
            confidence=extraction.confidence,
            next_action="manual_review",
            shipment_extracted=True,
            missing_fields=extraction.missing_fields,
            ambiguity_reasons=extraction.ambiguity_reasons,
            manual_review_required=True,
        )
    if clarification_needed:
        shipment.status = ShipmentStage.WAITING_CUSTOMER_DETAILS.value
        shipment.updated_at = datetime.now(timezone.utc)
        await _log_event(
            session,
            shipment.id,
            WorkflowEventType.SHIPMENT_PARSE_FAILED.value,
            shipment.status,
            {
                "reason": (
                    "Missing critical shipment fields"
                    if critical_missing
                    else "Missing recommended shipment fields"
                ),
                "missing_fields": extraction.missing_fields,
                "ambiguity_reasons": extraction.ambiguity_reasons,
                "confidence": extraction.confidence,
                "intent": intent_result.intent,
                "next_action": "request_missing_info",
                "manual_review_required": manual_review,
                "source_email_id": str(email_message.id),
            },
        )
        if client is not None:
            if not await _has_open_review(session, shipment.id, "Missing critical shipment fields"):
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
                allow_repeat=policy.allow_repeat_manual_review,
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
            ambiguity_reasons=extraction.ambiguity_reasons,
            manual_review_required=manual_review,
        )

    if manual_review or client is None:
        await _log_manual_review(
            session,
            shipment.id,
            "Low parse confidence or unresolved client",
            intent_result=intent_result,
            allow_repeat=policy.allow_repeat_manual_review,
        )
        return WorkflowDecisionResult(
            email_message_id=str(email_message.id),
            shipment_id=str(shipment.id),
            intent=intent_result.intent,
            confidence=extraction.confidence,
            next_action="manual_review",
            shipment_extracted=True,
            missing_fields=extraction.missing_fields,
            ambiguity_reasons=extraction.ambiguity_reasons,
            manual_review_required=True,
        )

    ack_subject = None
    outreach_subject = None
    outreach_targeted = 0
    try:
        if policy.auto_acknowledgement and not await _has_event(session, shipment.id, WorkflowEventType.CLIENT_ACK_SENT.value):
            ack = await send_client_acknowledgement(
                session,
                shipment_id=shipment.id,
                dry_run=policy.acknowledgement_dry_run,
                custom_message=None,
            )
            ack_subject = ack.subject
        if policy.auto_outreach and not await _has_event(session, shipment.id, WorkflowEventType.CARRIER_OUTREACH_SENT.value):
            outreach = await create_carrier_outreach(
                session,
                shipment_id=shipment.id,
                carrier_ids=[],
                dry_run=policy.outreach_dry_run,
                custom_message=None,
            )
            outreach_subject = outreach.subject
            outreach_targeted = outreach.targeted
    except RuntimeError as exc:
        await _log_manual_review(
            session,
            shipment.id,
            f"Quote intake automation blocked: {exc}",
            intent_result=intent_result,
            next_action="manual_review",
            allow_repeat=policy.allow_repeat_manual_review,
        )
        return WorkflowDecisionResult(
            email_message_id=str(email_message.id),
            shipment_id=str(shipment.id),
            intent=intent_result.intent,
            confidence=extraction.confidence,
            next_action="manual_review",
            shipment_extracted=True,
            missing_fields=extraction.missing_fields,
            ambiguity_reasons=extraction.ambiguity_reasons,
            acknowledgement_drafted=ack_subject is not None,
            acknowledgement_subject=ack_subject,
            manual_review_required=True,
        )
    next_action = "waiting_bids" if outreach_subject is not None else "awaiting_next_policy_action"
    return WorkflowDecisionResult(
        email_message_id=str(email_message.id),
        shipment_id=str(shipment.id),
        intent=intent_result.intent,
        confidence=extraction.confidence,
        next_action=next_action,
        shipment_extracted=True,
        missing_fields=extraction.missing_fields,
        acknowledgement_drafted=ack_subject is not None,
        acknowledgement_subject=ack_subject,
        outreach_drafted=outreach_subject is not None,
        outreach_subject=outreach_subject,
        outreach_targeted=outreach_targeted,
    )


async def _handle_customer_clarification(
    session: AsyncSession,
    *,
    email_message: EmailMessage,
    shipment: Shipment,
    client: Client | None,
    intent_result: IntentResult,
    email_context: dict,
    policy: AutomationPolicy,
) -> WorkflowDecisionResult:
    extraction = await extract_shipment_details(email_context)
    _apply_shipment_extraction(shipment, extraction)
    await session.commit()
    await freight_realtime_hub.publish_shipment_updated(shipment_id=str(shipment.id))
    if extraction.ambiguity_reasons:
        await _log_manual_review(
            session,
            shipment.id,
            f"Ambiguous clarification details: {', '.join(extraction.ambiguity_reasons)}",
            intent_result=intent_result,
            allow_repeat=policy.allow_repeat_manual_review,
        )
        return WorkflowDecisionResult(
            email_message_id=str(email_message.id),
            shipment_id=str(shipment.id),
            intent=intent_result.intent,
            confidence=extraction.confidence,
            next_action="manual_review",
            shipment_extracted=True,
            missing_fields=extraction.missing_fields,
            ambiguity_reasons=extraction.ambiguity_reasons,
            manual_review_required=True,
        )
    if extraction.confidence >= AUTO_PARSE_CONFIDENCE and not [
        field for field in extraction.missing_fields if field in CRITICAL_SHIPMENT_FIELDS
    ] and client is not None:
        ack_sent = await _has_event(session, shipment.id, WorkflowEventType.CLIENT_ACK_SENT.value)
        outreach_sent = await _has_event(session, shipment.id, WorkflowEventType.CARRIER_OUTREACH_SENT.value)
        ack_subject = None
        outreach_subject = None
        outreach_targeted = 0
        try:
            if policy.auto_acknowledgement and not ack_sent:
                ack = await send_client_acknowledgement(
                    session,
                    shipment_id=shipment.id,
                    dry_run=policy.acknowledgement_dry_run,
                    custom_message=None,
                )
                ack_subject = ack.subject
            if policy.auto_outreach and not outreach_sent:
                outreach = await create_carrier_outreach(
                    session,
                    shipment_id=shipment.id,
                    carrier_ids=[],
                    dry_run=policy.outreach_dry_run,
                    custom_message=None,
                )
                outreach_subject = outreach.subject
                outreach_targeted = outreach.targeted
        except RuntimeError as exc:
            await _log_manual_review(
                session,
                shipment.id,
                f"Clarification automation blocked: {exc}",
                intent_result=intent_result,
                next_action="manual_review",
                allow_repeat=policy.allow_repeat_manual_review,
            )
            return WorkflowDecisionResult(
                email_message_id=str(email_message.id),
                shipment_id=str(shipment.id),
                intent=intent_result.intent,
                confidence=extraction.confidence,
                next_action="manual_review",
                shipment_extracted=True,
                missing_fields=extraction.missing_fields,
                ambiguity_reasons=extraction.ambiguity_reasons,
                acknowledgement_drafted=ack_subject is not None,
                acknowledgement_subject=ack_subject,
                manual_review_required=True,
            )
        return WorkflowDecisionResult(
            email_message_id=str(email_message.id),
            shipment_id=str(shipment.id),
            intent=intent_result.intent,
            confidence=extraction.confidence,
            next_action="waiting_bids",
            shipment_extracted=True,
            missing_fields=extraction.missing_fields,
            ambiguity_reasons=extraction.ambiguity_reasons,
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
        allow_repeat=policy.allow_repeat_manual_review,
    )
    return WorkflowDecisionResult(
        email_message_id=str(email_message.id),
        shipment_id=str(shipment.id),
        intent=intent_result.intent,
        confidence=extraction.confidence,
        next_action="manual_review",
        shipment_extracted=True,
        missing_fields=extraction.missing_fields,
        ambiguity_reasons=extraction.ambiguity_reasons,
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
    policy: AutomationPolicy,
) -> WorkflowDecisionResult:
    if carrier is None:
        await _log_manual_review(
            session,
            shipment.id,
            "Carrier reply could not be mapped to known carrier",
            intent_result=intent_result,
            allow_repeat=policy.allow_repeat_manual_review,
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
    existing_bid = await session.scalar(
        select(CarrierBid).where(CarrierBid.email_message_id == email_message.id)
    )
    if existing_bid is not None:
        return WorkflowDecisionResult(
            email_message_id=str(email_message.id),
            shipment_id=str(shipment.id),
            intent=intent_result.intent,
            confidence=extraction.confidence,
            next_action="bid_already_processed",
            bid_intaken=True,
            bid_id=str(existing_bid.id),
            bid_amount=existing_bid.amount,
        )
    if extraction.amount is None or extraction.confidence < AUTO_BID_CONFIDENCE or extraction.ambiguity_reasons:
        await _log_event(
            session,
            shipment.id,
            WorkflowEventType.BID_PARSE_FAILED.value,
            shipment.status,
            {
                "carrier_id": str(carrier.id),
                "confidence": extraction.confidence,
                "notes": extraction.notes,
                "ambiguity_reasons": extraction.ambiguity_reasons,
                "source_email_id": str(email_message.id),
            },
        )
        await _log_manual_review(
            session,
            shipment.id,
            (
                f"Ambiguous carrier bid: {', '.join(extraction.ambiguity_reasons)}"
                if extraction.ambiguity_reasons
                else "Carrier bid parsing confidence too low"
            ),
            intent_result=intent_result,
            ambiguity_reasons=extraction.ambiguity_reasons,
            source_email_id=str(email_message.id),
            allow_repeat=policy.allow_repeat_manual_review,
        )
        return WorkflowDecisionResult(
            email_message_id=str(email_message.id),
            shipment_id=str(shipment.id),
            intent=intent_result.intent,
            confidence=extraction.confidence,
            next_action="manual_review",
            ambiguity_reasons=extraction.ambiguity_reasons,
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
        evaluation = await evaluate_shipment_bids(session, shipment.id)
        evaluation_triggered = True
        if policy.auto_quote:
            await send_customer_quote(
                session,
                shipment_id=shipment.id,
                bid_id=evaluation.selected_bid_id,
                dry_run=policy.quote_dry_run,
                custom_message=None,
            )
            quote_auto_sent = not policy.quote_dry_run

    return WorkflowDecisionResult(
        email_message_id=str(email_message.id),
        shipment_id=str(shipment.id),
        intent=intent_result.intent,
        confidence=extraction.confidence,
        next_action="waiting_bids" if not quote_auto_sent else "customer_quote_sent",
        bid_intaken=True,
        bid_id=str(bid.bid.id),
        bid_amount=bid.bid.amount,
        evaluation_triggered=evaluation_triggered,
        quote_auto_sent=quote_auto_sent,
    )


async def _handle_customer_status_request(
    session: AsyncSession,
    *,
    email_message: EmailMessage,
    shipment: Shipment,
    client: Client | None,
    intent_result: IntentResult,
    email_context: dict,
) -> WorkflowDecisionResult:
    if client is None:
        await _log_manual_review(
            session,
            shipment.id,
            "Customer status request could not be mapped to a known client",
            intent_result=intent_result,
            review_type="customer_status_request_review",
            next_action="approve_status_reply",
        )
        return WorkflowDecisionResult(
            email_message_id=str(email_message.id),
            shipment_id=str(shipment.id),
            intent=intent_result.intent,
            confidence=intent_result.confidence,
            next_action="manual_review",
            manual_review_required=True,
        )

    extraction = await extract_status_request(email_context)
    latest_status_reply_event = await session.scalar(
        select(WorkflowEvent)
        .where(
            WorkflowEvent.shipment_id == shipment.id,
            WorkflowEvent.event_type == WorkflowEventType.CUSTOMER_STATUS_SENT.value,
        )
        .order_by(WorkflowEvent.created_at.desc())
    )
    if latest_status_reply_event is not None and (latest_status_reply_event.payload_json or {}).get("dry_run"):
        return WorkflowDecisionResult(
            email_message_id=str(email_message.id),
            shipment_id=str(shipment.id),
            intent=intent_result.intent,
            confidence=extraction.confidence,
            next_action="status_reply_drafted",
            status_lookup_triggered=False,
            status_reply_sent=False,
            manual_review_required=True,
        )
    status_response = await fetch_tms_shipment_status(session, shipment_id=shipment.id)
    reply = await send_customer_status_reply(
        session,
        shipment_id=shipment.id,
        status_payload=status_response.payload,
        dry_run=True,
        custom_message=None,
    )
    await _log_manual_review(
        session,
        shipment.id,
        "Customer status reply requires operator approval",
        intent_result=intent_result,
        review_type="customer_status_request_review",
        next_action="approve_status_reply",
        structured_payload={
            "draft_subject": reply.subject,
            "draft_body": reply.body,
            "latest_status_snapshot": status_response.payload,
            "requested_fields": extraction.requested_fields,
        },
        source_email_id=str(email_message.id),
        allow_repeat=True,
    )
    return WorkflowDecisionResult(
        email_message_id=str(email_message.id),
        shipment_id=str(shipment.id),
        intent=intent_result.intent,
        confidence=extraction.confidence,
        next_action="status_reply_drafted",
        status_lookup_triggered=True,
        status_reply_sent=False,
        manual_review_required=True,
    )


async def _handle_carrier_status_update(
    session: AsyncSession,
    *,
    email_message: EmailMessage,
    shipment: Shipment,
    carrier: Carrier | None,
    intent_result: IntentResult,
    email_context: dict,
    policy: AutomationPolicy,
) -> WorkflowDecisionResult:
    if carrier is None:
        await _log_manual_review(
            session,
            shipment.id,
            "Carrier status update could not be mapped to known carrier",
            intent_result=intent_result,
            review_type="carrier_status_update_review",
            next_action="rerun_tms_update",
            allow_repeat=policy.allow_repeat_manual_review,
        )
        return WorkflowDecisionResult(
            email_message_id=str(email_message.id),
            shipment_id=str(shipment.id),
            intent=intent_result.intent,
            confidence=intent_result.confidence,
            next_action="manual_review",
            manual_review_required=True,
        )

    extraction = await extract_carrier_status_update(email_context)
    if extraction.confidence < AUTO_BID_CONFIDENCE or extraction.ambiguity_reasons:
        await _log_manual_review(
            session,
            shipment.id,
            (
                f"Ambiguous carrier status update: {', '.join(extraction.ambiguity_reasons)}"
                if extraction.ambiguity_reasons
                else "Carrier status update confidence too low"
            ),
            intent_result=intent_result,
            review_type="carrier_status_update_review",
            next_action="rerun_tms_update",
            ambiguity_reasons=extraction.ambiguity_reasons,
            structured_payload={
                "status_text": extraction.status_text,
                "eta_text": extraction.eta_text,
                "location_text": extraction.location_text,
                "notes": extraction.notes,
            },
            source_email_id=str(email_message.id),
            allow_repeat=policy.allow_repeat_manual_review,
        )
        return WorkflowDecisionResult(
            email_message_id=str(email_message.id),
            shipment_id=str(shipment.id),
            intent=intent_result.intent,
            confidence=extraction.confidence,
            next_action="manual_review",
            ambiguity_reasons=extraction.ambiguity_reasons,
            manual_review_required=True,
        )

    status_update = await push_carrier_status_to_tms(
        session,
        shipment_id=shipment.id,
        status_text=extraction.status_text,
        eta_text=extraction.eta_text,
        location_text=extraction.location_text,
        notes=extraction.notes,
    )
    return WorkflowDecisionResult(
        email_message_id=str(email_message.id),
        shipment_id=str(shipment.id),
        intent=intent_result.intent,
        confidence=extraction.confidence,
        next_action="tms_status_updated",
        tms_status_updated=True,
        tms_handoff_status=status_update.status,
    )


def _apply_shipment_extraction(shipment: Shipment, extraction: ShipmentExtractionResult) -> None:
    shipment.status = ShipmentStage.PARSING.value
    shipment.updated_at = datetime.now(timezone.utc)
    shipment.origin = extraction.origin or shipment.origin
    shipment.destination = extraction.destination or shipment.destination
    shipment.pallets = extraction.pallets if extraction.pallets is not None else shipment.pallets
    shipment.weight_lb = extraction.weight_lb if extraction.weight_lb is not None else shipment.weight_lb
    shipment.equipment_type = extraction.equipment_type or shipment.equipment_type
    extraction_ready_at = extraction.ready_at
    extraction_delivery_at = extraction.delivery_at
    pickup_utc, pickup_local, pickup_tz, pickup_off = normalize_pickup_datetime_fields(
        ready_at=(
            extraction_ready_at
            if extraction_ready_at is not None and extraction_ready_at.tzinfo is not None
            else shipment.ready_at
        ),
        ready_at_local=(
            extraction_ready_at
            if extraction_ready_at is not None and extraction_ready_at.tzinfo is None
            else shipment.ready_at_local
        ),
        origin=shipment.origin,
        destination=shipment.destination,
    )
    shipment.ready_at = pickup_utc
    shipment.ready_at_local = pickup_local
    shipment.ready_at_timezone = pickup_tz
    shipment.ready_at_offset_minutes = pickup_off
    delivery_utc, delivery_local, delivery_tz, delivery_off = normalize_delivery_datetime_fields(
        delivery_at=(
            extraction_delivery_at
            if extraction_delivery_at is not None and extraction_delivery_at.tzinfo is not None
            else shipment.delivery_at
        ),
        delivery_at_local=(
            extraction_delivery_at
            if extraction_delivery_at is not None and extraction_delivery_at.tzinfo is None
            else shipment.delivery_at_local
        ),
        origin=shipment.origin,
        destination=shipment.destination,
    )
    shipment.delivery_at = delivery_utc
    shipment.delivery_at_local = delivery_local
    shipment.delivery_at_timezone = delivery_tz
    shipment.delivery_at_offset_minutes = delivery_off
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
    await freight_realtime_hub.publish_shipment_updated(shipment_id=str(shipment.id))


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
    evt = WorkflowEvent(
        shipment_id=shipment_id,
        event_type=event_type,
        stage=stage,
        payload_json=payload,
    )
    session.add(evt)
    await session.commit()
    await freight_realtime_hub.notify_workflow_event(evt)


async def _log_manual_review(
    session: AsyncSession,
    shipment_id: UUID,
    reason: str,
    *,
    intent_result: IntentResult,
    review_type: str | None = None,
    next_action: str = "manual_review",
    ambiguity_reasons: list[str] | None = None,
    structured_payload: dict | None = None,
    source_email_id: str | None = None,
    allow_repeat: bool = False,
) -> None:
    if not allow_repeat and await _has_open_review(session, shipment_id, reason):
        return
    await _log_event(
        session,
        shipment_id,
        WorkflowEventType.MANUAL_REVIEW_REQUIRED.value,
        ShipmentStage.PARSING.value,
        {
            "reason": reason,
            "intent": intent_result.intent,
            "review_type": review_type,
            "confidence": intent_result.confidence,
            "next_action": next_action,
            "ambiguity_reasons": ambiguity_reasons or [],
            "structured_payload": structured_payload or {},
            "source_email_id": source_email_id,
            "status_audit_kind": "status_review_required" if review_type and "status" in review_type else "manual_review_required",
            "manual_review_required": True,
        },
    )


async def _has_open_review(session: AsyncSession, shipment_id: UUID, reason: str) -> bool:
    event = await session.scalar(
        select(WorkflowEvent)
        .where(
            WorkflowEvent.shipment_id == shipment_id,
            WorkflowEvent.event_type == WorkflowEventType.MANUAL_REVIEW_REQUIRED.value,
        )
        .order_by(WorkflowEvent.created_at.desc())
    )
    if event is None:
        return False
    return str((event.payload_json or {}).get("reason", "")) == reason
