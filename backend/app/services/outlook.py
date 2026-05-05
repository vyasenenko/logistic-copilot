"""Microsoft Graph client for Outlook mailbox automation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from uuid import UUID

import httpx

from app.config import settings

logger = logging.getLogger(__name__)
OUTLOOK_WEBHOOK_MAX_EXPIRATION_MINUTES = 10070


def _graph_error_body(response: httpx.Response) -> str:
    try:
        data = response.json()
        err = data.get("error") if isinstance(data, dict) else None
        if isinstance(err, dict):
            code = (err.get("code") or "").strip()
            msg = (err.get("message") or "").strip()
            if code and msg:
                return f"{code}: {msg}"
            return msg or code or (response.text or "")[:800]
    except Exception:
        pass
    return (response.text or "")[:800]


def _raise_graph_http(
    response: httpx.Response,
    *,
    operation: str,
    mailbox_for_hint: str | None = None,
) -> None:
    if response.is_success:
        return
    detail = _graph_error_body(response)
    request = response.request
    hint = ""
    mb = mailbox_for_hint or "configured mailbox"
    if response.status_code == 403:
        hint = (
            " Add Microsoft Graph Application permissions (e.g. Mail.Read or Mail.ReadWrite), "
            "click Grant admin consent, and if the tenant uses Exchange Online application access policies, "
            f"allow this app for mailbox {mb!r}."
        )
    elif response.status_code == 401:
        hint = " Check client id, secret value (not Secret ID), and tenant id."
    raise RuntimeError(
        "Microsoft Graph HTTP "
        f"{response.status_code} ({operation}) "
        f"[{request.method} {request.url}]: {detail}{hint}"
    )


@dataclass(slots=True)
class OutlookGraphCredentials:
    tenant_id: str
    client_id: str
    client_secret: str
    mailbox: str
    organization_id: UUID | None = None


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
    in_reply_to: str | None = None
    references: list[str] | None = None


class OutlookGraphClient:
    """Microsoft Graph wrapper scoped to one mailbox and app registration."""

    def __init__(
        self,
        credentials: OutlookGraphCredentials,
        *,
        webhook_notification_url: str = "",
        webhook_resource: str = "",
        webhook_client_state: str = "",
        webhook_change_type: str | None = None,
    ) -> None:
        self._creds = credentials
        self._webhook_notification_url = (webhook_notification_url or "").strip()
        self._webhook_resource = (webhook_resource or "").strip()
        self._webhook_client_state = webhook_client_state or ""
        self._webhook_change_type = (webhook_change_type or settings.microsoft_webhook_change_type or "created").strip()
        self.base_url = settings.microsoft_graph_base_url.rstrip("/")

    @property
    def mailbox(self) -> str:
        return self._creds.mailbox.strip()

    @property
    def organization_id(self) -> UUID | None:
        return self._creds.organization_id

    def _token_url(self) -> str:
        tenant = self._creds.tenant_id.strip()
        return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

    def missing_settings(self) -> list[str]:
        missing: list[str] = []
        if not self._creds.tenant_id.strip():
            missing.append("tenant_id")
        if not self._creds.client_id.strip():
            missing.append("client_id")
        if not self._creds.client_secret.strip():
            missing.append("client_secret")
        if not self._creds.mailbox.strip():
            missing.append("mailbox")
        return missing

    def is_configured(self) -> bool:
        return not self.missing_settings()

    def webhook_is_configured(self) -> bool:
        return bool(
            self.is_configured()
            and self._webhook_notification_url
            and self._webhook_resource
            and self._webhook_client_state
        )

    def webhook_subscription_payload(self) -> dict:
        if not self.webhook_is_configured():
            raise RuntimeError("Outlook webhook subscription is not fully configured")
        expiration_minutes = min(
            max(45, settings.microsoft_webhook_expiration_minutes),
            OUTLOOK_WEBHOOK_MAX_EXPIRATION_MINUTES,
        )
        expiration = datetime.now(timezone.utc) + timedelta(minutes=expiration_minutes)
        return {
            "changeType": self._webhook_change_type,
            "notificationUrl": self._webhook_notification_url,
            "resource": self._webhook_resource,
            "expirationDateTime": expiration.isoformat().replace("+00:00", "Z"),
            "clientState": self._webhook_client_state,
            "latestSupportedTlsVersion": "v1_2",
        }

    async def fetch_access_token(self) -> str:
        missing = self.missing_settings()
        if missing:
            raise RuntimeError("Microsoft Graph is not configured. Missing: " + ", ".join(missing))

        payload = {
            "client_id": self._creds.client_id.strip(),
            "client_secret": self._creds.client_secret.strip(),
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(self._token_url(), data=payload)
            _raise_graph_http(response, operation="token (client credentials)", mailbox_for_hint=self.mailbox)
            data = response.json()

        token = data.get("access_token")
        if not token:
            raise RuntimeError("Microsoft Graph token response did not include access_token")
        return token

    async def health_check(self) -> dict:
        missing = self.missing_settings()
        details = {
            "mailbox": self.mailbox or None,
            "base_url": self.base_url,
            "webhook_client_state_configured": bool(self._webhook_client_state),
            "webhook_endpoint": "/api/freight/outlook/webhook",
            "webhook_notification_url": self._webhook_notification_url or None,
            "webhook_resource": self._webhook_resource or None,
        }

        if missing:
            return {
                "configured": False,
                "status": "missing_configuration",
                "missing_fields": list(missing),
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

    async def _fetch_message_attachments(
        self,
        client: httpx.AsyncClient,
        *,
        message_id: str,
    ) -> list[dict]:
        url = f"{self.base_url}/users/{self.mailbox}/messages/{message_id}/attachments"
        params = {
            "$top": "10",
            "$select": "id,name,contentType,size,isInline,contentBytes",
        }
        response = await client.get(url, params=params)
        _raise_graph_http(response, operation="list attachments", mailbox_for_hint=self.mailbox)
        data = response.json()
        return [item for item in data.get("value", []) if isinstance(item, dict)]

    def normalize_message(self, payload: dict) -> OutlookMailboxMessage:
        """Convert a Graph message payload into a stable internal shape."""
        sender = (payload.get("from") or {}).get("emailAddress") or {}
        to_recipients = payload.get("toRecipients") or []
        received_raw = payload.get("receivedDateTime")
        received_at = datetime.now(timezone.utc)
        if received_raw:
            received_at = datetime.fromisoformat(received_raw.replace("Z", "+00:00"))
        headers = {
            str(header.get("name") or "").strip().lower(): str(header.get("value") or "").strip()
            for header in (payload.get("internetMessageHeaders") or [])
            if isinstance(header, dict)
        }
        references = [ref.strip() for ref in headers.get("references", "").split() if ref.strip()]

        return OutlookMailboxMessage(
            provider_message_id=payload.get("id", ""),
            conversation_id=payload.get("conversationId"),
            internet_message_id=payload.get("internetMessageId"),
            in_reply_to=headers.get("in-reply-to") or None,
            references=references,
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
        missing = self.missing_settings()
        if missing:
            raise RuntimeError("Microsoft Graph is not configured. Missing: " + ", ".join(missing))

        url = f"{self.base_url}/users/{self.mailbox}/mailFolders/inbox/messages"
        params = {
            "$top": str(limit),
            "$orderby": "receivedDateTime desc",
            "$select": (
                "id,conversationId,internetMessageId,subject,bodyPreview,"
                "from,toRecipients,receivedDateTime,hasAttachments,internetMessageHeaders"
            ),
        }

        async with await self._authorized_client() as client:
            response = await client.get(url, params=params)
            _raise_graph_http(response, operation="list inbox messages", mailbox_for_hint=self.mailbox)
            data = response.json()
            items = [item for item in data.get("value", []) if isinstance(item, dict)]
            for item in items:
                if not item.get("hasAttachments") or not item.get("id"):
                    continue
                try:
                    item["attachments"] = await self._fetch_message_attachments(
                        client,
                        message_id=str(item["id"]),
                    )
                except Exception:
                    item["attachments"] = []

        return [self.normalize_message(item) for item in items]

    async def get_message(self, message_id: str) -> OutlookMailboxMessage:
        missing = self.missing_settings()
        if missing:
            raise RuntimeError("Microsoft Graph is not configured. Missing: " + ", ".join(missing))
        if not message_id:
            raise RuntimeError("Outlook message id is required")

        url = f"{self.base_url}/users/{self.mailbox}/messages/{message_id}"
        params = {
            "$select": (
                "id,conversationId,internetMessageId,subject,bodyPreview,"
                "from,toRecipients,receivedDateTime,hasAttachments,internetMessageHeaders"
            ),
        }

        async with await self._authorized_client() as client:
            response = await client.get(url, params=params)
            _raise_graph_http(response, operation="get message", mailbox_for_hint=self.mailbox)
            item = response.json()
            if not isinstance(item, dict):
                raise RuntimeError("Microsoft Graph get message returned an invalid payload")
            if item.get("hasAttachments") and item.get("id"):
                try:
                    item["attachments"] = await self._fetch_message_attachments(
                        client,
                        message_id=str(item["id"]),
                    )
                except Exception:
                    item["attachments"] = []

        return self.normalize_message(item)

    async def mark_message_read(self, message_id: str) -> dict:
        missing = self.missing_settings()
        if missing:
            raise RuntimeError("Microsoft Graph is not configured. Missing: " + ", ".join(missing))
        if not message_id:
            raise RuntimeError("Outlook message id is required")

        url = f"{self.base_url}/users/{self.mailbox}/messages/{message_id}"
        async with await self._authorized_client() as client:
            response = await client.patch(url, json={"isRead": True})
            _raise_graph_http(response, operation="mark message read", mailbox_for_hint=self.mailbox)

        return {"provider": "outlook", "message_id": message_id, "is_read": True}

    async def list_master_categories(self) -> list[dict]:
        missing = self.missing_settings()
        if missing:
            raise RuntimeError("Microsoft Graph is not configured. Missing: " + ", ".join(missing))
        url = f"{self.base_url}/users/{self.mailbox}/outlook/masterCategories"
        async with await self._authorized_client() as client:
            response = await client.get(url)
            _raise_graph_http(response, operation="list master categories", mailbox_for_hint=self.mailbox)
            data = response.json()
        return [item for item in data.get("value", []) if isinstance(item, dict)]

    async def ensure_master_categories(self, category_colors: dict[str, str]) -> dict:
        clean = {name.strip(): color.strip() for name, color in category_colors.items() if name.strip() and color.strip()}
        if not clean:
            return {"created": [], "existing": [], "failed": []}

        url = f"{self.base_url}/users/{self.mailbox}/outlook/masterCategories"
        async with await self._authorized_client() as client:
            response = await client.get(url)
            _raise_graph_http(response, operation="list master categories", mailbox_for_hint=self.mailbox)
            data = response.json()
            existing_items = [item for item in data.get("value", []) if isinstance(item, dict)]
            existing_by_name = {
                str(item.get("displayName") or "").strip().lower(): item
                for item in existing_items
                if str(item.get("displayName") or "").strip()
            }
            created: list[dict] = []
            failed: list[dict] = []
            for display_name, color in clean.items():
                if display_name.lower() in existing_by_name:
                    continue
                create_response = await client.post(url, json={"displayName": display_name, "color": color})
                if create_response.is_success:
                    payload = create_response.json() if create_response.content else {}
                    created.append(
                        {
                            "displayName": display_name,
                            "color": color,
                            "id": payload.get("id") if isinstance(payload, dict) else None,
                        }
                    )
                    continue
                if create_response.status_code == 409:
                    continue
                failed.append(
                    {
                        "displayName": display_name,
                        "color": color,
                        "error": _graph_error_body(create_response),
                        "status_code": create_response.status_code,
                    }
                )

        if failed:
            logger.warning("Graph master category sync had failures: %s", failed)
        return {
            "created": created,
            "existing": [
                str(item.get("displayName"))
                for item in existing_items
                if str(item.get("displayName") or "").strip().lower() in {name.lower() for name in clean}
            ],
            "failed": failed,
        }

    async def add_message_categories(
        self,
        message_id: str,
        categories: list[str],
        category_colors: dict[str, str] | None = None,
    ) -> dict:
        missing = self.missing_settings()
        if missing:
            raise RuntimeError("Microsoft Graph is not configured. Missing: " + ", ".join(missing))
        if not message_id:
            raise RuntimeError("Outlook message id is required")

        clean_categories = [category.strip() for category in categories if category.strip()]
        if not clean_categories:
            return {"provider": "outlook", "message_id": message_id, "categories": [], "changed": False}

        url = f"{self.base_url}/users/{self.mailbox}/messages/{message_id}"
        async with await self._authorized_client() as client:
            master_category_result: dict | None = None
            if category_colors:
                master_url = f"{self.base_url}/users/{self.mailbox}/outlook/masterCategories"
                master_response = await client.get(master_url)
                if master_response.is_success:
                    master_data = master_response.json()
                    existing_items = [item for item in master_data.get("value", []) if isinstance(item, dict)]
                    existing_names = {
                        str(item.get("displayName") or "").strip().lower()
                        for item in existing_items
                        if str(item.get("displayName") or "").strip()
                    }
                    created: list[dict] = []
                    failed: list[dict] = []
                    for display_name, color in category_colors.items():
                        display_name = display_name.strip()
                        color = color.strip()
                        if not display_name or not color or display_name.lower() in existing_names:
                            continue
                        create_response = await client.post(
                            master_url,
                            json={"displayName": display_name, "color": color},
                        )
                        if create_response.is_success:
                            payload = create_response.json() if create_response.content else {}
                            created.append(
                                {
                                    "displayName": display_name,
                                    "color": color,
                                    "id": payload.get("id") if isinstance(payload, dict) else None,
                                }
                            )
                            existing_names.add(display_name.lower())
                        elif create_response.status_code != 409:
                            failed.append(
                                {
                                    "displayName": display_name,
                                    "color": color,
                                    "error": _graph_error_body(create_response),
                                    "status_code": create_response.status_code,
                                }
                            )
                    if failed:
                        logger.warning("Graph master category sync had failures: %s", failed)
                    master_category_result = {"created": created, "failed": failed}
                else:
                    logger.warning(
                        "Graph master category sync skipped; plain message categories will still be applied: %s",
                        _graph_error_body(master_response),
                    )
                    master_category_result = {
                        "created": [],
                        "failed": [
                            {
                                "operation": "list_master_categories",
                                "status_code": master_response.status_code,
                                "error": _graph_error_body(master_response),
                            }
                        ],
                        "fallback": "plain_message_categories",
                    }

            response = await client.get(url, params={"$select": "id,categories"})
            _raise_graph_http(response, operation="get message categories", mailbox_for_hint=self.mailbox)
            current_payload = response.json()
            existing = current_payload.get("categories") if isinstance(current_payload, dict) else []
            if not isinstance(existing, list):
                existing = []
            merged = list(dict.fromkeys([str(item) for item in existing] + clean_categories))
            response = await client.patch(url, json={"categories": merged})
            _raise_graph_http(response, operation="set message categories", mailbox_for_hint=self.mailbox)

        return {
            "provider": "outlook",
            "message_id": message_id,
            "categories": merged,
            "added_categories": clean_categories,
            "master_category_result": master_category_result,
            "changed": merged != existing,
        }

    async def _resolve_archive_folder_id(self, client: httpx.AsyncClient) -> str:
        url = f"{self.base_url}/users/{self.mailbox}/mailFolders/archive"
        response = await client.get(url, params={"$select": "id,displayName"})
        if response.is_success:
            data = response.json()
            folder_id = data.get("id") if isinstance(data, dict) else None
            if folder_id:
                return str(folder_id)
        logger.warning(
            "Graph archive folder lookup failed; falling back to well-known archive folder name: %s",
            _graph_error_body(response),
        )
        return "archive"

    async def move_message_to_archive(self, message_id: str) -> dict:
        missing = self.missing_settings()
        if missing:
            raise RuntimeError("Microsoft Graph is not configured. Missing: " + ", ".join(missing))
        if not message_id:
            raise RuntimeError("Outlook message id is required")

        async with await self._authorized_client() as client:
            archive_folder_id = await self._resolve_archive_folder_id(client)
            url = f"{self.base_url}/users/{self.mailbox}/messages/{message_id}/move"
            response = await client.post(url, json={"destinationId": archive_folder_id})
            _raise_graph_http(response, operation="move message to archive", mailbox_for_hint=self.mailbox)
            moved = response.json() if response.content else {}

        return {
            "provider": "outlook",
            "message_id": message_id,
            "archive_folder_id": archive_folder_id,
            "moved_message_id": moved.get("id") if isinstance(moved, dict) else None,
        }

    async def send_mail(
        self,
        *,
        subject: str,
        body: str,
        recipients: list[str],
        save_to_sent_items: bool = True,
    ) -> dict:
        missing = self.missing_settings()
        if missing:
            raise RuntimeError("Microsoft Graph is not configured. Missing: " + ", ".join(missing))
        if not recipients:
            raise RuntimeError("At least one recipient is required to send email")

        url = f"{self.base_url}/users/{self.mailbox}/sendMail"
        effective_sender = self.mailbox
        payload = {
            "message": {
                "subject": subject,
                "body": {"contentType": "Text", "content": body},
                "from": {"emailAddress": {"address": effective_sender}},
                "sender": {"emailAddress": {"address": effective_sender}},
                "toRecipients": [{"emailAddress": {"address": recipient}} for recipient in recipients],
            },
            "saveToSentItems": save_to_sent_items,
        }

        async with await self._authorized_client() as client:
            response = await client.post(url, json=payload)
            _raise_graph_http(response, operation="sendMail", mailbox_for_hint=self.mailbox)

        return {
            "subject": subject,
            "recipients": recipients,
            "save_to_sent_items": save_to_sent_items,
            "provider": "outlook",
            "sender_address": effective_sender,
        }

    async def reply_to_message(
        self,
        *,
        message_id: str,
        body: str,
        recipients: list[str] | None = None,
    ) -> dict:
        missing = self.missing_settings()
        if missing:
            raise RuntimeError("Microsoft Graph is not configured. Missing: " + ", ".join(missing))
        if not message_id:
            raise RuntimeError("A provider message id is required to send an email reply")

        url = f"{self.base_url}/users/{self.mailbox}/messages/{message_id}/reply"
        message: dict = {"body": {"contentType": "Text", "content": body}}
        if recipients:
            message["toRecipients"] = [{"emailAddress": {"address": recipient}} for recipient in recipients]
        payload = {"message": message}

        async with await self._authorized_client() as client:
            response = await client.post(url, json=payload)
            _raise_graph_http(response, operation="reply", mailbox_for_hint=self.mailbox)

        return {
            "provider": "outlook",
            "reply_to_provider_message_id": message_id,
            "recipients": recipients or [],
            "sender_address": self.mailbox,
        }

    async def list_subscriptions(self) -> list[dict]:
        missing = self.missing_settings()
        if missing:
            raise RuntimeError("Microsoft Graph is not configured. Missing: " + ", ".join(missing))
        url = f"{self.base_url}/subscriptions"
        logger.info("Graph webhook: listing subscriptions from %s", url)
        async with await self._authorized_client() as client:
            response = await client.get(url)
            _raise_graph_http(response, operation="list subscriptions", mailbox_for_hint=self.mailbox)
            data = response.json()
        return [item for item in data.get("value", []) if isinstance(item, dict)]

    async def create_webhook_subscription(self) -> dict:
        payload = self.webhook_subscription_payload()
        url = f"{self.base_url}/subscriptions"
        logger.info(
            "Graph webhook: creating subscription notification_url=%r resource=%r change_type=%r",
            payload.get("notificationUrl"),
            payload.get("resource"),
            payload.get("changeType"),
        )
        async with await self._authorized_client() as client:
            response = await client.post(url, json=payload)
            _raise_graph_http(response, operation="create subscription", mailbox_for_hint=self.mailbox)
            return response.json()

    async def renew_webhook_subscription(self, subscription_id: str) -> dict:
        if not subscription_id:
            raise RuntimeError("Subscription id is required for renewal")
        expiration_minutes = min(
            max(45, settings.microsoft_webhook_expiration_minutes),
            OUTLOOK_WEBHOOK_MAX_EXPIRATION_MINUTES,
        )
        expiration = datetime.now(timezone.utc) + timedelta(minutes=expiration_minutes)
        payload = {"expirationDateTime": expiration.isoformat().replace("+00:00", "Z")}
        url = f"{self.base_url}/subscriptions/{subscription_id}"
        logger.info(
            "Graph webhook: renewing subscription id=%s expiration=%s",
            subscription_id,
            payload["expirationDateTime"],
        )
        async with await self._authorized_client() as client:
            response = await client.patch(url, json=payload)
            _raise_graph_http(response, operation="renew subscription", mailbox_for_hint=self.mailbox)
            return response.json()

    async def delete_subscription(self, subscription_id: str) -> None:
        if not subscription_id:
            raise RuntimeError("Subscription id is required for deletion")
        url = f"{self.base_url}/subscriptions/{subscription_id}"
        async with await self._authorized_client() as client:
            response = await client.delete(url)
            _raise_graph_http(response, operation="delete subscription", mailbox_for_hint=self.mailbox)

    async def ensure_inbox_webhook_subscription(self) -> dict:
        if not self.webhook_is_configured():
            raise RuntimeError("Outlook webhook subscription is not fully configured")

        expected_url = self._webhook_notification_url
        expected_resource = self._webhook_resource
        expected_change_type = self._webhook_change_type
        now = datetime.now(timezone.utc)
        renew_before = now + timedelta(minutes=max(15, settings.microsoft_webhook_renewal_buffer_minutes))
        logger.info(
            "Graph webhook: ensure subscription started notification_url=%r resource=%r renew_before=%s",
            expected_url,
            expected_resource,
            renew_before.isoformat(),
        )

        subscriptions = await self.list_subscriptions()
        logger.info("Graph webhook: fetched %d subscriptions", len(subscriptions))
        matching: list[dict] = []
        for item in subscriptions:
            if item.get("notificationUrl") != expected_url:
                continue
            if item.get("resource") != expected_resource:
                continue
            if item.get("changeType") != expected_change_type:
                continue
            matching.append(item)

        if matching:
            logger.info("Graph webhook: found %d matching subscription(s)", len(matching))
            active_or_unknown: list[tuple[dict, datetime | None]] = []
            for item in matching:
                expiration = None
                expiration_raw = item.get("expirationDateTime")
                if isinstance(expiration_raw, str) and expiration_raw:
                    try:
                        expiration = datetime.fromisoformat(expiration_raw.replace("Z", "+00:00"))
                    except ValueError:
                        expiration = None

                subscription_id = item.get("id")
                if expiration is not None and expiration <= now:
                    if isinstance(subscription_id, str) and subscription_id:
                        try:
                            logger.info(
                                "Graph webhook: deleting expired matching subscription id=%s expiration=%s",
                                subscription_id,
                                expiration_raw,
                            )
                            await self.delete_subscription(subscription_id)
                        except Exception:
                            logger.warning(
                                "Failed to delete expired Graph subscription %s", subscription_id, exc_info=True
                            )
                    continue
                active_or_unknown.append((item, expiration))

            if not active_or_unknown:
                logger.info("Graph webhook: only expired matching subscriptions found, creating a new one.")
                created = await self.create_webhook_subscription()
                created["subscriptionAction"] = "created"
                return created

            primary, expiration = active_or_unknown[0]
            for duplicate, _duplicate_expiration in active_or_unknown[1:]:
                duplicate_id = duplicate.get("id")
                if isinstance(duplicate_id, str) and duplicate_id:
                    try:
                        await self.delete_subscription(duplicate_id)
                    except Exception:
                        logger.warning("Failed to delete duplicate Graph subscription %s", duplicate_id, exc_info=True)

            expiration_raw = primary.get("expirationDateTime")
            subscription_id = primary.get("id")
            if isinstance(subscription_id, str) and subscription_id and (expiration is None or expiration <= renew_before):
                logger.info(
                    "Graph webhook: renewing matching subscription id=%s expiration=%s",
                    subscription_id,
                    expiration_raw,
                )
                try:
                    renewed = await self.renew_webhook_subscription(subscription_id)
                except RuntimeError as exc:
                    if "Microsoft Graph HTTP 404" not in str(exc):
                        raise
                    logger.warning(
                        "Graph webhook: matching subscription disappeared during renewal; creating a new one.",
                        exc_info=True,
                    )
                    created = await self.create_webhook_subscription()
                    created["subscriptionAction"] = "created"
                    return created
                renewed["subscriptionAction"] = "renewed"
                return renewed

            logger.info(
                "Graph webhook: reusing active subscription id=%s expiration=%s",
                primary.get("id"),
                expiration_raw,
            )
            primary["subscriptionAction"] = "reused"
            return primary

        logger.info("Graph webhook: no matching subscription found, creating a new one.")
        created = await self.create_webhook_subscription()
        created["subscriptionAction"] = "created"
        return created
