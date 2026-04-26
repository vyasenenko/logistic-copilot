from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.api import freight
from app.memory.database import Carrier, Client, EmailThread, FraudDenylistEntry, Shipment, WorkflowEvent
from app.schemas import (
    FraudDenylistScope,
    OperatorAction,
    SenderIdentityRole,
    SenderTrustScope,
    ShipmentOperatorActionRequest,
    ShipmentStage,
    WorkflowDecisionResult,
    WorkflowEventType,
)
from app.services.mailbox_sync import _looks_like_bounce_or_non_delivery
from app.services.outlook import OutlookMailboxMessage


class ArchiveSession:
    def __init__(self, *, shipment: Shipment, thread: EmailThread | None, scalar_results=None, execute_results=None, client=None, carrier=None):
        self.shipment = shipment
        self.thread = thread
        self.client = client
        self.carrier = carrier
        self.scalar_results = list(scalar_results or [])
        self.execute_results = list(execute_results or [])
        self.added: list[WorkflowEvent] = []
        self.committed = False
        self.refreshed = False

    async def get(self, model, key):
        if model is Shipment and key == self.shipment.id:
            return self.shipment
        if model is EmailThread and self.thread is not None and key == self.thread.id:
            return self.thread
        if model is Client and self.client is not None and key == self.client.id:
            return self.client
        if model is Carrier and self.carrier is not None and key == self.carrier.id:
            return self.carrier
        return None

    async def scalar(self, _query):
        return self.scalar_results.pop(0) if self.scalar_results else None

    async def execute(self, _query):
        values = self.execute_results.pop(0) if self.execute_results else []

        class _Scalars:
            def all(self):
                return list(values)

            def first(self):
                return values[0] if values else None

        class _Result:
            def scalars(self):
                return _Scalars()

        return _Result()

    def add(self, instance):
        self.added.append(instance)

    async def flush(self):
        for instance in self.added:
            if getattr(instance, "id", None) is None:
                instance.id = uuid4()

    async def commit(self):
        self.committed = True

    async def refresh(self, instance):
        self.refreshed = True


@pytest.mark.asyncio
async def test_archive_operator_action_archives_shipment_and_suppresses_thread(monkeypatch):
    thread = EmailThread(
        id=uuid4(),
        mailbox="ops@example.com",
        provider="outlook",
        subject="Undeliverable message",
        normalized_subject="undeliverable message",
    )
    shipment = Shipment(
        id=uuid4(),
        email_thread_id=thread.id,
        status=ShipmentStage.RECEIVED.value,
    )
    session = ArchiveSession(shipment=shipment, thread=thread)

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(freight.freight_realtime_hub, "publish_overview_stale_throttled", _noop)
    monkeypatch.setattr(freight.freight_realtime_hub, "publish_shipment_updated", _noop)
    monkeypatch.setattr(freight, "move_shipment_thread_messages_to_archive", _noop)

    response = await freight.freight_operator_action(
        shipment_id=shipment.id,
        request=ShipmentOperatorActionRequest(
            action=OperatorAction.ARCHIVE_SHIPMENT,
            reason="invalid shipment from bounce",
            suppress_source_thread=True,
        ),
        session=session,
    )

    assert response.archived is True
    assert response.suppression_applied is True
    assert response.suppressed_thread_id == str(thread.id)
    assert shipment.is_archived is True
    assert shipment.archived_reason == "invalid shipment from bounce"
    assert thread.shipment_ingest_suppressed is True
    assert thread.shipment_ingest_suppressed_reason == "invalid shipment from bounce"
    assert session.committed is True
    assert session.refreshed is True
    event_types = [item.event_type for item in session.added]
    assert WorkflowEventType.SHIPMENT_ARCHIVED.value in event_types
    assert WorkflowEventType.SHIPMENT_SOURCE_SUPPRESSED.value in event_types


@pytest.mark.asyncio
async def test_mark_sender_fraud_creates_denylist_entry_and_archives(monkeypatch):
    thread = EmailThread(
        id=uuid4(),
        mailbox="ops@example.com",
        provider="outlook",
        subject="Suspicious quote",
        normalized_subject="suspicious quote",
    )
    shipment = Shipment(
        id=uuid4(),
        email_thread_id=thread.id,
        status=ShipmentStage.RECEIVED.value,
    )
    session = ArchiveSession(
        shipment=shipment,
        thread=thread,
        scalar_results=["bad@fraud.test"],
        execute_results=[[]],
    )

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(freight.freight_realtime_hub, "publish_overview_stale_throttled", _noop)
    monkeypatch.setattr(freight.freight_realtime_hub, "publish_shipment_updated", _noop)
    monkeypatch.setattr(freight, "move_shipment_thread_messages_to_archive", _noop)

    response = await freight.freight_operator_action(
        shipment_id=shipment.id,
        request=ShipmentOperatorActionRequest(
            action=OperatorAction.MARK_SENDER_FRAUD,
            fraud_block_scope=FraudDenylistScope.SENDER_DOMAIN,
            suppress_source_thread=True,
        ),
        session=session,
    )

    assert response.archived is True
    assert response.denylist_scope == FraudDenylistScope.SENDER_DOMAIN
    assert response.denylist_value == "fraud.test"
    assert shipment.archive_reason_code == "fraud"
    assert thread.shipment_ingest_suppressed is True
    entries = [item for item in session.added if isinstance(item, FraudDenylistEntry)]
    assert entries
    assert entries[0].scope == FraudDenylistScope.SENDER_DOMAIN.value
    assert entries[0].value == "fraud.test"
    event_types = [item.event_type for item in session.added if isinstance(item, WorkflowEvent)]
    assert WorkflowEventType.SENDER_FRAUD_MARKED.value in event_types
    assert WorkflowEventType.SHIPMENT_ARCHIVED.value in event_types


