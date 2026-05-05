from datetime import datetime, timedelta, timezone
import json
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api import freight
from app.memory.database import Shipment, WorkflowEvent
from app.schemas import (
    CarrierStatusUpdateResponse,
    CustomerStatusReplyResponse,
    OutlookIngestResult,
    OutlookWebhookRequest,
    ShipmentStage,
    StatusQueueAction,
    StatusQueueActionRequest,
    StatusQueueItem,
    TmsStatusIngestRequest,
    TmsStatusResponse,
    WorkflowEventType,
)


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
    def __init__(self, *, shipment: Shipment, task_event: WorkflowEvent):
        self.shipment = shipment
        self.task_event = task_event
        self.added: list[WorkflowEvent] = []
        self.committed = False

    async def get(self, model, key):
        if model is WorkflowEvent and key == self.task_event.id:
            return self.task_event
        if model is Shipment and key == self.shipment.id:
            return self.shipment
        return None

    def add(self, instance):
        self.added.append(instance)

    async def commit(self):
        self.committed = True


class FakeTmsSession:
    def __init__(
        self,
        *,
        shipment_by_id: dict | None = None,
        scalar_shipment: Shipment | None = None,
        execute_batches: list[list] | None = None,
    ):
        self.shipment_by_id = shipment_by_id or {}
        self.scalar_shipment = scalar_shipment
        self.execute_batches = list(execute_batches or [])
        self.added: list[WorkflowEvent] = []
        self.committed = False

    async def get(self, model, key):
        if model is Shipment:
            return self.shipment_by_id.get(key)
        return None

    async def scalar(self, _query):
        return self.scalar_shipment

    async def execute(self, _query):
        batch = self.execute_batches.pop(0) if self.execute_batches else []
        return FakeExecuteResult(batch)

    def add(self, instance):
        self.added.append(instance)

    async def commit(self):
        self.committed = True


class FakeReadSession:
    def __init__(self, *, shipment: Shipment):
        self.shipment = shipment

    async def get(self, model, key):
        if model is Shipment and key == self.shipment.id:
            return self.shipment
        return None


def _build_request(*, query_string: bytes = b"", payload: dict | None = None) -> Request:
    body = b""
    headers: list[tuple[bytes, bytes]] = []
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers.append((b"content-type", b"application/json"))
        headers.append((b"content-length", str(len(body)).encode("utf-8")))

    async def receive():
        nonlocal body
        current = body
        body = b""
        return {"type": "http.request", "body": current, "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/freight/outlook/webhook",
        "query_string": query_string,
        "headers": headers,
    }
    return Request(scope, receive)


@pytest.mark.asyncio
async def test_status_queue_endpoint_can_include_resolved_history(monkeypatch):
    active_item = StatusQueueItem(
        task_id=str(uuid4()),
        task_type="status_reply",
        task_state="awaiting_approval",
        queue_scope="active",
        shipment_id=str(uuid4()),
        reason="Needs approval",
        created_at=datetime.now(timezone.utc),
    )
    resolved_item = StatusQueueItem(
        task_id=str(uuid4()),
        task_type="carrier_update",
        task_state="pushed",
        queue_scope="resolved",
        resolution_state="pushed",
        resolution_reason="pushed_to_tms",
        resolution_at=datetime.now(timezone.utc),
        shipment_id=str(uuid4()),
        reason="Resolved task",
        created_at=datetime.now(timezone.utc),
    )

    async def _active(_session):
        return [active_item]

    async def _resolved(_session, *, limit=25):
        assert limit == 25
        return [resolved_item]

    monkeypatch.setattr(freight, "_active_status_queue_items", _active)
    monkeypatch.setattr(freight, "_resolved_status_queue_items", _resolved)

    result = await freight.freight_status_queue(include_resolved=True, resolved_limit=25, session=object())

    assert len(result) == 2
    assert result[0].queue_scope == "active"
    assert result[1].queue_scope == "resolved"
    assert result[1].resolution_reason == "pushed_to_tms"


