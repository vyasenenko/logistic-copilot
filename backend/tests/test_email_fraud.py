from app.services.email_fraud import assess_sender_risk


def test_assess_sender_risk_exact_known_sender_is_low():
    result = assess_sender_risk(
        sender_email="ops@company.com",
        sender_name="Company Logistics",
        known_senders={"ops@company.com"},
        known_domains={"company.com"},
    )

    assert result.risk_level == "low"
    assert result.sender_known is True
    assert result.verification_required is False
    assert result.recommended_action == "allow"


def test_assess_sender_risk_unknown_sender_requires_verification():
    result = assess_sender_risk(
        sender_email="new@unknownshipper.com",
        sender_name="Unknown Shipper",
        known_senders={"ops@company.com"},
        known_domains={"company.com"},
    )

    assert result.risk_level == "medium"
    assert result.sender_known is False
    assert result.verification_required is True
    assert result.recommended_action == "verify"
    assert "unknown_sender" in result.reasons


def test_assess_sender_risk_digit_swapped_domain_is_high():
    result = assess_sender_risk(
        sender_email="quotes@c0mpany.com",
        sender_name="Company Dispatch",
        known_senders={"ops@company.com"},
        known_domains={"company.com"},
    )

    assert result.risk_level == "high"
    assert result.recommended_action == "block_automation"
    assert "digit_swapped_domain" in result.reasons


def test_assess_sender_risk_punycode_domain_is_high():
    result = assess_sender_risk(
        sender_email="quotes@xn--company-9db.com",
        sender_name="Company Dispatch",
        known_senders={"ops@company.com"},
        known_domains={"company.com"},
    )

    assert result.risk_level == "high"
    assert "punycode_domain" in result.reasons


def test_assess_sender_risk_display_name_domain_mismatch_is_medium():
    result = assess_sender_risk(
        sender_email="quotes@carrier-mail.net",
        sender_name="Company Logistics",
        known_senders={"ops@company.com"},
        known_domains={"company.com"},
    )

    assert result.risk_level in {"medium", "high"}
    assert "display_name_domain_mismatch" in result.reasons
