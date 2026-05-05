"""Best-effort Outlook mailbox actions tied to freight workflow state."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.database import EmailMessage, EmailThread, Shipment, WorkflowEvent
from app.schemas import ShipmentStage, WorkflowEventType
from app.services.outlook import OutlookGraphClient
from app.services.outlook_organization import (
    build_outlook_graph_client,
    build_outlook_graph_client_for_shipment,
    graph_mailbox_for_email_thread,
)

logger = logging.getLogger(__name__)

OUTLOOK_CATEGORY_NEW_QUOTE = "🆕 New Quote"
OUTLOOK_CATEGORY_CARRIER_BID = "🚚 Carrier Bid"
OUTLOOK_CATEGORY_CONFIRMATION = "✅ Confirmation"
OUTLOOK_CATEGORY_CLARIFICATION = "❓ Clarification"
OUTLOOK_CATEGORY_STATUS = "🔍 Status"
OUTLOOK_CATEGORY_NEEDS_REVIEW = "👀 Needs Review"
OUTLOOK_CATEGORY_ARCHIVED = "🗃️ Archived"
OUTLOOK_CATEGORY_EXCEPTION = "❌ Exception"
OUTLOOK_CATEGORY_OTHER = "Other"
OUTLOOK_CATEGORY_NEW_SENDER = "🆕 New Sender"
OUTLOOK_CATEGORY_VERIFY_SENDER = "⚠️ Verify Sender"
OUTLOOK_CATEGORY_PROBABLE_FRAUD = "‼️ Probable Fraud"
OUTLOOK_CATEGORY_NOT_SHIPMENT = "🚫 Not Shipment"
OUTLOOK_CATEGORY_TRIAGE = "🔍 Triage"


async def _outlook_client_for_email_message(
    session: AsyncSession,
    message: EmailMessage,
) -> OutlookGraphClient | None:
    org_id = message.organization_id
    if org_id is None and message.thread_id:
        thread = await session.get(EmailThread, message.thread_id)
        if thread is not None:
            org_id = thread.organization_id
    if org_id is None:
        return None
    mailbox, email_connection_id = await graph_mailbox_for_email_thread(
        session,
        organization_id=org_id,
        email_thread_id=message.thread_id,
    )
    try:
        return await build_outlook_graph_client(
            session,
            org_id,
            mailbox=mailbox,
            email_connection_id=email_connection_id,
        )
    except RuntimeError:
        return None


OUTLOOK_CATEGORY_COLORS = {
    OUTLOOK_CATEGORY_NEW_QUOTE: "preset4",
    OUTLOOK_CATEGORY_CARRIER_BID: "preset10",
    OUTLOOK_CATEGORY_CONFIRMATION: "preset17",
    OUTLOOK_CATEGORY_CLARIFICATION: "preset7",
    OUTLOOK_CATEGORY_STATUS: "preset2",
    OUTLOOK_CATEGORY_NEEDS_REVIEW: "preset0",
    OUTLOOK_CATEGORY_ARCHIVED: "preset8",
    OUTLOOK_CATEGORY_EXCEPTION: "preset0",
    OUTLOOK_CATEGORY_OTHER: "preset14",
    OUTLOOK_CATEGORY_NEW_SENDER: "preset3",
    OUTLOOK_CATEGORY_VERIFY_SENDER: "preset12",
    OUTLOOK_CATEGORY_PROBABLE_FRAUD: "preset0",
    OUTLOOK_CATEGORY_NOT_SHIPMENT: "preset14",
    OUTLOOK_CATEGORY_TRIAGE: "preset7",
}


def quote_token_outlook_category(quote_token: str | None) -> str | None:
    token = (quote_token or "").strip().upper()
    if not token:
        return None
    return f"{token}"


async def _workflow_stage_for_shipment(
    session: AsyncSession,
    shipment_id: str | UUID | None,
) -> str:
    if not shipment_id:
        return ShipmentStage.RECEIVED.value
    shipment = await session.get(Shipment, UUID(str(shipment_id)))
    return shipment.status if shipment is not None and shipment.status else ShipmentStage.RECEIVED.value


def outlook_categories_for_ai_decision(
    *,
    intent: str | None,
    manual_review_required: bool,
    bid_intaken: bool = False,
    status_lookup_triggered: bool = False,
    status_reply_sent: bool = False,
    tms_status_updated: bool = False,
) -> list[str]:
    """Map freight inbox decisions into human-visible Outlook categories."""
    categories: list[str] = []
    normalized_intent = (intent or "").strip().lower()
    if normalized_intent == "new_quote_request":
        categories.append(OUTLOOK_CATEGORY_NEW_QUOTE)
    elif normalized_intent == "carrier_bid_reply" or bid_intaken:
        categories.append(OUTLOOK_CATEGORY_CARRIER_BID)
    elif normalized_intent == "customer_quote_confirmation":
        categories.append(OUTLOOK_CATEGORY_CONFIRMATION)
    elif normalized_intent == "customer_clarification":
        categories.append(OUTLOOK_CATEGORY_CLARIFICATION)
    elif normalized_intent in {"customer_status_request", "carrier_status_update"} or (
        status_lookup_triggered or status_reply_sent or tms_status_updated
    ):
        categories.append(OUTLOOK_CATEGORY_STATUS)
    elif normalized_intent == "exception_or_issue":
        categories.append(OUTLOOK_CATEGORY_EXCEPTION)
    elif normalized_intent and normalized_intent != "noise_or_unhandled":
        categories.append(OUTLOOK_CATEGORY_OTHER)

    if manual_review_required:
        categories.append(OUTLOOK_CATEGORY_NEEDS_REVIEW)

    return list(dict.fromkeys(categories))


def outlook_categories_for_fraud_assessment(
    *,
    sender_verification_required: bool,
    fraud_risk_level: str | None,
) -> list[str]:
    categories: list[str] = []
    if sender_verification_required:
        categories.extend([OUTLOOK_CATEGORY_NEW_SENDER, OUTLOOK_CATEGORY_VERIFY_SENDER])
    if fraud_risk_level == "medium":
        categories.extend([OUTLOOK_CATEGORY_VERIFY_SENDER, OUTLOOK_CATEGORY_NEEDS_REVIEW])
    elif fraud_risk_level == "high":
        categories.extend([OUTLOOK_CATEGORY_PROBABLE_FRAUD, OUTLOOK_CATEGORY_NEEDS_REVIEW])
    return list(dict.fromkeys(categories))


def outlook_categories_for_email_triage(classification: str | None) -> list[str]:
    """Map pre-shipment triage classifications into Outlook categories."""
    if classification == "fraud_or_phishing":
        return [OUTLOOK_CATEGORY_PROBABLE_FRAUD, OUTLOOK_CATEGORY_NEEDS_REVIEW]
    if classification == "needs_operator_triage":
        return [OUTLOOK_CATEGORY_TRIAGE, OUTLOOK_CATEGORY_NEEDS_REVIEW]
    if classification == "noise_or_unhandled":
        return [OUTLOOK_CATEGORY_NOT_SHIPMENT, OUTLOOK_CATEGORY_TRIAGE]
    if classification in {"carrier_reply", "status_or_ops"}:
        return [OUTLOOK_CATEGORY_TRIAGE]
    return []


async def add_email_message_categories(
    session: AsyncSession,
    *,
    email_message_id: str | UUID,
    shipment_id: str | UUID | None,
    categories: list[str],
    reason: str,
) -> dict:
    """Add Outlook categories to one saved email message."""
    message = await session.get(EmailMessage, UUID(str(email_message_id)))
    if message is None:
        return {"attempted": False, "status": "email_message_not_found"}
    if not message.provider_message_id:
        return {"attempted": False, "status": "missing_provider_message_id"}
    shipment = await session.get(Shipment, UUID(str(shipment_id))) if shipment_id else None
    token_category = quote_token_outlook_category(shipment.quote_token if shipment else None)
    effective_categories = list(dict.fromkeys(categories + ([token_category] if token_category else [])))

    if not effective_categories:
        return {"attempted": False, "status": "no_categories"}

    outlook = await _outlook_client_for_email_message(session, message)
    if outlook is None:
        return {"attempted": False, "status": "outlook_not_configured"}

    try:
        result = await outlook.add_message_categories(
            message.provider_message_id,
            effective_categories,
            category_colors=OUTLOOK_CATEGORY_COLORS,
        )
    except Exception as exc:
        logger.warning(
            "outlook_mail_action.categorize_failed email_message_id=%s provider_message_id=%s shipment_id=%s categories=%s reason=%s error=%s",
            message.id,
            message.provider_message_id,
            shipment_id,
            effective_categories,
            reason,
            exc,
            exc_info=True,
        )
        return {"attempted": True, "status": "failed", "error": str(exc)}

    if shipment_id:
        try:
            session.add(
                WorkflowEvent(
                    shipment_id=UUID(str(shipment_id)),
                    event_type=WorkflowEventType.EMAIL_CATEGORIZED.value,
                    stage=await _workflow_stage_for_shipment(session, shipment_id),
                    payload_json={
                        "email_message_id": str(message.id),
                        "provider_message_id": message.provider_message_id,
                        "categories": effective_categories,
                        "quote_token_category": token_category,
                        "reason": reason,
                        "outlook_result": result,
                    },
                )
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.warning(
                "outlook_mail_action.categorize_event_failed email_message_id=%s shipment_id=%s categories=%s reason=%s error=%s",
                message.id,
                shipment_id,
                effective_categories,
                reason,
                exc,
                exc_info=True,
            )
            return {"attempted": True, "status": "event_failed", "error": str(exc), **result}

    logger.info(
        "outlook_mail_action.categorize_success email_message_id=%s provider_message_id=%s shipment_id=%s categories=%s reason=%s",
        message.id,
        message.provider_message_id,
        shipment_id,
        effective_categories,
        reason,
    )
    return {"attempted": True, "status": "completed", **result}


async def mark_email_message_read_after_ai_success(
    session: AsyncSession,
    *,
    email_message_id: str | UUID,
    shipment_id: str | UUID | None,
    reason: str,
) -> dict:
    """Mark an inbound email as read after successful AI processing.

    This is intentionally best-effort: Outlook mailbox state should never block
    freight ingestion or shipment automation.
    """
    message = await session.get(EmailMessage, UUID(str(email_message_id)))
    if message is None:
        return {"attempted": False, "status": "email_message_not_found"}
    if (message.direction or "").lower() != "inbound":
        return {"attempted": False, "status": "not_inbound"}
    if not message.provider_message_id:
        return {"attempted": False, "status": "missing_provider_message_id"}

    outlook = await _outlook_client_for_email_message(session, message)
    if outlook is None:
        return {"attempted": False, "status": "outlook_not_configured"}

    try:
        result = await outlook.mark_message_read(message.provider_message_id)
    except Exception as exc:
        logger.warning(
            "outlook_mail_action.mark_read_failed email_message_id=%s provider_message_id=%s shipment_id=%s reason=%s error=%s",
            message.id,
            message.provider_message_id,
            shipment_id,
            reason,
            exc,
            exc_info=True,
        )
        return {"attempted": True, "status": "failed", "error": str(exc)}

    if shipment_id:
        try:
            session.add(
                WorkflowEvent(
                    shipment_id=UUID(str(shipment_id)),
                    event_type=WorkflowEventType.EMAIL_MARKED_READ.value,
                    stage=await _workflow_stage_for_shipment(session, shipment_id),
                    payload_json={
                        "email_message_id": str(message.id),
                        "provider_message_id": message.provider_message_id,
                        "reason": reason,
                        "outlook_result": result,
                    },
                )
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.warning(
                "outlook_mail_action.mark_read_event_failed email_message_id=%s shipment_id=%s reason=%s error=%s",
                message.id,
                shipment_id,
                reason,
                exc,
                exc_info=True,
            )
            return {"attempted": True, "status": "event_failed", "error": str(exc), **result}

    logger.info(
        "outlook_mail_action.mark_read_success email_message_id=%s provider_message_id=%s shipment_id=%s reason=%s",
        message.id,
        message.provider_message_id,
        shipment_id,
        reason,
    )
    return {"attempted": True, "status": "completed", **result}


async def move_shipment_thread_messages_to_archive(
    session: AsyncSession,
    *,
    shipment: Shipment,
    reason: str,
) -> dict:
    """Move Outlook messages linked to a shipment thread into Archive.

    The DB archive/suppression state remains source of truth. Graph failures are
    logged and returned, but do not unarchive or roll back the shipment.
    """
    if not shipment.email_thread_id:
        return {"attempted": False, "status": "missing_email_thread_id", "moved": 0, "failed": 0}

    result = await session.execute(
        select(EmailMessage)
        .where(EmailMessage.thread_id == shipment.email_thread_id)
        .order_by(EmailMessage.received_at.asc())
    )
    messages = [
        message
        for message in result.scalars().all()
        if message.provider_message_id
    ]
    if not messages:
        return {"attempted": False, "status": "no_provider_messages", "moved": 0, "failed": 0}

    if not shipment.organization_id:
        return {"attempted": False, "status": "missing_organization_id", "moved": 0, "failed": 0}

    try:
        outlook = await build_outlook_graph_client_for_shipment(session, shipment)
    except RuntimeError:
        return {"attempted": False, "status": "outlook_not_configured", "moved": 0, "failed": 0}

    moved: list[dict] = []
    failed: list[dict] = []
    for message in messages:
        try:
            token_category = quote_token_outlook_category(shipment.quote_token)
            await outlook.add_message_categories(
                str(message.provider_message_id),
                [category for category in [OUTLOOK_CATEGORY_ARCHIVED, token_category] if category],
                category_colors=OUTLOOK_CATEGORY_COLORS,
            )
            graph_result = await outlook.move_message_to_archive(str(message.provider_message_id))
            moved.append(
                {
                    "email_message_id": str(message.id),
                    "provider_message_id": message.provider_message_id,
                    "moved_message_id": graph_result.get("moved_message_id"),
                    "direction": message.direction,
                }
            )
        except Exception as exc:
            failed.append(
                {
                    "email_message_id": str(message.id),
                    "provider_message_id": message.provider_message_id,
                    "direction": message.direction,
                    "error": str(exc),
                }
            )
            logger.warning(
                "outlook_mail_action.move_archive_failed shipment_id=%s email_message_id=%s provider_message_id=%s reason=%s error=%s",
                shipment.id,
                message.id,
                message.provider_message_id,
                reason,
                exc,
                exc_info=True,
            )

    session.add(
        WorkflowEvent(
            shipment_id=shipment.id,
            event_type=WorkflowEventType.EMAIL_MOVED_TO_ARCHIVE.value,
            stage=shipment.status,
            payload_json={
                "email_thread_id": str(shipment.email_thread_id),
                "reason": reason,
                "attempted": len(messages),
                "moved": len(moved),
                "failed": len(failed),
                "moved_messages": moved,
                "failed_messages": failed[:10],
                "completed_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    )
    await session.commit()

    logger.info(
        "outlook_mail_action.move_archive_completed shipment_id=%s thread_id=%s attempted=%s moved=%s failed=%s reason=%s",
        shipment.id,
        shipment.email_thread_id,
        len(messages),
        len(moved),
        len(failed),
        reason,
    )
    return {
        "attempted": True,
        "status": "completed" if not failed else "partial_failed",
        "attempted_count": len(messages),
        "moved": len(moved),
        "failed": len(failed),
    }
