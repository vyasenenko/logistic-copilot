"""Deterministic helpers for correlating email replies to quote workflows."""

from __future__ import annotations

import re
from uuid import uuid4

from app.schemas import EmailCorrelationSignals, QuoteReference

QUOTE_TOKEN_PATTERN = re.compile(r"\[(Q-[A-Z0-9]{8})\]")
SUBJECT_PREFIX_PATTERN = re.compile(r"^(re|fw|fwd)\s*:\s*", re.IGNORECASE)


def generate_quote_reference() -> QuoteReference:
    """Generate a short quote identifier safe for email subjects."""
    quote_id = uuid4().hex[:8].upper()
    return QuoteReference(quote_id=quote_id, subject_token=f"Q-{quote_id}")


def attach_quote_token(subject: str, subject_token: str) -> str:
    """Append a stable quote token to the subject when absent."""
    if subject_token in subject:
        return subject
    return f"{subject.strip()} [{subject_token}]".strip()


def extract_quote_token(subject: str) -> str | None:
    """Extract the stable quote token from an email subject."""
    match = QUOTE_TOKEN_PATTERN.search(subject or "")
    if not match:
        return None
    return match.group(1)


def normalize_subject(subject: str) -> str:
    """Normalize a subject for fallback reply matching."""
    normalized = (subject or "").strip()
    while True:
        updated = SUBJECT_PREFIX_PATTERN.sub("", normalized).strip()
        if updated == normalized:
            break
        normalized = updated
    return " ".join(normalized.split()).lower()


def build_correlation_signals(
    *,
    subject: str,
    sender: str | None = None,
    internet_message_id: str | None = None,
    in_reply_to: str | None = None,
    references: list[str] | None = None,
    conversation_id: str | None = None,
) -> EmailCorrelationSignals:
    """Build all non-LLM signals used to correlate email replies."""
    return EmailCorrelationSignals(
        internet_message_id=internet_message_id,
        in_reply_to=in_reply_to,
        references=references or [],
        conversation_id=conversation_id,
        subject=subject,
        normalized_subject=normalize_subject(subject),
        quote_token=extract_quote_token(subject),
        sender=sender.lower() if sender else None,
    )