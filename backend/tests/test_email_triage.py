from app.services.email_triage import classify_email_triage


def test_triage_phishing_invoice_skips_shipment():
    result = classify_email_triage(
        subject="Pay invoice in 24 hours",
        body_preview="Click https://fraud.example/pay now or your account will be suspended.",
        sender_email="billing@fraud.test",
    )

    assert result.classification == "fraud_or_phishing"
    assert result.recommended_action == "mark_fraud_email"


def test_triage_newsletter_noise_skips_shipment():
    result = classify_email_triage(
        subject="April logistics newsletter",
        body_preview="Read our marketing digest and unsubscribe here.",
        sender_email="news@example.com",
    )

    assert result.classification == "noise_or_unhandled"
    assert result.recommended_action == "mark_not_shipment"


def test_triage_real_quote_request_creates_shipment():
    result = classify_email_triage(
        subject="Quote request",
        body_preview="Need a dry van load pickup Chicago, IL delivery Dallas, TX, 10 pallets, 20000 lb.",
        sender_email="shipper@example.com",
    )

    assert result.classification == "freight_quote_request"
    assert result.recommended_action == "create_shipment"


def test_triage_correlated_carrier_reply_links_existing_shipment():
    result = classify_email_triage(
        subject="Re: LCQ-123456",
        body_preview="We can do this load for $1800 all in.",
        sender_email="carrier@example.com",
        quote_token="LCQ-123456",
        existing_shipment_linked=True,
    )

    assert result.classification == "carrier_reply"
    assert result.recommended_action == "link_to_existing_shipment"


def test_triage_uncertain_freight_email_needs_operator():
    result = classify_email_triage(
        subject="Possible load",
        body_preview="Can you check availability for a shipment next week?",
        sender_email="shipper@example.com",
    )

    assert result.classification == "needs_operator_triage"
    assert result.recommended_action == "create_shipment"
