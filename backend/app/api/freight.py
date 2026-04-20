"""Freight workflow foundation endpoints."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
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
    async_session,
    get_session,
)
from app.schemas import (
    AutomationPolicy,
    BidIntakeRequest,
    BidIntakeResponse,
    BidRecord,
    BookingExecutionResponse,
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
    OutlookIngestRequest,
    OutlookIngestResult,
    OutlookSyncRequest,
    OutlookSyncResponse,
    OutlookWebhookRequest,
    OutlookWebhookResponse,
    OperatorAction,
    FreightOverviewCounts,
    FreightStatusMetrics,
    FreightSlaSummary,
    FreightOverviewResponse,
    MarginPolicy,
    ShipmentEvaluationResponse,
    ShipmentRecord,
    ShipmentUpsertRequest,
    ShipmentStage,
    ReviewQueueItem,
    StatusQueueAction,
    StatusQueueActionRequest,
    StatusQueueActionResponse,
    StatusQueueItem,
    ShipmentOperatorActionRequest,
    ShipmentOperatorActionResponse,
    ShipmentDocumentRecord,
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
from app.services.freight_inbox_agent import (
    continue_phase1_workflow,
    evaluate_expired_quote_windows,
    run_freight_inbox_orchestrator,
)
from app.services.freight_ai import extract_carrier_status_update
from app.services.location_timezone import (
    apply_shipment_ready_at_wall_fields,
    infer_shipment_timezone,
    offset_minutes_for_local_naive,
)
from app.services.freight_outreach import create_carrier_outreach
from app.services.mailbox_sync import ingest_outlook_message
from app.services.outlook import OutlookGraphClient

router = APIRouter()


STATUS_ACTIVE_SHIPMENT_STATES = {
    ShipmentStage.BOOKED.value,
    ShipmentStage.BOOKING_IN_PROGRESS.value,
    ShipmentStage.AWAITING_CONFIRMATION.value,
}


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

    if result.created_message:
        try:
            decision = await run_freight_inbox_orchestrator(
                session,
                email_message_id=result.email_message_id,
                policy=policy,
            )
            _apply_decision(result, decision)
        except RuntimeError:
            result.manual_review_required = True
            result.next_action = "manual_review"
            result.intent = "orchestrator_error"
            result.confidence = 0.0
            result.missing_fields = []
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


def _serialize_shipment(shipment: Shipment, ai_payload: dict | None = None) -> ShipmentRecord:
    ai_payload = ai_payload or {}
    inferred_timezone = infer_shipment_timezone(shipment.origin, shipment.destination)
    timezone_name = shipment.ready_at_timezone or inferred_timezone
    ready_offset = (
        shipment.ready_at_offset_minutes
        if shipment.ready_at_offset_minutes is not None
        else (
            offset_minutes_for_local_naive(timezone_name, shipment.ready_at)
            if timezone_name and shipment.ready_at is not None
            else None
        )
    )
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
        ready_at=shipment.ready_at,
        ready_at_timezone=timezone_name,
        ready_at_offset_minutes=ready_offset,
        margin_policy=dict(shipment.margin_policy_json or {}),
        notes=shipment.notes,
        ai_intent=ai_payload.get("intent"),
        ai_confidence=ai_payload.get("confidence"),
        ai_missing_fields=list(ai_payload.get("missing_fields", []) or []),
        ai_ambiguity_reasons=list(ai_payload.get("ambiguity_reasons", []) or []),
        ai_next_action=ai_payload.get("next_action"),
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
        status_review_required=bool(ai_payload.get("status_review_required", False)),
        status_stale=bool(ai_payload.get("status_stale", False)),
        status_sla_hours=ai_payload.get("status_sla_hours"),
        manual_review_required=bool(ai_payload.get("manual_review_required", False)),
        created_at=shipment.created_at,
        updated_at=shipment.updated_at,
    )


def _normalize_shipment_ready_at_timezone_fields(shipment: Shipment) -> None:
    """Persist naive local ready_at plus IANA zone and offset metadata (no shifting wall-clock time)."""
    wall, tz, off = apply_shipment_ready_at_wall_fields(
        ready_at=shipment.ready_at,
        origin=shipment.origin,
        destination=shipment.destination,
    )
    shipment.ready_at = wall
    shipment.ready_at_timezone = tz
    shipment.ready_at_offset_minutes = off


def _serialize_workflow_event(event: WorkflowEvent) -> WorkflowEventRecord:
    return WorkflowEventRecord(
        id=str(event.id),
        shipment_id=str(event.shipment_id),
        event_type=event.event_type,
        stage=event.stage,
        payload=dict(event.payload_json or {}),
        created_at=event.created_at,
    )


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
            WorkflowEvent.event_type == WorkflowEventType.MANUAL_REVIEW_REQUIRED.value,
        )
        .order_by(WorkflowEvent.created_at.desc())
    )
    payloads: dict[UUID, dict] = {}
    for event in result.scalars().all():
        if event.shipment_id in payloads:
            continue
        payload = dict(event.payload_json or {})
        review_type = str(payload.get("review_type") or "")
        if "status" not in review_type:
            continue
        payloads[event.shipment_id] = {
            "status_review_required": True,
            "manual_review_required": True,
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


def _status_event_cutoff(*, now: datetime) -> datetime:
    return now - timedelta(hours=settings.status_sla_hours_default)


def _is_status_stale(
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


async def _status_metrics_summary(session: AsyncSession) -> FreightStatusMetrics:
    result = await session.execute(
        select(WorkflowEvent.event_type, WorkflowEvent.payload_json, WorkflowEvent.created_at, Shipment.id, Shipment.status)
        .join(Shipment, Shipment.id == WorkflowEvent.shipment_id)
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

    shipment_result = await session.execute(select(Shipment.id, Shipment.status))
    for shipment_id, shipment_status in shipment_result.all():
        if _is_status_stale(
            shipment_status=shipment_status,
            last_status_event_at=latest_status_event_at.get(shipment_id),
            now=now,
        ):
            metrics.stale_shipments += 1

    return metrics


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


async def _record_status_task_resolution(
    session: AsyncSession,
    *,
    shipment: Shipment,
    task_type: str,
    resolution_state: str,
    resolution_reason: str,
    source_task_id: str | None = None,
    source: str | None = None,
) -> None:
    session.add(
        WorkflowEvent(
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
    )


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
    task_type: str | None = None
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
        task_type = "status_reply"
        task_state = "draft_ready"
        draft_subject = payload.get("subject")
        draft_body = payload.get("body")
        structured_payload = {"custom_message": payload.get("custom_message")}
        alert_label = "Reply draft ready"
        recommended_next_action = "approve_and_send"
    elif event.event_type == WorkflowEventType.TMS_STATUS_UPDATED.value and payload.get("status_audit_kind") == "carrier_update_parsed":
        task_type = "carrier_update"
        task_state = "awaiting_review"
        structured_payload = dict(payload.get("payload", {}) or {})
        alert_label = "Carrier update review"
        recommended_next_action = "approve_and_push"
    elif event.event_type == WorkflowEventType.MANUAL_REVIEW_REQUIRED.value and "status" in str(review_type or ""):
        task_type = _status_queue_task_type(str(review_type))
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


async def _persist_document_analysis_events(
    session: AsyncSession,
    shipment: Shipment,
    *,
    document_health: dict,
    document_context: dict,
    event_type: WorkflowEventType = WorkflowEventType.DOCUMENT_ANALYZED,
) -> None:
    session.add(
        WorkflowEvent(
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
    )
    if document_health.get("review_required"):
        session.add(
            WorkflowEvent(
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
        )


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
    return _serialize_carrier(carrier)


@router.get("/freight/shipments", response_model=list[ShipmentRecord])
async def list_shipments(session: AsyncSession = Depends(get_session)) -> list[ShipmentRecord]:
    """List all tracked shipments."""
    result = await session.execute(select(Shipment).order_by(Shipment.created_at.desc()))
    shipments = list(result.scalars().all())
    ai_payloads = await _latest_ai_payloads(session, [shipment.id for shipment in shipments])
    booking_payloads = await _latest_booking_payloads(session, [shipment.id for shipment in shipments])
    status_payloads = await _latest_status_payloads(session, [shipment.id for shipment in shipments])
    status_review_payloads = await _latest_status_review_payloads(session, [shipment.id for shipment in shipments])
    tms_identity_payloads = await _latest_tms_identity_payloads(session, [shipment.id for shipment in shipments])
    status_workflow_payloads = await _status_workflow_payloads(session, [shipment.id for shipment in shipments])
    document_action_payloads = await _latest_document_action_payloads(session, [shipment.id for shipment in shipments])
    attachment_counts = await _attachment_counts(session, shipments)
    document_summaries = await _document_booking_summaries(session, shipments, document_action_payloads)
    now = datetime.now(timezone.utc)
    return [
        _serialize_shipment(
            shipment,
            {
                **(ai_payloads.get(shipment.id) or {}),
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
            },
        )
        for shipment in shipments
    ]


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
        ready_at=request.ready_at,
        margin_policy_json=(request.margin_policy.model_dump() if request.margin_policy else {}),
        notes=request.notes,
    )
    _normalize_shipment_ready_at_timezone_fields(shipment)
    session.add(shipment)
    await session.commit()
    await session.refresh(shipment)
    return _serialize_shipment(shipment)


@router.get("/freight/shipments/{shipment_id}", response_model=ShipmentRecord)
async def get_shipment(
    shipment_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ShipmentRecord:
    """Get a shipment by id."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise HTTPException(status_code=404, detail="Shipment not found.")
    ai_payloads = await _latest_ai_payloads(session, [shipment.id])
    booking_payloads = await _latest_booking_payloads(session, [shipment.id])
    status_payloads = await _latest_status_payloads(session, [shipment.id])
    status_review_payloads = await _latest_status_review_payloads(session, [shipment.id])
    tms_identity_payloads = await _latest_tms_identity_payloads(session, [shipment.id])
    status_workflow_payloads = await _status_workflow_payloads(session, [shipment.id])
    document_action_payloads = await _latest_document_action_payloads(session, [shipment.id])
    attachment_counts = await _attachment_counts(session, [shipment])
    document_summaries = await _document_booking_summaries(session, [shipment], document_action_payloads)
    now = datetime.now(timezone.utc)
    return _serialize_shipment(
        shipment,
        {
            **(ai_payloads.get(shipment.id) or {}),
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
        },
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
        "notes": shipment.notes,
    }

    shipment.client_id = client_id
    shipment.status = request.status.value
    shipment.origin = request.origin
    shipment.destination = request.destination
    shipment.pallets = request.pallets
    shipment.weight_lb = request.weight_lb
    shipment.equipment_type = request.equipment_type
    shipment.ready_at = request.ready_at
    shipment.margin_policy_json = request.margin_policy.model_dump() if request.margin_policy else {}
    shipment.notes = request.notes
    shipment.updated_at = datetime.now(timezone.utc)
    _normalize_shipment_ready_at_timezone_fields(shipment)

    current_values = {
        "client_id": str(shipment.client_id) if shipment.client_id else None,
        "status": shipment.status,
        "origin": shipment.origin,
        "destination": shipment.destination,
        "pallets": shipment.pallets,
        "weight_lb": shipment.weight_lb,
        "equipment_type": shipment.equipment_type,
        "ready_at": shipment.ready_at.isoformat() if shipment.ready_at else None,
        "notes": shipment.notes,
    }
    changed_fields = [
        field
        for field, value in current_values.items()
        if previous_values.get(field) != value
    ]
    if changed_fields:
        session.add(
            WorkflowEvent(
                shipment_id=shipment.id,
                event_type=WorkflowEventType.SHIPMENT_FIELDS_UPDATED.value,
                stage=shipment.status,
                payload_json={
                    "changed_fields": changed_fields,
                    "manual_review_required": False,
                    "edited_by": "operator",
                },
            )
        )

    await session.commit()
    await session.refresh(shipment)
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
    ]
    return sorted(items, key=_review_priority_score)


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
            await _record_status_task_resolution(
                session,
                shipment=shipment,
                task_type=task_type,
                resolution_state="dismissed",
                resolution_reason="dismissed_by_operator",
                source_task_id=str(task_id),
            )
            await session.commit()
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
                await _record_status_task_resolution(
                    session,
                    shipment=shipment,
                    task_type=task_type,
                    resolution_state="sent",
                    resolution_reason="sent_to_customer",
                    source_task_id=str(task_id),
                )
                await session.commit()
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
                await _record_status_task_resolution(
                    session,
                    shipment=shipment,
                    task_type=task_type,
                    resolution_state="pushed",
                    resolution_reason="pushed_to_tms",
                    source_task_id=str(task_id),
                )
                await session.commit()
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

    session.add(
        WorkflowEvent(
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
    )
    await _record_status_task_resolution(
        session,
        shipment=shipment,
        task_type="carrier_update",
        resolution_state="resolved_no_push",
        resolution_reason="superseded_by_newer_snapshot",
        source="tms_inbound_sync",
    )
    await _record_status_task_resolution(
        session,
        shipment=shipment,
        task_type="status_reply",
        resolution_state="resolved_no_send",
        resolution_reason="superseded_by_newer_snapshot",
        source="tms_inbound_sync",
    )
    await session.commit()
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

        if request.action == OperatorAction.RERUN_PARSING:
            latest_message = await _latest_inbound_message_for_shipment(session, shipment)
            if latest_message is None:
                raise RuntimeError("No inbound email available to re-run parsing.")
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
            await _persist_document_analysis_events(
                session,
                shipment,
                document_health=document_health,
                document_context=document_context,
            )
            await session.commit()
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
            session.add(
                WorkflowEvent(
                    shipment_id=shipment.id,
                    event_type=WorkflowEventType.DOCUMENT_VALUES_APPROVED.value,
                    stage=shipment.status,
                    payload_json={
                        "approved_fields": approved_fields,
                        "document_health_status": document_health.get("document_health_status"),
                    },
                )
            )
            await _persist_document_analysis_events(
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
            session.add(
                WorkflowEvent(
                    shipment_id=shipment.id,
                    event_type=WorkflowEventType.DOCUMENT_WARNING_IGNORED.value,
                    stage=shipment.status,
                    payload_json={
                        "ignored_warning": document_health.get("booking_review_warning"),
                        "document_health_status": document_health.get("document_health_status"),
                    },
                )
            )
            await _persist_document_analysis_events(
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
            return ShipmentOperatorActionResponse(
                shipment_id=str(shipment.id),
                action=request.action,
                status="completed",
                message="Document warning ignored for this shipment; workflow can continue with operator override.",
                next_action="document_warning_ignored",
                manual_review_required=False,
            )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    raise HTTPException(status_code=400, detail="Unsupported operator action.")


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
    counts = FreightOverviewCounts(
        clients=await session.scalar(select(func.count()).select_from(Client)) or 0,
        carriers=await session.scalar(select(func.count()).select_from(Carrier)) or 0,
        email_threads=await session.scalar(select(func.count()).select_from(EmailThread)) or 0,
        email_messages=await session.scalar(select(func.count()).select_from(EmailMessage)) or 0,
        shipments=await session.scalar(select(func.count()).select_from(Shipment)) or 0,
        bids=await session.scalar(select(func.count()).select_from(CarrierBid)) or 0,
        workflow_events=await session.scalar(select(func.count()).select_from(WorkflowEvent)) or 0,
    )

    result = await session.execute(
        select(Shipment.status, func.count(Shipment.id))
        .group_by(Shipment.status)
        .order_by(Shipment.status)
    )
    active_stages = {str(status): total for status, total in result.all()}
    status_metrics = await _status_metrics_summary(session)

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
