# Logistic Copilot

Logistic Copilot is an AI-powered freight operations platform that turns an inbox into a workflow engine for logistics teams.

It reads quote requests from Outlook, extracts shipment details, sends anonymized carrier outreach, captures carrier bids, evaluates the best option, applies margin rules, prepares customer quotes, handles booking handoff to TMS, processes shipment documents, and supports status updates between email and TMS.

The product combines deterministic backend services with a freight-specific AI orchestrator. The AI decides what an email means and what should happen next, while the backend owns side effects, state, idempotency, review routing, and operator visibility.

## Product Vision

Freight teams still run large parts of their operation inside email. Customer quote requests, carrier bids, booking confirmations, rate confirmations, BOLs, pickup documents, ETAs, and location updates arrive as unstructured messages and attachments.

Logistic Copilot is designed to become the operating layer above that inbox:

- Detect freight intent from incoming emails.
- Extract structured load, bid, booking, document, and status data.
- Automate repetitive customer and carrier communication.
- Protect brokers by anonymizing customer-sensitive details before carrier outreach.
- Keep humans in control through review queues, timelines, confidence scores, and operator actions.
- Push confirmed operational data into an existing TMS instead of replacing the TMS.

## Current Status

The project has evolved from a generic AI chat agent into a freight-specific automation platform.

High-level roadmap status:

| Phase | Scope | Status |
| --- | --- | --- |
| Phase 1 | Quote intake, carrier outreach, bid evaluation, suggested customer quote | Functional MVP / operator-ready |
| Phase 2 | Booking confirmation, TMS load creation, document handoff | Implemented foundation with active document hardening |
| Phase 3 | Status updates and two-way TMS/email sync | Implemented foundation with operator controls |
| Phase 4 | Rules engine, verification, Outlook hardening, multi-user operations | Partially started through org auth, Outlook settings, sender verification, review routing |
| Phase 5 | Full AI copilot, analytics, optimization, advanced automation | Partially started through chat, tools, dashboard metrics, and AI plumbing |

This is not yet a production-hardened enterprise system. It is a strong functional MVP with the core freight workflows, operator surfaces, Outlook integration, document processing foundation, and deployment scaffolding already in place.

## Core Features

### AI Freight Inbox Orchestrator

The freight orchestrator is the core workflow brain for inbox automation.

It receives normalized email events from Outlook ingestion, loads shipment/thread/client/carrier/workflow context, classifies intent, extracts structured data, chooses the next action, calls deterministic services, and writes workflow events after each step.

Supported intent areas include:

- New customer quote requests.
- Carrier bid replies.
- Customer quote confirmations.
- Customer clarification replies.
- Customer status requests.
- Carrier location or ETA updates.
- Noise, unhandled, ambiguous, or unsafe emails.

The orchestrator does not directly mutate the world from prompts. It delegates execution to backend services so that actions can be validated, audited, retried, and made idempotent.

### Outlook Inbox Sync And Webhooks

The backend supports Outlook ingestion through Microsoft Graph.

Implemented capabilities:

- Manual Outlook sync endpoint.
- Outlook webhook endpoint.
- Webhook ensure/status endpoints.
- Auto-sync status and ensure endpoints.
- Organization-level Outlook credentials.
- Per-user Outlook email connection settings.
- Encrypted credential storage using Fernet.
- Import result payloads with parsed shipments, bids, acknowledgements, outreach, quote activity, and review counts.

Outlook is the supported email provider for the current product.

### Quote Intake

When a customer sends a quote request, the AI extraction layer attempts to parse:

- Origin.
- Destination.
- Pallets.
- Weight in pounds.
- Equipment type.
- Ready time.
- Notes.
- Missing fields.
- Confidence.

The validation layer normalizes values, filters impossible data, maps equipment labels, and protects the workflow from unsafe automation when confidence is low or required fields are missing.

If data is incomplete, the shipment can be created as partial and routed into customer clarification or manual review.

### Carrier Outreach

The system can prepare and send anonymized carrier outreach based on shipment requirements.

Implemented behavior:

