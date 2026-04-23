"""AI Agent Backend — Pydantic schemas for API."""

from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Role(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class ShipmentStage(str, Enum):
    RECEIVED = "received"
    PARSING = "parsing"
    WAITING_CUSTOMER_DETAILS = "waiting_customer_details"
    CLIENT_ACKNOWLEDGED = "client_acknowledged"
    OUTREACHING = "outreaching"
    WAITING_BIDS = "waiting_bids"
    EVALUATING = "evaluating"
    QUOTED = "quoted"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    BOOKING_IN_PROGRESS = "booking_in_progress"
    BOOKING_FAILED = "booking_failed"
    BOOKED = "booked"
    EXPIRED = "expired"
    DECLINED = "declined"


class ArchiveReasonCode(str, Enum):
    DUPLICATE = "duplicate"
    CANCELLED = "cancelled"
    PARSED_ERROR = "parsed_error"
    FRAUD = "fraud"
    TEST = "test"
    NON_DELIVERY_BOUNCE = "non_delivery_bounce"
    OTHER = "other"


class WorkflowEventType(str, Enum):
    EMAIL_RECEIVED = "email_received"
    EMAIL_MARKED_READ = "email_marked_read"
    EMAIL_CATEGORIZED = "email_categorized"
    EMAIL_MOVED_TO_ARCHIVE = "email_moved_to_archive"
    PARSING_COMPLETED = "parsing_completed"
    SHIPMENT_PARSED = "shipment_parsed"
    SHIPMENT_FIELDS_UPDATED = "shipment_fields_updated"
    SHIPMENT_PARSE_FAILED = "shipment_parse_failed"
    CLIENT_ACK_SENT = "client_ack_sent"
    CARRIER_OUTREACH_SENT = "carrier_outreach_sent"
    BID_RECEIVED = "bid_received"
    BID_PARSE_FAILED = "bid_parse_failed"
    EVALUATION_COMPLETED = "evaluation_completed"
    CLIENT_QUOTE_SENT = "client_quote_sent"
    CUSTOMER_CONFIRMED = "customer_confirmed"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    DOCUMENT_ANALYZED = "document_analyzed"
    DOCUMENT_VALUES_APPROVED = "document_values_approved"
    DOCUMENT_WARNING_IGNORED = "document_warning_ignored"
    SHIPMENT_ARCHIVED = "shipment_archived"
    SHIPMENT_SOURCE_SUPPRESSED = "shipment_source_suppressed"
    TMS_HANDOFF_SENT = "tms_handoff_sent"
    TMS_STATUS_LOOKUP = "tms_status_lookup"
    CUSTOMER_STATUS_SENT = "customer_status_sent"
    TMS_STATUS_UPDATED = "tms_status_updated"
    TMS_STATUS_INGESTED = "tms_status_ingested"
    STATUS_WORKFLOW_RESOLVED = "status_workflow_resolved"
    EXCEPTION_RAISED = "exception_raised"


class MessageRequest(BaseModel):
    """Incoming message from the user."""

    content: str = Field(..., min_length=1, max_length=50_000)
    conversation_id: UUID | None = None
    browser_context: dict | None = None


class ToolCall(BaseModel):
    """A tool call made by the agent during reasoning."""

    tool_name: str
    tool_input: dict
    tool_output: str | None = None


class MessageResponse(BaseModel):
    """Response message from the agent."""

    id: UUID = Field(default_factory=uuid4)
    conversation_id: UUID
    role: Role = Role.ASSISTANT
    content: str
    tool_calls: list[ToolCall] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)


class StreamEvent(BaseModel):
    """Server-sent event during streaming."""

    event: str  # "token", "tool_start", "tool_end", "done", "error"
    data: str
    conversation_id: UUID | None = None


class ConversationInfo(BaseModel):
    """Summary of a conversation."""

    id: UUID
    title: str
    created_at: datetime
    message_count: int


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"


class MarginPolicy(BaseModel):
    percent: float = Field(..., ge=0)
    floor_amount: float = Field(0, ge=0)


class ClientUpsertRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: str = Field(..., min_length=3, max_length=320)
    is_active: bool = True
    default_margin_percent: float = Field(0, ge=0)
    default_margin_floor: float = Field(0, ge=0)


