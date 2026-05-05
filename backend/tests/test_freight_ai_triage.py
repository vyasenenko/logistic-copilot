"""LLM-assisted email triage (falls back to heuristics when no model)."""

import pytest

from app.schemas import EmailTriageClassification
from app.services import freight_ai
from app.services.email_fraud import FraudReasonCode
from app.services.email_triage import classify_email_triage_heuristic


@pytest.mark.asyncio
async def test_classify_email_triage_with_ai_skips_llm_when_no_model(monkeypatch):
    monkeypatch.setattr(freight_ai, "_choose_llm", lambda: None)
    kwargs = dict(
        subject="Re: Quote ABC",
        body_preview="900$ same day.",
        sender_email="carrier@example.com",
        quote_token="Q-TOKEN",
        existing_shipment_linked=True,
    )
    expected = classify_email_triage_heuristic(**kwargs)
    got = await freight_ai.classify_email_triage_with_ai(**kwargs)
    assert got.classification == expected.classification
    assert got.recommended_action == expected.recommended_action


@pytest.mark.asyncio
async def test_classify_email_triage_with_ai_skips_llm_on_fraud_heuristic(monkeypatch):
    called = {"n": 0}

    async def _fake_invoke(*args, **kwargs):
        called["n"] += 1
        raise AssertionError("LLM should not run when heuristic fraud")

    monkeypatch.setattr(freight_ai, "_invoke_structured_with_fallback", _fake_invoke)
    monkeypatch.setattr(freight_ai, "_choose_llm", lambda: object())

    got = await freight_ai.classify_email_triage_with_ai(
        subject="Wire payment now",
        body_preview="Pay invoice https://evil.example/pay",
        sender_email="billing@evil.example",
        fraud_reasons=[FraudReasonCode.DENYLISTED_SENDER_EMAIL.value],
    )
    assert got.classification == EmailTriageClassification.FRAUD_OR_PHISHING
    assert called["n"] == 0
