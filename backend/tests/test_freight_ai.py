"""Focused tests for freight inbox heuristic extraction."""

from app.services.freight_ai import (
    _classify_with_heuristics,
    _extract_carrier_status_update_with_heuristics,
    _extract_status_request_with_heuristics,
    _extract_bid_with_heuristics,
    _extract_shipment_with_heuristics,
)


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


def test_extract_shipment_marks_multiple_routes_as_ambiguous():
    result = _extract_shipment_with_heuristics(
        {
            "subject": "Need quote from Chicago to NYC and from Dallas to Phoenix",
            "body_preview": "Please advise.",
        }
    )
    assert "multiple_routes_detected" in result.ambiguity_reasons


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
