"""Mailbox ingestion helpers for Outlook-first freight workflow."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.memory.database import Carrier, Client, EmailMessage, EmailThread, Shipment, WorkflowEvent
from app.schemas import OutlookIngestResult, ShipmentStage, WorkflowEventType
from app.services.email_correlation import build_correlation_signals, generate_quote_reference
from app.services.freight_realtime import freight_realtime_hub
from app.services.outlook import OutlookMailboxMessage


def _display_name_from_email(email: str) -> str:
    local_part = email.split("@", 1)[0]
    return local_part.replace(".", " ").replace("_", " ").title() or email


async def _find_or_create_thread(
    session: AsyncSession,
    *,
    mailbox_message: OutlookMailboxMessage,
    quote_token: str | None,
) -> tuple[EmailThread, bool]:
    signals = build_correlation_signals(
        subject=mailbox_message.subject,
        sender=mailbox_message.sender_email,
        internet_message_id=mailbox_message.internet_message_id,
        conversation_id=mailbox_message.conversation_id,
    )

    thread = None
    if mailbox_message.conversation_id:
        thread = await session.scalar(
            select(EmailThread).where(
                EmailThread.provider_thread_id == mailbox_message.conversation_id
            )
        )

    if thread is None and quote_token:
        thread = await session.scalar(
            select(EmailThread).where(EmailThread.quote_token == quote_token)
        )

    if thread is None:
        thread = await session.scalar(
            select(EmailThread).where(
                EmailThread.mailbox == settings.microsoft_mailbox,
                EmailThread.normalized_subject == signals.normalized_subject,
            )
        )

    created = False
    if thread is None:
        thread = EmailThread(
            provider="outlook",
            mailbox=settings.microsoft_mailbox or "unknown",
            provider_thread_id=mailbox_message.conversation_id,
            quote_token=quote_token,
            subject=mailbox_message.subject,
            normalized_subject=signals.normalized_subject,
            last_message_at=mailbox_message.received_at,
        )
        session.add(thread)
        await session.flush()
        created = True
    else:
        thread.subject = mailbox_message.subject or thread.subject
        thread.normalized_subject = signals.normalized_subject
        thread.provider_thread_id = mailbox_message.conversation_id or thread.provider_thread_id
        thread.quote_token = thread.quote_token or quote_token
        thread.last_message_at = mailbox_message.received_at

    return thread, created


async def _find_or_create_client(
    session: AsyncSession,
    *,
    sender_email: str,
    sender_name: str | None,
    create_if_missing: bool,
) -> tuple[Client | None, bool]:
    if not sender_email:
        return None, False

    client = await session.scalar(select(Client).where(Client.email == sender_email))
    if client is not None or not create_if_missing:
        return client, False

    client = Client(
        name=sender_name or _display_name_from_email(sender_email),
        email=sender_email,
        default_margin_percent=settings.profit_margin_percent_default,
        default_margin_floor=settings.profit_margin_floor_default,
    )
    session.add(client)
    await session.flush()
    return client, True


async def _find_or_create_shipment(
    session: AsyncSession,
    *,
    thread: EmailThread,
    client: Client | None,
    body_preview: str,
) -> tuple[Shipment, bool]:
    shipment = await session.scalar(
        select(Shipment).where(
            or_(Shipment.email_thread_id == thread.id, Shipment.quote_token == thread.quote_token)
        )
    )
    if shipment is not None:
        if client and shipment.client_id is None:
            shipment.client_id = client.id
        if not shipment.notes:
            shipment.notes = body_preview
        return shipment, False

    shipment = Shipment(
        client_id=client.id if client else None,
        email_thread_id=thread.id,
        status=ShipmentStage.RECEIVED.value,
        quote_token=thread.quote_token,
        margin_policy_json={
            "percent": client.default_margin_percent if client else settings.profit_margin_percent_default,
            "floor_amount": client.default_margin_floor if client else settings.profit_margin_floor_default,
        },
        notes=body_preview,
    )
    session.add(shipment)
    await session.flush()
    return shipment, True

async def ingest_outlook_message(
    session: AsyncSession,
    mailbox_message: OutlookMailboxMessage,
    *,
    create_client_if_missing: bool = True,
) -> OutlookIngestResult | None:
    """Normalize an Outlook message into freight workflow tables."""
    if not mailbox_message.provider_message_id:
        raise RuntimeError("Outlook message payload must include a provider message id")

    existing_message = await session.scalar(
        select(EmailMessage).where(
            EmailMessage.provider_message_id == mailbox_message.provider_message_id
        )
    )
    if existing_message is not None:
        shipment = await session.scalar(
            select(Shipment).where(Shipment.email_thread_id == existing_message.thread_id)
        )
        if shipment is None:
            return None
        return OutlookIngestResult(
            thread_id=str(existing_message.thread_id),
            email_message_id=str(existing_message.id),
            shipment_id=str(shipment.id),
            client_id=str(shipment.client_id) if shipment.client_id else None,
            created_thread=False,
            created_message=False,
            created_shipment=False,
            created_client=False,
        )

    quote_reference = generate_quote_reference()
    signals = build_correlation_signals(
        subject=mailbox_message.subject,
        sender=mailbox_message.sender_email,
        internet_message_id=mailbox_message.internet_message_id,
        conversation_id=mailbox_message.conversation_id,
    )
    quote_token = signals.quote_token or quote_reference.subject_token

    thread, created_thread = await _find_or_create_thread(
        session,
        mailbox_message=mailbox_message,
        quote_token=quote_token,
    )

    email_message = EmailMessage(
        thread_id=thread.id,
        provider_message_id=mailbox_message.provider_message_id,
        internet_message_id=mailbox_message.internet_message_id,
        conversation_id=mailbox_message.conversation_id,
        sender=mailbox_message.sender_email,
        recipients_json=mailbox_message.recipients,
        direction="inbound",
        subject=mailbox_message.subject,
        body_preview=mailbox_message.body_preview,
        raw_payload_json=mailbox_message.raw_payload,
        received_at=mailbox_message.received_at,
    )
    session.add(email_message)
    await session.flush()

    carrier = await session.scalar(select(Carrier).where(Carrier.email == mailbox_message.sender_email))

    client = None
    created_client = False
    if carrier is None:
        client, created_client = await _find_or_create_client(
            session,
            sender_email=mailbox_message.sender_email,
            sender_name=mailbox_message.sender_name,
            create_if_missing=create_client_if_missing,
        )

    shipment, created_shipment = await _find_or_create_shipment(
        session,
        thread=thread,
        client=client,
        body_preview=mailbox_message.body_preview,
    )

    workflow_event = WorkflowEvent(
        shipment_id=shipment.id,
        event_type=WorkflowEventType.EMAIL_RECEIVED.value,
        stage=ShipmentStage.RECEIVED.value,
        payload_json={
            "provider_message_id": mailbox_message.provider_message_id,
            "conversation_id": mailbox_message.conversation_id,
            "sender": mailbox_message.sender_email,
            "subject": mailbox_message.subject,
        },
    )
    session.add(workflow_event)
    await session.commit()
    await freight_realtime_hub.notify_workflow_event(workflow_event)

    return OutlookIngestResult(
        thread_id=str(thread.id),
        email_message_id=str(email_message.id),
        shipment_id=str(shipment.id),
        client_id=str(client.id) if client else None,
        created_thread=created_thread,
        created_message=True,
        created_shipment=created_shipment,
        created_client=created_client,
    )
