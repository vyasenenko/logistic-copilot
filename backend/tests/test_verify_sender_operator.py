"""Operator sender-trust overlay on fraud projection (pure logic)."""

from datetime import datetime, timezone

from app.services.email_fraud import (
    apply_operator_sender_trust_to_fraud_projection,
    fraud_assessment_from_denylist_match,
)


def test_apply_operator_trust_clears_fraud_when_sender_matches():
    verified_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    out = apply_operator_sender_trust_to_fraud_projection(
        {
            "sender_email": "shipper@acme.test",
            "sender_verification_required": True,
            "fraud_risk_level": "high",
            "fraud_risk_reasons": ["lookalike_domain"],
            "fraud_score": 0.9,
        },
        {"verified_sender_email": "shipper@acme.test", "verified_at": verified_at},
    )
    assert out["sender_verification_required"] is False
    assert out["sender_known"] is True
    assert out["fraud_risk_level"] is None
    assert out["fraud_risk_reasons"] == []
    assert out["fraud_score"] is None
    assert out["sender_verified_at"] == verified_at
    assert out["sender_verified_for_email"] == "shipper@acme.test"


def test_apply_operator_trust_noop_when_sender_mismatch():
    out = apply_operator_sender_trust_to_fraud_projection(
        {
            "sender_email": "evil@acme.test",
            "sender_verification_required": True,
            "fraud_risk_level": "high",
        },
        {"verified_sender_email": "shipper@acme.test", "verified_at": datetime.now(timezone.utc)},
    )
    assert out["sender_verification_required"] is True
    assert out["fraud_risk_level"] == "high"


def test_apply_operator_domain_trust_clears_same_domain():
    verified_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    out = apply_operator_sender_trust_to_fraud_projection(
        {
            "sender_email": "ops@acme.test",
            "sender_verification_required": True,
            "fraud_risk_level": "medium",
            "fraud_risk_reasons": ["unknown_sender"],
            "fraud_score": 0.5,
        },
        {
            "verified_sender_email": "shipper@acme.test",
            "verified_sender_domain": "acme.test",
            "trust_scope": "sender_domain",
            "sender_role": "customer",
            "verified_at": verified_at,
        },
    )
    assert out["sender_verification_required"] is False
    assert out["fraud_risk_level"] is None
    assert out["sender_verified_for_domain"] == "acme.test"
    assert out["sender_verified_role"] == "customer"
    assert out["sender_verified_scope"] == "sender_domain"


def test_apply_operator_domain_trust_noop_for_different_domain():
    out = apply_operator_sender_trust_to_fraud_projection(
        {
            "sender_email": "ops@evil.test",
            "sender_verification_required": True,
            "fraud_risk_level": "medium",
        },
        {
            "verified_sender_email": "shipper@acme.test",
            "verified_sender_domain": "acme.test",
            "trust_scope": "sender_domain",
            "sender_role": "carrier",
            "verified_at": datetime.now(timezone.utc),
        },
    )
    assert out["sender_verification_required"] is True
    assert out["fraud_risk_level"] == "medium"


def test_denylist_match_builds_high_risk_assessment():
    assessment = fraud_assessment_from_denylist_match(
        sender_email="bad@fraud.test",
        scope="sender_domain",
        value="fraud.test",
    )

    assert assessment.risk_level == "high"
    assert assessment.recommended_action == "block_automation"
    assert assessment.verification_required is True
    assert assessment.reasons == ["denylisted_sender_domain"]
    assert assessment.sender_email == "bad@fraud.test"
    assert assessment.sender_domain == "fraud.test"


def test_operator_trust_does_not_clear_denylisted_sender():
    out = apply_operator_sender_trust_to_fraud_projection(
        {
            "sender_email": "bad@fraud.test",
            "sender_verification_required": True,
            "fraud_risk_level": "high",
            "reasons": ["denylisted_sender_email"],
        },
        {
            "verified_sender_email": "bad@fraud.test",
            "verified_sender_domain": "fraud.test",
            "trust_scope": "sender_email",
            "sender_role": "customer",
            "verified_at": datetime.now(timezone.utc),
        },
    )
    assert out["sender_verification_required"] is True
    assert out["fraud_risk_level"] == "high"
