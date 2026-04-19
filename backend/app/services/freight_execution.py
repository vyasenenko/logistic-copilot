"""Core freight workflow execution helpers beyond carrier outreach."""

from __future__ import annotations

import base64
import binascii
from io import BytesIO
import re
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.memory.database import Carrier, CarrierBid, Client, EmailMessage, EmailThread, Shipment, WorkflowEvent
from app.schemas import (
    BidIntakeRequest,
    BidIntakeResponse,
    BidRecord,
    BookingConfirmationResponse,
    CarrierStatusUpdateResponse,
    ClientAcknowledgementResponse,
    CustomerStatusReplyResponse,
    CustomerQuoteResponse,
    ShipmentEvaluationResponse,
    ShipmentStage,
    TmsStatusResponse,
    TmsHandoffResponse,
    WorkflowEventType,
)
from app.services.email_correlation import attach_quote_token, extract_quote_token
from app.services.outlook import OutlookGraphClient
from app.services.tms_connector import TmsConnector


DOCUMENT_TYPE_RULES = (
    ("rate_confirmation", ("rate confirmation", "rateconf", "rate-con", "rate con", "ratecons")),
    ("bill_of_lading", ("bol", "bill of lading", "b/l")),
    ("proof_of_delivery", ("pod", "proof of delivery")),
    ("pickup_number", ("pickup number", "pu number", "pickup#", "pickup no", "pick up number", "pick up no")),
    ("quote_sheet", ("quote", "pricing", "rate request", "quote request")),
)

BOOKING_DOCUMENT_REQUIREMENTS = (
    ("pricing_backup", {"rate_confirmation", "quote_sheet"}),
)
GENERIC_AMOUNT_PATTERN = re.compile(r"(?:\$|usd\s*)(\d{2,7}(?:,\d{3})*(?:\.\d{1,2})?)", re.IGNORECASE)
RATE_AMOUNT_PATTERNS = (
    re.compile(r"(?:all[- ]?in|total|rate(?:\s+confirmation)?|confirmed\s+rate|carrier\s+rate)\s*[:#-]?\s*\$?\s*(\d{2,7}(?:,\d{3})*(?:\.\d{1,2})?)", re.IGNORECASE),
    re.compile(r"(?:linehaul|line\s*haul)\s*[:#-]?\s*\$?\s*(\d{2,7}(?:,\d{3})*(?:\.\d{1,2})?)", re.IGNORECASE),
    re.compile(r"(?:amount\s+due|total\s+charges)\s*[:#-]?\s*\$?\s*(\d{2,7}(?:,\d{3})*(?:\.\d{1,2})?)", re.IGNORECASE),
)
PICKUP_NUMBER_PATTERNS = (
    re.compile(r"(?:pickup(?:\s+number|\s+no\.?)?|pick\s*up(?:\s+number|\s+no\.?)?|pu#?|p\/u#?)\s*[:#-]?\s*([A-Z0-9][A-Z0-9-]{3,})", re.IGNORECASE),
    re.compile(r"(?:confirmation\s*#|conf\s*#)\s*[:#-]?\s*([A-Z0-9][A-Z0-9-]{3,})", re.IGNORECASE),
)
BOL_NUMBER_PATTERNS = (
    re.compile(r"(?:b\/l|bol|bill of lading)(?:\s+number|\s+no\.?)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9-]{3,})", re.IGNORECASE),
)
REFERENCE_NUMBER_PATTERNS = (
    re.compile(r"(?:reference|ref|load)(?:\s+number|\s+no\.?|\s*#)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9-]{3,})", re.IGNORECASE),
)
DATE_PATTERNS = (
    re.compile(r"(?:pickup\s+date|pu\s+date|ship\s+date)\s*[:#-]?\s*([A-Za-z]{3,10}\s+\d{1,2}(?:,\s*\d{4})?)", re.IGNORECASE),
    re.compile(r"(?:delivery\s+date|del\s+date)\s*[:#-]?\s*([A-Za-z]{3,10}\s+\d{1,2}(?:,\s*\d{4})?)", re.IGNORECASE),
)


