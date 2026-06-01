# Logistic Copilot — Document Quality Evaluation

This layer enables safer `OCR + parsing` improvements without manually checking every change in the booking flow.

## What the evaluator checks

- `document_type`
- presence and exact-match of key fields
- `review_required`
- shipment-level enrichment
- conflict detection
- extraction metadata:
  - `extraction_method`
  - `ocr_status`
  - `ocr_confidence`
  - `field_confidence`

## Where samples live

- Manifest and synthetic fixtures: [backend/app/evals/fixtures/document_quality_samples.json](/Users/yasenenko/Documents/CopilotRunner/backend/app/evals/fixtures/document_quality_samples.json)

## How to run

From the `backend` directory:

```bash
python -m app.evals.document_quality
```

With a filter:

```bash
python -m app.evals.document_quality --sample-filter rate_confirmation
```

With a JSON report:

```bash
python -m app.evals.document_quality --json-out /tmp/document-quality.json
```

## How to add a new sample

For each sample, fill in:

- `sample_id`
- `document_family`
- `source_format`
- `filename`
- `content_type`
- `content_text`
- `notes`
- `expectation`

In `expectation`, specify:

- `expected_document_type`
- `expected_fields`
- `expected_review_required`
- `expected_enrichment_fields` when needed
- `expected_conflict_fields` for conflict cases

## How to read mismatches

- `document_type ...` — document type recognized incorrectly
- `missing_field:<field>` — expected field was not extracted
- `field_value:<field> ...` — field extracted but value did not match
- `review_required ...` — review routing differs from expectation
- `missing_enrichment:<field>` — shipment-level enrichment was not applied
- `conflict_fields ...` — conflict detection did not match expectation

## Next steps

Next sub-stage after synthetic-first:

- connect a local-only real doc corpus outside git
- add benchmark run on 10–20 anonymized real files
- extend coverage to `POD`
- introduce CI threshold gating if needed
