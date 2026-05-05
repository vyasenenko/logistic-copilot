"""Load per-organization Outlook / Graph credentials and build OutlookGraphClient instances."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.memory.database import EmailConnection, EmailThread, OrganizationOutlookCredentials, Shipment
from app.services.outlook import OutlookGraphClient, OutlookGraphCredentials
from app.services.outlook_org_crypto import decrypt_outlook_client_secret
from app.services.outlook_webhook_state import sign_outlook_webhook_client_state


def inbox_subscription_resource(mailbox: str) -> str:
    normalized = mailbox.strip()
    return f"users/{normalized}/mailFolders('Inbox')/messages"


def mailbox_from_graph_resource(resource: str | None) -> str | None:
    if not resource:
        return None
    parts = resource.strip("/").split("/")
    if len(parts) >= 2 and parts[0].lower() == "users":
        return parts[1].strip().lower()
    return None


async def get_organization_outlook_row(
    session: AsyncSession,
    organization_id: UUID,
) -> OrganizationOutlookCredentials | None:
    return await session.get(OrganizationOutlookCredentials, organization_id)


def missing_fields_for_outlook_row(row: OrganizationOutlookCredentials | None) -> list[str]:
    if row is None:
        return ["tenant_id", "client_id", "client_secret"]
    missing: list[str] = []
    if not (row.tenant_id or "").strip():
        missing.append("tenant_id")
    if not (row.client_id or "").strip():
        missing.append("client_id")
    if not (row.client_secret_encrypted or "").strip():
        missing.append("client_secret")
    return missing


async def organization_outlook_mailbox(session: AsyncSession, organization_id: UUID | None) -> str:
    if organization_id is None:
        return "unknown"
    row = await get_organization_outlook_row(session, organization_id)
    if row and row.mailbox and str(row.mailbox).strip():
        return str(row.mailbox).strip().lower()
    return "unknown"


async def build_outlook_graph_client(
    session: AsyncSession,
    organization_id: UUID,
    *,
    mailbox: str | None = None,
    email_connection_id: UUID | None = None,
) -> OutlookGraphClient:
    row = await get_organization_outlook_row(session, organization_id)
    if row is None:
        raise RuntimeError(
            "Microsoft Graph is not configured for this organization. Missing: tenant_id, client_id, client_secret"
        )
    missing: list[str] = []
    tenant = (row.tenant_id or "").strip()
    client_id = (row.client_id or "").strip()
    target_mailbox = (mailbox or row.mailbox or "").strip().lower()
    enc = row.client_secret_encrypted or ""
    if not tenant:
        missing.append("tenant_id")
    if not client_id:
        missing.append("client_id")
    if not enc:
        missing.append("client_secret")
    if not target_mailbox:
        missing.append("mailbox")
    if missing:
        raise RuntimeError(
            "Microsoft Graph is not configured for this organization. Missing: " + ", ".join(missing)
        )
    try:
        client_secret = decrypt_outlook_client_secret(enc)
    except RuntimeError:
        raise
    creds = OutlookGraphCredentials(
        tenant_id=tenant,
        client_id=client_id,
        client_secret=client_secret,
        mailbox=target_mailbox,
        organization_id=organization_id,
    )
    notification_url = (settings.microsoft_webhook_notification_url or "").strip()
    resource = inbox_subscription_resource(target_mailbox)
    client_state = sign_outlook_webhook_client_state(organization_id, email_connection_id)
    return OutlookGraphClient(
        creds,
        webhook_notification_url=notification_url,
        webhook_resource=resource,
        webhook_client_state=client_state,
        webhook_change_type=settings.microsoft_webhook_change_type,
    )


async def graph_mailbox_for_email_thread(
    session: AsyncSession,
    *,
    organization_id: UUID,
    email_thread_id: UUID | None,
) -> tuple[str | None, UUID | None]:
    """Return Graph ``mailbox`` and optional ``EmailConnection`` id for a thread, if resolvable."""
    if not email_thread_id:
        return None, None
    thread = await session.get(EmailThread, email_thread_id)
    if thread is None or not (thread.mailbox or "").strip():
        return None, None
    mailbox = str(thread.mailbox).strip().lower()
    conn_id = await session.scalar(
        select(EmailConnection.id)
        .where(
            EmailConnection.organization_id == organization_id,
            EmailConnection.provider == "outlook",
            func.lower(EmailConnection.mailbox) == mailbox,
        )
        .limit(1)
    )
    return mailbox, conn_id


async def build_outlook_graph_client_for_shipment(
    session: AsyncSession,
    shipment: Shipment,
) -> OutlookGraphClient:
    """Graph client scoped to the shipment's email thread mailbox when known.

    Uses ``EmailThread.mailbox`` so replies/sends go through the same M365 mailbox as the thread.
    Falls back to ``OrganizationOutlookCredentials.mailbox`` when the thread is missing or has no mailbox.
    """
    org_id = shipment.organization_id
    if org_id is None:
        raise RuntimeError("Shipment has no organization_id; cannot build Microsoft Graph client.")

    mailbox, email_connection_id = await graph_mailbox_for_email_thread(
        session,
        organization_id=org_id,
        email_thread_id=shipment.email_thread_id,
    )
    return await build_outlook_graph_client(
        session,
        org_id,
        mailbox=mailbox,
        email_connection_id=email_connection_id,
    )


async def apply_graph_subscription_to_org(
    session: AsyncSession,
    organization_id: UUID,
    subscription: dict,
) -> None:
    row = await get_organization_outlook_row(session, organization_id)
    if row is None:
        return
    sub_id = subscription.get("id")
    exp_raw = subscription.get("expirationDateTime")
    row.graph_subscription_id = str(sub_id) if sub_id else None
    if isinstance(exp_raw, str) and exp_raw.strip():
        try:
            row.subscription_expires_at = datetime.fromisoformat(exp_raw.replace("Z", "+00:00"))
        except ValueError:
            row.subscription_expires_at = None
    else:
        row.subscription_expires_at = None
    row.updated_at = datetime.now(timezone.utc)


async def apply_graph_subscription_to_email_connection(
    session: AsyncSession,
    email_connection_id: UUID,
    subscription: dict | None,
) -> None:
    connection = await session.get(EmailConnection, email_connection_id)
    if connection is None:
        return
    if not subscription:
        connection.graph_subscription_id = None
        connection.subscription_expires_at = None
        connection.updated_at = datetime.now(timezone.utc)
        return
    sub_id = subscription.get("id")
    exp_raw = subscription.get("expirationDateTime")
    connection.graph_subscription_id = str(sub_id) if sub_id else None
    if isinstance(exp_raw, str) and exp_raw.strip():
        try:
            connection.subscription_expires_at = datetime.fromisoformat(exp_raw.replace("Z", "+00:00"))
        except ValueError:
            connection.subscription_expires_at = None
    else:
        connection.subscription_expires_at = None
    connection.updated_at = datetime.now(timezone.utc)


async def sync_email_connection_for_outlook_mailbox(
    session: AsyncSession,
    *,
    user_id: UUID,
    organization_id: UUID,
    mailbox: str,
) -> None:
    normalized = mailbox.strip().lower()
    if not normalized:
        return
    existing = await session.scalar(
        select(EmailConnection).where(
            EmailConnection.organization_id == organization_id,
            EmailConnection.provider == "outlook",
            EmailConnection.mailbox == normalized,
        )
    )
    if existing is not None:
        existing.status = "active"
        existing.user_id = user_id
        existing.updated_at = datetime.now(timezone.utc)
        return
    session.add(
        EmailConnection(
            user_id=user_id,
            organization_id=organization_id,
            provider="outlook",
            mailbox=normalized,
            status="active",
            metadata_json={"source": "outlook_credentials_settings"},
        )
    )


async def outlook_mailbox_conflict_other_org(
    session: AsyncSession,
    *,
    mailbox: str,
    organization_id: UUID,
) -> bool:
    normalized = mailbox.strip().lower()
    if not normalized:
        return False
    other = await session.scalar(
        select(OrganizationOutlookCredentials.organization_id).where(
            func.lower(OrganizationOutlookCredentials.mailbox) == normalized,
            OrganizationOutlookCredentials.organization_id != organization_id,
        )
    )
    return other is not None
