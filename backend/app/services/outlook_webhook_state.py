"""Signed clientState for Microsoft Graph webhook notifications (organization routing)."""

from __future__ import annotations

import hashlib
import hmac
from uuid import UUID

from app.config import settings


def _state_signing_key() -> bytes:
    secret = (settings.outlook_webhook_state_secret or settings.api_secret_key).encode("utf-8")
    return secret


def sign_outlook_webhook_client_state(organization_id: UUID, email_connection_id: UUID | None = None) -> str:
    subject = str(organization_id)
    if email_connection_id is not None:
        subject = f"{organization_id}.{email_connection_id}"
    subject_bytes = subject.encode("utf-8")
    # Microsoft Graph clientState is capped, so keep a 128-bit HMAC prefix.
    sig = hmac.new(_state_signing_key(), subject_bytes, hashlib.sha256).hexdigest()[:32]
    return f"{subject}:{sig}"


def parse_outlook_webhook_client_state(value: str | None) -> tuple[UUID, UUID | None] | None:
    if not value or ":" not in value:
        return None
    subject, sig = value.rsplit(":", 1)
    if len(sig) not in {32, 64}:
        return None
    parts = subject.split(".", 1)
    try:
        org_id = UUID(parts[0])
        email_connection_id = UUID(parts[1]) if len(parts) == 2 and parts[1] else None
    except ValueError:
        return None
    normalized_subject = str(org_id)
    if email_connection_id is not None:
        normalized_subject = f"{org_id}.{email_connection_id}"
    expected_full = hmac.new(
        _state_signing_key(),
        normalized_subject.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    expected = expected_full[: len(sig)]
    if not hmac.compare_digest(expected, sig):
        return None
    return org_id, email_connection_id
