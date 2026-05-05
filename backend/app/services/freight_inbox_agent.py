"""Freight-specific inbox orchestrator for email-driven workflows."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.memory.database import Carrier, CarrierBid, Client, EmailMessage, Shipment, WorkflowEvent
from app.schemas import (
    AutomationPolicy,
    BidIntakeRequest,
    CarrierBidExtractionResult,
    FraudRiskLevel,
    FraudReviewType,
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
    deliver_customer_thread_email,
    send_client_acknowledgement,
    send_customer_status_reply,
    send_customer_quote,
)
from app.services.freight_realtime import freight_realtime_hub
from app.services.location_timezone import normalize_delivery_datetime_fields, normalize_pickup_datetime_fields
from app.services.freight_outreach import create_carrier_outreach
from app.services.outlook_organization import organization_outlook_mailbox

CRITICAL_SHIPMENT_FIELDS = {"origin", "destination"}
RECOMMENDED_SHIPMENT_FIELDS = {"pallets", "weight_lb", "equipment_type", "ready_at"}
AUTO_INTENT_CONFIDENCE = 0.6


async def operator_sender_trust_confirmed(
    session: AsyncSession,
    *,
    shipment_id: UUID | None,
    sender_email: str | None,
) -> bool:
    """True when an operator recorded sender trust for this shipment and inbound address."""
    if shipment_id is None or not sender_email:
        return False
    normalized = str(sender_email).strip().lower()
    if not normalized:
        return False
    sender_domain = normalized.split("@", 1)[1] if "@" in normalized else ""
    result = await session.execute(
        select(WorkflowEvent)
        .where(
            WorkflowEvent.shipment_id == shipment_id,
            WorkflowEvent.event_type == WorkflowEventType.SENDER_VERIFIED.value,
        )
        .order_by(WorkflowEvent.created_at.desc())
        .limit(40)
    )
    for event in result.scalars().all():
        payload = dict(event.payload_json or {})
        trust_scope = str(payload.get("trust_scope") or "sender_email")
        trusted_email = str(payload.get("sender_email", "")).strip().lower()
        trusted_domain = str(payload.get("sender_domain", "")).strip().lower().rstrip(".")
        if trust_scope == "sender_domain" and trusted_domain and trusted_domain == sender_domain:
            return True
        if trust_scope == "sender_email" and trusted_email == normalized:
            return True
    return False
AUTO_PARSE_CONFIDENCE = 0.65
AUTO_BID_CONFIDENCE = 0.6
logger = logging.getLogger(__name__)


def _normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


async def _resolve_exact_carrier(
    session: AsyncSession,
    *,
    sender_email: str,
) -> Carrier | None:
    normalized_sender = _normalize_email(sender_email)
    if not normalized_sender:
        return None
    return await session.scalar(
        select(Carrier).where(func.lower(Carrier.email) == normalized_sender)
    )


async def _resolve_client_by_email(
    session: AsyncSession,
    *,
    sender_email: str,
) -> Client | None:
    normalized_sender = _normalize_email(sender_email)
    if not normalized_sender:
        return None
    return await session.scalar(
        select(Client).where(func.lower(Client.email) == normalized_sender)
    )


async def resolve_carrier_for_inbound_thread_reply(
    session: AsyncSession,
    *,
    shipment: Shipment | None,
    email_message: EmailMessage,
) -> tuple[Carrier | None, str, str]:
    sender_email = _normalize_email(email_message.sender)
    if not sender_email:
        return None, "unresolved", "missing_sender_email"

    exact_carrier = await _resolve_exact_carrier(session, sender_email=sender_email)
    if exact_carrier is not None:
        return exact_carrier, "exact_email", "exact_sender_match"

    if shipment is None:
        return None, "unresolved", "shipment_not_linked"

    requested_bids = (
        await session.execute(
            select(CarrierBid, EmailMessage)
            .join(EmailMessage, EmailMessage.id == CarrierBid.email_message_id)
            .where(
                CarrierBid.shipment_id == shipment.id,
                CarrierBid.status.in_(["requested", "drafted"]),
                EmailMessage.direction == "outbound",
            )
            .order_by(EmailMessage.received_at.desc())
        )
    ).all()

    recipient_carrier_ids: list[UUID] = []
    for bid, outbound_message in requested_bids:
        recipients = [_normalize_email(recipient) for recipient in (outbound_message.recipients_json or [])]
        if sender_email in recipients:
            carrier = await session.get(Carrier, bid.carrier_id)
            if carrier is not None:
                return carrier, "thread_outreach_recipient", "matched_outbound_recipient"
        recipient_carrier_ids.append(bid.carrier_id)

    unique_requested_carrier_ids: list[UUID] = list(dict.fromkeys(recipient_carrier_ids))
    if len(unique_requested_carrier_ids) == 1:
        carrier = await session.get(Carrier, unique_requested_carrier_ids[0])
        if carrier is not None:
            return carrier, "single_thread_carrier_inferred", "single_requested_carrier_for_thread"

    return None, "unresolved", "no_carrier_match_from_thread"


def _sender_role_for_inbox_context(
    *,
    shipment: Shipment | None,
    client: Client | None,
    carrier: Carrier | None,
) -> str:
    """Resolve ambiguous identities for workflow intent classification."""
    if (
        shipment is not None
        and shipment.status
        in {
            ShipmentStage.WAITING_CUSTOMER_DETAILS.value,
            ShipmentStage.QUOTED.value,
            ShipmentStage.AWAITING_CONFIRMATION.value,
        }
        and client is not None
    ):
        return "client"
    if carrier is not None:
        return "carrier"
    if client is not None:
        return "client"
    return "unknown"


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
    fraud_payload = dict((email_message.raw_payload_json or {}).get("fraud", {}) or {})
    fraud_level = fraud_payload.get("risk_level")
    fraud_reasons = {str(reason) for reason in list(fraud_payload.get("reasons", []) or [])}
    trust_confirmed = await operator_sender_trust_confirmed(
        session,
        shipment_id=shipment.id if shipment else None,
        sender_email=email_message.sender,
    )
    if fraud_reasons & {"denylisted_sender_email", "denylisted_sender_domain"}:
        trust_confirmed = False
    if not trust_confirmed and (
        fraud_payload.get("verification_required")
        or fraud_level
        in {
            FraudRiskLevel.MEDIUM.value,
            FraudRiskLevel.HIGH.value,
        }
    ):
        if shipment is not None:
            reason = (
                "Probable fraud detected for sender domain verification."
                if fraud_level == FraudRiskLevel.HIGH.value
                else "Sender verification is required before automation continues."
            )
            await _log_manual_review(
                session,
                shipment.id,
                reason,
                intent_result=IntentResult(
                    intent="sender_risk_assessment",
                    confidence=float(fraud_payload.get("score") or 0),
                ),
                review_type=(
                    FraudReviewType.PROBABLE_FRAUD.value
                    if fraud_level == FraudRiskLevel.HIGH.value
                    else FraudReviewType.SENDER_VERIFICATION.value
                ),
                next_action=(
                    "probable_fraud_review"
                    if fraud_level == FraudRiskLevel.HIGH.value
                    else "sender_verification_required"
                ),
                ambiguity_reasons=list(fraud_payload.get("reasons", []) or []),
                structured_payload=fraud_payload,
                source_email_id=str(email_message.id),
                allow_repeat=False,
            )
        return WorkflowDecisionResult(
            email_message_id=str(email_message.id),
            shipment_id=str(shipment.id) if shipment is not None else None,
            intent="sender_risk_assessment",
            confidence=float(fraud_payload.get("score") or 0),
            next_action=(
                "probable_fraud_review"
                if fraud_level == FraudRiskLevel.HIGH.value
                else "sender_verification_required"
            ),
            manual_review_required=True,
        )
    client = await _resolve_client_by_email(session, sender_email=email_message.sender)
    carrier, carrier_resolution_mode, carrier_resolution_reason = await resolve_carrier_for_inbound_thread_reply(
        session,
        shipment=shipment,
        email_message=email_message,
    )
    logger.info(
        "carrier_reply.resolution_attempt provider_message_id=%s thread_id=%s shipment_id=%s quote_token=%s sender_email=%s resolved_carrier_email=%s resolution_mode=%s resolution_reason=%s",
        email_message.provider_message_id,
        email_message.thread_id,
        shipment.id if shipment else None,
        shipment.quote_token if shipment else None,
        email_message.sender,
        carrier.email if carrier else None,
        carrier_resolution_mode,
        carrier_resolution_reason,
    )

    email_context = {
        "sender_email": email_message.sender,
        "sender_role": _sender_role_for_inbox_context(
            shipment=shipment,
            client=client,
            carrier=carrier,
        ),
        "subject": email_message.subject,
        "body_preview": email_message.body_preview,
        "thread_subject": email_message.subject,
        "shipment_status": shipment.status if shipment else "",
        "known_client": client.email if client else "",
        "known_carrier": carrier.email if carrier else "",
        "collecting_carrier_bids": bool(shipment and shipment.status == ShipmentStage.WAITING_BIDS.value),
        "shipment_quote_token": shipment.quote_token if shipment else "",
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
            carrier_resolution_mode=carrier_resolution_mode,
            carrier_resolution_reason=carrier_resolution_reason,
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
            carrier_resolution_mode=carrier_resolution_mode,
            carrier_resolution_reason=carrier_resolution_reason,
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
        if shipment.status == ShipmentStage.BOOKED.value or await _has_real_tms_handoff(session, shipment.id):
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
    organization_id: UUID | None = None,
    system_scope: bool = False,
) -> list[WorkflowDecisionResult]:
    """Evaluate shipments whose bid collection windows are already expired."""
    if organization_id is None and not system_scope:
        raise RuntimeError("organization_id is required unless system_scope=True.")
    policy = policy or AutomationPolicy()
    now = datetime.now(timezone.utc)
    conditions = [Shipment.status.in_([ShipmentStage.WAITING_BIDS.value, ShipmentStage.QUOTED.value])]
    if organization_id is not None:
        conditions.append(Shipment.organization_id == organization_id)
    result = await session.execute(
        select(Shipment)
        .where(*conditions)
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
        if await _has_real_customer_quote_sent(session, shipment.id):
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
    quote_sent = await _has_real_customer_quote_sent(session, shipment.id)
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
    logger.warning(
        "shipment_parse.extracted email_message_id=%s shipment_id=%s origin=%s destination=%s pallets=%s weight_lb=%s equipment_type=%s ready_at=%s delivery_at=%s confidence=%s missing_fields=%s ambiguity_reasons=%s",
        email_message.id,
        shipment.id,
        extraction.origin,
        extraction.destination,
        extraction.pallets,
        extraction.weight_lb,
        extraction.equipment_type,
        extraction.ready_at.isoformat() if extraction.ready_at else None,
        extraction.delivery_at.isoformat() if extraction.delivery_at else None,
        extraction.confidence,
        extraction.missing_fields,
        extraction.ambiguity_reasons,
    )
    _apply_shipment_extraction(shipment, extraction)
    logger.warning(
        "shipment_parse.applied email_message_id=%s shipment_id=%s status=%s origin=%s destination=%s pallets=%s weight_lb=%s equipment_type=%s ready_at=%s ready_at_local=%s ready_at_timezone=%s delivery_at=%s delivery_at_local=%s",
        email_message.id,
        shipment.id,
        shipment.status,
        shipment.origin,
        shipment.destination,
        shipment.pallets,
        shipment.weight_lb,
        shipment.equipment_type,
        shipment.ready_at.isoformat() if shipment.ready_at else None,
        shipment.ready_at_local.isoformat() if shipment.ready_at_local else None,
        shipment.ready_at_timezone,
        shipment.delivery_at.isoformat() if shipment.delivery_at else None,
        shipment.delivery_at_local.isoformat() if shipment.delivery_at_local else None,
    )
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
    logger.warning(
        "shipment_parse.committed email_message_id=%s shipment_id=%s origin=%s destination=%s status=%s",
        email_message.id,
        shipment.id,
        shipment.origin,
        shipment.destination,
        shipment.status,
    )

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
        clarification_reason = (
            "Missing critical shipment fields"
            if critical_missing
            else "Missing recommended shipment fields"
        )
        await _log_event(
            session,
            shipment.id,
            WorkflowEventType.SHIPMENT_PARSE_FAILED.value,
            shipment.status,
            {
                "reason": clarification_reason,
                "missing_fields": extraction.missing_fields,
                "ambiguity_reasons": extraction.ambiguity_reasons,
                "confidence": extraction.confidence,
                "intent": intent_result.intent,
                "next_action": "request_customer_details",
                "manual_review_required": True,
                "source_email_id": str(email_message.id),
            },
        )
        if client is not None:
            await _log_manual_review(
                session,
                shipment.id,
                clarification_reason,
                intent_result=intent_result,
                review_type="customer_clarification_required",
                next_action="request_customer_details",
                structured_payload={
                    "missing_fields": extraction.missing_fields,
                    "critical_missing": critical_missing,
                    "recommended_missing": recommended_missing,
                },
                source_email_id=str(email_message.id),
                allow_repeat=policy.allow_repeat_manual_review,
            )
            manual_review = True
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
            next_action="request_customer_details",
            shipment_extracted=True,
            missing_fields=extraction.missing_fields,
            ambiguity_reasons=extraction.ambiguity_reasons,
            manual_review_required=True,
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
    logger.warning(
        "shipment_clarification_parse.extracted email_message_id=%s shipment_id=%s origin=%s destination=%s pallets=%s weight_lb=%s equipment_type=%s ready_at=%s delivery_at=%s confidence=%s missing_fields=%s ambiguity_reasons=%s",
        email_message.id,
        shipment.id,
        extraction.origin,
        extraction.destination,
        extraction.pallets,
        extraction.weight_lb,
        extraction.equipment_type,
        extraction.ready_at.isoformat() if extraction.ready_at else None,
        extraction.delivery_at.isoformat() if extraction.delivery_at else None,
        extraction.confidence,
        extraction.missing_fields,
        extraction.ambiguity_reasons,
    )
    _apply_shipment_extraction(shipment, extraction)
    logger.warning(
        "shipment_clarification_parse.applied email_message_id=%s shipment_id=%s status=%s origin=%s destination=%s pallets=%s weight_lb=%s equipment_type=%s ready_at=%s ready_at_local=%s ready_at_timezone=%s delivery_at=%s delivery_at_local=%s",
        email_message.id,
        shipment.id,
        shipment.status,
        shipment.origin,
        shipment.destination,
        shipment.pallets,
        shipment.weight_lb,
        shipment.equipment_type,
        shipment.ready_at.isoformat() if shipment.ready_at else None,
        shipment.ready_at_local.isoformat() if shipment.ready_at_local else None,
        shipment.ready_at_timezone,
        shipment.delivery_at.isoformat() if shipment.delivery_at else None,
        shipment.delivery_at_local.isoformat() if shipment.delivery_at_local else None,
    )
    await session.commit()
    logger.warning(
        "shipment_clarification_parse.committed email_message_id=%s shipment_id=%s origin=%s destination=%s status=%s",
        email_message.id,
        shipment.id,
        shipment.origin,
        shipment.destination,
        shipment.status,
    )
    await freight_realtime_hub.publish_shipment_updated(
        organization_id=shipment.organization_id,
        shipment_id=str(shipment.id),
    )
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
    carrier_resolution_mode: str,
    carrier_resolution_reason: str,
    intent_result: IntentResult,
    email_context: dict,
    policy: AutomationPolicy,
) -> WorkflowDecisionResult:
    logger.info(
        "carrier_reply.ingested provider_message_id=%s thread_id=%s shipment_id=%s quote_token=%s sender_email=%s resolved_carrier_email=%s resolution_mode=%s",
        email_message.provider_message_id,
        email_message.thread_id,
        shipment.id,
        shipment.quote_token,
        email_message.sender,
        carrier.email if carrier else None,
        carrier_resolution_mode,
    )
    if carrier is None:
        await _log_manual_review(
            session,
            shipment.id,
            "Unknown carrier sender in RFQ thread",
            intent_result=intent_result,
            review_type="carrier_bid_review",
            structured_payload={
                "sender_email": email_message.sender,
                "carrier_resolution_mode": carrier_resolution_mode,
                "carrier_resolution_reason": carrier_resolution_reason,
                "identity_mismatch": True,
            },
            source_email_id=str(email_message.id),
            allow_repeat=policy.allow_repeat_manual_review,
        )
        logger.warning(
            "carrier_reply.unresolved provider_message_id=%s shipment_id=%s sender_email=%s resolution_mode=%s resolution_reason=%s",
            email_message.provider_message_id,
            shipment.id,
            email_message.sender,
            carrier_resolution_mode,
            carrier_resolution_reason,
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
    logger.info(
        "carrier_reply.bid_extracted provider_message_id=%s shipment_id=%s sender_email=%s resolved_carrier_email=%s resolution_mode=%s amount=%s confidence=%s ambiguity_count=%s",
        email_message.provider_message_id,
        shipment.id,
        email_message.sender,
        carrier.email,
        carrier_resolution_mode,
        extraction.amount,
        extraction.confidence,
        len(extraction.ambiguity_reasons or []),
    )
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
                "sender_email": email_message.sender,
                "resolved_carrier_email": carrier.email,
                "carrier_resolution_mode": carrier_resolution_mode,
                "carrier_resolution_reason": carrier_resolution_reason,
                "identity_mismatch": _normalize_email(email_message.sender) != _normalize_email(carrier.email),
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
                else "Low confidence bid parse"
            ),
            intent_result=intent_result,
            review_type="carrier_bid_review",
            ambiguity_reasons=extraction.ambiguity_reasons,
            structured_payload={
                "sender_email": email_message.sender,
                "resolved_carrier_email": carrier.email,
                "carrier_resolution_mode": carrier_resolution_mode,
                "carrier_resolution_reason": carrier_resolution_reason,
                "identity_mismatch": _normalize_email(email_message.sender) != _normalize_email(carrier.email),
                "amount": extraction.amount,
                "confidence": extraction.confidence,
            },
            source_email_id=str(email_message.id),
            allow_repeat=policy.allow_repeat_manual_review,
        )
        logger.warning(
            "carrier_reply.manual_review provider_message_id=%s shipment_id=%s sender_email=%s resolved_carrier_email=%s resolution_mode=%s amount=%s confidence=%s",
            email_message.provider_message_id,
            shipment.id,
            email_message.sender,
            carrier.email,
            carrier_resolution_mode,
            extraction.amount,
            extraction.confidence,
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
            sender_email=email_message.sender,
            resolved_carrier_email=carrier.email,
            carrier_resolution_mode=carrier_resolution_mode,
            carrier_resolution_reason=carrier_resolution_reason,
            identity_mismatch=_normalize_email(email_message.sender) != _normalize_email(carrier.email),
            create_carrier_if_missing=False,
        ),
    )
    logger.info(
        "carrier_reply.bid_created provider_message_id=%s shipment_id=%s sender_email=%s resolved_carrier_email=%s resolution_mode=%s bid_id=%s amount=%s",
        email_message.provider_message_id,
        shipment.id,
        email_message.sender,
        carrier.email,
        carrier_resolution_mode,
        bid.bid.id,
        bid.bid.amount,
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
        and not await _has_real_customer_quote_sent(session, shipment.id)
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
    carrier_resolution_mode: str,
    carrier_resolution_reason: str,
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
            structured_payload={
                "sender_email": email_message.sender,
                "carrier_resolution_mode": carrier_resolution_mode,
                "carrier_resolution_reason": carrier_resolution_reason,
                "identity_mismatch": True,
            },
            allow_repeat=policy.allow_repeat_manual_review,
        )
        logger.warning(
            "carrier_reply.unresolved provider_message_id=%s shipment_id=%s sender_email=%s resolution_mode=%s resolution_reason=%s branch=carrier_status_update",
            email_message.provider_message_id,
            shipment.id,
            email_message.sender,
            carrier_resolution_mode,
            carrier_resolution_reason,
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
                "sender_email": email_message.sender,
                "resolved_carrier_email": carrier.email,
                "carrier_resolution_mode": carrier_resolution_mode,
                "carrier_resolution_reason": carrier_resolution_reason,
                "identity_mismatch": _normalize_email(email_message.sender) != _normalize_email(carrier.email),
            },
            source_email_id=str(email_message.id),
            allow_repeat=policy.allow_repeat_manual_review,
        )
        logger.warning(
            "carrier_reply.manual_review provider_message_id=%s shipment_id=%s sender_email=%s resolved_carrier_email=%s resolution_mode=%s confidence=%s branch=carrier_status_update",
            email_message.provider_message_id,
            shipment.id,
            email_message.sender,
            carrier.email,
            carrier_resolution_mode,
            extraction.confidence,
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
) -> bool:
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None or shipment.client_id is None or shipment.email_thread_id is None:
        raise RuntimeError("Shipment is not ready for customer clarification")
    if await customer_clarification_already_requested(session, shipment):
        return False
    client = await session.get(Client, shipment.client_id)
    if client is None:
        raise RuntimeError("Client not found for clarification")
    effective_missing_fields = missing_fields or ["shipment details"]
    body = (
        "We need a few more details before we can price this load.\n\n"
        f"Missing fields: {', '.join(effective_missing_fields)}\n\n"
        "Please reply with the missing information and we will continue right away."
    )
    subject = f"Need more details for your quote [{shipment.quote_token or 'Q-UNKNOWN'}]"
    delivery_payload = await deliver_customer_thread_email(
        session,
        shipment=shipment,
        client_email=client.email,
        subject=subject,
        body=body,
        dry_run=False,
    )
    session.add(
        EmailMessage(
            organization_id=shipment.organization_id,
            thread_id=shipment.email_thread_id,
            sender=await organization_outlook_mailbox(session, shipment.organization_id),
            recipients_json=[client.email],
            direction="outbound",
            subject=subject,
            body_preview=body[:1000],
            raw_payload_json={
                "type": "customer_clarification",
                "missing_fields": effective_missing_fields,
                **delivery_payload,
            },
            received_at=datetime.now(timezone.utc),
        )
    )
    shipment.status = ShipmentStage.WAITING_CUSTOMER_DETAILS.value
    shipment.updated_at = datetime.now(timezone.utc)
    session.add(
        WorkflowEvent(
            organization_id=shipment.organization_id,
            shipment_id=shipment.id,
            event_type=WorkflowEventType.CUSTOMER_DETAILS_REQUESTED.value,
            stage=shipment.status,
            payload_json={
                "missing_fields": effective_missing_fields,
                "dry_run": False,
                **delivery_payload,
            },
        )
    )
    await session.commit()
    await freight_realtime_hub.publish_shipment_updated(
        organization_id=shipment.organization_id,
        shipment_id=str(shipment.id),
    )
    return True


async def customer_clarification_already_requested(
    session: AsyncSession,
    shipment: Shipment,
) -> bool:
    if shipment.email_thread_id is None:
        return False
    result = await session.execute(
        select(EmailMessage)
        .where(
            EmailMessage.thread_id == shipment.email_thread_id,
            EmailMessage.direction == "outbound",
        )
        .order_by(EmailMessage.received_at.desc())
    )
    for message in result.scalars().all():
        payload = dict(message.raw_payload_json or {})
        if payload.get("type") == "customer_clarification":
            return True
    return False


async def _has_event(session: AsyncSession, shipment_id: UUID, event_type: str) -> bool:
    event = await session.scalar(
        select(WorkflowEvent).where(
            WorkflowEvent.shipment_id == shipment_id,
            WorkflowEvent.event_type == event_type,
        )
    )
    return event is not None


async def _has_real_customer_quote_sent(session: AsyncSession, shipment_id: UUID) -> bool:
    result = await session.execute(
        select(WorkflowEvent)
        .where(
            WorkflowEvent.shipment_id == shipment_id,
            WorkflowEvent.event_type == WorkflowEventType.CLIENT_QUOTE_SENT.value,
        )
        .order_by(WorkflowEvent.created_at.desc())
    )
    for event in result.scalars().all():
        if not dict(event.payload_json or {}).get("dry_run"):
            return True
    return False


async def _has_real_tms_handoff(session: AsyncSession, shipment_id: UUID) -> bool:
    result = await session.execute(
        select(WorkflowEvent)
        .where(
            WorkflowEvent.shipment_id == shipment_id,
            WorkflowEvent.event_type == WorkflowEventType.TMS_HANDOFF_SENT.value,
        )
        .order_by(WorkflowEvent.created_at.desc())
    )
    for event in result.scalars().all():
        payload = dict(event.payload_json or {})
        if not payload.get("dry_run") and payload.get("status") in {
            "submitted",
            "already_submitted",
            "not_configured",
            "manual_pending",
        }:
            return True
    return False


async def _log_event(
    session: AsyncSession,
    shipment_id: UUID | None,
    event_type: str,
    stage: str,
    payload: dict,
) -> None:
    if shipment_id is None:
        return
    shipment = await session.get(Shipment, shipment_id)
    evt = WorkflowEvent(
        organization_id=shipment.organization_id if shipment is not None else None,
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
    structured_payload = structured_payload or {}
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
            "missing_fields": list(structured_payload.get("missing_fields", []) or []),
            "structured_payload": structured_payload,
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
