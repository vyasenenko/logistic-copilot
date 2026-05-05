"""Mailbox ingestion helpers for Outlook-first freight workflow."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.memory.database import (
    Carrier,
    Client,
    EmailMessage,
    EmailThread,
    EmailTriageItem,
    FraudDenylistEntry,
    Shipment,
    WorkflowEvent,
)
from app.schemas import (
    EmailTriageClassification,
    FraudDenylistScope,
    OutlookIngestResult,
    ShipmentStage,
    WorkflowEventType,
)
from app.services.email_correlation import build_correlation_signals, generate_quote_reference
from app.services.email_fraud import (
    assess_sender_risk,
    extract_sender_domain,
    fraud_assessment_from_denylist_match,
    normalize_sender_email,
)
from app.services.freight_ai import classify_email_triage_with_ai
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


def _should_materialize_shipment_for_triage(
    *,
    classification: EmailTriageClassification,
    quote_token: str | None,
    existing_shipment_linked: bool,
) -> bool:
    if classification == EmailTriageClassification.FREIGHT_QUOTE_REQUEST:
        return True
    if classification in {EmailTriageClassification.CARRIER_REPLY, EmailTriageClassification.STATUS_OR_OPS}:
        return existing_shipment_linked
    return False


async def _find_or_create_thread(
    session: AsyncSession,
    *,
    organization_id: UUID,
    mailbox: str,
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
                EmailThread.organization_id == organization_id,
                EmailThread.provider_thread_id == mailbox_message.conversation_id
            )
        )

    reply_message_ids = [
        message_id
        for message_id in [mailbox_message.in_reply_to, *(mailbox_message.references or [])]
        if message_id
    ]
    if thread is None and reply_like and reply_message_ids:
        thread = await session.scalar(
            select(EmailThread)
            .join(EmailMessage, EmailMessage.thread_id == EmailThread.id)
            .where(
                EmailThread.organization_id == organization_id,
                EmailMessage.organization_id == organization_id,
                EmailMessage.internet_message_id.in_(reply_message_ids),
            )
            .order_by(EmailMessage.received_at.desc())
        )

    if thread is None and subject_quote_token:
        thread = await session.scalar(
            select(EmailThread).where(
                EmailThread.organization_id == organization_id,
                EmailThread.quote_token == subject_quote_token,
            )
        )

    created = False
    if thread is None:
        thread = EmailThread(
            organization_id=organization_id,
            provider="outlook",
            mailbox=mailbox,
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
    organization_id: UUID,
    sender_email: str,
    sender_name: str | None,
    create_if_missing: bool,
) -> tuple[Client | None, bool]:
    if not sender_email:
        return None, False

    client = await session.scalar(
        select(Client).where(Client.organization_id == organization_id, Client.email == sender_email)
    )
    if client is not None or not create_if_missing:
        return client, False

    client = Client(
        organization_id=organization_id,
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
    organization_id: UUID,
    thread: EmailThread,
    client: Client | None,
    body_preview: str,
) -> tuple[Shipment, bool]:
    if bool(getattr(thread, "shipment_ingest_suppressed", False)):
        existing_archived = await session.scalar(
            select(Shipment)
            .where(Shipment.organization_id == organization_id, Shipment.email_thread_id == thread.id)
            .order_by(Shipment.created_at.desc())
        )
        if existing_archived is not None:
            return existing_archived, False
        raise RuntimeError("Shipment creation suppressed for this email thread")

    shipment = await session.scalar(
        select(Shipment).where(
            Shipment.organization_id == organization_id,
            or_(Shipment.email_thread_id == thread.id, Shipment.quote_token == thread.quote_token)
        )
    )
    if shipment is not None:
        if client and shipment.client_id is None:
            shipment.client_id = client.id
        return shipment, False

    shipment = Shipment(
        organization_id=organization_id,
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


async def _latest_shipment_for_thread(session: AsyncSession, thread_id, *, organization_id: UUID) -> Shipment | None:
    return await session.scalar(
        select(Shipment)
        .where(Shipment.organization_id == organization_id, Shipment.email_thread_id == thread_id)
        .order_by(Shipment.created_at.desc())
    )


async def _find_active_fraud_denylist_entry(
    session: AsyncSession,
    *,
    organization_id: UUID,
    sender_email: str,
) -> FraudDenylistEntry | None:
    normalized_email = normalize_sender_email(sender_email)
    sender_domain = extract_sender_domain(normalized_email)
    if not normalized_email:
        return None
    result = await session.execute(
        select(FraudDenylistEntry)
        .where(FraudDenylistEntry.organization_id == organization_id, FraudDenylistEntry.is_active.is_(True))
        .where(
            or_(
                (FraudDenylistEntry.scope == FraudDenylistScope.SENDER_EMAIL.value)
                & (FraudDenylistEntry.value == normalized_email),
                (FraudDenylistEntry.scope == FraudDenylistScope.SENDER_DOMAIN.value)
                & (FraudDenylistEntry.value == sender_domain),
            )
        )
        .order_by(FraudDenylistEntry.created_at.desc())
    )
    return result.scalars().first()


async def _save_email_triage_item(
    session: AsyncSession,
    *,
    email_message: EmailMessage,
    thread: EmailThread,
    triage_result,
    shipment: Shipment | None = None,
    fraud_payload: dict | None = None,
) -> EmailTriageItem:
    item = EmailTriageItem(
        organization_id=email_message.organization_id,
        email_message_id=email_message.id,
        thread_id=thread.id,
        classification=triage_result.classification.value,
        confidence=triage_result.confidence,
        reason=triage_result.reason[:500] if triage_result.reason else None,
        recommended_action=triage_result.recommended_action,
        created_shipment_id=shipment.id if shipment is not None else None,
        payload_json={
            "signals": triage_result.signals,
            "fraud": fraud_payload or {},
            "sender": email_message.sender,
            "subject": email_message.subject,
        },
    )
    session.add(item)
    await session.flush()
    return item


async def ingest_outlook_message(
    session: AsyncSession,
    mailbox_message: OutlookMailboxMessage,
    *,
    organization_id: UUID,
    mailbox: str | None = None,
    create_client_if_missing: bool = True,
) -> OutlookIngestResult | None:
    """Normalize an Outlook message into freight workflow tables."""
    if not mailbox_message.provider_message_id:
        raise RuntimeError("Outlook message payload must include a provider message id")

    normalized_mailbox = (mailbox or "").strip().lower() or "unknown"
    existing_message = await session.scalar(
        select(EmailMessage)
        .join(EmailThread, EmailThread.id == EmailMessage.thread_id)
        .where(
            EmailMessage.organization_id == organization_id,
            EmailMessage.provider_message_id == mailbox_message.provider_message_id,
            EmailThread.organization_id == organization_id,
            EmailThread.mailbox == normalized_mailbox,
        )
    )
    if existing_message is not None:
        shipment = await _latest_shipment_for_thread(
            session,
            existing_message.thread_id,
            organization_id=organization_id,
        )
        fraud_payload = dict((existing_message.raw_payload_json or {}).get("fraud", {}) or {})
        triage_item = await session.scalar(
            select(EmailTriageItem)
            .where(EmailTriageItem.email_message_id == existing_message.id)
            .order_by(EmailTriageItem.created_at.desc())
        )
        if shipment is None:
            if triage_item is None:
                return None
            return OutlookIngestResult(
                thread_id=str(existing_message.thread_id),
                email_message_id=str(existing_message.id),
                shipment_id="",
                created_thread=False,
                created_message=False,
                created_shipment=False,
                created_client=False,
                suppressed=True,
                suppression_reason="shipment_creation_skipped",
                shipment_creation_skipped=True,
                sender_known=bool(fraud_payload.get("sender_known", False)),
                sender_verification_required=bool(fraud_payload.get("verification_required", False)),
                fraud_risk_level=fraud_payload.get("risk_level"),
                fraud_risk_reasons=list(fraud_payload.get("reasons", []) or []),
                fraud_score=fraud_payload.get("score"),
                sender_email=fraud_payload.get("sender_email"),
                sender_domain=fraud_payload.get("sender_domain"),
                triage_id=str(triage_item.id),
                triage_classification=triage_item.classification,
                triage_reason=triage_item.reason,
                triage_recommended_action=triage_item.recommended_action,
            )
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
            sender_known=bool(fraud_payload.get("sender_known", False)),
            sender_verification_required=bool(fraud_payload.get("verification_required", False)),
            fraud_risk_level=fraud_payload.get("risk_level"),
            fraud_risk_reasons=list(fraud_payload.get("reasons", []) or []),
            fraud_score=fraud_payload.get("score"),
            sender_email=fraud_payload.get("sender_email"),
            sender_domain=fraud_payload.get("sender_domain"),
            triage_id=str(triage_item.id) if triage_item else None,
            triage_classification=triage_item.classification if triage_item else None,
            triage_reason=triage_item.reason if triage_item else None,
            triage_recommended_action=triage_item.recommended_action if triage_item else None,
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
        organization_id=organization_id,
        mailbox=normalized_mailbox,
        mailbox_message=mailbox_message,
        quote_token=quote_token,
    )

    looks_like_bounce, suppression_reason = _looks_like_bounce_or_non_delivery(mailbox_message)
    if looks_like_bounce:
        thread.shipment_ingest_suppressed = True
        thread.shipment_ingest_suppressed_reason = suppression_reason
        thread.shipment_ingest_suppressed_at = datetime.now(timezone.utc)

    email_message = EmailMessage(
        organization_id=organization_id,
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

    denylist_entry = await _find_active_fraud_denylist_entry(
        session,
        organization_id=organization_id,
        sender_email=mailbox_message.sender_email,
    )
    if denylist_entry is not None:
        fraud_assessment = fraud_assessment_from_denylist_match(
            sender_email=mailbox_message.sender_email,
            scope=denylist_entry.scope,
            value=denylist_entry.value,
        )
    else:
        known_sender_rows = await session.execute(select(Client.email).where(Client.organization_id == organization_id))
        known_carrier_rows = await session.execute(select(Carrier.email).where(Carrier.organization_id == organization_id))
        known_senders = {
            str(value).strip().lower()
            for value in [*known_sender_rows.scalars().all(), *known_carrier_rows.scalars().all()]
            if str(value).strip()
        }
        known_domains = {
            email.split("@", 1)[1]
            for email in known_senders
            if "@" in email
        }
        fraud_assessment = assess_sender_risk(
            sender_email=mailbox_message.sender_email,
            sender_name=mailbox_message.sender_name,
            known_senders=known_senders,
            known_domains=known_domains,
        )
    email_payload = dict(email_message.raw_payload_json or {})
    fraud_payload = fraud_assessment.model_dump(mode="json")
    if denylist_entry is not None:
        fraud_payload["denylist_entry_id"] = str(denylist_entry.id)
        fraud_payload["denylist_scope"] = denylist_entry.scope
        fraud_payload["denylist_value"] = denylist_entry.value
    email_payload["fraud"] = fraud_payload
    email_message.raw_payload_json = email_payload
    session.add(email_message)
    await session.flush()

    existing_shipment = await _latest_shipment_for_thread(session, thread.id, organization_id=organization_id)
    triage_result = await classify_email_triage_with_ai(
        subject=mailbox_message.subject,
        body_preview=mailbox_message.body_preview,
        sender_email=mailbox_message.sender_email,
        quote_token=signals.quote_token,
        existing_shipment_linked=existing_shipment is not None,
        fraud_reasons=list(fraud_assessment.reasons),
        fraud_risk_level=fraud_assessment.risk_level.value,
    )

    carrier = await session.scalar(
        select(Carrier).where(Carrier.organization_id == organization_id, Carrier.email == mailbox_message.sender_email)
    )
    client = await session.scalar(
        select(Client).where(Client.organization_id == organization_id, Client.email == mailbox_message.sender_email)
    )

    created_client = False
    if (
        carrier is None
        and client is None
        and not thread.shipment_ingest_suppressed
        and denylist_entry is None
        and triage_result.classification == EmailTriageClassification.FREIGHT_QUOTE_REQUEST
    ):
        # New senders are ingested for review, but are not auto-trusted as customers.
        if not fraud_assessment.verification_required and create_client_if_missing:
            client, created_client = await _find_or_create_client(
                session,
                organization_id=organization_id,
                sender_email=mailbox_message.sender_email,
                sender_name=mailbox_message.sender_name,
                create_if_missing=create_client_if_missing,
            )

    shipment = None
    created_shipment = False
    shipment_creation_skipped = False
    should_materialize_shipment = _should_materialize_shipment_for_triage(
        classification=triage_result.classification,
        quote_token=signals.quote_token or thread.quote_token,
        existing_shipment_linked=existing_shipment is not None,
    )
    if not thread.shipment_ingest_suppressed and should_materialize_shipment:
        shipment, created_shipment = await _find_or_create_shipment(
            session,
            organization_id=organization_id,
            thread=thread,
            client=client,
            body_preview=mailbox_message.body_preview,
        )
    else:
        shipment_creation_skipped = True
        shipment = existing_shipment
        if shipment is None:
            thread.shipment_ingest_suppressed = True
            thread.shipment_ingest_suppressed_reason = triage_result.classification.value
            thread.shipment_ingest_suppressed_at = datetime.now(timezone.utc)

    triage_item = await _save_email_triage_item(
        session,
        email_message=email_message,
        thread=thread,
        triage_result=triage_result,
        shipment=shipment,
        fraud_payload=fraud_payload,
    )

    workflow_events: list[WorkflowEvent] = []
    if shipment is not None:
        workflow_event = WorkflowEvent(
            organization_id=organization_id,
            shipment_id=shipment.id,
            event_type=WorkflowEventType.EMAIL_RECEIVED.value,
            stage=ShipmentStage.RECEIVED.value,
            payload_json={
                "provider_message_id": mailbox_message.provider_message_id,
                "conversation_id": mailbox_message.conversation_id,
                "sender": mailbox_message.sender_email,
                "subject": mailbox_message.subject,
                "suppressed": bool(thread.shipment_ingest_suppressed),
                "fraud": fraud_payload,
            },
        )
        session.add(workflow_event)
        workflow_events.append(workflow_event)
        if denylist_entry is not None and shipment.is_archived:
            archive_payload = {
                "reason": thread.shipment_ingest_suppressed_reason,
                "reason_code": "fraud",
                "reason_note": thread.shipment_ingest_suppressed_reason,
                "email_thread_id": str(thread.id),
                "denylist_entry_id": str(denylist_entry.id),
                "denylist_scope": denylist_entry.scope,
                "denylist_value": denylist_entry.value,
            }
            archive_event = WorkflowEvent(
                organization_id=organization_id,
                shipment_id=shipment.id,
                event_type=WorkflowEventType.SHIPMENT_ARCHIVED.value,
                stage=shipment.status,
                payload_json={**archive_payload, "suppress_source_thread": True},
            )
            suppress_event = WorkflowEvent(
                organization_id=organization_id,
                shipment_id=shipment.id,
                event_type=WorkflowEventType.SHIPMENT_SOURCE_SUPPRESSED.value,
                stage=shipment.status,
                payload_json={**archive_payload, "suppressed": True},
            )
            session.add(archive_event)
            session.add(suppress_event)
            workflow_events.extend([archive_event, suppress_event])
    await session.commit()
    if workflow_events:
        await freight_realtime_hub.notify_workflow_events(workflow_events)

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
        sender_known=fraud_assessment.sender_known,
        sender_verification_required=fraud_assessment.verification_required,
        fraud_risk_level=fraud_assessment.risk_level,
        fraud_risk_reasons=list(fraud_assessment.reasons),
        fraud_score=fraud_assessment.score,
        sender_email=fraud_assessment.sender_email,
        sender_domain=fraud_assessment.sender_domain,
        triage_id=str(triage_item.id),
        triage_classification=triage_result.classification,
        triage_reason=triage_result.reason,
        triage_recommended_action=triage_result.recommended_action,
    )