def _normalize_identifier(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().upper().strip(" .,:;")
    return normalized or None


def _humanize_status_value(value: str | None, default: str = "Unknown") -> str:
    if not value:
        return default
    return value.replace("_", " ").strip().title()


def _build_status_audit_payload(
    *,
    kind: str,
    status: str | None = None,
    eta: str | None = None,
    location: str | None = None,
    milestone: str | None = None,
    source: str | None = None,
    extra: dict | None = None,
) -> dict:
    payload = {
        "status_audit_kind": kind,
        "status_label": _humanize_status_value(status),
        "eta_label": eta or "Not available",
        "location_label": location or "Not available",
        "milestone_label": _humanize_status_value(milestone, default="Not available"),
        "status_source": source,
    }
    if extra:
        payload.update(extra)
    return payload


def _extract_labeled_value(patterns: tuple[re.Pattern[str], ...], text: str) -> str | None:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return None


def _extract_rate_amount(text: str) -> float | None:
    for pattern in RATE_AMOUNT_PATTERNS:
        match = pattern.search(text)
        if match:
            return float(match.group(1).replace(",", ""))
    generic_matches = [float(match.group(1).replace(",", "")) for match in GENERIC_AMOUNT_PATTERN.finditer(text)]
    if not generic_matches:
        return None
    return max(generic_matches)


def classify_document_type(name: str | None, content_type: str | None) -> str:
    haystack = f"{name or ''} {content_type or ''}".lower()
    for document_type, hints in DOCUMENT_TYPE_RULES:
        if any(hint in haystack for hint in hints):
            return document_type
    if (content_type or "").lower() in {"application/pdf", "image/png", "image/jpeg"}:
        return "supporting_document"
    return "unknown"


def _extract_attachment_text(item: dict) -> str | None:
    for key in ("contentText", "content_text", "text", "body"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:4000]

    raw_bytes = item.get("contentBytes") or item.get("content_bytes")
    content_type = str(item.get("contentType") or item.get("@odata.mediaContentType") or "").lower()
    if not isinstance(raw_bytes, str) or not raw_bytes.strip():
        return None

    try:
        decoded = base64.b64decode(raw_bytes, validate=False)
        if any(token in content_type for token in ("text/", "json", "xml", "csv")):
            return decoded.decode("utf-8", errors="ignore").strip()[:4000] or None
        if "application/pdf" in content_type:
            return _extract_pdf_text(decoded)
        return None
    except (binascii.Error, ValueError):
        return None


def _extract_pdf_text(content_bytes: bytes) -> str | None:
    try:
        from pypdf import PdfReader
    except Exception:
        return None

    try:
        reader = PdfReader(BytesIO(content_bytes))
        text_parts: list[str] = []
        for page in reader.pages[:3]:
            extracted = page.extract_text() or ""
            if extracted.strip():
                text_parts.append(extracted.strip())
        combined = "\n".join(text_parts).strip()
        return combined[:4000] if combined else None
    except Exception:
        return None


def _attachment_extraction_details(item: dict, extracted_text: str | None) -> tuple[str | None, str | None]:
    content_type = str(item.get("contentType") or item.get("@odata.mediaContentType") or "").lower()
    if extracted_text:
        if "application/pdf" in content_type:
            return "pdf_text", "complete"
        if any(token in content_type for token in ("text/", "json", "xml", "csv")):
            return "inline_text", "not_needed"
    if any(token in content_type for token in ("image/png", "image/jpeg", "image/jpg", "image/webp")):
        return "image_binary", "pending"
    if "application/pdf" in content_type:
        return "pdf_binary", "unavailable"
    return None, None


def _parse_document_fields(document_type: str, name: str | None, text: str | None) -> dict:
    haystack = f"{name or ''}\n{text or ''}"
    fields: dict[str, str | float] = {}

    rate_amount = _extract_rate_amount(haystack)
    if document_type in {"rate_confirmation", "quote_sheet"} and rate_amount is not None:
        fields["rate_amount"] = rate_amount

    pickup_number = _normalize_identifier(_extract_labeled_value(PICKUP_NUMBER_PATTERNS, haystack))
    if pickup_number:
        fields["pickup_number"] = pickup_number

    bol_number = _normalize_identifier(_extract_labeled_value(BOL_NUMBER_PATTERNS, haystack))
    if bol_number:
        fields["bol_number"] = bol_number

    reference_number = _normalize_identifier(_extract_labeled_value(REFERENCE_NUMBER_PATTERNS, haystack))
    if reference_number:
        fields["reference_number"] = reference_number

    pickup_date = _extract_labeled_value((DATE_PATTERNS[0],), haystack)
    if pickup_date:
        fields["pickup_date_text"] = pickup_date.strip()

    delivery_date = _extract_labeled_value((DATE_PATTERNS[1],), haystack)
    if delivery_date:
        fields["delivery_date_text"] = delivery_date.strip()

    return fields


def _extract_message_attachments(email_message: EmailMessage) -> list[dict]:
    payload = dict(email_message.raw_payload_json or {})
    raw_attachments = payload.get("attachments") or payload.get("Attachments") or []
    attachments: list[dict] = []
    for item in raw_attachments:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("fileName") or item.get("filename")
        content_type = item.get("contentType") or item.get("@odata.mediaContentType")
        size = item.get("size")
        attachment_id = item.get("id")
        if not name and not attachment_id:
            continue
        extracted_text = _extract_attachment_text(item)
        document_type = classify_document_type(name, content_type)
        extraction_method, ocr_status = _attachment_extraction_details(item, extracted_text)
        attachments.append(
            {
                "id": attachment_id,
                "name": name,
                "document_type": document_type,
                "content_type": content_type,
                "size": size,
                "extracted_text_preview": extracted_text[:280] if extracted_text else None,
                "extracted_fields": _parse_document_fields(document_type, name, extracted_text),
                "extraction_method": extraction_method,
                "ocr_status": ocr_status,
                "source_email_id": str(email_message.id),
            }
        )
    return attachments


async def collect_shipment_attachments(
    session: AsyncSession,
    shipment: Shipment,
) -> list[dict]:
    if shipment.email_thread_id is None:
        return []
    result = await session.execute(
        select(EmailMessage)
        .where(EmailMessage.thread_id == shipment.email_thread_id)
        .order_by(EmailMessage.received_at.asc())
    )
    attachments: list[dict] = []
    seen: set[tuple[str | None, str | None]] = set()
    for email_message in result.scalars().all():
        for attachment in _extract_message_attachments(email_message):
            key = (attachment.get("id"), attachment.get("name"))
            if key in seen:
                continue
            seen.add(key)
            attachments.append(attachment)
    return attachments


def summarize_booking_documents(attachments: list[dict]) -> dict:
    summary: dict[str, int] = {}
    for attachment in attachments:
        document_type = str(attachment.get("document_type", "unknown"))
        summary[document_type] = summary.get(document_type, 0) + 1

    missing_document_types: list[str] = []
    for requirement_name, accepted_types in BOOKING_DOCUMENT_REQUIREMENTS:
        if not any(summary.get(document_type, 0) > 0 for document_type in accepted_types):
            missing_document_types.append(requirement_name)

    pricing_docs = summary.get("rate_confirmation", 0) + summary.get("quote_sheet", 0)
    warning = None
    if "pricing_backup" in missing_document_types:
        warning = "No rate confirmation or quote sheet found in the email thread."

    return {
        "attachment_count": len(attachments),
        "document_summary": summary,
        "pricing_document_count": pricing_docs,
        "missing_document_types": missing_document_types,
        "booking_review_warning": warning,
        "booking_review_required": bool(missing_document_types),
    }


def build_document_context(attachments: list[dict]) -> dict:
    rate_amounts: list[float] = []
    pickup_numbers: list[str] = []
    bol_numbers: list[str] = []
    reference_numbers: list[str] = []
    pickup_dates: list[str] = []
    delivery_dates: list[str] = []
    ocr_pending_documents: list[str] = []
    extracted_documents: list[dict] = []

    for attachment in attachments:
        extracted_fields = dict(attachment.get("extracted_fields", {}) or {})
        if not extracted_fields:
            continue
        if "rate_amount" in extracted_fields:
            rate_amounts.append(float(extracted_fields["rate_amount"]))
        if "pickup_number" in extracted_fields:
            pickup_numbers.append(str(extracted_fields["pickup_number"]))
        if "bol_number" in extracted_fields:
            bol_numbers.append(str(extracted_fields["bol_number"]))
        if "reference_number" in extracted_fields:
            reference_numbers.append(str(extracted_fields["reference_number"]))
        if "pickup_date_text" in extracted_fields:
            pickup_dates.append(str(extracted_fields["pickup_date_text"]))
        if "delivery_date_text" in extracted_fields:
            delivery_dates.append(str(extracted_fields["delivery_date_text"]))
        if attachment.get("ocr_status") == "pending":
            ocr_pending_documents.append(str(attachment.get("name") or attachment.get("id") or "attachment"))
        extracted_documents.append(
            {
                "id": attachment.get("id"),
                "name": attachment.get("name"),
                "document_type": attachment.get("document_type"),
                "extracted_fields": extracted_fields,
                "extraction_method": attachment.get("extraction_method"),
                "ocr_status": attachment.get("ocr_status"),
            }
        )

    return {
        "document_extracts": extracted_documents,
        "pricing_rate_amounts": rate_amounts,
        "pickup_numbers": sorted(set(pickup_numbers)),
        "bol_numbers": sorted(set(bol_numbers)),
        "reference_numbers": sorted(set(reference_numbers)),
        "pickup_dates": sorted(set(pickup_dates)),
        "delivery_dates": sorted(set(delivery_dates)),
        "ocr_pending_documents": sorted(set(ocr_pending_documents)),
    }


def _display_name_from_email(email: str) -> str:
    local_part = email.split("@", 1)[0]
    return local_part.replace(".", " ").replace("_", " ").title() or email


def _serialize_bid(bid: CarrierBid, carrier: Carrier) -> BidRecord:
    return BidRecord(
        id=str(bid.id),
        shipment_id=str(bid.shipment_id),
        carrier_id=str(carrier.id),
        carrier_name=carrier.name,
        carrier_email=carrier.email,
        amount=bid.amount,
        currency=bid.currency,
        eta_text=bid.eta_text,
        status=bid.status,
        score=dict(bid.score_json or {}),
        received_at=bid.received_at,
    )


async def _resolve_shipment(session: AsyncSession, request: BidIntakeRequest) -> Shipment:
    shipment = None
    if request.shipment_id:
        shipment = await session.get(Shipment, UUID(request.shipment_id))
    elif request.subject:
        quote_token = extract_quote_token(request.subject)
        if quote_token:
            shipment = await session.scalar(select(Shipment).where(Shipment.quote_token == quote_token))

    if shipment is None:
        raise RuntimeError("Shipment not found for bid intake")
    return shipment


async def _resolve_carrier(session: AsyncSession, request: BidIntakeRequest) -> tuple[Carrier, bool]:
    carrier = None
    created = False
    if request.carrier_id:
        carrier = await session.get(Carrier, UUID(request.carrier_id))
    elif request.carrier_email:
        carrier = await session.scalar(
            select(Carrier).where(Carrier.email == request.carrier_email.lower())
        )

    if carrier is None and request.create_carrier_if_missing and request.carrier_email:
        carrier = Carrier(
            name=_display_name_from_email(request.carrier_email),
            email=request.carrier_email.lower(),
            rating=0,
            is_active=True,
            regions_json=[],
            equipment_json=[],
            metadata_json={"source": "bid_intake"},
        )
        session.add(carrier)
        await session.flush()
        created = True

    if carrier is None:
        raise RuntimeError("Carrier not found for bid intake")

    return carrier, created


async def intake_bid(session: AsyncSession, request: BidIntakeRequest) -> BidIntakeResponse:
    """Create or update a carrier bid from a reply/manual intake payload."""
    shipment = await _resolve_shipment(session, request)
    carrier, created_carrier = await _resolve_carrier(session, request)

    created_email_message = False
    email_message_id = UUID(request.email_message_id) if request.email_message_id else None
    if email_message_id is None and shipment.email_thread_id:
        email_message = EmailMessage(
            thread_id=shipment.email_thread_id,
            sender=carrier.email,
            recipients_json=[settings.microsoft_mailbox or "unknown"],
            direction="inbound",
            subject=request.subject or attach_quote_token("Carrier bid response", shipment.quote_token or "Q-UNKNOWN"),
            body_preview=request.raw_email[:1000],
            raw_payload_json={
                "source": "bid_intake",
                "carrier_email": carrier.email,
            },
            received_at=datetime.now(timezone.utc),
        )
        session.add(email_message)
        await session.flush()
        email_message_id = email_message.id
        created_email_message = True

    bid = await session.scalar(
        select(CarrierBid).where(
            CarrierBid.shipment_id == shipment.id,
            CarrierBid.carrier_id == carrier.id,
        )
    )
    now = datetime.now(timezone.utc)
    if bid is None:
        bid = CarrierBid(
            shipment_id=shipment.id,
            carrier_id=carrier.id,
            email_message_id=email_message_id,
            amount=request.amount,
            currency=request.currency,
            eta_text=request.eta_text,
            status="received",
            raw_email=request.raw_email,
            received_at=now,
        )
        session.add(bid)
        await session.flush()
    else:
        bid.email_message_id = email_message_id or bid.email_message_id
        bid.amount = request.amount
        bid.currency = request.currency
        bid.eta_text = request.eta_text
        bid.status = "received"
        bid.raw_email = request.raw_email or bid.raw_email
        bid.received_at = now

    shipment.status = ShipmentStage.WAITING_BIDS.value
    shipment.updated_at = now
    session.add(
        WorkflowEvent(
            shipment_id=shipment.id,
            event_type=WorkflowEventType.BID_RECEIVED.value,
            stage=shipment.status,
            payload_json={
                "carrier_id": str(carrier.id),
                "amount": request.amount,
                "currency": request.currency,
                "eta_text": request.eta_text,
            },
        )
    )
    await session.commit()
    await session.refresh(bid)

    return BidIntakeResponse(
        shipment_id=str(shipment.id),
        bid=_serialize_bid(bid, carrier),
        created_carrier=created_carrier,
        created_email_message=created_email_message,
    )


def _score_bid(bid: CarrierBid, carrier: Carrier, cheapest_amount: float) -> dict:
    amount = bid.amount or 0
    price_score = 100.0 if cheapest_amount <= 0 else max(0.0, 100 - ((amount - cheapest_amount) / cheapest_amount) * 100)
    rating_score = min(carrier.rating * 20, 100)
    eta_score = 15 if bid.eta_text else 0
    total = round(price_score * 0.65 + rating_score * 0.25 + eta_score * 0.10, 2)
    return {
        "price_score": round(price_score, 2),
        "rating_score": round(rating_score, 2),
        "eta_score": eta_score,
        "total": total,
    }


def _margin_amount(base_amount: float, margin_policy: dict) -> float:
    percent = float(margin_policy.get("percent", settings.profit_margin_percent_default))
    floor_amount = float(margin_policy.get("floor_amount", settings.profit_margin_floor_default))
    return round(max(base_amount * (percent / 100), floor_amount), 2)


async def send_client_acknowledgement(
    session: AsyncSession,
    *,
    shipment_id: UUID,
    dry_run: bool,
    custom_message: str | None,
) -> ClientAcknowledgementResponse:
    """Build and optionally send the initial customer acknowledgement."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise RuntimeError("Shipment not found")
    if shipment.client_id is None:
        raise RuntimeError("Shipment has no linked client")

    client = await session.get(Client, shipment.client_id)
    if client is None:
        raise RuntimeError("Client not found for shipment")

    thread = await session.get(EmailThread, shipment.email_thread_id) if shipment.email_thread_id else None
    subject_token = shipment.quote_token or (thread.quote_token if thread else None) or "Q-UNKNOWN"
    subject = attach_quote_token(
        thread.subject if thread and thread.subject else "Quote request received",
        subject_token,
    )

    wait_window = settings.quote_wait_minutes_default
    body_lines = [
        f"Hi {client.name},",
        "",
        "Thanks for sending this quote request. We're reviewing the shipment now.",
        f"We'll be back with pricing within about {wait_window} minutes.",
        "",
        f"Route: {shipment.origin or 'TBD'} to {shipment.destination or 'TBD'}",
        f"Equipment: {shipment.equipment_type or 'TBD'}",
        f"Pallets: {shipment.pallets if shipment.pallets is not None else 'TBD'}",
        f"Weight (lb): {shipment.weight_lb if shipment.weight_lb is not None else 'TBD'}",
    ]
    if shipment.ready_at:
        body_lines.append(
            f"Requested ready time: {shipment.ready_at.astimezone(timezone.utc).isoformat()}"
        )
    if custom_message:
        body_lines.extend(["", custom_message.strip()])
    body_lines.extend(["", "We'll follow up shortly with the best option available."])
    body = "\n".join(body_lines)

    if not dry_run:
        outlook = OutlookGraphClient()
        await outlook.send_mail(subject=subject, body=body, recipients=[client.email])

    if shipment.email_thread_id:
        session.add(
            EmailMessage(
                thread_id=shipment.email_thread_id,
                sender=settings.microsoft_mailbox or "unknown",
                recipients_json=[client.email],
                direction="outbound",
                subject=subject,
                body_preview=body[:1000],
                raw_payload_json={"type": "customer_ack", "dry_run": dry_run},
                received_at=datetime.now(timezone.utc),
            )
        )

    shipment.status = ShipmentStage.CLIENT_ACKNOWLEDGED.value
    shipment.updated_at = datetime.now(timezone.utc)
    session.add(
        WorkflowEvent(
            shipment_id=shipment.id,
            event_type=WorkflowEventType.CLIENT_ACK_SENT.value,
            stage=shipment.status,
            payload_json={
                "client_email": client.email,
                "dry_run": dry_run,
                "wait_window_minutes": wait_window,
            },
        )
    )
    await session.commit()

    return ClientAcknowledgementResponse(
        shipment_id=str(shipment.id),
        client_email=client.email,
        subject=subject,
        body=body,
        dry_run=dry_run,
    )


async def evaluate_shipment_bids(session: AsyncSession, shipment_id: UUID) -> ShipmentEvaluationResponse:
    """Score bids for a shipment and select the recommended option."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise RuntimeError("Shipment not found")

    result = await session.execute(
        select(CarrierBid, Carrier)
        .join(Carrier, Carrier.id == CarrierBid.carrier_id)
        .where(CarrierBid.shipment_id == shipment.id, CarrierBid.amount.is_not(None))
    )
    rows = result.all()
    if not rows:
        raise RuntimeError("No priced bids available for evaluation")

    cheapest_amount = min((bid.amount or 0) for bid, _carrier in rows if bid.amount is not None)
    scored: list[tuple[CarrierBid, Carrier]] = []
    for bid, carrier in rows:
        bid.score_json = _score_bid(bid, carrier, cheapest_amount)
        scored.append((bid, carrier))

    winner_bid, winner_carrier = max(scored, key=lambda pair: pair[0].score_json.get("total", 0))
    for bid, _carrier in scored:
        bid.status = "selected" if bid.id == winner_bid.id else "received"

    shipment.status = ShipmentStage.EVALUATING.value
    shipment.updated_at = datetime.now(timezone.utc)
    margin_amount = _margin_amount(winner_bid.amount or 0, dict(shipment.margin_policy_json or {}))
    recommended_quote = round((winner_bid.amount or 0) + margin_amount, 2)
    session.add(
        WorkflowEvent(
            shipment_id=shipment.id,
            event_type=WorkflowEventType.EVALUATION_COMPLETED.value,
            stage=shipment.status,
            payload_json={
                "selected_bid_id": str(winner_bid.id),
                "selected_carrier_id": str(winner_carrier.id),
                "recommended_quote_amount": recommended_quote,
                "margin_amount": margin_amount,
            },
        )
    )
    await session.commit()

    return ShipmentEvaluationResponse(
        shipment_id=str(shipment.id),
        selected_bid_id=str(winner_bid.id),
        selected_carrier_id=str(winner_carrier.id),
        selected_amount=float(winner_bid.amount or 0),
        recommended_quote_amount=recommended_quote,
        margin_amount=margin_amount,
        results=[_serialize_bid(bid, carrier) for bid, carrier in scored],
    )


async def _get_selected_bid(session: AsyncSession, shipment: Shipment, bid_id: str | None) -> tuple[CarrierBid, Carrier]:
    result = await session.execute(
        select(CarrierBid, Carrier)
        .join(Carrier, Carrier.id == CarrierBid.carrier_id)
        .where(CarrierBid.shipment_id == shipment.id)
    )
    rows = result.all()
    if not rows:
        raise RuntimeError("No bids found for shipment")

    if bid_id:
        for bid, carrier in rows:
            if str(bid.id) == bid_id:
                return bid, carrier
        raise RuntimeError("Selected bid not found")

    selected = [row for row in rows if row[0].status == "selected"]
    if selected:
        return selected[0]

    best = max(rows, key=lambda row: row[0].score_json.get("total", 0))
    return best


async def _latest_workflow_event(
    session: AsyncSession,
    shipment_id: UUID,
    event_type: str,
) -> WorkflowEvent | None:
    return await session.scalar(
        select(WorkflowEvent)
        .where(
            WorkflowEvent.shipment_id == shipment_id,
            WorkflowEvent.event_type == event_type,
        )
        .order_by(WorkflowEvent.created_at.desc())
    )


async def send_customer_quote(
    session: AsyncSession,
    *,
    shipment_id: UUID,
    bid_id: str | None,
    dry_run: bool,
    custom_message: str | None,
) -> CustomerQuoteResponse:
    """Send or preview the customer quote based on the winning bid."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise RuntimeError("Shipment not found")
    if shipment.client_id is None:
        raise RuntimeError("Shipment has no linked client")

    client = await session.get(Client, shipment.client_id)
    if client is None:
        raise RuntimeError("Client not found for shipment")

    bid, _carrier = await _get_selected_bid(session, shipment, bid_id)
    base_amount = float(bid.amount or 0)
    margin_amount = _margin_amount(base_amount, dict(shipment.margin_policy_json or {}))
    final_amount = round(base_amount + margin_amount, 2)
    subject = attach_quote_token(
        f"Quote {shipment.origin or 'Origin'} to {shipment.destination or 'Destination'}",
        shipment.quote_token or "Q-UNKNOWN",
    )
    body_lines = [
        f"We can cover this load for ${final_amount:.2f}.",
        f"Base carrier cost: ${base_amount:.2f}",
        f"Margin applied: ${margin_amount:.2f}",
        f"Route: {shipment.origin or 'TBD'} to {shipment.destination or 'TBD'}",
    ]
    if shipment.ready_at:
        body_lines.append(f"Ready at: {shipment.ready_at.astimezone(timezone.utc).isoformat()}")
    if custom_message:
        body_lines.extend(["", custom_message.strip()])
    body_lines.extend(["", "Reply OK to confirm booking."])
    body = "\n".join(body_lines)

    if not dry_run:
        outlook = OutlookGraphClient()
        await outlook.send_mail(subject=subject, body=body, recipients=[client.email])

    if shipment.email_thread_id:
        session.add(
            EmailMessage(
                thread_id=shipment.email_thread_id,
                sender=settings.microsoft_mailbox or "unknown",
                recipients_json=[client.email],
                direction="outbound",
                subject=subject,
                body_preview=body[:1000],
                raw_payload_json={"type": "customer_quote", "dry_run": dry_run},
                received_at=datetime.now(timezone.utc),
            )
        )

    shipment.status = (
        ShipmentStage.AWAITING_CONFIRMATION.value if not dry_run else ShipmentStage.QUOTED.value
    )
    shipment.updated_at = datetime.now(timezone.utc)
    session.add(
        WorkflowEvent(
            shipment_id=shipment.id,
            event_type=WorkflowEventType.CLIENT_QUOTE_SENT.value,
            stage=shipment.status,
            payload_json={
                "bid_id": str(bid.id),
                "client_email": client.email,
                "final_amount": final_amount,
                "dry_run": dry_run,
            },
        )
    )
    await session.commit()

    return CustomerQuoteResponse(
        shipment_id=str(shipment.id),
        bid_id=str(bid.id),
        client_email=client.email,
        subject=subject,
        body=body,
        base_amount=base_amount,
        margin_amount=margin_amount,
        final_amount=final_amount,
        dry_run=dry_run,
    )


async def handoff_to_tms(
    session: AsyncSession,
    *,
    shipment_id: UUID,
    bid_id: str | None,
    dry_run: bool,
) -> TmsHandoffResponse:
    """Preview or submit the selected load to the TMS."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise RuntimeError("Shipment not found")

    if not dry_run:
        latest_handoff = await _latest_workflow_event(
            session,
            shipment.id,
            WorkflowEventType.TMS_HANDOFF_SENT.value,
        )
        if shipment.status == ShipmentStage.BOOKED.value and latest_handoff is not None:
            payload = dict((latest_handoff.payload_json or {}).get("payload", {}) or {})
            response_payload = dict((latest_handoff.payload_json or {}).get("response", {}) or {})
            existing_bid_id = str((latest_handoff.payload_json or {}).get("bid_id", bid_id or ""))
            return TmsHandoffResponse(
                shipment_id=str(shipment.id),
                bid_id=existing_bid_id,
                status="already_submitted",
                dry_run=False,
                payload=payload,
                response=response_payload,
            )

    bid, carrier = await _get_selected_bid(session, shipment, bid_id)
    client = await session.get(Client, shipment.client_id) if shipment.client_id else None
    attachments = await collect_shipment_attachments(session, shipment)
    document_status = summarize_booking_documents(attachments)
    document_context = build_document_context(attachments)
    payload = {
        "shipment_id": str(shipment.id),
        "quote_token": shipment.quote_token,
        "client": {
            "id": str(client.id) if client else None,
            "name": client.name if client else None,
            "email": client.email if client else None,
        },
        "carrier": {
            "id": str(carrier.id),
            "name": carrier.name,
            "email": carrier.email,
        },
        "lane": {
            "origin": shipment.origin,
            "destination": shipment.destination,
            "pallets": shipment.pallets,
            "weight_lb": shipment.weight_lb,
            "equipment_type": shipment.equipment_type,
            "ready_at": shipment.ready_at.astimezone(timezone.utc).isoformat() if shipment.ready_at else None,
        },
        "bid": {
            "id": str(bid.id),
            "amount": bid.amount,
            "currency": bid.currency,
            "eta_text": bid.eta_text,
        },
        "documents": attachments,
        "document_status": document_status,
        "document_context": document_context,
    }

    connector = TmsConnector()
    response_payload: dict = {}
    status = "preview"
    if not dry_run:
        shipment.status = ShipmentStage.BOOKING_IN_PROGRESS.value
        shipment.updated_at = datetime.now(timezone.utc)
        await session.commit()
        try:
            response_payload = await connector.request(
                "POST",
                "/loads",
                json=payload,
                idempotency_key=shipment.quote_token or str(shipment.id),
            )
            status = "submitted"
            shipment.status = ShipmentStage.BOOKED.value
        except RuntimeError as exc:
            shipment.status = ShipmentStage.BOOKING_FAILED.value
            shipment.updated_at = datetime.now(timezone.utc)
            session.add(
                WorkflowEvent(
                    shipment_id=shipment.id,
                    event_type=WorkflowEventType.EXCEPTION_RAISED.value,
                    stage=shipment.status,
                    payload_json={
                        "reason": "tms_handoff_failed",
                        "message": str(exc),
                        "payload": payload,
                    },
                )
            )
            await session.commit()
            raise
    else:
        shipment.status = ShipmentStage.AWAITING_CONFIRMATION.value

    shipment.updated_at = datetime.now(timezone.utc)
    if document_status["booking_review_required"]:
        latest_review = await _latest_workflow_event(
            session,
            shipment.id,
            WorkflowEventType.MANUAL_REVIEW_REQUIRED.value,
        )
        latest_review_payload = dict((latest_review.payload_json or {}) if latest_review else {})
        if latest_review_payload.get("reason") != "booking_documents_missing":
            session.add(
                WorkflowEvent(
                    shipment_id=shipment.id,
                    event_type=WorkflowEventType.MANUAL_REVIEW_REQUIRED.value,
                    stage=shipment.status,
                    payload_json={
                        "reason": "booking_documents_missing",
                        "next_action": "review_documents",
                        "missing_document_types": document_status["missing_document_types"],
                        "booking_review_warning": document_status["booking_review_warning"],
                        "manual_review_required": True,
                    },
                )
            )
    session.add(
        WorkflowEvent(
            shipment_id=shipment.id,
            event_type=WorkflowEventType.TMS_HANDOFF_SENT.value,
            stage=shipment.status,
            payload_json={
                "bid_id": str(bid.id),
                "carrier_id": str(carrier.id),
                "dry_run": dry_run,
                "payload": payload,
                "response": response_payload,
                "status": status,
                "attachment_count": len(attachments),
                "document_summary": document_status["document_summary"],
                "missing_document_types": document_status["missing_document_types"],
                "booking_review_warning": document_status["booking_review_warning"],
                "booking_review_required": document_status["booking_review_required"],
                "document_context": document_context,
            },
        )
    )
    await session.commit()

    return TmsHandoffResponse(
        shipment_id=str(shipment.id),
        bid_id=str(bid.id),
        status=status,
        dry_run=dry_run,
        payload=payload,
        response=response_payload,
    )


async def send_booking_confirmation(
    session: AsyncSession,
    *,
    shipment_id: UUID,
    dry_run: bool,
    custom_message: str | None,
) -> BookingConfirmationResponse:
    """Send a booking confirmation back to the customer after TMS handoff."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise RuntimeError("Shipment not found")
    if shipment.client_id is None:
        raise RuntimeError("Shipment has no linked client")

    client = await session.get(Client, shipment.client_id)
    if client is None:
        raise RuntimeError("Client not found for shipment")

    if not dry_run and shipment.email_thread_id:
        result = await session.execute(
            select(EmailMessage)
            .where(
                EmailMessage.thread_id == shipment.email_thread_id,
                EmailMessage.direction == "outbound",
            )
            .order_by(EmailMessage.received_at.desc())
        )
        for existing_confirmation in result.scalars().all():
            if dict(existing_confirmation.raw_payload_json or {}).get("type") == "booking_confirmation":
                return BookingConfirmationResponse(
                    shipment_id=str(shipment.id),
                    client_email=client.email,
                    subject=existing_confirmation.subject,
                    body=existing_confirmation.body_preview,
                    dry_run=False,
                )

    subject = attach_quote_token(
        f"Booking confirmed {shipment.origin or 'Origin'} to {shipment.destination or 'Destination'}",
        shipment.quote_token or "Q-UNKNOWN",
    )
    body_lines = [
        f"Hi {client.name},",
        "",
        "Your load is confirmed and has been booked in our system.",
        f"Route: {shipment.origin or 'TBD'} to {shipment.destination or 'TBD'}",
        f"Equipment: {shipment.equipment_type or 'TBD'}",
        f"Pallets: {shipment.pallets if shipment.pallets is not None else 'TBD'}",
        f"Weight (lb): {shipment.weight_lb if shipment.weight_lb is not None else 'TBD'}",
    ]
    if shipment.ready_at:
        body_lines.append(
            f"Scheduled ready time: {shipment.ready_at.astimezone(timezone.utc).isoformat()}"
        )
    if custom_message:
        body_lines.extend(["", custom_message.strip()])
    body_lines.extend(["", "We'll keep you updated with the next status changes."])
    body = "\n".join(body_lines)

    if not dry_run:
        outlook = OutlookGraphClient()
        await outlook.send_mail(subject=subject, body=body, recipients=[client.email])

    if shipment.email_thread_id:
        session.add(
            EmailMessage(
                thread_id=shipment.email_thread_id,
                sender=settings.microsoft_mailbox or "unknown",
                recipients_json=[client.email],
                direction="outbound",
                subject=subject,
                body_preview=body[:1000],
                raw_payload_json={"type": "booking_confirmation", "dry_run": dry_run},
                received_at=datetime.now(timezone.utc),
            )
        )

    await session.commit()

    return BookingConfirmationResponse(
        shipment_id=str(shipment.id),
        client_email=client.email,
        subject=subject,
        body=body,
        dry_run=dry_run,
    )


async def fetch_tms_shipment_status(
    session: AsyncSession,
    *,
    shipment_id: UUID,
) -> TmsStatusResponse:
    """Fetch current shipment status from the TMS and log the lookup."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise RuntimeError("Shipment not found")

    shipment_key = shipment.quote_token or str(shipment.id)
    connector = TmsConnector()
    payload = await connector.fetch_shipment_status(shipment_key)
    audit_payload = _build_status_audit_payload(
        kind="lookup",
        status=payload.get("status"),
        eta=payload.get("eta"),
        location=payload.get("location"),
        milestone=payload.get("milestone"),
        source=payload.get("source") or "tms",
        extra=payload,
    )
    session.add(
        WorkflowEvent(
            shipment_id=shipment.id,
            event_type=WorkflowEventType.TMS_STATUS_LOOKUP.value,
            stage=shipment.status,
            payload_json=audit_payload,
        )
    )
    await session.commit()
    return TmsStatusResponse(
        shipment_id=str(shipment.id),
        status=str(payload.get("status", "unknown")),
        payload=payload,
    )


async def send_customer_status_reply(
    session: AsyncSession,
    *,
    shipment_id: UUID,
    status_payload: dict,
    dry_run: bool,
    custom_message: str | None = None,
) -> CustomerStatusReplyResponse:
    """Send a shipment status update back to the customer."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise RuntimeError("Shipment not found")
    if shipment.client_id is None:
        raise RuntimeError("Shipment has no linked client")

    client = await session.get(Client, shipment.client_id)
    if client is None:
        raise RuntimeError("Client not found for shipment")

    if not dry_run and shipment.email_thread_id:
        result = await session.execute(
            select(EmailMessage)
            .where(
                EmailMessage.thread_id == shipment.email_thread_id,
                EmailMessage.direction == "outbound",
            )
            .order_by(EmailMessage.received_at.desc())
        )
        latest_status = {
            "status": status_payload.get("status"),
            "eta": status_payload.get("eta"),
            "location": status_payload.get("location"),
            "milestone": status_payload.get("milestone"),
        }
        for existing_reply in result.scalars().all():
            payload = dict(existing_reply.raw_payload_json or {})
            if payload.get("type") != "customer_status_reply":
                continue
            existing_status = dict(payload.get("status_payload", {}) or {})
            comparable = {
                "status": existing_status.get("status"),
                "eta": existing_status.get("eta"),
                "location": existing_status.get("location"),
                "milestone": existing_status.get("milestone"),
            }
            if comparable == latest_status:
                return CustomerStatusReplyResponse(
                    shipment_id=str(shipment.id),
                    client_email=client.email,
                    subject=existing_reply.subject,
                    body=existing_reply.body_preview,
                    dry_run=False,
                )

    subject = attach_quote_token(
        f"Status update {shipment.origin or 'Origin'} to {shipment.destination or 'Destination'}",
        shipment.quote_token or "Q-UNKNOWN",
    )
    status = status_payload.get("status") or "unknown"
    eta = status_payload.get("eta") or "Not available"
    location = status_payload.get("location") or "Not available"
    milestone = status_payload.get("milestone") or "Not available"
    body = "\n".join(
        [
            f"Hi {client.name},",
            "",
            "Here is the latest shipment update from our system.",
            f"Status: {status}",
            f"ETA: {eta}",
            f"Location: {location}",
            f"Milestone: {milestone}",
        ]
    )
    if custom_message:
        body = "\n".join([body, "", custom_message.strip()])

    if not dry_run:
        outlook = OutlookGraphClient()
        await outlook.send_mail(subject=subject, body=body, recipients=[client.email])

    if shipment.email_thread_id:
        session.add(
            EmailMessage(
                thread_id=shipment.email_thread_id,
                sender=settings.microsoft_mailbox or "unknown",
                recipients_json=[client.email],
                direction="outbound",
                subject=subject,
                body_preview=body[:1000],
                raw_payload_json={"type": "customer_status_reply", "dry_run": dry_run, "status_payload": status_payload},
                received_at=datetime.now(timezone.utc),
            )
        )

    session.add(
        WorkflowEvent(
            shipment_id=shipment.id,
            event_type=WorkflowEventType.CUSTOMER_STATUS_SENT.value,
            stage=shipment.status,
            payload_json=_build_status_audit_payload(
                kind="reply_drafted" if dry_run else "reply_sent",
                status=status_payload.get("status"),
                eta=status_payload.get("eta"),
                location=status_payload.get("location"),
                milestone=status_payload.get("milestone"),
                source="customer_reply",
                extra={"dry_run": dry_run, **status_payload},
            ),
        )
    )
    await session.commit()
    return CustomerStatusReplyResponse(
        shipment_id=str(shipment.id),
        client_email=client.email,
        subject=subject,
        body=body,
        dry_run=dry_run,
    )


async def push_carrier_status_to_tms(
    session: AsyncSession,
    *,
    shipment_id: UUID,
    status_text: str | None,
    eta_text: str | None,
    location_text: str | None,
    notes: str | None,
) -> TmsStatusResponse:
    """Push a carrier status update into the TMS and persist the event."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise RuntimeError("Shipment not found")
    shipment_key = shipment.quote_token or str(shipment.id)
    connector = TmsConnector()
    payload = await connector.push_shipment_update(
        shipment_key,
        status_text=status_text,
        eta_text=eta_text,
        location_text=location_text,
        notes=notes,
    )
    session.add(
        WorkflowEvent(
            shipment_id=shipment.id,
            event_type=WorkflowEventType.TMS_STATUS_UPDATED.value,
            stage=shipment.status,
            payload_json=_build_status_audit_payload(
                kind="carrier_update_pushed",
                status=status_text or payload.get("payload", {}).get("status_text"),
                eta=eta_text or payload.get("payload", {}).get("eta_text"),
                location=location_text or payload.get("payload", {}).get("location_text"),
                source="carrier_update",
                extra=payload,
            ),
        )
    )
    await session.commit()
    return TmsStatusResponse(
        shipment_id=str(shipment.id),
        status=str(payload.get("status", "unknown")),
        payload=payload,
    )


async def preview_or_push_carrier_status_update(
    session: AsyncSession,
    *,
    shipment_id: UUID,
    status_text: str | None,
    eta_text: str | None,
    location_text: str | None,
    notes: str | None,
    dry_run: bool,
) -> CarrierStatusUpdateResponse:
    """Preview or send a structured carrier status update to the TMS."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise RuntimeError("Shipment not found")

    shipment_key = shipment.quote_token or str(shipment.id)
    payload = {
        "shipment_key": shipment_key,
        "status_text": status_text,
        "eta_text": eta_text,
        "location_text": location_text,
        "notes": notes,
    }

    if dry_run:
        session.add(
            WorkflowEvent(
                shipment_id=shipment.id,
                event_type=WorkflowEventType.TMS_STATUS_UPDATED.value,
                stage=shipment.status,
                payload_json=_build_status_audit_payload(
                    kind="carrier_update_parsed",
                    status=status_text,
                    eta=eta_text,
                    location=location_text,
                    source="carrier_preview",
                    extra=payload,
                ),
            )
        )
        await session.commit()
        return CarrierStatusUpdateResponse(
            shipment_id=str(shipment.id),
            status="preview",
            dry_run=True,
            status_text=status_text,
            eta_text=eta_text,
            location_text=location_text,
            notes=notes,
            payload=payload,
        )

    response = await push_carrier_status_to_tms(
        session,
        shipment_id=shipment.id,
        status_text=status_text,
        eta_text=eta_text,
        location_text=location_text,
        notes=notes,
    )
    return CarrierStatusUpdateResponse(
        shipment_id=str(shipment.id),
        status=response.status,
        dry_run=False,
        status_text=status_text,
        eta_text=eta_text,
        location_text=location_text,
        notes=notes,
        payload=response.payload,
    )


async def confirm_booking_and_handoff(
    session: AsyncSession,
    *,
    shipment_id: UUID,
    bid_id: str | None,
    dry_run: bool,
    custom_message: str | None = None,
) -> tuple[TmsHandoffResponse, BookingConfirmationResponse]:
    """Execute the booking flow after customer confirmation."""
    handoff = await handoff_to_tms(
        session,
        shipment_id=shipment_id,
        bid_id=bid_id,
        dry_run=dry_run,
    )
    confirmation = await send_booking_confirmation(
        session,
        shipment_id=shipment_id,
        dry_run=dry_run,
        custom_message=custom_message,
    )
    return handoff, confirmation