class ClientRecord(BaseModel):
    id: str
    name: str
    email: str
    is_active: bool
    default_margin_percent: float
    default_margin_floor: float
    created_at: datetime
    updated_at: datetime


class CarrierUpsertRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: str = Field(..., min_length=3, max_length=320)
    rating: float = Field(0, ge=0)
    is_active: bool = True
    regions: list[str] = Field(default_factory=list)
    equipment: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class CarrierRecord(BaseModel):
    id: str
    name: str
    email: str
    rating: float
    is_active: bool
    regions: list[str] = Field(default_factory=list)
    equipment: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ShipmentUpsertRequest(BaseModel):
    client_id: str | None = None
    status: ShipmentStage = ShipmentStage.RECEIVED
    origin: str | None = None
    destination: str | None = None
    pallets: int | None = Field(None, ge=0)
    weight_lb: float | None = Field(None, ge=0)
    equipment_type: str | None = Field(None, max_length=100)
    ready_at: datetime | None = None
    ready_at_local: datetime | None = None
    delivery_at: datetime | None = None
    delivery_at_local: datetime | None = None
    margin_policy: MarginPolicy | None = None
    notes: str = ""


class ShipmentRecord(BaseModel):
    id: str
    client_id: str | None = None
    email_thread_id: str | None = None
    status: str
    quote_token: str | None = None
    origin: str | None = None
    destination: str | None = None
    pallets: int | None = None
    weight_lb: float | None = None
    equipment_type: str | None = None
    ready_at: datetime | None = None
    ready_at_local: datetime | None = None
    ready_at_display: str | None = None
    ready_at_timezone: str | None = None
    ready_at_offset_minutes: int | None = None
    delivery_at: datetime | None = None
    delivery_at_local: datetime | None = None
    delivery_at_display: str | None = None
    delivery_at_timezone: str | None = None
    delivery_at_offset_minutes: int | None = None
    margin_policy: dict = Field(default_factory=dict)
    notes: str = ""
    ai_intent: str | None = None
    ai_confidence: float | None = None
    ai_missing_fields: list[str] = Field(default_factory=list)
    ai_ambiguity_reasons: list[str] = Field(default_factory=list)
    ai_next_action: str | None = None
    booking_state: str | None = None
    booking_error: str | None = None
    tms_handoff_status: str | None = None
    attachment_count: int = 0
    document_summary: dict[str, int] = Field(default_factory=dict)
    document_enrichment: dict = Field(default_factory=dict)
    document_health_status: str | None = None
    ocr_pending_count: int = 0
    document_conflict_count: int = 0
    missing_document_types: list[str] = Field(default_factory=list)
    booking_review_warning: str | None = None
    booking_review_required: bool = False
    last_known_status: str | None = None
    last_known_eta: str | None = None
    last_known_location: str | None = None
    last_status_source: str | None = None
    last_status_event_at: datetime | None = None
    tms_load_id: str | None = None
    tms_system: str | None = None
    status_workflow_state: str | None = None
    status_sync_health: str | None = None
    status_review_required: bool = False
    status_stale: bool = False
    status_sla_hours: int | None = None
    manual_review_required: bool = False
    board_stage: str | None = None
    attention_state: str = "none"
    attention_reason: str | None = None
    attention_level: str = "normal"
    has_active_review: bool = False
    has_active_status_review: bool = False
    has_active_booking_warning: bool = False
    next_step_label: str | None = None
    is_archived: bool = False
    archive_reason_code: ArchiveReasonCode | None = None
    archive_reason_note: str | None = None
    archived_reason: str | None = None
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class WorkflowEventRecord(BaseModel):
    id: str
    shipment_id: str
    event_type: str
    stage: str
    payload: dict = Field(default_factory=dict)
    created_at: datetime


class NotificationFeedItem(BaseModel):
    id: str
    shipment_id: str | None = None
    quote_token: str | None = None
    route: str | None = None
    status: str | None = None
    event_type: str
    stage: str
    kind: str
    title: str
    detail: str
    archived: bool = False
    created_at: datetime


class NotificationFeedResponse(BaseModel):
    items: list[NotificationFeedItem] = Field(default_factory=list)
    total: int = 0
    limit: int = 20
    offset: int = 0
    has_more: bool = False