- Removes or avoids customer-sensitive details before sending to carriers.
- Uses configured carrier capacity contacts.
- Writes carrier outreach events.
- Moves shipments into outreach/waiting-bids states.
- Supports follow-up and carrier award workflow primitives.

### Carrier Bid Intake

Carrier replies are parsed into bids.

Supported extraction fields include:

- Amount.
- Currency.
- ETA text.
- Notes.
- Confidence.

Rules:

- Bid intake is tied to an existing shipment/thread.
- Low-confidence carrier replies do not silently create bids.
- Failed bid extraction writes review events.
- Heuristics/regex can serve as fallback, but AI extraction is the main path.

### Bid Evaluation And Customer Quote

The backend can evaluate received bids, choose a recommended option, apply margin/profit rules, and prepare/send a customer quote.

Implemented capabilities:

- Quote window evaluation loop.
- Evaluation endpoint.
- Customer quote endpoint.
- Customer quote sent events.
- Awaiting confirmation state.
- Idempotency around repeated sync and workflow actions.

### Booking And TMS Handoff

Phase 2 introduces booking confirmation and TMS handoff.

Implemented capabilities:

- Customer confirmation detection.
- Booking-ready and booking execution flow.
- TMS handoff endpoint.
- Booking states: `booking_in_progress`, `booked`, `booking_failed`.
- Retry and idempotency foundation around TMS handoff.
- TMS handoff events and booking warnings.
- Generic TMS connector boundary.

The current TMS layer is intentionally generic. It is designed to be adapted to the customer's actual TMS once the final system is known.

### Document Processing And OCR

The project includes a document pipeline for shipment attachments.

Implemented capabilities:

- Attachment records linked to shipments.
- Document type classification.
- Searchable PDF text extraction.
- Text/JSON/XML/CSV extraction.
- OCR/vision abstraction for image and scanned document workflows.
- OpenAI and Anthropic OCR provider order via environment configuration.
- Extracted document fields.
- Document confidence scores.
- Document health on shipment records.
- Document-aware booking warnings.
- Operator actions for reprocessing, approving values, and ignoring warnings.
- Document review routing for low confidence, conflicts, and OCR review needs.

Supported document families include:

- Rate confirmation.
- Bill of lading.
- Pickup document.
- POD foundation.

The OCR path requires real provider keys and real document testing to fully validate production quality.

### Document Quality Harness

A synthetic-first quality evaluation layer exists for document extraction hardening.

It provides:

- Synthetic golden samples.
- Manifest-based expected outputs.
- CLI evaluation.
- JSON report export.
- Metrics for document type accuracy, field presence, exact value matching, review routing, false positive fields, enrichment candidates, and conflict detection.

Run it from the backend directory:

```bash
python -m app.evals.document_quality
python -m app.evals.document_quality --sample-filter rate_confirmation
python -m app.evals.document_quality --json-out /tmp/document-quality.json
```

See [docs/document-quality-evaluation.md](/Users/yasenenko/Documents/CopilotRunner/docs/document-quality-evaluation.md) for details.

### Status Workflows

Phase 3 adds customer and carrier status automation.

Implemented capabilities:

- Customer ETA/location request detection.
- TMS status lookup.
- Customer status reply draft/send flow.
- Carrier location update parsing.
- TMS status update push.
- TMS inbound status event endpoint.
- Status queue.
- Operator actions to re-run status lookup and re-run TMS update.
- Status workflow resolution.
- Status timeline and review routing foundation.

### Operator Dashboard

The dashboard is the human control layer for automation.

It includes surfaces for:

- Shipments.
- Shipment detail.
- Timeline/workflow events.
- Bids.
- Documents.
- Status queues.
- Review queues.
- Email triage.
- Clients.
- Carriers.
- Fraud denylist.
- Outlook settings.
- Users and organization management.
- Admin overview.
- Financial and freight overview summaries.

The goal is not to hide automation. The goal is to make every AI decision visible, explainable, reversible, and rerunnable.

### Email Triage And Sender Verification

The platform includes safety and triage flows for inbound email.

Implemented capabilities:

- Classifies freight quote request, carrier reply, status/ops, fraud/phishing, noise/unhandled, and operator triage.
- Sender verification events.
- Probable fraud review routing.
- Fraud denylist by sender email or domain.
- Outlook mail actions for categorization, marking read, and archive movement.