@pytest.mark.asyncio
async def test_verify_sender_as_customer_links_client_and_records_scope(monkeypatch):
    thread = EmailThread(id=uuid4(), mailbox="ops@example.com", provider="outlook", subject="Quote", normalized_subject="quote")
    client = Client(id=uuid4(), name="Acme", email="shipper@acme.test")
    shipment = Shipment(id=uuid4(), email_thread_id=thread.id, status=ShipmentStage.RECEIVED.value)
    session = ArchiveSession(
        shipment=shipment,
        thread=thread,
        client=client,
        scalar_results=["shipper@acme.test"],
    )

    async def _noop(*args, **kwargs):
        return None

    async def _decision(*args, **kwargs):
        return WorkflowDecisionResult(email_message_id="", shipment_id=str(shipment.id), intent="test", next_action="continued")

    monkeypatch.setattr(freight.freight_realtime_hub, "notify_workflow_event", _noop)
    monkeypatch.setattr(freight, "continue_phase1_workflow", _decision)

    response = await freight.freight_operator_action(
        shipment_id=shipment.id,
        request=ShipmentOperatorActionRequest(
            action=OperatorAction.VERIFY_SENDER,
            sender_identity_role=SenderIdentityRole.CUSTOMER,
            sender_trust_scope=SenderTrustScope.SENDER_EMAIL,
            client_id=str(client.id),
        ),
        session=session,
    )

    assert response.sender_identity_role == SenderIdentityRole.CUSTOMER
    assert response.sender_trust_scope == SenderTrustScope.SENDER_EMAIL
    assert response.verified_client_id == str(client.id)
    assert shipment.client_id == client.id
    event = next(item for item in session.added if isinstance(item, WorkflowEvent) and item.event_type == WorkflowEventType.SENDER_VERIFIED.value)
    assert event.payload_json["sender_role"] == "customer"
    assert event.payload_json["trust_scope"] == "sender_email"


@pytest.mark.asyncio
async def test_verify_sender_as_carrier_records_domain_scope_without_client_link(monkeypatch):
    thread = EmailThread(id=uuid4(), mailbox="ops@example.com", provider="outlook", subject="Bid", normalized_subject="bid")
    carrier = Carrier(id=uuid4(), name="Fast Trucking", email="dispatch@carrier.test")
    shipment = Shipment(id=uuid4(), email_thread_id=thread.id, status=ShipmentStage.RECEIVED.value)
    session = ArchiveSession(
        shipment=shipment,
        thread=thread,
        carrier=carrier,
        scalar_results=["ops@carrier.test"],
    )

    async def _noop(*args, **kwargs):
        return None

    async def _decision(*args, **kwargs):
        return WorkflowDecisionResult(email_message_id="", shipment_id=str(shipment.id), intent="test", next_action="continued")

    monkeypatch.setattr(freight.freight_realtime_hub, "notify_workflow_event", _noop)
    monkeypatch.setattr(freight, "continue_phase1_workflow", _decision)

    response = await freight.freight_operator_action(
        shipment_id=shipment.id,
        request=ShipmentOperatorActionRequest(
            action=OperatorAction.VERIFY_SENDER,
            sender_identity_role=SenderIdentityRole.CARRIER,
            sender_trust_scope=SenderTrustScope.SENDER_DOMAIN,
            carrier_id=str(carrier.id),
        ),
        session=session,
    )

    assert response.sender_identity_role == SenderIdentityRole.CARRIER
    assert response.sender_trust_scope == SenderTrustScope.SENDER_DOMAIN
    assert response.verified_carrier_id == str(carrier.id)
    assert shipment.client_id is None
    event = next(item for item in session.added if isinstance(item, WorkflowEvent) and item.event_type == WorkflowEventType.SENDER_VERIFIED.value)
    assert event.payload_json["sender_role"] == "carrier"
    assert event.payload_json["sender_domain"] == "carrier.test"
    assert event.payload_json["trust_scope"] == "sender_domain"


def test_bounce_detector_flags_non_delivery_messages():
    message = OutlookMailboxMessage(
        provider_message_id="msg-1",
        conversation_id="conv-1",
        internet_message_id="<msg-1@example.com>",
        subject="Undeliverable: Quote request Newark to Miami",
        body_preview="Не удалось выполнить доставку следующим получателям. Remote server returned 550 5.7.708",
        sender_email="postmaster@example.com",
        sender_name="Postmaster",
        recipients=["ops@example.com"],
        received_at=datetime.now(timezone.utc),
        raw_payload={},
    )

    suppressed, reason = _looks_like_bounce_or_non_delivery(message)

    assert suppressed is True
    assert reason in {"bounce_sender_detected", "bounce_subject_detected", "bounce_body_detected"}