class ShipmentDocumentRecord(BaseModel):
    id: str | None = None
    name: str | None = None
    document_type: str
    content_type: str | None = None
    size: int | None = None
    extracted_text_preview: str | None = None
    extracted_fields: dict = Field(default_factory=dict)
    extraction_method: str | None = None
    ocr_status: str | None = None
    ocr_confidence: float | None = None
    field_confidence: float | None = None
    review_required: bool = False
    review_reason: str | None = None
    source_email_id: str


class ShipmentThreadMessageRecord(BaseModel):
    id: str
    thread_id: str
    provider_message_id: str | None = None
    direction: str
    sender: str
    recipients: list[str] = Field(default_factory=list)
    subject: str
    received_at: datetime
    body_preview: str = ""
    display_body: str = ""
    has_raw_payload: bool = False


class ShipmentThreadResponse(BaseModel):
    shipment_id: str
    thread_id: str | None = None
    thread_subject: str | None = None
    quote_token: str | None = None
    messages: list[ShipmentThreadMessageRecord] = Field(default_factory=list)


class ShipmentMagicField(str, Enum):
    READY_AT_LOCAL = "ready_at_local"


class ShipmentMagicFillRequest(BaseModel):
    field: ShipmentMagicField
    apply_value: bool = True


class ShipmentMagicFillResponse(BaseModel):
    shipment_id: str
    field: ShipmentMagicField
    status: str
    message: str
    confidence: float = 0
    suggested_value: str | None = None
    ambiguity_reasons: list[str] = Field(default_factory=list)
    source_messages: int = 0
    shipment: ShipmentRecord | None = None


class DocumentContentResult(BaseModel):
    raw_text: str = ""
    raw_text_preview: str | None = None
    extraction_method: str | None = None
    ocr_status: str | None = None
    ocr_confidence: float | None = None
    review_required: bool = False
    review_reason: str | None = None


class DocumentFieldResult(BaseModel):
    extracted_fields: dict = Field(default_factory=dict)
    field_confidence: float | None = None
    review_required: bool = False
    review_reason: str | None = None


class DocumentExtract(BaseModel):
    document_type: str
    raw_text_preview: str | None = None
    extraction_method: str | None = None
    ocr_status: str | None = None
    ocr_confidence: float | None = None
    field_confidence: float | None = None
    extracted_fields: dict = Field(default_factory=dict)
    review_required: bool = False
    review_reason: str | None = None


class DocumentQualityExpectation(BaseModel):
    expected_document_type: str
    expected_fields: dict = Field(default_factory=dict)
    expected_review_required: bool = False
    expected_enrichment_fields: dict = Field(default_factory=dict)
    expected_conflict_fields: list[str] = Field(default_factory=list)


class DocumentQualitySample(BaseModel):
    sample_id: str
    document_family: str
    source_format: str
    filename: str
    content_type: str
    content_text: str
    notes: str = ""
    shipment_ready_at: datetime | None = None
    expectation: DocumentQualityExpectation


class DocumentQualityResult(BaseModel):
    sample_id: str
    document_family: str
    source_format: str
    passed: bool = False
    document_type: str
    extraction_method: str | None = None
    ocr_status: str | None = None
    ocr_confidence: float | None = None
    field_confidence: float | None = None
    review_required: bool = False
    expected_review_required: bool = False
    extracted_fields: dict = Field(default_factory=dict)
    expected_fields: dict = Field(default_factory=dict)
    document_enrichment: dict = Field(default_factory=dict)
    expected_enrichment_fields: dict = Field(default_factory=dict)
    document_conflict_fields: list[str] = Field(default_factory=list)
    expected_conflict_fields: list[str] = Field(default_factory=list)
    document_health_status: str | None = None
    false_positive_fields: list[str] = Field(default_factory=list)
    mismatches: list[str] = Field(default_factory=list)


class DocumentQualityRunSummary(BaseModel):
    run_at: datetime
    sample_count: int = 0
    metrics: dict = Field(default_factory=dict)
    results: list[DocumentQualityResult] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)


class QuoteReference(BaseModel):
    quote_id: str
    subject_token: str


class EmailCorrelationSignals(BaseModel):
    internet_message_id: str | None = None
    in_reply_to: str | None = None
    references: list[str] = Field(default_factory=list)
    conversation_id: str | None = None
    subject: str = ""
    normalized_subject: str = ""
    quote_token: str | None = None
    sender: str | None = None


