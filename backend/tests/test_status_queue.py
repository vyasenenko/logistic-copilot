from datetime import datetime, timezone
from uuid import uuid4

from app.api.freight import (
    _board_stage_from_status,
    _build_resolved_status_queue_item,
    _build_status_queue_item,
    _derive_attention_projection,
    _status_task_type_from_event,
    _status_task_state_from_resolution,
    _status_queue_task_type,
    _status_sync_health,
)
from app.memory.database import Shipment, WorkflowEvent
from app.schemas import ShipmentStage, WorkflowEventType


def test_status_queue_task_type_mapping():
    assert _status_queue_task_type("customer_status_request_review") == "status_reply"
    assert _status_queue_task_type("carrier_status_update_review") == "carrier_update"
    assert _status_queue_task_type("other_review") is None


def test_status_task_type_from_event_matches_queue_rules():
    shipment = Shipment(id=uuid4(), status=ShipmentStage.BOOKED.value)

    dry_run_reply = WorkflowEvent(
        id=uuid4(),
        shipment_id=shipment.id,
        event_type=WorkflowEventType.CUSTOMER_STATUS_SENT.value,
        stage=shipment.status,
        payload_json={"dry_run": True},
        created_at=datetime.now(timezone.utc),
    )
    assert _status_task_type_from_event(dry_run_reply, dry_run_reply.payload_json or {}) == "status_reply"

    carrier_preview = WorkflowEvent(
        id=uuid4(),
        shipment_id=shipment.id,
        event_type=WorkflowEventType.TMS_STATUS_UPDATED.value,
        stage=shipment.status,
        payload_json={"status_audit_kind": "carrier_update_parsed"},
        created_at=datetime.now(timezone.utc),
    )
    assert _status_task_type_from_event(carrier_preview, carrier_preview.payload_json or {}) == "carrier_update"


def test_status_sync_health_prioritizes_stale_and_failure():
    assert _status_sync_health(status_stale=True, status_review_required=False, status_workflow_state=None) == "stale"
    assert _status_sync_health(status_stale=False, status_review_required=False, status_workflow_state="failed") == "failed"
    assert _status_sync_health(status_stale=False, status_review_required=True, status_workflow_state=None) == "review_required"
    assert _status_sync_health(status_stale=False, status_review_required=False, status_workflow_state="status_reply_drafted") == "attention_needed"
    assert _status_sync_health(status_stale=False, status_review_required=False, status_workflow_state="status_reply_sent") == "healthy"


def test_board_stage_from_status_uses_business_lanes():
    assert _board_stage_from_status(ShipmentStage.RECEIVED.value) == "parsing"
    assert _board_stage_from_status(ShipmentStage.WAITING_CUSTOMER_DETAILS.value) == "parsing"
    assert _board_stage_from_status(ShipmentStage.WAITING_BIDS.value) == "waiting_bids"
    assert _board_stage_from_status(ShipmentStage.QUOTED.value) == "quoted"
    assert _board_stage_from_status(ShipmentStage.BOOKING_FAILED.value) == "booked"
    assert _board_stage_from_status(ShipmentStage.DECLINED.value) == "closed"


def test_attention_projection_prioritizes_blocker_signal():
    state, reason, level = _derive_attention_projection(
        manual_review_required=True,
        ai_missing_fields=["origin", "destination"],
        ai_ambiguity_reasons=[],
        status_review_required=False,
        booking_review_required=False,
        status_stale=False,
    )
    assert state == "missing_details"
    assert "origin" in (reason or "")
    assert level == "high"

    stale_state, stale_reason, stale_level = _derive_attention_projection(
        manual_review_required=False,
        ai_missing_fields=[],
        ai_ambiguity_reasons=[],
        status_review_required=False,
        booking_review_required=False,
        status_stale=True,
    )
    assert stale_state == "stale"
    assert stale_reason == "Shipment status is stale"
    assert stale_level == "critical"


