"""Heuristics for sender verification and probable-fraud detection."""

from __future__ import annotations

from difflib import SequenceMatcher
from enum import Enum
import re

from app.schemas import (
    FraudAssessmentResult,
    FraudDenylistScope,
    FraudRecommendedAction,
    FraudRiskLevel,
    SenderTrustScope,
)

FREE_MAIL_DOMAINS = {
    "gmail.com",
    "hotmail.com",
    "icloud.com",
    "outlook.com",
    "yahoo.com",
    "aol.com",
    "proton.me",
    "protonmail.com",
    "fastmail.com",

}

DISPLAY_NAME_TOKEN_RE = re.compile(r"[a-z0-9]+")
DOMAIN_SPLIT_RE = re.compile(r"[.\-_]")
SUSPICIOUS_DIGIT_MAP = str.maketrans(
    {
        "0": "o",
        "1": "l",
        "3": "e",
        "4": "a",
        "5": "s",
        "7": "t",
        "8": "b",
    }
)


class FraudReasonCode(str, Enum):
    KNOWN_SENDER = "known_sender"
    UNKNOWN_SENDER = "unknown_sender"
    FREE_MAIL_DOMAIN = "free_mail_domain"
    PUNYCODE_DOMAIN = "punycode_domain"
    LOOKALIKE_DOMAIN = "lookalike_domain"
    DIGIT_SWAPPED_DOMAIN = "digit_swapped_domain"
    DOMAIN_SHAPE_SUSPICIOUS = "domain_shape_suspicious"
    DISPLAY_NAME_DOMAIN_MISMATCH = "display_name_domain_mismatch"
    DENYLISTED_SENDER_EMAIL = "denylisted_sender_email"
    DENYLISTED_SENDER_DOMAIN = "denylisted_sender_domain"


def _normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def _extract_domain(email: str | None) -> str:
    normalized = _normalize_email(email)
    if "@" not in normalized:
        return ""
    return normalized.split("@", 1)[1]


def normalize_sender_email(email: str | None) -> str:
    return _normalize_email(email)


def extract_sender_domain(email: str | None) -> str:
    return _extract_domain(email)


def fraud_assessment_from_denylist_match(
    *,
    sender_email: str,
    scope: FraudDenylistScope | str,
    value: str,
) -> FraudAssessmentResult:
    normalized_email = _normalize_email(sender_email)
    sender_domain = _extract_domain(normalized_email)
    scope_value = scope.value if isinstance(scope, FraudDenylistScope) else str(scope)
    reason = (
        FraudReasonCode.DENYLISTED_SENDER_DOMAIN.value
        if scope_value == FraudDenylistScope.SENDER_DOMAIN.value
        else FraudReasonCode.DENYLISTED_SENDER_EMAIL.value
    )
    return FraudAssessmentResult(
        risk_level=FraudRiskLevel.HIGH,
        reasons=[reason],
        recommended_action=FraudRecommendedAction.BLOCK_AUTOMATION,
        sender_known=False,
        verification_required=True,
        score=1.0,
        sender_email=normalized_email or None,
        sender_domain=sender_domain or None,
        matched_domain=value if scope_value == FraudDenylistScope.SENDER_DOMAIN.value else None,
        matched_identity=value if scope_value == FraudDenylistScope.SENDER_EMAIL.value else None,
    )


def _normalize_domain(domain: str | None) -> str:
    return (domain or "").strip().lower().rstrip(".")


def _domain_root(domain: str) -> str:
    parts = [part for part in DOMAIN_SPLIT_RE.split(_normalize_domain(domain)) if part]
    if not parts:
        return ""
    if len(parts) >= 2:
        return parts[-2]
    return parts[0]


def _skeleton(value: str) -> str:
    return _normalize_domain(value).translate(SUSPICIOUS_DIGIT_MAP)


def _display_name_tokens(name: str | None) -> set[str]:
    return {token for token in DISPLAY_NAME_TOKEN_RE.findall((name or "").lower()) if len(token) > 2}


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0
    return SequenceMatcher(a=left, b=right).ratio()


