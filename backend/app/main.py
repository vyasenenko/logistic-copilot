"""AI Agent Backend — FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    # Startup: initialize DB, Qdrant, etc.
    from app.memory.database import init_db
    from app.memory.vector_store import init_vector_store

    await init_db()
    await init_vector_store()
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

app.include_router(health_router, tags=["health"])
app.include_router(chat_router, prefix="/api", tags=["chat"])
app.include_router(conversations_router, prefix="/api", tags=["conversations"])
app.include_router(freight_router, prefix="/api", tags=["freight"])
app.include_router(integrations_router, prefix="/api", tags=["integrations"])
app.include_router(upload_router, prefix="/api", tags=["upload"])
