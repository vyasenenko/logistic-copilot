# Phase 3 Completion Checklist

Use this checklist to decide whether `Phase 3` is fully closed as an operator-ready milestone.

## Workflow completion

- customer status request creates a safe `status_reply` workflow
- carrier status email creates a safe `carrier_update` workflow
- inbound TMS status event updates shipment state
- duplicate inbound TMS events are suppressed
- stale or superseded operator tasks move out of active queue

## Queue and history

- `Status Ops` shows active tasks
- `Status Ops` shows recent resolved history
- resolved tasks expose:
  - `resolution_state`
  - `resolution_reason`
  - `resolution_at`
- resolved tasks do not offer active operator actions

## Shipment projection

- shipment detail shows:
  - `last_known_status`
  - `last_known_eta`
  - `last_known_location`
  - `last_status_source`
  - `tms_load_id`
  - `tms_system`
  - `status_workflow_state`
  - `status_sync_health`
- stale shipments are visible as stale
- fresh sync clears stale state when appropriate

## Timeline and audit

- timeline shows lookup, draft, send, push, ingest, and resolution signals
- `status_workflow_resolved` events display a meaningful reason
- operator can reconstruct the full status workflow without raw payload inspection

## Verification

- backend route-level tests cover:
  - `GET /api/freight/status-queue?include_resolved=true`
  - `POST /api/freight/status-queue/{task_id}/action`
  - `POST /api/freight/tms/status-event`
  - shipment detail projection after status changes
- manual UAT scenarios from `docs/phase3-status-uat.md` are executable