def assess_sender_risk(
    *,
    sender_email: str,
    sender_name: str | None = None,
    known_senders: set[str] | None = None,
    known_domains: set[str] | None = None,
) -> FraudAssessmentResult:
    normalized_email = _normalize_email(sender_email)
    sender_domain = _extract_domain(normalized_email)
    known_senders = {_normalize_email(item) for item in (known_senders or set()) if _normalize_email(item)}
    known_domains = {_normalize_domain(item) for item in (known_domains or set()) if _normalize_domain(item)}

    reasons: list[str] = []
    score = 0.0
    matched_domain: str | None = None
    matched_identity: str | None = None

    sender_known = normalized_email in known_senders
    if sender_known:
        reasons.append(FraudReasonCode.KNOWN_SENDER.value)
        matched_identity = normalized_email
    else:
        reasons.append(FraudReasonCode.UNKNOWN_SENDER.value)
        score = max(score, 0.35)

    if sender_domain.startswith("xn--"):
        reasons.append(FraudReasonCode.PUNYCODE_DOMAIN.value)
        score = max(score, 0.95)

    if sender_domain in FREE_MAIL_DOMAINS and not sender_known:
        reasons.append(FraudReasonCode.FREE_MAIL_DOMAIN.value)
        score = max(score, 0.55)

    if sender_domain.count("-") >= 2 or re.search(r"\d", _domain_root(sender_domain)):
        reasons.append(FraudReasonCode.DOMAIN_SHAPE_SUSPICIOUS.value)
        score = max(score, 0.65 if not sender_known else 0.45)

    sender_root = _domain_root(sender_domain)
    sender_skeleton = _skeleton(sender_root)
    best_similarity = 0.0
    best_domain = ""
    for domain in known_domains:
        domain_root = _domain_root(domain)
        if not domain_root or domain == sender_domain:
            continue
        similarity = _similarity(sender_root, domain_root)
        if _skeleton(domain_root) == sender_skeleton and sender_root != domain_root:
            reasons.append(FraudReasonCode.DIGIT_SWAPPED_DOMAIN.value)
            score = max(score, 0.97)
            matched_domain = domain
            break
        if similarity > best_similarity:
            best_similarity = similarity
            best_domain = domain

    if matched_domain is None and best_similarity >= 0.88 and best_domain:
        reasons.append(FraudReasonCode.LOOKALIKE_DOMAIN.value)
        score = max(score, 0.9)
        matched_domain = best_domain

    display_tokens = _display_name_tokens(sender_name)
    if display_tokens and known_domains:
        known_roots = {_domain_root(domain) for domain in known_domains}
        if any(token in known_roots for token in display_tokens) and sender_root not in known_roots:
            reasons.append(FraudReasonCode.DISPLAY_NAME_DOMAIN_MISMATCH.value)
            score = max(score, 0.72 if not sender_known else 0.55)

    verification_required = not sender_known
    if sender_known and score < 0.5:
        risk_level = FraudRiskLevel.LOW
        action = FraudRecommendedAction.ALLOW
        score = min(score, 0.25)
    elif score >= 0.85:
        risk_level = FraudRiskLevel.HIGH
        action = FraudRecommendedAction.BLOCK_AUTOMATION
    elif verification_required or score >= 0.45:
        risk_level = FraudRiskLevel.MEDIUM
        action = FraudRecommendedAction.VERIFY
        score = max(score, 0.5 if verification_required else score)
    else:
        risk_level = FraudRiskLevel.LOW
        action = FraudRecommendedAction.ALLOW

    return FraudAssessmentResult(
        risk_level=risk_level,
        reasons=list(dict.fromkeys(reasons)),
        recommended_action=action,
        sender_known=sender_known,
        verification_required=verification_required,
        score=min(max(score, 0.0), 1.0),
        sender_email=normalized_email or None,
        sender_domain=sender_domain or None,
        matched_domain=matched_domain,
        matched_identity=matched_identity,
    )


def apply_operator_sender_trust_to_fraud_projection(fraud: dict | None, verification: dict | None) -> dict:
    """Clear blocking fraud projection when operator confirmed trust for the same inbound sender."""
    base = dict(fraud or {})
    reasons = {str(reason) for reason in list(base.get("reasons", []) or [])}
    if {
        FraudReasonCode.DENYLISTED_SENDER_EMAIL.value,
        FraudReasonCode.DENYLISTED_SENDER_DOMAIN.value,
    } & reasons:
        return base
    if not verification:
        return base
    trust_scope = str(verification.get("trust_scope") or SenderTrustScope.SENDER_EMAIL.value)
    verified_email = str(verification.get("verified_sender_email") or "").strip().lower()
    verified_domain = str(verification.get("verified_sender_domain") or "").strip().lower().rstrip(".")
    inbound_email = str(base.get("sender_email") or "").strip().lower()
    inbound_domain = _extract_domain(inbound_email)
    trusted = (
        bool(verified_domain and inbound_domain and verified_domain == inbound_domain)
        if trust_scope == SenderTrustScope.SENDER_DOMAIN.value
        else bool(verified_email and inbound_email and inbound_email == verified_email)
    )
    if not trusted:
        return base
    base["sender_verification_required"] = False
    base["sender_known"] = True
    base["fraud_risk_level"] = None
    base["fraud_risk_reasons"] = []
    base["fraud_score"] = None
    base["sender_verified_at"] = verification.get("verified_at")
    base["sender_verified_for_email"] = verification.get("verified_sender_email")
    base["sender_verified_for_domain"] = verification.get("verified_sender_domain")
    base["sender_verified_role"] = verification.get("sender_role")
    base["sender_verified_scope"] = trust_scope
    return base
