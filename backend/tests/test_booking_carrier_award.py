from uuid import uuid4

import pytest

from app.memory.database import Carrier, CarrierBid, Client, EmailThread, Shipment, WorkflowEvent
from app.schemas import ShipmentStage, WorkflowEventType
from app.services import freight_outreach


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _AwardSession:
    def __init__(self, *, shipment, client, carrier, bid, thread=None, existing_award=None):
        self.shipment = shipment
        self.client = client
        self.carrier = carrier
        self.bid = bid
        self.thread = thread
        self.existing_award = existing_award
        self.added = []
        self.committed = False
        self.flushed = False
        self.scalar_calls = 0

    async def get(self, model, key):
        if model is Shipment and key == self.shipment.id:
            return self.shipment
        if model is Client and self.client is not None and key == self.client.id:
            return self.client
        if model is EmailThread and self.thread is not None and key == self.thread.id:
            return self.thread
        return None

    async def execute(self, _query):
        return _Rows([(self.bid, self.carrier)])

    async def scalar(self, _query):
        self.scalar_calls += 1
        if self.scalar_calls == 1:
            return self.existing_award
        return None

    def add(self, item):
        self.added.append(item)

    async def flush(self):
        self.flushed = True

    async def commit(self):
        self.committed = True


def _objects(*, carrier_email="dispatch@carrier.test", client_email="ops@customer.test"):
    thread = EmailThread(id=uuid4(), mailbox="ops@example.com", provider="outlook", quote_token="Q-123")
    client = Client(id=uuid4(), name="Customer", email=client_email)
    shipment = Shipment(
        id=uuid4(),
        client_id=client.id,
        email_thread_id=thread.id,
        status=ShipmentStage.AWAITING_CONFIRMATION.value,
        quote_token="Q-123",
        origin="Chicago, IL",
        destination="Dallas, TX",
        equipment_type="Van",
    )
    carrier = Carrier(id=uuid4(), name="Carrier", email=carrier_email)
    bid = CarrierBid(
        id=uuid4(),
        shipment_id=shipment.id,
        carrier_id=carrier.id,
        amount=1000,
        currency="USD",
        status="selected",
        score_json={"total": 100},
    )
    return shipment, client, carrier, bid, thread


@pytest.mark.asyncio
async def test_carrier_award_uses_carrier_delivery_not_customer_delivery(monkeypatch):
    shipment, client, carrier, bid, thread = _objects()
    session = _AwardSession(
        shipment=shipment,
        client=client,
        carrier=carrier,
        bid=bid,
        thread=thread,
    )
    calls = []

    async def _deliver(_session, *, carrier_email, **kwargs):
        calls.append((carrier_email, kwargs))
        return {"delivery_mode": "send_mail_fallback", "reply_to_provider_message_id": None}

    async def _notify(_event):
        return None

    monkeypatch.setattr(freight_outreach, "deliver_carrier_thread_email", _deliver)
    monkeypatch.setattr(freight_outreach.freight_realtime_hub, "notify_workflow_event", _notify)

    result = await freight_outreach.send_carrier_award_confirmation(
        session,
        shipment_id=shipment.id,
        bid_id=None,
        dry_run=False,
    )

    events = [item for item in session.added if isinstance(item, WorkflowEvent)]
    assert calls[0][0] == carrier.email
    assert calls[0][0] != client.email
    assert result.carrier_email == carrier.email
    assert events[-1].event_type == WorkflowEventType.CARRIER_AWARD_SENT.value
    assert events[-1].payload_json["carrier_email"] == carrier.email


@pytest.mark.asyncio
async def test_carrier_award_blocks_when_carrier_email_matches_customer():
    shipment, client, carrier, bid, thread = _objects(
        carrier_email="same@example.com",
        client_email="same@example.com",
    )
    session = _AwardSession(
        shipment=shipment,
        client=client,
        carrier=carrier,
        bid=bid,
        thread=thread,
    )

    with pytest.raises(RuntimeError, match="matches customer email"):
        await freight_outreach.send_carrier_award_confirmation(
            session,
            shipment_id=shipment.id,
            bid_id=None,
            dry_run=False,
        )

    assert session.added == []
