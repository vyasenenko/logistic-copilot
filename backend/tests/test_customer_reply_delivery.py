from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.memory.database import EmailMessage, Shipment
from app.memory.database import Carrier, Client
from app.schemas import ShipmentStage
from app.services import freight_execution
from app.services.freight_inbox_agent import _sender_role_for_inbox_context


class FakeScalarSession:
    def __init__(self, scalar_results):
        self.scalar_results = list(scalar_results)

    async def scalar(self, _query):
        if self.scalar_results:
            return self.scalar_results.pop(0)
        return None

    async def get(self, _model, _ident):
        return None


def _shipment(thread_id=None):
    return Shipment(
        id=uuid4(),
        organization_id=uuid4(),
        email_thread_id=thread_id or uuid4(),
        status="received",
    )


def _inbound_message(*, thread_id, message_id, sender="client@example.com", received_at=None):
    return EmailMessage(
        id=uuid4(),
        thread_id=thread_id,
        provider_message_id=message_id,
        sender=sender,
        recipients_json=["ops@example.com"],
        direction="inbound",
        subject="Quote request",
        body_preview="Please quote this shipment",
        received_at=received_at or datetime.now(timezone.utc),
    )


def test_sender_role_prefers_client_when_waiting_for_customer_details():
    shipment = Shipment(
        id=uuid4(),
        status=ShipmentStage.WAITING_CUSTOMER_DETAILS.value,
    )
    client = Client(id=uuid4(), name="Client", email="same@example.com")
    carrier = Carrier(id=uuid4(), name="Carrier", email="same@example.com")

    role = _sender_role_for_inbox_context(
        shipment=shipment,
        client=client,
        carrier=carrier,
    )

    assert role == "client"


def test_sender_role_keeps_carrier_for_normal_carrier_replies():
    shipment = Shipment(
        id=uuid4(),
        status=ShipmentStage.WAITING_BIDS.value,
    )
    client = Client(id=uuid4(), name="Client", email="same@example.com")
    carrier = Carrier(id=uuid4(), name="Carrier", email="same@example.com")

    role = _sender_role_for_inbox_context(
        shipment=shipment,
        client=client,
        carrier=carrier,
    )

    assert role == "carrier"


@pytest.mark.asyncio
async def test_find_customer_reply_anchor_prefers_client_first_inbound_message():
    thread_id = uuid4()
    shipment = _shipment(thread_id)
    client_anchor = _inbound_message(
        thread_id=thread_id,
        message_id="client-first",
        received_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    session = FakeScalarSession([client_anchor])

    anchor = await freight_execution._find_customer_reply_anchor(
        session,
        shipment=shipment,
        client_email="CLIENT@example.com",
    )

    assert anchor is client_anchor
    assert anchor.provider_message_id == "client-first"


@pytest.mark.asyncio
async def test_deliver_customer_thread_email_replies_when_anchor_exists(monkeypatch):
    calls = []

    class FakeOutlook:
        async def reply_to_message(self, **kwargs):
            calls.append(("reply", kwargs))

        async def send_mail(self, **kwargs):
            calls.append(("send", kwargs))

    async def _fake_build(_session, _shipment):
        return FakeOutlook()

    monkeypatch.setattr(freight_execution, "build_outlook_graph_client_for_shipment", _fake_build)
    thread_id = uuid4()
    shipment = _shipment(thread_id)
    anchor = _inbound_message(thread_id=thread_id, message_id="msg-123")
    session = FakeScalarSession([anchor])

    delivery = await freight_execution.deliver_customer_thread_email(
        session,
        shipment=shipment,
        client_email="client@example.com",
        subject="Quote ready",
        body="We can cover this load.",
        dry_run=False,
    )

    assert delivery == {
        "delivery_mode": "reply",
        "reply_to_provider_message_id": "msg-123",
    }
    assert calls == [
        (
            "reply",
            {
                "message_id": "msg-123",
                "body": "We can cover this load.",
                "recipients": ["client@example.com"],
            },
        )
    ]


@pytest.mark.asyncio
async def test_deliver_customer_thread_email_falls_back_to_send_mail_without_anchor(monkeypatch):
    calls = []

    class FakeOutlook:
        async def reply_to_message(self, **kwargs):
            calls.append(("reply", kwargs))

        async def send_mail(self, **kwargs):
            calls.append(("send", kwargs))

    async def _fake_build(_session, _shipment):
        return FakeOutlook()

    monkeypatch.setattr(freight_execution, "build_outlook_graph_client_for_shipment", _fake_build)
    shipment = _shipment()
    session = FakeScalarSession([None, None])

    delivery = await freight_execution.deliver_customer_thread_email(
        session,
        shipment=shipment,
        client_email="client@example.com",
        subject="Quote ready",
        body="We can cover this load.",
        dry_run=False,
    )

    assert delivery == {
        "delivery_mode": "send_mail_fallback",
        "reply_to_provider_message_id": None,
    }
    assert calls == [
        (
            "send",
            {
                "subject": "Quote ready",
                "body": "We can cover this load.",
                "recipients": ["client@example.com"],
            },
        )
    ]


@pytest.mark.asyncio
async def test_deliver_customer_thread_email_dry_run_reports_reply_without_sending(monkeypatch):
    calls = []

    class FakeOutlook:
        async def reply_to_message(self, **kwargs):
            calls.append(("reply", kwargs))

        async def send_mail(self, **kwargs):
            calls.append(("send", kwargs))

    async def _fake_build(_session, _shipment):
        return FakeOutlook()

    monkeypatch.setattr(freight_execution, "build_outlook_graph_client_for_shipment", _fake_build)
    thread_id = uuid4()
    shipment = _shipment(thread_id)
    anchor = _inbound_message(thread_id=thread_id, message_id="msg-123")
    session = FakeScalarSession([anchor])

    delivery = await freight_execution.deliver_customer_thread_email(
        session,
        shipment=shipment,
        client_email="client@example.com",
        subject="Quote ready",
        body="We can cover this load.",
        dry_run=True,
    )

    assert delivery == {
        "delivery_mode": "reply",
        "reply_to_provider_message_id": "msg-123",
    }
    assert calls == []