class FreightFoundationResponse(BaseModel):
    stages: list[ShipmentStage] = Field(default_factory=list)
    event_types: list[WorkflowEventType] = Field(default_factory=list)
    correlation_strategy: list[str] = Field(default_factory=list)
    margin_defaults: MarginPolicy


class FreightOverviewCounts(BaseModel):
    clients: int = 0
    carriers: int = 0
    email_threads: int = 0
    email_messages: int = 0
    shipments: int = 0
    bids: int = 0
    workflow_events: int = 0


class FreightStatusMetrics(BaseModel):
    lookups: int = 0
    replies_drafted: int = 0
    replies_sent: int = 0
    carrier_updates_parsed: int = 0
    carrier_updates_pushed: int = 0
    review_required: int = 0
    stale_shipments: int = 0


class FreightSlaSummary(BaseModel):
    status_stale_after_hours: int = 24


class FreightOverviewResponse(BaseModel):
    counts: FreightOverviewCounts
    active_stages: dict[str, int] = Field(default_factory=dict)
    status_metrics: FreightStatusMetrics = Field(default_factory=FreightStatusMetrics)
    sla: FreightSlaSummary = Field(default_factory=FreightSlaSummary)
    integrations: dict[str, str] = Field(default_factory=dict)


class OutlookSyncRequest(BaseModel):
    limit: int = Field(10, ge=1, le=100)
    auto_acknowledge_new_shipments: bool = True
    acknowledgement_dry_run: bool = True
    auto_prepare_outreach_for_new_shipments: bool = True
    outreach_dry_run: bool = True
    auto_send_customer_quotes: bool = True
    customer_quote_dry_run: bool = False
    auto_book_on_confirmation: bool = True
    booking_dry_run: bool = False


class OutlookIngestRequest(BaseModel):
    message: dict
    create_client_if_missing: bool = True
    auto_acknowledge_new_shipment: bool = True
    acknowledgement_dry_run: bool = True
    auto_prepare_outreach_for_new_shipment: bool = True
    outreach_dry_run: bool = True
    auto_send_customer_quote: bool = True
    customer_quote_dry_run: bool = False
    auto_book_on_confirmation: bool = True
    booking_dry_run: bool = False


class OutlookWebhookNotification(BaseModel):
    subscriptionId: str | None = None
    clientState: str | None = None
    changeType: str | None = None
    resource: str | None = None
    tenantId: str | None = None
    resourceData: dict = Field(default_factory=dict)


class OutlookWebhookRequest(BaseModel):
    value: list[OutlookWebhookNotification] = Field(default_factory=list)


class OutlookIngestResult(BaseModel):
    thread_id: str
    email_message_id: str
    shipment_id: str
    client_id: str | None = None
    created_thread: bool = False
    created_message: bool = False
    created_shipment: bool = False
    created_client: bool = False
    acknowledgement_drafted: bool = False
    acknowledgement_subject: str | None = None
    outreach_drafted: bool = False
    outreach_subject: str | None = None
    outreach_targeted: int = 0
    bid_intaken: bool = False
    bid_id: str | None = None
    bid_amount: float | None = None
    intent: str | None = None
    confidence: float | None = None
    shipment_extracted: bool = False
    missing_fields: list[str] = Field(default_factory=list)
    ambiguity_reasons: list[str] = Field(default_factory=list)
    manual_review_required: bool = False
    next_action: str | None = None
    evaluation_triggered: bool = False
    quote_auto_sent: bool = False
    booking_triggered: bool = False
    booking_confirmation_sent: bool = False
    tms_handoff_status: str | None = None
    status_lookup_triggered: bool = False
    status_reply_sent: bool = False
    tms_status_updated: bool = False
    suppressed: bool = False
    suppression_reason: str | None = None
    shipment_creation_skipped: bool = False
    event_type: WorkflowEventType = WorkflowEventType.EMAIL_RECEIVED


class OutlookSyncResponse(BaseModel):
    imported: int = 0
    skipped: int = 0
    parsed_shipments: int = 0
    auto_acknowledgements: int = 0
    auto_outreach: int = 0
    auto_bids: int = 0
    auto_evaluations: int = 0
    auto_quotes: int = 0
    auto_status_replies: int = 0
    auto_tms_status_updates: int = 0
    manual_reviews: int = 0
    results: list[OutlookIngestResult] = Field(default_factory=list)