### Authentication And Multi-Organization Foundation

The backend includes organization-aware auth and access control.

Implemented capabilities:

- Bootstrap owner/org configuration.
- Login/logout/session APIs.
- Invite acceptance.
- Organization member management.
- Admin organization overview.
- Organization-level Outlook credentials.
- Organization-level TMS integration settings.
- Extension authorization token flow.

### Chrome Extension

The repository contains a browser extension under `chrome-extension/`.

Current purpose:

- Bring Logistic Copilot into the browser/inbox context.
- Support extension login/authorization bridge.
- Provide side panel UI foundation.
- Reuse backend session/auth flow.

This extension is a companion surface, not the main backend orchestration engine.

### AI Chat And Shared Agent Plumbing

The original AI chat system still exists and is useful as shared AI/tooling infrastructure.

Implemented capabilities:

- Streaming chat endpoint.
- LLM provider abstraction.
- Tool registry.
- Memory/vector infrastructure.
- Conversation persistence.

Important architecture note: the universal chat agent is not the core freight inbox orchestrator. Freight automation lives in the freight-specific orchestrator and services.

## Architecture

```text
Outlook / inbox
    |
    v
Email sync + webhook ingestion
    |
    v
Freight Inbox Orchestrator
    |
    +--> AI classification and extraction
    |
    +--> Policy, confidence, idempotency checks
    |
    +--> Deterministic freight services
             |
             +--> Shipment creation/update
             +--> Client acknowledgement
             +--> Carrier outreach
             +--> Bid intake
             +--> Bid evaluation
             +--> Customer quote
             +--> Booking/TMS handoff
             +--> Document processing/OCR
             +--> Status lookup/update
             +--> Review queue events
    |
    v
PostgreSQL + workflow events + operator dashboard
```

## Tech Stack

| Layer | Technology |
| --- | --- |
| Backend | FastAPI, Python, SQLAlchemy, Pydantic |
| AI orchestration | LangChain/LangGraph plumbing plus freight-specific services |
| LLM providers | DeepSeek, OpenAI, Anthropic, configurable provider order |
| OCR/Vision | OpenAI and Anthropic provider abstraction |
| Database | PostgreSQL |
| Vector memory | Qdrant |
| Object/file storage | MinIO locally, S3-compatible storage in cloud |
| Frontend | Next.js 15, React 19, TypeScript, Tailwind |
| Extension | Chrome extension / side panel foundation |
| Local runtime | Docker Compose |
| Deployment | Docker, Kubernetes manifests, optional DigitalOcean stack |

## Repository Structure

```text
.
├── backend/
│   ├── app/
│   │   ├── agent/                  # Shared AI chat/agent plumbing
│   │   ├── api/                    # FastAPI routers
│   │   ├── evals/                  # Document quality evaluation harness
│   │   ├── memory/                 # Database and vector memory
│   │   ├── services/               # Freight, Outlook, TMS, OCR, document services
│   │   ├── tools/                  # Tool registry and freight tools
│   │   ├── config.py               # Environment-driven settings
│   │   ├── schemas.py              # API contracts and workflow types
│   │   └── main.py                 # FastAPI application entrypoint
│   ├── Dockerfile
│   └── pyproject.toml
├── frontend/
│   ├── src/app/                    # Next.js routes
│   ├── src/components/             # Dashboard, landing, auth, freight UI
│   ├── src/constants/              # Public contact and extension constants
│   ├── Dockerfile
│   └── package.json
├── chrome-extension/               # Browser extension companion
├── docs/                           # Product and technical notes
├── k8s/                            # Kubernetes manifests
├── docker-compose.yaml             # Local development stack
├── Makefile                        # Development and deployment commands
├── .env.example                    # Environment template
└── README.md
```

## Main Backend API Areas

The backend is mounted under `/api`.

Important API groups:

