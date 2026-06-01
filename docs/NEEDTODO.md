# Logistic Copilot — Need To Do Later

This file tracks tasks we intentionally deferred but should revisit later.

## Current Project Stage

- `Phase 1`: functional MVP / operator-ready — done
- `Phase 2`: actively in progress, substantially advanced
- `Phase 3`: next active phase

## Carryover From Phase 2

### Document Processing Hardening

- Wire up `real image OCR path` for `png/jpg/webp` attachments.
- Decide how to run OCR:
  - vision-capable LLM provider
  - dedicated OCR service/backend
- Add confidence/scoring for document extraction.
- Add explicit status:
  - `ocr_complete`
  - `ocr_failed`
  - `ocr_review_required`
- Add retry/reprocess for OCR-heavy documents.

### PDF / Attachment Processing

- Improve extraction for real `rate confirmation`, `BOL`, `pickup docs`, `POD`.
- Add multi-page PDF parsing, not only the first pages.
- Add parsing for scanned PDFs.
- Map extracted fields into shipment enrichment, not only TMS payload.
- Add conflict detection between email body and extracted document data.
- Connect a `real local-only document corpus` for quality benchmark on top of the synthetic harness.
- Add `provider benchmark runs` on real OCR-heavy files and compare `openai` vs `anthropic`.
- Decide when to introduce `CI threshold gating` for document quality metrics.

### Document-Aware Booking

- Make document requirements rule-based instead of hardcoded.
- Configure per-client / per-flow required document policy.
- Add strict mode:
  - warning only
  - review required
  - block booking
- Add document coverage summary to overview/dashboard metrics.

## Phase 3 — Status Updates And Two-Way TMS/Email Sync

### Core Workflow

- Teach the system to recognize customer `status request`.
- Teach the system to recognize carrier `location / ETA update`.
- Add agent path:
  - customer email -> TMS lookup -> draft/send reply
  - carrier email -> parse update -> push to TMS
- Introduce separate intent types for status/update flows.

### TMS Synchronization

- Add read path from TMS:
  - ETA
  - location
  - shipment status
  - milestones
- Add write path to TMS:
  - carrier location update
  - ETA change
  - status milestone update
- Add idempotency for inbound status updates.
- Add retry/error handling for TMS sync failures.

### Email Automation

- Add customer status reply templates.
- Add safe auto-send policy for status updates.
- Add operator review for ambiguous status requests.
- Add correlation between email thread and booked load/TMS entity.

### AI / Agent Layer

- Extend `classify_email_intent(...)` with new intents:
  - `customer_status_request`
  - `carrier_status_update`
  - `exception_or_issue`
- Add extraction schema for status/update messages.
- Add workflow decisions:
  - `fetch_tms_status`
  - `reply_with_status`
  - `update_tms_status`
  - `request_clarification`

### Dashboard / Operator UX

- Show live shipment status timeline.
- Show last known ETA/location.
- Add status sync health card.
- Add review queue for status exceptions.
- Give operator manual actions:
  - `re-run status lookup`
  - `re-run TMS update`
  - `approve status reply`

## Future Phases

### Phase 4

- rules engine
- verification layer
- Outlook sync and webhook hardening
- multi-user operations
- roles / audit / permissions

### Phase 5

- full AI copilot experience
- analytics
- optimization loops
- operational recommendations
- advanced automation

## Notes

- Do not turn Phase 3 into a chaotic set of email handlers.
- Keep the current architecture principle:
  - AI decides
  - deterministic services execute
  - workflow state persists
- Do not mix universal chat-agent and freight inbox orchestration.
