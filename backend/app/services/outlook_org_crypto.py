"""Encrypt/decrypt organization Microsoft client secrets at rest."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


def _fernet() -> Fernet:
    raw = settings.outlook_credentials_fernet_key.strip()
    if not raw:
        raise RuntimeError(
            "OUTLOOK_CREDENTIALS_FERNET_KEY is not set; required to store Outlook client secrets."
        )
    return Fernet(raw.encode("ascii"))


def encrypt_outlook_client_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_outlook_client_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("Failed to decrypt Outlook client secret") from exc
