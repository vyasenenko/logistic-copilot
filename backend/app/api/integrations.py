"""Integration readiness endpoints for Outlook-first workflow setup."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.memory.database import get_session
from app.schemas import IntegrationStatus, IntegrationsStatusResponse
from app.services.auth import CurrentUserContext, get_current_user_context
from app.services.outlook_organization import build_outlook_graph_client
from app.services.tms_connector import TmsConnector

router = APIRouter()


@router.get("/integrations/status", response_model=IntegrationsStatusResponse)
async def integrations_status(
    session: AsyncSession = Depends(get_session),
    context: CurrentUserContext = Depends(get_current_user_context),
) -> IntegrationsStatusResponse:
    """Return current integration readiness for email and TMS connectors."""
    try:
        outlook = await build_outlook_graph_client(
            session,
            context.organization_id,
            mailbox=context.email.strip().lower(),
        )
        email_status = await outlook.health_check()
    except RuntimeError:
        email_status = {
            "configured": False,
            "status": "missing_configuration",
            "missing_fields": ["tenant_id", "client_id", "client_secret", "mailbox"],
            "details": {},
        }
    tms = TmsConnector()
    tms_status = await tms.health_check()

    return IntegrationsStatusResponse(
        email=IntegrationStatus(name="outlook", **email_status),
        tms=IntegrationStatus(name="tms", **tms_status),
        defaults={
            "quote_wait_minutes_default": settings.quote_wait_minutes_default,
            "profit_margin_percent_default": settings.profit_margin_percent_default,
            "profit_margin_floor_default": settings.profit_margin_floor_default,
        },
    )