class OutlookWebhookResponse(BaseModel):
    accepted: bool = True
    imported: int = 0
    skipped: int = 0
    ignored: int = 0
    manual_reviews: int = 0
    results: list[OutlookIngestResult] = Field(default_factory=list)


class IntentResult(BaseModel):
    intent: str
    confidence: float = Field(0, ge=0, le=1)
    notes: str = ""


class ShipmentExtractionResult(BaseModel):
    intent: str = "new_quote_request"
    origin: str | None = None
    destination: str | None = None
    pallets: int | None = Field(None, ge=0)
    weight_lb: float | None = Field(None, ge=0)
    equipment_type: str | None = None
    ready_at: datetime | None = None
    delivery_at: datetime | None = None
    notes: str = ""
    missing_fields: list[str] = Field(default_factory=list)
    ambiguity_reasons: list[str] = Field(default_factory=list)
    confidence: float = Field(0, ge=0, le=1)


class ShipmentFieldExtractionResult(BaseModel):
    field: str
    value_local_text: str | None = None
    confidence: float = Field(0, ge=0, le=1)
    notes: str = ""
    ambiguity_reasons: list[str] = Field(default_factory=list)


class CarrierBidExtractionResult(BaseModel):
    intent: str = "carrier_bid_reply"
    amount: float | None = Field(None, ge=0)
    currency: str = "USD"
    eta_text: str | None = None
    notes: str = ""
    ambiguity_reasons: list[str] = Field(default_factory=list)
    confidence: float = Field(0, ge=0, le=1)


class StatusRequestExtractionResult(BaseModel):
    intent: str = "customer_status_request"
    request_type: str = "general_status"
    requested_fields: list[str] = Field(default_factory=list)
    notes: str = ""
    confidence: float = Field(0, ge=0, le=1)


class CarrierStatusUpdateExtractionResult(BaseModel):
    intent: str = "carrier_status_update"
    status_text: str | None = None
    eta_text: str | None = None
    location_text: str | None = None
    notes: str = ""
    ambiguity_reasons: list[str] = Field(default_factory=list)
    confidence: float = Field(0, ge=0, le=1)


class AutomationPolicy(BaseModel):
    auto_acknowledgement: bool = True
    acknowledgement_dry_run: bool = False
    auto_outreach: bool = True
    outreach_dry_run: bool = False
    auto_quote: bool = True
    quote_dry_run: bool = False
    auto_book: bool = True
    booking_dry_run: bool = False
    allow_repeat_manual_review: bool = False


class WorkflowDecisionResult(BaseModel):
    email_message_id: str
    shipment_id: str | None = None
    intent: str
    confidence: float = Field(0, ge=0, le=1)
    next_action: str
    shipment_extracted: bool = False
    missing_fields: list[str] = Field(default_factory=list)
    ambiguity_reasons: list[str] = Field(default_factory=list)
    acknowledgement_drafted: bool = False
    acknowledgement_subject: str | None = None
    outreach_drafted: bool = False
    outreach_subject: str | None = None
    outreach_targeted: int = 0
    bid_intaken: bool = False
    bid_id: str | None = None
    bid_amount: float | None = None
    evaluation_triggered: bool = False
    quote_auto_sent: bool = False
    booking_triggered: bool = False
    booking_confirmation_sent: bool = False
    tms_handoff_status: str | None = None
    status_lookup_triggered: bool = False
    status_reply_sent: bool = False
    tms_status_updated: bool = False
    manual_review_required: bool = False


class ReviewQueueItem(BaseModel):
    workflow_event_id: str
    shipment_id: str
    stage: str
    event_type: str
    review_type: str | None = None
    priority: str = "normal"
    alert_label: str | None = None
    reason: str = ""
    next_action: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    ambiguity_reasons: list[str] = Field(default_factory=list)
    missing_document_types: list[str] = Field(default_factory=list)
    document_conflict_fields: list[str] = Field(default_factory=list)
    booking_review_warning: str | None = None
    status_stale: bool = False
    status_review_required: bool = False
    created_at: datetime


