"""PostgreSQL database — conversations and message history."""

import ssl
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship

from app.config import settings


def _postgres_connect_args() -> dict:
    if not settings.postgres_ssl:
        return {}
    if settings.postgres_ssl_skip_verify:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return {"ssl": ctx}
    ctx = ssl.create_default_context()
    ca_file = settings.postgres_ssl_ca_file.strip()
    if ca_file:
        ctx.load_verify_locations(ca_file)
    return {"ssl": ctx}


engine = create_async_engine(settings.postgres_url, echo=False, connect_args=_postgres_connect_args())
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(500), default="New conversation")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    messages = relationship("Message", back_populates="conversation", order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False)
    role = Column(String(20), nullable=False)  # user, assistant, system, tool
    content = Column(Text, nullable=False)
    tool_calls_json = Column(Text, default="[]")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    conversation = relationship("Conversation", back_populates="messages")


class Client(Base):
    __tablename__ = "clients"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    email = Column(String(320), nullable=False, unique=True)
    is_active = Column(Boolean, default=True, nullable=False)
    default_margin_percent = Column(Float, default=0, nullable=False)
    default_margin_floor = Column(Float, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    shipments = relationship("Shipment", back_populates="client")


class Carrier(Base):
    __tablename__ = "carriers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    email = Column(String(320), nullable=False, unique=True)
    rating = Column(Float, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    regions_json = Column(JSON, default=list, nullable=False)
    equipment_json = Column(JSON, default=list, nullable=False)
    metadata_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    bids = relationship("CarrierBid", back_populates="carrier")


class EmailThread(Base):
    __tablename__ = "email_threads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider = Column(String(50), default="outlook", nullable=False)
    mailbox = Column(String(320), nullable=False)
    provider_thread_id = Column(String(255), nullable=True, unique=True)
    quote_token = Column(String(32), nullable=True, unique=True)
    subject = Column(String(500), nullable=False)
    normalized_subject = Column(String(500), nullable=False)
    last_message_at = Column(DateTime(timezone=True), nullable=True)
    shipment_ingest_suppressed = Column(Boolean, default=False, nullable=False)
    shipment_ingest_suppressed_reason = Column(String(500), nullable=True)
    shipment_ingest_suppressed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    messages = relationship("EmailMessage", back_populates="thread", order_by="EmailMessage.received_at")
    shipments = relationship("Shipment", back_populates="email_thread")


class EmailMessage(Base):
    __tablename__ = "email_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id = Column(UUID(as_uuid=True), ForeignKey("email_threads.id"), nullable=False)
    provider_message_id = Column(String(255), nullable=True, unique=True)
    internet_message_id = Column(String(500), nullable=True)
    conversation_id = Column(String(255), nullable=True)
    in_reply_to = Column(String(500), nullable=True)
    references_json = Column(JSON, default=list, nullable=False)
    sender = Column(String(320), nullable=False)
    recipients_json = Column(JSON, default=list, nullable=False)
    direction = Column(String(20), nullable=False)
    subject = Column(String(500), nullable=False)
    body_preview = Column(Text, default="", nullable=False)
    raw_payload_json = Column(JSON, default=dict, nullable=False)
    received_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    thread = relationship("EmailThread", back_populates="messages")
    bids = relationship("CarrierBid", back_populates="email_message")


class Shipment(Base):
    __tablename__ = "shipments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=True)
    email_thread_id = Column(UUID(as_uuid=True), ForeignKey("email_threads.id"), nullable=True)
    status = Column(String(50), nullable=False, default="received")
    quote_token = Column(String(32), nullable=True, unique=True)
    origin = Column(String(255), nullable=True)
    destination = Column(String(255), nullable=True)
    pallets = Column(Integer, nullable=True)
    weight_lb = Column(Float, nullable=True)
    equipment_type = Column(String(100), nullable=True)
    # Canonical pickup-ready UTC instant.
    ready_at = Column(DateTime(timezone=True), nullable=True)
    # Pickup local "wall clock" time; zone is ready_at_timezone (IANA).
    ready_at_local = Column(DateTime(timezone=False), nullable=True)
    ready_at_timezone = Column(String(64), nullable=True)
    ready_at_offset_minutes = Column(Integer, nullable=True)
    # Canonical delivery UTC instant and local destination wall time.
    delivery_at = Column(DateTime(timezone=True), nullable=True)
    delivery_at_local = Column(DateTime(timezone=False), nullable=True)
    delivery_at_timezone = Column(String(64), nullable=True)
    delivery_at_offset_minutes = Column(Integer, nullable=True)
    margin_policy_json = Column(JSON, default=dict, nullable=False)
    notes = Column(Text, default="", nullable=False)
    is_archived = Column(Boolean, default=False, nullable=False)
    archive_reason_code = Column(String(50), nullable=True)
    archive_reason_note = Column(String(500), nullable=True)
    archived_reason = Column(String(500), nullable=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    client = relationship("Client", back_populates="shipments")
    email_thread = relationship("EmailThread", back_populates="shipments")
    bids = relationship("CarrierBid", back_populates="shipment", order_by="CarrierBid.received_at")
    workflow_events = relationship(
        "WorkflowEvent",
        back_populates="shipment",
        order_by="WorkflowEvent.created_at",
    )


class CarrierBid(Base):
    __tablename__ = "carrier_bids"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shipment_id = Column(UUID(as_uuid=True), ForeignKey("shipments.id"), nullable=False)
    carrier_id = Column(UUID(as_uuid=True), ForeignKey("carriers.id"), nullable=False)
    email_message_id = Column(UUID(as_uuid=True), ForeignKey("email_messages.id"), nullable=True)
    amount = Column(Float, nullable=True)
    currency = Column(String(10), default="USD", nullable=False)
    eta_text = Column(String(255), nullable=True)
    status = Column(String(50), default="pending", nullable=False)
    raw_email = Column(Text, default="", nullable=False)
    score_json = Column(JSON, default=dict, nullable=False)
    received_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    shipment = relationship("Shipment", back_populates="bids")
    carrier = relationship("Carrier", back_populates="bids")
    email_message = relationship("EmailMessage", back_populates="bids")


class WorkflowEvent(Base):
    __tablename__ = "workflow_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shipment_id = Column(UUID(as_uuid=True), ForeignKey("shipments.id"), nullable=False)
    event_type = Column(String(100), nullable=False)
    stage = Column(String(50), nullable=False)
    payload_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    shipment = relationship("Shipment", back_populates="workflow_events")


async def init_db() -> None:
    """Create all tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Lightweight schema patching for existing dev databases (no migration framework yet).
        await conn.execute(
            text("ALTER TABLE shipments ADD COLUMN IF NOT EXISTS ready_at_timezone VARCHAR(64)")
        )
        await conn.execute(
            text("ALTER TABLE shipments ADD COLUMN IF NOT EXISTS ready_at_offset_minutes INTEGER")
        )
        await conn.execute(
            text("ALTER TABLE shipments ADD COLUMN IF NOT EXISTS ready_at_local TIMESTAMP WITHOUT TIME ZONE")
        )
        await conn.execute(
            text("ALTER TABLE shipments ADD COLUMN IF NOT EXISTS delivery_at TIMESTAMP WITH TIME ZONE")
        )
        await conn.execute(
            text("ALTER TABLE shipments ADD COLUMN IF NOT EXISTS delivery_at_local TIMESTAMP WITHOUT TIME ZONE")
        )
        await conn.execute(
            text("ALTER TABLE shipments ADD COLUMN IF NOT EXISTS delivery_at_timezone VARCHAR(64)")
        )
        await conn.execute(
            text("ALTER TABLE shipments ADD COLUMN IF NOT EXISTS delivery_at_offset_minutes INTEGER")
        )
        await conn.execute(
            text(
                """
                DO $$
                BEGIN
                  IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'shipments'
                      AND column_name = 'ready_at'
                      AND data_type = 'timestamp with time zone'
                  ) THEN
                    UPDATE shipments
                    SET ready_at_local = ready_at
                    WHERE ready_at IS NOT NULL
                      AND ready_at_local IS NULL;

                    ALTER TABLE shipments
                      ALTER COLUMN ready_at TYPE timestamp with time zone
                      USING (
                        CASE
                          WHEN ready_at IS NULL THEN NULL
                          WHEN ready_at_timezone IS NOT NULL
                            THEN (ready_at AT TIME ZONE ready_at_timezone)
                          ELSE NULL
                        END
                      );
                  ELSIF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'shipments'
                      AND column_name = 'ready_at'
                      AND data_type = 'timestamp with time zone'
                  ) THEN
                    UPDATE shipments
                    SET ready_at_local = (
                      CASE
                        WHEN ready_at_timezone IS NOT NULL THEN (ready_at AT TIME ZONE ready_at_timezone)
                        ELSE ready_at_local
                      END
                    )
                    WHERE ready_at IS NOT NULL
                      AND ready_at_local IS NULL;
                  END IF;
                END$$;
                """
            )
        )
        await conn.execute(
            text("ALTER TABLE shipments ADD COLUMN IF NOT EXISTS is_archived BOOLEAN DEFAULT FALSE NOT NULL")
        )
        await conn.execute(
            text("ALTER TABLE shipments ADD COLUMN IF NOT EXISTS archive_reason_code VARCHAR(50)")
        )
        await conn.execute(
            text("ALTER TABLE shipments ADD COLUMN IF NOT EXISTS archive_reason_note VARCHAR(500)")
        )
        await conn.execute(
            text("ALTER TABLE shipments ADD COLUMN IF NOT EXISTS archived_reason VARCHAR(500)")
        )
        await conn.execute(
            text("ALTER TABLE shipments ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP WITH TIME ZONE")
        )
        await conn.execute(
            text("ALTER TABLE email_threads ADD COLUMN IF NOT EXISTS shipment_ingest_suppressed BOOLEAN DEFAULT FALSE NOT NULL")
        )
        await conn.execute(
            text("ALTER TABLE email_threads ADD COLUMN IF NOT EXISTS shipment_ingest_suppressed_reason VARCHAR(500)")
        )
        await conn.execute(
            text("ALTER TABLE email_threads ADD COLUMN IF NOT EXISTS shipment_ingest_suppressed_at TIMESTAMP WITH TIME ZONE")
        )


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get a database session."""
    async with async_session() as session:
        yield session
