from uuid import uuid4

import pytest

from app.api import freight
from app.schemas import OutlookIngestResult


class DummySession:
    pass


@pytest.mark.asyncio
async def test_process_outlook_message_blocks_automation_for_high_risk_sender(monkeypatch):
    session = DummySession()
    inbox_result = OutlookIngestResult(
        thread_id=str(uuid4()),
        email_message_id=str(uuid4()),
        shipment_id=str(uuid4()),
        created_message=True,
        sender_verification_required=True,
        fraud_risk_level="high",
        fraud_risk_reasons=["digit_swapped_domain"],
        fraud_score=0.97,
        sender_email="quotes@c0mpany.com",
        sender_domain="c0mpany.com",
    )

    async def _ingest(*args, **kwargs):
        return inbox_result

    async def _fail_orchestrator(*args, **kwargs):
        raise AssertionError("orchestrator should not be called for flagged senders")

    gate_calls: list[str] = []

    async def _gate(_session, *, result):
        gate_calls.append(result.email_message_id)
        result.manual_review_required = True
        result.next_action = "probable_fraud_review"

    monkeypatch.setattr(freight, "ingest_outlook_message", _ingest)
    monkeypatch.setattr(freight, "run_freight_inbox_orchestrator", _fail_orchestrator)
    monkeypatch.setattr(freight, "_apply_sender_risk_gate", _gate)

    result = await freight._process_outlook_mailbox_message(
        session,
        mailbox_message=object(),
        policy=freight.AutomationPolicy(),
    )

    assert result is not None
    assert result.manual_review_required is True
    assert result.next_action == "probable_fraud_review"
    assert gate_calls == [inbox_result.email_message_id]


@pytest.mark.asyncio
async def test_process_outlook_message_keeps_automation_for_low_risk_sender(monkeypatch):
    session = DummySession()
    inbox_result = OutlookIngestResult(
        thread_id=str(uuid4()),
        email_message_id=str(uuid4()),
        shipment_id=str(uuid4()),
        created_message=True,
        sender_verification_required=False,
        fraud_risk_level="low",
    )

    async def _ingest(*args, **kwargs):
        return inbox_result

    async def _orchestrator(*args, **kwargs):
        return freight.WorkflowDecisionResult(
            email_message_id=inbox_result.email_message_id,
            shipment_id=inbox_result.shipment_id,
            intent="new_quote_request",
            confidence=0.91,
            next_action="workflow_already_current",
        )

    async def _noop(*args, **kwargs):
        return {"attempted": False}

    monkeypatch.setattr(freight, "ingest_outlook_message", _ingest)
    monkeypatch.setattr(freight, "run_freight_inbox_orchestrator", _orchestrator)
    monkeypatch.setattr(freight, "add_email_message_categories", _noop)
    monkeypatch.setattr(freight, "mark_email_message_read_after_ai_success", _noop)

    result = await freight._process_outlook_mailbox_message(
        session,
        mailbox_message=object(),
        policy=freight.AutomationPolicy(),
    )

    assert result is not None
    assert result.manual_review_required is False
    assert result.intent == "new_quote_request"
    assert result.next_action == "workflow_already_current"


@pytest.mark.asyncio
async def test_process_outlook_message_triage_skip_does_not_run_orchestrator(monkeypatch):
    session = DummySession()
    inbox_result = OutlookIngestResult(
        thread_id=str(uuid4()),
        email_message_id=str(uuid4()),
        shipment_id="",
        created_message=True,
        shipment_creation_skipped=True,
        triage_classification="fraud_or_phishing",
        triage_reason="Payment link without freight context.",
        fraud_risk_level="high",
    )

    async def _ingest(*args, **kwargs):
        return inbox_result

    async def _fail_orchestrator(*args, **kwargs):
        raise AssertionError("orchestrator should not be called for triage-skipped email")

    category_calls: list[list[str]] = []

    async def _categories(*args, **kwargs):
        category_calls.append(kwargs.get("categories", []))
        return {"attempted": False}

    monkeypatch.setattr(freight, "ingest_outlook_message", _ingest)
    monkeypatch.setattr(freight, "run_freight_inbox_orchestrator", _fail_orchestrator)
    monkeypatch.setattr(freight, "add_email_message_categories", _categories)

    result = await freight._process_outlook_mailbox_message(
        session,
        mailbox_message=object(),
        policy=freight.AutomationPolicy(),
    )

    assert result is not None
    assert result.next_action == "fraud_triage"
    assert result.shipment_id == ""
    assert category_calls
