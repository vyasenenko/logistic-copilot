"""Visual OCR helpers for image-heavy logistics documents."""

from __future__ import annotations

import base64

import httpx

from app.config import settings
from app.schemas import DocumentContentResult


OCR_PROMPT = (
    "Extract visible text from this logistics document. Preserve important labels, numbers, and line breaks. "
    "Focus on rate confirmations, BOLs, pickup numbers, references, dates, and totals. "
    "If the document is unreadable, respond with only UNREADABLE."
)


def _ocr_provider_order() -> list[str]:
    ordered = [provider.strip().lower() for provider in settings.document_ocr_provider_order.split(",")]
    return [provider for provider in ordered if provider in {"openai", "anthropic"}]


async def extract_document_content(
    *,
    content_bytes: bytes | None,
    content_type: str | None,
    filename: str | None,
) -> DocumentContentResult:
    """Extract text from attachment bytes using the best available path."""
    if not content_bytes:
        return DocumentContentResult(
            extraction_method="missing_binary",
            ocr_status="ocr_review_required",
            review_required=True,
            review_reason="Attachment binary content is missing.",
        )

    content_type = (content_type or "").lower()
    is_image = any(token in content_type for token in ("image/png", "image/jpeg", "image/jpg", "image/webp"))
    is_pdf = "application/pdf" in content_type
    if not (is_image or is_pdf):
        return DocumentContentResult(
            extraction_method="unsupported_visual_type",
            ocr_status="ocr_review_required",
            review_required=True,
            review_reason=f"Visual OCR is not configured for {content_type or filename or 'unknown document type'}.",
        )

    last_error: str | None = None
    for provider in _ocr_provider_order():
        try:
            if provider == "openai" and settings.openai_api_key and is_image:
                return await _extract_with_openai(content_bytes=content_bytes, content_type=content_type)
            if provider == "anthropic" and settings.anthropic_api_key:
                return await _extract_with_anthropic(
                    content_bytes=content_bytes,
                    content_type=content_type,
                )
        except Exception as exc:
            last_error = str(exc)

    return DocumentContentResult(
        extraction_method="visual_ocr_unavailable",
        ocr_status="ocr_review_required",
        review_required=True,
        review_reason=last_error or "No OCR-capable provider is configured for visual extraction.",
    )


async def _extract_with_openai(*, content_bytes: bytes, content_type: str) -> DocumentContentResult:
    payload = {
        "model": settings.effective_openai_model,
        "temperature": 0,
        "max_tokens": min(settings.llm_fallback_max_tokens, 2000),
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": OCR_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{content_type};base64,{base64.b64encode(content_bytes).decode('utf-8')}"
                        },
                    },
                ],
            }
        ],
    }
    async with httpx.AsyncClient(timeout=settings.document_ocr_timeout_seconds) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
    raw_text = (
        (((data.get("choices") or [{}])[0].get("message") or {}).get("content"))
        or ""
    ).strip()
    if raw_text.upper() == "UNREADABLE" or not raw_text:
        return DocumentContentResult(
            extraction_method="openai_vision",
            ocr_status="ocr_failed",
            ocr_confidence=0.2,
            review_required=True,
            review_reason="Visual OCR could not confidently read the attachment.",
        )
    confidence = 0.84 if len(raw_text) > 40 else 0.62
    return DocumentContentResult(
        raw_text=raw_text[:8000],
        raw_text_preview=raw_text[:280],
        extraction_method="openai_vision",
        ocr_status="ocr_complete" if confidence >= settings.document_min_ocr_confidence else "ocr_review_required",
        ocr_confidence=confidence,
        review_required=confidence < settings.document_min_ocr_confidence,
        review_reason=(
            "Visual OCR confidence is below threshold."
            if confidence < settings.document_min_ocr_confidence
            else None
        ),
    )


async def _extract_with_anthropic(*, content_bytes: bytes, content_type: str) -> DocumentContentResult:
    source = {
        "type": "base64",
        "media_type": content_type,
        "data": base64.b64encode(content_bytes).decode("utf-8"),
    }
    content_block = {"type": "image", "source": source}
    extraction_method = "anthropic_vision"
    if "application/pdf" in content_type:
        content_block = {"type": "document", "source": source}
        extraction_method = "anthropic_pdf_ocr"

    payload = {
        "model": settings.effective_anthropic_model,
        "max_tokens": min(settings.llm_fallback_max_tokens, 2000),
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": OCR_PROMPT},
                    content_block,
                ],
            }
        ],
    }
    async with httpx.AsyncClient(timeout=settings.document_ocr_timeout_seconds) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
    text_parts: list[str] = []
    for block in data.get("content", []) or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text_parts.append(str(block.get("text", "")))
    raw_text = "\n".join(part.strip() for part in text_parts if part.strip()).strip()
    if raw_text.upper() == "UNREADABLE" or not raw_text:
        return DocumentContentResult(
            extraction_method=extraction_method,
            ocr_status="ocr_failed",
            ocr_confidence=0.2,
            review_required=True,
            review_reason="Visual OCR could not confidently read the attachment.",
        )
    confidence = 0.84 if len(raw_text) > 40 else 0.62
    return DocumentContentResult(
        raw_text=raw_text[:8000],
        raw_text_preview=raw_text[:280],
        extraction_method=extraction_method,
        ocr_status="ocr_complete" if confidence >= settings.document_min_ocr_confidence else "ocr_review_required",
        ocr_confidence=confidence,
        review_required=confidence < settings.document_min_ocr_confidence,
        review_reason=(
            "Visual OCR confidence is below threshold."
            if confidence < settings.document_min_ocr_confidence
            else None
        ),
    )
