from datetime import datetime, timedelta, timezone

import pytest

from app.services.outlook import OutlookGraphClient


@pytest.mark.asyncio
async def test_ensure_inbox_webhook_subscription_reuses_active_subscription(monkeypatch):
    client = OutlookGraphClient()

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
    monkeypatch.setattr("app.services.outlook.settings.microsoft_webhook_public_base_url", "https://bc08-87-196-72-44.ngrok-free.app", raising=False)
    monkeypatch.setattr("app.services.outlook.settings.microsoft_mailbox", "example@contoso.com", raising=False)
    monkeypatch.setattr("app.services.outlook.settings.microsoft_webhook_change_type", "created", raising=False)

    result = await client.ensure_inbox_webhook_subscription()

    assert result["id"] == "sub-1"
    assert result["subscriptionAction"] == "reused"


@pytest.mark.asyncio
async def test_ensure_inbox_webhook_subscription_renews_expiring_subscription(monkeypatch):
    client = OutlookGraphClient()

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
    monkeypatch.setattr("app.services.outlook.settings.microsoft_webhook_public_base_url", "https://bc08-87-196-72-44.ngrok-free.app", raising=False)
    monkeypatch.setattr("app.services.outlook.settings.microsoft_mailbox", "example@contoso.com", raising=False)
    monkeypatch.setattr("app.services.outlook.settings.microsoft_webhook_change_type", "created", raising=False)

    result = await client.ensure_inbox_webhook_subscription()

    assert result["id"] == "sub-1"
    assert result["subscriptionAction"] == "renewed"


@pytest.mark.asyncio
async def test_ensure_inbox_webhook_subscription_creates_when_missing(monkeypatch):
    client = OutlookGraphClient()

    async def _list_subscriptions():
        return []

    async def _create():
        return {"id": "sub-new", "expirationDateTime": "2026-04-27T10:00:00Z"}

    monkeypatch.setattr(client, "webhook_is_configured", lambda: True)
    monkeypatch.setattr(client, "list_subscriptions", _list_subscriptions)
    monkeypatch.setattr(client, "create_webhook_subscription", _create)
    monkeypatch.setattr("app.services.outlook.settings.microsoft_webhook_public_base_url", "https://bc08-87-196-72-44.ngrok-free.app", raising=False)
    monkeypatch.setattr("app.services.outlook.settings.microsoft_mailbox", "example@contoso.com", raising=False)
    monkeypatch.setattr("app.services.outlook.settings.microsoft_webhook_change_type", "created", raising=False)

    result = await client.ensure_inbox_webhook_subscription()

    assert result["id"] == "sub-new"
    assert result["subscriptionAction"] == "created"