class StatusQueueItem(BaseModel):
    task_id: str
    task_type: str
    task_state: str
    queue_scope: str = "active"
    resolution_state: str | None = None
    resolution_reason: str | None = None
    resolution_at: datetime | None = None
    shipment_id: str
    email_thread_id: str | None = None
    source_email_id: str | None = None
    priority: str = "normal"
    alert_label: str | None = None
    reason: str = ""
    recommended_next_action: str | None = None
    review_type: str | None = None
    ambiguity_reasons: list[str] = Field(default_factory=list)
    latest_status_snapshot: dict = Field(default_factory=dict)
    draft_subject: str | None = None
    draft_body: str | None = None
    structured_payload: dict = Field(default_factory=dict)
    last_failure: str | None = None
    tms_load_id: str | None = None
    tms_system: str | None = None
    status_sync_health: str | None = None
    created_at: datetime


class StatusQueueAction(str, Enum):
    PREVIEW = "preview"
    APPROVE_AND_SEND = "approve_and_send"
    APPROVE_AND_PUSH = "approve_and_push"
    REBUILD_DRAFT = "rebuild_draft"
    RETRY_PUSH = "retry_push"
    DISMISS = "dismiss"


class StatusQueueActionRequest(BaseModel):
    action: StatusQueueAction
    custom_message: str | None = None
    draft_subject: str | None = None
    draft_body: str | None = None
    status_text: str | None = None
    eta_text: str | None = None
    location_text: str | None = None
    notes: str | None = None


class StatusQueueActionResponse(BaseModel):
    task_id: str
    task_type: str
    action: StatusQueueAction
    status: str
    message: str
    task_state: str
    resolution_state: str | None = None
    resolution_reason: str | None = None
    shipment_id: str
    preview: dict = Field(default_factory=dict)


class TmsStatusIngestRequest(BaseModel):
    external_event_id: str | None = None
    tms_load_id: str | None = None
    external_load_ref: str | None = None
    tms_system: str | None = None
    quote_token: str | None = None
    shipment_id: str | None = None
    status: str | None = None
    eta: str | None = None
    location: str | None = None
    milestone: str | None = None
    source_timestamp: datetime | None = None
    payload: dict = Field(default_factory=dict)


class TmsStatusIngestResponse(BaseModel):
    shipment_id: str
    status: str
    event_type: str
    tms_load_id: str | None = None


class OperatorAction(str, Enum):
    RESUME_WORKFLOW = "resume_workflow"
    APPROVE_AND_CONTINUE = "approve_and_continue"
    RERUN_PARSING = "rerun_parsing"
    RERUN_OUTREACH = "rerun_outreach"
    RERUN_EVALUATION = "rerun_evaluation"
    RERUN_STATUS_LOOKUP = "rerun_status_lookup"
    RERUN_TMS_UPDATE = "rerun_tms_update"
    APPROVE_STATUS_REPLY = "approve_status_reply"
    RERUN_DOCUMENT_EXTRACTION = "rerun_document_extraction"
    APPROVE_DOCUMENT_VALUES = "approve_document_values"
    IGNORE_DOCUMENT_WARNING = "ignore_document_warning"
    ARCHIVE_SHIPMENT = "archive_shipment"


class ShipmentOperatorActionRequest(BaseModel):
    action: OperatorAction
    reason: str | None = None
    reason_code: ArchiveReasonCode | None = None
    reason_note: str | None = None
    suppress_source_thread: bool = True


class ShipmentArchiveRequest(BaseModel):
    reason_code: ArchiveReasonCode = ArchiveReasonCode.OTHER
    reason_note: str | None = None
    suppress_source_thread: bool = True


class ShipmentOperatorActionResponse(BaseModel):
    shipment_id: str
    action: OperatorAction
    status: str
    message: str
    next_action: str
    manual_review_required: bool = False
    acknowledgement_sent: bool = False
    outreach_sent: bool = False
    evaluation_triggered: bool = False
    quote_sent: bool = False
    archived: bool = False
    suppression_applied: bool = False
    suppressed_thread_id: str | None = None
    decision: WorkflowDecisionResult | None = None


class CarrierOutreachRequest(BaseModel):
    carrier_ids: list[str] = Field(default_factory=list)
    dry_run: bool = True
    custom_message: str | None = None