@pytest.mark.asyncio
async def test_status_queue_action_approve_and_send_records_resolution(monkeypatch):
    shipment = Shipment(
        id=uuid4(),
        status=ShipmentStage.BOOKED.value,
    )
    task_event = WorkflowEvent(
        id=uuid4(),
        shipment_id=shipment.id,
        event_type=WorkflowEventType.CUSTOMER_STATUS_SENT.value,
        stage=shipment.status,
        payload_json={"dry_run": True, "subject": "Status update", "body": "Still moving"},
        created_at=datetime.now(timezone.utc),
    )
    session = FakeSession(shipment=shipment, task_event=task_event)

    async def _not_resolved(*args, **kwargs):
        return False

    async def _fetch_status(*args, **kwargs):
        return TmsStatusResponse(
            shipment_id=str(shipment.id),
            status="ok",
            payload={"status": "in_transit", "eta": "Tomorrow"},
        )

    async def _send_reply(*args, **kwargs):
        return CustomerStatusReplyResponse(
            shipment_id=str(shipment.id),
            client_email="client@example.com",
            subject="Status update",
            body="Still moving",
            dry_run=False,
        )

    monkeypatch.setattr(freight, "_is_task_already_resolved", _not_resolved)
    monkeypatch.setattr(freight, "fetch_tms_shipment_status", _fetch_status)
    monkeypatch.setattr(freight, "send_customer_status_reply", _send_reply)

    response = await freight.freight_status_queue_action(
        task_id=task_event.id,
        request=StatusQueueActionRequest(action=StatusQueueAction.APPROVE_AND_SEND),
        session=session,
    )

    assert response.status == "completed"
    assert response.task_state == "sent"
    assert response.resolution_state == "sent"
    assert response.resolution_reason == "sent_to_customer"
    assert session.committed is True
    assert any(
        added.event_type == WorkflowEventType.STATUS_WORKFLOW_RESOLVED.value
        and added.payload_json.get("resolution_reason") == "sent_to_customer"
        for added in session.added
    )


@pytest.mark.asyncio
async def test_status_queue_action_approve_and_send_returns_already_completed(monkeypatch):
    shipment = Shipment(
        id=uuid4(),
        status=ShipmentStage.BOOKED.value,
    )
    task_event = WorkflowEvent(
        id=uuid4(),
        shipment_id=shipment.id,
        event_type=WorkflowEventType.CUSTOMER_STATUS_SENT.value,
        stage=shipment.status,
        payload_json={"dry_run": True},
        created_at=datetime.now(timezone.utc),
    )
    session = FakeSession(shipment=shipment, task_event=task_event)

    async def _already_resolved(*args, **kwargs):
        return True

    async def _fetch_status(*args, **kwargs):
        return TmsStatusResponse(
            shipment_id=str(shipment.id),
            status="ok",
            payload={"status": "in_transit"},
        )

    monkeypatch.setattr(freight, "_is_task_already_resolved", _already_resolved)
    monkeypatch.setattr(freight, "fetch_tms_shipment_status", _fetch_status)

    response = await freight.freight_status_queue_action(
        task_id=task_event.id,
        request=StatusQueueActionRequest(action=StatusQueueAction.APPROVE_AND_SEND),
        session=session,
    )

    assert response.status == "already_completed"
    assert response.task_state == "sent"
    assert response.resolution_reason == "sent_to_customer"
    assert session.added == []
    assert session.committed is False


