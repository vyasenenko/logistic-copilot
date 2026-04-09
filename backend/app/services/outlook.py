"""Microsoft Graph client for Outlook mailbox automation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app.config import settings


@dataclass(slots=True)
class OutlookMessageRef:
    """Minimal identifiers needed for message/thread correlation."""

    message_id: str
    internet_message_id: str | None = None
    conversation_id: str | None = None


@dataclass(slots=True)
class OutlookMailboxMessage:
    """Normalized Outlook message payload used by the freight workflow."""

    provider_message_id: str
    conversation_id: str | None
    internet_message_id: str | None
    subject: str
    body_preview: str
    sender_email: str
    sender_name: str | None
    recipients: list[str]
    received_at: datetime
    raw_payload: dict


class OutlookGraphClient:
    """Thin Microsoft Graph wrapper for mailbox operations.

    This is intentionally small for the first foundation pass. Business workflow
    orchestration should call this service, not embed Graph logic in agent prompts.
    """

    required_settings = (
        "microsoft_tenant_id",
        "microsoft_client_id",
        "microsoft_client_secret",
        "microsoft_mailbox",
    )

    def __init__(self) -> None:
        self.base_url = settings.microsoft_graph_base_url.rstrip("/")

    def missing_settings(self) -> list[str]:
        missing = []
        for field_name in self.required_settings:
            if not getattr(settings, field_name):
                missing.append(field_name)
        return missing

    def is_configured(self) -> bool:
        return not self.missing_settings()

    async def fetch_access_token(self) -> str:
        """Acquire an application token for Microsoft Graph."""
        missing = self.missing_settings()
        if missing:
            raise RuntimeError(
                "Microsoft Graph is not configured. Missing: " + ", ".join(missing)
            )

        payload = {
            "client_id": settings.microsoft_client_id,
            "client_secret": settings.microsoft_client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(settings.microsoft_token_url, data=payload)
            response.raise_for_status()
            data = response.json()

        token = data.get("access_token")
        if not token:
            raise RuntimeError("Microsoft Graph token response did not include access_token")
        return token

    async def health_check(self) -> dict:
        """Return configuration-aware health details for the Outlook integration."""
        missing = self.missing_settings()
        details = {
            "mailbox": settings.microsoft_mailbox or None,
            "base_url": self.base_url,
        }

        if missing:
            return {
                "configured": False,
                "status": "missing_configuration",
                "missing_fields": missing,
                "details": details,
            }

        return {
            "configured": True,
            "status": "configured",
            "missing_fields": [],
            "details": details,
        }

    async def _authorized_client(self) -> httpx.AsyncClient:
        token = await self.fetch_access_token()
        return httpx.AsyncClient(
            timeout=30,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )

    def normalize_message(self, payload: dict) -> OutlookMailboxMessage:
        """Convert a Graph message payload into a stable internal shape."""
        sender = (payload.get("from") or {}).get("emailAddress") or {}
        to_recipients = payload.get("toRecipients") or []
        received_raw = payload.get("receivedDateTime")
        received_at = datetime.now(timezone.utc)
        if received_raw:
            received_at = datetime.fromisoformat(received_raw.replace("Z", "+00:00"))

        return OutlookMailboxMessage(
            provider_message_id=payload.get("id", ""),
            conversation_id=payload.get("conversationId"),
            internet_message_id=payload.get("internetMessageId"),
            subject=payload.get("subject", ""),
            body_preview=payload.get("bodyPreview", ""),
            sender_email=(sender.get("address") or "").lower(),
            sender_name=sender.get("name"),
            recipients=[
                ((recipient.get("emailAddress") or {}).get("address") or "").lower()
                for recipient in to_recipients
                if (recipient.get("emailAddress") or {}).get("address")
            ],
            received_at=received_at,
            raw_payload=payload,
        )

    async def list_messages(self, limit: int = 10) -> list[OutlookMailboxMessage]:
        """Fetch recent inbox messages from the configured Outlook mailbox."""
        missing = self.missing_settings()
        if missing:
            raise RuntimeError(
                "Microsoft Graph is not configured. Missing: " + ", ".join(missing)
            )

        url = f"{self.base_url}/users/{settings.microsoft_mailbox}/mailFolders/inbox/messages"
        params = {
            "$top": str(limit),
            "$orderby": "receivedDateTime desc",
            "$select": (
                "id,conversationId,internetMessageId,subject,bodyPreview,"
                "from,toRecipients,receivedDateTime"
            ),
        }

        async with await self._authorized_client() as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

        return [self.normalize_message(item) for item in data.get("value", [])]

    async def send_mail(
        self,
        *,
        subject: str,
        body: str,
        recipients: list[str],
        save_to_sent_items: bool = True,
    ) -> dict:
        """Send an email from the configured Outlook mailbox."""
        missing = self.missing_settings()
        if missing:
            raise RuntimeError(
                "Microsoft Graph is not configured. Missing: " + ", ".join(missing)
            )
        if not recipients:
            raise RuntimeError("At least one recipient is required to send email")

        url = f"{self.base_url}/users/{settings.microsoft_mailbox}/sendMail"
        payload = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": "Text",
                    "content": body,
                },
                "toRecipients": [
                    {"emailAddress": {"address": recipient}}
                    for recipient in recipients
                ],
            },
            "saveToSentItems": save_to_sent_items,
        }

        async with await self._authorized_client() as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()

        return {
            "subject": subject,
            "recipients": recipients,
            "save_to_sent_items": save_to_sent_items,
            "provider": "outlook",
        }
