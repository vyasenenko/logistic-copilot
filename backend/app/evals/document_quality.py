"""Golden-sample quality evaluator for freight document extraction."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.schemas import (
    DocumentQualityResult,
    DocumentQualityRunSummary,
    DocumentQualitySample,
)
from app.services.freight_execution import (
    build_document_context,
    build_document_extract,
    build_document_health,
)


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "document_quality_samples.json"


def _load_fixture_payload() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def load_document_quality_samples(sample_filter: str | None = None) -> list[DocumentQualitySample]:
    payload = _load_fixture_payload()
    samples = [DocumentQualitySample.model_validate(item) for item in payload.get("samples", [])]
    if sample_filter:
        needle = sample_filter.strip().lower()
        samples = [
            sample
            for sample in samples
            if needle in sample.sample_id.lower() or needle in sample.document_family.lower()
        ]
    return samples


def _attachment_from_sample(sample: DocumentQualitySample) -> dict:
    return {
        "id": str(uuid4()),
        "name": sample.filename,
        "contentType": sample.content_type,
        # Synthetic-first mode: we intentionally use inline content so fixtures remain lightweight and safe.
        "contentText": sample.content_text,
    }


def _value_matches(expected, actual) -> bool:
    if isinstance(expected, float) and isinstance(actual, (float, int)):
        return abs(float(expected) - float(actual)) < 1e-6
    return expected == actual


async def _evaluate_sample(sample: DocumentQualitySample) -> DocumentQualityResult:
    attachment = _attachment_from_sample(sample)
    document_extract, _ = await build_document_extract(attachment, force_reprocess=True)
    attachment_record = {
        "id": attachment["id"],
        "name": sample.filename,
        "document_type": document_extract.document_type,
        "content_type": sample.content_type,
        "size": len(sample.content_text.encode("utf-8")),
        "extracted_text_preview": document_extract.raw_text_preview,
        "extracted_fields": document_extract.extracted_fields,
        "extraction_method": document_extract.extraction_method,
        "ocr_status": document_extract.ocr_status,
        "ocr_confidence": document_extract.ocr_confidence,
        "field_confidence": document_extract.field_confidence,
        "review_required": document_extract.review_required,
        "review_reason": document_extract.review_reason,
        "source_email_id": str(uuid4()),
    }
    shipment = SimpleNamespace(
        id=uuid4(),
        status="awaiting_confirmation",
        ready_at=sample.shipment_ready_at,
    )
    document_health = build_document_health([attachment_record], shipment)
    effective_review_required = bool(
        document_extract.review_required or document_health.get("document_conflict_count", 0)
    )
    mismatches: list[str] = []
    expected = sample.expectation

    if document_extract.document_type != expected.expected_document_type:
        mismatches.append(
            f"document_type expected={expected.expected_document_type} actual={document_extract.document_type}"
        )

    extracted_fields = dict(document_extract.extracted_fields or {})
    expected_fields = dict(expected.expected_fields or {})
    false_positive_fields = sorted(field for field in extracted_fields if field not in expected_fields)
    for field_name, expected_value in expected_fields.items():
        if field_name not in extracted_fields:
            mismatches.append(f"missing_field:{field_name}")
            continue
        if not _value_matches(expected_value, extracted_fields[field_name]):
            mismatches.append(
                f"field_value:{field_name} expected={expected_value} actual={extracted_fields[field_name]}"
            )

    if effective_review_required != expected.expected_review_required:
        mismatches.append(
            "review_required "
            f"expected={expected.expected_review_required} actual={effective_review_required}"
        )

    enrichment = dict(document_health.get("document_enrichment", {}) or {})
    for field_name, expected_value in dict(expected.expected_enrichment_fields or {}).items():
        if field_name not in enrichment:
            mismatches.append(f"missing_enrichment:{field_name}")
            continue
        if not _value_matches(expected_value, enrichment[field_name]):
            mismatches.append(
                f"enrichment_value:{field_name} expected={expected_value} actual={enrichment[field_name]}"
            )

    expected_conflicts = sorted(expected.expected_conflict_fields or [])
    actual_conflicts = sorted(document_health.get("document_conflict_fields", []) or [])
    if expected_conflicts != actual_conflicts:
        mismatches.append(
            f"conflict_fields expected={expected_conflicts} actual={actual_conflicts}"
        )

    _ = build_document_context([attachment_record])

    return DocumentQualityResult(
        sample_id=sample.sample_id,
        document_family=sample.document_family,
        source_format=sample.source_format,
        passed=not mismatches,
        document_type=document_extract.document_type,
        extraction_method=document_extract.extraction_method,
        ocr_status=document_extract.ocr_status,
        ocr_confidence=document_extract.ocr_confidence,
        field_confidence=document_extract.field_confidence,
        review_required=effective_review_required,
        expected_review_required=expected.expected_review_required,
        extracted_fields=extracted_fields,
        expected_fields=expected_fields,
        document_enrichment=enrichment,
        expected_enrichment_fields=dict(expected.expected_enrichment_fields or {}),
        document_conflict_fields=actual_conflicts,
        expected_conflict_fields=expected_conflicts,
        document_health_status=document_health.get("document_health_status"),
        false_positive_fields=false_positive_fields,
        mismatches=mismatches,
    )


def _build_metrics(
    samples: list[DocumentQualitySample],
    results: list[DocumentQualityResult],
) -> dict:
    sample_count = len(results)
    if sample_count == 0:
        return {
            "document_type_accuracy": 0.0,
            "field_presence_accuracy": 0.0,
            "field_value_exact_match": 0.0,
            "review_required_accuracy": 0.0,
            "false_positive_fields": 0,
            "field_coverage": {},
        }

    type_matches = 0
    review_matches = 0
    expected_field_total = 0
    present_field_total = 0
    exact_match_total = 0
    false_positive_total = 0
    field_coverage: dict[str, dict[str, int]] = {}

    sample_by_id = {sample.sample_id: sample for sample in samples}
    for result in results:
        sample = sample_by_id[result.sample_id]
        expected = sample.expectation
        if result.document_type == expected.expected_document_type:
            type_matches += 1
        if result.review_required == expected.expected_review_required:
            review_matches += 1
        false_positive_total += len(result.false_positive_fields)

        for field_name, expected_value in dict(expected.expected_fields or {}).items():
            expected_field_total += 1
            coverage = field_coverage.setdefault(
                field_name,
                {"expected": 0, "present": 0, "exact": 0},
            )
            coverage["expected"] += 1
            if field_name in result.extracted_fields:
                present_field_total += 1
                coverage["present"] += 1
                if _value_matches(expected_value, result.extracted_fields[field_name]):
                    exact_match_total += 1
                    coverage["exact"] += 1

    return {
        "document_type_accuracy": round(type_matches / sample_count, 4),
        "field_presence_accuracy": round(
            present_field_total / expected_field_total, 4
        )
        if expected_field_total
        else 1.0,
        "field_value_exact_match": round(
            exact_match_total / expected_field_total, 4
        )
        if expected_field_total
        else 1.0,
        "review_required_accuracy": round(review_matches / sample_count, 4),
        "false_positive_fields": false_positive_total,
        "field_coverage": field_coverage,
    }


async def run_document_quality_evaluation(
    sample_filter: str | None = None,
) -> DocumentQualityRunSummary:
    failures: list[str] = []
    try:
        samples = load_document_quality_samples(sample_filter)
    except Exception as exc:  # pragma: no cover - exercised by contract failure path
        return DocumentQualityRunSummary(
            run_at=datetime.now(timezone.utc),
            sample_count=0,
            metrics={},
            results=[],
            failures=[f"manifest_load_failed: {exc}"],
        )

    results: list[DocumentQualityResult] = []
    for sample in samples:
        try:
            results.append(await _evaluate_sample(sample))
        except Exception as exc:  # pragma: no cover - safety path for malformed fixtures
            failures.append(f"{sample.sample_id}: {exc}")

    metrics = _build_metrics(samples, results)
    return DocumentQualityRunSummary(
        run_at=datetime.now(timezone.utc),
        sample_count=len(samples),
        metrics=metrics,
        results=results,
        failures=failures,
    )


def _render_summary(summary: DocumentQualityRunSummary) -> str:
    lines = [
        "Document Quality Evaluation",
        f"run_at: {summary.run_at.isoformat()}",
        f"samples: {summary.sample_count}",
        f"failures: {len(summary.failures)}",
        "",
        "Metrics:",
    ]
    for key in (
        "document_type_accuracy",
        "field_presence_accuracy",
        "field_value_exact_match",
        "review_required_accuracy",
        "false_positive_fields",
    ):
        lines.append(f"  - {key}: {summary.metrics.get(key)}")
    lines.append("")
    lines.append("Results:")
    for result in summary.results:
        state = "PASS" if result.passed else "FAIL"
        lines.append(
            f"  - {state} {result.sample_id} "
            f"[{result.document_family}/{result.source_format}] "
            f"type={result.document_type} method={result.extraction_method or '--'} "
            f"review={result.review_required}"
        )
        if result.mismatches:
            lines.append(f"    mismatches: {', '.join(result.mismatches)}")
    if summary.failures:
        lines.append("")
        lines.append("Failures:")
        for failure in summary.failures:
            lines.append(f"  - {failure}")
    return "\n".join(lines)


async def _async_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Logistic Copilot document quality evaluation.")
    parser.add_argument("--sample-filter", default=None, help="Filter by sample id or document family.")
    parser.add_argument("--json-out", default=None, help="Optional file path for JSON report output.")
    args = parser.parse_args(argv)

    summary = await run_document_quality_evaluation(sample_filter=args.sample_filter)
    print(_render_summary(summary))

    if args.json_out:
        output_path = Path(args.json_out)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(summary.model_dump_json(indent=2), encoding="utf-8")

    return 0 if not summary.failures else 1


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
