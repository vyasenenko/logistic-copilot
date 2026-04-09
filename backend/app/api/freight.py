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
    CarrierOutreachRequest,
    CarrierOutreachResponse,
    CarrierRecord,
    CarrierUpsertRequest,
    ClientRecord,
    ClientUpsertRequest,
    FreightFoundationResponse,
    OutlookIngestRequest,
    OutlookSyncRequest,
    OutlookSyncResponse,
    FreightOverviewCounts,
    FreightOverviewResponse,
    MarginPolicy,
    ShipmentRecord,
    ShipmentUpsertRequest,
    ShipmentStage,
    WorkflowEventRecord,
    WorkflowEventType,
)
from app.services.email_correlation import build_correlation_signals, generate_quote_reference
from app.services.freight_outreach import create_carrier_outreach
from app.services.mailbox_sync import ingest_outlook_message
from app.services.outlook import OutlookGraphClient

router = APIRouter()


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


def _serialize_shipment(shipment: Shipment) -> ShipmentRecord:
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
    return [_serialize_shipment(shipment) for shipment in result.scalars().all()]


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
    return _serialize_shipment(shipment)


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
    client = OutlookGraphClient()
    mailbox_message = client.normalize_message(request.message)
    result = await ingest_outlook_message(
        session,
        mailbox_message,
        create_client_if_missing=request.create_client_if_missing,
    )
    if result is None:
        return OutlookSyncResponse(imported=0, skipped=1, results=[])
    return OutlookSyncResponse(imported=1, skipped=0, results=[result])


@router.post("/freight/outlook/sync", response_model=OutlookSyncResponse)
async def freight_outlook_sync(
    request: OutlookSyncRequest,
    session: AsyncSession = Depends(get_session),
) -> OutlookSyncResponse:
    """Pull recent Outlook inbox messages and ingest them into workflow tables."""
    outlook = OutlookGraphClient()
    messages = await outlook.list_messages(limit=request.limit)

    imported = 0
    skipped = 0
    results = []
    for message in messages:
        result = await ingest_outlook_message(session, message)
        if result is None:
            skipped += 1
            continue
        imported += 1
        results.append(result)

    return OutlookSyncResponse(imported=imported, skipped=skipped, results=results)