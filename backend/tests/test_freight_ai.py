"""Focused tests for freight inbox heuristic extraction."""

from types import SimpleNamespace

from app.services import freight_ai
from app.services.freight_ai import (
    _invoke_structured_with_fallback,
    _classify_with_heuristics,
    _extract_carrier_status_update_with_heuristics,
    _extract_status_request_with_heuristics,
    _extract_bid_with_heuristics,
    _extract_shipment_with_heuristics,
    _extract_ready_at,
    _merge_shipment_results,
)
from app.services.freight_inbox_agent import _sender_role_for_inbox_context
from app.schemas import IntentResult, ShipmentExtractionResult, ShipmentStage


def test_extract_shipment_from_arrow_route_and_k_weight():
    result = _extract_shipment_with_heuristics(
        {
            "subject": "Need quote Chicago -> NYC tomorrow 8 am",
            "body_preview": "Need to move 5 pallets, 10k lb, dry van.",
        }
    )
    assert result.origin == "Chicago, IL"
    assert result.destination == "New York, NY"
    assert result.pallets == 5
    assert result.weight_lb == 10000
    assert result.equipment_type == "Dry Van"
    assert result.ready_at is not None


def test_extract_shipment_converts_kg_to_lb():
    result = _extract_shipment_with_heuristics(
        {
            "subject": "Quote from Dallas to Phoenix",
            "body_preview": "4 pallets, 2000 kg, reefer",
        }
    )
    assert result.origin == "Dallas, TX"
    assert result.destination == "Phoenix, AZ"
    assert result.weight_lb is not None
    assert round(result.weight_lb, 2) == 4409.24
    assert result.equipment_type == "Reefer"


def test_merge_shipment_results_keeps_naive_ready_at_wall_time_with_origin_timezone():
    primary = ShipmentExtractionResult(
        origin="Dallas, TX",
        destination="Atlanta, GA",
        ready_at=None,
        missing_fields=[],
        ambiguity_reasons=[],
        confidence=0.8,
    )
    fallback = ShipmentExtractionResult(
        origin="Dallas, TX",
        destination="Atlanta, GA",
        ready_at="2026-04-21T09:30:00",  # naive local pickup time
        missing_fields=[],
        ambiguity_reasons=[],
        confidence=0.7,
    )

    merged = _merge_shipment_results(primary, fallback)

    assert merged.ready_at is not None
    assert merged.ready_at.tzinfo is None
    assert merged.ready_at.hour == 9
    assert merged.ready_at.minute == 30
    assert "ready_at_timezone_unresolved" not in merged.ambiguity_reasons


def test_merge_shipment_results_converts_early_morning_midnight_to_seven_am():
    primary = ShipmentExtractionResult(
        origin="Houston, TX",
        destination="Austin, TX",
        ready_at="2026-04-26T00:00:00",
        missing_fields=[],
        ambiguity_reasons=[],
        confidence=0.95,
    )
    fallback = ShipmentExtractionResult(confidence=0.5)

    merged = _merge_shipment_results(
        primary,
        fallback,
        source_text="Pickup April 26, early morning if possible.",
    )

    assert merged.ready_at is not None
    assert merged.ready_at.hour == 12
    assert merged.ready_at.minute == 0


def test_merge_shipment_results_drops_date_only_midnight_without_daypart():
    primary = ShipmentExtractionResult(
        origin="Houston, TX",
        destination="Austin, TX",
        ready_at="2026-04-26T00:00:00",
        missing_fields=[],
        ambiguity_reasons=[],
        confidence=0.95,
    )
    fallback = ShipmentExtractionResult(confidence=0.5)

    merged = _merge_shipment_results(primary, fallback, source_text="Pickup April 26.")

    assert merged.ready_at is None
    assert "ready_at_date_only_no_time" in merged.ambiguity_reasons


def test_merge_shipment_results_flags_unresolved_timezone_for_naive_ready_at():
    primary = ShipmentExtractionResult(
        origin="Unknown Origin",
        destination="Unknown Destination",
        ready_at="2026-04-21T09:30:00",
        missing_fields=[],
        ambiguity_reasons=[],
        confidence=0.8,
    )
    fallback = ShipmentExtractionResult(confidence=0.5)

    merged = _merge_shipment_results(primary, fallback)

    assert "ready_at_timezone_unresolved" in merged.ambiguity_reasons


