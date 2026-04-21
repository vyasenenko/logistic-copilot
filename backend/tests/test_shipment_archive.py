from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.api import freight
from app.memory.database import EmailThread, Shipment, WorkflowEvent
from app.schemas import OperatorAction, ShipmentOperatorActionRequest, ShipmentStage, WorkflowEventType
from app.services.mailbox_sync import _looks_like_bounce_or_non_delivery
from app.services.outlook import OutlookMailboxMessage


class ArchiveSession:
    def __init__(self, *, shipment: Shipment, thread: EmailThread | None):
        self.shipment = shipment
        self.thread = thread
        self.added: list[WorkflowEvent] = []
        self.committed = False
        self.refreshed = False

    async def get(self, model, key):
        if model is Shipment and key == self.shipment.id:
            return self.shipment
        if model is EmailThread and self.thread is not None and key == self.thread.id:
            return self.thread
        return None

    def add(self, instance):
        self.added.append(instance)

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