@pytest.mark.asyncio
async def test_status_queue_action_approve_and_push_records_resolution(monkeypatch):
    shipment = Shipment(
        id=uuid4(),
        status=ShipmentStage.BOOKED.value,
    )
    task_event = WorkflowEvent(
        id=uuid4(),
        shipment_id=shipment.id,
        event_type=WorkflowEventType.TMS_STATUS_UPDATED.value,
        stage=shipment.status,
        payload_json={
            "status_audit_kind": "carrier_update_parsed",
            "payload": {
                "status_text": "arrived",
                "eta_text": "Now",
                "location_text": "Chicago, IL",
            },
        },
        created_at=datetime.now(timezone.utc),
    )
    session = FakeSession(shipment=shipment, task_event=task_event)

    async def _not_resolved(*args, **kwargs):
        return False

    async def _push_update(*args, **kwargs):
        return CarrierStatusUpdateResponse(
            shipment_id=str(shipment.id),
            status="ok",
            dry_run=False,
            status_text="arrived",
            eta_text="Now",
            location_text="Chicago, IL",
            payload={"pushed": True},
        )

    monkeypatch.setattr(freight, "_is_task_already_resolved", _not_resolved)
    monkeypatch.setattr(freight, "preview_or_push_carrier_status_update", _push_update)

    response = await freight.freight_status_queue_action(
        task_id=task_event.id,
        request=StatusQueueActionRequest(action=StatusQueueAction.APPROVE_AND_PUSH),
        session=session,
    )

    assert response.status == "completed"
    assert response.task_state == "pushed"
    assert response.resolution_state == "pushed"
    assert response.resolution_reason == "pushed_to_tms"
    assert session.committed is True
    assert any(
        added.event_type == WorkflowEventType.STATUS_WORKFLOW_RESOLVED.value
        and added.payload_json.get("resolution_reason") == "pushed_to_tms"
        for added in session.added
    )


@pytest.mark.asyncio
async def test_status_queue_action_approve_and_push_returns_already_completed(monkeypatch):
    shipment = Shipment(
        id=uuid4(),
        status=ShipmentStage.BOOKED.value,
    )
    task_event = WorkflowEvent(
        id=uuid4(),
        shipment_id=shipment.id,
        event_type=WorkflowEventType.TMS_STATUS_UPDATED.value,
        stage=shipment.status,
        payload_json={"status_audit_kind": "carrier_update_parsed", "payload": {"status_text": "arrived"}},
        created_at=datetime.now(timezone.utc),
    )
    session = FakeSession(shipment=shipment, task_event=task_event)

    async def _already_resolved(*args, **kwargs):
        return True

    async def _preview_or_push(*args, **kwargs):
        return CarrierStatusUpdateResponse(
            shipment_id=str(shipment.id),
            status="ok",
            dry_run=False,
            status_text="arrived",
            payload={},
        )

    monkeypatch.setattr(freight, "_is_task_already_resolved", _already_resolved)
    monkeypatch.setattr(freight, "preview_or_push_carrier_status_update", _preview_or_push)

    response = await freight.freight_status_queue_action(
        task_id=task_event.id,
        request=StatusQueueActionRequest(action=StatusQueueAction.APPROVE_AND_PUSH),
        session=session,
    )

    assert response.status == "already_completed"
    assert response.task_state == "pushed"
    assert response.resolution_reason == "pushed_to_tms"
    assert session.added == []
    assert session.committed is False


@pytest.mark.asyncio
async def test_tms_status_event_ingests_and_supersedes_stale_tasks():
    shipment = Shipment(
        id=uuid4(),
        status=ShipmentStage.BOOKED.value,
        quote_token="Q-10023",
    )
    session = FakeTmsSession(
        shipment_by_id={shipment.id: shipment},
        execute_batches=[[]],
    )

    response = await freight.freight_tms_status_event(
        request=TmsStatusIngestRequest(
            shipment_id=str(shipment.id),
            external_event_id="evt-1001",
            tms_load_id="LOAD-123",
            tms_system="generic",
            status="in_transit",
            eta="2026-04-20T18:00:00Z",
            location="Columbus, OH",
            milestone="linehaul",
            payload={"source": "tracking_feed"},
        ),
        session=session,
    )

    assert response.status == "ingested"
    assert session.committed is True
    assert len(session.added) == 3
    assert session.added[0].event_type == WorkflowEventType.TMS_STATUS_INGESTED.value
    assert session.added[1].payload_json["resolution_state"] == "resolved_no_push"
    assert session.added[1].payload_json["resolution_reason"] == "superseded_by_newer_snapshot"
    assert session.added[2].payload_json["resolution_state"] == "resolved_no_send"
    assert session.added[2].payload_json["resolution_reason"] == "superseded_by_newer_snapshot"


