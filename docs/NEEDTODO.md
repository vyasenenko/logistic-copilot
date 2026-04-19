# Logistic Copilot — Need To Do Later

Этот файл фиксирует задачи, которые мы осознанно не добивали сейчас, но к которым нужно вернуться позже.

## Current Project Stage

- `Phase 1`: functional MVP / operator-ready — закрыта
- `Phase 2`: в активной реализации, сильно продвинута
- `Phase 3`: следующий активный этап

## Carryover From Phase 2

### Document Processing Hardening

- Подключить `real image OCR path` для `png/jpg/webp` вложений.
- Решить, через что делать OCR:
  - vision-capable LLM provider
  - отдельный OCR service/backend
- Добавить confidence/scoring для document extraction.
- Добавить явный статус:
  - `ocr_complete`
  - `ocr_failed`
  - `ocr_review_required`
- Добавить retry/reprocess для OCR-heavy documents.

### PDF / Attachment Processing

- Улучшить extraction для реальных `rate confirmation`, `BOL`, `pickup docs`, `POD`.
- Добавить parsing multi-page PDF, а не только первых страниц.
- Добавить parsing для scanned PDF.
- Добавить mapping extracted fields в shipment enrichment, а не только в TMS payload.
- Добавить conflict detection между email body и extracted document data.

### Document-Aware Booking

- Сделать document requirements rule-based, а не hardcoded.
- Настроить per-client / per-flow required document policy.
- Добавить strict mode:
  - warning only
  - review required
  - block booking
- Добавить document coverage summary в overview/dashboard metrics.

## Phase 3 — Status Updates And Two-Way TMS/Email Sync

### Core Workflow

- Научить систему распознавать `status request` от customer.
- Научить систему распознавать `location / ETA update` от carrier.
- Добавить agent path:
  - customer email -> TMS lookup -> draft/send reply
  - carrier email -> parse update -> push to TMS
- Ввести отдельные intent types для status/update flows.

### TMS Synchronization

- Добавить read path из TMS:
  - ETA
  - location
  - shipment status
  - milestones
- Добавить write path в TMS:
  - carrier location update
  - ETA change
  - status milestone update
- Добавить idempotency для inbound status updates.
- Добавить retry/error handling для TMS sync failures.

### Email Automation

- Добавить шаблоны customer status reply.
- Добавить safe auto-send policy для status updates.
- Добавить operator review для ambiguous status requests.
- Добавить correlation между email thread и booked load/TMS entity.

### AI / Agent Layer

- Расширить `classify_email_intent(...)` новыми intent:
  - `customer_status_request`
  - `carrier_status_update`
  - `exception_or_issue`
- Добавить extraction schema для status/update messages.
- Добавить workflow decisions:
  - `fetch_tms_status`
  - `reply_with_status`
  - `update_tms_status`
  - `request_clarification`

### Dashboard / Operator UX

- Показать live shipment status timeline.
- Показать last known ETA/location.
- Добавить карточку status sync health.
- Добавить review queue для status exceptions.
- Дать оператору manual actions:
  - `re-run status lookup`
  - `re-run TMS update`
  - `approve status reply`

## Future Phases

### Phase 4

- rules engine
- verification layer
- Gmail integration
- multi-user operations
- roles / audit / permissions

### Phase 5

- full AI copilot experience
- analytics
- optimization loops
- operational recommendations
- advanced automation

## Notes

- Не превращать Phase 3 в хаотичный набор email handlers.
- Сохранять текущий принцип архитектуры:
  - AI decides
  - deterministic services execute
  - workflow state persists
- Не смешивать universal chat-agent и freight inbox orchestration.