def test_extract_bid_prefers_rate_language():
    result = _extract_bid_with_heuristics(
        {
            "subject": "Re: quote",
            "body_preview": "We can do $1,250 all in. ETA delivery next morning.",
        }
    )
    assert result.amount == 1250
    assert result.eta_text is not None
    assert result.confidence >= 0.75


def test_classify_carrier_reply_without_quote_request_conflict():
    result = _classify_with_heuristics(
        {
            "subject": "Re: quote request",
            "body_preview": "Carrier here, best rate is $1400.",
            "sender_role": "carrier",
            "shipment_status": "waiting_bids",
        }
    )
    assert result.intent == "carrier_bid_reply"
    assert result.confidence >= 0.8


def test_classify_short_ok_as_customer_quote_confirmation():
    result = _classify_with_heuristics(
        {
            "subject": "Re: Quote Fresno, CA to Los Angeles, CA [Q-DC836F74]",
            "body_preview": "Ok",
            "sender_role": "client",
            "shipment_status": "awaiting_confirmation",
        }
    )
    assert result.intent == "customer_quote_confirmation"
    assert result.confidence >= 0.85


def test_classify_cyrillic_ok_with_outlook_quote_as_customer_quote_confirmation():
    result = _classify_with_heuristics(
        {
            "subject": "Re: Quote Fresno, CA to Los Angeles, CA [Q-DC836F74]",
            "body_preview": (
                "Окей\r\n\r\n"
                "Get Outlook for iOS\r\n"
                "________________________________\r\n"
                "From: Ops <ops@example.com>"
            ),
            "sender_role": "client",
            "shipment_status": "awaiting_confirmation",
        }
    )
    assert result.intent == "customer_quote_confirmation"
    assert result.confidence >= 0.85


def test_classify_short_ok_does_not_confirm_before_quote_is_sent():
    result = _classify_with_heuristics(
        {
            "subject": "Re: Quote Fresno, CA to Los Angeles, CA [Q-DC836F74]",
            "body_preview": "Ok",
            "sender_role": "client",
            "shipment_status": "waiting_bids",
        }
    )
    assert result.intent != "customer_quote_confirmation"


def test_sender_role_prefers_client_while_awaiting_confirmation():
    shipment = SimpleNamespace(status=ShipmentStage.AWAITING_CONFIRMATION.value)
    client = SimpleNamespace(email="customer@example.com")
    carrier = SimpleNamespace(email="customer@example.com")

    role = _sender_role_for_inbox_context(
        shipment=shipment,
        client=client,
        carrier=carrier,
    )

    assert role == "client"


def test_extract_shipment_marks_multiple_routes_as_ambiguous():
    result = _extract_shipment_with_heuristics(
        {
            "subject": "Need quote from Chicago to NYC and from Dallas to Phoenix",
            "body_preview": "Please advise.",
        }
    )
    assert "multiple_routes_detected" in result.ambiguity_reasons


def test_same_lane_in_subject_and_body_is_not_multiple_routes():
    """Subject + body often repeat one lane; must not downgrade LLM merge with a false flag."""
    result = _extract_shipment_with_heuristics(
        {
            "subject": "Need pricing Salt Lake City to Boise",
            "body_preview": "Need a quote for 4 pallets from Salt Lake City, UT to Boise, ID.\nPickup April 30.",
        }
    )
    assert "multiple_routes_detected" not in result.ambiguity_reasons


def test_extract_ready_at_month_day_flexible_after_clock():
    parsed = _extract_ready_at("Pickup April 30, flexible after 8:00 AM.")
    assert parsed is not None
    assert parsed.month == 4
    assert parsed.day == 30
    assert parsed.hour == 8
    assert parsed.minute == 0


def test_extract_bid_marks_multiple_amounts_as_ambiguous():
    result = _extract_bid_with_heuristics(
        {
            "subject": "Re: load",
            "body_preview": "We can do 1200 all in, or 1450 if pickup shifts.",
        }
    )
    assert "multiple_bid_amounts_detected" in result.ambiguity_reasons


def test_classify_customer_status_request():
    result = _classify_with_heuristics(
        {
            "subject": "Need ETA update",
            "body_preview": "Can you share the current location and ETA?",
            "sender_role": "client",
            "shipment_status": "booked",
        }
    )
    assert result.intent == "customer_status_request"
    assert result.confidence >= 0.8