@pytest.mark.asyncio
async def test_tms_status_event_suppresses_duplicate_external_event():
    shipment = Shipment(
        id=uuid4(),
        status=ShipmentStage.BOOKED.value,
    )
    existing = WorkflowEvent(
        id=uuid4(),
        shipment_id=shipment.id,
        event_type=WorkflowEventType.TMS_STATUS_INGESTED.value,
        stage=shipment.status,
        payload_json={
            "external_event_id": "evt-dup-1",
            "tms_load_id": "LOAD-123",
            "status": "in_transit",
        },
        created_at=datetime.now(timezone.utc),
    )
    session = FakeTmsSession(
        shipment_by_id={shipment.id: shipment},
        execute_batches=[[existing]],
    )

    response = await freight.freight_tms_status_event(
        request=TmsStatusIngestRequest(
            shipment_id=str(shipment.id),
            external_event_id="evt-dup-1",
            tms_load_id="LOAD-123",
            status="in_transit",
        ),
        session=session,
    )

    assert response.status == "already_processed"
    assert session.added == []
    assert session.committed is False


@pytest.mark.asyncio
async def test_tms_status_event_suppresses_duplicate_snapshot_payload():
    shipment = Shipment(
        id=uuid4(),
        status=ShipmentStage.BOOKED.value,
    )
    existing = WorkflowEvent(
        id=uuid4(),
        shipment_id=shipment.id,
        event_type=WorkflowEventType.TMS_STATUS_INGESTED.value,
        stage=shipment.status,
        payload_json={
            "tms_load_id": "LOAD-123",
            "status": "in_transit",
            "eta": "Tomorrow",
            "location": "Columbus, OH",
            "milestone": "linehaul",
            "source_timestamp": "2026-04-20T18:00:00+00:00",
        },
        created_at=datetime.now(timezone.utc),
    )
    session = FakeTmsSession(
        shipment_by_id={shipment.id: shipment},
        execute_batches=[[existing]],
    )

    response = await freight.freight_tms_status_event(
        request=TmsStatusIngestRequest(
            shipment_id=str(shipment.id),
            tms_load_id="LOAD-123",
            status="in_transit",
            eta="Tomorrow",
            location="Columbus, OH",
            milestone="linehaul",
            source_timestamp=datetime.fromisoformat("2026-04-20T18:00:00+00:00"),
        ),
        session=session,
    )

    assert response.status == "already_processed"
    assert session.added == []
    assert session.committed is False


@pytest.mark.asyncio
async def test_tms_status_event_can_resolve_shipment_by_tms_load_id(monkeypatch):
    shipment = Shipment(
        id=uuid4(),
        status=ShipmentStage.BOOKED.value,
    )
    session = FakeTmsSession(
        execute_batches=[[shipment], []],
    )

    async def _identity_payloads(_session, shipment_ids):
        assert shipment_ids == [shipment.id]
        return {shipment.id: {"tms_load_id": "LOAD-123", "tms_system": "generic"}}

    monkeypatch.setattr(freight, "_latest_tms_identity_payloads", _identity_payloads)

    response = await freight.freight_tms_status_event(
        request=TmsStatusIngestRequest(
            tms_load_id="LOAD-123",
            status="in_transit",
            eta="Tomorrow",
            location="Columbus, OH",
        ),
        session=session,
    )

    assert response.status == "ingested"
    assert response.tms_load_id == "LOAD-123"
    assert session.committed is True


