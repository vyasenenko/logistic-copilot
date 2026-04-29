"""Freight workflow foundation endpoints."""

from datetime import datetime, timedelta, timezone
import html
import logging
import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.memory.database import (
    Carrier,
    CarrierBid,
    Client,
    EmailMessage,
    EmailThread,
    EmailTriageItem,
    FraudDenylistEntry,
    Shipment,
    WorkflowEvent,
    async_session,
    get_session,
)
from app.schemas import (
    ArchiveReasonCode,
    AutomationPolicy,
    BidIntakeRequest,
    BidIntakeResponse,
    BidRecord,
    BookingExecutionResponse,
    CarrierFollowupRequest,
    CarrierFollowupResponse,
    CarrierOutreachRequest,
    CarrierOutreachResponse,
    CarrierRecord,
    CarrierStatusUpdateRequest,
    CarrierStatusUpdateResponse,
    CarrierUpsertRequest,
    ClientAcknowledgementRequest,
    ClientAcknowledgementResponse,
    ClientRecord,
    ClientUpsertRequest,
    CustomerQuoteRequest,
    CustomerQuoteResponse,
    CustomerStatusReplyRequest,
    CustomerStatusReplyResponse,
    FreightFoundationResponse,
    FreightFinancialShipmentSummary,
    FreightFinancialSummaryResponse,
    FraudDenylistEntryRecord,
    FraudDenylistEntryRequest,
    FraudDenylistEntryUpdateRequest,
    FraudDenylistScope,
    FraudReviewType,
    FraudRiskLevel,
    EmailTriageAction,
    EmailTriageActionRequest,
    EmailTriageClassification,
    EmailTriageRecord,
    OutlookIngestRequest,
    OutlookIngestResult,
    OutlookSyncRequest,
    OutlookSyncResponse,
    OutlookWebhookStatusResponse,
    OutlookWebhookRequest,
    OutlookWebhookResponse,
    OperatorAction,
    FreightOverviewResponse,
    MarginPolicy,
    NotificationFeedResponse,
    ShipmentEvaluationResponse,
    ShipmentRecord,
    ShipmentThreadMessageRecord,
    ShipmentThreadResponse,
    ShipmentUpsertRequest,
    ShipmentStage,
    ReviewQueueItem,
    StatusQueueAction,
    StatusQueueActionRequest,
    StatusQueueActionResponse,
    StatusQueueItem,
    ShipmentArchiveRequest,
    ShipmentOperatorActionRequest,
    ShipmentOperatorActionResponse,
    SenderIdentityRole,
    SenderTrustScope,
    ShipmentDocumentRecord,
    ShipmentMagicField,
    ShipmentMagicFillRequest,
    ShipmentMagicFillResponse,
    TmsHandoffRequest,
    TmsHandoffResponse,
    TmsStatusIngestRequest,
    TmsStatusIngestResponse,
    WorkflowEventRecord,
    WorkflowDecisionResult,
    WorkflowEventType,
)
from app.services.freight_execution import (
    build_document_health,
    build_document_context,
    collect_shipment_attachments,
    confirm_booking_and_handoff,
    evaluate_shipment_bids,
    fetch_tms_shipment_status,
    handoff_to_tms,
    intake_bid,
    preview_or_push_carrier_status_update,
    push_carrier_status_to_tms,
    send_client_acknowledgement,
    send_customer_status_reply,
    send_customer_quote,
    summarize_booking_documents,
)
from app.services.email_correlation import build_correlation_signals, generate_quote_reference
from app.services.email_fraud import (
    apply_operator_sender_trust_to_fraud_projection,
    extract_sender_domain,
    normalize_sender_email,
)
from app.services.freight_inbox_agent import (
    customer_clarification_already_requested,
    continue_phase1_workflow,
    evaluate_expired_quote_windows,
    run_freight_inbox_orchestrator,
    send_customer_clarification,
)
from app.services.freight_ai import (
    extract_carrier_status_update,
    extract_shipment_details,
    extract_shipment_field_from_thread,
)
from app.services.freight_realtime import freight_realtime_hub
from app.services.location_timezone import (
    format_route_datetime_display,
    normalize_delivery_datetime_fields,
    normalize_pickup_datetime_fields,
)
from app.services.workflow_event_codec import workflow_event_to_record
from app.services.freight_outreach import create_carrier_outreach, send_carrier_followup
from app.services.mailbox_sync import ingest_outlook_message
from app.services.outlook import OutlookGraphClient
from app.services.outlook_mail_actions import (
    add_email_message_categories,
    mark_email_message_read_after_ai_success,
    move_shipment_thread_messages_to_archive,
    outlook_categories_for_ai_decision,
    outlook_categories_for_email_triage,
    outlook_categories_for_fraud_assessment,
)
from app.services.freight_read import build_freight_overview, is_status_stale as _is_status_stale, list_notification_feed

router = APIRouter()
logger = logging.getLogger(__name__)


def _parse_graph_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _outlook_webhook_status_response(
    *,
    outlook: OutlookGraphClient,
    subscriptions: list[dict],
    subscription_action: str | None = None,
) -> OutlookWebhookStatusResponse:
    now = datetime.now(timezone.utc)
    expected_url = settings.microsoft_webhook_notification_url or None
    expected_resource = settings.microsoft_webhook_effective_resource or None
    expected_change_type = settings.microsoft_webhook_change_type or None
    missing_fields = outlook.missing_settings()
    if not expected_url:
        missing_fields.append("microsoft_webhook_public_base_url")
    if not expected_resource:
        missing_fields.append("microsoft_webhook_resource")

    if missing_fields:
        return OutlookWebhookStatusResponse(
            configured=False,
            status="missing_configuration",
            missing_fields=sorted(set(missing_fields)),
            expected_notification_url=expected_url,
            expected_resource=expected_resource,
            expected_change_type=expected_change_type,
            total_subscriptions=len(subscriptions),
            last_checked_at=now.isoformat().replace("+00:00", "Z"),
        )

    matching = [
        item
        for item in subscriptions
        if item.get("notificationUrl") == expected_url
        and item.get("resource") == expected_resource
        and item.get("changeType") == expected_change_type
    ]
    active_matching = [
        item
        for item in matching
        if (_parse_graph_datetime(str(item.get("expirationDateTime") or "")) or datetime.min.replace(tzinfo=timezone.utc)) > now
    ]
    primary = active_matching[0] if active_matching else (matching[0] if matching else None)
    expires_at = str(primary.get("expirationDateTime")) if primary and primary.get("expirationDateTime") else None
    expires = _parse_graph_datetime(expires_at)
    renew_before = now + timedelta(minutes=max(15, settings.microsoft_webhook_renewal_buffer_minutes))

    status = "not_installed"
    if active_matching:
        status = "expiring_soon" if expires and expires <= renew_before else "active"
    elif matching:
        status = "expired"

    return OutlookWebhookStatusResponse(
        configured=True,
        status=status,
        expected_notification_url=expected_url,
        expected_resource=expected_resource,
        expected_change_type=expected_change_type,
        subscription_id=str(primary.get("id")) if primary and primary.get("id") else None,
        subscription_action=subscription_action,
        expires_at=expires_at,
        matching_count=len(matching),
        active_matching_count=len(active_matching),
        total_subscriptions=len(subscriptions),
        last_checked_at=now.isoformat().replace("+00:00", "Z"),
    )


def _shipment_matches_month_filter(
    shipment: Shipment,
    *,
    month: str | None,
) -> bool:
    if not month:
        return True
    reference = shipment.created_at
    if reference is None:
        return False
    return reference.strftime("%Y-%m") == month


async def _serialize_shipment_detail(session: AsyncSession, shipment: Shipment) -> ShipmentRecord:
    ai_payloads = await _latest_ai_payloads(session, [shipment.id])
    fraud_payloads = await _merged_fraud_projections(session, [shipment.id])
    booking_payloads = await _latest_booking_payloads(session, [shipment.id])
    status_payloads = await _latest_status_payloads(session, [shipment.id])
    status_review_payloads = await _latest_status_review_payloads(session, [shipment.id])
    tms_identity_payloads = await _latest_tms_identity_payloads(session, [shipment.id])
    status_workflow_payloads = await _status_workflow_payloads(session, [shipment.id])
    document_action_payloads = await _latest_document_action_payloads(session, [shipment.id])
    clarification_flags = await _customer_clarification_requested_flags(session, [shipment])
    attachment_counts = await _attachment_counts(session, [shipment])
    document_summaries = await _document_booking_summaries(session, [shipment], document_action_payloads)
    now = datetime.now(timezone.utc)
    status_stale = _is_status_stale(
        shipment_status=shipment.status,
        last_status_event_at=(status_payloads.get(shipment.id) or {}).get("last_status_event_at"),
        now=now,
    )
    return _serialize_shipment(
        shipment,
        {
            **(ai_payloads.get(shipment.id) or {}),
            **(fraud_payloads.get(shipment.id) or {}),
            **(booking_payloads.get(shipment.id) or {}),
            **(status_payloads.get(shipment.id) or {}),
            **(status_review_payloads.get(shipment.id) or {}),
            **(tms_identity_payloads.get(shipment.id) or {}),
            **(status_workflow_payloads.get(shipment.id) or {}),
            "attachment_count": attachment_counts.get(shipment.id, 0),
            "document_summary": document_summaries.get(shipment.id, {}).get("document_summary", {}),
            "document_enrichment": document_summaries.get(shipment.id, {}).get("document_enrichment", {}),
            "document_health_status": document_summaries.get(shipment.id, {}).get("document_health_status"),
            "ocr_pending_count": document_summaries.get(shipment.id, {}).get("ocr_pending_count", 0),
            "document_conflict_count": document_summaries.get(shipment.id, {}).get("document_conflict_count", 0),
            "missing_document_types": document_summaries.get(shipment.id, {}).get("missing_document_types", []),
            "booking_review_warning": document_summaries.get(shipment.id, {}).get("booking_review_warning"),
            "booking_review_required": document_summaries.get(shipment.id, {}).get("review_required", False),
            "status_stale": status_stale,
            "status_sync_health": _status_sync_health(
                status_stale=status_stale,
                status_review_required=bool((status_review_payloads.get(shipment.id) or {}).get("status_review_required", False)),
                status_workflow_state=(status_workflow_payloads.get(shipment.id) or {}).get("status_workflow_state"),
            ),
            "status_sla_hours": settings.status_sla_hours_default,
            "customer_clarification_requested": clarification_flags.get(shipment.id, False),
        },
    )


def _clean_message_excerpt(value: str | None) -> str:
    if not value:
        return ""
    cleaned = html.unescape(str(value))
    cleaned = re.sub(r"<br\s*/?>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"</p\s*>", "\n\n", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\r\n?", "\n", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


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
    payload = dict(message.raw_payload_json or {})
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
        dry_run=bool(payload.get("dry_run", False)),
        message_type=payload.get("type"),
    )


def _parse_magic_local_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip().strip('"').strip("'")
    if not normalized:
        return None
    if normalized.startswith("```"):
        normalized = re.sub(r"^```[a-zA-Z]*\s*", "", normalized)
        normalized = re.sub(r"\s*```$", "", normalized).strip()
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.replace(tzinfo=None)
    return parsed


async def _magic_fill_ready_fallback_from_full_extraction(
    *,
    shipment: Shipment,
    client: Client,
    customer_messages: list[EmailMessage],
    all_messages: list[EmailMessage],
) -> datetime | None:
    """When single-field extraction does not yield a parseable pickup time, reuse full shipment extraction."""
    last = customer_messages[-1]
    body = _message_display_body(last) or (last.body_preview or "")
    email_context = {
        "sender_email": (last.sender or ""),
        "sender_role": "customer",
        "subject": last.subject or "",
        "body_preview": body,
        "body": body,
        "thread_subject": (all_messages[-1].subject if all_messages else "") or "",
        "shipment_status": shipment.status,
        "known_client": client.email,
        "known_carrier": "",
    }
    full_ext = await extract_shipment_details(email_context)
    if full_ext.ready_at is None:
        return None
    origin = shipment.origin or full_ext.origin
    destination = shipment.destination or full_ext.destination
    _, pickup_local, _, _ = normalize_pickup_datetime_fields(
        ready_at=full_ext.ready_at if full_ext.ready_at.tzinfo is not None else None,
        ready_at_local=full_ext.ready_at if full_ext.ready_at.tzinfo is None else None,
        origin=origin,
        destination=destination,
    )
    return pickup_local


def _message_touches_email(message: EmailMessage, email: str) -> bool:
    email_lc = email.strip().lower()
    if not email_lc:
        return False
    if (message.sender or "").strip().lower() == email_lc:
        return True
    recipients = [str(recipient).strip().lower() for recipient in (message.recipients_json or [])]
    return email_lc in recipients


def _build_magic_thread_transcript(messages: list[EmailMessage]) -> str:
    lines: list[str] = []
    for message in messages:
        display_body = _message_display_body(message) or (message.body_preview or "")
        direction = (message.direction or "unknown").upper()
        timestamp = message.received_at.isoformat() if message.received_at else ""
        recipients = ", ".join(message.recipients_json or [])
        lines.extend(
            [
                f"[{direction}] {timestamp}",
                f"From: {message.sender}",
                f"To: {recipients}",
                f"Subject: {message.subject}",
                display_body.strip(),
                "",
            ]
        )
    return "\n".join(lines).strip()


def _apply_decision(result, decision: WorkflowDecisionResult) -> None:
    result.intent = decision.intent
    result.confidence = decision.confidence
    result.shipment_extracted = decision.shipment_extracted
    result.missing_fields = decision.missing_fields
    result.ambiguity_reasons = decision.ambiguity_reasons
    result.manual_review_required = decision.manual_review_required
    result.next_action = decision.next_action
    result.acknowledgement_drafted = decision.acknowledgement_drafted
    result.acknowledgement_subject = decision.acknowledgement_subject
    result.outreach_drafted = decision.outreach_drafted
    result.outreach_subject = decision.outreach_subject
    result.outreach_targeted = decision.outreach_targeted
    result.bid_intaken = decision.bid_intaken
    result.bid_id = decision.bid_id
    result.bid_amount = decision.bid_amount
    result.evaluation_triggered = decision.evaluation_triggered
    result.quote_auto_sent = decision.quote_auto_sent
    result.booking_triggered = decision.booking_triggered
    result.booking_confirmation_sent = decision.booking_confirmation_sent
    result.tms_handoff_status = decision.tms_handoff_status
    result.status_lookup_triggered = decision.status_lookup_triggered
    result.status_reply_sent = decision.status_reply_sent
    result.tms_status_updated = decision.tms_status_updated


def _decision_should_mark_email_read(decision: WorkflowDecisionResult) -> bool:
    if decision.manual_review_required or decision.next_action == "manual_review":
        return False
    if decision.shipment_extracted and decision.confidence >= 0.7:
        return True
    return bool(
        decision.bid_intaken
        or decision.evaluation_triggered
        or decision.quote_auto_sent
        or decision.booking_triggered
        or decision.booking_confirmation_sent
        or decision.status_lookup_triggered
        or decision.status_reply_sent
        or decision.tms_status_updated
    )


async def _has_open_review_for_reason(
    session: AsyncSession,
    *,
    shipment_id: str,
    reason: str,
    source_email_id: str | None,
) -> bool:
    result = await session.execute(
        select(WorkflowEvent)
        .where(
            WorkflowEvent.shipment_id == UUID(shipment_id),
            WorkflowEvent.event_type == WorkflowEventType.MANUAL_REVIEW_REQUIRED.value,
        )
        .order_by(WorkflowEvent.created_at.desc())
    )
    for event in result.scalars().all():
        payload = dict(event.payload_json or {})
        if str(payload.get("reason") or "") != reason:
            continue
        if source_email_id is not None and payload.get("source_email_id") not in {None, source_email_id}:
            continue
        return True
    return False


async def _create_sender_review_event(
    session: AsyncSession,
    *,
    result: OutlookIngestResult,
) -> None:
    if not result.shipment_id:
        return
    fraud_level = str(result.fraud_risk_level or "")
    review_type = (
        FraudReviewType.PROBABLE_FRAUD.value
        if fraud_level == FraudRiskLevel.HIGH.value
        else FraudReviewType.SENDER_VERIFICATION.value
    )
    reason = (
        "Probable fraud detected for sender domain verification."
        if review_type == FraudReviewType.PROBABLE_FRAUD.value
        else "Sender verification is required before automation continues."
    )
    if await _has_open_review_for_reason(
        session,
        shipment_id=result.shipment_id,
        reason=reason,
        source_email_id=result.email_message_id,
    ):
        return
    event = WorkflowEvent(
        shipment_id=UUID(result.shipment_id),
        event_type=WorkflowEventType.MANUAL_REVIEW_REQUIRED.value,
        stage=ShipmentStage.PARSING.value,
        payload_json={
            "reason": reason,
            "intent": "sender_risk_assessment",
            "review_type": review_type,
            "confidence": result.fraud_score or 0,
            "next_action": "probable_fraud_review"
            if review_type == FraudReviewType.PROBABLE_FRAUD.value
            else "sender_verification_required",
            "ambiguity_reasons": list(result.fraud_risk_reasons or []),
            "structured_payload": {
                "sender_email": result.sender_email,
                "sender_domain": result.sender_domain,
                "fraud_risk_level": result.fraud_risk_level,
                "fraud_risk_reasons": list(result.fraud_risk_reasons or []),
                "sender_known": result.sender_known,
                "sender_verification_required": result.sender_verification_required,
            },
            "source_email_id": result.email_message_id,
            "manual_review_required": True,
        },
    )
    session.add(event)
    await session.commit()
    await freight_realtime_hub.notify_workflow_event(event)


async def _apply_sender_risk_gate(
    session: AsyncSession,
    *,
    result: OutlookIngestResult,
) -> None:
    fraud_level = str(result.fraud_risk_level or "")
    if not (
        result.sender_verification_required
        or fraud_level in {FraudRiskLevel.MEDIUM.value, FraudRiskLevel.HIGH.value}
    ):
        return

    result.manual_review_required = True
    result.next_action = (
        "probable_fraud_review"
        if fraud_level == FraudRiskLevel.HIGH.value
        else "sender_verification_required"
    )
    result.intent = result.intent or "sender_risk_assessment"
    result.confidence = result.confidence if result.confidence is not None else result.fraud_score
    await _create_sender_review_event(session, result=result)

    categories = outlook_categories_for_fraud_assessment(
        sender_verification_required=result.sender_verification_required,
        fraud_risk_level=fraud_level or None,
    )
    if categories:
        await add_email_message_categories(
            session,
            email_message_id=result.email_message_id,
            shipment_id=result.shipment_id,
            categories=categories,
            reason=f"fraud_gate:{result.fraud_risk_level or 'verification'}:{result.next_action}",
        )


def _build_automation_policy(
    *,
    auto_acknowledgement: bool,
    acknowledgement_dry_run: bool,
    auto_outreach: bool,
    outreach_dry_run: bool,
    auto_quote: bool,
    quote_dry_run: bool,
    auto_book: bool,
    booking_dry_run: bool,
) -> AutomationPolicy:
    return AutomationPolicy(
        auto_acknowledgement=auto_acknowledgement,
        acknowledgement_dry_run=acknowledgement_dry_run,
        auto_outreach=auto_outreach,
        outreach_dry_run=outreach_dry_run,
        auto_quote=auto_quote,
        quote_dry_run=quote_dry_run,
        auto_book=auto_book,
        booking_dry_run=booking_dry_run,
        allow_repeat_manual_review=False,
    )


async def _process_outlook_mailbox_message(
    session: AsyncSession,
    *,
    mailbox_message,
    policy: AutomationPolicy,
    create_client_if_missing: bool = True,
) -> OutlookIngestResult | None:
    result = await ingest_outlook_message(
        session,
        mailbox_message,
        create_client_if_missing=create_client_if_missing,
    )
    if result is None:
        return None

    if result.shipment_creation_skipped or result.suppressed:
        fraud_level = str(result.fraud_risk_level or "")
        classification = (
            result.triage_classification.value
            if hasattr(result.triage_classification, "value")
            else result.triage_classification
        )
        if classification == "fraud_or_phishing":
            result.next_action = "fraud_triage"
        elif classification == "noise_or_unhandled":
            result.next_action = "triage_archived"
        elif classification == "needs_operator_triage":
            result.next_action = "operator_triage"
            result.manual_review_required = True
        else:
            result.next_action = "fraud_suppressed" if fraud_level == FraudRiskLevel.HIGH.value else "suppressed"
        categories = outlook_categories_for_fraud_assessment(
            sender_verification_required=result.sender_verification_required,
            fraud_risk_level=fraud_level or None,
        )
        categories = list(dict.fromkeys(categories + outlook_categories_for_email_triage(classification)))
        if categories and result.email_message_id:
            await add_email_message_categories(
                session,
                email_message_id=result.email_message_id,
                shipment_id=result.shipment_id or None,
                categories=categories,
                reason=f"suppressed:{result.next_action}",
            )
        if result.next_action == "fraud_suppressed" and result.shipment_id:
            shipment = await session.get(Shipment, UUID(result.shipment_id))
            if shipment is not None:
                await move_shipment_thread_messages_to_archive(
                    session,
                    shipment=shipment,
                    reason=result.suppression_reason or "fraud denylist",
                )
        return result

    if result.sender_verification_required or str(result.fraud_risk_level or "") in {
        FraudRiskLevel.MEDIUM.value,
        FraudRiskLevel.HIGH.value,
    }:
        await _apply_sender_risk_gate(session, result=result)
        return result

    if result.created_message:
        try:
            decision = await run_freight_inbox_orchestrator(
                session,
                email_message_id=result.email_message_id,
                policy=policy,
            )
            _apply_decision(result, decision)
            categories = outlook_categories_for_ai_decision(
                intent=decision.intent,
                manual_review_required=decision.manual_review_required,
                bid_intaken=decision.bid_intaken,
                status_lookup_triggered=decision.status_lookup_triggered,
                status_reply_sent=decision.status_reply_sent,
                tms_status_updated=decision.tms_status_updated,
            )
            if categories:
                await add_email_message_categories(
                    session,
                    email_message_id=result.email_message_id,
                    shipment_id=result.shipment_id,
                    categories=categories,
                    reason=f"ai_decision:{decision.intent}:{decision.next_action}",
                )
            if _decision_should_mark_email_read(decision):
                await mark_email_message_read_after_ai_success(
                    session,
                    email_message_id=result.email_message_id,
                    shipment_id=result.shipment_id,
                    reason=f"ai_processed:{decision.intent}:{decision.next_action}",
                )
        except Exception:
            logger.exception(
                "freight_inbox_orchestrator.failed email_message_id=%s shipment_id=%s",
                result.email_message_id,
                result.shipment_id,
            )
            result.manual_review_required = True
            result.next_action = "manual_review"
            result.intent = "orchestrator_error"
            result.confidence = 0.0
            result.missing_fields = []
            await add_email_message_categories(
                session,
                email_message_id=result.email_message_id,
                shipment_id=result.shipment_id,
                categories=outlook_categories_for_ai_decision(
                    intent="exception_or_issue",
                    manual_review_required=True,
                ),
                reason="orchestrator_error",
            )
    else:
        result.next_action = "already_ingested"

    return result


