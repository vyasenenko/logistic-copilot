"""Focused tests for freight document extraction heuristics."""

from datetime import datetime

from app.memory.database import Shipment
from app.services.freight_execution import _parse_document_fields, build_document_context, build_document_health


def test_rate_confirmation_extracts_rate_and_reference_variants():
    fields = _parse_document_fields(
        "rate_confirmation",
        "Rate Con 88421.pdf",
        (
            "Rate Confirmation\n"
            "Confirmed Rate: $1,450.00\n"
            "Load Number: LD-77881\n"
            "Pickup Number: PU-99172\n"
        ),
    )
    assert fields["rate_amount"] == 1450.0
    assert fields["reference_number"] == "LD-77881"
    assert fields["pickup_number"] == "PU-99172"


def test_bill_of_lading_extracts_bol_and_dates():
    fields = _parse_document_fields(
        "bill_of_lading",
        "BOL-00077.txt",
        (
            "Bill of Lading Number: BOL-00077\n"
            "Pickup Date: April 22, 2026\n"
            "Delivery Date: April 23, 2026\n"
            "Reference #: REF-19A2\n"
        ),
    )
    assert fields["bol_number"] == "BOL-00077"
    assert fields["pickup_date_text"] == "April 22, 2026"
    assert fields["delivery_date_text"] == "April 23, 2026"
    assert fields["reference_number"] == "REF-19A2"


def test_document_context_collects_extracted_values():
    context = build_document_context(
        [
            {
                "id": "doc-1",
                "name": "Rate Confirmation.pdf",
                "document_type": "rate_confirmation",
                "extracted_fields": {
                    "rate_amount": 1325.0,
                    "pickup_number": "PU-4455",
                    "reference_number": "LOAD-77",
                },
            },
            {
                "id": "doc-2",
                "name": "BOL.txt",
                "document_type": "bill_of_lading",
                "extracted_fields": {
                    "bol_number": "BOL-4455",
                    "pickup_date_text": "April 24, 2026",
                    "delivery_date_text": "April 25, 2026",
                },
            },
        ]
    )
    assert context["pricing_rate_amounts"] == [1325.0]
    assert context["pickup_numbers"] == ["PU-4455"]
    assert context["reference_numbers"] == ["LOAD-77"]
    assert context["bol_numbers"] == ["BOL-4455"]
    assert context["pickup_dates"] == ["April 24, 2026"]
    assert context["delivery_dates"] == ["April 25, 2026"]
    assert len(context["document_extracts"]) == 2


def test_document_health_merges_enrichment_and_counts_reviews():
    shipment = Shipment(status="awaiting_confirmation")
    health = build_document_health(
        [
            {
                "id": "doc-1",
                "name": "Rate Confirmation.pdf",
                "document_type": "rate_confirmation",
                "ocr_status": "ocr_complete",
                "review_required": False,
                "extracted_fields": {
                    "rate_amount": 1325.0,
                    "pickup_number": "PU-4455",
                },
            },
            {
                "id": "doc-2",
                "name": "BOL.txt",
                "document_type": "bill_of_lading",
                "ocr_status": "not_needed",
                "review_required": False,
                "extracted_fields": {
                    "bol_number": "BOL-4455",
                },
            },
        ],
        shipment,
        approved_fields={"reference_number": "LOAD-77"},
    )

    assert health["document_health_status"] == "healthy"
    assert health["document_enrichment"]["pickup_number"] == "PU-4455"
    assert health["document_enrichment"]["reference_number"] == "LOAD-77"
    assert health["ocr_pending_count"] == 0
    assert health["document_conflict_count"] == 0
    assert health["review_required"] is False


def test_document_health_does_not_require_pricing_backup_before_booking_flow():
    shipment = Shipment(status="quoted")
    health = build_document_health([], shipment)

    assert health["missing_document_types"] == []
    assert health["booking_review_warning"] is None
    assert health["booking_review_required"] is False
    assert health["review_required"] is False


def test_document_health_requires_pricing_backup_for_booking_flow():
    shipment = Shipment(status="awaiting_confirmation")
    health = build_document_health([], shipment)

    assert health["missing_document_types"] == ["pricing_backup"]
    assert health["booking_review_warning"] == "No rate confirmation or quote sheet found in the email thread."
    assert health["booking_review_required"] is True
    assert health["review_required"] is True


def test_document_health_detects_conflict_against_ready_date():
    shipment = Shipment(
        status="awaiting_confirmation",
        ready_at=datetime(2026, 4, 24, 8, 0),
    )
    health = build_document_health(
        [
            {
                "id": "doc-1",
                "name": "BOL.txt",
                "document_type": "bill_of_lading",
                "ocr_status": "not_needed",
                "review_required": False,
                "extracted_fields": {
                    "pickup_date_text": "April 26, 2026",
                },
            }
        ],
        shipment,
    )

    assert health["document_health_status"] == "review_required"
    assert health["document_conflict_count"] == 1
    assert health["document_conflict_fields"] == ["pickup_date_text"]
    assert health["review_required"] is True