@pytest.mark.asyncio
async def test_tms_status_event_returns_404_for_unknown_identity():
    session = FakeTmsSession(execute_batches=[[]])

    with pytest.raises(HTTPException) as exc:
        await freight.freight_tms_status_event(
            request=TmsStatusIngestRequest(
                tms_load_id="UNKNOWN-LOAD",
                status="in_transit",
            ),
            session=session,
        )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_shipment_includes_status_projection_after_inbound_sync(monkeypatch):
    shipment = Shipment(
        id=uuid4(),
        status=ShipmentStage.BOOKED.value,
        email_thread_id=uuid4(),
    )
    session = FakeReadSession(shipment=shipment)
    now = datetime.now(timezone.utc)

    async def _empty(_session, shipment_ids):
        return {}

    async def _status_payloads(_session, shipment_ids):
        assert shipment_ids == [shipment.id]
        return {
            shipment.id: {
                "last_known_status": "in_transit",
                "last_known_eta": "2026-04-20T18:00:00Z",
                "last_known_location": "Columbus, OH",
                "last_status_source": "tms_inbound_sync",
                "last_status_event_at": now,
            }
        }

    async def _status_review_payloads(_session, shipment_ids):
        return {shipment.id: {"status_review_required": False}}

    async def _tms_identity_payloads(_session, shipment_ids):
        return {shipment.id: {"tms_load_id": "LOAD-123", "tms_system": "generic"}}

    async def _workflow_payloads(_session, shipment_ids):
        return {shipment.id: {"status_workflow_state": "resolved_no_send"}}

    async def _attachment_counts(_session, shipments):
        return {shipment.id: 0}

    async def _document_summaries(_session, shipments, document_action_payloads):
        return {shipment.id: {"document_summary": {}}}

    monkeypatch.setattr(freight, "_latest_ai_payloads", _empty)
    monkeypatch.setattr(freight, "_latest_booking_payloads", _empty)
    monkeypatch.setattr(freight, "_latest_status_payloads", _status_payloads)
    monkeypatch.setattr(freight, "_latest_status_review_payloads", _status_review_payloads)
    monkeypatch.setattr(freight, "_latest_tms_identity_payloads", _tms_identity_payloads)
    monkeypatch.setattr(freight, "_status_workflow_payloads", _workflow_payloads)
    monkeypatch.setattr(freight, "_latest_document_action_payloads", _empty)
    monkeypatch.setattr(freight, "_attachment_counts", _attachment_counts)
    monkeypatch.setattr(freight, "_document_booking_summaries", _document_summaries)

    response = await freight.get_shipment(shipment_id=shipment.id, session=session)

    assert response.last_known_status == "in_transit"
    assert response.last_known_eta == "2026-04-20T18:00:00Z"
    assert response.last_known_location == "Columbus, OH"
    assert response.last_status_source == "tms_inbound_sync"
    assert response.tms_load_id == "LOAD-123"
    assert response.tms_system == "generic"
    assert response.status_workflow_state == "resolved_no_send"
    assert response.status_sync_health == "healthy"
    assert response.status_stale is False


@pytest.mark.asyncio
async def test_get_shipment_marks_status_as_stale_when_event_is_outside_sla(monkeypatch):
    shipment = Shipment(
        id=uuid4(),
        status=ShipmentStage.BOOKED.value,
    )
    session = FakeReadSession(shipment=shipment)
    stale_at = datetime.now(timezone.utc) - timedelta(days=2)

    async def _empty(_session, shipment_ids):
        return {}

    async def _status_payloads(_session, shipment_ids):
        return {
            shipment.id: {
                "last_known_status": "in_transit",
                "last_known_eta": "Tomorrow",
                "last_known_location": "Chicago, IL",
                "last_status_source": "tms_lookup",
                "last_status_event_at": stale_at,
            }
        }

    async def _status_review_payloads(_session, shipment_ids):
        return {shipment.id: {"status_review_required": False}}

    async def _attachment_counts(_session, shipments):
        return {shipment.id: 0}

    async def _document_summaries(_session, shipments, document_action_payloads):
        return {shipment.id: {"document_summary": {}}}

    monkeypatch.setattr(freight, "_latest_ai_payloads", _empty)
    monkeypatch.setattr(freight, "_latest_booking_payloads", _empty)
    monkeypatch.setattr(freight, "_latest_status_payloads", _status_payloads)
    monkeypatch.setattr(freight, "_latest_status_review_payloads", _status_review_payloads)
    monkeypatch.setattr(freight, "_latest_tms_identity_payloads", _empty)
    monkeypatch.setattr(freight, "_status_workflow_payloads", _empty)
    monkeypatch.setattr(freight, "_latest_document_action_payloads", _empty)
    monkeypatch.setattr(freight, "_attachment_counts", _attachment_counts)
    monkeypatch.setattr(freight, "_document_booking_summaries", _document_summaries)

    response = await freight.get_shipment(shipment_id=shipment.id, session=session)

    assert response.status_stale is True
    assert response.status_sync_health == "stale"


