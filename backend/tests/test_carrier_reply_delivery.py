from uuid import uuid4

import pytest

from app.memory.database import EmailMessage, Shipment
from app.services import freight_outreach


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
        status="waiting_bids",
    )


def _carrier_message(*, thread_id, message_id="carrier-msg-1"):
    return EmailMessage(
        id=uuid4(),
        thread_id=thread_id,
        provider_message_id=message_id,
        sender="carrier@example.com",
        recipients_json=["ops@example.com"],
        direction="inbound",
        subject="Re: Quote request",
        body_preview="Can do it for 1200",
    )


@pytest.mark.asyncio
async def test_deliver_carrier_thread_email_replies_when_carrier_anchor_exists(monkeypatch):
    calls = []

    class FakeOutlook:
        async def reply_to_message(self, **kwargs):
            calls.append(("reply", kwargs))

        async def send_mail(self, **kwargs):
            calls.append(("send", kwargs))

    async def _fake_build(_session, _shipment):
        return FakeOutlook()

    monkeypatch.setattr(freight_outreach, "build_outlook_graph_client_for_shipment", _fake_build)
    thread_id = uuid4()
    shipment = _shipment(thread_id)
    session = FakeScalarSession([_carrier_message(thread_id=thread_id)])

    delivery = await freight_outreach.deliver_carrier_thread_email(
        session,
        shipment=shipment,
        carrier_email="carrier@example.com",
        subject="Follow-up",
        body="Can you confirm pickup time?",
        dry_run=False,
    )

    assert delivery == {
        "delivery_mode": "reply",
        "reply_to_provider_message_id": "carrier-msg-1",
    }
    assert calls == [
        (
            "reply",
            {
                "message_id": "carrier-msg-1",
                "body": "Can you confirm pickup time?",
                "recipients": ["carrier@example.com"],
            },
        )
    ]


@pytest.mark.asyncio
async def test_deliver_carrier_thread_email_falls_back_before_carrier_reply(monkeypatch):
    calls = []

    class FakeOutlook:
        async def reply_to_message(self, **kwargs):
            calls.append(("reply", kwargs))

        async def send_mail(self, **kwargs):
            calls.append(("send", kwargs))

    async def _fake_build(_session, _shipment):
        return FakeOutlook()

    monkeypatch.setattr(freight_outreach, "build_outlook_graph_client_for_shipment", _fake_build)
    shipment = _shipment()
    session = FakeScalarSession([None])

    delivery = await freight_outreach.deliver_carrier_thread_email(
        session,
        shipment=shipment,
        carrier_email="carrier@example.com",
        subject="Follow-up",
        body="Can you confirm pickup time?",
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
                "subject": "Follow-up",
                "body": "Can you confirm pickup time?",
                "recipients": ["carrier@example.com"],
            },
        )
    ]


@pytest.mark.asyncio
async def test_deliver_carrier_thread_email_dry_run_reports_reply_without_sending(monkeypatch):
    calls = []

    class FakeOutlook:
        async def reply_to_message(self, **kwargs):
            calls.append(("reply", kwargs))

        async def send_mail(self, **kwargs):
            calls.append(("send", kwargs))

    async def _fake_build(_session, _shipment):
        return FakeOutlook()

    monkeypatch.setattr(freight_outreach, "build_outlook_graph_client_for_shipment", _fake_build)
    thread_id = uuid4()
    shipment = _shipment(thread_id)
    session = FakeScalarSession([_carrier_message(thread_id=thread_id)])

    delivery = await freight_outreach.deliver_carrier_thread_email(
        session,
        shipment=shipment,
        carrier_email="carrier@example.com",
        subject="Follow-up",
        body="Can you confirm pickup time?",
        dry_run=True,
    )

    assert delivery == {
        "delivery_mode": "reply",
        "reply_to_provider_message_id": "carrier-msg-1",
    }
    assert calls == []
