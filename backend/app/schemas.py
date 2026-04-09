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
    CLIENT_ACKNOWLEDGED = "client_acknowledged"
    OUTREACHING = "outreaching"
    WAITING_BIDS = "waiting_bids"
    EVALUATING = "evaluating"
    QUOTED = "quoted"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    BOOKED = "booked"
    EXPIRED = "expired"
    DECLINED = "declined"


class WorkflowEventType(str, Enum):
    EMAIL_RECEIVED = "email_received"
    PARSING_COMPLETED = "parsing_completed"
    CLIENT_ACK_SENT = "client_ack_sent"
    CARRIER_OUTREACH_SENT = "carrier_outreach_sent"
    BID_RECEIVED = "bid_received"
    EVALUATION_COMPLETED = "evaluation_completed"
    CLIENT_QUOTE_SENT = "client_quote_sent"
    CUSTOMER_CONFIRMED = "customer_confirmed"
    TMS_HANDOFF_SENT = "tms_handoff_sent"
    EXCEPTION_RAISED = "exception_raised"


class MessageRequest(BaseModel):
    """Incoming message from the user."""

    content: str = Field(..., min_length=1, max_length=50_000)
    conversation_id: UUID | None = None


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
    margin_policy: dict = Field(default_factory=dict)
    notes: str = ""
    created_at: datetime
    updated_at: datetime


class WorkflowEventRecord(BaseModel):
    id: str
    shipment_id: str
    event_type: str
    stage: str
    payload: dict = Field(default_factory=dict)
    created_at: datetime


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


class FreightOverviewResponse(BaseModel):
    counts: FreightOverviewCounts
    active_stages: dict[str, int] = Field(default_factory=dict)
    integrations: dict[str, str] = Field(default_factory=dict)


class OutlookSyncRequest(BaseModel):
    limit: int = Field(10, ge=1, le=100)


class OutlookIngestRequest(BaseModel):
    message: dict
    create_client_if_missing: bool = True


class OutlookIngestResult(BaseModel):
    thread_id: str
    email_message_id: str
    shipment_id: str
    client_id: str | None = None
    created_thread: bool = False
    created_message: bool = False
    created_shipment: bool = False
    created_client: bool = False
    event_type: WorkflowEventType = WorkflowEventType.EMAIL_RECEIVED


class OutlookSyncResponse(BaseModel):
    imported: int = 0
    skipped: int = 0
    results: list[OutlookIngestResult] = Field(default_factory=list)


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
