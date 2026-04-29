"""Pre-shipment email triage for Outlook intake."""

from __future__ import annotations

import re

from app.schemas import EmailTriageClassification, EmailTriageResult
from app.services.email_fraud import FraudReasonCode

PAYMENT_PHISHING_RE = re.compile(
    r"\b(invoice|payment|pay|wire|bank|overdue|past due|24\s*hours?|click|link|portal|account suspended|verify account)\b",
    re.IGNORECASE,
)
URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
FREIGHT_RE = re.compile(
    r"\b(load|shipment|quote|rate|pickup|delivery|origin|destination|pallet|weight|reefer|dry\s*van|flatbed|truck|lane|carrier|ftl|ltl)\b",
    re.IGNORECASE,
)
ROUTE_RE = re.compile(r"\b[A-Z][a-zA-Z .'-]+,\s*[A-Z]{2}\b.*\b[A-Z][a-zA-Z .'-]+,\s*[A-Z]{2}\b")
STATUS_RE = re.compile(r"\b(status|eta|delivered|picked up|in transit|pod|bol|appointment)\b", re.IGNORECASE)
BID_RE = re.compile(r"\$\s*\d+|\b\d+(?:\.\d+)?\s*(?:all in|usd|dollars?)\b", re.IGNORECASE)
NEWSLETTER_RE = re.compile(r"\b(unsubscribe|newsletter|marketing|webinar|promotion|sale|digest)\b", re.IGNORECASE)


def classify_email_triage(
    *,
    subject: str,
    body_preview: str,
    sender_email: str,
    quote_token: str | None = None,
    existing_shipment_linked: bool = False,
    fraud_reasons: list[str] | None = None,
    fraud_risk_level: str | None = None,
) -> EmailTriageResult:
    """Classify whether an email should create/link a shipment or stay in triage."""
    text = f"{subject or ''}\n{body_preview or ''}"
    lowered = text.lower()
    reasons = set(fraud_reasons or [])

    if {FraudReasonCode.DENYLISTED_SENDER_EMAIL.value, FraudReasonCode.DENYLISTED_SENDER_DOMAIN.value} & reasons:
        return EmailTriageResult(
            classification=EmailTriageClassification.FRAUD_OR_PHISHING,
            confidence=1.0,
            reason="Sender matched fraud denylist.",
            recommended_action="mark_fraud_email",
            signals={"fraud_risk_level": fraud_risk_level, "fraud_reasons": list(reasons)},
        )

    payment_like = bool(PAYMENT_PHISHING_RE.search(text))
    has_url = bool(URL_RE.search(text))
    freight_like = bool(FREIGHT_RE.search(text))
    if payment_like and has_url and not freight_like:
        return EmailTriageResult(
            classification=EmailTriageClassification.FRAUD_OR_PHISHING,
            confidence=0.94,
            reason="Payment/invoice urgency with external link and no freight context.",
            recommended_action="mark_fraud_email",
            signals={"payment_like": True, "has_url": True},
        )

    if quote_token or existing_shipment_linked:
        if STATUS_RE.search(text):
            return EmailTriageResult(
                classification=EmailTriageClassification.STATUS_OR_OPS,
                confidence=0.82,
                reason="Correlated shipment thread with status/ops language.",
                recommended_action="link_to_existing_shipment",
                signals={"quote_token": quote_token, "existing_shipment_linked": existing_shipment_linked},
            )
        if BID_RE.search(text) or "rate" in lowered:
            return EmailTriageResult(
                classification=EmailTriageClassification.CARRIER_REPLY,
                confidence=0.84,
                reason="Correlated shipment thread with carrier bid/rate language.",
                recommended_action="link_to_existing_shipment",
                signals={"quote_token": quote_token, "existing_shipment_linked": existing_shipment_linked},
            )
        return EmailTriageResult(
            classification=EmailTriageClassification.NEEDS_OPERATOR_TRIAGE,
            confidence=0.62,
            reason="Message is correlated to a shipment but intent is unclear.",
            recommended_action="link_to_existing_shipment",
            signals={"quote_token": quote_token, "existing_shipment_linked": existing_shipment_linked},
        )

    route_like = bool(ROUTE_RE.search(text))
    if freight_like and (route_like or any(token in lowered for token in ("pickup", "delivery", "pallet", "weight", "dry van", "reefer"))):
        return EmailTriageResult(
            classification=EmailTriageClassification.FREIGHT_QUOTE_REQUEST,
            confidence=0.86 if route_like else 0.72,
            reason="Freight quote/load language detected before shipment creation.",
            recommended_action="create_shipment",
            signals={"freight_like": True, "route_like": route_like},
        )

    if NEWSLETTER_RE.search(text):
        return EmailTriageResult(
            classification=EmailTriageClassification.NOISE_OR_UNHANDLED,
            confidence=0.88,
            reason="Marketing/newsletter style email with no shipment signal.",
            recommended_action="mark_not_shipment",
            signals={"newsletter_like": True},
        )

    if payment_like and not freight_like:
        return EmailTriageResult(
            classification=EmailTriageClassification.FRAUD_OR_PHISHING,
            confidence=0.78,
            reason="Payment/invoice language without freight context.",
            recommended_action="mark_fraud_email",
            signals={"payment_like": True},
        )

    if freight_like:
        return EmailTriageResult(
            classification=EmailTriageClassification.NEEDS_OPERATOR_TRIAGE,
            confidence=0.58,
            reason="Some freight language found, but not enough to safely create a shipment.",
            recommended_action="create_shipment",
            signals={"freight_like": True},
        )

    return EmailTriageResult(
        classification=EmailTriageClassification.NOISE_OR_UNHANDLED,
        confidence=0.74,
        reason="No shipment, carrier, route, or quote signal detected.",
        recommended_action="mark_not_shipment",
        signals={"sender_email": sender_email},
    )
