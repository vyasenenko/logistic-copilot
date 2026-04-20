"""AI helpers for freight inbox classification and extraction."""

from __future__ import annotations

import re
from json import JSONDecodeError, loads
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import TypeVar

from app.agent.llm import try_get_primary_llm
from app.services.location_timezone import infer_shipment_timezone
from app.schemas import (
    CarrierBidExtractionResult,
    CarrierStatusUpdateExtractionResult,
    IntentResult,
    ShipmentExtractionResult,
    StatusRequestExtractionResult,
)

TStructured = TypeVar("TStructured", IntentResult, ShipmentExtractionResult, CarrierBidExtractionResult, StatusRequestExtractionResult, CarrierStatusUpdateExtractionResult)

ROUTE_FROM_TO_PATTERN = re.compile(
    r"(?:from\s+(?P<origin>.+?)\s+to\s+(?P<destination>.+?))(?:\s|$|,|\.)",
    re.IGNORECASE,
)
ROUTE_ARROW_PATTERN = re.compile(
    r"(?P<origin>[A-Za-z][A-Za-z .-]{1,40}?)\s*(?:->|to)\s*(?P<destination>[A-Za-z][A-Za-z .-]{1,40})(?:\s|$|,|\.)",
    re.IGNORECASE,
)
PALLETS_PATTERN = re.compile(r"(\d{1,3})\s*(?:pallets?|plts?)", re.IGNORECASE)
WEIGHT_PATTERN = re.compile(
    r"(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(k)?\s*(lb|lbs|pounds?|kg|kgs|kilograms?)",
    re.IGNORECASE,
)
EQUIPMENT_PATTERN = re.compile(
    r"\b(dry van|van|reefer|refer|flatbed|flat bed|step deck|stepdeck|power only|box truck)\b",
    re.IGNORECASE,
)
AMOUNT_PATTERN = re.compile(
    r"(?:\$|usd\s*)(\d{2,7}(?:,\d{3})*(?:\.\d{1,2})?)|(\d{2,7}(?:,\d{3})*(?:\.\d{1,2})?)\s*(?:all in|total|usd)",
    re.IGNORECASE,
)
RATE_PATTERNS = [
    re.compile(r"(?:rate|quote|can do|all[- ]?in|our price|best rate|we can do|i can do)\D{0,12}\$?\s*(\d{2,7}(?:,\d{3})*(?:\.\d{1,2})?)", re.IGNORECASE),
    re.compile(r"\$\s*(\d{2,7}(?:,\d{3})*(?:\.\d{1,2})?)", re.IGNORECASE),
]
ETA_PATTERN = re.compile(r"((?:eta|delivery|pickup)[^.,;\n]{0,80})", re.IGNORECASE)
READY_AT_PATTERN = re.compile(
    r"\b(today|tomorrow|tmrw|tmr|monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s+at|\s+by)?\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?",
    re.IGNORECASE,
)
TIME_ONLY_PATTERN = re.compile(r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm))\b", re.IGNORECASE)
QUOTE_REQUEST_HINTS = ("quote", "need to move", "need moved", "move", "load", "pickup", "delivery", "pallet", "lb", "lbs")
BID_HINTS = ("all in", "can do", "rate", "quote back", "our quote", "best rate", "$")
CONFIRM_HINTS = ("ok book", "please book", "book it", "go ahead and book", "approved")
STATUS_REQUEST_HINTS = ("eta", "status", "update", "where is", "where's", "location", "arrive", "delivery status")
CARRIER_STATUS_HINTS = ("arrived", "loaded", "empty", "unloaded", "detained", "running late", "eta", "currently in", "gps", "location")
ISSUE_HINTS = ("delay", "delayed", "problem", "issue", "damaged", "missed", "late", "breakdown", "detention")
EQUIPMENT_ALIASES = {
    "van": "Dry Van",
    "dry van": "Dry Van",
    "reefer": "Reefer",
    "refer": "Reefer",
    "flatbed": "Flatbed",
    "flat bed": "Flatbed",
    "step deck": "Step Deck",
    "stepdeck": "Step Deck",
    "power only": "Power Only",
    "box truck": "Box Truck",
}
LOCATION_ALIASES = {
    "nyc": "New York, NY",
    "chicago": "Chicago, IL",
    "la": "Los Angeles, CA",
    "phx": "Phoenix, AZ",
    "dfw": "Dallas, TX",
}
ATTACHMENT_HINTS = ("see attached", "attached rate", "attached quote", "attachment", "attached")
CLARIFICATION_PATTERNS = (
    re.compile(r"\b(?:update|correction|corrected|actually)\b", re.IGNORECASE),
    re.compile(r"\b(?:pickup|delivery|weight|pallet|equipment)\s+(?:is|will be|changed to)\b", re.IGNORECASE),
)


