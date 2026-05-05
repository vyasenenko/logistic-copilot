"""Invite email delivery via Resend."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import invite_email


@pytest.mark.asyncio
async def test_send_skipped_without_resend_api_key(monkeypatch):
    monkeypatch.setattr(invite_email.settings, "resend_api_key", "")
    monkeypatch.setattr(invite_email.settings, "resend_from_email", "App <noreply@example.com>")
    monkeypatch.setattr(invite_email.settings, "public_app_base_url", "http://localhost:3000")

    ctor = MagicMock()
    with patch.object(invite_email.httpx, "AsyncClient", ctor):
        await invite_email.send_invite_email_if_configured(
            to_email="user@company.com",
            raw_token="raw-token",
            organization_name="Acme Logistics",
            role="member",
            inviter_email="admin@company.com",
            invite_ttl_days=7,
        )

    ctor.assert_not_called()


@pytest.mark.asyncio
async def test_send_skipped_without_public_app_base_url(monkeypatch):
    monkeypatch.setattr(invite_email.settings, "resend_api_key", "re_key")
    monkeypatch.setattr(invite_email.settings, "resend_from_email", "App <noreply@example.com>")
    monkeypatch.setattr(invite_email.settings, "public_app_base_url", "   ")

    ctor = MagicMock()
    with patch.object(invite_email.httpx, "AsyncClient", ctor):
        await invite_email.send_invite_email_if_configured(
            to_email="user@company.com",
            raw_token="raw-token",
            organization_name="Acme Logistics",
            role="owner",
            inviter_email=None,
            invite_ttl_days=7,
        )

    ctor.assert_not_called()


@pytest.mark.asyncio
async def test_send_posts_to_resend_when_configured(monkeypatch):
    monkeypatch.setattr(invite_email.settings, "resend_api_key", "re_test_secret")
    monkeypatch.setattr(invite_email.settings, "resend_from_email", "Logistic Copilot <noreply@example.com>")
    monkeypatch.setattr(invite_email.settings, "public_app_base_url", "https://app.example.com")

    post_mock = AsyncMock(return_value=MagicMock(status_code=200, text='{"id":"em_1"}'))

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        post = post_mock

    with patch.object(invite_email.httpx, "AsyncClient", return_value=FakeClient()):
        await invite_email.send_invite_email_if_configured(
            to_email="user@company.com",
            raw_token="secret-invite-token",
            organization_name="Acme Logistics",
            role="member",
            inviter_email="admin@company.com",
            invite_ttl_days=7,
        )

    post_mock.assert_awaited_once()
    call_kw = post_mock.call_args[1]
    assert post_mock.call_args[0][0] == invite_email.RESEND_SEND_URL
    payload = call_kw["json"]
    assert payload["to"] == ["user@company.com"]
    assert payload["from"] == "Logistic Copilot <noreply@example.com>"
    assert "secret-invite-token" in payload["html"]
    assert "https://app.example.com/invite?" in payload["html"]
    headers = call_kw["headers"]
    assert headers["Authorization"] == "Bearer re_test_secret"


@pytest.mark.asyncio
async def test_send_logs_on_http_error(monkeypatch, caplog):
    monkeypatch.setattr(invite_email.settings, "resend_api_key", "re_test_secret")
    monkeypatch.setattr(invite_email.settings, "resend_from_email", "App <noreply@example.com>")
    monkeypatch.setattr(invite_email.settings, "public_app_base_url", "https://app.example.com")

    post_mock = AsyncMock(return_value=MagicMock(status_code=422, text="invalid payload"))

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        post = post_mock

    with patch.object(invite_email.httpx, "AsyncClient", return_value=FakeClient()):
        await invite_email.send_invite_email_if_configured(
            to_email="user@company.com",
            raw_token="tok",
            organization_name="Acme",
            role="viewer",
            inviter_email=None,
            invite_ttl_days=7,
        )

    assert post_mock.await_count == 1
    assert "Resend invite email failed" in caplog.text
