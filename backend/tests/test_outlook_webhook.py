from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.services.outlook import OutlookGraphClient, OutlookGraphCredentials


def _test_client() -> OutlookGraphClient:
    creds = OutlookGraphCredentials(
        tenant_id="tenant",
        client_id="cid",
        client_secret="sec",
        mailbox="example@contoso.com",
        organization_id=uuid4(),
    )
    return OutlookGraphClient(
        creds,
        webhook_notification_url="https://bc08-87-196-72-44.ngrok-free.app/api/freight/outlook/webhook",
        webhook_resource="users/example@contoso.com/mailFolders('Inbox')/messages",
        webhook_client_state="org:deadbeef",
        webhook_change_type="created",
    )


@pytest.mark.asyncio
async def test_ensure_inbox_webhook_subscription_reuses_active_subscription(monkeypatch):
    client = _test_client()

    async def _list_subscriptions():
        return [
            {
                "id": "sub-1",
                "notificationUrl": "https://bc08-87-196-72-44.ngrok-free.app/api/freight/outlook/webhook",
                "resource": "users/example@contoso.com/mailFolders('Inbox')/messages",
                "changeType": "created",
                "expirationDateTime": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat().replace("+00:00", "Z"),
            }
        ]

    monkeypatch.setattr(client, "webhook_is_configured", lambda: True)
    monkeypatch.setattr(client, "list_subscriptions", _list_subscriptions)
    monkeypatch.setattr(client, "create_webhook_subscription", lambda: pytest.fail("should not create"))
    monkeypatch.setattr(client, "renew_webhook_subscription", lambda _subscription_id: pytest.fail("should not renew"))

    result = await client.ensure_inbox_webhook_subscription()

    assert result["id"] == "sub-1"
    assert result["subscriptionAction"] == "reused"


@pytest.mark.asyncio
async def test_ensure_inbox_webhook_subscription_renews_expiring_subscription(monkeypatch):
    client = _test_client()

    async def _list_subscriptions():
        return [
            {
                "id": "sub-1",
                "notificationUrl": "https://bc08-87-196-72-44.ngrok-free.app/api/freight/outlook/webhook",
                "resource": "users/example@contoso.com/mailFolders('Inbox')/messages",
                "changeType": "created",
                "expirationDateTime": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
            }
        ]

    async def _renew(subscription_id: str):
        return {"id": subscription_id, "expirationDateTime": "2026-04-27T10:00:00Z"}

    monkeypatch.setattr(client, "webhook_is_configured", lambda: True)
    monkeypatch.setattr(client, "list_subscriptions", _list_subscriptions)
    monkeypatch.setattr(client, "renew_webhook_subscription", _renew)
    monkeypatch.setattr(client, "create_webhook_subscription", lambda: pytest.fail("should not create"))

    result = await client.ensure_inbox_webhook_subscription()

    assert result["id"] == "sub-1"
    assert result["subscriptionAction"] == "renewed"


@pytest.mark.asyncio
async def test_ensure_inbox_webhook_subscription_creates_when_missing(monkeypatch):
    client = _test_client()

    async def _list_subscriptions():
        return []

    async def _create():
        return {"id": "sub-new", "expirationDateTime": "2026-04-27T10:00:00Z"}

    monkeypatch.setattr(client, "webhook_is_configured", lambda: True)
    monkeypatch.setattr(client, "list_subscriptions", _list_subscriptions)
    monkeypatch.setattr(client, "create_webhook_subscription", _create)

    result = await client.ensure_inbox_webhook_subscription()

    assert result["id"] == "sub-new"
    assert result["subscriptionAction"] == "created"
