"""AI Agent Backend — FastAPI application entry point."""

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

logger = logging.getLogger(__name__)


async def _ensure_outlook_webhook_subscription_on_startup() -> None:
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
        "Ensuring Outlook webhook subscription on startup "
        "(notification_url=%r resource=%r change_type=%r).",
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
        logger.exception("Failed to ensure Outlook webhook subscription on startup.")


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

    logger.info("Startup step 3/3: ensuring Outlook webhook subscription (if configured).")
    await _ensure_outlook_webhook_subscription_on_startup()
    logger.info("Startup sequence complete.")
    yield
    # Shutdown: cleanup


app = FastAPI(
    title="AI Agent",
    version="0.1.0",
    description="Universal AI Agent API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Routes ---
from app.api.chat import router as chat_router  # noqa: E402
from app.api.conversations import router as conversations_router  # noqa: E402
from app.api.freight import router as freight_router  # noqa: E402
from app.api.health import router as health_router  # noqa: E402
from app.api.integrations import router as integrations_router  # noqa: E402
from app.api.upload import router as upload_router  # noqa: E402
from app.api.events_ws import router as events_ws_router  # noqa: E402

app.include_router(health_router, tags=["health"])
app.include_router(events_ws_router, tags=["events"])
app.include_router(chat_router, prefix="/api", tags=["chat"])
app.include_router(conversations_router, prefix="/api", tags=["conversations"])
app.include_router(freight_router, prefix="/api", tags=["freight"])
app.include_router(integrations_router, prefix="/api", tags=["integrations"])
app.include_router(upload_router, prefix="/api", tags=["upload"])
