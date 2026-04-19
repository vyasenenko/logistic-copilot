# Phase 3 Status UAT Pack

This document is the operator-facing manual test pack for `Phase 3: Status updates and two-way TMS/email sync`.

## Goal

Validate that:

- customer status requests create safe reply workflows
- carrier status emails create safe structured update workflows
- inbound TMS status events update shipment state correctly
- duplicate and stale flows are suppressed safely
- queue, shipment detail, and timeline stay consistent

## Preconditions

- Outlook sync is enabled for the mailbox under test
- at least one booked shipment exists in the dashboard
- the shipment has a stable thread reference or quote token
- the shipment can be resolved by one of:
  - `shipment_id`
  - `quote_token`
  - `tms_load_id`

Recommended fixture shipment:

- Quote token: `Q-2026-0419`
- TMS load id: `LOAD-123`
- Status: `booked`
- Current known location: `Chicago, IL`

## Test Case 1 — Customer status request to approved send

Email:

```text
From: customer@acme.com
Subject: Re: Load Q-2026-0419 status?
Body:
Hi team,
Can you send me the latest ETA for this shipment?
Thanks.
```

Expected flow:

1. Inbox sync ingests the email.
2. Intent becomes `customer_status_request`.
3. Shipment/thread is resolved.
4. TMS lookup runs.
5. A `status_reply` task appears in `Status Ops`.
6. Task state is `draft_ready` or `awaiting_approval`.
7. Draft contains latest `status`, `ETA`, and `location`.
8. Operator reviews or edits the draft.
9. Operator clicks `approve_and_send`.
10. The reply is sent.
11. Task leaves `Active` and appears in `Recent resolved`.
12. Timeline shows lookup, draft, send, and resolution signals.

Success:

- no duplicate task
- no duplicate send after repeated click
- shipment detail matches the draft snapshot

## Test Case 2 — Duplicate customer follow-up should not double-send

Email:

```text
From: customer@acme.com
Subject: Re: Load Q-2026-0419 status?
Body:
Just following up on ETA.
```

Expected flow:

1. System detects the request as part of the same shipment context.
2. If the status snapshot is unchanged, system suppresses duplicate unsafe send behavior.
3. Queue does not accumulate conflicting active drafts for the same snapshot.

Success:

- no duplicate outbound reply for same snapshot
- queue stays clean
- timeline does not show duplicate send noise

## Test Case 3 — Ambiguous customer escalation routes to review

Email:

```text
From: customer@acme.com
Subject: Re: Need update
Body:
What is going on with this one? We have a problem on our side.
```

Expected flow:

1. Email is ingested.
2. Intent becomes `customer_status_request` or `exception_or_issue`.
3. Case routes to review instead of auto-send.
4. Operator sees a clear review reason.
5. No automated customer reply is sent.

Success:

- no unsafe auto-reply
- review reason is visible
- timeline records review routing

## Test Case 4 — Carrier status update to approved push

Email:

```text
From: dispatch@carrier-one.com
Subject: Re: Load Q-2026-0419
Body:
Driver arrived for pickup at 8:05 AM in Chicago.
ETA delivery tomorrow 6 PM.
```

Expected flow:

1. Inbox sync ingests the email.
2. Intent becomes `carrier_status_update`.
3. Structured extraction builds the carrier update payload.
4. A `carrier_update` task appears in `Status Ops`, unless policy auto-pushes.
5. Operator previews or edits the payload.
6. Operator clicks `approve_and_push`.
7. Update is pushed to TMS.
8. Task resolves into history.

Success:

- pushed payload matches structured extraction
- repeated push does not duplicate the TMS update
- shipment snapshot stays consistent

## Test Case 5 — Ambiguous carrier update requires review

Email:

```text
From: dispatch@carrier-one.com
Subject: Re: Load Q-2026-0419
Body:
Driver delayed. Call me.
```

Expected flow:

1. Email is ingested.
2. Intent goes to `carrier_status_update` or issue handling.
3. Extraction confidence is low or missing fields remain.
4. Review task appears with ambiguity reasons.
5. No blind TMS push occurs.
6. Operator edits the structured payload and then approves push.

Success:

- no silent TMS update
- ambiguity reasons are visible
- edited payload is what gets pushed

## Test Case 6 — Inbound TMS event supersedes stale tasks

Inbound event:

```json
{
  "external_event_id": "evt-1001",
  "tms_load_id": "LOAD-123",
  "tms_system": "generic",
  "status": "in_transit",
  "eta": "2026-04-20T18:00:00Z",
  "location": "Columbus, OH",
  "milestone": "linehaul",
  "payload": {
    "source": "tracking_feed"
  }
}
```

Expected flow:

1. A stale `status_reply` draft or `carrier_update` review already exists.
2. Inbound TMS event is received.
3. Shipment snapshot updates from TMS.
4. Older tasks become resolved with:
   - `resolved_no_send` or `resolved_no_push`
   - `resolution_reason = superseded_by_newer_snapshot`
5. Resolved history explains why those tasks are no longer actionable.

Success:

- stale task disappears from active queue
- task appears in resolved queue
- shipment detail reflects the fresh TMS snapshot

## Test Case 7 — Duplicate inbound TMS event is suppressed

Repeat the same TMS payload twice.

Expected flow:

1. First event ingests normally.
2. Second event returns `already_processed`.
3. No duplicate timeline pollution appears.
4. No extra resolution events are added.

Success:

- idempotent response
- shipment state remains stable

## Test Case 8 — Shipment lookup by different identities

Scenarios:

- `shipment_id` provided
- `quote_token` provided
- `tms_load_id` provided

Expected flow:

1. Inbound event resolves shipment by one of the available identities.
2. Unknown identity returns an explicit failure.

Success:

- no silent mis-linking
- correct shipment gets updated
- unknown load returns a clear error

## Test Case 9 — Timeline consistency after send, push, and ingest

For one booked shipment, run this sequence:

1. Customer status request
2. Approve send
3. Carrier status update
4. Approve push
5. Inbound TMS event

Expected timeline:

1. `tms_status_lookup`
2. `customer_status_sent` dry run or draft signal
3. `customer_status_sent` sent signal
4. `status_workflow_resolved`
5. `tms_status_updated` parsed
6. `tms_status_updated` pushed
7. `status_workflow_resolved`
8. `tms_status_ingested`
9. `status_workflow_resolved`

Success:

- operator can reconstruct the full workflow from the UI
- queue, shipment detail, and timeline agree

## Test Case 10 — Stale shipment visibility

Setup:

- shipment is in an active tracking state
- no recent status activity exists beyond the SLA threshold

Expected flow:

1. Shipment shows as `stale`.
2. Queue or review priority increases.
3. Fresh lookup or inbound TMS event clears the stale flag.

Success:

- SLA visibility works
- status health transitions correctly from `stale` to a healthy state

