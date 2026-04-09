"""Integration readiness endpoints for Outlook-first workflow setup."""

from fastapi import APIRouter

from app.config import settings
from app.schemas import IntegrationStatus, IntegrationsStatusResponse
from app.services.outlook import OutlookGraphClient
from app.services.tms_connector import TmsConnector

router = APIRouter()


@router.get("/integrations/status", response_model=IntegrationsStatusResponse)
async def integrations_status() -> IntegrationsStatusResponse:
    """Return current integration readiness for email and TMS connectors."""
    outlook = OutlookGraphClient()
    tms = TmsConnector()

    email_status = await outlook.health_check()
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