class CarrierOutreachItem(BaseModel):
    carrier_id: str
    carrier_email: str
    carrier_name: str
    bid_id: str | None = None
    email_message_id: str | None = None
    status: str


class CarrierOutreachResponse(BaseModel):
    shipment_id: str
    thread_id: str
    quote_token: str
    subject: str
    body: str
    dry_run: bool
    targeted: int = 0
    created_bids: int = 0
    results: list[CarrierOutreachItem] = Field(default_factory=list)


class BidIntakeRequest(BaseModel):
    shipment_id: str | None = None
    carrier_id: str | None = None
    carrier_email: str | None = None
    email_message_id: str | None = None
    subject: str = ""
    amount: float = Field(..., ge=0)
    currency: str = Field("USD", min_length=1, max_length=10)
    eta_text: str | None = None
    raw_email: str = ""
    sender_email: str | None = None
    resolved_carrier_email: str | None = None
    carrier_resolution_mode: str | None = None
    carrier_resolution_reason: str | None = None
    identity_mismatch: bool = False
    create_carrier_if_missing: bool = False


class BidRecord(BaseModel):
    id: str
    shipment_id: str
    carrier_id: str
    carrier_name: str
    carrier_email: str
    amount: float | None = None
    currency: str
    eta_text: str | None = None
    status: str
    score: dict = Field(default_factory=dict)
    received_at: datetime


class BidIntakeResponse(BaseModel):
    shipment_id: str
    bid: BidRecord
    created_carrier: bool = False
    created_email_message: bool = False


class ShipmentEvaluationResponse(BaseModel):
    shipment_id: str
    selected_bid_id: str
    selected_carrier_id: str
    selected_amount: float
    recommended_quote_amount: float
    margin_amount: float
    results: list[BidRecord] = Field(default_factory=list)


class ClientAcknowledgementRequest(BaseModel):
    dry_run: bool = True
    custom_message: str | None = None


class ClientAcknowledgementResponse(BaseModel):
    shipment_id: str
    client_email: str
    subject: str
    body: str
    dry_run: bool


class BookingConfirmationResponse(BaseModel):
    shipment_id: str
    client_email: str
    subject: str
    body: str
    dry_run: bool


class CustomerQuoteRequest(BaseModel):
    bid_id: str | None = None
    dry_run: bool = True
    custom_message: str | None = None


class CustomerQuoteResponse(BaseModel):
    shipment_id: str
    bid_id: str
    client_email: str
    subject: str
    body: str
    base_amount: float
    margin_amount: float
    final_amount: float
    dry_run: bool


class TmsHandoffRequest(BaseModel):
    bid_id: str | None = None
    dry_run: bool = True


class TmsHandoffResponse(BaseModel):
    shipment_id: str
    bid_id: str
    status: str
    dry_run: bool
    payload: dict = Field(default_factory=dict)
    response: dict = Field(default_factory=dict)


class TmsStatusResponse(BaseModel):
    shipment_id: str
    status: str
    payload: dict = Field(default_factory=dict)


class CustomerStatusReplyResponse(BaseModel):
    shipment_id: str
    client_email: str
    subject: str
    body: str
    dry_run: bool


class CustomerStatusReplyRequest(BaseModel):
    dry_run: bool = True
    custom_message: str | None = None


class CarrierStatusUpdateRequest(BaseModel):
    dry_run: bool = True
    status_text: str | None = None
    eta_text: str | None = None
    location_text: str | None = None
    notes: str | None = None


class CarrierStatusUpdateResponse(BaseModel):
    shipment_id: str
    status: str
    dry_run: bool
    status_text: str | None = None
    eta_text: str | None = None
    location_text: str | None = None
    notes: str | None = None
    payload: dict = Field(default_factory=dict)


class BookingExecutionResponse(BaseModel):
    shipment_id: str
    dry_run: bool
    handoff: TmsHandoffResponse
    confirmation: BookingConfirmationResponse


class IntegrationStatus(BaseModel):
    name: str
    configured: bool
    status: str
    missing_fields: list[str] = Field(default_factory=list)
    details: dict = Field(default_factory=dict)


class IntegrationsStatusResponse(BaseModel):
    email: IntegrationStatus
    tms: IntegrationStatus
    defaults: dict = Field(default_factory=dict)