def _default_outlook_event_policy() -> AutomationPolicy:
    return _build_automation_policy(
        auto_acknowledgement=True,
        acknowledgement_dry_run=False,
        auto_outreach=True,
        outreach_dry_run=False,
        auto_quote=True,
        quote_dry_run=False,
        auto_book=True,
        booking_dry_run=False,
    )


async def _latest_inbound_message_for_shipment(
    session: AsyncSession,
    shipment: Shipment,
    *,
    sender: str | None = None,
) -> EmailMessage | None:
    if shipment.email_thread_id is None:
        return None
    result = await session.execute(
        select(EmailMessage)
        .where(
            EmailMessage.thread_id == shipment.email_thread_id,
            EmailMessage.direction == "inbound",
        )
        .order_by(EmailMessage.received_at.desc())
    )
    for message in result.scalars().all():
        if sender is None or message.sender == sender:
            return message
    return None


async def _latest_carrier_message_for_shipment(
    session: AsyncSession,
    shipment: Shipment,
) -> EmailMessage | None:
    if shipment.email_thread_id is None:
        return None
    result = await session.execute(
        select(EmailMessage)
        .where(
            EmailMessage.thread_id == shipment.email_thread_id,
            EmailMessage.direction == "inbound",
        )
        .order_by(EmailMessage.received_at.desc())
    )
    for message in result.scalars().all():
        carrier = await session.scalar(select(Carrier).where(Carrier.email == message.sender))
        if carrier is not None:
            return message
    return None


def _serialize_client(client: Client) -> ClientRecord:
    return ClientRecord(
        id=str(client.id),
        name=client.name,
        email=client.email,
        is_active=client.is_active,
        default_margin_percent=client.default_margin_percent,
        default_margin_floor=client.default_margin_floor,
        created_at=client.created_at,
        updated_at=client.updated_at,
    )


def _serialize_carrier(carrier: Carrier) -> CarrierRecord:
    return CarrierRecord(
        id=str(carrier.id),
        name=carrier.name,
        email=carrier.email,
        rating=carrier.rating,
        is_active=carrier.is_active,
        regions=list(carrier.regions_json or []),
        equipment=list(carrier.equipment_json or []),
        metadata=dict(carrier.metadata_json or {}),
        created_at=carrier.created_at,
        updated_at=carrier.updated_at,
    )


