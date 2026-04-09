"""ElevenLabs text-to-speech integration."""

import httpx

from app.config import settings

ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"


async def generate_speech(
    text: str,
    voice_id: str | None = None,
    model_id: str = "eleven_multilingual_v2",
    stability: float = 0.5,
    similarity_boost: float = 0.75,
) -> bytes:
    """Generate speech audio from text using ElevenLabs.

    Args:
        text: The text to convert to speech.
        voice_id: ElevenLabs voice ID. Falls back to default from settings.
        model_id: ElevenLabs model to use.
        stability: Voice stability (0.0-1.0).
        similarity_boost: Voice similarity boost (0.0-1.0).

    Returns:
        MP3 audio bytes.
    """
    vid = voice_id or settings.elevenlabs_default_voice_id
    if not vid:
        raise ValueError("No voice_id provided and no default configured.")

    if not settings.elevenlabs_api_key:
        raise ValueError("ELEVENLABS_API_KEY not configured.")

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{ELEVENLABS_BASE}/text-to-speech/{vid}",
            headers={
                "xi-api-key": settings.elevenlabs_api_key,
                "Content-Type": "application/json",
            },
            json={
                "text": text,
                "model_id": model_id,
                "voice_settings": {
                    "stability": stability,
                    "similarity_boost": similarity_boost,
                },
            },
        )
        response.raise_for_status()
        return response.content


async def list_voices() -> list[dict]:
    """List available voices from ElevenLabs."""
    if not settings.elevenlabs_api_key:
        return []

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{ELEVENLABS_BASE}/voices",
            headers={"xi-api-key": settings.elevenlabs_api_key},
        )
        response.raise_for_status()
        data = response.json()

    return [
        {
            "voice_id": v["voice_id"],
            "name": v["name"],
            "category": v.get("category", ""),
            "preview_url": v.get("preview_url", ""),
        }
        for v in data.get("voices", [])
    ]