- `/api/auth/*` - login, logout, invites, sessions, extension auth, user/org context.
- `/api/admin/*` - admin organization and access request management.
- `/api/organizations/current/*` - current organization settings, Outlook credentials, TMS integration.
- `/api/freight/shipments/*` - shipment CRUD, detail, archive, thread, events, operator actions.
- `/api/freight/clients/*` - client configuration.
- `/api/freight/carriers/*` - carrier configuration.
- `/api/freight/bids/*` - bid intake and bid records.
- `/api/freight/reviews` - manual review queue.
- `/api/freight/email-triage/*` - inbound email triage queue and actions.
- `/api/freight/status-queue/*` - status workflow queue and operator actions.
- `/api/freight/outlook/*` - Outlook ingest, sync, webhook, and auto-sync control.
- `/api/freight/tms/status-event` - inbound TMS status updates.
- `/api/integrations/status` - integration health summary.
- `/api/chat` - shared AI chat endpoint.

## Environment Configuration

Start from the example file:

```bash
make env-init
make env-check
```

Key configuration groups:

### Core

- `ENVIRONMENT`
- `DEBUG`
- `API_SECRET_KEY`
- `BACKEND_CORS_ORIGINS`
- `CORS_ALLOW_CHROME_EXTENSIONS`

### Database And Storage

- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_SSL`
- `QDRANT_HOST`
- `QDRANT_PORT`
- `S3_ENDPOINT_URL`
- `S3_ACCESS_KEY_ID`
- `S3_SECRET_ACCESS_KEY`
- `S3_BUCKET`

### LLM Providers

The provider order is configurable:

```env
LLM_PROVIDER_ORDER=deepseek,openai,anthropic
DEEPSEEK_API_KEY=...
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
```

If the first provider fails or is unavailable, the system can fall back according to the configured order.

### Document OCR

```env
DOCUMENT_OCR_PROVIDER_ORDER=openai,anthropic
DOCUMENT_OCR_TIMEOUT_SECONDS=45
DOCUMENT_MIN_OCR_CONFIDENCE=0.55
DOCUMENT_MIN_FIELD_CONFIDENCE=0.6
```

For real image/scanned document extraction, at least one vision-capable provider key must be configured.

### Outlook

- `OUTLOOK_CREDENTIALS_FERNET_KEY`
- `OUTLOOK_WEBHOOK_PUBLIC_BASE_URL`
- `OUTLOOK_WEBHOOK_CLIENT_STATE`
- `OUTLOOK_GRAPH_BASE_URL`

Azure client ID, tenant ID, and client secret are configured per organization through the app/API and stored encrypted.

### TMS

- `TMS_BASE_URL`
- `TMS_API_KEY`
- `TMS_TIMEOUT_SECONDS`

The current connector is generic and should be adapted to the customer's real TMS API.

### Freight Defaults

- `FREIGHT_QUOTE_WAIT_MINUTES`
- `FREIGHT_QUOTE_CHECK_INTERVAL_SECONDS`
- `FREIGHT_DEFAULT_PROFIT_MARGIN`

### Frontend

- `NEXT_PUBLIC_API_URL`
- `NEXT_PUBLIC_TURNSTILE_SITE_KEY`
- `NEXT_PUBLIC_TURNSTILE_THEME`
- `NEXT_PUBLIC_TURNSTILE_LANGUAGE`
- `NEXT_PUBLIC_TURNSTILE_SIZE`

## Local Development

### Prerequisites

- Docker and Docker Compose.
- Python 3.12 if running backend outside Docker.
- Node.js 20 if running frontend outside Docker.
- At least one LLM provider key for AI workflows.

### Run Everything With Docker Compose

```bash
make env-init
make env-check
make up-d
```

Default local services:

- Frontend: `http://localhost:3000`
- Backend: `http://localhost:8000`
- Backend health: `http://localhost:8000/health`
- Qdrant dashboard: `http://localhost:6333/dashboard`
- MinIO console: `http://localhost:9001`

### Makefile Shortcuts

```bash
make doctor
make env-check
make up
make up-d
make logs
make logs-backend
make ps
make down
```

### Backend Development

```bash
cd backend
python -m pytest
python -m compileall app
ruff check app
```

### Frontend Development

```bash
cd frontend
npm install
npm run dev
npm run lint
npm run build
```

### Document Quality Evaluation