@pytest.mark.asyncio
async def test_outlook_webhook_returns_validation_token():
    response = await freight.freight_outlook_webhook(
        http_request=_build_request(query_string=b"validationToken=validate-me"),
    )

    assert response.body == b"validate-me"
    assert response.media_type == "text/plain"


@pytest.mark.asyncio
async def test_outlook_webhook_fetches_message_for_signed_connection_with_graph_user_id_resource(monkeypatch):
    shipment = Shipment(id=uuid4(), status=ShipmentStage.RECEIVED.value)
    session = object()
    mailbox_message = object()
    org_id = uuid4()

    class _FakeSessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _FakeOutlook:
        mailbox = "ops@example.com"

        async def get_message(self, message_id):
            assert message_id == "msg-123"
            return mailbox_message

    expected_email_connection_id = uuid4()

    async def _fake_resolve(_session, _notification):
        return org_id, "ops@example.com", expected_email_connection_id

    async def _fake_build(_session, oid, *, mailbox=None, email_connection_id=None):
        assert oid == org_id
        assert mailbox == "ops@example.com"
        assert email_connection_id == expected_email_connection_id
        return _FakeOutlook()

    async def _process_message(_session, *, mailbox_message, policy, organization_id, mailbox, create_client_if_missing=True):
        assert _session is session
        assert mailbox_message is not None
        assert policy.auto_acknowledgement is True
        assert organization_id == org_id
        return OutlookIngestResult(
            thread_id=str(uuid4()),
            email_message_id=str(uuid4()),
            shipment_id=str(shipment.id),
            created_message=True,
            shipment_extracted=True,
            acknowledgement_drafted=True,
        )

    async def _expired(_session, *, policy):
        return []

    monkeypatch.setattr(freight, "_resolve_outlook_webhook_context", _fake_resolve)
    monkeypatch.setattr(freight, "build_outlook_graph_client", _fake_build)
    monkeypatch.setattr(freight, "_process_outlook_mailbox_message", _process_message)
    monkeypatch.setattr(freight, "evaluate_expired_quote_windows", _expired)
    monkeypatch.setattr(freight, "async_session", lambda: _FakeSessionContext())

    response = await freight.freight_outlook_webhook(
        http_request=_build_request(
            payload={
                "value": [
                    {
                        "changeType": "created",
                        "resource": "Users/64d34868-97b1-48b3-a294-7d6aadc9d200/Messages/msg-123",
                        "resourceData": {"id": "msg-123"},
                        "clientState": "signed-state",
                    }
                ]
            }
        ),
    )

    assert response.accepted is True
    assert response.imported == 1
    assert response.skipped == 0
    assert response.ignored == 0
    assert len(response.results) == 1


@pytest.mark.asyncio
async def test_outlook_webhook_ignores_non_created_events(monkeypatch):
    class _FakeSessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def _expired(_session, *, policy):
        return []

    monkeypatch.setattr(freight, "evaluate_expired_quote_windows", _expired)
    monkeypatch.setattr(freight, "async_session", lambda: _FakeSessionContext())

    response = await freight.freight_outlook_webhook(
        http_request=_build_request(
            payload={
                "value": [
                    {
                        "changeType": "updated",
                        "resourceData": {"id": "msg-123"},
                    }
                ]
            }
        ),
    )

    assert response.accepted is True
    assert response.imported == 0
    assert response.ignored == 1
