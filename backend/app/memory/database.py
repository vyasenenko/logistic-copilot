"""PostgreSQL database — conversations and message history."""

import hashlib
import secrets
import ssl
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship

from app.config import settings


def _hash_bootstrap_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 240_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def _domain_from_email(email: str) -> str:
    return email.split("@", 1)[1].strip().lower() if "@" in email else ""


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
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    title = Column(String(500), default="New conversation")
    metadata_json = Column(JSON, default=dict, nullable=False)
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


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(320), nullable=False)
    name = Column(String(255), nullable=True)
    status = Column(String(50), default="active", nullable=False)
    email_verified_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    primary_domain = Column(String(255), nullable=True)
    status = Column(String(50), default="active", nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class OrganizationMember(Base):
    __tablename__ = "organization_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    role = Column(String(50), default="member", nullable=False)
    status = Column(String(50), default="active", nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AccessRequest(Base):
    __tablename__ = "access_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(320), nullable=False)
    company_name = Column(String(255), nullable=False)
    domain = Column(String(255), nullable=True)
    status = Column(String(50), default="pending", nullable=False)
    review_notes = Column(Text, nullable=True)
    payload_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Invite(Base):
    __tablename__ = "invites"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    email = Column(String(320), nullable=False)
    role = Column(String(50), default="member", nullable=False)
    token_hash = Column(String(128), nullable=False, unique=True)
    status = Column(String(50), default="pending", nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    token_hash = Column(String(128), nullable=False, unique=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    ip_address = Column(String(100), nullable=True)
    user_agent = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ExtensionAuthCode(Base):
    __tablename__ = "extension_auth_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    code_hash = Column(String(128), nullable=False, unique=True)
    state = Column(String(500), nullable=False)
    redirect_uri = Column(String(1000), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AuthMethod(Base):
    __tablename__ = "auth_methods"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    method_type = Column(String(50), nullable=False)
    secret_hash = Column(String(500), nullable=True)
    metadata_json = Column(JSON, default=dict, nullable=False)
    enabled_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class EmailConnection(Base):
    __tablename__ = "email_connections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    provider = Column(String(50), default="outlook", nullable=False)
    mailbox = Column(String(320), nullable=False)
    status = Column(String(50), default="active", nullable=False)
    visibility_mode = Column(String(50), default="private", nullable=False)
    graph_subscription_id = Column(String(128), nullable=True)
    subscription_expires_at = Column(DateTime(timezone=True), nullable=True)
    metadata_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class OrganizationOutlookCredentials(Base):
    """Per-organization Microsoft Graph app registration and mailbox (secrets encrypted at rest)."""

    __tablename__ = "organization_outlook_credentials"

    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), primary_key=True)
    tenant_id = Column(String(128), nullable=True)
    client_id = Column(String(128), nullable=True)
    client_secret_encrypted = Column(Text, nullable=True)
    mailbox = Column(String(320), nullable=True)
    graph_subscription_id = Column(String(128), nullable=True)
    subscription_expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class OrganizationTmsIntegration(Base):
    """Per-organization generic TMS integration boundary."""

    __tablename__ = "organization_tms_integrations"

    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), primary_key=True)
    tms_system = Column(String(100), default="generic", nullable=False)
    base_url = Column(String(500), nullable=True)
    api_key_encrypted = Column(Text, nullable=True)
    inbound_token_hash = Column(String(128), nullable=True, unique=True)
    status = Column(String(50), default="inactive", nullable=False)
    metadata_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    event_type = Column(String(100), nullable=False)
    actor = Column(String(255), nullable=True)
    ip_address = Column(String(100), nullable=True)
    user_agent = Column(String(500), nullable=True)
    payload_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Client(Base):
    __tablename__ = "clients"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True)
    name = Column(String(255), nullable=False)
    email = Column(String(320), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    default_margin_percent = Column(Float, default=0, nullable=False)
    default_margin_floor = Column(Float, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    shipments = relationship("Shipment", back_populates="client")


class Carrier(Base):
    __tablename__ = "carriers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True)
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


class FraudDenylistEntry(Base):
    __tablename__ = "fraud_denylist_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True)
    scope = Column(String(50), nullable=False)
    value = Column(String(320), nullable=False)
    reason = Column(String(500), nullable=True)
    source_shipment_id = Column(UUID(as_uuid=True), ForeignKey("shipments.id"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class EmailThread(Base):
    __tablename__ = "email_threads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True)
    provider = Column(String(50), default="outlook", nullable=False)
    mailbox = Column(String(320), nullable=False)
    provider_thread_id = Column(String(255), nullable=True)
    quote_token = Column(String(32), nullable=True)
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
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True)
    thread_id = Column(UUID(as_uuid=True), ForeignKey("email_threads.id"), nullable=False)
    provider_message_id = Column(String(255), nullable=True)
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


class EmailTriageItem(Base):
    __tablename__ = "email_triage_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True)
    email_message_id = Column(UUID(as_uuid=True), ForeignKey("email_messages.id"), nullable=False)
    thread_id = Column(UUID(as_uuid=True), ForeignKey("email_threads.id"), nullable=False)
    classification = Column(String(50), nullable=False)
    confidence = Column(Float, default=0, nullable=False)
    reason = Column(String(500), nullable=True)
    recommended_action = Column(String(100), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_action = Column(String(100), nullable=True)
    created_shipment_id = Column(UUID(as_uuid=True), ForeignKey("shipments.id"), nullable=True)
    payload_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Shipment(Base):
    __tablename__ = "shipments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=True)
    email_thread_id = Column(UUID(as_uuid=True), ForeignKey("email_threads.id"), nullable=True)
    status = Column(String(50), nullable=False, default="received")
    quote_token = Column(String(32), nullable=True)
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
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True)
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
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True)
    shipment_id = Column(UUID(as_uuid=True), ForeignKey("shipments.id"), nullable=False)
    event_type = Column(String(100), nullable=False)
    stage = Column(String(50), nullable=False)
    payload_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    shipment = relationship("Shipment", back_populates="workflow_events")


async def init_db() -> None:
    """Create all tables."""
    legacy_default_org_id = uuid.UUID("00000000-0000-4000-8000-000000000001")
    bootstrap_owner_email = settings.bootstrap_owner_email.strip().lower()
    bootstrap_org_domain = (
        settings.bootstrap_organization_domain.strip().lower()
        or _domain_from_email(bootstrap_owner_email)
    )
    bootstrap_org_name = settings.bootstrap_organization_name.strip() or bootstrap_org_domain or "Logistic Copilot"
    bootstrap_owner_name = settings.bootstrap_owner_name.strip() or None
    bootstrap_mailbox = (
        settings.bootstrap_outlook_mailbox.strip().lower()
        or bootstrap_owner_email
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Lightweight schema patching for existing dev databases (no migration framework yet).
        await conn.execute(
            text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS metadata_json JSON DEFAULT '{}'::json NOT NULL")
        )
        await conn.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id)"))
        await conn.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id)"))
        await conn.execute(text("ALTER TABLE email_connections ADD COLUMN IF NOT EXISTS graph_subscription_id VARCHAR(128)"))
        await conn.execute(text("ALTER TABLE email_connections ADD COLUMN IF NOT EXISTS subscription_expires_at TIMESTAMPTZ"))
        await conn.execute(text("ALTER TABLE email_connections ADD COLUMN IF NOT EXISTS visibility_mode VARCHAR(50) DEFAULT 'private' NOT NULL"))
        await conn.execute(text("ALTER TABLE organization_tms_integrations ADD COLUMN IF NOT EXISTS metadata_json JSON DEFAULT '{}'::json NOT NULL"))
        await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique ON users(email)"))
        await conn.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS idx_organizations_primary_domain_unique ON organizations(primary_domain)")
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_organization_members_user_org_unique "
                "ON organization_members(user_id, organization_id)"
            )
        )
        await conn.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS idx_organization_members_user_unique ON organization_members(user_id)")
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_auth_methods_user_method_unique "
                "ON auth_methods(user_id, method_type)"
            )
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_email_connections_org_provider_mailbox_unique "
                "ON email_connections(organization_id, provider, mailbox)"
            )
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_email_connections_user_provider_mailbox_unique "
                "ON email_connections(user_id, provider, mailbox)"
            )
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_org_outlook_mailbox_lower "
                "ON organization_outlook_credentials (LOWER(mailbox)) "
                "WHERE mailbox IS NOT NULL AND BTRIM(mailbox) <> ''"
            )
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_extension_auth_codes_code_hash_unique "
                "ON extension_auth_codes(code_hash)"
            )
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_org_tms_inbound_token_hash_unique "
                "ON organization_tms_integrations(inbound_token_hash) "
                "WHERE inbound_token_hash IS NOT NULL"
            )
        )
        bootstrap_org_id = None
        bootstrap_user_id = None
        if bootstrap_owner_email and bootstrap_org_domain:
            bootstrap_row = await conn.execute(
                text(
                    """
                    WITH upsert_org AS (
                        INSERT INTO organizations (id, name, primary_domain, status, created_at, updated_at)
                        VALUES (:new_organization_id, :organization_name, :organization_domain, 'active', now(), now())
                        ON CONFLICT (primary_domain) DO UPDATE
                        SET name = EXCLUDED.name,
                            status = 'active',
                            updated_at = now()
                        RETURNING id
                    ),
                    org_row AS (
                        SELECT id FROM upsert_org
                        UNION
                        SELECT id FROM organizations WHERE primary_domain = :organization_domain
                        LIMIT 1
                    ),
                    upsert_user AS (
                        INSERT INTO users (id, email, name, status, email_verified_at, created_at, updated_at)
                        VALUES (:new_user_id, :owner_email, :owner_name, 'active', now(), now(), now())
                        ON CONFLICT (email) DO UPDATE
                        SET name = COALESCE(EXCLUDED.name, users.name),
                            status = 'active',
                            email_verified_at = COALESCE(users.email_verified_at, now()),
                            updated_at = now()
                        RETURNING id
                    ),
                    user_row AS (
                        SELECT id FROM upsert_user
                        UNION
                        SELECT id FROM users WHERE email = :owner_email
                        LIMIT 1
                    ),
                    member_row AS (
                        INSERT INTO organization_members (id, user_id, organization_id, role, status, created_at, updated_at)
                        SELECT :new_member_id, user_row.id, org_row.id, 'owner', 'active', now(), now()
                        FROM user_row, org_row
                        ON CONFLICT (user_id, organization_id) DO UPDATE
                        SET role = 'owner',
                            status = 'active',
                            updated_at = now()
                        RETURNING organization_id, user_id
                    )
                    SELECT organization_id, user_id FROM member_row
                    """
                ),
                {
                    "new_organization_id": uuid.uuid4(),
                    "new_user_id": uuid.uuid4(),
                    "new_member_id": uuid.uuid4(),
                    "organization_name": bootstrap_org_name,
                    "organization_domain": bootstrap_org_domain,
                    "owner_email": bootstrap_owner_email,
                    "owner_name": bootstrap_owner_name,
                },
            )
            bootstrap_ids = bootstrap_row.first()
            if bootstrap_ids:
                bootstrap_org_id = bootstrap_ids.organization_id
                bootstrap_user_id = bootstrap_ids.user_id

            if bootstrap_org_id and bootstrap_user_id and bootstrap_mailbox:
                await conn.execute(
                    text(
                        """
                        INSERT INTO email_connections (
                            id, user_id, organization_id, provider, mailbox, status, metadata_json, created_at, updated_at
                        )
                        VALUES (
                            :new_connection_id, :user_id, :organization_id, 'outlook', :mailbox, 'active',
                            '{"source":"bootstrap"}'::json, now(), now()
                        )
                        ON CONFLICT (organization_id, provider, mailbox) DO UPDATE
                        SET user_id = EXCLUDED.user_id,
                            status = 'active',
                            updated_at = now()
                        """
                    ),
                    {
                        "new_connection_id": uuid.uuid4(),
                        "user_id": bootstrap_user_id,
                        "organization_id": bootstrap_org_id,
                        "mailbox": bootstrap_mailbox,
                    },
                )

            if bootstrap_user_id and settings.bootstrap_owner_password:
                await conn.execute(
                    text(
                        """
                        INSERT INTO auth_methods (
                            id, user_id, method_type, secret_hash, metadata_json, enabled_at, created_at, updated_at
                        )
                        VALUES (
                            :new_auth_method_id, :user_id, 'password', :password_hash, '{}'::json, now(), now(), now()
                        )
                        ON CONFLICT (user_id, method_type) DO UPDATE
                        SET secret_hash = EXCLUDED.secret_hash,
                            enabled_at = COALESCE(auth_methods.enabled_at, now()),
                            updated_at = now()
                        """
                    ),
                    {
                        "new_auth_method_id": uuid.uuid4(),
                        "user_id": bootstrap_user_id,
                        "password_hash": _hash_bootstrap_password(settings.bootstrap_owner_password),
                    },
                )
        for table_name in [
            "conversations",
            "clients",
            "carriers",
            "fraud_denylist_entries",
            "email_threads",
            "email_messages",
            "email_triage_items",
            "shipments",
            "carrier_bids",
            "workflow_events",
        ]:
            await conn.execute(
                text(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id)")
            )
            await conn.execute(
                text(
                    f"""
                    UPDATE {table_name}
                    SET organization_id = :organization_id
                    WHERE organization_id IS NULL OR organization_id = :legacy_default_org_id
                    """
                ),
                {
                    "organization_id": bootstrap_org_id,
                    "legacy_default_org_id": legacy_default_org_id,
                },
            )
            await conn.execute(
                text(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_organization_id ON {table_name}(organization_id)")
            )
        for constraint_name, table_name in [
            ("clients_email_key", "clients"),
            ("carriers_email_key", "carriers"),
            ("email_threads_provider_thread_id_key", "email_threads"),
            ("email_threads_quote_token_key", "email_threads"),
            ("email_messages_provider_message_id_key", "email_messages"),
            ("shipments_quote_token_key", "shipments"),
        ]:
            await conn.execute(text(f"ALTER TABLE {table_name} DROP CONSTRAINT IF EXISTS {constraint_name}"))
        await conn.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS idx_clients_org_email_unique ON clients(organization_id, email)")
        )
        await conn.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS idx_carriers_org_email_unique ON carriers(organization_id, email)")
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_email_threads_org_provider_mailbox_thread_unique "
                "ON email_threads(organization_id, provider, mailbox, provider_thread_id) "
                "WHERE provider_thread_id IS NOT NULL"
            )
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_email_threads_org_quote_token_unique "
                "ON email_threads(organization_id, quote_token) WHERE quote_token IS NOT NULL"
            )
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_email_messages_org_provider_message_unique "
                "ON email_messages(organization_id, provider_message_id) WHERE provider_message_id IS NOT NULL"
            )
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_shipments_org_quote_token_unique "
                "ON shipments(organization_id, quote_token) WHERE quote_token IS NOT NULL"
            )
        )
        if bootstrap_org_id:
            await conn.execute(
                text("DELETE FROM organizations WHERE id = :legacy_default_org_id"),
                {"legacy_default_org_id": legacy_default_org_id},
            )
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
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS fraud_denylist_entries (
                    id UUID PRIMARY KEY,
                    organization_id UUID REFERENCES organizations(id),
                    scope VARCHAR(50) NOT NULL,
                    value VARCHAR(320) NOT NULL,
                    reason VARCHAR(500),
                    source_shipment_id UUID REFERENCES shipments(id),
                    is_active BOOLEAN DEFAULT TRUE NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
                """
            )
        )
        await conn.execute(
            text("ALTER TABLE fraud_denylist_entries ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()")
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_fraud_denylist_scope_value_active "
                "ON fraud_denylist_entries(scope, value, is_active)"
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS email_triage_items (
                    id UUID PRIMARY KEY,
                    organization_id UUID REFERENCES organizations(id),
                    email_message_id UUID NOT NULL REFERENCES email_messages(id),
                    thread_id UUID NOT NULL REFERENCES email_threads(id),
                    classification VARCHAR(50) NOT NULL,
                    confidence DOUBLE PRECISION DEFAULT 0 NOT NULL,
                    reason VARCHAR(500),
                    recommended_action VARCHAR(100),
                    resolved_at TIMESTAMP WITH TIME ZONE,
                    resolved_action VARCHAR(100),
                    created_shipment_id UUID REFERENCES shipments(id),
                    payload_json JSON DEFAULT '{}'::json NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
                """
            )
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS idx_email_triage_classification ON email_triage_items(classification)")
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS idx_email_triage_resolved_at ON email_triage_items(resolved_at)")
        )


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get a database session."""
    async with async_session() as session:
        yield session