```bash
cd backend
python -m app.evals.document_quality
python -m app.evals.document_quality --json-out /tmp/document-quality.json
```

## Outlook Setup

1. Create or use an Azure application with Microsoft Graph mail permissions.
2. Configure organization Outlook credentials in the app or through the organization credentials API.
3. Set `OUTLOOK_CREDENTIALS_FERNET_KEY` so credentials are encrypted at rest.
4. Set `OUTLOOK_WEBHOOK_PUBLIC_BASE_URL` to a public HTTPS backend URL for webhook callbacks.
5. Enable Outlook for the user from the app.
6. Use Outlook sync or webhook ensure endpoints to start ingestion.

For local development, manual sync is usually easier than webhooks because Microsoft Graph webhooks require a public HTTPS endpoint.

## TMS Integration Setup

The TMS layer is currently a generic connector boundary.

To connect a real TMS:

1. Identify the target TMS API for load creation, status lookup, status update, and document attachment.
2. Configure organization TMS settings through `/api/organizations/current/tms-integration`.
3. Set backend environment values for the generic connector if needed.
4. Map Logistic Copilot shipment fields to the TMS load schema.
5. Map document extracts and attachments to the TMS document model.
6. Configure inbound TMS status webhooks to call `/api/freight/tms/status-event`.
7. Run booking and status UAT against sandbox data before enabling auto-send in production.

## Environment Handoff Workflow

The project includes an annotated `.env.example` and helper scripts for safe handoff:

```bash
make env-init
make env-check
make env-set KEY=API_SECRET_KEY VALUE="$(openssl rand -hex 32)"
```

The checker understands required, optional, secret, production-critical, and placeholder values from comments in `.env.example`. It does not print secret values back to the terminal.

## Chrome Extension Setup

The extension is located in `chrome-extension/`.

For local testing:

1. Open Chrome extensions page.
2. Enable developer mode.
3. Load `chrome-extension/` as an unpacked extension.
4. Configure the extension to use the local or deployed frontend/backend.
5. Authorize through the extension login flow.

The extension is intended as an inbox companion UI. The backend still owns all workflow decisions, state, and side effects.

## Deployment

### Docker Compose

Docker Compose is the fastest path for local demos and development. It starts:

- Backend.
- Frontend.
- PostgreSQL.
- Qdrant.
- MinIO.

```bash
docker compose up --build
```

### Kubernetes

Kubernetes manifests live in `k8s/`.

