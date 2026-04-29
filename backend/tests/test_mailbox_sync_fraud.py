from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.memory.database import EmailMessage, EmailTriageItem, FraudDenylistEntry, Shipment, WorkflowEvent
from app.schemas import EmailTriageClassification
from app.services import mailbox_sync
from app.services.outlook import OutlookMailboxMessage


class FakeScalarList:
    def __init__(self, values):
        self._values = values

    def all(self):
        return list(self._values)

    def first(self):
        return self._values[0] if self._values else None


class FakeExecuteResult:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return FakeScalarList(self._values)


class FakeSession:
    def __init__(self, *, scalar_results, execute_results):
        self.scalar_results = list(scalar_results)
        self.execute_results = list(execute_results)
        self.added = []
        self.committed = False

    async def scalar(self, _query):
        return self.scalar_results.pop(0) if self.scalar_results else None

    async def execute(self, _query):
        values = self.execute_results.pop(0) if self.execute_results else []
        return FakeExecuteResult(values)

    def add(self, instance):
        self.added.append(instance)

    async def flush(self):
        for instance in self.added:
            if getattr(instance, "id", None) is None:
                instance.id = uuid4()

    async def commit(self):
        self.committed = True


def test_q_token_reply_reaches_ai_even_when_triage_intent_is_unclear():
    should_materialize = mailbox_sync._should_materialize_shipment_for_triage(
        classification=EmailTriageClassification.NEEDS_OPERATOR_TRIAGE,
        quote_token="Q-12345678",
        existing_shipment_linked=False,
    )

    assert should_materialize is True


def test_existing_shipment_reply_reaches_ai_even_without_q_token():
    should_materialize = mailbox_sync._should_materialize_shipment_for_triage(
        classification=EmailTriageClassification.NEEDS_OPERATOR_TRIAGE,
        quote_token=None,
        existing_shipment_linked=True,
    )

    assert should_materialize is True


def test_correlated_carrier_reply_reaches_ai_flow():
    should_materialize = mailbox_sync._should_materialize_shipment_for_triage(
        classification=EmailTriageClassification.CARRIER_REPLY,
        quote_token="Q-12345678",
        existing_shipment_linked=True,
    )

    assert should_materialize is True


def test_fraud_triage_still_blocks_q_token_materialization():
    should_materialize = mailbox_sync._should_materialize_shipment_for_triage(
        classification=EmailTriageClassification.FRAUD_OR_PHISHING,
        quote_token="Q-12345678",
        existing_shipment_linked=True,
    )

    assert should_materialize is False


@pytest.mark.asyncio
async def test_ingest_outlook_message_flags_unknown_sender_and_skips_client_creation(monkeypatch):
    session = FakeSession(
        scalar_results=[
            None,  # existing EmailMessage
            None,  # existing shipment
            None,  # carrier by exact email
            None,  # client by exact email
            None,  # existing shipment during materialization
        ],
        execute_results=[
            [],  # fraud denylist entries
            ["ops@company.com"],  # known client emails
            [],  # known carrier emails
        ],
    )
    message = OutlookMailboxMessage(
        provider_message_id="msg-1",
        conversation_id=None,
        internet_message_id="<msg-1@example.com>",
        subject="Quote request",
        body_preview="Need a quote pickup Chicago, IL delivery New York, NY dry van 5 pallets 12000 lb",
        sender_email="quotes@c0mpany.com",
        sender_name="Company Logistics",
        recipients=["ops@example.com"],
        received_at=datetime.now(timezone.utc),
        raw_payload={},
    )

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(mailbox_sync.freight_realtime_hub, "notify_workflow_event", _noop)
    monkeypatch.setattr(mailbox_sync.freight_realtime_hub, "notify_workflow_events", _noop)

    result = await mailbox_sync.ingest_outlook_message(session, message)

    assert result.created_client is False
    assert result.shipment_id
    assert result.sender_verification_required is True
    assert result.fraud_risk_level == "high"
    email_messages = [item for item in session.added if isinstance(item, EmailMessage)]
    workflow_events = [item for item in session.added if isinstance(item, WorkflowEvent)]
    shipments = [item for item in session.added if isinstance(item, Shipment)]
    triage_items = [item for item in session.added if isinstance(item, EmailTriageItem)]
    assert shipments and shipments[0].client_id is None
    assert triage_items and triage_items[0].classification == "freight_quote_request"
    assert email_messages
    assert email_messages[0].raw_payload_json["fraud"]["risk_level"] == "high"
    assert workflow_events
    assert workflow_events[0].payload_json["fraud"]["risk_level"] == "high"
    assert session.committed is True


@pytest.mark.asyncio
async def test_ingest_outlook_message_archives_denylisted_sender(monkeypatch):
    denylist_entry = FraudDenylistEntry(
        id=uuid4(),
        scope="sender_email",
        value="bad@fraud.test",
        reason="known fraud",
        is_active=True,
    )
    session = FakeSession(
        scalar_results=[
            None,  # existing EmailMessage
            None,  # existing shipment
            None,  # carrier by exact email
            None,  # client by exact email
        ],
        execute_results=[
            [denylist_entry],  # fraud denylist entries
        ],
    )
    message = OutlookMailboxMessage(
        provider_message_id="msg-deny-1",
        conversation_id=None,
        internet_message_id="<msg-deny-1@example.com>",
        subject="Quote request",
        body_preview="Need a quote",
        sender_email="bad@fraud.test",
        sender_name="Fraud",
        recipients=["ops@example.com"],
        received_at=datetime.now(timezone.utc),
        raw_payload={},
    )

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(mailbox_sync.freight_realtime_hub, "notify_workflow_event", _noop)
    monkeypatch.setattr(mailbox_sync.freight_realtime_hub, "notify_workflow_events", _noop)

    result = await mailbox_sync.ingest_outlook_message(session, message)

    assert result.created_client is False
    assert result.suppressed is True
    assert result.suppression_reason == "fraud_or_phishing"
    assert result.fraud_risk_level == "high"
    assert result.fraud_risk_reasons == ["denylisted_sender_email"]
    shipments = [item for item in session.added if isinstance(item, Shipment)]
    assert shipments == []
    triage_items = [item for item in session.added if isinstance(item, EmailTriageItem)]
    assert triage_items and triage_items[0].classification == "fraud_or_phishing"
    assert result.shipment_creation_skipped is True
    assert result.shipment_id == ""
    workflow_events = [item for item in session.added if isinstance(item, WorkflowEvent)]
    assert workflow_events == []
