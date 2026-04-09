"""TMS connector foundation for booking handoff and shipment sync."""

from __future__ import annotations

import httpx

from app.config import settings


class TmsConnector:
    """Thin TMS HTTP wrapper.

    The connector stays deterministic and explicit. Agent tools may call into it,
    but payload mapping and retries should remain here.
    """

    required_settings = (
        "tms_base_url",
        "tms_api_key",
    )

    def __init__(self) -> None:
        self.base_url = settings.tms_base_url.rstrip("/") if settings.tms_base_url else ""

    def missing_settings(self) -> list[str]:
        missing = []
        for field_name in self.required_settings:
            if not getattr(settings, field_name):
                missing.append(field_name)
        return missing

    def is_configured(self) -> bool:
        return not self.missing_settings()

    async def health_check(self) -> dict:
        """Return configuration-aware health details for the TMS integration."""
        missing = self.missing_settings()
        details = {
            "base_url": self.base_url or None,
            "timeout_seconds": settings.tms_timeout_seconds,
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

    async def request(self, method: str, path: str, json: dict | None = None) -> dict:
        """Make an authenticated request to the TMS API."""
        missing = self.missing_settings()
        if missing:
            raise RuntimeError("TMS is not configured. Missing: " + ", ".join(missing))

        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {settings.tms_api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=settings.tms_timeout_seconds) as client:
            response = await client.request(method.upper(), url, headers=headers, json=json)
            response.raise_for_status()
            if not response.content:
                return {}
            return response.json()
