"""OpenAI audio transcription helper service."""

from __future__ import annotations

import json

import httpx
from fastapi import HTTPException

from app.config import settings

TRANSCRIPTION_MODEL = "whisper-1"
TRANSCRIPTION_TIMEOUT_SECONDS = 60


async def transcribe_audio_bytes(
    *,
    content_bytes: bytes,
    filename: str,
    content_type: str,
    language: str | None = None,
    prompt: str | None = None,
) -> str:
    """Transcribe audio bytes with OpenAI audio transcriptions API."""
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OpenAI API key is not configured on the backend.")
    files = {
        "file": (filename, content_bytes, content_type or "application/octet-stream"),
    }
    data: dict[str, str] = {
        "model": TRANSCRIPTION_MODEL,
        "response_format": "json",
    }
    if language:
        data["language"] = language
    if prompt:
        data["prompt"] = prompt
    try:
        async with httpx.AsyncClient(timeout=TRANSCRIPTION_TIMEOUT_SECONDS) as client:
            response = await client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                data=data,
                files=files,
            )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = _extract_error_message(exc.response)
        raise HTTPException(status_code=exc.response.status_code, detail=detail) from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Transcription request timed out.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Transcription request failed: {exc}") from exc
    payload = response.json()
    text = payload.get("text")
    if not isinstance(text, str):
        raise HTTPException(status_code=502, detail="Transcription provider returned an invalid payload.")
    return text.strip()


def _extract_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        body = response.text.strip()
        return body or "OpenAI transcription request failed."
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
    return "OpenAI transcription request failed."