def _serialize_fraud_denylist_entry(entry: FraudDenylistEntry) -> FraudDenylistEntryRecord:
    return FraudDenylistEntryRecord(
        id=str(entry.id),
        scope=FraudDenylistScope(entry.scope),
        value=entry.value,
        reason=entry.reason,
        source_shipment_id=str(entry.source_shipment_id) if entry.source_shipment_id else None,
        is_active=entry.is_active,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


def _normalize_fraud_denylist_value(scope: FraudDenylistScope, value: str) -> str:
    return (
        extract_sender_domain(value)
        if scope == FraudDenylistScope.SENDER_DOMAIN and "@" in value
        else str(value or "").strip().lower().rstrip(".")
    )


def _serialize_shipment(shipment: Shipment, ai_payload: dict | None = None) -> ShipmentRecord:
    ai_payload = ai_payload or {}
    ready_at, ready_at_local, ready_timezone_name, ready_offset = normalize_pickup_datetime_fields(
        ready_at=shipment.ready_at,
        ready_at_local=shipment.ready_at_local,
        origin=shipment.origin,
        destination=shipment.destination,
    )
    delivery_at, delivery_at_local, delivery_timezone_name, delivery_offset = normalize_delivery_datetime_fields(
        delivery_at=shipment.delivery_at,
        delivery_at_local=shipment.delivery_at_local,
        origin=shipment.origin,
        destination=shipment.destination,
    )
    ai_missing_fields = _shipment_current_missing_fields(
        shipment,
        ready_at=ready_at,
        ready_at_local=ready_at_local,
    )
    ai_ambiguity_reasons = list(ai_payload.get("ambiguity_reasons", []) or [])
    manual_review_required = bool(ai_payload.get("manual_review_required", False))
    sender_verification_required = bool(ai_payload.get("sender_verification_required", False))
    fraud_risk_level = ai_payload.get("fraud_risk_level")
    fraud_risk_reasons = list(ai_payload.get("fraud_risk_reasons", []) or [])
    booking_review_required = bool(ai_payload.get("booking_review_required", False))
    status_review_required = bool(ai_payload.get("status_review_required", False))
    status_stale = bool(ai_payload.get("status_stale", False))
    board_stage = _board_stage_from_status(shipment.status)
    attention_state, attention_reason, attention_level = _derive_attention_projection(
        manual_review_required=manual_review_required,
        sender_verification_required=sender_verification_required,
        fraud_risk_level=fraud_risk_level,
        fraud_risk_reasons=fraud_risk_reasons,
        ai_missing_fields=ai_missing_fields,
        ai_ambiguity_reasons=ai_ambiguity_reasons,
        status_review_required=status_review_required,
        booking_review_required=booking_review_required,
        status_stale=status_stale,
    )
    has_active_review = attention_state != "none"
    return ShipmentRecord(
        id=str(shipment.id),
        client_id=str(shipment.client_id) if shipment.client_id else None,
        email_thread_id=str(shipment.email_thread_id) if shipment.email_thread_id else None,
        status=shipment.status,
        quote_token=shipment.quote_token,
        origin=shipment.origin,
        destination=shipment.destination,
        pallets=shipment.pallets,
        weight_lb=shipment.weight_lb,
        equipment_type=shipment.equipment_type,
        ready_at=ready_at,
        ready_at_local=ready_at_local,
        ready_at_display=format_route_datetime_display(ready_at_local, ready_timezone_name) if ready_at_local else None,
        ready_at_timezone=ready_timezone_name,
        ready_at_offset_minutes=ready_offset,
        delivery_at=delivery_at,
        delivery_at_local=delivery_at_local,
        delivery_at_display=format_route_datetime_display(delivery_at_local, delivery_timezone_name) if delivery_at_local else None,
        delivery_at_timezone=delivery_timezone_name,
        delivery_at_offset_minutes=delivery_offset,
        margin_policy=dict(shipment.margin_policy_json or {}),
        notes=shipment.notes,
        ai_intent=ai_payload.get("intent"),
        ai_confidence=ai_payload.get("confidence"),
        ai_missing_fields=ai_missing_fields,
        ai_ambiguity_reasons=ai_ambiguity_reasons,
        ai_next_action=ai_payload.get("next_action"),
        customer_clarification_requested=bool(ai_payload.get("customer_clarification_requested", False)),
        booking_state=ai_payload.get("booking_state"),
        booking_error=ai_payload.get("booking_error"),
        tms_handoff_status=ai_payload.get("tms_handoff_status"),
        attachment_count=int(ai_payload.get("attachment_count", 0) or 0),
        document_summary=dict(ai_payload.get("document_summary", {}) or {}),
        document_enrichment=dict(ai_payload.get("document_enrichment", {}) or {}),
        document_health_status=ai_payload.get("document_health_status"),
        ocr_pending_count=int(ai_payload.get("ocr_pending_count", 0) or 0),
        document_conflict_count=int(ai_payload.get("document_conflict_count", 0) or 0),
        missing_document_types=list(ai_payload.get("missing_document_types", []) or []),
        booking_review_warning=ai_payload.get("booking_review_warning"),
        booking_review_required=bool(ai_payload.get("booking_review_required", False)),
        last_known_status=ai_payload.get("last_known_status"),
        last_known_eta=ai_payload.get("last_known_eta"),
        last_known_location=ai_payload.get("last_known_location"),
        last_status_source=ai_payload.get("last_status_source"),
        last_status_event_at=ai_payload.get("last_status_event_at"),
        tms_load_id=ai_payload.get("tms_load_id"),
        tms_system=ai_payload.get("tms_system"),
        status_workflow_state=ai_payload.get("status_workflow_state"),
        status_sync_health=ai_payload.get("status_sync_health"),
        status_review_required=status_review_required,
        status_stale=status_stale,
        status_sla_hours=ai_payload.get("status_sla_hours"),
        manual_review_required=manual_review_required,
        sender_verification_required=sender_verification_required,
        fraud_risk_level=fraud_risk_level,
        fraud_risk_reasons=fraud_risk_reasons,
        fraud_score=ai_payload.get("fraud_score"),
        sender_known=bool(ai_payload.get("sender_known", False)),
        sender_email=ai_payload.get("sender_email"),
        sender_domain=ai_payload.get("sender_domain"),
        sender_verified_at=ai_payload.get("sender_verified_at"),
        sender_verified_for_email=ai_payload.get("sender_verified_for_email"),
        sender_verified_for_domain=ai_payload.get("sender_verified_for_domain"),
        sender_verified_role=ai_payload.get("sender_verified_role"),
        sender_verified_scope=ai_payload.get("sender_verified_scope"),
        board_stage=board_stage,
        attention_state=attention_state,
        attention_reason=attention_reason,
        attention_level=attention_level,
        has_active_review=has_active_review,
        has_active_status_review=status_review_required,
        has_active_booking_warning=booking_review_required,
        next_step_label=_shipment_next_step_label(
            next_action=ai_payload.get("next_action"),
            status_workflow_state=ai_payload.get("status_workflow_state"),
            booking_state=ai_payload.get("booking_state"),
            status=shipment.status,
        ),
        is_archived=bool(getattr(shipment, "is_archived", False)),
        archive_reason_code=getattr(shipment, "archive_reason_code", None)
        or (ArchiveReasonCode.OTHER.value if bool(getattr(shipment, "is_archived", False)) else None),
        archive_reason_note=getattr(shipment, "archive_reason_note", None) or getattr(shipment, "archived_reason", None),
        archived_reason=getattr(shipment, "archived_reason", None),
        archived_at=getattr(shipment, "archived_at", None),
        created_at=shipment.created_at,
        updated_at=shipment.updated_at,
    )


def _shipment_board_sort_key(record: ShipmentRecord) -> tuple[int, float, float]:
    needs_attention = record.attention_state != "none" or record.has_active_review
    updated_at = record.updated_at or record.created_at
    created_at = record.created_at
    updated_ts = updated_at.timestamp() if updated_at else float("-inf")
    created_ts = created_at.timestamp() if created_at else float("-inf")
    return (0 if needs_attention else 1, -updated_ts, -created_ts)


def _board_stage_from_status(status: str | None) -> str:
    if status in {
        ShipmentStage.RECEIVED.value,
        ShipmentStage.PARSING.value,
        ShipmentStage.WAITING_CUSTOMER_DETAILS.value,
        ShipmentStage.CLIENT_ACKNOWLEDGED.value,
    }:
        return "parsing"
    if status in {
        ShipmentStage.OUTREACHING.value,
        ShipmentStage.WAITING_BIDS.value,
        ShipmentStage.EVALUATING.value,
    }:
        return "waiting_bids"
    if status in {
        ShipmentStage.QUOTED.value,
        ShipmentStage.AWAITING_CONFIRMATION.value,
    }:
        return "quoted"
    if status in {
        ShipmentStage.EXPIRED.value,
        ShipmentStage.DECLINED.value,
    }:
        return "closed"
    return "booked"


def _humanize_token(value: str | None) -> str | None:
    if not value:
        return None
    return str(value).replace("_", " ").strip()


def _shipment_next_step_label(
    *,
    next_action: str | None,
    status_workflow_state: str | None,
    booking_state: str | None,
    status: str | None,
) -> str | None:
    for candidate in (next_action, status_workflow_state, booking_state, status):
        label = _humanize_token(candidate)
        if label:
            return label
    return None


def _shipment_current_missing_fields(
    shipment: Shipment,
    *,
    ready_at: datetime | None,
    ready_at_local: datetime | None,
) -> list[str]:
    missing_fields: list[str] = []
    if not (shipment.origin or "").strip():
        missing_fields.append("origin")
    if not (shipment.destination or "").strip():
        missing_fields.append("destination")
    if shipment.pallets is None:
        missing_fields.append("pallets")
    if shipment.weight_lb is None:
        missing_fields.append("weight_lb")
    if not (shipment.equipment_type or "").strip():
        missing_fields.append("equipment_type")
    if ready_at is None and ready_at_local is None:
        missing_fields.append("ready_at")
    return missing_fields


def _derive_attention_projection(
    *,
    manual_review_required: bool,
    sender_verification_required: bool,
    fraud_risk_level: str | None,
    fraud_risk_reasons: list[str],
    ai_missing_fields: list[str],
    ai_ambiguity_reasons: list[str],
    status_review_required: bool,
    booking_review_required: bool,
    status_stale: bool,
) -> tuple[str, str | None, str]:
    if fraud_risk_level == FraudRiskLevel.HIGH.value:
        return (
            "review",
            "Probable fraud: verify sender before any automation",
            "critical",
        )
    if sender_verification_required:
        return (
            "review",
            "Sender verification required before automation continues",
            "high",
        )
    if ai_missing_fields:
        return (
            "missing_details",
            f"Missing: {', '.join(field.replace('_', ' ') for field in ai_missing_fields)}",
            "high",
        )
    if ai_ambiguity_reasons:
        return (
            "ambiguous",
            _humanize_token(ai_ambiguity_reasons[0]),
            "high",
        )
    if status_stale:
        return ("stale", "Shipment status is stale", "critical")
    if status_review_required:
        return ("status_review", "Status workflow needs operator review", "high")
    if booking_review_required:
        return ("docs_warning", "Document review is blocking safe booking flow", "high")
    if manual_review_required:
        review_reason = "Operator review is required before automation continues"
        if fraud_risk_reasons:
            review_reason = f"{review_reason} ({fraud_risk_reasons[0].replace('_', ' ')})"
        return ("review", review_reason, "high")
    return ("none", None, "normal")


def _normalize_shipment_schedule_fields(shipment: Shipment) -> None:
    """Persist canonical UTC + local schedule fields for pickup and delivery."""
    ready_at, ready_at_local, ready_tz, ready_off = normalize_pickup_datetime_fields(
        ready_at=shipment.ready_at,
        ready_at_local=shipment.ready_at_local,
        origin=shipment.origin,
        destination=shipment.destination,
    )
    shipment.ready_at = ready_at
    shipment.ready_at_local = ready_at_local
    shipment.ready_at_timezone = ready_tz
    shipment.ready_at_offset_minutes = ready_off
    delivery_at, delivery_at_local, delivery_tz, delivery_off = normalize_delivery_datetime_fields(
        delivery_at=shipment.delivery_at,
        delivery_at_local=shipment.delivery_at_local,
        origin=shipment.origin,
        destination=shipment.destination,
    )
    shipment.delivery_at = delivery_at
    shipment.delivery_at_local = delivery_at_local
    shipment.delivery_at_timezone = delivery_tz
    shipment.delivery_at_offset_minutes = delivery_off


async def _archive_shipment_and_optionally_suppress_source(
    session: AsyncSession,
    *,
    shipment: Shipment,
    reason: str | None,
    reason_code: ArchiveReasonCode | None = None,
    reason_note: str | None = None,
    suppress_source_thread: bool,
) -> tuple[Shipment, EmailThread | None]:
    now = datetime.now(timezone.utc)
    archive_reason_code = (reason_code or ArchiveReasonCode.OTHER).value
    archive_reason_note = (reason_note or reason or "").strip() or None
    archive_reason = archive_reason_note or archive_reason_code
    shipment.is_archived = True
    shipment.archive_reason_code = archive_reason_code
    shipment.archive_reason_note = archive_reason_note
    shipment.archived_reason = archive_reason
    shipment.archived_at = now
    shipment.updated_at = now

    archive_event = WorkflowEvent(
        shipment_id=shipment.id,
        event_type=WorkflowEventType.SHIPMENT_ARCHIVED.value,
        stage=shipment.status,
        payload_json={
            "reason": archive_reason,
            "reason_code": archive_reason_code,
            "reason_note": archive_reason_note,
            "suppress_source_thread": suppress_source_thread,
            "email_thread_id": str(shipment.email_thread_id) if shipment.email_thread_id else None,
        },
    )
    session.add(archive_event)

    thread = await session.get(EmailThread, shipment.email_thread_id) if shipment.email_thread_id else None
    if suppress_source_thread and thread is not None:
        thread.shipment_ingest_suppressed = True
        thread.shipment_ingest_suppressed_reason = archive_reason
        thread.shipment_ingest_suppressed_at = now
        suppress_event = WorkflowEvent(
            shipment_id=shipment.id,
            event_type=WorkflowEventType.SHIPMENT_SOURCE_SUPPRESSED.value,
            stage=shipment.status,
            payload_json={
                "reason": archive_reason,
                "reason_code": archive_reason_code,
                "reason_note": archive_reason_note,
                "email_thread_id": str(thread.id),
                "suppressed": True,
            },
        )
        session.add(suppress_event)

    await session.commit()
    await session.refresh(shipment)
    await move_shipment_thread_messages_to_archive(
        session,
        shipment=shipment,
        reason=archive_reason,
    )
    await freight_realtime_hub.publish_overview_stale_throttled(reason="shipment_archived")
    await freight_realtime_hub.publish_shipment_updated(shipment_id=str(shipment.id))
    return shipment, thread


def _serialize_workflow_event(event: WorkflowEvent) -> WorkflowEventRecord:
    return workflow_event_to_record(event)


def _review_priority_score(item: ReviewQueueItem) -> tuple[int, datetime]:
    priority_rank = {
        "critical": 0,
        "high": 1,
        "normal": 2,
    }.get(item.priority, 2)
    return (priority_rank, -item.created_at.timestamp())


def _status_queue_priority(item: StatusQueueItem) -> tuple[int, float]:
    priority_rank = {
        "critical": 0,
        "high": 1,
        "normal": 2,
    }.get(item.priority, 2)
    return (priority_rank, -item.created_at.timestamp())


def _serialize_review_queue_item(
    event: WorkflowEvent,
    *,
    shipment: Shipment | None = None,
    status_payload: dict | None = None,
) -> ReviewQueueItem:
    payload = dict(event.payload_json or {})
    review_type = payload.get("review_type")
    status_payload = status_payload or {}
    now = datetime.now(timezone.utc)
    status_stale = False
    if shipment is not None:
        status_stale = _is_status_stale(
            shipment_status=shipment.status,
            last_status_event_at=status_payload.get("last_status_event_at"),
            now=now,
        )
    status_review_required = isinstance(review_type, str) and "status" in review_type
    priority = "normal"
    alert_label = None
    if status_stale:
        priority = "critical"
        alert_label = "Status overdue"
    elif status_review_required:
        priority = "high"
        alert_label = "Status review"
    elif review_type == "document_conflict_review":
        priority = "high"
        alert_label = "Document conflict"
    elif review_type in {"ocr_review_required", "document_parse_low_confidence"}:
        priority = "high"
        alert_label = "Document review"
    elif review_type == FraudReviewType.SENDER_VERIFICATION.value:
        priority = "high"
        alert_label = "Verify sender"
    elif review_type == FraudReviewType.PROBABLE_FRAUD.value:
        priority = "critical"
        alert_label = "Probable fraud"
    elif payload.get("booking_review_warning"):
        priority = "high"
        alert_label = "Booking warning"

    return ReviewQueueItem(
        workflow_event_id=str(event.id),
        shipment_id=str(event.shipment_id),
        stage=event.stage,
        event_type=event.event_type,
        review_type=review_type,
        priority=priority,
        alert_label=alert_label,
        reason=str(payload.get("reason", "")),
        next_action=payload.get("next_action"),
        missing_fields=list(payload.get("missing_fields", []) or []),
        ambiguity_reasons=list(payload.get("ambiguity_reasons", []) or []),
        missing_document_types=list(payload.get("missing_document_types", []) or []),
        document_conflict_fields=list(payload.get("document_conflict_fields", []) or []),
        booking_review_warning=payload.get("booking_review_warning"),
        status_stale=status_stale,
        status_review_required=status_review_required,
        created_at=event.created_at,
    )


def _status_queue_task_type(review_type: str | None) -> str | None:
    if review_type == "customer_status_request_review":
        return "status_reply"
    if review_type == "carrier_status_update_review":
        return "carrier_update"
    return None


def _status_task_type_from_event(event: WorkflowEvent, payload: dict) -> str | None:
    if event.event_type == WorkflowEventType.CUSTOMER_STATUS_SENT.value and payload.get("dry_run"):
        return "status_reply"
    if event.event_type == WorkflowEventType.TMS_STATUS_UPDATED.value and payload.get("status_audit_kind") == "carrier_update_parsed":
        return "carrier_update"
    if event.event_type == WorkflowEventType.MANUAL_REVIEW_REQUIRED.value:
        return _status_queue_task_type(payload.get("review_type"))
    return None


def _serialize_bid_record(bid: CarrierBid, carrier: Carrier) -> BidRecord:
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


def _serialize_document_record(document: dict) -> ShipmentDocumentRecord:
    return ShipmentDocumentRecord(
        id=document.get("id"),
        name=document.get("name"),
        document_type=str(document.get("document_type", "unknown")),
        content_type=document.get("content_type"),
        size=document.get("size"),
        extracted_text_preview=document.get("extracted_text_preview"),
        extracted_fields=dict(document.get("extracted_fields", {}) or {}),
        extraction_method=document.get("extraction_method"),
        ocr_status=document.get("ocr_status"),
        ocr_confidence=document.get("ocr_confidence"),
        field_confidence=document.get("field_confidence"),
        review_required=bool(document.get("review_required", False)),
        review_reason=document.get("review_reason"),
        source_email_id=str(document.get("source_email_id", "")),
    )


def _is_phase1_ai_event(event: WorkflowEvent, payload: dict) -> bool:
    if event.event_type in {
        WorkflowEventType.SHIPMENT_PARSED.value,
        WorkflowEventType.SHIPMENT_PARSE_FAILED.value,
        WorkflowEventType.SHIPMENT_FIELDS_UPDATED.value,
        WorkflowEventType.CLIENT_ACK_SENT.value,
        WorkflowEventType.CARRIER_OUTREACH_SENT.value,
        WorkflowEventType.EVALUATION_COMPLETED.value,
        WorkflowEventType.CLIENT_QUOTE_SENT.value,
        WorkflowEventType.CUSTOMER_CONFIRMED.value,
    }:
        return True
    if event.event_type != WorkflowEventType.MANUAL_REVIEW_REQUIRED.value:
        return False
    review_type = str(payload.get("review_type") or "")
    if "status" in review_type:
        return False
    if "document" in review_type or "ocr" in review_type:
        return False
    return True


async def _latest_ai_payloads(
    session: AsyncSession,
    shipment_ids: list[UUID],
) -> dict[UUID, dict]:
    if not shipment_ids:
        return {}
    result = await session.execute(
        select(WorkflowEvent)
        .where(WorkflowEvent.shipment_id.in_(shipment_ids))
        .order_by(WorkflowEvent.created_at.desc())
    )
    payloads: dict[UUID, dict] = {}
    for event in result.scalars().all():
        if event.shipment_id in payloads:
            continue
        payload = dict(event.payload_json or {})
        if not _is_phase1_ai_event(event, payload):
            continue
        if any(
            key in payload
            for key in (
                "intent",
                "confidence",
                "missing_fields",
                "ambiguity_reasons",
                "next_action",
                "manual_review_required",
            )
        ):
            payloads[event.shipment_id] = payload
    return payloads


async def _customer_clarification_requested_flags(
    session: AsyncSession,
    shipments: list[Shipment],
) -> dict[UUID, bool]:
    thread_to_shipment = {
        shipment.email_thread_id: shipment.id
        for shipment in shipments
        if shipment.email_thread_id is not None
    }
    if not thread_to_shipment:
        return {}
    result = await session.execute(
        select(EmailMessage).where(
            EmailMessage.thread_id.in_(list(thread_to_shipment.keys())),
            EmailMessage.direction == "outbound",
        )
    )
    flags: dict[UUID, bool] = {}
    for message in result.scalars().all():
        payload = dict(message.raw_payload_json or {})
        if payload.get("type") != "customer_clarification":
            continue
        shipment_id = thread_to_shipment.get(message.thread_id)
        if shipment_id is not None:
            flags[shipment_id] = True
    return flags


async def _latest_missing_fields_for_shipment(
    session: AsyncSession,
    shipment: Shipment,
) -> list[str]:
    result = await session.execute(
        select(WorkflowEvent)
        .where(WorkflowEvent.shipment_id == shipment.id)
        .order_by(WorkflowEvent.created_at.desc())
    )
    for event in result.scalars().all():
        payload = dict(event.payload_json or {})
        missing_fields = list(payload.get("missing_fields", []) or [])
        if missing_fields:
            return missing_fields
        structured = dict(payload.get("structured_payload", {}) or {})
        missing_fields = list(structured.get("missing_fields", []) or [])
        if missing_fields:
            return missing_fields
    return []


async def _latest_fraud_payloads(
    session: AsyncSession,
    shipment_ids: list[UUID],
) -> dict[UUID, dict]:
    if not shipment_ids:
        return {}
    result = await session.execute(
        select(WorkflowEvent)
        .where(
            WorkflowEvent.shipment_id.in_(shipment_ids),
            WorkflowEvent.event_type.in_(
                [
                    WorkflowEventType.EMAIL_RECEIVED.value,
                    WorkflowEventType.MANUAL_REVIEW_REQUIRED.value,
                ]
            ),
        )
        .order_by(WorkflowEvent.created_at.desc())
    )
    payloads: dict[UUID, dict] = {}
    for event in result.scalars().all():
        if event.shipment_id in payloads:
            continue
        payload = dict(event.payload_json or {})
        fraud = dict(payload.get("fraud", {}) or {})
        structured = dict(payload.get("structured_payload", {}) or {})
        risk_level = fraud.get("risk_level") or structured.get("fraud_risk_level")
        verification_required = fraud.get("verification_required")
        if risk_level is None and verification_required is None:
            continue
        payloads[event.shipment_id] = {
            "sender_known": bool(fraud.get("sender_known", structured.get("sender_known", False))),
            "sender_verification_required": bool(
                fraud.get("verification_required", structured.get("sender_verification_required", False))
            ),
            "fraud_risk_level": risk_level,
            "fraud_risk_reasons": list(
                fraud.get("reasons", structured.get("fraud_risk_reasons", [])) or []
            ),
            "fraud_score": fraud.get("score", payload.get("confidence")),
            "sender_email": fraud.get("sender_email", structured.get("sender_email")),
            "sender_domain": fraud.get("sender_domain", structured.get("sender_domain")),
        }
    return payloads


async def _latest_sender_verification_by_shipment(
    session: AsyncSession,
    shipment_ids: list[UUID],
) -> dict[UUID, dict]:
    """Latest operator sender-trust confirmation per shipment (for fraud projection)."""
    if not shipment_ids:
        return {}
    result = await session.execute(
        select(WorkflowEvent)
        .where(
            WorkflowEvent.shipment_id.in_(shipment_ids),
            WorkflowEvent.event_type == WorkflowEventType.SENDER_VERIFIED.value,
        )
        .order_by(WorkflowEvent.created_at.desc())
    )
    out: dict[UUID, dict] = {}
    for event in result.scalars().all():
        if event.shipment_id in out:
            continue
        payload = dict(event.payload_json or {})
        out[event.shipment_id] = {
            "verified_sender_email": payload.get("sender_email"),
            "verified_sender_domain": payload.get("sender_domain"),
            "trust_scope": payload.get("trust_scope", SenderTrustScope.SENDER_EMAIL.value),
            "sender_role": payload.get("sender_role"),
            "verified_at": event.created_at,
            "client_id": payload.get("client_id"),
            "carrier_id": payload.get("carrier_id"),
        }
    return out


async def _merged_fraud_projections(session: AsyncSession, shipment_ids: list[UUID]) -> dict[UUID, dict]:
    if not shipment_ids:
        return {}
    fraud = await _latest_fraud_payloads(session, shipment_ids)
    ver = await _latest_sender_verification_by_shipment(session, shipment_ids)
    return {
        sid: apply_operator_sender_trust_to_fraud_projection(fraud.get(sid), ver.get(sid))
        for sid in shipment_ids
    }


async def _latest_inbound_sender_email_for_shipment(session: AsyncSession, shipment: Shipment) -> str | None:
    """Normalized sender address from the latest inbound message on the shipment thread."""
    if shipment.email_thread_id is None:
        return None
    sender = await session.scalar(
        select(EmailMessage.sender)
        .where(
            EmailMessage.thread_id == shipment.email_thread_id,
            EmailMessage.direction == "inbound",
        )
        .order_by(EmailMessage.received_at.desc())
        .limit(1)
    )
    if not sender:
        return None
    return str(sender).strip().lower()


async def _upsert_fraud_denylist_entry(
    session: AsyncSession,
    *,
    scope: FraudDenylistScope,
    value: str,
    reason: str | None,
    source_shipment_id: UUID | None,
) -> tuple[FraudDenylistEntry, bool]:
    normalized_value = _normalize_fraud_denylist_value(scope, value)
    if not normalized_value:
        raise HTTPException(status_code=400, detail="Cannot create fraud denylist entry without a sender value.")
    entry = await session.scalar(
        select(FraudDenylistEntry).where(
            FraudDenylistEntry.scope == scope.value,
            FraudDenylistEntry.value == normalized_value,
            FraudDenylistEntry.is_active.is_(True),
        )
    )
    if entry is not None:
        return entry, False
    entry = FraudDenylistEntry(
        scope=scope.value,
        value=normalized_value,
        reason=reason,
        source_shipment_id=source_shipment_id,
        is_active=True,
    )
    session.add(entry)
    await session.flush()
    return entry, True


async def _latest_booking_payloads(
    session: AsyncSession,
    shipment_ids: list[UUID],
) -> dict[UUID, dict]:
    if not shipment_ids:
        return {}
    result = await session.execute(
        select(WorkflowEvent)
        .where(WorkflowEvent.shipment_id.in_(shipment_ids))
        .order_by(WorkflowEvent.created_at.desc())
    )
    payloads: dict[UUID, dict] = {}
    for event in result.scalars().all():
        if event.shipment_id in payloads:
            continue
        payload = dict(event.payload_json or {})
        if event.event_type == WorkflowEventType.TMS_HANDOFF_SENT.value:
            payloads[event.shipment_id] = {
                "booking_state": "booked" if payload.get("status") in {"submitted", "already_submitted"} else "booking_preview",
                "tms_handoff_status": payload.get("status"),
                "booking_error": None,
                "attachment_count": payload.get("attachment_count", 0),
                "document_summary": dict(payload.get("document_summary", {}) or {}),
                "document_enrichment": dict(payload.get("document_enrichment", {}) or {}),
                "document_health_status": payload.get("document_health_status"),
                "ocr_pending_count": payload.get("ocr_pending_count", 0),
                "document_conflict_count": payload.get("document_conflict_count", 0),
                "missing_document_types": list(payload.get("missing_document_types", []) or []),
                "booking_review_warning": payload.get("booking_review_warning"),
                "booking_review_required": bool(payload.get("booking_review_required", False)),
            }
        elif event.event_type == WorkflowEventType.EXCEPTION_RAISED.value and payload.get("reason") == "tms_handoff_failed":
            payloads[event.shipment_id] = {
                "booking_state": "booking_failed",
                "tms_handoff_status": "failed",
                "booking_error": payload.get("message"),
                "attachment_count": 0,
                "document_summary": {},
                "document_enrichment": {},
                "document_health_status": None,
                "ocr_pending_count": 0,
                "document_conflict_count": 0,
                "missing_document_types": [],
                "booking_review_warning": None,
                "booking_review_required": False,
            }
        elif event.event_type == WorkflowEventType.CUSTOMER_CONFIRMED.value:
            payloads[event.shipment_id] = {
                "booking_state": "booking_ready",
                "tms_handoff_status": None,
                "booking_error": None,
                "attachment_count": 0,
                "document_summary": {},
                "document_enrichment": {},
                "document_health_status": None,
                "ocr_pending_count": 0,
                "document_conflict_count": 0,
                "missing_document_types": [],
                "booking_review_warning": None,
                "booking_review_required": False,
            }
    return payloads


async def _latest_status_payloads(
    session: AsyncSession,
    shipment_ids: list[UUID],
) -> dict[UUID, dict]:
    if not shipment_ids:
        return {}
    result = await session.execute(
        select(WorkflowEvent)
        .where(WorkflowEvent.shipment_id.in_(shipment_ids))
        .order_by(WorkflowEvent.created_at.desc())
    )
    payloads: dict[UUID, dict] = {}
    for event in result.scalars().all():
        if event.shipment_id in payloads:
            continue
        payload = dict(event.payload_json or {})
        if event.event_type == WorkflowEventType.TMS_STATUS_UPDATED.value:
            update_payload = dict(payload.get("payload", {}) or {})
            payloads[event.shipment_id] = {
                "last_known_status": update_payload.get("status_text") or payload.get("status"),
                "last_known_eta": update_payload.get("eta_text"),
                "last_known_location": update_payload.get("location_text"),
                "last_status_source": "carrier_update",
                "last_status_event_at": event.created_at,
            }
        elif event.event_type in {
            WorkflowEventType.TMS_STATUS_LOOKUP.value,
            WorkflowEventType.CUSTOMER_STATUS_SENT.value,
            WorkflowEventType.TMS_STATUS_INGESTED.value,
        }:
            payloads[event.shipment_id] = {
                "last_known_status": payload.get("status"),
                "last_known_eta": payload.get("eta"),
                "last_known_location": payload.get("location"),
                "last_status_source": "tms_inbound_sync" if event.event_type == WorkflowEventType.TMS_STATUS_INGESTED.value else "tms_lookup",
                "last_status_event_at": event.created_at,
            }
    return payloads


async def _latest_status_review_payloads(
    session: AsyncSession,
    shipment_ids: list[UUID],
) -> dict[UUID, dict]:
    if not shipment_ids:
        return {}
    result = await session.execute(
        select(WorkflowEvent)
        .where(
            WorkflowEvent.shipment_id.in_(shipment_ids),
            WorkflowEvent.event_type.in_(
                [
                    WorkflowEventType.CUSTOMER_STATUS_SENT.value,
                    WorkflowEventType.TMS_STATUS_UPDATED.value,
                    WorkflowEventType.MANUAL_REVIEW_REQUIRED.value,
                    WorkflowEventType.STATUS_WORKFLOW_RESOLVED.value,
                ]
            ),
        )
        .order_by(WorkflowEvent.created_at.desc())
    )
    payloads: dict[UUID, dict] = {}
    resolved: set[tuple[UUID, str]] = set()
    seen: set[tuple[UUID, str]] = set()
    for event in result.scalars().all():
        payload = dict(event.payload_json or {})
        if event.event_type == WorkflowEventType.STATUS_WORKFLOW_RESOLVED.value:
            task_type = str(payload.get("task_type") or "")
            if task_type:
                resolved.add((event.shipment_id, task_type))
            continue
        if event.event_type == WorkflowEventType.CUSTOMER_STATUS_SENT.value and not payload.get("dry_run"):
            resolved.add((event.shipment_id, "status_reply"))
            continue
        if event.event_type == WorkflowEventType.TMS_STATUS_UPDATED.value and payload.get("status_audit_kind") == "carrier_update_pushed":
            resolved.add((event.shipment_id, "carrier_update"))
            continue

        task_type = _status_task_type_from_event(event, payload)
        if task_type is None:
            continue
        key = (event.shipment_id, task_type)
        if key in resolved or key in seen:
            continue
        seen.add(key)
        payloads[event.shipment_id] = {
            "status_review_required": True,
        }
    return payloads


async def _latest_tms_identity_payloads(
    session: AsyncSession,
    shipment_ids: list[UUID],
) -> dict[UUID, dict]:
    if not shipment_ids:
        return {}
    result = await session.execute(
        select(WorkflowEvent)
        .where(
            WorkflowEvent.shipment_id.in_(shipment_ids),
            WorkflowEvent.event_type.in_(
                [
                    WorkflowEventType.TMS_HANDOFF_SENT.value,
                    WorkflowEventType.TMS_STATUS_INGESTED.value,
                ]
            ),
        )
        .order_by(WorkflowEvent.created_at.desc())
    )
    payloads: dict[UUID, dict] = {}
    for event in result.scalars().all():
        current = payloads.setdefault(event.shipment_id, {})
        payload = dict(event.payload_json or {})
        response_payload = dict(payload.get("response", {}) or {})
        request_payload = dict(payload.get("payload", {}) or {})
        if "tms_load_id" not in current:
            tms_load_id = (
                payload.get("tms_load_id")
                or response_payload.get("tms_load_id")
                or response_payload.get("load_id")
                or response_payload.get("id")
                or payload.get("external_load_ref")
            )
            if tms_load_id:
                current["tms_load_id"] = str(tms_load_id)
        if "tms_system" not in current:
            tms_system = payload.get("tms_system") or response_payload.get("tms_system") or request_payload.get("tms_system")
            if tms_system:
                current["tms_system"] = str(tms_system)
    return payloads


async def _status_workflow_payloads(
    session: AsyncSession,
    shipment_ids: list[UUID],
) -> dict[UUID, dict]:
    if not shipment_ids:
        return {}
    result = await session.execute(
        select(WorkflowEvent)
        .where(WorkflowEvent.shipment_id.in_(shipment_ids))
        .order_by(WorkflowEvent.created_at.desc())
    )
    payloads: dict[UUID, dict] = {}
    for event in result.scalars().all():
        if event.shipment_id in payloads:
            continue
        payload = dict(event.payload_json or {})
        state = None
        if event.event_type == WorkflowEventType.STATUS_WORKFLOW_RESOLVED.value:
            state = payload.get("resolution_state") or "resolved"
        elif event.event_type == WorkflowEventType.EXCEPTION_RAISED.value and payload.get("reason") in {
            "lookup_failed",
            "reply_send_failed",
            "tms_push_failed",
            "identity_resolution_failed",
        }:
            state = "failed"
        elif event.event_type == WorkflowEventType.CUSTOMER_STATUS_SENT.value:
            state = "status_reply_drafted" if payload.get("dry_run") else "status_reply_sent"
        elif event.event_type == WorkflowEventType.TMS_STATUS_UPDATED.value:
            audit_kind = str(payload.get("status_audit_kind") or "")
            if audit_kind == "carrier_update_parsed":
                state = "carrier_update_parsed"
            elif audit_kind == "carrier_update_pushed":
                state = "carrier_update_pushed"
        elif event.event_type == WorkflowEventType.TMS_STATUS_INGESTED.value:
            state = "tms_inbound_sync"
        elif event.event_type == WorkflowEventType.MANUAL_REVIEW_REQUIRED.value and "status" in str(payload.get("review_type") or ""):
            state = "awaiting_status_review"
        if state is None:
            continue
        payloads[event.shipment_id] = {"status_workflow_state": state}
    return payloads


def _status_sync_health(
    *,
    status_stale: bool,
    status_review_required: bool,
    status_workflow_state: str | None,
) -> str:
    if status_stale:
        return "stale"
    if status_workflow_state == "failed":
        return "failed"
    if status_review_required:
        return "review_required"
    if status_workflow_state in {"status_reply_drafted", "carrier_update_parsed", "awaiting_status_review"}:
        return "attention_needed"
    return "healthy"


def _latest_status_snapshot(status_payload: dict | None) -> dict:
    status_payload = status_payload or {}
    return {
        "status": status_payload.get("last_known_status"),
        "eta": status_payload.get("last_known_eta"),
        "location": status_payload.get("last_known_location"),
        "source": status_payload.get("last_status_source"),
        "event_at": status_payload.get("last_status_event_at").isoformat() if status_payload.get("last_status_event_at") else None,
    }


def _status_task_state_from_resolution(*, task_type: str, resolution_state: str | None) -> str:
    if resolution_state == "sent":
        return "sent"
    if resolution_state == "pushed":
        return "pushed"
    if resolution_state == "dismissed":
        return "dismissed"
    if resolution_state == "resolved_no_send":
        return "resolved_no_send"
    if resolution_state == "resolved_no_push":
        return "resolved_no_push"
    if resolution_state == "failed":
        return "failed"
    return "resolved" if task_type == "status_reply" else "pushed"


def _resolution_reason_label(reason: str | None) -> str | None:
    if not reason:
        return None
    return str(reason)


def _record_status_task_resolution(
    session: AsyncSession,
    *,
    shipment: Shipment,
    task_type: str,
    resolution_state: str,
    resolution_reason: str,
    source_task_id: str | None = None,
    source: str | None = None,
) -> WorkflowEvent:
    evt = WorkflowEvent(
        shipment_id=shipment.id,
        event_type=WorkflowEventType.STATUS_WORKFLOW_RESOLVED.value,
        stage=shipment.status,
        payload_json={
            "task_type": task_type,
            "resolution_state": resolution_state,
            "resolution_reason": resolution_reason,
            "source_task_id": source_task_id,
            "source": source,
        },
    )
    session.add(evt)
    return evt


def _build_status_queue_item(
    *,
    event: WorkflowEvent,
    shipment: Shipment,
    status_payload: dict | None,
    tms_identity_payload: dict | None,
    workflow_payload: dict | None,
) -> StatusQueueItem | None:
    payload = dict(event.payload_json or {})
    status_payload = status_payload or {}
    tms_identity_payload = tms_identity_payload or {}
    workflow_payload = workflow_payload or {}
    task_type: str | None = _status_task_type_from_event(event, payload)
    task_state: str | None = None
    reason = str(payload.get("reason", ""))
    structured_payload: dict = {}
    draft_subject: str | None = None
    draft_body: str | None = None
    last_failure: str | None = None
    alert_label: str | None = None
    recommended_next_action = payload.get("next_action")
    review_type = payload.get("review_type")
    ambiguity_reasons = list(payload.get("ambiguity_reasons", []) or [])
    source_email_id = payload.get("source_email_id")

    if event.event_type == WorkflowEventType.CUSTOMER_STATUS_SENT.value and payload.get("dry_run"):
        task_state = "draft_ready"
        draft_subject = payload.get("subject")
        draft_body = payload.get("body")
        structured_payload = {"custom_message": payload.get("custom_message")}
        alert_label = "Reply draft ready"
        recommended_next_action = "approve_and_send"
    elif event.event_type == WorkflowEventType.TMS_STATUS_UPDATED.value and payload.get("status_audit_kind") == "carrier_update_parsed":
        task_state = "awaiting_review"
        structured_payload = dict(payload.get("payload", {}) or {})
        alert_label = "Carrier update review"
        recommended_next_action = "approve_and_push"
    elif event.event_type == WorkflowEventType.MANUAL_REVIEW_REQUIRED.value and "status" in str(review_type or ""):
        task_state = "awaiting_approval" if task_type == "status_reply" else "awaiting_review"
        structured_payload = dict(payload.get("structured_payload", {}) or {})
        draft_subject = structured_payload.get("draft_subject") if task_type == "status_reply" else None
        draft_body = structured_payload.get("draft_body") if task_type == "status_reply" else None
        alert_label = "Status review required"
    elif event.event_type == WorkflowEventType.EXCEPTION_RAISED.value and payload.get("reason") in {
        "lookup_failed",
        "reply_send_failed",
        "tms_push_failed",
        "identity_resolution_failed",
    }:
        task_type = "status_reply" if payload.get("reason") in {"lookup_failed", "reply_send_failed"} else "carrier_update"
        task_state = "failed"
        last_failure = str(payload.get("message") or payload.get("reason"))
        structured_payload = dict(payload.get("payload", {}) or {})
        alert_label = "Status sync failed"
        recommended_next_action = "retry_push" if task_type == "carrier_update" else "rebuild_draft"
    if task_type is None or task_state is None:
        return None

    priority = "critical" if _is_status_stale(
        shipment_status=shipment.status,
        last_status_event_at=status_payload.get("last_status_event_at"),
        now=datetime.now(timezone.utc),
    ) else "high" if task_state in {"failed", "awaiting_review", "awaiting_approval"} else "normal"

    return StatusQueueItem(
        task_id=str(event.id),
        task_type=task_type,
        task_state=task_state,
        queue_scope="active",
        resolution_state=None,
        resolution_reason=None,
        resolution_at=None,
        shipment_id=str(shipment.id),
        email_thread_id=str(shipment.email_thread_id) if shipment.email_thread_id else None,
        source_email_id=str(source_email_id) if source_email_id else None,
        priority=priority,
        alert_label=alert_label,
        reason=reason,
        recommended_next_action=str(recommended_next_action) if recommended_next_action else None,
        review_type=str(review_type) if review_type else None,
        ambiguity_reasons=ambiguity_reasons,
        latest_status_snapshot=_latest_status_snapshot(status_payload),
        draft_subject=draft_subject,
        draft_body=draft_body,
        structured_payload=structured_payload,
        last_failure=last_failure,
        tms_load_id=tms_identity_payload.get("tms_load_id"),
        tms_system=tms_identity_payload.get("tms_system"),
        status_sync_health=_status_sync_health(
            status_stale=_is_status_stale(
                shipment_status=shipment.status,
                last_status_event_at=status_payload.get("last_status_event_at"),
                now=datetime.now(timezone.utc),
            ),
            status_review_required="status" in str(review_type or ""),
            status_workflow_state=workflow_payload.get("status_workflow_state"),
        ),
        created_at=event.created_at,
    )


def _build_resolved_status_queue_item(
    *,
    resolution_event: WorkflowEvent,
    shipment: Shipment,
    source_event: WorkflowEvent | None,
    status_payload: dict | None,
    tms_identity_payload: dict | None,
) -> StatusQueueItem | None:
    resolution_payload = dict(resolution_event.payload_json or {})
    task_type = str(resolution_payload.get("task_type") or "")
    if not task_type:
        return None

    if source_event is not None:
        source_item = _build_status_queue_item(
            event=source_event,
            shipment=shipment,
            status_payload=status_payload,
            tms_identity_payload=tms_identity_payload,
            workflow_payload={},
        )
        if source_item is not None:
            return source_item.model_copy(
                update={
                    "task_state": _status_task_state_from_resolution(
                        task_type=task_type,
                        resolution_state=resolution_payload.get("resolution_state"),
                    ),
                    "queue_scope": "resolved",
                    "resolution_state": resolution_payload.get("resolution_state"),
                    "resolution_reason": _resolution_reason_label(resolution_payload.get("resolution_reason")),
                    "resolution_at": resolution_event.created_at,
                }
            )

    return StatusQueueItem(
        task_id=str(resolution_event.id),
        task_type=task_type,
        task_state=_status_task_state_from_resolution(
            task_type=task_type,
            resolution_state=resolution_payload.get("resolution_state"),
        ),
        queue_scope="resolved",
        resolution_state=resolution_payload.get("resolution_state"),
        resolution_reason=_resolution_reason_label(resolution_payload.get("resolution_reason")),
        resolution_at=resolution_event.created_at,
        shipment_id=str(shipment.id),
        email_thread_id=str(shipment.email_thread_id) if shipment.email_thread_id else None,
        source_email_id=str(resolution_payload.get("source_email_id")) if resolution_payload.get("source_email_id") else None,
        priority="normal",
        alert_label="Resolved status task",
        reason="Resolved status task",
        recommended_next_action=None,
        review_type=None,
        ambiguity_reasons=[],
        latest_status_snapshot=_latest_status_snapshot(status_payload),
        draft_subject=None,
        draft_body=None,
        structured_payload={},
        last_failure=None,
        tms_load_id=(tms_identity_payload or {}).get("tms_load_id"),
        tms_system=(tms_identity_payload or {}).get("tms_system"),
        status_sync_health=_status_sync_health(
            status_stale=_is_status_stale(
                shipment_status=shipment.status,
                last_status_event_at=(status_payload or {}).get("last_status_event_at"),
                now=datetime.now(timezone.utc),
            ),
            status_review_required=False,
            status_workflow_state=resolution_payload.get("resolution_state"),
        ),
        created_at=source_event.created_at if source_event is not None else resolution_event.created_at,
    )


async def _active_status_queue_items(session: AsyncSession) -> list[StatusQueueItem]:
    result = await session.execute(
        select(WorkflowEvent)
        .where(
            WorkflowEvent.event_type.in_(
                [
                    WorkflowEventType.CUSTOMER_STATUS_SENT.value,
                    WorkflowEventType.TMS_STATUS_UPDATED.value,
                    WorkflowEventType.MANUAL_REVIEW_REQUIRED.value,
                    WorkflowEventType.EXCEPTION_RAISED.value,
                    WorkflowEventType.STATUS_WORKFLOW_RESOLVED.value,
                ]
            )
        )
        .order_by(WorkflowEvent.created_at.desc())
    )
    events = list(result.scalars().all())
    shipment_ids = list({event.shipment_id for event in events})
    shipments_by_id: dict[UUID, Shipment] = {}
    if shipment_ids:
        shipment_result = await session.execute(select(Shipment).where(Shipment.id.in_(shipment_ids)))
        shipments_by_id = {shipment.id: shipment for shipment in shipment_result.scalars().all()}
    status_payloads = await _latest_status_payloads(session, shipment_ids)
    tms_identity_payloads = await _latest_tms_identity_payloads(session, shipment_ids)
    workflow_payloads = await _status_workflow_payloads(session, shipment_ids)
    resolved: set[tuple[UUID, str]] = set()
    items: list[StatusQueueItem] = []
    seen: set[tuple[UUID, str]] = set()

    for event in events:
        payload = dict(event.payload_json or {})
        if event.event_type == WorkflowEventType.STATUS_WORKFLOW_RESOLVED.value:
            task_type = str(payload.get("task_type") or "")
            if task_type:
                resolved.add((event.shipment_id, task_type))
            continue
        if event.event_type == WorkflowEventType.CUSTOMER_STATUS_SENT.value and not payload.get("dry_run"):
            resolved.add((event.shipment_id, "status_reply"))
            continue
        if event.event_type == WorkflowEventType.TMS_STATUS_UPDATED.value and payload.get("status_audit_kind") == "carrier_update_pushed":
            resolved.add((event.shipment_id, "carrier_update"))
            continue

        shipment = shipments_by_id.get(event.shipment_id)
        if shipment is None:
            continue
        if shipment.is_archived:
            continue
        item = _build_status_queue_item(
            event=event,
            shipment=shipment,
            status_payload=status_payloads.get(event.shipment_id),
            tms_identity_payload=tms_identity_payloads.get(event.shipment_id),
            workflow_payload=workflow_payloads.get(event.shipment_id),
        )
        if item is None:
            continue
        key = (event.shipment_id, item.task_type)
        if key in resolved or key in seen:
            continue
        seen.add(key)
        items.append(item)

    return sorted(items, key=_status_queue_priority)


async def _resolved_status_queue_items(session: AsyncSession, *, limit: int = 25) -> list[StatusQueueItem]:
    result = await session.execute(
        select(WorkflowEvent)
        .where(WorkflowEvent.event_type == WorkflowEventType.STATUS_WORKFLOW_RESOLVED.value)
        .order_by(WorkflowEvent.created_at.desc())
    )
    resolution_events = list(result.scalars().all())
    if not resolution_events:
        return []

    shipment_ids = list({event.shipment_id for event in resolution_events})
    shipment_result = await session.execute(select(Shipment).where(Shipment.id.in_(shipment_ids)))
    shipments_by_id = {shipment.id: shipment for shipment in shipment_result.scalars().all()}
    status_payloads = await _latest_status_payloads(session, shipment_ids)
    tms_identity_payloads = await _latest_tms_identity_payloads(session, shipment_ids)

    source_task_ids = {
        UUID(source_task_id)
        for event in resolution_events
        for source_task_id in [dict(event.payload_json or {}).get("source_task_id")]
        if isinstance(source_task_id, str)
    }
    source_events_by_id: dict[UUID, WorkflowEvent] = {}
    if source_task_ids:
        source_result = await session.execute(select(WorkflowEvent).where(WorkflowEvent.id.in_(source_task_ids)))
        source_events_by_id = {event.id: event for event in source_result.scalars().all()}

    items: list[StatusQueueItem] = []
    seen: set[tuple[UUID, str, str | None]] = set()
    for resolution_event in resolution_events:
        payload = dict(resolution_event.payload_json or {})
        shipment = shipments_by_id.get(resolution_event.shipment_id)
        if shipment is None:
            continue
        if shipment.is_archived:
            continue
        task_type = str(payload.get("task_type") or "")
        key = (resolution_event.shipment_id, task_type, str(payload.get("source_task_id") or ""))
        if key in seen:
            continue
        seen.add(key)
        source_event = None
        source_task_id = payload.get("source_task_id")
        if isinstance(source_task_id, str):
            try:
                source_event = source_events_by_id.get(UUID(source_task_id))
            except ValueError:
                source_event = None
        item = _build_resolved_status_queue_item(
            resolution_event=resolution_event,
            shipment=shipment,
            source_event=source_event,
            status_payload=status_payloads.get(resolution_event.shipment_id),
            tms_identity_payload=tms_identity_payloads.get(resolution_event.shipment_id),
        )
        if item is not None:
            items.append(item)
        if len(items) >= limit:
            break
    return items


async def _latest_status_resolution(
    session: AsyncSession,
    *,
    shipment_id: UUID,
    task_type: str,
) -> WorkflowEvent | None:
    return await session.scalar(
        select(WorkflowEvent)
        .where(
            WorkflowEvent.shipment_id == shipment_id,
            WorkflowEvent.event_type == WorkflowEventType.STATUS_WORKFLOW_RESOLVED.value,
            WorkflowEvent.payload_json["task_type"].as_string() == task_type,
        )
        .order_by(WorkflowEvent.created_at.desc())
    )


async def _is_task_already_resolved(
    session: AsyncSession,
    *,
    shipment_id: UUID,
    task_type: str,
    resolution_state: str,
    source_task_id: str | None = None,
) -> bool:
    result = await session.execute(
        select(WorkflowEvent)
        .where(
            WorkflowEvent.shipment_id == shipment_id,
            WorkflowEvent.event_type == WorkflowEventType.STATUS_WORKFLOW_RESOLVED.value,
        )
        .order_by(WorkflowEvent.created_at.desc())
    )
    for event in result.scalars().all():
        payload = dict(event.payload_json or {})
        if payload.get("task_type") != task_type:
            continue
        if payload.get("resolution_state") != resolution_state:
            continue
        if source_task_id is not None and payload.get("source_task_id") not in {None, source_task_id}:
            continue
        return True
    return False


async def _attachment_counts(
    session: AsyncSession,
    shipments: list[Shipment],
) -> dict[UUID, int]:
    counts: dict[UUID, int] = {}
    for shipment in shipments:
        if shipment.email_thread_id is None:
            counts[shipment.id] = 0
            continue
        result = await session.execute(
            select(EmailMessage).where(EmailMessage.thread_id == shipment.email_thread_id)
        )
        count = 0
        seen: set[tuple[str | None, str | None]] = set()
        for message in result.scalars().all():
            payload = dict(message.raw_payload_json or {})
            for item in payload.get("attachments") or payload.get("Attachments") or []:
                if not isinstance(item, dict):
                    continue
                key = (item.get("id"), item.get("name") or item.get("fileName") or item.get("filename"))
                if key in seen:
                    continue
                seen.add(key)
                count += 1
        counts[shipment.id] = count
    return counts


async def _document_booking_summaries(
    session: AsyncSession,
    shipments: list[Shipment],
    action_payloads: dict[UUID, dict] | None = None,
) -> dict[UUID, dict]:
    summaries: dict[UUID, dict] = {}
    for shipment in shipments:
        attachments = await collect_shipment_attachments(session, shipment)
        action_payload = (action_payloads or {}).get(shipment.id) or {}
        summaries[shipment.id] = build_document_health(
            attachments,
            shipment,
            approved_fields=dict(action_payload.get("approved_fields", {}) or {}),
            warning_ignored=bool(action_payload.get("warning_ignored", False)),
        )
    return summaries


async def _latest_document_action_payloads(
    session: AsyncSession,
    shipment_ids: list[UUID],
) -> dict[UUID, dict]:
    if not shipment_ids:
        return {}
    result = await session.execute(
        select(WorkflowEvent)
        .where(
            WorkflowEvent.shipment_id.in_(shipment_ids),
            WorkflowEvent.event_type.in_(
                [
                    WorkflowEventType.DOCUMENT_VALUES_APPROVED.value,
                    WorkflowEventType.DOCUMENT_WARNING_IGNORED.value,
                ]
            ),
        )
        .order_by(WorkflowEvent.created_at.desc())
    )
    payloads: dict[UUID, dict] = {}
    for event in result.scalars().all():
        current = payloads.setdefault(event.shipment_id, {})
        payload = dict(event.payload_json or {})
        if event.event_type == WorkflowEventType.DOCUMENT_VALUES_APPROVED.value and "approved_fields" not in current:
            current["approved_fields"] = dict(payload.get("approved_fields", {}) or {})
        if event.event_type == WorkflowEventType.DOCUMENT_WARNING_IGNORED.value and "warning_ignored" not in current:
            current["warning_ignored"] = True
    return payloads


async def _collect_document_state(
    session: AsyncSession,
    shipment: Shipment,
    *,
    force_reprocess: bool = False,
) -> tuple[list[dict], dict, dict]:
    attachments = await collect_shipment_attachments(
        session,
        shipment,
        force_reprocess=force_reprocess,
    )
    action_payload = (await _latest_document_action_payloads(session, [shipment.id])).get(shipment.id) or {}
    document_health = build_document_health(
        attachments,
        shipment,
        approved_fields=dict(action_payload.get("approved_fields", {}) or {}),
        warning_ignored=bool(action_payload.get("warning_ignored", False)),
    )
    document_context = build_document_context(attachments)
    return attachments, document_health, document_context


def _document_review_type(document_health: dict) -> str:
    if document_health.get("document_conflict_count", 0):
        return "document_conflict_review"
    if document_health.get("ocr_pending_count", 0):
        return "ocr_review_required"
    return "document_parse_low_confidence"


def _persist_document_analysis_events(
    session: AsyncSession,
    shipment: Shipment,
    *,
    document_health: dict,
    document_context: dict,
    event_type: WorkflowEventType = WorkflowEventType.DOCUMENT_ANALYZED,
) -> list[WorkflowEvent]:
    events_out: list[WorkflowEvent] = []
    analyzed = WorkflowEvent(
        shipment_id=shipment.id,
        event_type=event_type.value,
        stage=shipment.status,
        payload_json={
            "attachment_count": document_health.get("attachment_count", 0),
            "document_summary": dict(document_health.get("document_summary", {}) or {}),
            "document_enrichment": dict(document_health.get("document_enrichment", {}) or {}),
            "document_health_status": document_health.get("document_health_status"),
            "ocr_pending_count": document_health.get("ocr_pending_count", 0),
            "document_conflict_count": document_health.get("document_conflict_count", 0),
            "document_conflict_fields": list(document_health.get("document_conflict_fields", []) or []),
            "missing_document_types": list(document_health.get("missing_document_types", []) or []),
            "booking_review_warning": document_health.get("booking_review_warning"),
            "booking_review_required": bool(document_health.get("booking_review_required", False)),
            "review_required": bool(document_health.get("review_required", False)),
            "document_extracts": list(document_context.get("document_extracts", []) or []),
        },
    )
    session.add(analyzed)
    events_out.append(analyzed)
    if document_health.get("review_required"):
        review_evt = WorkflowEvent(
            shipment_id=shipment.id,
            event_type=WorkflowEventType.MANUAL_REVIEW_REQUIRED.value,
            stage=shipment.status,
            payload_json={
                "review_type": _document_review_type(document_health),
                "reason": document_health.get("booking_review_warning")
                or "Document extraction requires operator review.",
                "next_action": "review_documents",
                "missing_document_types": list(document_health.get("missing_document_types", []) or []),
                "document_conflict_fields": list(document_health.get("document_conflict_fields", []) or []),
                "booking_review_warning": document_health.get("booking_review_warning"),
            },
        )
        session.add(review_evt)
        events_out.append(review_evt)
    return events_out


@router.get("/freight/foundation", response_model=FreightFoundationResponse)
async def freight_foundation() -> FreightFoundationResponse:
    """Return workflow enums and deterministic correlation strategy details."""
    return FreightFoundationResponse(
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


@router.get("/freight/clients", response_model=list[ClientRecord])
async def list_clients(session: AsyncSession = Depends(get_session)) -> list[ClientRecord]:
    """List all clients for freight workflows."""
    result = await session.execute(select(Client).order_by(Client.created_at.desc()))
    return [_serialize_client(client) for client in result.scalars().all()]


@router.post("/freight/clients", response_model=ClientRecord)
async def create_client(
    request: ClientUpsertRequest,
    session: AsyncSession = Depends(get_session),
) -> ClientRecord:
    """Create a client record."""
    existing = await session.scalar(select(Client).where(Client.email == request.email.lower()))
    if existing is not None:
        raise HTTPException(status_code=409, detail="Client with this email already exists.")

    client = Client(
        name=request.name,
        email=request.email.lower(),
        is_active=request.is_active,
        default_margin_percent=request.default_margin_percent,
        default_margin_floor=request.default_margin_floor,
    )
    session.add(client)
    await session.commit()
    await session.refresh(client)
    await freight_realtime_hub.publish_overview_stale_throttled(reason="client_created")
    return _serialize_client(client)


@router.get("/freight/clients/{client_id}", response_model=ClientRecord)
async def get_client(client_id: UUID, session: AsyncSession = Depends(get_session)) -> ClientRecord:
    """Get a client by id."""
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found.")
    return _serialize_client(client)


@router.patch("/freight/clients/{client_id}", response_model=ClientRecord)
async def update_client(
    client_id: UUID,
    request: ClientUpsertRequest,
    session: AsyncSession = Depends(get_session),
) -> ClientRecord:
    """Update a client record."""
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found.")

    existing = await session.scalar(select(Client).where(Client.email == request.email.lower()))
    if existing is not None and existing.id != client.id:
        raise HTTPException(status_code=409, detail="Client with this email already exists.")

    client.name = request.name
    client.email = request.email.lower()
    client.is_active = request.is_active
    client.default_margin_percent = request.default_margin_percent
    client.default_margin_floor = request.default_margin_floor
    await session.commit()
    await session.refresh(client)
    await freight_realtime_hub.publish_overview_stale_throttled(reason="client_updated")
    return _serialize_client(client)


@router.get("/freight/carriers", response_model=list[CarrierRecord])
async def list_carriers(session: AsyncSession = Depends(get_session)) -> list[CarrierRecord]:
    """List all carriers available for outreach."""
    result = await session.execute(select(Carrier).order_by(Carrier.created_at.desc()))
    return [_serialize_carrier(carrier) for carrier in result.scalars().all()]


@router.post("/freight/carriers", response_model=CarrierRecord)
async def create_carrier(
    request: CarrierUpsertRequest,
    session: AsyncSession = Depends(get_session),
) -> CarrierRecord:
    """Create a carrier record."""
    existing = await session.scalar(select(Carrier).where(Carrier.email == request.email.lower()))
    if existing is not None:
        raise HTTPException(status_code=409, detail="Carrier with this email already exists.")

    carrier = Carrier(
        name=request.name,
        email=request.email.lower(),
        rating=request.rating,
        is_active=request.is_active,
        regions_json=request.regions,
        equipment_json=request.equipment,
        metadata_json=request.metadata,
    )
    session.add(carrier)
    await session.commit()
    await session.refresh(carrier)
    await freight_realtime_hub.publish_overview_stale_throttled(reason="carrier_created")
    return _serialize_carrier(carrier)


@router.get("/freight/carriers/{carrier_id}", response_model=CarrierRecord)
async def get_carrier(carrier_id: UUID, session: AsyncSession = Depends(get_session)) -> CarrierRecord:
    """Get a carrier by id."""
    carrier = await session.get(Carrier, carrier_id)
    if carrier is None:
        raise HTTPException(status_code=404, detail="Carrier not found.")
    return _serialize_carrier(carrier)


@router.patch("/freight/carriers/{carrier_id}", response_model=CarrierRecord)
async def update_carrier(
    carrier_id: UUID,
    request: CarrierUpsertRequest,
    session: AsyncSession = Depends(get_session),
) -> CarrierRecord:
    """Update a carrier record."""
    carrier = await session.get(Carrier, carrier_id)
    if carrier is None:
        raise HTTPException(status_code=404, detail="Carrier not found.")

    existing = await session.scalar(select(Carrier).where(Carrier.email == request.email.lower()))
    if existing is not None and existing.id != carrier.id:
        raise HTTPException(status_code=409, detail="Carrier with this email already exists.")

    carrier.name = request.name
    carrier.email = request.email.lower()
    carrier.rating = request.rating
    carrier.is_active = request.is_active
    carrier.regions_json = request.regions
    carrier.equipment_json = request.equipment
    carrier.metadata_json = request.metadata
    await session.commit()
    await session.refresh(carrier)
    await freight_realtime_hub.publish_overview_stale_throttled(reason="carrier_updated")
    return _serialize_carrier(carrier)


@router.get("/freight/fraud-denylist", response_model=list[FraudDenylistEntryRecord])
async def list_fraud_denylist_entries(
    value: str | None = Query(default=None),
    include_inactive: bool = Query(default=True),
    session: AsyncSession = Depends(get_session),
) -> list[FraudDenylistEntryRecord]:
    """List fraud denylist entries, optionally scoped to one email/domain value."""
    conditions = []
    if not include_inactive:
        conditions.append(FraudDenylistEntry.is_active.is_(True))
    if value:
        normalized_email = normalize_sender_email(value)
        normalized_domain = extract_sender_domain(normalized_email or value)
        value_conditions = []
        if normalized_email:
            value_conditions.append(
                (FraudDenylistEntry.scope == FraudDenylistScope.SENDER_EMAIL.value)
                & (FraudDenylistEntry.value == normalized_email)
            )
        if normalized_domain:
            value_conditions.append(
                (FraudDenylistEntry.scope == FraudDenylistScope.SENDER_DOMAIN.value)
                & (FraudDenylistEntry.value == normalized_domain)
            )
        if value_conditions:
            conditions.append(or_(*value_conditions))
    query = select(FraudDenylistEntry).order_by(FraudDenylistEntry.updated_at.desc())
    if conditions:
        query = query.where(*conditions)
    result = await session.execute(query)
    return [_serialize_fraud_denylist_entry(entry) for entry in result.scalars().all()]


@router.post("/freight/fraud-denylist", response_model=FraudDenylistEntryRecord)
async def create_fraud_denylist_entry(
    request: FraudDenylistEntryRequest,
    session: AsyncSession = Depends(get_session),
) -> FraudDenylistEntryRecord:
    """Create or reactivate a fraud denylist entry."""
    normalized_value = _normalize_fraud_denylist_value(request.scope, request.value)
    if not normalized_value:
        raise HTTPException(status_code=400, detail="Cannot create fraud denylist entry without a sender value.")
    entry = await session.scalar(
        select(FraudDenylistEntry).where(
            FraudDenylistEntry.scope == request.scope.value,
            FraudDenylistEntry.value == normalized_value,
        )
    )
    if entry is None:
        entry = FraudDenylistEntry(
            scope=request.scope.value,
            value=normalized_value,
            reason=request.reason,
            is_active=request.is_active,
        )
        session.add(entry)
    else:
        entry.reason = request.reason
        entry.is_active = request.is_active
        entry.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(entry)
    return _serialize_fraud_denylist_entry(entry)


@router.patch("/freight/fraud-denylist/{entry_id}", response_model=FraudDenylistEntryRecord)
async def update_fraud_denylist_entry(
    entry_id: UUID,
    request: FraudDenylistEntryUpdateRequest,
    session: AsyncSession = Depends(get_session),
) -> FraudDenylistEntryRecord:
    """Update fraud denylist entry state."""
    entry = await session.get(FraudDenylistEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Fraud denylist entry not found.")
    entry.reason = request.reason
    entry.is_active = request.is_active
    entry.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(entry)
    return _serialize_fraud_denylist_entry(entry)


@router.get("/freight/shipments", response_model=list[ShipmentRecord])
async def list_shipments(
    month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    session: AsyncSession = Depends(get_session),
) -> list[ShipmentRecord]:
    """List all tracked shipments."""
    result = await session.execute(
        select(Shipment).where(Shipment.is_archived.is_(False)).order_by(Shipment.updated_at.desc(), Shipment.created_at.desc())
    )
    shipments = [
        shipment
        for shipment in result.scalars().all()
        if _shipment_matches_month_filter(shipment, month=month)
    ]
    ai_payloads = await _latest_ai_payloads(session, [shipment.id for shipment in shipments])
    fraud_payloads = await _merged_fraud_projections(session, [shipment.id for shipment in shipments])
    booking_payloads = await _latest_booking_payloads(session, [shipment.id for shipment in shipments])
    status_payloads = await _latest_status_payloads(session, [shipment.id for shipment in shipments])
    status_review_payloads = await _latest_status_review_payloads(session, [shipment.id for shipment in shipments])
    tms_identity_payloads = await _latest_tms_identity_payloads(session, [shipment.id for shipment in shipments])
    status_workflow_payloads = await _status_workflow_payloads(session, [shipment.id for shipment in shipments])
    document_action_payloads = await _latest_document_action_payloads(session, [shipment.id for shipment in shipments])
    clarification_flags = await _customer_clarification_requested_flags(session, shipments)
    attachment_counts = await _attachment_counts(session, shipments)
    document_summaries = await _document_booking_summaries(session, shipments, document_action_payloads)
    now = datetime.now(timezone.utc)
    records = [
        _serialize_shipment(
            shipment,
            {
                **(ai_payloads.get(shipment.id) or {}),
                **(fraud_payloads.get(shipment.id) or {}),
                **(booking_payloads.get(shipment.id) or {}),
                **(status_payloads.get(shipment.id) or {}),
                **(status_review_payloads.get(shipment.id) or {}),
                **(tms_identity_payloads.get(shipment.id) or {}),
                **(status_workflow_payloads.get(shipment.id) or {}),
                "attachment_count": attachment_counts.get(shipment.id, 0),
                "document_summary": document_summaries.get(shipment.id, {}).get("document_summary", {}),
                "document_enrichment": document_summaries.get(shipment.id, {}).get("document_enrichment", {}),
                "document_health_status": document_summaries.get(shipment.id, {}).get("document_health_status"),
                "ocr_pending_count": document_summaries.get(shipment.id, {}).get("ocr_pending_count", 0),
                "document_conflict_count": document_summaries.get(shipment.id, {}).get("document_conflict_count", 0),
                "missing_document_types": document_summaries.get(shipment.id, {}).get("missing_document_types", []),
                "booking_review_warning": document_summaries.get(shipment.id, {}).get("booking_review_warning"),
                "booking_review_required": document_summaries.get(shipment.id, {}).get("review_required", False),
                "status_stale": _is_status_stale(
                    shipment_status=shipment.status,
                    last_status_event_at=(status_payloads.get(shipment.id) or {}).get("last_status_event_at"),
                    now=now,
                ),
                "status_sync_health": _status_sync_health(
                    status_stale=_is_status_stale(
                        shipment_status=shipment.status,
                        last_status_event_at=(status_payloads.get(shipment.id) or {}).get("last_status_event_at"),
                        now=now,
                    ),
                    status_review_required=bool((status_review_payloads.get(shipment.id) or {}).get("status_review_required", False)),
                    status_workflow_state=(status_workflow_payloads.get(shipment.id) or {}).get("status_workflow_state"),
                ),
                "status_sla_hours": settings.status_sla_hours_default,
                "customer_clarification_requested": clarification_flags.get(shipment.id, False),
            },
        )
        for shipment in shipments
    ]
    return sorted(records, key=_shipment_board_sort_key)


@router.post("/freight/shipments", response_model=ShipmentRecord)
async def create_shipment(
    request: ShipmentUpsertRequest,
    session: AsyncSession = Depends(get_session),
) -> ShipmentRecord:
    """Create a shipment manually from the dashboard."""
    client_id = None
    if request.client_id:
        client_id = UUID(request.client_id)
        client = await session.get(Client, client_id)
        if client is None:
            raise HTTPException(status_code=404, detail="Client not found.")

    shipment = Shipment(
        client_id=client_id,
        status=request.status.value,
        origin=request.origin,
        destination=request.destination,
        pallets=request.pallets,
        weight_lb=request.weight_lb,
        equipment_type=request.equipment_type,
        ready_at=request.ready_at if request.ready_at and request.ready_at.tzinfo else None,
        ready_at_local=request.ready_at_local or (request.ready_at if request.ready_at and request.ready_at.tzinfo is None else None),
        delivery_at=request.delivery_at if request.delivery_at and request.delivery_at.tzinfo else None,
        delivery_at_local=request.delivery_at_local or (request.delivery_at if request.delivery_at and request.delivery_at.tzinfo is None else None),
        margin_policy_json=(request.margin_policy.model_dump() if request.margin_policy else {}),
        notes=request.notes,
    )
    _normalize_shipment_schedule_fields(shipment)
    session.add(shipment)
    await session.commit()
    await session.refresh(shipment)
    await freight_realtime_hub.publish_shipment_updated(shipment_id=str(shipment.id))
    return _serialize_shipment(shipment)


@router.get("/freight/shipments/by-token/{quote_token}", response_model=ShipmentRecord)
async def get_shipment_by_token(
    quote_token: str,
    session: AsyncSession = Depends(get_session),
) -> ShipmentRecord:
    """Get an active shipment by its public quote token."""
    normalized_token = quote_token.strip().upper()
    if not normalized_token:
        raise HTTPException(status_code=404, detail="Shipment not found.")
    shipment = await session.scalar(
        select(Shipment).where(
            Shipment.is_archived.is_(False),
            func.upper(Shipment.quote_token) == normalized_token,
        )
    )
    if shipment is None:
        raise HTTPException(status_code=404, detail="Shipment not found.")
    return await _serialize_shipment_detail(session, shipment)


def _shipment_archive_reason_code(shipment: Shipment) -> str:
    code = getattr(shipment, "archive_reason_code", None)
    if code:
        return str(code)
    legacy_reason = str(getattr(shipment, "archived_reason", None) or "").lower()
    if "duplicate" in legacy_reason:
        return ArchiveReasonCode.DUPLICATE.value
    if "cancel" in legacy_reason:
        return ArchiveReasonCode.CANCELLED.value
    if "bounce" in legacy_reason or "non-delivery" in legacy_reason or "undeliver" in legacy_reason:
        return ArchiveReasonCode.NON_DELIVERY_BOUNCE.value
    if "fraud" in legacy_reason or "spam" in legacy_reason:
        return ArchiveReasonCode.FRAUD.value
    if "test" in legacy_reason:
        return ArchiveReasonCode.TEST.value
    if "parse" in legacy_reason or "invalid" in legacy_reason or "error" in legacy_reason:
        return ArchiveReasonCode.PARSED_ERROR.value
    return ArchiveReasonCode.OTHER.value


def _shipment_archive_reason_note(shipment: Shipment) -> str | None:
    note = getattr(shipment, "archive_reason_note", None)
    if note:
        return str(note)
    legacy = getattr(shipment, "archived_reason", None)
    return str(legacy) if legacy else None


@router.get("/freight/shipments/archive", response_model=list[ShipmentRecord])
async def list_archived_shipments(
    reason_code: ArchiveReasonCode | None = Query(default=None),
    query: str | None = Query(default=None),
    month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    limit: int = Query(default=100, ge=1, le=300),
    session: AsyncSession = Depends(get_session),
) -> list[ShipmentRecord]:
    """List archived shipments for the archive-only dashboard surface."""
    result = await session.execute(
        select(Shipment)
        .where(Shipment.is_archived.is_(True))
        .order_by(Shipment.archived_at.desc().nullslast(), Shipment.created_at.desc())
        .limit(500)
    )
    query_text = (query or "").strip().lower()
    rows: list[ShipmentRecord] = []
    for shipment in result.scalars().all():
        code = _shipment_archive_reason_code(shipment)
        if reason_code and code != reason_code.value:
            continue
        archived_reference = shipment.archived_at or shipment.updated_at or shipment.created_at
        if month and (archived_reference is None or archived_reference.strftime("%Y-%m") != month):
            continue
        if query_text:
            haystack = " ".join(
                [
                    shipment.origin or "",
                    shipment.destination or "",
                    shipment.quote_token or "",
                    str(shipment.email_thread_id or ""),
                    shipment.archived_reason or "",
                    _shipment_archive_reason_note(shipment) or "",
                    code,
                ]
            ).lower()
            if query_text not in haystack:
                continue
        record = _serialize_shipment(shipment)
        record.archive_reason_code = ArchiveReasonCode(code)
        record.archive_reason_note = _shipment_archive_reason_note(shipment)
        rows.append(record)
        if len(rows) >= limit:
            break
    return rows


@router.get("/freight/shipments/archive/by-token/{quote_token}", response_model=ShipmentRecord)
async def get_archived_shipment_by_token(
    quote_token: str,
    session: AsyncSession = Depends(get_session),
) -> ShipmentRecord:
    """Get an archived shipment by quote token."""
    normalized_token = quote_token.strip().upper()
    shipment = await session.scalar(
        select(Shipment).where(
            Shipment.is_archived.is_(True),
            func.upper(Shipment.quote_token) == normalized_token,
        )
    )
    if shipment is None:
        raise HTTPException(status_code=404, detail="Archived shipment not found.")
    return await _serialize_shipment_detail(session, shipment)


@router.get("/freight/shipments/archive/{shipment_id}", response_model=ShipmentRecord)
async def get_archived_shipment(
    shipment_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ShipmentRecord:
    """Get an archived shipment by id."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None or not shipment.is_archived:
        raise HTTPException(status_code=404, detail="Archived shipment not found.")
    return await _serialize_shipment_detail(session, shipment)


@router.get("/freight/shipments/{shipment_id}", response_model=ShipmentRecord)
async def get_shipment(
    shipment_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ShipmentRecord:
    """Get a shipment by id."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None or shipment.is_archived:
        raise HTTPException(status_code=404, detail="Shipment not found.")
    return await _serialize_shipment_detail(session, shipment)


@router.get("/freight/shipments/{shipment_id}/thread", response_model=ShipmentThreadResponse)
async def get_shipment_thread(
    shipment_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ShipmentThreadResponse:
    """Return the email thread transcript linked to a shipment."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise HTTPException(status_code=404, detail="Shipment not found.")
    if shipment.email_thread_id is None:
        return ShipmentThreadResponse(
            shipment_id=str(shipment.id),
            thread_id=None,
            thread_subject=None,
            quote_token=shipment.quote_token,
            messages=[],
        )

    thread = await session.get(EmailThread, shipment.email_thread_id)
    if thread is None:
        return ShipmentThreadResponse(
            shipment_id=str(shipment.id),
            thread_id=str(shipment.email_thread_id),
            thread_subject=None,
            quote_token=shipment.quote_token,
            messages=[],
        )

    result = await session.execute(
        select(EmailMessage)
        .where(EmailMessage.thread_id == shipment.email_thread_id)
        .order_by(EmailMessage.received_at.asc())
    )
    messages = [_serialize_thread_message(message) for message in result.scalars().all()]
    return ShipmentThreadResponse(
        shipment_id=str(shipment.id),
        thread_id=str(thread.id),
        thread_subject=thread.subject,
        quote_token=shipment.quote_token or thread.quote_token,
        messages=messages,
    )


@router.post("/freight/shipments/{shipment_id}/magic-fill", response_model=ShipmentMagicFillResponse)
async def magic_fill_shipment_field(
    shipment_id: UUID,
    request: ShipmentMagicFillRequest,
    session: AsyncSession = Depends(get_session),
) -> ShipmentMagicFillResponse:
    """Use AI to recover one shipment field from the linked customer thread."""
    logger.info("magic_fill.request shipment_id=%s field=%s apply_value=%s", shipment_id, request.field.value, request.apply_value)
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        logger.warning("magic_fill.shipment_not_found shipment_id=%s", shipment_id)
        raise HTTPException(status_code=404, detail="Shipment not found.")
    if shipment.is_archived:
        raise HTTPException(status_code=409, detail="Shipment is archived and cannot be edited.")
    if shipment.email_thread_id is None:
        logger.warning("magic_fill.no_thread shipment_id=%s", shipment_id)
        raise HTTPException(status_code=400, detail="Shipment has no linked email thread.")
    if shipment.client_id is None:
        logger.warning("magic_fill.no_client shipment_id=%s", shipment_id)
        raise HTTPException(status_code=400, detail="Shipment has no linked customer.")

    client = await session.get(Client, shipment.client_id)
    if client is None:
        logger.warning("magic_fill.linked_client_not_found shipment_id=%s client_id=%s", shipment_id, shipment.client_id)
        raise HTTPException(status_code=404, detail="Linked customer not found.")

    result = await session.execute(
        select(EmailMessage)
        .where(EmailMessage.thread_id == shipment.email_thread_id)
        .order_by(EmailMessage.received_at.asc())
    )
    all_messages = result.scalars().all()
    customer_messages = [message for message in all_messages if _message_touches_email(message, client.email)]
    logger.info(
        "magic_fill.thread_loaded shipment_id=%s total_messages=%s customer_messages=%s customer_email=%s",
        shipment_id,
        len(all_messages),
        len(customer_messages),
        client.email,
    )
    if not customer_messages:
        logger.warning("magic_fill.no_customer_messages shipment_id=%s thread_id=%s", shipment_id, shipment.email_thread_id)
        raise HTTPException(status_code=400, detail="No customer-facing messages found in the linked thread.")

    transcript = _build_magic_thread_transcript(customer_messages[-12:])
    logger.info(
        "magic_fill.transcript_ready shipment_id=%s transcript_messages=%s transcript_chars=%s",
        shipment_id,
        min(len(customer_messages), 12),
        len(transcript),
    )
    extraction = await extract_shipment_field_from_thread(
        request.field.value,
        {
            "origin": shipment.origin or "",
            "destination": shipment.destination or "",
            "quote_token": shipment.quote_token or "",
            "thread_subject": all_messages[-1].subject if all_messages else "",
            "customer_email": client.email,
            "thread_transcript": transcript,
        },
    )
    logger.info(
        "magic_fill.extraction shipment_id=%s field=%s confidence=%s value_local_text=%s ambiguity_reasons=%s",
        shipment_id,
        request.field.value,
        extraction.confidence,
        extraction.value_local_text,
        extraction.ambiguity_reasons,
    )

    suggested_local = _parse_magic_local_datetime(extraction.value_local_text)
    suggested_value_for_response = extraction.value_local_text
    used_full_extraction_fallback = False
    if suggested_local is None and request.field == ShipmentMagicField.READY_AT_LOCAL:
        fb_local = await _magic_fill_ready_fallback_from_full_extraction(
            shipment=shipment,
            client=client,
            customer_messages=customer_messages,
            all_messages=all_messages,
        )
        if fb_local is not None:
            suggested_local = fb_local
            suggested_value_for_response = fb_local.replace(microsecond=0).isoformat(sep="T")
            used_full_extraction_fallback = True
            logger.info(
                "magic_fill.full_extraction_fallback shipment_id=%s suggested_local=%s",
                shipment_id,
                suggested_value_for_response,
            )

    logger.info(
        "magic_fill.normalized shipment_id=%s field=%s suggested_local=%s",
        shipment_id,
        request.field.value,
        suggested_local.isoformat() if suggested_local else None,
    )
    if request.field == ShipmentMagicField.READY_AT_LOCAL and request.apply_value and suggested_local is not None:
        shipment.ready_at_local = suggested_local
        shipment.ready_at = None
        shipment.updated_at = datetime.now(timezone.utc)
        _normalize_shipment_schedule_fields(shipment)
        logger.info(
            "magic_fill.applying shipment_id=%s ready_at_local=%s ready_at_utc=%s timezone=%s",
            shipment_id,
            shipment.ready_at_local.isoformat() if shipment.ready_at_local else None,
            shipment.ready_at.isoformat() if shipment.ready_at else None,
            shipment.ready_at_timezone,
        )

        response_confidence = max(extraction.confidence, 0.85) if used_full_extraction_fallback else extraction.confidence
        evt = WorkflowEvent(
            shipment_id=shipment.id,
            event_type=WorkflowEventType.SHIPMENT_FIELDS_UPDATED.value,
            stage=shipment.status,
            payload_json={
                "changed_fields": ["ready_at", "ready_at_local", "ready_at_timezone", "ready_at_offset_minutes"],
                "edited_by": "magic_fill",
                "source": "customer_thread_ai",
                "field": request.field.value,
                "confidence": response_confidence,
                "suggested_value": suggested_value_for_response,
                "single_field_value_local_text": extraction.value_local_text,
                "full_extraction_fallback": used_full_extraction_fallback,
                "source_messages": len(customer_messages),
                "ambiguity_reasons": extraction.ambiguity_reasons,
            },
        )
        session.add(evt)
        await session.commit()
        await session.refresh(shipment)
        await freight_realtime_hub.notify_workflow_event(evt)
        logger.info("magic_fill.applied shipment_id=%s field=%s", shipment_id, request.field.value)
        applied_message = (
            "Pickup-ready time recovered from thread (full extraction) and applied."
            if used_full_extraction_fallback
            else "Pickup-ready time extracted from customer thread and applied to shipment."
        )
        return ShipmentMagicFillResponse(
            shipment_id=str(shipment.id),
            field=request.field,
            status="applied",
            message=applied_message,
            confidence=response_confidence,
            suggested_value=suggested_value_for_response,
            ambiguity_reasons=extraction.ambiguity_reasons,
            source_messages=len(customer_messages),
            shipment=_serialize_shipment(shipment),
        )

    status = "no_value"
    message = "AI could not confidently recover a pickup-ready time from the customer thread."
    if suggested_local is not None and not request.apply_value:
        status = "suggested"
        message = (
            "Pickup-ready time suggested via full thread extraction."
            if used_full_extraction_fallback
            else "Pickup-ready time extracted from customer thread."
        )
    logger.warning(
        "magic_fill.no_apply shipment_id=%s field=%s status=%s value_local_text=%s",
        shipment_id,
        request.field.value,
        status,
        extraction.value_local_text,
    )

    return ShipmentMagicFillResponse(
        shipment_id=str(shipment.id),
        field=request.field,
        status=status,
        message=message,
        confidence=max(extraction.confidence, 0.85) if used_full_extraction_fallback else extraction.confidence,
        suggested_value=suggested_value_for_response,
        ambiguity_reasons=extraction.ambiguity_reasons,
        source_messages=len(customer_messages),
        shipment=None,
    )


@router.patch("/freight/shipments/{shipment_id}", response_model=ShipmentRecord)
async def update_shipment(
    shipment_id: UUID,
    request: ShipmentUpsertRequest,
    session: AsyncSession = Depends(get_session),
) -> ShipmentRecord:
    """Update a shipment record."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise HTTPException(status_code=404, detail="Shipment not found.")
    if shipment.is_archived:
        raise HTTPException(status_code=409, detail="Shipment is archived and cannot be edited.")

    client_id = None
    if request.client_id:
        client_id = UUID(request.client_id)
        client = await session.get(Client, client_id)
        if client is None:
            raise HTTPException(status_code=404, detail="Client not found.")

    previous_values = {
        "client_id": str(shipment.client_id) if shipment.client_id else None,
        "status": shipment.status,
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

    shipment.client_id = client_id
    shipment.status = request.status.value
    shipment.origin = request.origin
    shipment.destination = request.destination
    shipment.pallets = request.pallets
    shipment.weight_lb = request.weight_lb
    shipment.equipment_type = request.equipment_type
    shipment.ready_at = request.ready_at if request.ready_at and request.ready_at.tzinfo else None
    shipment.ready_at_local = request.ready_at_local or (request.ready_at if request.ready_at and request.ready_at.tzinfo is None else None)
    shipment.delivery_at = request.delivery_at if request.delivery_at and request.delivery_at.tzinfo else None
    shipment.delivery_at_local = request.delivery_at_local or (request.delivery_at if request.delivery_at and request.delivery_at.tzinfo is None else None)
    shipment.margin_policy_json = request.margin_policy.model_dump() if request.margin_policy else {}
    shipment.notes = request.notes
    shipment.updated_at = datetime.now(timezone.utc)
    _normalize_shipment_schedule_fields(shipment)

    current_values = {
        "client_id": str(shipment.client_id) if shipment.client_id else None,
        "status": shipment.status,
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
        field
        for field, value in current_values.items()
        if previous_values.get(field) != value
    ]
    fields_evt: WorkflowEvent | None = None
    if changed_fields:
        fields_evt = WorkflowEvent(
            shipment_id=shipment.id,
            event_type=WorkflowEventType.SHIPMENT_FIELDS_UPDATED.value,
            stage=shipment.status,
            payload_json={
                "changed_fields": changed_fields,
                "manual_review_required": False,
                "edited_by": "operator",
            },
        )
        session.add(fields_evt)

    await session.commit()
    await session.refresh(shipment)
    if fields_evt is not None:
        await freight_realtime_hub.notify_workflow_event(fields_evt)
    else:
        await freight_realtime_hub.publish_shipment_updated(shipment_id=str(shipment.id))
    return _serialize_shipment(shipment)


@router.get("/freight/shipments/{shipment_id}/events", response_model=list[WorkflowEventRecord])
async def list_shipment_events(
    shipment_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> list[WorkflowEventRecord]:
    """Return workflow events for a shipment timeline."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise HTTPException(status_code=404, detail="Shipment not found.")

    result = await session.execute(
        select(WorkflowEvent)
        .where(WorkflowEvent.shipment_id == shipment_id)
        .order_by(WorkflowEvent.created_at.desc())
    )
    return [_serialize_workflow_event(event) for event in result.scalars().all()]


@router.get("/freight/notifications", response_model=NotificationFeedResponse)
async def freight_notifications(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> NotificationFeedResponse:
    """Paginated notification feed projected from workflow events."""
    return await list_notification_feed(session, limit=limit, offset=offset)


@router.get("/freight/reviews", response_model=list[ReviewQueueItem])
async def freight_review_queue(
    session: AsyncSession = Depends(get_session),
) -> list[ReviewQueueItem]:
    """Return shipments requiring operator review."""
    result = await session.execute(
        select(WorkflowEvent)
        .where(WorkflowEvent.event_type == WorkflowEventType.MANUAL_REVIEW_REQUIRED.value)
        .order_by(WorkflowEvent.created_at.desc())
        .limit(50)
    )
    review_events = list(result.scalars().all())
    shipment_ids = [event.shipment_id for event in review_events]
    shipments_by_id: dict[UUID, Shipment] = {}
    if shipment_ids:
        shipment_result = await session.execute(select(Shipment).where(Shipment.id.in_(shipment_ids)))
        shipments_by_id = {shipment.id: shipment for shipment in shipment_result.scalars().all()}
    status_payloads = await _latest_status_payloads(session, shipment_ids)
    items = [
        _serialize_review_queue_item(
            event,
            shipment=shipments_by_id.get(event.shipment_id),
            status_payload=status_payloads.get(event.shipment_id),
        )
        for event in review_events
        if (shipments_by_id.get(event.shipment_id) is not None and not shipments_by_id[event.shipment_id].is_archived)
    ]
    return sorted(items, key=_review_priority_score)


async def _serialize_email_triage_item(session: AsyncSession, item: EmailTriageItem) -> EmailTriageRecord:
    message = await session.get(EmailMessage, item.email_message_id)
    shipment = None
    if item.created_shipment_id:
        shipment = await session.get(Shipment, item.created_shipment_id)
    elif item.thread_id:
        shipment = await session.scalar(
            select(Shipment).where(Shipment.email_thread_id == item.thread_id).order_by(Shipment.created_at.desc())
        )
    return EmailTriageRecord(
        id=str(item.id),
        email_message_id=str(item.email_message_id),
        thread_id=str(item.thread_id),
        shipment_id=str(shipment.id) if shipment else None,
        classification=item.classification,
        confidence=float(item.confidence or 0),
        reason=item.reason,
        recommended_action=item.recommended_action,
        resolved_at=item.resolved_at,
        resolved_action=item.resolved_action,
        created_shipment_id=str(item.created_shipment_id) if item.created_shipment_id else None,
        sender=message.sender if message else None,
        subject=message.subject if message else None,
        body_preview=message.body_preview if message else None,
        received_at=message.received_at if message else None,
        payload=dict(item.payload_json or {}),
        created_at=item.created_at,
    )


@router.get("/freight/email-triage", response_model=list[EmailTriageRecord])
async def freight_email_triage_queue(
    include_resolved: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[EmailTriageRecord]:
    """Return pre-shipment email triage items for operator review."""
    query = select(EmailTriageItem).order_by(EmailTriageItem.created_at.desc()).limit(limit)
    if not include_resolved:
        query = query.where(EmailTriageItem.resolved_at.is_(None))
    result = await session.execute(query)
    return [await _serialize_email_triage_item(session, item) for item in result.scalars().all()]


@router.post("/freight/email-triage/{triage_id}/action", response_model=EmailTriageRecord)
async def freight_email_triage_action(
    triage_id: UUID,
    request: EmailTriageActionRequest,
    session: AsyncSession = Depends(get_session),
) -> EmailTriageRecord:
    """Resolve a triage item by creating/linking a shipment or marking it as non-shipment/fraud."""
    item = await session.get(EmailTriageItem, triage_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Email triage item not found.")
    message = await session.get(EmailMessage, item.email_message_id)
    thread = await session.get(EmailThread, item.thread_id)
    if message is None or thread is None:
        raise HTTPException(status_code=404, detail="Triage source email not found.")

    now = datetime.now(timezone.utc)
    shipment: Shipment | None = None
    if request.action == EmailTriageAction.CREATE_SHIPMENT:
        shipment = await session.scalar(
            select(Shipment).where(Shipment.email_thread_id == thread.id).order_by(Shipment.created_at.desc())
        )
        if shipment is None:
            thread.quote_token = thread.quote_token or generate_quote_reference().subject_token
            shipment = Shipment(
                email_thread_id=thread.id,
                status=ShipmentStage.RECEIVED.value,
                quote_token=thread.quote_token,
                margin_policy_json={
                    "percent": settings.profit_margin_percent_default,
                    "floor_amount": settings.profit_margin_floor_default,
                },
                notes=None,
            )
            session.add(shipment)
            await session.flush()
        item.created_shipment_id = shipment.id
        item.resolved_action = request.action.value
    elif request.action == EmailTriageAction.LINK_TO_EXISTING_SHIPMENT:
        if not request.shipment_id:
            raise HTTPException(status_code=400, detail="shipment_id is required to link triage email.")
        shipment = await session.get(Shipment, UUID(str(request.shipment_id)))
        if shipment is None:
            raise HTTPException(status_code=404, detail="Shipment not found.")
        shipment.email_thread_id = shipment.email_thread_id or thread.id
        item.created_shipment_id = shipment.id
        item.resolved_action = request.action.value
    elif request.action == EmailTriageAction.MARK_NOT_SHIPMENT:
        thread.shipment_ingest_suppressed = True
        thread.shipment_ingest_suppressed_reason = request.reason or "operator_marked_not_shipment"
        thread.shipment_ingest_suppressed_at = now
        item.resolved_action = request.action.value
    elif request.action in {EmailTriageAction.MARK_FRAUD_EMAIL, EmailTriageAction.MARK_FRAUD_DOMAIN}:
        sender_email = normalize_sender_email(message.sender)
        sender_value = sender_email if request.action == EmailTriageAction.MARK_FRAUD_EMAIL else extract_sender_domain(sender_email)
        scope = (
            FraudDenylistScope.SENDER_EMAIL
            if request.action == EmailTriageAction.MARK_FRAUD_EMAIL
            else FraudDenylistScope.SENDER_DOMAIN
        )
        await _upsert_fraud_denylist_entry(
            session,
            scope=scope,
            value=sender_value,
            reason=request.reason or "operator_triage_fraud",
            source_shipment_id=None,
        )
        thread.shipment_ingest_suppressed = True
        thread.shipment_ingest_suppressed_reason = f"fraud_triage:{scope.value}:{sender_value}"
        thread.shipment_ingest_suppressed_at = now
        item.classification = EmailTriageClassification.FRAUD_OR_PHISHING.value
        item.resolved_action = request.action.value
    else:
        raise HTTPException(status_code=400, detail="Unsupported triage action.")

    item.resolved_at = item.resolved_at or now
    item.updated_at = now
    await session.commit()
    return await _serialize_email_triage_item(session, item)


@router.get("/freight/status-queue", response_model=list[StatusQueueItem])
async def freight_status_queue(
    include_resolved: bool = Query(default=False),
    resolved_limit: int = Query(default=25, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[StatusQueueItem]:
    """Return active operator tasks for Phase 3 status workflows."""
    active_items = await _active_status_queue_items(session)
    if not include_resolved:
        return active_items
    resolved_items = await _resolved_status_queue_items(session, limit=resolved_limit)
    return [*active_items, *resolved_items]


@router.post("/freight/status-queue/{task_id}/action", response_model=StatusQueueActionResponse)
async def freight_status_queue_action(
    task_id: UUID,
    request: StatusQueueActionRequest,
    session: AsyncSession = Depends(get_session),
) -> StatusQueueActionResponse:
    """Run an operator action on a status queue task."""
    task_event = await session.get(WorkflowEvent, task_id)
    if task_event is None:
        raise HTTPException(status_code=404, detail="Status queue task not found.")
    shipment = await session.get(Shipment, task_event.shipment_id)
    if shipment is None:
        raise HTTPException(status_code=404, detail="Shipment not found.")

    payload = dict(task_event.payload_json or {})
    task_type = "status_reply" if task_event.event_type == WorkflowEventType.CUSTOMER_STATUS_SENT.value else "carrier_update"
    if task_event.event_type == WorkflowEventType.MANUAL_REVIEW_REQUIRED.value:
        task_type = _status_queue_task_type(str(payload.get("review_type"))) or task_type
    if task_event.event_type == WorkflowEventType.EXCEPTION_RAISED.value and payload.get("reason") in {"lookup_failed", "reply_send_failed"}:
        task_type = "status_reply"

    try:
        if request.action == StatusQueueAction.PREVIEW:
            preview = payload if task_event.event_type != WorkflowEventType.MANUAL_REVIEW_REQUIRED.value else dict(payload.get("structured_payload", {}) or {})
            return StatusQueueActionResponse(
                task_id=str(task_id),
                task_type=task_type,
                action=request.action,
                status="completed",
                message="Task preview ready.",
                task_state="preview",
                resolution_reason=None,
                shipment_id=str(shipment.id),
                preview=preview,
            )

        if request.action == StatusQueueAction.DISMISS:
            if await _is_task_already_resolved(
                session,
                shipment_id=shipment.id,
                task_type=task_type,
                resolution_state="dismissed",
                source_task_id=str(task_id),
            ):
                return StatusQueueActionResponse(
                    task_id=str(task_id),
                    task_type=task_type,
                    action=request.action,
                    status="already_completed",
                    message="Status task was already dismissed.",
                    task_state="dismissed",
                    resolution_state="dismissed",
                    resolution_reason="dismissed_by_operator",
                    shipment_id=str(shipment.id),
                )
            resolution_evt = _record_status_task_resolution(
                session,
                shipment=shipment,
                task_type=task_type,
                resolution_state="dismissed",
                resolution_reason="dismissed_by_operator",
                source_task_id=str(task_id),
            )
            await session.commit()
            await freight_realtime_hub.notify_workflow_event(resolution_evt)
            return StatusQueueActionResponse(
                task_id=str(task_id),
                task_type=task_type,
                action=request.action,
                status="completed",
                message="Status task dismissed.",
                task_state="dismissed",
                resolution_state="dismissed",
                resolution_reason="dismissed_by_operator",
                shipment_id=str(shipment.id),
            )

        if task_type == "status_reply":
            status_response = await fetch_tms_shipment_status(session, shipment_id=shipment.id)
            if request.action == StatusQueueAction.REBUILD_DRAFT:
                draft = await send_customer_status_reply(
                    session,
                    shipment_id=shipment.id,
                    status_payload=status_response.payload,
                    dry_run=True,
                    custom_message=request.custom_message,
                    subject_override=request.draft_subject,
                    body_override=request.draft_body,
                )
                return StatusQueueActionResponse(
                    task_id=str(task_id),
                    task_type=task_type,
                    action=request.action,
                    status="completed",
                    message="Status reply draft rebuilt.",
                    task_state="draft_ready",
                    resolution_reason=None,
                    shipment_id=str(shipment.id),
                    preview=draft.model_dump(),
                )
            if request.action == StatusQueueAction.APPROVE_AND_SEND:
                if await _is_task_already_resolved(
                    session,
                    shipment_id=shipment.id,
                    task_type=task_type,
                    resolution_state="sent",
                    source_task_id=str(task_id),
                ):
                    return StatusQueueActionResponse(
                        task_id=str(task_id),
                        task_type=task_type,
                        action=request.action,
                        status="already_completed",
                        message="Status reply was already sent for this task.",
                        task_state="sent",
                        resolution_state="sent",
                        resolution_reason="sent_to_customer",
                        shipment_id=str(shipment.id),
                    )
                reply = await send_customer_status_reply(
                    session,
                    shipment_id=shipment.id,
                    status_payload=status_response.payload,
                    dry_run=False,
                    custom_message=request.custom_message,
                    subject_override=request.draft_subject,
                    body_override=request.draft_body,
                )
                resolution_evt = _record_status_task_resolution(
                    session,
                    shipment=shipment,
                    task_type=task_type,
                    resolution_state="sent",
                    resolution_reason="sent_to_customer",
                    source_task_id=str(task_id),
                )
                await session.commit()
                await freight_realtime_hub.notify_workflow_event(resolution_evt)
                return StatusQueueActionResponse(
                    task_id=str(task_id),
                    task_type=task_type,
                    action=request.action,
                    status="completed",
                    message=f"Status reply sent to {reply.client_email}.",
                    task_state="sent",
                    resolution_state="sent",
                    resolution_reason="sent_to_customer",
                    shipment_id=str(shipment.id),
                    preview=reply.model_dump(),
                )

        if task_type == "carrier_update":
            preview_or_response = await preview_or_push_carrier_status_update(
                session,
                shipment_id=shipment.id,
                status_text=request.status_text or payload.get("status_text") or dict(payload.get("payload", {}) or {}).get("status_text"),
                eta_text=request.eta_text or payload.get("eta_text") or dict(payload.get("payload", {}) or {}).get("eta_text"),
                location_text=request.location_text or payload.get("location_text") or dict(payload.get("payload", {}) or {}).get("location_text"),
                notes=request.notes or payload.get("notes") or dict(payload.get("payload", {}) or {}).get("notes"),
                dry_run=request.action == StatusQueueAction.PREVIEW,
            )
            if request.action == StatusQueueAction.PREVIEW:
                return StatusQueueActionResponse(
                    task_id=str(task_id),
                    task_type=task_type,
                    action=request.action,
                    status="completed",
                    message="Carrier update preview ready.",
                    task_state="awaiting_review",
                    resolution_reason=None,
                    shipment_id=str(shipment.id),
                    preview=preview_or_response.model_dump(),
                )
            if request.action in {StatusQueueAction.APPROVE_AND_PUSH, StatusQueueAction.RETRY_PUSH}:
                if request.action == StatusQueueAction.APPROVE_AND_PUSH and await _is_task_already_resolved(
                    session,
                    shipment_id=shipment.id,
                    task_type=task_type,
                    resolution_state="pushed",
                    source_task_id=str(task_id),
                ):
                    return StatusQueueActionResponse(
                        task_id=str(task_id),
                        task_type=task_type,
                        action=request.action,
                        status="already_completed",
                        message="Carrier status update was already pushed for this task.",
                        task_state="pushed",
                        resolution_state="pushed",
                        resolution_reason="pushed_to_tms",
                        shipment_id=str(shipment.id),
                    )
                resolution_evt = _record_status_task_resolution(
                    session,
                    shipment=shipment,
                    task_type=task_type,
                    resolution_state="pushed",
                    resolution_reason="pushed_to_tms",
                    source_task_id=str(task_id),
                )
                await session.commit()
                await freight_realtime_hub.notify_workflow_event(resolution_evt)
                return StatusQueueActionResponse(
                    task_id=str(task_id),
                    task_type=task_type,
                    action=request.action,
                    status="completed",
                    message="Carrier status update pushed to TMS.",
                    task_state="pushed",
                    resolution_state="pushed",
                    resolution_reason="pushed_to_tms",
                    shipment_id=str(shipment.id),
                    preview=preview_or_response.model_dump(),
                )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    raise HTTPException(status_code=400, detail="Unsupported status queue action.")


@router.post("/freight/tms/status-event", response_model=TmsStatusIngestResponse)
async def freight_tms_status_event(
    request: TmsStatusIngestRequest,
    session: AsyncSession = Depends(get_session),
) -> TmsStatusIngestResponse:
    """Ingest an inbound TMS status event and reconcile it to a shipment."""
    shipment: Shipment | None = None
    if request.shipment_id:
        shipment = await session.get(Shipment, UUID(request.shipment_id))
    if shipment is None and request.quote_token:
        shipment = await session.scalar(select(Shipment).where(Shipment.quote_token == request.quote_token))
    if shipment is None and request.external_load_ref:
        shipment = await session.scalar(select(Shipment).where(Shipment.quote_token == request.external_load_ref))
    if shipment is None and request.tms_load_id:
        shipment_result = await session.execute(select(Shipment))
        for candidate in shipment_result.scalars().all():
            identity_payload = (await _latest_tms_identity_payloads(session, [candidate.id])).get(candidate.id) or {}
            if str(identity_payload.get("tms_load_id") or "") == request.tms_load_id:
                shipment = candidate
                break
    if shipment is None:
        raise HTTPException(status_code=404, detail="Shipment not found for inbound TMS status event.")

    existing_ingest_result = await session.execute(
        select(WorkflowEvent)
        .where(
            WorkflowEvent.shipment_id == shipment.id,
            WorkflowEvent.event_type == WorkflowEventType.TMS_STATUS_INGESTED.value,
        )
        .order_by(WorkflowEvent.created_at.desc())
    )
    for existing in existing_ingest_result.scalars().all():
        existing_payload = dict(existing.payload_json or {})
        if request.external_event_id and existing_payload.get("external_event_id") == request.external_event_id:
            return TmsStatusIngestResponse(
                shipment_id=str(shipment.id),
                status="already_processed",
                event_type=WorkflowEventType.TMS_STATUS_INGESTED.value,
                tms_load_id=request.tms_load_id,
            )
        comparable_existing = (
            existing_payload.get("tms_load_id"),
            existing_payload.get("status"),
            existing_payload.get("eta"),
            existing_payload.get("location"),
            existing_payload.get("milestone"),
            existing_payload.get("source_timestamp"),
        )
        comparable_incoming = (
            request.tms_load_id,
            request.status,
            request.eta,
            request.location,
            request.milestone,
            request.source_timestamp.isoformat() if request.source_timestamp else None,
        )
        if comparable_existing == comparable_incoming and any(comparable_incoming):
            return TmsStatusIngestResponse(
                shipment_id=str(shipment.id),
                status="already_processed",
                event_type=WorkflowEventType.TMS_STATUS_INGESTED.value,
                tms_load_id=request.tms_load_id,
            )

    ingest_evt = WorkflowEvent(
        shipment_id=shipment.id,
        event_type=WorkflowEventType.TMS_STATUS_INGESTED.value,
        stage=shipment.status,
        payload_json={
            "external_event_id": request.external_event_id,
            "tms_load_id": request.tms_load_id,
            "external_load_ref": request.external_load_ref,
            "tms_system": request.tms_system,
            "status": request.status,
            "eta": request.eta,
            "location": request.location,
            "milestone": request.milestone,
            "source_timestamp": request.source_timestamp.isoformat() if request.source_timestamp else None,
            "status_audit_kind": "tms_inbound_sync",
            "status_label": request.status or "Unknown",
            "eta_label": request.eta or "Not available",
            "location_label": request.location or "Not available",
            "milestone_label": request.milestone or "Not available",
            "status_source": "tms_inbound_sync",
            "payload": request.payload,
        },
    )
    session.add(ingest_evt)
    res_carrier = _record_status_task_resolution(
        session,
        shipment=shipment,
        task_type="carrier_update",
        resolution_state="resolved_no_push",
        resolution_reason="superseded_by_newer_snapshot",
        source="tms_inbound_sync",
    )
    res_status = _record_status_task_resolution(
        session,
        shipment=shipment,
        task_type="status_reply",
        resolution_state="resolved_no_send",
        resolution_reason="superseded_by_newer_snapshot",
        source="tms_inbound_sync",
    )
    await session.commit()
    await freight_realtime_hub.notify_workflow_events([ingest_evt, res_carrier, res_status])
    return TmsStatusIngestResponse(
        shipment_id=str(shipment.id),
        status="ingested",
        event_type=WorkflowEventType.TMS_STATUS_INGESTED.value,
        tms_load_id=request.tms_load_id,
    )


@router.post(
    "/freight/shipments/{shipment_id}/operator-action",
    response_model=ShipmentOperatorActionResponse,
)
async def freight_operator_action(
    shipment_id: UUID,
    request: ShipmentOperatorActionRequest,
    session: AsyncSession = Depends(get_session),
) -> ShipmentOperatorActionResponse:
    """Run an operator-approved Phase 1 action on a shipment."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise HTTPException(status_code=404, detail="Shipment not found.")

    if shipment.is_archived and request.action not in {OperatorAction.ARCHIVE_SHIPMENT, OperatorAction.MARK_SENDER_FRAUD}:
        raise HTTPException(status_code=409, detail="Shipment is archived and cannot continue active workflow actions.")

    policy = _build_automation_policy(
        auto_acknowledgement=True,
        acknowledgement_dry_run=False,
        auto_outreach=True,
        outreach_dry_run=False,
        auto_quote=True,
        quote_dry_run=False,
        auto_book=True,
        booking_dry_run=False,
    )

    try:
        if request.action in {OperatorAction.ARCHIVE_SHIPMENT, OperatorAction.MARK_SENDER_FRAUD}:
            denylist_entry: FraudDenylistEntry | None = None
            if request.action == OperatorAction.MARK_SENDER_FRAUD or (
                request.reason_code == ArchiveReasonCode.FRAUD and request.fraud_block_scope is not None
            ):
                inbound_sender = await _latest_inbound_sender_email_for_shipment(session, shipment)
                if not inbound_sender:
                    raise HTTPException(
                        status_code=409,
                        detail="No inbound sender is linked to this shipment, so a fraud denylist entry cannot be created.",
                    )
                block_scope = request.fraud_block_scope or FraudDenylistScope.SENDER_EMAIL
                denylist_value = (
                    extract_sender_domain(inbound_sender)
                    if block_scope == FraudDenylistScope.SENDER_DOMAIN
                    else normalize_sender_email(inbound_sender)
                )
                denylist_entry, created_denylist = await _upsert_fraud_denylist_entry(
                    session,
                    scope=block_scope,
                    value=denylist_value,
                    reason=request.reason_note or request.reason or "sender flagged as fraud by operator",
                    source_shipment_id=shipment.id,
                )
                fraud_evt = WorkflowEvent(
                    shipment_id=shipment.id,
                    event_type=WorkflowEventType.SENDER_FRAUD_MARKED.value,
                    stage=shipment.status,
                    payload_json={
                        "sender_email": inbound_sender,
                        "denylist_scope": denylist_entry.scope,
                        "denylist_value": denylist_entry.value,
                        "denylist_entry_id": str(denylist_entry.id),
                        "denylist_created": created_denylist,
                        "reason": request.reason_note or request.reason or "sender flagged as fraud by operator",
                    },
                )
                session.add(fraud_evt)

            archive_reason_code = request.reason_code or (
                ArchiveReasonCode.FRAUD if request.action == OperatorAction.MARK_SENDER_FRAUD else None
            )
            archive_reason_note = request.reason_note or (
                "sender flagged as fraud by operator" if request.action == OperatorAction.MARK_SENDER_FRAUD else None
            )
            shipment, thread = await _archive_shipment_and_optionally_suppress_source(
                session,
                shipment=shipment,
                reason=request.reason,
                reason_code=archive_reason_code,
                reason_note=archive_reason_note,
                suppress_source_thread=request.suppress_source_thread,
            )
            return ShipmentOperatorActionResponse(
                shipment_id=str(shipment.id),
                action=request.action,
                status="completed",
                message=(
                    "Sender fraud denylist entry saved. Shipment archived and source thread ignored."
                    if denylist_entry is not None
                    else "Shipment archived and source thread ignored for future sync."
                ),
                next_action="archived",
                archived=True,
                suppression_applied=bool(thread is not None and request.suppress_source_thread),
                suppressed_thread_id=str(thread.id) if thread is not None and request.suppress_source_thread else None,
                denylist_entry_id=str(denylist_entry.id) if denylist_entry is not None else None,
                denylist_scope=FraudDenylistScope(denylist_entry.scope) if denylist_entry is not None else None,
                denylist_value=denylist_entry.value if denylist_entry is not None else None,
            )

        if request.action == OperatorAction.VERIFY_SENDER:
            inbound_sender = await _latest_inbound_sender_email_for_shipment(session, shipment)
            if not inbound_sender:
                raise HTTPException(
                    status_code=409,
                    detail="No inbound customer message is linked to this shipment yet.",
                )
            sender_role = request.sender_identity_role
            if sender_role is None:
                sender_role = SenderIdentityRole.CUSTOMER if shipment.client_id else None
            if sender_role is None:
                raise HTTPException(
                    status_code=400,
                    detail="Choose whether this sender is a customer or a carrier before confirming trust.",
                )
            trust_scope = request.sender_trust_scope or SenderTrustScope.SENDER_EMAIL
            inbound_domain = extract_sender_domain(inbound_sender)
            client: Client | None = None
            carrier: Carrier | None = None
            contact_email = ""
            contact_domain = ""

            if sender_role == SenderIdentityRole.CUSTOMER:
                client_id = UUID(request.client_id) if request.client_id else shipment.client_id
                if client_id is None:
                    raise HTTPException(status_code=400, detail="Select or create a customer before confirming sender trust.")
                client = await session.get(Client, client_id)
                if client is None:
                    raise HTTPException(status_code=404, detail="Selected customer record was not found.")
                contact_email = (client.email or "").strip().lower()
                contact_domain = extract_sender_domain(contact_email)
                shipment.client_id = client.id
            elif sender_role == SenderIdentityRole.CARRIER:
                if not request.carrier_id:
                    raise HTTPException(status_code=400, detail="Select or create a carrier before confirming sender trust.")
                carrier = await session.get(Carrier, UUID(request.carrier_id))
                if carrier is None:
                    raise HTTPException(status_code=404, detail="Selected carrier record was not found.")
                contact_email = (carrier.email or "").strip().lower()
                contact_domain = extract_sender_domain(contact_email)
            else:
                raise HTTPException(status_code=400, detail="Unsupported sender identity role.")

            if trust_scope == SenderTrustScope.SENDER_EMAIL and contact_email != inbound_sender:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Contact email must exactly match the inbound sender address for email trust. "
                        f"Selected contact uses {contact_email!r}; latest inbound sender is {inbound_sender!r}."
                    ),
                )
            if trust_scope == SenderTrustScope.SENDER_DOMAIN and (not contact_domain or contact_domain != inbound_domain):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Contact domain must match the inbound sender domain for domain trust. "
                        f"Selected contact domain is {contact_domain!r}; latest inbound sender domain is {inbound_domain!r}."
                    ),
                )
            verify_evt = WorkflowEvent(
                shipment_id=shipment.id,
                event_type=WorkflowEventType.SENDER_VERIFIED.value,
                stage=shipment.status,
                payload_json={
                    "sender_email": inbound_sender,
                    "sender_domain": inbound_domain,
                    "sender_role": sender_role.value,
                    "trust_scope": trust_scope.value,
                    "client_id": str(client.id) if client is not None else None,
                    "client_name": client.name if client is not None else None,
                    "carrier_id": str(carrier.id) if carrier is not None else None,
                    "carrier_name": carrier.name if carrier is not None else None,
                    "contact_email": contact_email,
                    "contact_domain": contact_domain,
                },
            )
            session.add(verify_evt)
            shipment.updated_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(shipment)
            await freight_realtime_hub.notify_workflow_event(verify_evt)
            decision = await continue_phase1_workflow(session, shipment_id=shipment.id, policy=policy)
            return ShipmentOperatorActionResponse(
                shipment_id=str(shipment.id),
                action=request.action,
                status="completed",
                message=(
                    f"Sender trust confirmed for this {trust_scope.value.replace('sender_', '')} "
                    f"as {sender_role.value}. Workflow continued."
                ),
                next_action=decision.next_action,
                manual_review_required=decision.manual_review_required,
                acknowledgement_sent=decision.acknowledgement_drafted,
                outreach_sent=decision.outreach_drafted,
                evaluation_triggered=decision.evaluation_triggered,
                quote_sent=decision.quote_auto_sent,
                sender_identity_role=sender_role,
                sender_trust_scope=trust_scope,
                verified_sender_email=inbound_sender,
                verified_sender_domain=inbound_domain,
                verified_client_id=str(client.id) if client is not None else None,
                verified_carrier_id=str(carrier.id) if carrier is not None else None,
                decision=decision,
            )

        if request.action in {OperatorAction.RESUME_WORKFLOW, OperatorAction.APPROVE_AND_CONTINUE}:
            decision = await continue_phase1_workflow(session, shipment_id=shipment.id, policy=policy)
            return ShipmentOperatorActionResponse(
                shipment_id=str(shipment.id),
                action=request.action,
                status="completed",
                message="Workflow continued from current state.",
                next_action=decision.next_action,
                manual_review_required=decision.manual_review_required,
                acknowledgement_sent=decision.acknowledgement_drafted,
                outreach_sent=decision.outreach_drafted,
                evaluation_triggered=decision.evaluation_triggered,
                quote_sent=decision.quote_auto_sent,
                decision=decision,
            )

        if request.action == OperatorAction.REQUEST_CUSTOMER_DETAILS:
            if await customer_clarification_already_requested(session, shipment):
                return ShipmentOperatorActionResponse(
                    shipment_id=str(shipment.id),
                    action=request.action,
                    status="already_done",
                    message="Customer details were already requested for this shipment.",
                    next_action="waiting_customer_details",
                )
            missing_fields = await _latest_missing_fields_for_shipment(session, shipment)
            sent = await send_customer_clarification(
                session,
                shipment_id=shipment.id,
                missing_fields=missing_fields,
            )
            return ShipmentOperatorActionResponse(
                shipment_id=str(shipment.id),
                action=request.action,
                status="completed" if sent else "already_done",
                message=(
                    "Requested additional details from the customer."
                    if sent
                    else "Customer details were already requested for this shipment."
                ),
                next_action="waiting_customer_details",
            )

        if request.action == OperatorAction.RERUN_PARSING:
            latest_message = await _latest_inbound_message_for_shipment(session, shipment)
            if latest_message is None:
                raise RuntimeError("No inbound email available to re-run parsing.")
            logger.warning(
                "shipment_operator.rerun_parsing shipment_id=%s email_message_id=%s provider_message_id=%s subject=%s body_preview=%s",
                shipment.id,
                latest_message.id,
                latest_message.provider_message_id,
                latest_message.subject,
                (latest_message.body_preview or "")[:1200],
            )
            decision = await run_freight_inbox_orchestrator(
                session,
                email_message_id=latest_message.id,
                policy=policy,
            )
            return ShipmentOperatorActionResponse(
                shipment_id=str(shipment.id),
                action=request.action,
                status="completed",
                message="Parsing and decisioning re-run on the latest inbound email.",
                next_action=decision.next_action,
                manual_review_required=decision.manual_review_required,
                acknowledgement_sent=decision.acknowledgement_drafted,
                outreach_sent=decision.outreach_drafted,
                evaluation_triggered=decision.evaluation_triggered,
                quote_sent=decision.quote_auto_sent,
                decision=decision,
            )

        if request.action == OperatorAction.RERUN_OUTREACH:
            response = await create_carrier_outreach(
                session,
                shipment_id=shipment.id,
                carrier_ids=[],
                dry_run=False,
                custom_message=None,
            )
            return ShipmentOperatorActionResponse(
                shipment_id=str(shipment.id),
                action=request.action,
                status="completed",
                message=f"Carrier outreach refreshed; {response.created_bids} new request(s) created across {response.targeted} carrier(s).",
                next_action="waiting_bids",
                outreach_sent=response.created_bids > 0,
            )

        if request.action == OperatorAction.RERUN_EVALUATION:
            evaluation = await evaluate_shipment_bids(session, shipment.id)
            quote_response = await send_customer_quote(
                session,
                shipment_id=shipment.id,
                bid_id=evaluation.selected_bid_id,
                dry_run=False,
                custom_message=None,
            )
            return ShipmentOperatorActionResponse(
                shipment_id=str(shipment.id),
                action=request.action,
                status="completed",
                message=f"Evaluation re-run and customer quote sent at ${quote_response.final_amount:.2f}.",
                next_action="customer_quote_sent",
                evaluation_triggered=True,
                quote_sent=True,
            )

        if request.action == OperatorAction.RERUN_STATUS_LOOKUP:
            status_response = await fetch_tms_shipment_status(session, shipment_id=shipment.id)
            return ShipmentOperatorActionResponse(
                shipment_id=str(shipment.id),
                action=request.action,
                status="completed",
                message=(
                    f"Status refreshed from TMS: {status_response.status.replace('_', ' ')}"
                    if status_response.status
                    else "Status refreshed from TMS."
                ),
                next_action="status_lookup_completed",
                decision=WorkflowDecisionResult(
                    email_message_id="",
                    shipment_id=str(shipment.id),
                    intent="operator_status_lookup",
                    confidence=1.0,
                    next_action="status_lookup_completed",
                    status_lookup_triggered=True,
                ),
            )

        if request.action == OperatorAction.RERUN_TMS_UPDATE:
            latest_status_update = await session.scalar(
                select(WorkflowEvent)
                .where(
                    WorkflowEvent.shipment_id == shipment.id,
                    WorkflowEvent.event_type == WorkflowEventType.TMS_STATUS_UPDATED.value,
                )
                .order_by(WorkflowEvent.created_at.desc())
            )
            if latest_status_update is None:
                raise RuntimeError("No carrier status update payload is available to replay.")
            update_payload = dict((latest_status_update.payload_json or {}).get("payload", {}) or {})
            status_response = await push_carrier_status_to_tms(
                session,
                shipment_id=shipment.id,
                status_text=update_payload.get("status_text"),
                eta_text=update_payload.get("eta_text"),
                location_text=update_payload.get("location_text"),
                notes=update_payload.get("notes"),
            )
            return ShipmentOperatorActionResponse(
                shipment_id=str(shipment.id),
                action=request.action,
                status="completed",
                message="Carrier status update re-sent to TMS.",
                next_action="tms_status_updated",
                decision=WorkflowDecisionResult(
                    email_message_id="",
                    shipment_id=str(shipment.id),
                    intent="operator_tms_status_update",
                    confidence=1.0,
                    next_action="tms_status_updated",
                    tms_status_updated=True,
                    tms_handoff_status=status_response.status,
                ),
            )

        if request.action == OperatorAction.APPROVE_STATUS_REPLY:
            status_response = await fetch_tms_shipment_status(session, shipment_id=shipment.id)
            reply = await send_customer_status_reply(
                session,
                shipment_id=shipment.id,
                status_payload=status_response.payload,
                dry_run=False,
                custom_message=None,
            )
            return ShipmentOperatorActionResponse(
                shipment_id=str(shipment.id),
                action=request.action,
                status="completed",
                message=f"Approved and sent status reply to {reply.client_email}.",
                next_action="customer_status_sent",
                decision=WorkflowDecisionResult(
                    email_message_id="",
                    shipment_id=str(shipment.id),
                    intent="operator_status_reply",
                    confidence=1.0,
                    next_action="customer_status_sent",
                    status_lookup_triggered=True,
                    status_reply_sent=True,
                ),
            )

        if request.action == OperatorAction.RERUN_DOCUMENT_EXTRACTION:
            _attachments, document_health, document_context = await _collect_document_state(
                session,
                shipment,
                force_reprocess=True,
            )
            doc_events = _persist_document_analysis_events(
                session,
                shipment,
                document_health=document_health,
                document_context=document_context,
            )
            await session.commit()
            await freight_realtime_hub.notify_workflow_events(doc_events)
            return ShipmentOperatorActionResponse(
                shipment_id=str(shipment.id),
                action=request.action,
                status="completed",
                message=(
                    f"Document extraction re-run for {document_health.get('attachment_count', 0)} attachment(s); "
                    f"health is {str(document_health.get('document_health_status') or 'unknown').replace('_', ' ')}."
                ),
                next_action="document_analysis_completed",
                manual_review_required=bool(document_health.get("review_required", False)),
            )

        if request.action == OperatorAction.APPROVE_DOCUMENT_VALUES:
            _attachments, document_health, document_context = await _collect_document_state(session, shipment)
            approved_fields = dict(document_health.get("document_enrichment", {}) or {})
            approve_evt = WorkflowEvent(
                shipment_id=shipment.id,
                event_type=WorkflowEventType.DOCUMENT_VALUES_APPROVED.value,
                stage=shipment.status,
                payload_json={
                    "approved_fields": approved_fields,
                    "document_health_status": document_health.get("document_health_status"),
                },
            )
            session.add(approve_evt)
            doc_events = _persist_document_analysis_events(
                session,
                shipment,
                document_health=build_document_health(
                    _attachments,
                    shipment,
                    approved_fields=approved_fields,
                    warning_ignored=bool(document_health.get("warning_ignored", False)),
                ),
                document_context=document_context,
            )
            await session.commit()
            await freight_realtime_hub.notify_workflow_events([approve_evt, *doc_events])
            return ShipmentOperatorActionResponse(
                shipment_id=str(shipment.id),
                action=request.action,
                status="completed",
                message=(
                    f"Approved {len(approved_fields)} document-derived value(s) for shipment enrichment."
                    if approved_fields
                    else "Document review marked approved; no extracted enrichment values were available."
                ),
                next_action="document_values_approved",
                manual_review_required=False,
            )

        if request.action == OperatorAction.IGNORE_DOCUMENT_WARNING:
            _attachments, document_health, document_context = await _collect_document_state(session, shipment)
            ignore_evt = WorkflowEvent(
                shipment_id=shipment.id,
                event_type=WorkflowEventType.DOCUMENT_WARNING_IGNORED.value,
                stage=shipment.status,
                payload_json={
                    "ignored_warning": document_health.get("booking_review_warning"),
                    "document_health_status": document_health.get("document_health_status"),
                },
            )
            session.add(ignore_evt)
            doc_events = _persist_document_analysis_events(
                session,
                shipment,
                document_health=build_document_health(
                    _attachments,
                    shipment,
                    approved_fields=dict(document_health.get("document_enrichment", {}) or {}),
                    warning_ignored=True,
                ),
                document_context=document_context,
            )
            await session.commit()
            await freight_realtime_hub.notify_workflow_events([ignore_evt, *doc_events])
            return ShipmentOperatorActionResponse(
                shipment_id=str(shipment.id),
                action=request.action,
                status="completed",
                message="Document warning ignored for this shipment; workflow can continue with operator override.",
                next_action="document_warning_ignored",
                manual_review_required=False,
            )
    except HTTPException:
        raise
    except RuntimeError as exc:
        logger.exception(
            "shipment_operator.action_failed shipment_id=%s action=%s",
            shipment.id,
            request.action,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "shipment_operator.action_failed shipment_id=%s action=%s",
            shipment.id,
            request.action,
        )
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc

    raise HTTPException(status_code=400, detail="Unsupported operator action.")


@router.post(
    "/freight/shipments/{shipment_id}/archive",
    response_model=ShipmentOperatorActionResponse,
)
async def archive_shipment(
    shipment_id: UUID,
    request: ShipmentArchiveRequest,
    session: AsyncSession = Depends(get_session),
) -> ShipmentOperatorActionResponse:
    return await freight_operator_action(
        shipment_id,
        ShipmentOperatorActionRequest(
            action=OperatorAction.ARCHIVE_SHIPMENT,
            reason_code=request.reason_code,
            reason_note=request.reason_note,
            suppress_source_thread=request.suppress_source_thread,
            fraud_block_scope=request.fraud_block_scope,
        ),
        session,
    )


@router.get("/freight/shipments/{shipment_id}/bids", response_model=list[BidRecord])
async def list_shipment_bids(
    shipment_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> list[BidRecord]:
    """Return all bids for a shipment."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise HTTPException(status_code=404, detail="Shipment not found.")

    result = await session.execute(
        select(CarrierBid, Carrier)
        .join(Carrier, Carrier.id == CarrierBid.carrier_id)
        .where(CarrierBid.shipment_id == shipment_id)
        .order_by(CarrierBid.received_at.desc())
    )
    return [_serialize_bid_record(bid, carrier) for bid, carrier in result.all()]


@router.get("/freight/shipments/{shipment_id}/documents", response_model=list[ShipmentDocumentRecord])
async def list_shipment_documents(
    shipment_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> list[ShipmentDocumentRecord]:
    """Return typed document metadata collected from the shipment email thread."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise HTTPException(status_code=404, detail="Shipment not found.")
    documents = await collect_shipment_attachments(session, shipment)
    return [_serialize_document_record(document) for document in documents]


@router.post(
    "/freight/shipments/{shipment_id}/documents/reprocess",
    response_model=ShipmentOperatorActionResponse,
)
async def reprocess_shipment_documents(
    shipment_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ShipmentOperatorActionResponse:
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise HTTPException(status_code=404, detail="Shipment not found.")
    return await freight_operator_action(
        shipment_id,
        ShipmentOperatorActionRequest(action=OperatorAction.RERUN_DOCUMENT_EXTRACTION),
        session,
    )


@router.post(
    "/freight/shipments/{shipment_id}/documents/approve",
    response_model=ShipmentOperatorActionResponse,
)
async def approve_shipment_documents(
    shipment_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ShipmentOperatorActionResponse:
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise HTTPException(status_code=404, detail="Shipment not found.")
    return await freight_operator_action(
        shipment_id,
        ShipmentOperatorActionRequest(action=OperatorAction.APPROVE_DOCUMENT_VALUES),
        session,
    )


@router.post(
    "/freight/shipments/{shipment_id}/documents/ignore-warning",
    response_model=ShipmentOperatorActionResponse,
)
async def ignore_shipment_document_warning(
    shipment_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ShipmentOperatorActionResponse:
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise HTTPException(status_code=404, detail="Shipment not found.")
    return await freight_operator_action(
        shipment_id,
        ShipmentOperatorActionRequest(action=OperatorAction.IGNORE_DOCUMENT_WARNING),
        session,
    )


@router.post(
    "/freight/shipments/{shipment_id}/outreach",
    response_model=CarrierOutreachResponse,
)
async def shipment_carrier_outreach(
    shipment_id: UUID,
    request: CarrierOutreachRequest,
    session: AsyncSession = Depends(get_session),
) -> CarrierOutreachResponse:
    """Create and optionally send anonymized outreach to carriers for a shipment."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise HTTPException(status_code=404, detail="Shipment not found.")

    try:
        return await create_carrier_outreach(
            session,
            shipment_id=shipment_id,
            carrier_ids=request.carrier_ids,
            dry_run=request.dry_run,
            custom_message=request.custom_message,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/freight/shipments/{shipment_id}/carrier-followup",
    response_model=CarrierFollowupResponse,
)
async def shipment_carrier_followup(
    shipment_id: UUID,
    request: CarrierFollowupRequest,
    session: AsyncSession = Depends(get_session),
) -> CarrierFollowupResponse:
    """Send a follow-up to one carrier, replying in-thread after first contact."""
    try:
        return await send_carrier_followup(
            session,
            shipment_id=shipment_id,
            carrier_id=request.carrier_id,
            carrier_email=request.carrier_email,
            dry_run=request.dry_run,
            subject=request.subject,
            message=request.message,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/freight/bids/intake", response_model=BidIntakeResponse)
async def freight_bid_intake(
    request: BidIntakeRequest,
    session: AsyncSession = Depends(get_session),
) -> BidIntakeResponse:
    """Intake a bid from a carrier reply or manual operator entry."""
    try:
        return await intake_bid(session, request)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/freight/shipments/{shipment_id}/evaluate",
    response_model=ShipmentEvaluationResponse,
)
async def freight_evaluate_shipment(
    shipment_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ShipmentEvaluationResponse:
    """Evaluate received bids and recommend the best option."""
    try:
        return await evaluate_shipment_bids(session, shipment_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/freight/shipments/{shipment_id}/acknowledge",
    response_model=ClientAcknowledgementResponse,
)
async def freight_client_acknowledgement(
    shipment_id: UUID,
    request: ClientAcknowledgementRequest,
    session: AsyncSession = Depends(get_session),
) -> ClientAcknowledgementResponse:
    """Build or send the initial acknowledgement back to the customer."""
    try:
        return await send_client_acknowledgement(
            session,
            shipment_id=shipment_id,
            dry_run=request.dry_run,
            custom_message=request.custom_message,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/freight/shipments/{shipment_id}/quote",
    response_model=CustomerQuoteResponse,
)
async def freight_customer_quote(
    shipment_id: UUID,
    request: CustomerQuoteRequest,
    session: AsyncSession = Depends(get_session),
) -> CustomerQuoteResponse:
    """Send or preview the customer quote based on the selected bid."""
    try:
        return await send_customer_quote(
            session,
            shipment_id=shipment_id,
            bid_id=request.bid_id,
            dry_run=request.dry_run,
            custom_message=request.custom_message,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/freight/shipments/{shipment_id}/status-reply",
    response_model=CustomerStatusReplyResponse,
)
async def freight_customer_status_reply(
    shipment_id: UUID,
    request: CustomerStatusReplyRequest,
    session: AsyncSession = Depends(get_session),
) -> CustomerStatusReplyResponse:
    """Build or send a customer-facing shipment status reply from current TMS status."""
    try:
        status_response = await fetch_tms_shipment_status(session, shipment_id=shipment_id)
        return await send_customer_status_reply(
            session,
            shipment_id=shipment_id,
            status_payload=status_response.payload,
            dry_run=request.dry_run,
            custom_message=request.custom_message,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/freight/shipments/{shipment_id}/carrier-status-update",
    response_model=CarrierStatusUpdateResponse,
)
async def freight_carrier_status_update(
    shipment_id: UUID,
    request: CarrierStatusUpdateRequest,
    session: AsyncSession = Depends(get_session),
) -> CarrierStatusUpdateResponse:
    """Preview or send a structured carrier status update into the TMS."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise HTTPException(status_code=404, detail="Shipment not found.")
    try:
        latest_carrier_message = await _latest_carrier_message_for_shipment(session, shipment)
        parsed_status_text = request.status_text
        parsed_eta_text = request.eta_text
        parsed_location_text = request.location_text
        parsed_notes = request.notes

        if latest_carrier_message is not None:
            extraction = await extract_carrier_status_update(
                {
                    "sender_email": latest_carrier_message.sender,
                    "sender_role": "carrier",
                    "subject": latest_carrier_message.subject,
                    "body_preview": latest_carrier_message.body_preview,
                    "thread_subject": latest_carrier_message.subject,
                    "shipment_status": shipment.status,
                    "known_client": "",
                    "known_carrier": latest_carrier_message.sender,
                }
            )
            parsed_status_text = parsed_status_text or extraction.status_text
            parsed_eta_text = parsed_eta_text or extraction.eta_text
            parsed_location_text = parsed_location_text or extraction.location_text
            parsed_notes = parsed_notes or extraction.notes

        return await preview_or_push_carrier_status_update(
            session,
            shipment_id=shipment_id,
            status_text=parsed_status_text,
            eta_text=parsed_eta_text,
            location_text=parsed_location_text,
            notes=parsed_notes,
            dry_run=request.dry_run,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/freight/shipments/{shipment_id}/tms-handoff",
    response_model=TmsHandoffResponse,
)
async def freight_tms_handoff(
    shipment_id: UUID,
    request: TmsHandoffRequest,
    session: AsyncSession = Depends(get_session),
) -> TmsHandoffResponse:
    """Preview or submit the selected shipment to the TMS."""
    try:
        return await handoff_to_tms(
            session,
            shipment_id=shipment_id,
            bid_id=request.bid_id,
            dry_run=request.dry_run,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/freight/shipments/{shipment_id}/book",
    response_model=BookingExecutionResponse,
)
async def freight_book_shipment(
    shipment_id: UUID,
    request: TmsHandoffRequest,
    session: AsyncSession = Depends(get_session),
) -> BookingExecutionResponse:
    """Confirm booking, submit to TMS, and send customer booking confirmation."""
    try:
        handoff, confirmation = await confirm_booking_and_handoff(
            session,
            shipment_id=shipment_id,
            bid_id=request.bid_id,
            dry_run=request.dry_run,
            custom_message=None,
        )
        return BookingExecutionResponse(
            shipment_id=str(shipment_id),
            dry_run=request.dry_run,
            handoff=handoff,
            confirmation=confirmation,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/freight/reference-preview")
async def freight_reference_preview(subject: str = "New quote request") -> dict:
    """Preview deterministic quote reference generation and subject correlation."""
    reference = generate_quote_reference()
    final_subject = f"{subject.strip()} [{reference.subject_token}]"
    signals = build_correlation_signals(subject=final_subject)
    return {
        "reference": reference.model_dump(),
        "subject": final_subject,
        "signals": signals.model_dump(),
    }


@router.get("/freight/overview", response_model=FreightOverviewResponse)
async def freight_overview(
    session: AsyncSession = Depends(get_session),
) -> FreightOverviewResponse:
    """Return current freight data footprint and shipment stage distribution."""
    return await build_freight_overview(session)


def _financial_margin_amount(base_amount: float, margin_policy: dict) -> tuple[float, float]:
    percent = float(margin_policy.get("percent", settings.profit_margin_percent_default) or 0)
    floor_amount = float(margin_policy.get("floor_amount", settings.profit_margin_floor_default) or 0)
    margin_amount = round(max(base_amount * (percent / 100), floor_amount), 2)
    margin_percent = round((margin_amount / base_amount) * 100, 1) if base_amount > 0 else 0
    return margin_amount, margin_percent


@router.get("/freight/financial-summary", response_model=FreightFinancialSummaryResponse)
async def freight_financial_summary(
    month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    session: AsyncSession = Depends(get_session),
) -> FreightFinancialSummaryResponse:
    """Return bid-backed financial projections for the active shipment board."""
    shipment_conditions = [Shipment.is_archived.is_(False)]
    if month:
        year, month_number = (int(part) for part in month.split("-"))
        month_start = datetime(year, month_number, 1, tzinfo=timezone.utc)
        if month_number == 12:
            month_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            month_end = datetime(year, month_number + 1, 1, tzinfo=timezone.utc)
        shipment_conditions.extend([Shipment.created_at >= month_start, Shipment.created_at < month_end])

    shipment_result = await session.execute(
        select(Shipment.id, Shipment.margin_policy_json)
        .where(*shipment_conditions)
        .order_by(Shipment.updated_at.desc(), Shipment.created_at.desc())
    )
    shipments = shipment_result.all()
    if not shipments:
        return FreightFinancialSummaryResponse()

    shipment_ids = [shipment_id for shipment_id, _margin_policy in shipments]
    priced_amount = case((CarrierBid.amount > 0, CarrierBid.amount), else_=None)
    selected_amount = case(((CarrierBid.status == "selected") & (CarrierBid.amount > 0), CarrierBid.amount), else_=None)
    bid_summary_result = await session.execute(
        select(
            CarrierBid.shipment_id,
            func.count(CarrierBid.id).label("bid_count"),
            func.count(priced_amount).label("priced_bid_count"),
            func.min(priced_amount).label("best_bid_amount"),
            func.max(selected_amount).label("selected_bid_amount"),
        )
        .where(CarrierBid.shipment_id.in_(shipment_ids))
        .group_by(CarrierBid.shipment_id)
    )
    bid_summaries = {
        row.shipment_id: {
            "bid_count": int(row.bid_count or 0),
            "priced_bid_count": int(row.priced_bid_count or 0),
            "best_bid_amount": float(row.best_bid_amount) if row.best_bid_amount is not None else None,
            "selected_bid_amount": float(row.selected_bid_amount) if row.selected_bid_amount is not None else None,
        }
        for row in bid_summary_result.all()
    }

    summaries: list[FreightFinancialShipmentSummary] = []
    for shipment_id, margin_policy in shipments:
        bid_summary = bid_summaries.get(shipment_id, {})
        best_bid_amount = bid_summary.get("best_bid_amount")
        selected_bid_amount = bid_summary.get("selected_bid_amount")
        quote_source_amount = selected_bid_amount or best_bid_amount
        margin_amount = 0.0
        margin_percent = 0.0
        recommended_quote_amount = None
        selected_quote_amount = None
        if quote_source_amount:
            margin_amount, margin_percent = _financial_margin_amount(
                float(quote_source_amount),
                dict(margin_policy or {}),
            )
            recommended_quote_amount = round(float(quote_source_amount) + margin_amount, 2)
        if selected_bid_amount:
            selected_margin, _selected_margin_percent = _financial_margin_amount(
                float(selected_bid_amount),
                dict(margin_policy or {}),
            )
            selected_quote_amount = round(float(selected_bid_amount) + selected_margin, 2)

        summaries.append(
            FreightFinancialShipmentSummary(
                shipment_id=str(shipment_id),
                best_bid_amount=best_bid_amount,
                best_bid_id=None,
                bid_count=int(bid_summary.get("bid_count") or 0),
                priced_bid_count=int(bid_summary.get("priced_bid_count") or 0),
                margin_amount=margin_amount,
                margin_percent=margin_percent,
                recommended_quote_amount=recommended_quote_amount,
                selected_bid_amount=selected_bid_amount,
                selected_quote_amount=selected_quote_amount,
                currency="USD",
            )
        )

    return FreightFinancialSummaryResponse(shipments=summaries)


@router.post("/freight/outlook/ingest", response_model=OutlookSyncResponse)
async def freight_outlook_ingest(
    request: OutlookIngestRequest,
    session: AsyncSession = Depends(get_session),
) -> OutlookSyncResponse:
    """Normalize a provided Outlook message payload into freight workflow tables."""
    policy = _build_automation_policy(
        auto_acknowledgement=request.auto_acknowledge_new_shipment,
        acknowledgement_dry_run=request.acknowledgement_dry_run,
        auto_outreach=request.auto_prepare_outreach_for_new_shipment,
        outreach_dry_run=request.outreach_dry_run,
        auto_quote=request.auto_send_customer_quote,
        quote_dry_run=request.customer_quote_dry_run,
        auto_book=request.auto_book_on_confirmation,
        booking_dry_run=request.booking_dry_run,
    )
    client = OutlookGraphClient()
    mailbox_message = client.normalize_message(request.message)
    result = await _process_outlook_mailbox_message(
        session,
        mailbox_message=mailbox_message,
        policy=policy,
        create_client_if_missing=request.create_client_if_missing,
    )
    if result is None:
        return OutlookSyncResponse(imported=0, skipped=1, results=[])
    expired = await evaluate_expired_quote_windows(session, policy=policy)

    return OutlookSyncResponse(
        imported=1,
        skipped=0,
        parsed_shipments=1 if result.shipment_extracted else 0,
        auto_acknowledgements=1 if result.acknowledgement_drafted else 0,
        auto_outreach=1 if result.outreach_drafted else 0,
        auto_bids=1 if result.bid_intaken else 0,
        auto_evaluations=len(expired) + (1 if result.evaluation_triggered else 0),
        auto_quotes=len([item for item in expired if item.quote_auto_sent]) + (1 if result.quote_auto_sent else 0),
        auto_status_replies=1 if result.status_reply_sent else 0,
        auto_tms_status_updates=1 if result.tms_status_updated else 0,
        manual_reviews=1 if result.manual_review_required else 0,
        results=[result],
    )


@router.post("/freight/outlook/sync", response_model=OutlookSyncResponse)
async def freight_outlook_sync(
    request: OutlookSyncRequest,
    session: AsyncSession = Depends(get_session),
) -> OutlookSyncResponse:
    """Pull recent Outlook inbox messages and ingest them into workflow tables."""
    policy = _build_automation_policy(
        auto_acknowledgement=request.auto_acknowledge_new_shipments,
        acknowledgement_dry_run=request.acknowledgement_dry_run,
        auto_outreach=request.auto_prepare_outreach_for_new_shipments,
        outreach_dry_run=request.outreach_dry_run,
        auto_quote=request.auto_send_customer_quotes,
        quote_dry_run=request.customer_quote_dry_run,
        auto_book=request.auto_book_on_confirmation,
        booking_dry_run=request.booking_dry_run,
    )
    outlook = OutlookGraphClient()
    try:
        messages = await outlook.list_messages(limit=request.limit)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    imported = 0
    skipped = 0
    parsed_shipments = 0
    auto_acknowledgements = 0
    auto_outreach = 0
    auto_bids = 0
    auto_evaluations = 0
    auto_quotes = 0
    auto_status_replies = 0
    auto_tms_status_updates = 0
    manual_reviews = 0
    results = []
    for message in messages:
        result = await _process_outlook_mailbox_message(
            session,
            mailbox_message=message,
            policy=policy,
        )
        if result is None:
            skipped += 1
            continue
        imported += 1
        parsed_shipments += 1 if result.shipment_extracted else 0
        auto_acknowledgements += 1 if result.acknowledgement_drafted else 0
        auto_outreach += 1 if result.outreach_drafted else 0
        auto_bids += 1 if result.bid_intaken else 0
        auto_evaluations += 1 if result.evaluation_triggered else 0
        auto_quotes += 1 if result.quote_auto_sent else 0
        auto_status_replies += 1 if result.status_reply_sent else 0
        auto_tms_status_updates += 1 if result.tms_status_updated else 0
        manual_reviews += 1 if result.manual_review_required else 0
        results.append(result)

    expired = await evaluate_expired_quote_windows(session, policy=policy)
    auto_evaluations += len(expired)
    auto_quotes += len([item for item in expired if item.quote_auto_sent])

    return OutlookSyncResponse(
        imported=imported,
        skipped=skipped,
        parsed_shipments=parsed_shipments,
        auto_acknowledgements=auto_acknowledgements,
        auto_outreach=auto_outreach,
        auto_bids=auto_bids,
        auto_evaluations=auto_evaluations,
        auto_quotes=auto_quotes,
        auto_status_replies=auto_status_replies,
        auto_tms_status_updates=auto_tms_status_updates,
        manual_reviews=manual_reviews,
        results=results,
    )


@router.get("/freight/outlook/webhook/status", response_model=OutlookWebhookStatusResponse)
async def freight_outlook_webhook_status() -> OutlookWebhookStatusResponse:
    """Report whether the configured Outlook webhook subscription exists and is active."""
    outlook = OutlookGraphClient()
    if not outlook.webhook_is_configured():
        return _outlook_webhook_status_response(outlook=outlook, subscriptions=[])
    try:
        subscriptions = await outlook.list_subscriptions()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _outlook_webhook_status_response(outlook=outlook, subscriptions=subscriptions)


@router.post("/freight/outlook/webhook/ensure", response_model=OutlookWebhookStatusResponse)
async def freight_outlook_webhook_ensure() -> OutlookWebhookStatusResponse:
    """Create or renew the configured Outlook webhook subscription."""
    outlook = OutlookGraphClient()
    try:
        subscription = await outlook.ensure_inbox_webhook_subscription()
        subscriptions = await outlook.list_subscriptions()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    action = str(subscription.get("subscriptionAction") or "ensured")
    return _outlook_webhook_status_response(
        outlook=outlook,
        subscriptions=subscriptions,
        subscription_action=action,
    )


@router.post("/freight/outlook/webhook", response_model=OutlookWebhookResponse)
async def freight_outlook_webhook(
    http_request: Request,
    validationToken: str | None = None,
) -> Response:
    """Receive Outlook/Graph mailbox events and automatically run inbox orchestration."""
    validation_token = validationToken or http_request.query_params.get("validationToken")
    if validation_token:
        return Response(content=validation_token, media_type="text/plain")

    raw_body = await http_request.body()
    payload = await http_request.json() if raw_body else {}
    request = OutlookWebhookRequest.model_validate(payload) if payload else None

    async with async_session() as session:
        policy = _default_outlook_event_policy()
        outlook = OutlookGraphClient()

        imported = 0
        skipped = 0
        ignored = 0
        manual_reviews = 0
        results: list[OutlookIngestResult] = []

        notifications = request.value if request else []
        for notification in notifications:
            client_state = settings.microsoft_webhook_client_state
            if client_state and notification.clientState and notification.clientState != client_state:
                ignored += 1
                continue
            if notification.changeType and "created" not in notification.changeType.lower():
                ignored += 1
                continue

            resource_data = notification.resourceData or {}
            message_id = resource_data.get("id")
            if not message_id and notification.resource:
                message_id = str(notification.resource).rstrip("/").split("/")[-1]
            if not message_id:
                ignored += 1
                continue

            try:
                mailbox_message = await outlook.get_message(str(message_id))
            except RuntimeError:
                ignored += 1
                continue

            result = await _process_outlook_mailbox_message(
                session,
                mailbox_message=mailbox_message,
                policy=policy,
            )
            if result is None:
                skipped += 1
                continue
            imported += 1
            manual_reviews += 1 if result.manual_review_required else 0
            results.append(result)

        expired = await evaluate_expired_quote_windows(session, policy=policy)
        for item in expired:
            if item.manual_review_required:
                manual_reviews += 1

        return OutlookWebhookResponse(
            accepted=True,
            imported=imported,
            skipped=skipped,
            ignored=ignored,
            manual_reviews=manual_reviews,
            results=results,
        )