def test_extract_status_request_fields():
    result = _extract_status_request_with_heuristics(
        {
            "subject": "Status update",
            "body_preview": "Please send ETA and current location.",
        }
    )
    assert "eta" in result.requested_fields
    assert "location" in result.requested_fields


def test_extract_carrier_status_update():
    result = _extract_carrier_status_update_with_heuristics(
        {
            "subject": "Re: load update",
            "body_preview": "Driver arrived and is currently in Columbus, ETA tomorrow 10 am.",
        }
    )
    assert result.status_text == "arrived"
    assert result.location_text == "Columbus"
    assert result.eta_text is not None


def test_classify_exception_or_issue():
    result = _classify_with_heuristics(
        {
            "subject": "Urgent delay",
            "body_preview": "The truck broke down and delivery will be delayed.",
            "sender_role": "carrier",
            "shipment_status": "booked",
        }
    )
    assert result.intent == "exception_or_issue"
    assert result.confidence >= 0.7


class _BrokenStructuredLlm:
    def with_structured_output(self, _schema):
        return self

    async def ainvoke(self, _prompt):
        raise RuntimeError("This response_format type is unavailable now")


class _FallbackJsonLlm(_BrokenStructuredLlm):
    async def ainvoke(self, prompt):
        if "Return a single JSON object only." in prompt:
            return SimpleNamespace(
                content=(
                    '{"intent":"new_quote_request","origin":"New York, NY","destination":"Chicago, IL",'
                    '"pallets":10,"weight_lb":2000,"equipment_type":"Dry Van","ready_at":null,'
                    '"notes":"Please quote.","missing_fields":[],"ambiguity_reasons":[],"confidence":0.91}'
                )
            )
        raise RuntimeError("This response_format type is unavailable now")


import pytest


class _NoiseIntentLlm:
    def __init__(self):
        self.called = False

    def with_structured_output(self, _schema):
        return self

    async def ainvoke(self, prompt):
        self.called = True
        assert "short affirmative body such as OK" in prompt
        return IntentResult(intent="noise_or_unhandled", confidence=0.9)


@pytest.mark.asyncio
async def test_classify_short_ok_calls_ai_and_keeps_confirmation(monkeypatch):
    llm = _NoiseIntentLlm()
    monkeypatch.setattr(freight_ai, "_choose_llm", lambda: llm)

    result = await freight_ai.classify_email_intent(
        {
            "subject": "Re: Quote Fresno, CA to Los Angeles, CA [Q-DC836F74]",
            "body_preview": "Ok",
            "sender_role": "client",
            "shipment_status": "awaiting_confirmation",
        }
    )

    assert llm.called is True
    assert result.intent == "customer_quote_confirmation"
    assert result.confidence >= 0.85


@pytest.mark.asyncio
async def test_structured_output_falls_back_to_json_prompt_when_response_format_is_unavailable():
    result = await _invoke_structured_with_fallback(
        llm=_FallbackJsonLlm(),
        schema=ShipmentExtractionResult,
        prompt="Extract shipment JSON.",
    )

    assert result.origin == "New York, NY"
    assert result.destination == "Chicago, IL"
    assert result.pallets == 10
    assert result.weight_lb == 2000
    assert result.confidence == 0.91


def test_shipment_extraction_result_accepts_null_notes_from_llm():
    """LLMs follow 'use null for unknown' and emit notes: null; must not fail validation."""
    model = ShipmentExtractionResult.model_validate(
        {
            "intent": "new_quote_request",
            "origin": "Salt Lake City, UT",
            "destination": "Boise, ID",
            "pallets": 4,
            "weight_lb": 7200,
            "equipment_type": "Dry Van",
            "ready_at": "2026-04-30T08:00:00",
            "delivery_at": None,
            "notes": None,
            "missing_fields": ["delivery_at"],
            "ambiguity_reasons": [],
            "confidence": 0.95,
        }
    )
    assert model.notes is None
    assert model.ready_at is not None


def test_extract_bid_amount_trailing_dollar():
    from app.services.freight_ai import _extract_bid_amount

    assert _extract_bid_amount("We can do 1000$ for this lane.") == 1000.0
