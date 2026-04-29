from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.api import freight
from app.memory.database import Shipment
from app.schemas import ShipmentStage


class FakeScalarResult:
    def __init__(self, values):
        self._values = values

    def all(self):
        return list(self._values)


class FakeExecuteResult:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return FakeScalarResult(self._values)


class FakeSession:
    def __init__(self, shipments):
        self.shipments = list(shipments)

    async def execute(self, _query):
        return FakeExecuteResult(self.shipments)


@pytest.mark.asyncio
async def test_list_shipments_filters_by_created_month_not_ready_month(monkeypatch):
    april_created_may_ready = Shipment(
        id=uuid4(),
        status=ShipmentStage.RECEIVED.value,
        created_at=datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc),
        ready_at_local=datetime(2026, 5, 2, 9, 0),
    )
    may_created_april_ready = Shipment(
        id=uuid4(),
        status=ShipmentStage.RECEIVED.value,
        created_at=datetime(2026, 5, 1, 8, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 1, 8, 0, tzinfo=timezone.utc),
        ready_at_local=datetime(2026, 4, 28, 10, 0),
    )
    session = FakeSession([may_created_april_ready, april_created_may_ready])

    async def _empty_payloads(*args, **kwargs):
        return {}

    async def _empty_counts(*args, **kwargs):
        return {}

    monkeypatch.setattr(freight, "_latest_ai_payloads", _empty_payloads)
    monkeypatch.setattr(freight, "_latest_booking_payloads", _empty_payloads)
    monkeypatch.setattr(freight, "_latest_status_payloads", _empty_payloads)
    monkeypatch.setattr(freight, "_latest_status_review_payloads", _empty_payloads)
    monkeypatch.setattr(freight, "_latest_tms_identity_payloads", _empty_payloads)
    monkeypatch.setattr(freight, "_status_workflow_payloads", _empty_payloads)
    monkeypatch.setattr(freight, "_latest_document_action_payloads", _empty_payloads)
    monkeypatch.setattr(freight, "_attachment_counts", _empty_counts)
    monkeypatch.setattr(freight, "_document_booking_summaries", _empty_counts)

    records = await freight.list_shipments(month="2026-04", session=session)

    assert [record.id for record in records] == [str(april_created_may_ready.id)]


@pytest.mark.asyncio
async def test_list_shipments_sorts_attention_first_then_updated_at_desc(monkeypatch):
    attention_older = Shipment(
        id=uuid4(),
        status=ShipmentStage.RECEIVED.value,
        created_at=datetime(2026, 4, 10, 9, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 10, 9, 0, tzinfo=timezone.utc),
        origin="Chicago, IL",
        destination="Atlanta, GA",
    )
    fresh_normal = Shipment(
        id=uuid4(),
        status=ShipmentStage.RECEIVED.value,
        created_at=datetime(2026, 4, 11, 9, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc),
        origin="Dallas, TX",
        destination="Phoenix, AZ",
    )
    older_normal = Shipment(
        id=uuid4(),
        status=ShipmentStage.RECEIVED.value,
        created_at=datetime(2026, 4, 9, 9, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 12, 9, 0, tzinfo=timezone.utc),
        origin="Miami, FL",
        destination="Nashville, TN",
    )
    session = FakeSession([fresh_normal, attention_older, older_normal])

    async def _latest_ai_payloads(_session, shipment_ids):
        return {
            shipment_id: ({"missing_fields": ["origin"]} if shipment_id == attention_older.id else {})
            for shipment_id in shipment_ids
        }

    async def _empty_payloads(*args, **kwargs):
        return {}

    async def _empty_counts(*args, **kwargs):
        return {}

    monkeypatch.setattr(freight, "_latest_ai_payloads", _latest_ai_payloads)
    monkeypatch.setattr(freight, "_latest_booking_payloads", _empty_payloads)
    monkeypatch.setattr(freight, "_latest_status_payloads", _empty_payloads)
    monkeypatch.setattr(freight, "_latest_status_review_payloads", _empty_payloads)
    monkeypatch.setattr(freight, "_latest_tms_identity_payloads", _empty_payloads)
    monkeypatch.setattr(freight, "_status_workflow_payloads", _empty_payloads)
    monkeypatch.setattr(freight, "_latest_document_action_payloads", _empty_payloads)
    monkeypatch.setattr(freight, "_attachment_counts", _empty_counts)
    monkeypatch.setattr(freight, "_document_booking_summaries", _empty_counts)

    records = await freight.list_shipments(month="2026-04", session=session)

    assert [record.id for record in records] == [
        str(attention_older.id),
        str(fresh_normal.id),
        str(older_normal.id),
    ]


def test_shipment_board_sort_key_prioritizes_attention_and_freshness():
    attention_record = freight.ShipmentRecord(
        id=str(uuid4()),
        status=ShipmentStage.RECEIVED.value,
        attention_state="review",
        has_active_review=True,
        created_at=datetime(2026, 4, 10, 9, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 10, 9, 0, tzinfo=timezone.utc),
    )
    fresh_record = freight.ShipmentRecord(
        id=str(uuid4()),
        status=ShipmentStage.RECEIVED.value,
        attention_state="none",
        has_active_review=False,
        created_at=datetime(2026, 4, 10, 9, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc),
    )
    older_record = freight.ShipmentRecord(
        id=str(uuid4()),
        status=ShipmentStage.RECEIVED.value,
        attention_state="none",
        has_active_review=False,
        created_at=datetime(2026, 4, 10, 9, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 12, 9, 0, tzinfo=timezone.utc),
    )

    ordered = sorted([fresh_record, older_record, attention_record], key=freight._shipment_board_sort_key)

    assert [record.id for record in ordered] == [
        attention_record.id,
        fresh_record.id,
        older_record.id,
    ]


def test_serialize_shipment_uses_current_missing_fields_not_stale_ai_payload():
    shipment = Shipment(
        id=uuid4(),
        status=ShipmentStage.RECEIVED.value,
        origin="Chicago, IL",
        destination="Atlanta, GA",
        pallets=4,
        weight_lb=7500,
        equipment_type="Dry Van",
        ready_at_local=datetime(2026, 4, 28, 9, 0),
        created_at=datetime(2026, 4, 10, 9, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc),
    )

    record = freight._serialize_shipment(
        shipment,
        {
            "missing_fields": ["origin", "destination", "ready_at"],
            "manual_review_required": False,
        },
    )

    assert record.ai_missing_fields == []
    assert record.attention_state == "none"
    assert record.has_active_review is False


def test_serialize_shipment_reports_actual_missing_fields():
    shipment = Shipment(
        id=uuid4(),
        status=ShipmentStage.RECEIVED.value,
        origin="Chicago, IL",
        destination="Atlanta, GA",
        created_at=datetime(2026, 4, 10, 9, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc),
    )

    record = freight._serialize_shipment(shipment, {"missing_fields": []})

    assert record.ai_missing_fields == ["pallets", "weight_lb", "equipment_type", "ready_at"]
    assert record.attention_state == "missing_details"
