from app.services.outlook_mail_actions import outlook_categories_for_fraud_assessment


def test_outlook_categories_for_new_sender_verification():
    categories = outlook_categories_for_fraud_assessment(
        sender_verification_required=True,
        fraud_risk_level=None,
    )

    assert categories == ["🆕 New Sender", "⚠️ Verify Sender"]


def test_outlook_categories_for_medium_risk_sender():
    categories = outlook_categories_for_fraud_assessment(
        sender_verification_required=True,
        fraud_risk_level="medium",
    )

    assert "🆕 New Sender" in categories
    assert "⚠️ Verify Sender" in categories
    assert "👀 Needs Review" in categories


def test_outlook_categories_for_high_risk_sender():
    categories = outlook_categories_for_fraud_assessment(
        sender_verification_required=True,
        fraud_risk_level="high",
    )

    assert "‼️ Probable Fraud" in categories
    assert "👀 Needs Review" in categories
