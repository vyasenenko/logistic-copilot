"""TMS connector foundation for booking handoff and shipment sync."""

from __future__ import annotations

import asyncio

import httpx

from app.config import settings
from app.memory.database import OrganizationTmsIntegration
from app.services.integration_crypto import decrypt_integration_secret


class TmsConnector:
    """Thin TMS HTTP wrapper.

    The connector stays deterministic and explicit. Agent tools may call into it,
    but payload mapping and retries should remain here.
    """

    required_settings = (
        "tms_base_url",
        "tms_api_key",
    )

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        tms_system: str = "generic",
        source: str = "env_fallback",
    ) -> None:
        self.base_url = (base_url if base_url is not None else settings.tms_base_url).rstrip("/") if (base_url if base_url is not None else settings.tms_base_url) else ""
        self.api_key = api_key if api_key is not None else settings.tms_api_key
        self.tms_system = tms_system
        self.source = source

    def missing_settings(self) -> list[str]:
        missing = []
        if not self.base_url:
            missing.append("tms_base_url")
        if not self.api_key:
            missing.append("tms_api_key")
        return missing

    def is_configured(self) -> bool:
        return not self.missing_settings()

    async def health_check(self) -> dict:
        """Return configuration-aware health details for the TMS integration."""
        missing = self.missing_settings()
        details = {
            "base_url": self.base_url or None,
            "timeout_seconds": settings.tms_timeout_seconds,
            "tms_system": self.tms_system,
            "source": self.source,
        }

        if missing:
            return {
                "configured": False,
                "status": "missing_configuration",
                "missing_fields": missing,
                "details": details,
            }

        return {
            "configured": True,
            "status": "configured",
            "missing_fields": [],
            "details": details,
        }

    async def request(
        self,
        method: str,
        path: str,
        json: dict | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> dict:
        """Make an authenticated request to the TMS API."""
        missing = self.missing_settings()
        if missing:
            raise RuntimeError("TMS is not configured. Missing: " + ", ".join(missing))

        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["X-Idempotency-Key"] = idempotency_key

        attempts = max(settings.tms_retry_attempts + 1, 1)
        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=settings.tms_timeout_seconds) as client:
            for attempt in range(1, attempts + 1):
                try:
                    response = await client.request(method.upper(), url, headers=headers, json=json)
                    response.raise_for_status()
                    if not response.content:
                        return {}
                    return response.json()
                except (httpx.TimeoutException, httpx.HTTPError) as exc:
                    last_error = exc
                    if attempt >= attempts:
                        break
                    await asyncio.sleep(min(attempt, 2))
        raise RuntimeError(f"TMS request failed after {attempts} attempt(s): {last_error}")

    async def fetch_shipment_status(self, shipment_key: str) -> dict:
        """Fetch the latest shipment status from the TMS."""
        try:
            return await self.request("GET", f"/loads/{shipment_key}/status")
        except RuntimeError:
            # Local fallback so Phase 3 can work before a real TMS status API is wired.
            return {
                "shipment_key": shipment_key,
                "status": "in_transit",
                "eta": "Tomorrow by 10:00 AM",
                "location": "Columbus, OH",
                "milestone": "linehaul_in_progress",
                "source": "fallback_mock",
            }

    async def push_shipment_update(
        self,
        shipment_key: str,
        *,
        status_text: str | None,
        eta_text: str | None,
        location_text: str | None,
        notes: str | None,
    ) -> dict:
        """Push a carrier status update into the TMS."""
        payload = {
            "shipment_key": shipment_key,
            "status_text": status_text,
            "eta_text": eta_text,
            "location_text": location_text,
            "notes": notes,
        }
        try:
            response = await self.request(
                "POST",
                f"/loads/{shipment_key}/updates",
                json=payload,
                idempotency_key=f"status-update:{shipment_key}:{status_text or 'none'}:{eta_text or 'none'}:{location_text or 'none'}",
            )
            return {"status": "submitted", "response": response, "payload": payload}
        except RuntimeError:
            return {"status": "accepted_mock", "response": {"source": "fallback_mock"}, "payload": payload}


async def build_tms_connector(session, organization_id) -> TmsConnector:
    """Build the TMS connector from the organization's integration row, with env fallback for dev."""
    integration = await session.get(OrganizationTmsIntegration, organization_id)
    if integration and integration.status == "active":
        api_key = None
        if integration.api_key_encrypted:
            api_key = decrypt_integration_secret(integration.api_key_encrypted)
        return TmsConnector(
            base_url=integration.base_url,
            api_key=api_key,
            tms_system=integration.tms_system or "generic",
            source="organization",
        )
    return TmsConnector()
