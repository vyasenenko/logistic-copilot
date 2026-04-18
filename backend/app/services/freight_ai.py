"""AI helpers for freight inbox classification and extraction."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from app.agent.llm import get_fallback_llm, get_primary_llm
from app.config import settings
from app.schemas import CarrierBidExtractionResult, IntentResult, ShipmentExtractionResult

ROUTE_PATTERN = re.compile(
    r"(?:from\s+(?P<origin>.+?)\s+to\s+(?P<destination>.+?))(?:\s|$|,|\.)",
    re.IGNORECASE,
)
PALLETS_PATTERN = re.compile(r"(\d{1,3})\s*(?:pallets?|plts?)", re.IGNORECASE)
WEIGHT_PATTERN = re.compile(r"(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:lb|lbs|pounds?)", re.IGNORECASE)
EQUIPMENT_PATTERN = re.compile(
    r"\b(dry van|reefer|flatbed|step deck|power only|box truck)\b",
    re.IGNORECASE,
)
AMOUNT_PATTERN = re.compile(
    r"(?:\$|usd\s*)(\d{2,7}(?:,\d{3})*(?:\.\d{1,2})?)|(\d{2,7}(?:,\d{3})*(?:\.\d{1,2})?)\s*(?:all in|total|usd)",
    re.IGNORECASE,
)
ETA_PATTERN = re.compile(r"((?:eta|delivery|pickup)[^.,;\n]{0,80})", re.IGNORECASE)


def _choose_llm():
    if settings.anthropic_api_key:
        return get_primary_llm()
    if settings.openai_api_key:
        return get_fallback_llm()
    return None


def _context_blob(email_context: dict) -> str:
    return "\n".join(
        [
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
        structured = llm.with_structured_output(IntentResult)
        prompt = (
            "Classify the freight inbox email intent. "
            "Allowed intents: new_quote_request, carrier_bid_reply, "
            "customer_quote_confirmation, customer_clarification, noise_or_unhandled. "
            "Return high confidence only when the intent is clear.\n\n"
            f"{_context_blob(email_context)}"
        )
        result = await structured.ainvoke(prompt)
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
        structured = llm.with_structured_output(ShipmentExtractionResult)
        prompt = (
            "Extract structured freight shipment data from the email. "
            "Use intent new_quote_request. Populate origin, destination, pallets, "
            "weight_lb, equipment_type, ready_at, notes, missing_fields and confidence. "
            "If a field is absent, leave it null and include it in missing_fields when critical.\n\n"
            f"{_context_blob(email_context)}"
        )
        result = await structured.ainvoke(prompt)
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
        structured = llm.with_structured_output(CarrierBidExtractionResult)
        prompt = (
            "Extract a structured carrier bid from the freight email. "
            "Use intent carrier_bid_reply. Populate amount, currency, eta_text, notes and confidence. "
            "If no clear price is present, keep amount null and reduce confidence.\n\n"
            f"{_context_blob(email_context)}"
        )
        result = await structured.ainvoke(prompt)
        return _merge_bid_results(result, heuristics)
    except Exception:
        return heuristics


def _classify_with_heuristics(email_context: dict) -> IntentResult:
    text = f"{email_context.get('subject', '')}\n{email_context.get('body_preview', '')}".lower()
    sender_role = email_context.get("sender_role")
    shipment_status = email_context.get("shipment_status") or ""

    if sender_role == "carrier" and AMOUNT_PATTERN.search(text):
        return IntentResult(intent="carrier_bid_reply", confidence=0.8)
    if "ok book" in text or "please book" in text or "book it" in text:
        return IntentResult(intent="customer_quote_confirmation", confidence=0.85)
    if sender_role == "client" and shipment_status == "waiting_customer_details":
        return IntentResult(intent="customer_clarification", confidence=0.75)
    if any(token in text for token in ["pallet", "lbs", "dry van", "reefer", "quote", "move", "from", "to"]):
        return IntentResult(intent="new_quote_request", confidence=0.65)
    return IntentResult(intent="noise_or_unhandled", confidence=0.45)


def _extract_shipment_with_heuristics(email_context: dict) -> ShipmentExtractionResult:
    text = f"{email_context.get('subject', '')}\n{email_context.get('body_preview', '')}"
    route = ROUTE_PATTERN.search(text)
    pallets = PALLETS_PATTERN.search(text)
    weight = WEIGHT_PATTERN.search(text)
    equipment = EQUIPMENT_PATTERN.search(text)
    missing_fields: list[str] = []

    origin = route.group("origin").strip(" ,.") if route else None
    destination = route.group("destination").strip(" ,.") if route else None
    pallets_value = int(pallets.group(1)) if pallets else None
    weight_value = float(weight.group(1).replace(",", "")) if weight else None
    equipment_value = equipment.group(1).title() if equipment else None

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
        notes=email_context.get("body_preview", ""),
        missing_fields=missing_fields,
        confidence=min(confidence, 0.9),
    )


def _extract_bid_with_heuristics(email_context: dict) -> CarrierBidExtractionResult:
    text = f"{email_context.get('subject', '')}\n{email_context.get('body_preview', '')}"
    amount_match = AMOUNT_PATTERN.search(text)
    eta_match = ETA_PATTERN.search(text)

    amount = None
    if amount_match:
        raw = amount_match.group(1) or amount_match.group(2)
        amount = float(raw.replace(",", "")) if raw else None

    confidence = 0.35
    if amount is not None:
        confidence += 0.4
    if eta_match:
        confidence += 0.1

    return CarrierBidExtractionResult(
        amount=amount,
        eta_text=eta_match.group(1).strip(" .") if eta_match else None,
        notes=email_context.get("body_preview", ""),
        confidence=min(confidence, 0.85),
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
    primary.confidence = max(primary.confidence, fallback.confidence)
    if primary.ready_at and primary.ready_at.tzinfo is None:
        primary.ready_at = primary.ready_at.replace(tzinfo=timezone.utc)
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
    primary.confidence = max(primary.confidence, fallback.confidence)
    return primary
