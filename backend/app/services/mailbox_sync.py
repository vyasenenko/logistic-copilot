"""Mailbox ingestion helpers for Outlook-first freight workflow."""

from __future__ import annotations

from datetime import datetime, timezone
import re

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.memory.database import Carrier, Client, EmailMessage, EmailThread, Shipment, WorkflowEvent
from app.schemas import OutlookIngestResult, ShipmentStage, WorkflowEventType
from app.services.email_correlation import build_correlation_signals, generate_quote_reference
from app.services.freight_realtime import freight_realtime_hub
from app.services.outlook import OutlookMailboxMessage

REPLY_SUBJECT_PATTERN = re.compile(r"^(re|fw|fwd)\s*:\s*", re.IGNORECASE)


def _display_name_from_email(email: str) -> str:
    local_part = email.split("@", 1)[0]
    return local_part.replace(".", " ").replace("_", " ").title() or email


def _is_reply_like_message(
    mailbox_message: OutlookMailboxMessage,
    *,
    subject_quote_token: str | None,
) -> bool:
    """Only reply-like messages are allowed to reuse existing workflow threads."""
    if subject_quote_token:
        return True
    if getattr(mailbox_message, "in_reply_to", None):
        return True
    if getattr(mailbox_message, "references", None):
        return True
    return bool(REPLY_SUBJECT_PATTERN.match(mailbox_message.subject or ""))


def _looks_like_bounce_or_non_delivery(mailbox_message: OutlookMailboxMessage) -> tuple[bool, str | None]:
    sender = (mailbox_message.sender_email or "").lower()
    subject = (mailbox_message.subject or "").lower()
    body_preview = (mailbox_message.body_preview or "").lower()
    sender_hints = ("mailer-daemon", "postmaster", "microsoft outlook", "mail delivery subsystem")
    subject_hints = (
        "undeliverable",
        "delivery has failed",
        "delivery failed",
        "message blocked",
        "not delivered",
        "failed delivery",
        "returned mail",
    )
    body_hints = (
        "не удалось выполнить доставку",
        "message not delivered",
        "remote server returned",
        "delivery to the following recipients failed",
        "service unavailable. access denied",
    )

    if any(hint in sender for hint in sender_hints):
        return True, "bounce_sender_detected"
    if any(hint in subject for hint in subject_hints):
        return True, "bounce_subject_detected"
    if any(hint in body_preview for hint in body_hints):
        return True, "bounce_body_detected"
    return False, None


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
        in_reply_to=mailbox_message.in_reply_to,
        references=mailbox_message.references or [],
        conversation_id=mailbox_message.conversation_id,
    )
    subject_quote_token = signals.quote_token
    reply_like = _is_reply_like_message(
        mailbox_message,
        subject_quote_token=subject_quote_token,
    )

    thread = None
    if reply_like and mailbox_message.conversation_id:
        thread = await session.scalar(
            select(EmailThread).where(
                EmailThread.provider_thread_id == mailbox_message.conversation_id
            )
        )

    reply_message_ids = [
        message_id
        for message_id in [mailbox_message.in_reply_to, *(mailbox_message.references or [])]
        if message_id
    ]
    if thread is None and reply_like and reply_message_ids:
        referenced_message = await session.scalar(
            select(EmailMessage)
            .where(EmailMessage.internet_message_id.in_(reply_message_ids))
            .order_by(EmailMessage.received_at.desc())
        )
        if referenced_message is not None:
            thread = referenced_message.thread

    if thread is None and subject_quote_token:
        thread = await session.scalar(
            select(EmailThread).where(EmailThread.quote_token == subject_quote_token)
        )

    created = False
    if thread is None:
        thread = EmailThread(
            provider="outlook",
            mailbox=settings.microsoft_mailbox or "unknown",
            provider_thread_id=mailbox_message.conversation_id if reply_like else None,
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
        if reply_like and mailbox_message.conversation_id:
            thread.provider_thread_id = mailbox_message.conversation_id
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
    if bool(getattr(thread, "shipment_ingest_suppressed", False)):
        existing_archived = await session.scalar(
            select(Shipment)
            .where(Shipment.email_thread_id == thread.id)
            .order_by(Shipment.created_at.desc())
        )
        if existing_archived is not None:
            return existing_archived, False
        raise RuntimeError("Shipment creation suppressed for this email thread")

    shipment = await session.scalar(
        select(Shipment).where(
            or_(Shipment.email_thread_id == thread.id, Shipment.quote_token == thread.quote_token)
        )
    )
    if shipment is not None:
        if client and shipment.client_id is None:
            shipment.client_id = client.id
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
        notes=None,
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
            select(Shipment).where(Shipment.email_thread_id == existing_message.thread_id).order_by(Shipment.created_at.desc())
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
            suppressed=bool(shipment.is_archived and shipment.email_thread_id),
            suppression_reason=shipment.archived_reason if shipment.is_archived else None,
            shipment_creation_skipped=bool(shipment.is_archived),
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

    looks_like_bounce, suppression_reason = _looks_like_bounce_or_non_delivery(mailbox_message)
    if looks_like_bounce:
        thread.shipment_ingest_suppressed = True
        thread.shipment_ingest_suppressed_reason = suppression_reason
        thread.shipment_ingest_suppressed_at = datetime.now(timezone.utc)

    email_message = EmailMessage(
        thread_id=thread.id,
        provider_message_id=mailbox_message.provider_message_id,
        internet_message_id=mailbox_message.internet_message_id,
        conversation_id=mailbox_message.conversation_id,
        in_reply_to=mailbox_message.in_reply_to,
        references_json=mailbox_message.references or [],
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
    if carrier is None and not thread.shipment_ingest_suppressed:
        client, created_client = await _find_or_create_client(
            session,
            sender_email=mailbox_message.sender_email,
            sender_name=mailbox_message.sender_name,
            create_if_missing=create_client_if_missing,
        )

    shipment = None
    created_shipment = False
    shipment_creation_skipped = False
    if not thread.shipment_ingest_suppressed:
        shipment, created_shipment = await _find_or_create_shipment(
            session,
            thread=thread,
            client=client,
            body_preview=mailbox_message.body_preview,
        )
    else:
        shipment_creation_skipped = True
        shipment = await session.scalar(
            select(Shipment).where(Shipment.email_thread_id == thread.id).order_by(Shipment.created_at.desc())
        )

    workflow_event = None
    if shipment is not None:
        workflow_event = WorkflowEvent(
            shipment_id=shipment.id,
            event_type=WorkflowEventType.EMAIL_RECEIVED.value,
            stage=ShipmentStage.RECEIVED.value,
            payload_json={
                "provider_message_id": mailbox_message.provider_message_id,
                "conversation_id": mailbox_message.conversation_id,
                "sender": mailbox_message.sender_email,
                "subject": mailbox_message.subject,
                "suppressed": bool(thread.shipment_ingest_suppressed),
            },
        )
        session.add(workflow_event)
    await session.commit()
    if workflow_event is not None:
        await freight_realtime_hub.notify_workflow_event(workflow_event)

    return OutlookIngestResult(
        thread_id=str(thread.id),
        email_message_id=str(email_message.id),
        shipment_id=str(shipment.id) if shipment else "",
        client_id=str(client.id) if client else (str(shipment.client_id) if shipment and shipment.client_id else None),
        created_thread=created_thread,
        created_message=True,
        created_shipment=created_shipment,
        created_client=created_client,
        suppressed=bool(thread.shipment_ingest_suppressed),
        suppression_reason=thread.shipment_ingest_suppressed_reason,
        shipment_creation_skipped=shipment_creation_skipped,
    )
