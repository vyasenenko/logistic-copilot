"""AI Agent Backend — FastAPI application entry point."""

import asyncio
from contextlib import asynccontextmanager, suppress
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

logger = logging.getLogger(__name__)
_webhook_renewal_task: asyncio.Task | None = None


async def _ensure_outlook_webhook_subscription(reason: str) -> None:
    from app.services.outlook import OutlookGraphClient

    outlook = OutlookGraphClient()
    if not outlook.webhook_is_configured():
        logger.info(
            "Skipping Outlook webhook subscription bootstrap; webhook is not fully configured "
            "(public_base_url=%r mailbox=%r resource=%r).",
            settings.microsoft_webhook_public_base_url,
            settings.microsoft_mailbox,
            settings.microsoft_webhook_effective_resource,
        )
        return

    logger.info(
        "Ensuring Outlook webhook subscription (%s) "
        "(notification_url=%r resource=%r change_type=%r).",
        reason,
        settings.microsoft_webhook_notification_url,
        settings.microsoft_webhook_effective_resource,
        settings.microsoft_webhook_change_type,
    )
    try:
        subscription = await outlook.ensure_inbox_webhook_subscription()
        logger.info(
            "Outlook webhook subscription %s: id=%s expires=%s",
            subscription.get("subscriptionAction", "ensured"),
            subscription.get("id"),
            subscription.get("expirationDateTime"),
        )
    except Exception:
        logger.exception("Failed to ensure Outlook webhook subscription (%s).", reason)


async def _outlook_webhook_subscription_renewal_loop() -> None:
    """Ensure the Outlook webhook on startup, then keep it renewed periodically."""
    delay_seconds = max(0, settings.microsoft_webhook_startup_delay_seconds)
    if delay_seconds:
        logger.info("Outlook webhook bootstrap will run in %ss.", delay_seconds)
        await asyncio.sleep(delay_seconds)

    await _ensure_outlook_webhook_subscription("startup")

    interval_seconds = max(3600, settings.microsoft_webhook_renew_interval_seconds)
    while True:
        logger.info("Next Outlook webhook renewal check will run in %ss.", interval_seconds)
        await asyncio.sleep(interval_seconds)
        await _ensure_outlook_webhook_subscription("scheduled")


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

    logger.info("Startup step 3/3: scheduling Outlook webhook renewal task.")
    global _webhook_renewal_task
    _webhook_renewal_task = asyncio.create_task(
        _outlook_webhook_subscription_renewal_loop(),
        name="outlook-webhook-renewal",
    )
    logger.info("Startup sequence complete.")
    yield
    # Shutdown: cleanup
    if _webhook_renewal_task and not _webhook_renewal_task.done():
        _webhook_renewal_task.cancel()
        with suppress(asyncio.CancelledError):
            await _webhook_renewal_task


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
app.include_router(chat_router, prefix="/api", tags=["chat"])
app.include_router(audio_router, prefix="/api", tags=["audio"])
app.include_router(conversations_router, prefix="/api", tags=["conversations"])
app.include_router(freight_router, prefix="/api", tags=["freight"])
app.include_router(integrations_router, prefix="/api", tags=["integrations"])
app.include_router(tools_router, prefix="/api", tags=["tools"])
app.include_router(upload_router, prefix="/api", tags=["upload"])
