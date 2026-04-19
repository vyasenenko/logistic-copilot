"""Tests for synthetic document quality evaluation harness."""

import pytest

from app.evals import document_quality


def test_load_document_quality_samples_returns_expected_families():
    samples = document_quality.load_document_quality_samples()

    assert len(samples) >= 11
    assert any(sample.document_family == "rate_confirmation" for sample in samples)
    assert any(sample.document_family == "bill_of_lading" for sample in samples)
    assert any(sample.document_family == "pickup_doc" for sample in samples)
    assert len({sample.sample_id for sample in samples}) == len(samples)


@pytest.mark.asyncio
async def test_run_document_quality_evaluation_returns_json_serializable_summary():
    summary = await document_quality.run_document_quality_evaluation(sample_filter="rate-confirmation-standard")

    assert summary.sample_count == 1
    assert summary.results
    assert "document_type_accuracy" in summary.metrics
    json_payload = summary.model_dump_json(indent=2)
    assert "rate-confirmation-standard" in json_payload
    assert "metrics" in json_payload


@pytest.mark.asyncio
async def test_run_document_quality_evaluation_uses_unified_extraction_path(monkeypatch):
    call_counter = {"count": 0}
    original = document_quality.build_document_extract

    async def _wrapped_build_document_extract(attachment, *, force_reprocess=False):
        call_counter["count"] += 1
        return await original(attachment, force_reprocess=force_reprocess)

    monkeypatch.setattr(document_quality, "build_document_extract", _wrapped_build_document_extract)

    summary = await document_quality.run_document_quality_evaluation(sample_filter="bol-standard")

    assert summary.sample_count == 1
    assert call_counter["count"] == 1


@pytest.mark.asyncio
async def test_run_document_quality_evaluation_surfaces_contract_failure(monkeypatch):
    async def _broken_build_document_extract(attachment, *, force_reprocess=False):
        raise RuntimeError("extract failed")

    monkeypatch.setattr(document_quality, "build_document_extract", _broken_build_document_extract)

    summary = await document_quality.run_document_quality_evaluation(sample_filter="rate-confirmation-standard")

    assert summary.sample_count == 1
    assert summary.failures
    assert "extract failed" in summary.failures[0]


def test_attachment_builder_keeps_synthetic_samples_lightweight():
    sample = document_quality.load_document_quality_samples("pickup-confirmation-standard")[0]

    attachment = document_quality._attachment_from_sample(sample)

    assert attachment["name"] == sample.filename
    assert attachment["contentType"] == sample.content_type
    assert attachment["contentText"] == sample.content_text
    assert attachment["id"]
