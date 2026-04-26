from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.memory.database import EmailMessage, FraudDenylistEntry, Shipment, WorkflowEvent
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


@pytest.mark.asyncio
async def test_ingest_outlook_message_flags_unknown_sender_and_skips_client_creation(monkeypatch):
    session = FakeSession(
        scalar_results=[
            None,  # existing EmailMessage
            None,  # carrier by exact email
            None,  # client by exact email
            None,  # existing shipment
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
        body_preview="Need a quote from Porto to Madrid",
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
    assert shipments and shipments[0].client_id is None
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
            None,  # carrier by exact email
            None,  # client by exact email
            None,  # existing shipment
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
    assert result.suppression_reason == "fraud_denylist:sender_email:bad@fraud.test"
    assert result.fraud_risk_level == "high"
    assert result.fraud_risk_reasons == ["denylisted_sender_email"]
    shipments = [item for item in session.added if isinstance(item, Shipment)]
    assert shipments
    assert shipments[0].is_archived is True
    assert shipments[0].archive_reason_code == "fraud"
    assert shipments[0].client_id is None
    workflow_events = [item for item in session.added if isinstance(item, WorkflowEvent)]
    assert workflow_events
    email_received = next(event for event in workflow_events if event.event_type == "email_received")
    assert email_received.payload_json["suppressed"] is True
    assert email_received.payload_json["fraud"]["denylist_entry_id"] == str(denylist_entry.id)
    assert any(event.event_type == "shipment_archived" for event in workflow_events)
    assert any(event.event_type == "shipment_source_suppressed" for event in workflow_events)
