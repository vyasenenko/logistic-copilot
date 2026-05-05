"""Audio API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.services.audio_transcription import transcribe_audio_bytes
from app.services.auth import CurrentUserContext, get_current_user_context

router = APIRouter()

ALLOWED_AUDIO_TYPES = {
    "audio/webm",
    "audio/wav",
    "audio/x-wav",
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/ogg",
    "audio/ogg; codecs=opus",
}
MAX_AUDIO_BYTES = 25 * 1024 * 1024


@router.post("/audio/transcriptions")
async def transcribe_audio(
    file: UploadFile = File(...),
    language: str | None = Form(default=None),
    prompt: str | None = Form(default=None),
    context: CurrentUserContext = Depends(get_current_user_context),
):
    """Transcribe user audio into plain text."""
    _ = context
    content_type = (file.content_type or "").lower().strip()
    if content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio type: {file.content_type or 'unknown'}.",
        )
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded audio file is empty.")
    if len(content) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=400, detail="Audio file is too large. Max 25 MB.")
    text = await transcribe_audio_bytes(
        content_bytes=content,
        filename=file.filename or "voice-note.webm",
        content_type=content_type,
        language=(language or "").strip() or None,
        prompt=(prompt or "").strip() or None,
    )
    return {"text": text}