Typical deployment flow:

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/secrets.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/databases.yaml
kubectl apply -f k8s/app.yaml
kubectl apply -f k8s/ingress.yaml
```

Recommended production shape:

- Managed PostgreSQL.
- In-cluster or managed Qdrant.
- S3-compatible object storage.
- HTTPS ingress.
- Public backend URL for Outlook webhooks.
- Separate staging and production namespaces.
- Secrets managed outside git.

### Build And Release Helpers

The Makefile includes Kubernetes and Docker helper targets for build, push, release, and rollout workflows.

Common examples:

```bash
make k8s-buildx-all
make k8s-apply
make k8s-rollout
make k8s-status
```

Review the Makefile and `k8s/` manifests before using these against a real cluster.

## Security Notes

Do not commit real credentials.

Before publishing this repository or pushing it to GitHub, inspect and sanitize:

- `.env`
- `k8s/secrets.yaml`
- Any generated reports containing customer data.
- Any real document fixtures.
- Any local-only customer/carrier samples.

If real secrets were ever committed, rotate them. Removing them from the current file is not enough because git history may still contain them.

Production recommendations:

- Use a real secrets manager or sealed secrets.
- Keep real logistics documents out of git.
- Use least-privilege Microsoft Graph permissions.
- Enable HTTPS for all webhook callbacks.
- Separate staging and production provider keys.
- Add audit retention policies before broad customer rollout.

## What Is Done

Implemented product areas:

- Marketing/product landing page with login panel.
- Auth, sessions, organization invites, users, admin overview.
- Freight dashboard and shipment control surfaces.
- Client and carrier management.
- Outlook sync, webhook, auto-sync, and per-user connection foundation.
- Freight-specific AI inbox orchestrator.
- Shipment parsing from customer emails.
- Customer acknowledgement flow.
- Anonymized carrier outreach.
- Carrier bid parsing and intake.
- Bid evaluation and customer quote flow.
- Booking confirmation detection.
- TMS handoff foundation.
- Document attachment records and document extraction pipeline.
- OCR provider abstraction for image/scanned document workflows.
- Document review, approval, warning, and health foundation.
- Document quality evaluation harness with synthetic golden samples.
- Status request lookup, carrier update parsing, and TMS status event ingestion.
- Review queues for parsing, bid, document, fraud, and status cases.
- Workflow events and shipment timeline.
- Chrome extension foundation.
- Docker Compose local stack.
- Kubernetes deployment manifests.

## What Still Needs Work

Recommended next work:

- Replace any committed Kubernetes secrets with safe templates and rotate exposed credentials.
- Run real-document OCR benchmark with 10-20 anonymized local-only logistics documents.
- Improve OCR prompts and extraction normalization based on real rate confirmations, BOLs, pickup documents, and PODs.
- Add provider benchmark reports for OpenAI vs Anthropic OCR.
- Add production-grade TMS adapters for the actual customer TMS.
- Expand document requirements into per-client/per-carrier booking rules.
- Add stricter CI gates for document extraction once real quality baselines exist.
- Harden Outlook sync, webhook renewal, and mailbox edge cases.
- Expand rules engine for per-client margins, carrier selection, wait windows, confidence thresholds, and auto-send policies.
- Improve analytics and optimization around margins, quote speed, win rate, carrier performance, and exception reasons.
- Harden background workers, retry policies, job queues, and observability for production scale.
- Add stronger audit logs and permission boundaries for multi-user operations.
- Package and publish the Chrome extension when product flows are stable.

## Roadmap

### Phase 1: Quote Automation

Goal: customer quote request to carrier outreach to bid evaluation to suggested customer quote.

Current status: functional MVP/operator-ready.

Remaining hardening:

- More real-world email samples.
- More duplicate/idempotency test coverage.
- More per-client rule customization.

### Phase 2: Booking And Documents

Goal: booking confirmation, TMS load creation, and document-aware handoff.

Current status: implemented foundation with active document hardening.

Remaining hardening:

- Real OCR benchmark pass.
- More robust document field extraction.
- Production TMS document attachment mapping.
- Client-specific booking document rules.

### Phase 3: Status Sync

Goal: customer status requests and carrier status updates synchronized with TMS.

Current status: implemented foundation with operator controls.

Remaining hardening:

- Real TMS sandbox validation.
- More status ambiguity handling.
- Better SLA and exception analytics.

### Phase 4: Rules, Verification, Outlook Hardening, Multi-User Ops

Goal: deeper configuration and safer operations at team scale.

Planned work:

- Outlook sync and webhook hardening.
- Advanced rules engine.
- Expanded identity verification.
- Richer roles and permissions.
- More audit and compliance features.

### Phase 5: Full AI Copilot And Optimization

Goal: advanced AI copilot, analytics, and optimization.

Planned work:

- Predictive pricing assistance.
- Carrier performance scoring.
- Workflow optimization recommendations.
- More autonomous exception handling.
- Advanced command center analytics.

## Useful Docs

- [docs/NEEDTODO.md](/Users/yasenenko/Documents/CopilotRunner/docs/NEEDTODO.md)
- [docs/document-quality-evaluation.md](/Users/yasenenko/Documents/CopilotRunner/docs/document-quality-evaluation.md)
- [docs/phase3-status-uat.md](/Users/yasenenko/Documents/CopilotRunner/docs/phase3-status-uat.md)
- [docs/phase3-completion-checklist.md](/Users/yasenenko/Documents/CopilotRunner/docs/phase3-completion-checklist.md)

## Development Principles

- AI decides intent and proposes actions.
- Backend services execute actions.
- Workflow state is explicit.
- Every important step writes a workflow event.
- Auto-send requires policy, confidence, identity, state, and idempotency checks.
- Low-confidence automation should route to review instead of failing silently.
- Operators must be able to see why the system stopped and how to continue.