def test_build_status_queue_item_for_status_reply_review():
    shipment = Shipment(
        id=uuid4(),
        status=ShipmentStage.BOOKED.value,
        email_thread_id=uuid4(),
    )
    event = WorkflowEvent(
        id=uuid4(),
        shipment_id=shipment.id,
        event_type=WorkflowEventType.MANUAL_REVIEW_REQUIRED.value,
        stage=shipment.status,
        payload_json={
            "reason": "Customer status reply requires operator approval",
            "review_type": "customer_status_request_review",
            "next_action": "approve_status_reply",
            "structured_payload": {
                "draft_subject": "Status update [Q-123]",
                "draft_body": "Here is the latest update.",
            },
            "source_email_id": str(uuid4()),
        },
        created_at=datetime.now(timezone.utc),
    )

    item = _build_status_queue_item(
        event=event,
        shipment=shipment,
        status_payload={
            "last_known_status": "in_transit",
            "last_known_eta": "Tomorrow",
            "last_known_location": "Columbus, OH",
            "last_status_source": "tms_lookup",
            "last_status_event_at": datetime.now(timezone.utc),
        },
        tms_identity_payload={"tms_load_id": "LOAD-123", "tms_system": "generic"},
        workflow_payload={"status_workflow_state": "awaiting_status_review"},
    )

    assert item is not None
    assert item.task_type == "status_reply"
    assert item.task_state == "awaiting_approval"
    assert item.draft_subject == "Status update [Q-123]"
    assert item.draft_body == "Here is the latest update."
    assert item.tms_load_id == "LOAD-123"
    assert item.latest_status_snapshot["status"] == "in_transit"


def test_build_status_queue_item_for_carrier_update_preview():
    shipment = Shipment(
        id=uuid4(),
        status=ShipmentStage.BOOKED.value,
    )
    event = WorkflowEvent(
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
                "notes": "Driver on site",
            },
        },
        created_at=datetime.now(timezone.utc),
    )

    item = _build_status_queue_item(
        event=event,
        shipment=shipment,
        status_payload={"last_status_event_at": datetime.now(timezone.utc)},
        tms_identity_payload={},
        workflow_payload={"status_workflow_state": "carrier_update_parsed"},
    )

    assert item is not None
    assert item.task_type == "carrier_update"
    assert item.task_state == "awaiting_review"
    assert item.structured_payload["status_text"] == "arrived"


def test_status_task_state_from_resolution_is_explicit():
    assert _status_task_state_from_resolution(task_type="status_reply", resolution_state="sent") == "sent"
    assert _status_task_state_from_resolution(task_type="carrier_update", resolution_state="pushed") == "pushed"
    assert _status_task_state_from_resolution(task_type="status_reply", resolution_state="resolved_no_send") == "resolved_no_send"
    assert _status_task_state_from_resolution(task_type="carrier_update", resolution_state="resolved_no_push") == "resolved_no_push"


def test_build_resolved_status_queue_item_preserves_source_context():
    shipment = Shipment(
        id=uuid4(),
        status=ShipmentStage.BOOKED.value,
        email_thread_id=uuid4(),
    )
    source_event = WorkflowEvent(
        id=uuid4(),
        shipment_id=shipment.id,
        event_type=WorkflowEventType.CUSTOMER_STATUS_SENT.value,
        stage=shipment.status,
        payload_json={
            "dry_run": True,
            "subject": "Status update [Q-123]",
            "body": "Current ETA is tomorrow morning.",
        },
        created_at=datetime.now(timezone.utc),
    )
    resolution_event = WorkflowEvent(
        id=uuid4(),
        shipment_id=shipment.id,
        event_type=WorkflowEventType.STATUS_WORKFLOW_RESOLVED.value,
        stage=shipment.status,
        payload_json={
            "task_type": "status_reply",
            "resolution_state": "resolved_no_send",
            "resolution_reason": "superseded_by_newer_snapshot",
            "source_task_id": str(source_event.id),
        },
        created_at=datetime.now(timezone.utc),
    )

    item = _build_resolved_status_queue_item(
        resolution_event=resolution_event,
        shipment=shipment,
        source_event=source_event,
        status_payload={
            "last_known_status": "in_transit",
            "last_known_eta": "Tomorrow",
            "last_known_location": "Columbus, OH",
            "last_status_source": "tms_inbound_sync",
            "last_status_event_at": datetime.now(timezone.utc),
        },
        tms_identity_payload={"tms_load_id": "LOAD-123", "tms_system": "generic"},
    )

    assert item is not None
    assert item.queue_scope == "resolved"
    assert item.task_state == "resolved_no_send"
    assert item.resolution_state == "resolved_no_send"
    assert item.resolution_reason == "superseded_by_newer_snapshot"
    assert item.draft_subject == "Status update [Q-123]"
    assert item.tms_load_id == "LOAD-123"
