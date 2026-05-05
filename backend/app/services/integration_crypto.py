"""Shared encryption helpers for organization integration credentials."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


def _fernet() -> Fernet:
    raw = settings.outlook_credentials_fernet_key.strip()
    if not raw:
        raise RuntimeError(
            "OUTLOOK_CREDENTIALS_FERNET_KEY is not set; required to store integration secrets."
        )
    return Fernet(raw.encode("ascii"))


def encrypt_integration_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_integration_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("Failed to decrypt integration secret") from exc
