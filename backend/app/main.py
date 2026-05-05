"""AI Agent Backend — FastAPI application entry point."""

import asyncio
from contextlib import asynccontextmanager, suppress
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

logger = logging.getLogger(__name__)
_webhook_renewal_task: asyncio.Task | None = None
_quote_window_task: asyncio.Task | None = None


async def _ensure_outlook_webhook_for_connection(reason: str, email_connection_id) -> None:
    """Create or renew Graph webhook subscription for one active mailbox connection."""
    from datetime import datetime, timedelta, timezone

    from app.memory.database import EmailConnection, async_session
    from app.services.outlook_organization import (
        apply_graph_subscription_to_email_connection,
        build_outlook_graph_client,
    )

    if not (settings.microsoft_webhook_public_base_url or "").strip():
        return

    async with async_session() as session:
        connection = await session.get(EmailConnection, email_connection_id)
        if connection is None or connection.status != "active":
            return
        if connection.subscription_expires_at:
            renew_before = datetime.now(timezone.utc) + timedelta(
                minutes=max(15, settings.microsoft_webhook_renewal_buffer_minutes)
            )
            if connection.subscription_expires_at > renew_before:
                return
        try:
            outlook = await build_outlook_graph_client(
                session,
                connection.organization_id,
                mailbox=connection.mailbox,
                email_connection_id=connection.id,
            )
        except RuntimeError:
            return
        if not outlook.webhook_is_configured():
            return
        logger.info("Ensuring Outlook webhook for mailbox %s (%s)", connection.mailbox, reason)
        try:
            subscription = await outlook.ensure_inbox_webhook_subscription()
            await apply_graph_subscription_to_email_connection(session, connection.id, subscription)
            await session.commit()
            logger.info(
                "Outlook webhook mailbox=%s %s: id=%s expires=%s",
                connection.mailbox,
                subscription.get("subscriptionAction", "ensured"),
                subscription.get("id"),
                subscription.get("expirationDateTime"),
            )
        except Exception:
            await session.rollback()
            logger.exception(
                "Failed to ensure Outlook webhook for mailbox connection %s (%s).", email_connection_id, reason
            )


async def _ensure_all_organization_outlook_webhooks(reason: str) -> None:
    from sqlalchemy import select

    from app.memory.database import EmailConnection, async_session

    if not (settings.microsoft_webhook_public_base_url or "").strip():
        logger.info(
            "Skipping Outlook webhook renewal (%s); microsoft_webhook_public_base_url is not set.", reason
        )
        return

    async with async_session() as session:
        result = await session.execute(
            select(EmailConnection.id).where(
                EmailConnection.provider == "outlook",
                EmailConnection.status == "active",
            )
        )
        connection_ids = [row[0] for row in result.all()]

    for connection_id in connection_ids:
        try:
            await _ensure_outlook_webhook_for_connection(reason, connection_id)
        except Exception:
            logger.exception("Outlook renewal iteration failed for email connection %s (%s)", connection_id, reason)


async def _outlook_webhook_subscription_renewal_loop() -> None:
    """Ensure Outlook webhooks per organization on startup, then renew periodically."""
    delay_seconds = max(0, settings.microsoft_webhook_startup_delay_seconds)
    if delay_seconds:
        logger.info("Outlook webhook bootstrap will run in %ss.", delay_seconds)
        await asyncio.sleep(delay_seconds)

    await _ensure_all_organization_outlook_webhooks("startup")

    interval_seconds = max(3600, settings.microsoft_webhook_renew_interval_seconds)
    while True:
        logger.info("Next Outlook webhook renewal check will run in %ss.", interval_seconds)
        await asyncio.sleep(interval_seconds)
        await _ensure_all_organization_outlook_webhooks("scheduled")


async def _quote_window_evaluation_loop() -> None:
    """Periodically close expired bid windows and send customer quotes."""
    from app.memory.database import async_session
    from app.services.freight_inbox_agent import evaluate_expired_quote_windows

    interval_seconds = max(1, settings.quote_window_check_interval_seconds)
    while True:
        try:
            async with async_session() as session:
                decisions = await evaluate_expired_quote_windows(session, system_scope=True)
            if decisions:
                logger.info("Quote window scheduler processed %d shipment(s).", len(decisions))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Quote window scheduler failed.")
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    # Startup: initialize DB, Qdrant, etc.
    from app.memory.database import init_db
    from app.memory.vector_store import init_vector_store

    logger.info("Startup step 1/3: initializing PostgreSQL schema.")
    await init_db()
    logger.info("Startup step 1/3 complete.")

    logger.info("Startup step 2/3: initializing Qdrant vector store.")
    await init_vector_store()
    logger.info("Startup step 2/3 complete.")

    logger.info("Startup step 3/3: scheduling Outlook webhook renewal and quote window tasks.")
    global _webhook_renewal_task, _quote_window_task
    _webhook_renewal_task = asyncio.create_task(
        _outlook_webhook_subscription_renewal_loop(),
        name="outlook-webhook-renewal",
    )
    _quote_window_task = asyncio.create_task(
        _quote_window_evaluation_loop(),
        name="quote-window-evaluation",
    )
    logger.info("Startup sequence complete.")
    yield
    # Shutdown: cleanup
    if _webhook_renewal_task and not _webhook_renewal_task.done():
        _webhook_renewal_task.cancel()
        with suppress(asyncio.CancelledError):
            await _webhook_renewal_task
    if _quote_window_task and not _quote_window_task.done():
        _quote_window_task.cancel()
        with suppress(asyncio.CancelledError):
            await _quote_window_task


app = FastAPI(
    title="AI Agent",
    version="0.1.0",
    description="Universal AI Agent API",
    lifespan=lifespan,
)

_cors_kw: dict = {
    "allow_origins": settings.cors_origins,
    "allow_credentials": True,
    "allow_methods": ["*"],
    "allow_headers": ["*"],
}
if settings.cors_allow_chrome_extensions:
    _cors_kw["allow_origin_regex"] = r"chrome-extension://.*"

app.add_middleware(CORSMiddleware, **_cors_kw)

# --- Routes ---
from app.api.auth import router as auth_router  # noqa: E402
from app.api.chat import router as chat_router  # noqa: E402
from app.api.conversations import router as conversations_router  # noqa: E402
from app.api.audio import router as audio_router  # noqa: E402
from app.api.freight import router as freight_router  # noqa: E402
from app.api.health import router as health_router  # noqa: E402
from app.api.integrations import router as integrations_router  # noqa: E402
from app.api.tools import router as tools_router  # noqa: E402
from app.api.upload import router as upload_router  # noqa: E402
from app.api.events_ws import router as events_ws_router  # noqa: E402

app.include_router(health_router, tags=["health"])
app.include_router(events_ws_router, tags=["events"])
app.include_router(auth_router, prefix="/api", tags=["auth"])
app.include_router(chat_router, prefix="/api", tags=["chat"])
app.include_router(audio_router, prefix="/api", tags=["audio"])
app.include_router(conversations_router, prefix="/api", tags=["conversations"])
app.include_router(freight_router, prefix="/api", tags=["freight"])
app.include_router(integrations_router, prefix="/api", tags=["integrations"])
app.include_router(tools_router, prefix="/api", tags=["tools"])
app.include_router(upload_router, prefix="/api", tags=["upload"])
