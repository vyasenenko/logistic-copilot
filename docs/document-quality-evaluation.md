# Logistic Copilot — Document Quality Evaluation

Этот слой нужен для безопасного улучшения `OCR + parsing` без ручной проверки каждого изменения в booking flow.

## Что проверяет evaluator

- `document_type`
- наличие и exact-match ключевых полей
- `review_required`
- shipment-level enrichment
- conflict detection
- extraction metadata:
  - `extraction_method`
  - `ocr_status`
  - `ocr_confidence`
  - `field_confidence`

## Где лежат samples

- Manifest и synthetic fixtures: [backend/app/evals/fixtures/document_quality_samples.json](/Users/yasenenko/Documents/CopilotRunner/backend/app/evals/fixtures/document_quality_samples.json)

## Как запускать

Из директории `backend`:

```bash
python -m app.evals.document_quality
```

С фильтром:

```bash
python -m app.evals.document_quality --sample-filter rate_confirmation
```

С JSON-отчетом:

```bash
python -m app.evals.document_quality --json-out /tmp/document-quality.json
```

## Как добавить новый sample

Для каждого sample заполняем:

- `sample_id`
- `document_family`
- `source_format`
- `filename`
- `content_type`
- `content_text`
- `notes`
- `expectation`

В `expectation` указываем:

- `expected_document_type`
- `expected_fields`
- `expected_review_required`
- `expected_enrichment_fields` при необходимости
- `expected_conflict_fields` для conflict cases

## Как читать mismatches

- `document_type ...` — тип документа распознан неверно
- `missing_field:<field>` — ожидаемое поле не извлечено
- `field_value:<field> ...` — поле извлечено, но значение не совпало
- `review_required ...` — review-routing отличается от expectation
- `missing_enrichment:<field>` — shipment-level enrichment не поднялся
- `conflict_fields ...` — conflict detection не совпала с expectation

## Что дальше

Следующий подэтап после synthetic-first:

- подключить local-only real doc corpus вне git
- добавить benchmark run по 10–20 обезличенным реальным файлам
- расширить coverage на `POD`
- при необходимости ввести CI threshold gating
