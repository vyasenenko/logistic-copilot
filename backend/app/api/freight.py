"""Freight workflow foundation endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
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
    CarrierUpsertRequest,
    ClientAcknowledgementRequest,
    ClientAcknowledgementResponse,
    ClientRecord,
    ClientUpsertRequest,
    CustomerQuoteRequest,
    CustomerQuoteResponse,
    FreightFoundationResponse,
    OutlookIngestRequest,
    OutlookSyncRequest,
    OutlookSyncResponse,
    OperatorAction,
    FreightOverviewCounts,
    FreightOverviewResponse,
    MarginPolicy,
    ShipmentEvaluationResponse,
    ShipmentRecord,
    ShipmentUpsertRequest,
    ShipmentStage,
    ReviewQueueItem,
    ShipmentOperatorActionRequest,
    ShipmentOperatorActionResponse,
    ShipmentDocumentRecord,
    TmsHandoffRequest,
    TmsHandoffResponse,
    WorkflowEventRecord,
    WorkflowDecisionResult,
    WorkflowEventType,
)
from app.services.freight_execution import (
    collect_shipment_attachments,
    confirm_booking_and_handoff,
    evaluate_shipment_bids,
    handoff_to_tms,
    intake_bid,
    send_client_acknowledgement,
    send_customer_quote,
)
from app.services.email_correlation import build_correlation_signals, generate_quote_reference
from app.services.freight_inbox_agent import (
    continue_phase1_workflow,
    evaluate_expired_quote_windows,
    run_freight_inbox_orchestrator,
)
from app.services.freight_outreach import create_carrier_outreach
from app.services.mailbox_sync import ingest_outlook_message
from app.services.outlook import OutlookGraphClient

router = APIRouter()


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
        manual_review_required=bool(ai_payload.get("manual_review_required", False)),
        created_at=shipment.created_at,
        updated_at=shipment.updated_at,
    )


def _serialize_workflow_event(event: WorkflowEvent) -> WorkflowEventRecord:
    return WorkflowEventRecord(
        id=str(event.id),
        shipment_id=str(event.shipment_id),
        event_type=event.event_type,
        stage=event.stage,
        payload=dict(event.payload_json or {}),
        created_at=event.created_at,
    )


def _serialize_review_queue_item(event: WorkflowEvent) -> ReviewQueueItem:
    return ReviewQueueItem(
        workflow_event_id=str(event.id),
        shipment_id=str(event.shipment_id),
        stage=event.stage,
        event_type=event.event_type,
        reason=str((event.payload_json or {}).get("reason", "")),
        next_action=(event.payload_json or {}).get("next_action"),
        missing_fields=list((event.payload_json or {}).get("missing_fields", []) or []),
        ambiguity_reasons=list((event.payload_json or {}).get("ambiguity_reasons", []) or []),
        created_at=event.created_at,
    )


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
            }
        elif event.event_type == WorkflowEventType.EXCEPTION_RAISED.value and payload.get("reason") == "tms_handoff_failed":
            payloads[event.shipment_id] = {
                "booking_state": "booking_failed",
                "tms_handoff_status": "failed",
                "booking_error": payload.get("message"),
                "attachment_count": 0,
            }
        elif event.event_type == WorkflowEventType.CUSTOMER_CONFIRMED.value:
            payloads[event.shipment_id] = {
                "booking_state": "booking_ready",
                "tms_handoff_status": None,
                "booking_error": None,
                "attachment_count": 0,
            }
    return payloads


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
    attachment_counts = await _attachment_counts(session, shipments)
    return [
        _serialize_shipment(
            shipment,
            {
                **(ai_payloads.get(shipment.id) or {}),
                **(booking_payloads.get(shipment.id) or {}),
                "attachment_count": attachment_counts.get(shipment.id, 0),
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
    attachment_counts = await _attachment_counts(session, [shipment])
    return _serialize_shipment(
        shipment,
        {
            **(ai_payloads.get(shipment.id) or {}),
            **(booking_payloads.get(shipment.id) or {}),
            "attachment_count": attachment_counts.get(shipment.id, 0),
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
    return [_serialize_review_queue_item(event) for event in result.scalars().all()]


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

    return FreightOverviewResponse(
        counts=counts,
        active_stages=active_stages,
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
    result = await ingest_outlook_message(
        session,
        mailbox_message,
        create_client_if_missing=request.create_client_if_missing,
    )
    if result is None:
        return OutlookSyncResponse(imported=0, skipped=1, results=[])

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
    messages = await outlook.list_messages(limit=request.limit)

    imported = 0
    skipped = 0
    parsed_shipments = 0
    auto_acknowledgements = 0
    auto_outreach = 0
    auto_bids = 0
    auto_evaluations = 0
    auto_quotes = 0
    manual_reviews = 0
    results = []
    for message in messages:
        result = await ingest_outlook_message(session, message)
        if result is None:
            skipped += 1
            continue

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
        else:
            result.next_action = "already_ingested"
        imported += 1
        parsed_shipments += 1 if result.shipment_extracted else 0
        auto_acknowledgements += 1 if result.acknowledgement_drafted else 0
        auto_outreach += 1 if result.outreach_drafted else 0
        auto_bids += 1 if result.bid_intaken else 0
        auto_evaluations += 1 if result.evaluation_triggered else 0
        auto_quotes += 1 if result.quote_auto_sent else 0
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
        manual_reviews=manual_reviews,
        results=results,
    )