def _choose_llm():
    return try_get_primary_llm()


def _extract_message_text(message) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return str(content or "")


def _supports_native_structured_output(llm) -> bool:
    """Best-effort capability check for provider/model structured-output support."""
    model_name = str(getattr(llm, "model_name", "") or getattr(llm, "model", "")).lower()
    base_url = str(
        getattr(llm, "openai_api_base", "") or getattr(llm, "base_url", "")
    ).lower()
    # DeepSeek OpenAI-compatible endpoint often rejects response_format/json_schema.
    if "deepseek" in model_name or "deepseek" in base_url:
        return False
    return True


def _extract_json_object(raw_text: str) -> dict:
    text = raw_text.strip()
    if not text:
        raise ValueError("Empty LLM response")
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        parsed = loads(text)
    except JSONDecodeError as exc:
        raise ValueError("LLM response did not contain valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("LLM response JSON must be an object")
    return parsed


async def _invoke_structured_with_fallback(
    *,
    llm,
    schema: type[TStructured],
    prompt: str,
) -> TStructured:
    if _supports_native_structured_output(llm):
        structured = llm.with_structured_output(schema)
        try:
            return await structured.ainvoke(prompt)
        except Exception as exc:
            error_text = str(exc).lower()
            unsupported_structured_output = (
                "response_format" in error_text
                or "response format" in error_text
                or "json_schema" in error_text
                or "structured output" in error_text
                or "invalid_request_error" in error_text
            )
            if not unsupported_structured_output:
                raise

    fallback_prompt = (
        f"{prompt}\n\n"
        "Return a single JSON object only. "
        "Do not wrap the JSON in markdown. "
        "Use null for unknown scalar fields, [] for unknown list fields, and preserve the requested schema keys."
    )
    message = await llm.ainvoke(fallback_prompt)
    payload = _extract_json_object(_extract_message_text(message))
    return schema.model_validate(payload)


def _context_blob(email_context: dict) -> str:
    now_utc = datetime.now(timezone.utc)
    return "\n".join(
        [
            f"current_datetime_utc: {now_utc.isoformat()}",
            f"current_date_utc: {now_utc.date().isoformat()}",
            f"sender_email: {email_context.get('sender_email', '')}",
            f"sender_role: {email_context.get('sender_role', '')}",
            f"subject: {email_context.get('subject', '')}",
            f"body_preview: {email_context.get('body_preview', '')}",
            f"thread_subject: {email_context.get('thread_subject', '')}",
            f"shipment_status: {email_context.get('shipment_status', '')}",
            f"known_client: {email_context.get('known_client', '')}",
            f"known_carrier: {email_context.get('known_carrier', '')}",
        ]
    )


async def classify_email_intent(email_context: dict) -> IntentResult:
    """Classify the business intent of an inbound freight email."""
    heuristics = _classify_with_heuristics(email_context)
    llm = _choose_llm()
    if llm is None:
        return heuristics

    try:
        prompt = (
            "Classify the freight inbox email intent. "
            "Allowed intents: new_quote_request, carrier_bid_reply, "
            "customer_quote_confirmation, customer_clarification, customer_status_request, carrier_status_update, exception_or_issue, noise_or_unhandled. "
            "Return high confidence only when the intent is clear.\n\n"
            f"{_context_blob(email_context)}"
        )
        result = await _invoke_structured_with_fallback(
            llm=llm,
            schema=IntentResult,
            prompt=prompt,
        )
        if result.confidence < heuristics.confidence:
            return heuristics
        return result
    except Exception:
        return heuristics


async def extract_shipment_details(email_context: dict) -> ShipmentExtractionResult:
    """Extract structured shipment details from a customer email."""
    heuristics = _extract_shipment_with_heuristics(email_context)
    llm = _choose_llm()
    if llm is None:
        return heuristics

    try:
        prompt = (
            "Extract structured freight shipment data from the email. "
            "Use intent new_quote_request. Populate origin, destination, pallets, "
            "weight_lb, equipment_type, ready_at, notes, missing_fields, ambiguity_reasons and confidence. "
            "For ready_at output a local pickup-ready date/time without timezone suffix (naive civil time); "
            "do not apply UTC offsets or Z in ready_at — timezone is inferred later from origin/destination. "
            "If a field is absent, leave it null and include it in missing_fields when critical. "
            "If the email suggests multiple routes, conflicting details, or attachment-only details, add ambiguity_reasons.\n\n"
            f"{_context_blob(email_context)}"
        )
        result = await _invoke_structured_with_fallback(
            llm=llm,
            schema=ShipmentExtractionResult,
            prompt=prompt,
        )
        return _merge_shipment_results(result, heuristics)
    except Exception:
        return heuristics


async def extract_carrier_bid(email_context: dict) -> CarrierBidExtractionResult:
    """Extract a carrier bid from a reply email."""
    heuristics = _extract_bid_with_heuristics(email_context)
    llm = _choose_llm()
    if llm is None:
        return heuristics

    try:
        prompt = (
            "Extract a structured carrier bid from the freight email. "
            "Use intent carrier_bid_reply. Populate amount, currency, eta_text, notes, ambiguity_reasons and confidence. "
            "If no clear price is present, keep amount null and reduce confidence. "
            "If the email contains multiple possible rates or attachment-only pricing, add ambiguity_reasons.\n\n"
            f"{_context_blob(email_context)}"
        )
        result = await _invoke_structured_with_fallback(
            llm=llm,
            schema=CarrierBidExtractionResult,
            prompt=prompt,
        )
        return _merge_bid_results(result, heuristics)
    except Exception:
        return heuristics


async def extract_status_request(email_context: dict) -> StatusRequestExtractionResult:
    """Extract the requested status detail from a customer email."""
    heuristics = _extract_status_request_with_heuristics(email_context)
    llm = _choose_llm()
    if llm is None:
        return heuristics

    try:
        prompt = (
            "Extract a structured customer shipment status request. "
            "Use intent customer_status_request. Populate request_type, requested_fields, notes and confidence. "
            "Typical fields are eta, location, general_status, delivery_timing.\n\n"
            f"{_context_blob(email_context)}"
        )
        result = await _invoke_structured_with_fallback(
            llm=llm,
            schema=StatusRequestExtractionResult,
            prompt=prompt,
        )
        if result.confidence < heuristics.confidence:
            return heuristics
        return result
    except Exception:
        return heuristics


async def extract_carrier_status_update(email_context: dict) -> CarrierStatusUpdateExtractionResult:
    """Extract a structured shipment update from a carrier email."""
    heuristics = _extract_carrier_status_update_with_heuristics(email_context)
    llm = _choose_llm()
    if llm is None:
        return heuristics

    try:
        prompt = (
            "Extract a structured carrier status update. "
            "Use intent carrier_status_update. Populate status_text, eta_text, location_text, notes, ambiguity_reasons and confidence. "
            "If the update is vague, lower confidence.\n\n"
            f"{_context_blob(email_context)}"
        )
        result = await _invoke_structured_with_fallback(
            llm=llm,
            schema=CarrierStatusUpdateExtractionResult,
            prompt=prompt,
        )
        return _merge_status_update_results(result, heuristics)
    except Exception:
        return heuristics


def _classify_with_heuristics(email_context: dict) -> IntentResult:
    text = f"{email_context.get('subject', '')}\n{email_context.get('body_preview', '')}".lower()
    sender_role = email_context.get("sender_role")
    shipment_status = email_context.get("shipment_status") or ""

    if sender_role == "carrier" and any(token in text for token in CARRIER_STATUS_HINTS):
        return IntentResult(intent="carrier_status_update", confidence=0.72)
    if any(token in text for token in ISSUE_HINTS):
        return IntentResult(intent="exception_or_issue", confidence=0.7)
    if sender_role == "carrier" and any(token in text for token in BID_HINTS):
        amount = _extract_bid_amount(text)
        return IntentResult(intent="carrier_bid_reply", confidence=0.85 if amount is not None else 0.68)
    if any(token in text for token in CONFIRM_HINTS):
        return IntentResult(intent="customer_quote_confirmation", confidence=0.85)
    if sender_role == "client" and shipment_status in {"booked", "booking_in_progress"} and any(token in text for token in STATUS_REQUEST_HINTS):
        return IntentResult(intent="customer_status_request", confidence=0.8)
    if sender_role == "client" and any(token in text for token in STATUS_REQUEST_HINTS):
        return IntentResult(intent="customer_status_request", confidence=0.68)
    if sender_role == "client" and any(pattern.search(text) for pattern in CLARIFICATION_PATTERNS):
        return IntentResult(intent="customer_clarification", confidence=0.78)
    if sender_role == "client" and shipment_status == "waiting_customer_details":
        return IntentResult(intent="customer_clarification", confidence=0.75)
    route = _extract_route(text)
    if sender_role != "carrier" and (route[0] or route[1] or any(token in text for token in QUOTE_REQUEST_HINTS)):
        confidence = 0.62
        if route[0] and route[1]:
            confidence += 0.12
        return IntentResult(intent="new_quote_request", confidence=min(confidence, 0.82))
    return IntentResult(intent="noise_or_unhandled", confidence=0.45)


def _extract_shipment_with_heuristics(email_context: dict) -> ShipmentExtractionResult:
    text = f"{email_context.get('subject', '')}\n{email_context.get('body_preview', '')}"
    origin, destination = _extract_route(text)
    pallets = PALLETS_PATTERN.search(text)
    weight_value = _extract_weight_lb(text)
    equipment_value = _extract_equipment(text)
    ready_at = _extract_ready_at(text)
    missing_fields: list[str] = []
    ambiguity_reasons = _shipment_ambiguity_reasons(text, origin, destination)

    pallets_value = int(pallets.group(1)) if pallets else None

    if origin is None:
        missing_fields.append("origin")
    if destination is None:
        missing_fields.append("destination")

    confidence = 0.4
    if origin and destination:
        confidence += 0.2
    if pallets_value is not None:
        confidence += 0.1
    if weight_value is not None:
        confidence += 0.1
    if equipment_value is not None:
        confidence += 0.1

    return ShipmentExtractionResult(
        origin=origin,
        destination=destination,
        pallets=pallets_value,
        weight_lb=weight_value,
        equipment_type=equipment_value,
        ready_at=ready_at,
        notes=email_context.get("body_preview", ""),
        missing_fields=missing_fields,
        ambiguity_reasons=ambiguity_reasons,
        confidence=max(0.2, min(confidence - min(len(ambiguity_reasons) * 0.08, 0.25), 0.9)),
    )


def _extract_bid_with_heuristics(email_context: dict) -> CarrierBidExtractionResult:
    text = f"{email_context.get('subject', '')}\n{email_context.get('body_preview', '')}"
    amount = _extract_bid_amount(text)
    eta_match = ETA_PATTERN.search(text)
    ambiguity_reasons = _bid_ambiguity_reasons(text)

    confidence = 0.35
    if amount is not None:
        confidence += 0.4
    if eta_match:
        confidence += 0.1

    return CarrierBidExtractionResult(
        amount=amount,
        eta_text=eta_match.group(1).strip(" .") if eta_match else None,
        notes=email_context.get("body_preview", ""),
        ambiguity_reasons=ambiguity_reasons,
        confidence=max(0.2, min(confidence - min(len(ambiguity_reasons) * 0.1, 0.3), 0.85)),
    )


def _merge_shipment_results(
    primary: ShipmentExtractionResult,
    fallback: ShipmentExtractionResult,
) -> ShipmentExtractionResult:
    if primary.origin is None:
        primary.origin = fallback.origin
    if primary.destination is None:
        primary.destination = fallback.destination
    if primary.pallets is None:
        primary.pallets = fallback.pallets
    if primary.weight_lb is None:
        primary.weight_lb = fallback.weight_lb
    if primary.equipment_type is None:
        primary.equipment_type = fallback.equipment_type
    if not primary.notes:
        primary.notes = fallback.notes
    primary.missing_fields = list(dict.fromkeys(primary.missing_fields + fallback.missing_fields))
    primary.ambiguity_reasons = list(
        dict.fromkeys(primary.ambiguity_reasons + fallback.ambiguity_reasons)
    )
    primary.confidence = max(primary.confidence, fallback.confidence)
    primary.origin = _normalize_location(primary.origin)
    primary.destination = _normalize_location(primary.destination)
    primary.equipment_type = _normalize_equipment(primary.equipment_type)
    primary.weight_lb = _normalize_weight_lb(primary.weight_lb)
    inferred_timezone = infer_shipment_timezone(primary.origin, primary.destination)
    if primary.ready_at:
        if primary.ready_at.tzinfo is not None:
            if inferred_timezone:
                primary.ready_at = primary.ready_at.astimezone(
                    ZoneInfo(inferred_timezone)
                ).replace(tzinfo=None)
            else:
                primary.ready_at = primary.ready_at.astimezone(timezone.utc).replace(tzinfo=None)
                if "ready_at_timezone_unresolved" not in primary.ambiguity_reasons:
                    primary.ambiguity_reasons.append("ready_at_timezone_unresolved")
        elif inferred_timezone is None:
            if "ready_at_timezone_unresolved" not in primary.ambiguity_reasons:
                primary.ambiguity_reasons.append("ready_at_timezone_unresolved")
    return primary


def _merge_bid_results(
    primary: CarrierBidExtractionResult,
    fallback: CarrierBidExtractionResult,
) -> CarrierBidExtractionResult:
    if primary.amount is None:
        primary.amount = fallback.amount
    if primary.currency == "USD" and fallback.currency:
        primary.currency = fallback.currency
    if primary.eta_text is None:
        primary.eta_text = fallback.eta_text
    if not primary.notes:
        primary.notes = fallback.notes
    primary.ambiguity_reasons = list(
        dict.fromkeys(primary.ambiguity_reasons + fallback.ambiguity_reasons)
    )
    primary.confidence = max(primary.confidence, fallback.confidence)
    return primary


def _extract_status_request_with_heuristics(email_context: dict) -> StatusRequestExtractionResult:
    text = f"{email_context.get('subject', '')}\n{email_context.get('body_preview', '')}".lower()
    requested_fields: list[str] = []
    if "eta" in text or "arrive" in text:
        requested_fields.append("eta")
    if "where is" in text or "where's" in text or "location" in text:
        requested_fields.append("location")
    if "status" in text and "general_status" not in requested_fields:
        requested_fields.append("general_status")
    if not requested_fields:
        requested_fields.append("general_status")
    request_type = requested_fields[0]
    confidence = 0.7 if requested_fields else 0.5
    return StatusRequestExtractionResult(
        request_type=request_type,
        requested_fields=requested_fields,
        notes=email_context.get("body_preview", ""),
        confidence=confidence,
    )


def _extract_carrier_status_update_with_heuristics(email_context: dict) -> CarrierStatusUpdateExtractionResult:
    text = f"{email_context.get('subject', '')}\n{email_context.get('body_preview', '')}"
    lower = text.lower()
    status_text = None
    for token in ("arrived", "loaded", "empty", "unloaded", "detained", "running late"):
        if token in lower:
            status_text = token
            break
    eta_match = ETA_PATTERN.search(text)
    location_text = None
    location_match = re.search(r"(?:currently in|at|near)\s+([A-Za-z][A-Za-z .-]{2,40})", text, re.IGNORECASE)
    if location_match:
        location_text = location_match.group(1).strip(" .,-")
    ambiguity_reasons: list[str] = []
    confidence = 0.45
    if status_text:
        confidence += 0.2
    if eta_match:
        confidence += 0.15
    if location_text:
        confidence += 0.15
    if status_text is None and eta_match is None and location_text is None:
        ambiguity_reasons.append("status_update_not_specific")
    return CarrierStatusUpdateExtractionResult(
        status_text=status_text,
        eta_text=eta_match.group(1).strip(" .") if eta_match else None,
        location_text=location_text,
        notes=email_context.get("body_preview", ""),
        ambiguity_reasons=ambiguity_reasons,
        confidence=min(confidence, 0.88),
    )


def _merge_status_update_results(
    primary: CarrierStatusUpdateExtractionResult,
    fallback: CarrierStatusUpdateExtractionResult,
) -> CarrierStatusUpdateExtractionResult:
    if primary.status_text is None:
        primary.status_text = fallback.status_text
    if primary.eta_text is None:
        primary.eta_text = fallback.eta_text
    if primary.location_text is None:
        primary.location_text = fallback.location_text
    if not primary.notes:
        primary.notes = fallback.notes
    primary.ambiguity_reasons = list(dict.fromkeys(primary.ambiguity_reasons + fallback.ambiguity_reasons))
    primary.confidence = max(primary.confidence, fallback.confidence)
    return primary


def _extract_route(text: str) -> tuple[str | None, str | None]:
    for pattern in (ROUTE_FROM_TO_PATTERN, ROUTE_ARROW_PATTERN):
        match = pattern.search(text)
        if match:
            origin = _normalize_location(match.group("origin"))
            destination = _normalize_location(match.group("destination"))
            if origin != destination:
                return origin, destination
    return None, None


def _normalize_location(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip(" ,.-")
    alias = LOCATION_ALIASES.get(cleaned.lower())
    if alias:
        return alias
    if len(cleaned) <= 2:
        return None
    return cleaned.title()


def _normalize_equipment(value: str | None) -> str | None:
    if not value:
        return None
    return EQUIPMENT_ALIASES.get(value.strip().lower(), value.strip().title())


def _extract_equipment(text: str) -> str | None:
    match = EQUIPMENT_PATTERN.search(text)
    if not match:
        return None
    return _normalize_equipment(match.group(1))


def _normalize_weight_lb(value: float | None) -> float | None:
    if value is None or value <= 0:
        return None
    return round(value, 2)


def _extract_weight_lb(text: str) -> float | None:
    match = WEIGHT_PATTERN.search(text)
    if not match:
        return None
    raw_value = float(match.group(1).replace(",", ""))
    if match.group(2):
        raw_value *= 1000
    unit = match.group(3).lower()
    if unit.startswith("kg"):
        raw_value *= 2.20462
    return _normalize_weight_lb(raw_value)


def _extract_ready_at(text: str) -> datetime | None:
    match = READY_AT_PATTERN.search(text)
    if not match:
        return None
    # Keep naive local time; timezone is inferred later from shipment origin/destination.
    base = datetime.utcnow().replace(tzinfo=None)
    day_token = match.group(1).lower()
    time_token = (match.group(2) or "").strip()
    if not time_token:
        time_match = TIME_ONLY_PATTERN.search(text)
        time_token = time_match.group(1).strip() if time_match else ""
    ready = _apply_day_token(base, day_token)
    hour, minute = _parse_time_token(time_token)
    return ready.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _apply_day_token(base: datetime, token: str) -> datetime:
    token = token.lower()
    if token in {"today"}:
        return base
    if token in {"tomorrow", "tmrw", "tmr"}:
        return base + timedelta(days=1)
    weekdays = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    if token not in weekdays:
        return base
    delta = (weekdays[token] - base.weekday()) % 7
    delta = 7 if delta == 0 else delta
    return base + timedelta(days=delta)


def _parse_time_token(value: str) -> tuple[int, int]:
    if not value:
        return 8, 0
    match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", value, re.IGNORECASE)
    if not match:
        return 8, 0
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = (match.group(3) or "").lower()
    if meridiem == "pm" and hour < 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    return min(hour, 23), min(minute, 59)


def _extract_bid_amount(text: str) -> float | None:
    candidates: list[tuple[float, int]] = []
    for index, pattern in enumerate(RATE_PATTERNS):
        for match in pattern.finditer(text):
            raw = match.group(1)
            if not raw:
                continue
            amount = float(raw.replace(",", ""))
            if amount < 100 or amount > 100000:
                continue
            score = 100 - index * 10
            window = text[max(0, match.start() - 20): match.end() + 20].lower()
            if any(token in window for token in ("rate", "all in", "can do", "quote", "price")):
                score += 15
            candidates.append((amount, score))
    if not candidates:
        fallback = AMOUNT_PATTERN.search(text)
        if not fallback:
            return None
        raw = fallback.group(1) or fallback.group(2)
        return float(raw.replace(",", "")) if raw else None
    candidates.sort(key=lambda item: item[1], reverse=True)
    return candidates[0][0]


def _shipment_ambiguity_reasons(
    text: str,
    origin: str | None,
    destination: str | None,
) -> list[str]:
    reasons: list[str] = []
    route_count = sum(1 for pattern in (ROUTE_FROM_TO_PATTERN, ROUTE_ARROW_PATTERN) for _ in pattern.finditer(text))
    if route_count > 1:
        reasons.append("multiple_routes_detected")
    if any(hint in text.lower() for hint in ATTACHMENT_HINTS) and not (origin and destination):
        reasons.append("attachment_referenced_without_lane_details")
    if origin and destination and origin == destination:
        reasons.append("origin_destination_conflict")
    return reasons


def _bid_ambiguity_reasons(text: str) -> list[str]:
    reasons: list[str] = []
    amounts = []
    for pattern in RATE_PATTERNS:
        amounts.extend(match.group(1) for match in pattern.finditer(text) if match.group(1))
    normalized = {amount.replace(",", "") for amount in amounts}
    if len(normalized) > 1:
        reasons.append("multiple_bid_amounts_detected")
    if any(hint in text.lower() for hint in ATTACHMENT_HINTS) and not amounts:
        reasons.append("attachment_referenced_without_inline_rate")
    return reasons
