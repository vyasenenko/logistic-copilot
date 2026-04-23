"use client";

import { startTransition, useEffect, useMemo, useState } from "react";

import { useFreightSocket } from "@/hooks/useFreightSocket";
import { DateTimePickerField } from "@/components/DateTimePickerField";
import { DashboardLogo } from "@/components/DashboardLogo";
import {
  AlertTriangle,
  ArrowRight,
  Building2,
  CheckCircle2,
  CircleDollarSign,
  ClipboardCheck,
  Clock3,
  Loader2,
  Mail,
  Map,
  MoreHorizontal,
  Package2,
  PencilLine,
  RadioTower,
  RefreshCcw,
  Send,
  ShieldCheck,
  Sparkles,
  Truck,
  Users,
} from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type DashboardTab = "shipments" | "status_ops" | "clients" | "carriers";

interface OverviewResponse {
  counts: {
    clients: number;
    carriers: number;
    email_threads: number;
    email_messages: number;
    shipments: number;
    bids: number;
    workflow_events: number;
  };
  active_stages: Record<string, number>;
  status_metrics: {
    lookups: number;
    replies_drafted: number;
    replies_sent: number;
    carrier_updates_parsed: number;
    carrier_updates_pushed: number;
    review_required: number;
    stale_shipments: number;
  };
  sla: {
    status_stale_after_hours: number;
  };
  integrations: Record<string, string>;
}

interface ClientRecord {
  id: string;
  name: string;
  email: string;
  is_active: boolean;
  default_margin_percent: number;
  default_margin_floor: number;
  created_at: string;
  updated_at: string;
}

interface CarrierRecord {
  id: string;
  name: string;
  email: string;
  rating: number;
  is_active: boolean;
  regions: string[];
  equipment: string[];
  metadata: Record<string, string>;
  created_at: string;
  updated_at: string;
}

interface ShipmentRecord {
  id: string;
  client_id: string | null;
  email_thread_id: string | null;
  status: string;
  quote_token: string | null;
  origin: string | null;
  destination: string | null;
  pallets: number | null;
  weight_lb: number | null;
  equipment_type: string | null;
  ready_at: string | null;
  ready_at_local: string | null;
  ready_at_display: string | null;
  delivery_at: string | null;
  delivery_at_local: string | null;
  delivery_at_display: string | null;
  delivery_at_timezone: string | null;
  delivery_at_offset_minutes: number | null;
  margin_policy: Record<string, number>;
  notes: string;
  ai_intent: string | null;
  ai_confidence: number | null;
  ai_missing_fields: string[];
  ai_ambiguity_reasons: string[];
  ai_next_action: string | null;
  booking_state: string | null;
  booking_error: string | null;
  tms_handoff_status: string | null;
  attachment_count: number;
  document_summary: Record<string, number>;
  document_enrichment: Record<string, string | number>;
  document_health_status: string | null;
  ocr_pending_count: number;
  document_conflict_count: number;
  missing_document_types: string[];
  booking_review_warning: string | null;
  booking_review_required: boolean;
  last_known_status: string | null;
  last_known_eta: string | null;
  last_known_location: string | null;
  last_status_source: string | null;
  last_status_event_at: string | null;
  tms_load_id: string | null;
  tms_system: string | null;
  status_workflow_state: string | null;
  status_sync_health: string | null;
  status_review_required: boolean;
  status_stale: boolean;
  status_sla_hours: number | null;
  manual_review_required: boolean;
  created_at: string;
  updated_at: string;
}

interface WorkflowEventRecord {
  id: string;
  shipment_id: string;
  event_type: string;
  stage: string;
  payload: Record<string, unknown>;
  created_at: string;
}

interface ShipmentDocumentRecord {
  id: string | null;
  name: string | null;
  document_type: string;
  content_type: string | null;
  size: number | null;
  extracted_text_preview: string | null;
  extracted_fields: Record<string, string | number>;
  extraction_method: string | null;
  ocr_status: string | null;
  ocr_confidence: number | null;
  field_confidence: number | null;
  review_required: boolean;
  review_reason: string | null;
  source_email_id: string;
}

interface BidRecord {
  id: string;
  shipment_id: string;
  carrier_id: string;
  carrier_name: string;
  carrier_email: string;
  amount: number | null;
  currency: string;
  eta_text: string | null;
  status: string;
  score: Record<string, number>;
  received_at: string;
}

interface OutreachResponse {
  shipment_id: string;
  thread_id: string;
  quote_token: string;
  subject: string;
  body: string;
  dry_run: boolean;
  targeted: number;
  created_bids: number;
}

interface EvaluationResponse {
  shipment_id: string;
  selected_bid_id: string;
  selected_carrier_id: string;
  selected_amount: number;
  recommended_quote_amount: number;
  margin_amount: number;
  results: BidRecord[];
}

interface ClientAcknowledgementResponse {
  shipment_id: string;
  client_email: string;
  subject: string;
  body: string;
  dry_run: boolean;
}

interface OutlookIngestResult {
  thread_id: string;
  email_message_id: string;
  shipment_id: string;
  client_id: string | null;
  created_thread: boolean;
  created_message: boolean;
  created_shipment: boolean;
  created_client: boolean;
  acknowledgement_drafted: boolean;
  acknowledgement_subject: string | null;
  outreach_drafted: boolean;
  outreach_subject: string | null;
  outreach_targeted: number;
  bid_intaken: boolean;
  bid_id: string | null;
  bid_amount: number | null;
  intent: string | null;
  confidence: number | null;
  shipment_extracted: boolean;
  missing_fields: string[];
  ambiguity_reasons: string[];
  manual_review_required: boolean;
  next_action: string | null;
  evaluation_triggered: boolean;
  quote_auto_sent: boolean;
  status_lookup_triggered: boolean;
  status_reply_sent: boolean;
  tms_status_updated: boolean;
  event_type: string;
}

interface OutlookSyncResponse {
  imported: number;
  skipped: number;
  parsed_shipments: number;
  auto_acknowledgements: number;
  auto_outreach: number;
  auto_bids: number;
  auto_evaluations: number;
  auto_quotes: number;
  auto_status_replies: number;
  auto_tms_status_updates: number;
  manual_reviews: number;
  results: OutlookIngestResult[];
}

interface ReviewQueueItem {
  workflow_event_id: string;
  shipment_id: string;
  stage: string;
  event_type: string;
  review_type: string | null;
  priority: string;
  alert_label: string | null;
  reason: string;
  next_action: string | null;
  missing_fields: string[];
  ambiguity_reasons: string[];
  missing_document_types: string[];
  document_conflict_fields: string[];
  booking_review_warning: string | null;
  status_stale: boolean;
  status_review_required: boolean;
  created_at: string;
}

type StatusQueueAction =
  | "preview"
  | "approve_and_send"
  | "approve_and_push"
  | "rebuild_draft"
  | "retry_push"
  | "dismiss";

interface StatusQueueItem {
  task_id: string;
  task_type: string;
  task_state: string;
  queue_scope: string;
  resolution_state: string | null;
  resolution_reason: string | null;
  resolution_at: string | null;
  shipment_id: string;
  email_thread_id: string | null;
  source_email_id: string | null;
  priority: string;
  alert_label: string | null;
  reason: string;
  recommended_next_action: string | null;
  review_type: string | null;
  ambiguity_reasons: string[];
  latest_status_snapshot: Record<string, unknown>;
  draft_subject: string | null;
  draft_body: string | null;
  structured_payload: Record<string, unknown>;
  last_failure: string | null;
  tms_load_id: string | null;
  tms_system: string | null;
  status_sync_health: string | null;
  created_at: string;
}

interface StatusQueueActionResponse {
  task_id: string;
  task_type: string;
  action: StatusQueueAction;
  status: string;
  message: string;
  task_state: string;
  resolution_state: string | null;
  resolution_reason: string | null;
  shipment_id: string;
  preview: Record<string, unknown>;
}

type OperatorAction =
  | "resume_workflow"
  | "approve_and_continue"
  | "rerun_parsing"
  | "rerun_outreach"
  | "rerun_evaluation"
  | "rerun_status_lookup"
  | "rerun_tms_update"
  | "approve_status_reply"
  | "rerun_document_extraction"
  | "approve_document_values"
  | "ignore_document_warning";

interface ShipmentOperatorActionResponse {
  shipment_id: string;
  action: OperatorAction;
  status: string;
  message: string;
  next_action: string;
  manual_review_required: boolean;
  acknowledgement_sent: boolean;
  outreach_sent: boolean;
  evaluation_triggered: boolean;
  quote_sent: boolean;
}

interface CustomerStatusReplyResponse {
  shipment_id: string;
  client_email: string;
  subject: string;
  body: string;
  dry_run: boolean;
}

interface CarrierStatusUpdateResponse {
  shipment_id: string;
  status: string;
  dry_run: boolean;
  status_text: string | null;
  eta_text: string | null;
  location_text: string | null;
  notes: string | null;
  payload: Record<string, unknown>;
}

interface CustomerQuoteResponse {
  shipment_id: string;
  bid_id: string;
  client_email: string;
  subject: string;
  body: string;
  base_amount: number;
  margin_amount: number;
  final_amount: number;
  dry_run: boolean;
}

interface TmsHandoffResponse {
  shipment_id: string;
  bid_id: string;
  status: string;
  dry_run: boolean;
  payload: Record<string, unknown>;
  response: Record<string, unknown>;
}

interface BookingExecutionResponse {
  shipment_id: string;
  dry_run: boolean;
  handoff: TmsHandoffResponse;
  confirmation: {
    shipment_id: string;
    client_email: string;
    subject: string;
    body: string;
    dry_run: boolean;
  };
}

const SHIPMENT_STATUS_STYLES: Record<string, string> = {
  received: "bg-sky-400/15 text-sky-200 border-sky-300/20",
  parsing: "bg-teal-400/15 text-teal-200 border-teal-300/20",
  client_acknowledged: "bg-violet-400/15 text-violet-200 border-violet-300/20",
  outreaching: "bg-amber-400/15 text-amber-200 border-amber-300/20",
  waiting_bids: "bg-orange-400/15 text-orange-200 border-orange-300/20",
  evaluating: "bg-rose-400/15 text-rose-200 border-rose-300/20",
  quoted: "bg-emerald-400/15 text-emerald-200 border-emerald-300/20",
  awaiting_confirmation: "bg-fuchsia-400/15 text-fuchsia-200 border-fuchsia-300/20",
  booking_in_progress: "bg-lime-400/15 text-lime-100 border-lime-300/20",
  booking_failed: "bg-red-500/15 text-red-100 border-red-400/20",
  booked: "bg-lime-400/15 text-lime-200 border-lime-300/20",
  expired: "bg-slate-400/15 text-slate-300 border-slate-300/20",
  declined: "bg-red-400/15 text-red-200 border-red-300/20",
};

const EMPTY_OVERVIEW: OverviewResponse = {
  counts: {
    clients: 0,
    carriers: 0,
    email_threads: 0,
    email_messages: 0,
    shipments: 0,
    bids: 0,
    workflow_events: 0,
  },
  active_stages: {},
  status_metrics: {
    lookups: 0,
    replies_drafted: 0,
    replies_sent: 0,
    carrier_updates_parsed: 0,
    carrier_updates_pushed: 0,
    review_required: 0,
    stale_shipments: 0,
  },
  sla: {
    status_stale_after_hours: 24,
  },
  integrations: {},
};

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed: ${response.status}`);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

function formatDate(value: string | null) {
  if (!value) return "Not scheduled";
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatShipmentSchedule(displayValue: string | null, localValue: string | null) {
  const rawValue = displayValue
    ? displayValue.replace(/\s*\([^)]+\)\s*$/, "").trim()
    : localValue
      ? localValue.replace("T", " ").trim()
      : "";
  if (!rawValue) return "Not scheduled";
  const normalizedForParse = rawValue.includes("T") ? rawValue : rawValue.replace(" ", "T");
  const parsed = new Date(normalizedForParse);
  if (Number.isNaN(parsed.getTime())) return rawValue;
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).format(parsed);
}

function formatAge(value: string | null) {
  if (!value) return "No status activity yet";
  const diffMs = Date.now() - new Date(value).getTime();
  if (Number.isNaN(diffMs)) return "Unknown";
  const diffMinutes = Math.max(0, Math.round(diffMs / 60000));
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 48) return `${diffHours}h ago`;
  const diffDays = Math.round(diffHours / 24);
  return `${diffDays}d ago`;
}

function payloadValue(payload: Record<string, unknown>, ...keys: string[]) {
  for (const key of keys) {
    const value = payload[key];
    if (typeof value === "string" && value.length > 0) return value;
    if (typeof value === "number") return String(value);
  }
  const nestedPayload = payload.payload;
  if (nestedPayload && typeof nestedPayload === "object" && !Array.isArray(nestedPayload)) {
    const record = nestedPayload as Record<string, unknown>;
    for (const key of keys) {
      const value = record[key];
      if (typeof value === "string" && value.length > 0) return value;
      if (typeof value === "number") return String(value);
    }
  }
  const nestedResponse = payload.response;
  if (nestedResponse && typeof nestedResponse === "object" && !Array.isArray(nestedResponse)) {
    const record = nestedResponse as Record<string, unknown>;
    for (const key of keys) {
      const value = record[key];
      if (typeof value === "string" && value.length > 0) return value;
      if (typeof value === "number") return String(value);
    }
  }
  return "--";
}

function payloadInputValue(payload: Record<string, unknown>, key: string) {
  const value = payload[key];
  return typeof value === "string" ? value : "";
}

function statusAuditLabel(eventRecord: WorkflowEventRecord) {
  const auditKind = typeof eventRecord.payload.status_audit_kind === "string" ? eventRecord.payload.status_audit_kind : null;
  if (auditKind) {
    return auditKind.replaceAll("_", " ");
  }
  if (eventRecord.event_type === "tms_status_lookup") return "lookup";
  if (eventRecord.event_type === "customer_status_sent") {
    return eventRecord.payload.dry_run ? "reply drafted" : "reply sent";
  }
  if (eventRecord.event_type === "tms_status_updated") return "carrier update pushed";
  if (eventRecord.event_type === "tms_status_ingested") return "tms inbound sync";
  if (eventRecord.event_type === "status_workflow_resolved") {
    const resolutionReason = typeof eventRecord.payload.resolution_reason === "string" ? eventRecord.payload.resolution_reason : null;
    return resolutionReason ? resolutionReason.replaceAll("_", " ") : "status workflow resolved";
  }
  if (eventRecord.event_type === "manual_review_required") return "status review required";
  return eventRecord.event_type.replaceAll("_", " ");
}

function reviewPriorityClasses(priority: string) {
  if (priority === "critical") return "bg-rose-300/10 text-rose-100 border-rose-300/20";
  if (priority === "high") return "bg-amber-300/10 text-amber-100 border-amber-300/20";
  return "bg-white/10 text-white border-white/10";
}

function healthBadgeClasses(value: string | null) {
  if (value === "blocking") return "bg-rose-300/10 text-rose-100 border-rose-300/20";
  if (value === "review_required") return "bg-amber-300/10 text-amber-100 border-amber-300/20";
  if (value === "warning" || value === "warning_ignored") return "bg-cyan-300/10 text-cyan-100 border-cyan-300/20";
  return "bg-emerald-300/10 text-emerald-100 border-emerald-300/20";
}

function formatConfidence(value: number | null) {
  if (value === null || value === undefined) return "--";
  return `${Math.round(value * 100)}%`;
}

function ShipmentStatusPill({ status }: { status: string }) {
  return (
    <span
      className={`inline-flex rounded-full border px-3 py-1 text-xs font-medium capitalize ${
        SHIPMENT_STATUS_STYLES[status] || "bg-white/10 text-white border-white/10"
      }`}
    >
      {status.replaceAll("_", " ")}
    </span>
  );
}

type WorkspaceSection = "overview" | "bids" | "timeline" | "status" | "docs";

interface ShipmentEditorState {
  client_id: string;
  origin: string;
  destination: string;
  pallets: string;
  weight_lb: string;
  equipment_type: string;
  ready_at: string;
  delivery_at: string;
  notes: string;
}

interface ShipmentContextAction {
  key: string;
  label: string;
  tone?: "primary" | "neutral" | "success" | "warning";
  operatorAction?: OperatorAction;
  requiresSave?: boolean;
}

interface ShipmentActionModel {
  label: string | null;
  reason: string;
  blockingReason: string | null;
  operatorAction: OperatorAction | null;
  requiresSave: boolean;
  contextActions: ShipmentContextAction[];
}

function formatRoute(shipment: ShipmentRecord) {
  return `${shipment.origin || "Origin TBD"} -> ${shipment.destination || "Destination TBD"}`;
}

function formatNumber(value: number | null, suffix = "") {
  if (value === null || value === undefined) return "--";
  return `${value}${suffix}`;
}

function toDateTimeLocal(value: string | null) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value.slice(0, 16);
  }
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function buildShipmentEditor(shipment: ShipmentRecord | null): ShipmentEditorState {
  if (!shipment) {
    return {
      client_id: "",
      origin: "",
      destination: "",
      pallets: "",
      weight_lb: "",
      equipment_type: "",
      ready_at: "",
      delivery_at: "",
      notes: "",
    };
  }
  return {
    client_id: shipment.client_id || "",
    origin: shipment.origin || "",
    destination: shipment.destination || "",
    pallets: shipment.pallets?.toString() || "",
    weight_lb: shipment.weight_lb?.toString() || "",
    equipment_type: shipment.equipment_type || "",
    ready_at: toDateTimeLocal(shipment.ready_at_local),
    delivery_at: toDateTimeLocal(shipment.delivery_at_local),
    notes: shipment.notes || "",
  };
}

function shipmentHasMinimumFields(editor: ShipmentEditorState) {
  return Boolean(
    editor.origin.trim() &&
      editor.destination.trim() &&
      editor.pallets.trim() &&
      editor.weight_lb.trim() &&
      editor.equipment_type.trim() &&
      editor.ready_at.trim(),
  );
}

function shipmentNeedsAttention(shipment: ShipmentRecord) {
  return Boolean(
    shipment.manual_review_required ||
      shipment.ai_missing_fields.length > 0 ||
      shipment.ai_ambiguity_reasons.length > 0 ||
      shipment.status_review_required ||
      shipment.booking_review_required,
  );
}

function shipmentShowsDeliveryTime(shipment: ShipmentRecord | null) {
  if (!shipment) return false;
  return ["booking_in_progress", "booking_failed", "booked"].includes(shipment.status);
}

function shipmentBlockingBadge(shipment: ShipmentRecord) {
  if (shipment.ai_missing_fields.length > 0) return "Missing details";
  if (shipment.ai_ambiguity_reasons.length > 0) return "Ambiguous parse";
  if (shipment.manual_review_required) return "Needs review";
  if (shipment.booking_review_required) return "Docs warning";
  if (shipment.status_review_required) return "Status review";
  if (shipment.status_stale) return "Status stale";
  if (shipment.status === "waiting_bids") return "Waiting bids";
  return "Ready";
}

function deriveShipmentActionModel(
  shipment: ShipmentRecord,
  editor: ShipmentEditorState,
  activeStatusTasks: StatusQueueItem[],
  bidCount: number,
) : ShipmentActionModel {
  const hasMinimumFields = shipmentHasMinimumFields(editor);
  const statusReplyTask = activeStatusTasks.find((task) => task.task_type === "status_reply");
  const carrierUpdateTask = activeStatusTasks.find((task) => task.task_type === "carrier_update");

  const baseActions: ShipmentContextAction[] = [
    { key: "edit", label: "Edit details" },
    { key: "rerun_parsing", label: "Re-run parsing", operatorAction: "rerun_parsing" },
  ];

  if (shipment.status === "waiting_bids" || shipment.status === "outreaching") {
    baseActions.push({ key: "rerun_outreach", label: "Re-run outreach", operatorAction: "rerun_outreach" });
  }
  if (bidCount > 0) {
    baseActions.push({ key: "rerun_evaluation", label: "Re-run evaluation", operatorAction: "rerun_evaluation" });
  }
  if (shipment.status_stale || shipment.status_workflow_state) {
    baseActions.push({ key: "rerun_status_lookup", label: "Refresh status", operatorAction: "rerun_status_lookup" });
  }
  if (carrierUpdateTask) {
    baseActions.push({ key: "rerun_tms_update", label: "Re-run TMS update", operatorAction: "rerun_tms_update" });
  }
  if (statusReplyTask) {
    baseActions.push({ key: "approve_status_reply", label: "Preview status reply", operatorAction: "approve_status_reply" });
  }

  if (!hasMinimumFields) {
    return {
      label: null,
      reason: "This shipment is missing critical quote fields. Update the details first so automation knows what to send to carriers.",
      blockingReason: `Missing: ${["origin", "destination", "pallets", "weight_lb", "equipment_type", "ready_at"]
        .filter((field) => !editor[field as keyof ShipmentEditorState])
        .map((field) => field.replaceAll("_", " "))
        .join(", ")}`,
      operatorAction: null,
      requiresSave: false,
      contextActions: baseActions,
    };
  }

  if (shipment.status === "parsing" || shipment.status === "received" || shipment.status === "client_acknowledged") {
    return {
      label: "Approve and send outreach",
      reason: "The parsed shipment looks complete. Approving should save the current values and move the quote flow forward.",
      blockingReason: null,
      operatorAction: "approve_and_continue",
      requiresSave: true,
      contextActions: [
        { key: "approve_and_continue", label: "Approve parsed shipment", operatorAction: "approve_and_continue", requiresSave: true, tone: "success" },
        ...baseActions,
      ],
    };
  }

  if (shipment.status === "waiting_customer_details") {
    return {
      label: null,
      reason: "Automation is waiting for missing customer details. You can either fill them in here or send a clarification manually.",
      blockingReason: "Customer details still incomplete",
      operatorAction: null,
      requiresSave: false,
      contextActions: baseActions,
    };
  }

  if ((shipment.status === "waiting_bids" || shipment.status === "evaluating") && bidCount > 0) {
    return {
      label: "Approve and evaluate bids",
      reason: "Carrier responses are in. Evaluating now will pick the best option and prepare the next quote step.",
      blockingReason: null,
      operatorAction: "rerun_evaluation",
      requiresSave: false,
      contextActions: [
        { key: "rerun_evaluation", label: "Approve and evaluate", operatorAction: "rerun_evaluation", tone: "success" },
        ...baseActions,
      ],
    };
  }

  if (statusReplyTask) {
    return {
      label: "Approve and send status reply",
      reason: "A customer-facing status reply is waiting for operator approval.",
      blockingReason: null,
      operatorAction: "approve_status_reply",
      requiresSave: false,
      contextActions: [
        { key: "approve_status_reply", label: "Approve and send reply", operatorAction: "approve_status_reply", tone: "success" },
        ...baseActions,
      ],
    };
  }

  if (shipment.booking_review_required) {
    return {
      label: "Approve document values",
      reason: "Document extraction found a warning. Approve the extracted values before relying on booking data.",
      blockingReason: shipment.booking_review_warning,
      operatorAction: "approve_document_values",
      requiresSave: false,
      contextActions: [
        { key: "approve_document_values", label: "Approve document values", operatorAction: "approve_document_values", tone: "success" },
        { key: "ignore_document_warning", label: "Ignore warning", operatorAction: "ignore_document_warning", tone: "warning" },
        ...baseActions,
      ],
    };
  }

  if (shipment.status === "quoted" || shipment.status === "awaiting_confirmation") {
    return {
      label: "Continue workflow",
      reason: "The shipment is already in the customer quote / confirmation stage. Use secondary actions below if you want previews or booking tools.",
      blockingReason: null,
      operatorAction: "resume_workflow",
      requiresSave: false,
      contextActions: [
        { key: "resume_workflow", label: "Approve and continue workflow", operatorAction: "resume_workflow", tone: "primary" },
        ...baseActions,
      ],
    };
  }

  return {
    label: "Continue workflow",
    reason: "This shipment has no blocking review. Continuing workflow will ask the backend for the next safe step.",
    blockingReason: null,
    operatorAction: "resume_workflow",
    requiresSave: false,
    contextActions: [{ key: "resume_workflow", label: "Approve and continue workflow", operatorAction: "resume_workflow", tone: "primary" }, ...baseActions],
  };
}

function LegacyFreightDashboard() {
  const [tab, setTab] = useState<DashboardTab>("shipments");
  const [overview, setOverview] = useState<OverviewResponse>(EMPTY_OVERVIEW);
  const [clients, setClients] = useState<ClientRecord[]>([]);
  const [carriers, setCarriers] = useState<CarrierRecord[]>([]);
  const [shipments, setShipments] = useState<ShipmentRecord[]>([]);
  const [events, setEvents] = useState<WorkflowEventRecord[]>([]);
  const [bids, setBids] = useState<BidRecord[]>([]);
  const [reviewQueue, setReviewQueue] = useState<ReviewQueueItem[]>([]);
  const [statusQueue, setStatusQueue] = useState<StatusQueueItem[]>([]);
  const [statusQueueScope, setStatusQueueScope] = useState<"active" | "resolved">("active");
  const [documents, setDocuments] = useState<ShipmentDocumentRecord[]>([]);
  const [evaluation, setEvaluation] = useState<EvaluationResponse | null>(null);
  const [ackPreview, setAckPreview] = useState<ClientAcknowledgementResponse | null>(null);
  const [quotePreview, setQuotePreview] = useState<CustomerQuoteResponse | null>(null);
  const [statusReplyPreview, setStatusReplyPreview] = useState<CustomerStatusReplyResponse | null>(null);
  const [carrierStatusPreview, setCarrierStatusPreview] = useState<CarrierStatusUpdateResponse | null>(null);
  const [tmsPreview, setTmsPreview] = useState<TmsHandoffResponse | null>(null);
  const [bookingResult, setBookingResult] = useState<BookingExecutionResponse | null>(null);
  const [selectedShipmentId, setSelectedShipmentId] = useState<string | null>(null);
  const [selectedStatusTaskId, setSelectedStatusTaskId] = useState<string | null>(null);
  const [selectedClientId, setSelectedClientId] = useState<string | null>(null);
  const [selectedCarrierId, setSelectedCarrierId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [lastSyncSummary, setLastSyncSummary] = useState<OutlookSyncResponse | null>(null);

  const [clientForm, setClientForm] = useState({
    name: "",
    email: "",
    default_margin_percent: "15",
    default_margin_floor: "0",
  });
  const [carrierForm, setCarrierForm] = useState({
    name: "",
    email: "",
    rating: "0",
    regions: "midwest,northeast",
    equipment: "dry van",
  });
  const [shipmentForm, setShipmentForm] = useState({
    client_id: "",
    origin: "Chicago, IL",
    destination: "New York, NY",
    pallets: "5",
    weight_lb: "10000",
    equipment_type: "Dry Van",
    ready_at: "",
    delivery_at: "",
    margin_percent: "15",
    margin_floor: "0",
    notes: "Need pickup tomorrow 08:00.",
  });
  const [bidForm, setBidForm] = useState({
    carrier_id: "",
    amount: "1000",
    eta_text: "Tomorrow pickup / next-day delivery",
    raw_email: "Best rate we can do is 1000 all in.",
  });
  const [statusReplyMessage, setStatusReplyMessage] = useState("");
  const [statusReplyDraftSubject, setStatusReplyDraftSubject] = useState("");
  const [statusReplyDraftBody, setStatusReplyDraftBody] = useState("");
  const [carrierStatusForm, setCarrierStatusForm] = useState({
    status_text: "",
    eta_text: "",
    location_text: "",
    notes: "",
  });

  const selectedShipment = useMemo(
    () => shipments.find((shipment) => shipment.id === selectedShipmentId) || null,
    [shipments, selectedShipmentId],
  );
  const selectedClient = useMemo(
    () => clients.find((client) => client.id === selectedClientId) || null,
    [clients, selectedClientId],
  );
  const selectedCarrier = useMemo(
    () => carriers.find((carrier) => carrier.id === selectedCarrierId) || null,
    [carriers, selectedCarrierId],
  );
  const selectedWinningBid = useMemo(() => {
    const bidId = evaluation?.selected_bid_id;
    if (!bidId) return null;
    return bids.find((bid) => bid.id === bidId) || evaluation.results.find((bid) => bid.id === bidId) || null;
  }, [bids, evaluation]);
  const selectedStatusTask = useMemo(
    () => statusQueue.find((task) => task.task_id === selectedStatusTaskId) || null,
    [statusQueue, selectedStatusTaskId],
  );
  const filteredStatusQueue = useMemo(
    () => statusQueue.filter((task) => task.queue_scope === statusQueueScope),
    [statusQueue, statusQueueScope],
  );
  const statusEvents = useMemo(
    () =>
      events.filter((eventRecord) =>
        ["tms_status_lookup", "customer_status_sent", "tms_status_updated", "tms_status_ingested", "status_workflow_resolved"].includes(eventRecord.event_type) ||
        (eventRecord.event_type === "manual_review_required" &&
          typeof eventRecord.payload.review_type === "string" &&
          eventRecord.payload.review_type.includes("status")),
      ),
    [events],
  );

  async function loadDashboard() {
    setLoading(true);
    setError(null);
    try {
      const [overviewData, clientData, carrierData, shipmentData, reviewData, statusQueueData] = await Promise.all([
        fetchJson<OverviewResponse>("/api/freight/overview"),
        fetchJson<ClientRecord[]>("/api/freight/clients"),
        fetchJson<CarrierRecord[]>("/api/freight/carriers"),
        fetchJson<ShipmentRecord[]>("/api/freight/shipments"),
        fetchJson<ReviewQueueItem[]>("/api/freight/reviews"),
        fetchJson<StatusQueueItem[]>("/api/freight/status-queue?include_resolved=true"),
      ]);

      startTransition(() => {
        setOverview(overviewData);
        setClients(clientData);
        setCarriers(carrierData);
        setShipments(shipmentData);
        setReviewQueue(reviewData);
        setStatusQueue(statusQueueData);
        setSelectedShipmentId((current) =>
          current && shipmentData.some((shipment) => shipment.id === current)
            ? current
            : shipmentData[0]?.id || null,
        );
        setSelectedStatusTaskId((current) =>
          current && statusQueueData.some((task) => task.task_id === current)
            ? current
            : statusQueueData[0]?.task_id || null,
        );
        setSelectedClientId((current) =>
          current && clientData.some((client) => client.id === current)
            ? current
            : clientData[0]?.id || null,
        );
        setSelectedCarrierId((current) =>
          current && carrierData.some((carrier) => carrier.id === current)
            ? current
            : carrierData[0]?.id || null,
        );
        if (!bidForm.carrier_id && carrierData[0]) {
          setBidForm((current) => ({ ...current, carrier_id: carrierData[0].id }));
        }
      });
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load dashboard.");
    } finally {
      setLoading(false);
    }
  }

  async function loadShipmentContext(shipmentId: string) {
    const [eventData, bidData, documentData] = await Promise.all([
      fetchJson<WorkflowEventRecord[]>(`/api/freight/shipments/${shipmentId}/events`),
      fetchJson<BidRecord[]>(`/api/freight/shipments/${shipmentId}/bids`),
      fetchJson<ShipmentDocumentRecord[]>(`/api/freight/shipments/${shipmentId}/documents`),
    ]);
    setEvents(eventData);
    setBids(bidData);
    setDocuments(documentData);
  }

  const refetchShipmentDetailTypes = useMemo(
    () =>
      new Set([
        "bid_received",
        "evaluation_completed",
        "client_quote_sent",
        "carrier_outreach_sent",
        "document_analyzed",
        "document_values_approved",
        "document_warning_ignored",
        "manual_review_required",
        "tms_handoff_sent",
        "tms_status_ingested",
      ]),
    [],
  );

  useFreightSocket({
    onOverviewStale: () => {
      void loadDashboard();
    },
    onShipmentUpdated: (shipmentId) => {
      void loadDashboard();
      if (shipmentId === selectedShipmentId) {
        void loadShipmentContext(shipmentId);
      }
    },
    onWorkflowEvent: ({ shipment_id, event }) => {
      void loadDashboard();
      if (shipment_id === selectedShipmentId) {
        setEvents((prev) =>
          prev.some((e) => e.id === event.id) ? prev : [event as WorkflowEventRecord, ...prev],
        );
        if (refetchShipmentDetailTypes.has(event.event_type)) {
          void loadShipmentContext(shipment_id);
        }
      }
    },
  });

  useEffect(() => {
    void loadDashboard();
  }, []);

  useEffect(() => {
    if (!selectedShipmentId) {
      setEvents([]);
      setBids([]);
      setDocuments([]);
      setEvaluation(null);
      setAckPreview(null);
      setQuotePreview(null);
      setStatusReplyPreview(null);
      setCarrierStatusPreview(null);
      setTmsPreview(null);
      setBookingResult(null);
      return;
    }

    setEvaluation(null);
    setAckPreview(null);
    setQuotePreview(null);
    setStatusReplyPreview(null);
    setCarrierStatusPreview(null);
    setTmsPreview(null);
    setBookingResult(null);
    void loadShipmentContext(selectedShipmentId).catch(() => {
      setEvents([]);
      setBids([]);
      setDocuments([]);
    });
  }, [selectedShipmentId]);

  useEffect(() => {
    if (!selectedStatusTask) {
      setStatusReplyDraftSubject("");
      setStatusReplyDraftBody("");
      return;
    }
    setStatusReplyDraftSubject(selectedStatusTask.draft_subject || "");
    setStatusReplyDraftBody(selectedStatusTask.draft_body || "");
    if (selectedStatusTask.task_type === "carrier_update") {
      setCarrierStatusForm({
        status_text: payloadInputValue(selectedStatusTask.structured_payload, "status_text"),
        eta_text: payloadInputValue(selectedStatusTask.structured_payload, "eta_text"),
        location_text: payloadInputValue(selectedStatusTask.structured_payload, "location_text"),
        notes: payloadInputValue(selectedStatusTask.structured_payload, "notes"),
      });
    }
  }, [selectedStatusTask]);

  useEffect(() => {
    if (filteredStatusQueue.length === 0) {
      setSelectedStatusTaskId(null);
      return;
    }
    if (!selectedStatusTaskId || !filteredStatusQueue.some((task) => task.task_id === selectedStatusTaskId)) {
      setSelectedStatusTaskId(filteredStatusQueue[0]?.task_id || null);
    }
  }, [filteredStatusQueue, selectedStatusTaskId]);

  async function refreshAll() {
    await loadDashboard();
    if (selectedShipmentId) {
      await loadShipmentContext(selectedShipmentId);
    }
  }

  async function handleCreateClient(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting("client");
    setError(null);
    try {
      await fetchJson<ClientRecord>("/api/freight/clients", {
        method: "POST",
        body: JSON.stringify({
          name: clientForm.name,
          email: clientForm.email,
          is_active: true,
          default_margin_percent: Number(clientForm.default_margin_percent || 0),
          default_margin_floor: Number(clientForm.default_margin_floor || 0),
        }),
      });
      setClientForm({ name: "", email: "", default_margin_percent: "15", default_margin_floor: "0" });
      setNotice("Client added to the control tower.");
      await refreshAll();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to create client.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handleCreateCarrier(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting("carrier");
    setError(null);
    try {
      await fetchJson<CarrierRecord>("/api/freight/carriers", {
        method: "POST",
        body: JSON.stringify({
          name: carrierForm.name,
          email: carrierForm.email,
          rating: Number(carrierForm.rating || 0),
          is_active: true,
          regions: carrierForm.regions.split(",").map((value) => value.trim()).filter(Boolean),
          equipment: carrierForm.equipment.split(",").map((value) => value.trim()).filter(Boolean),
          metadata: {},
        }),
      });
      setCarrierForm({ name: "", email: "", rating: "0", regions: "midwest,northeast", equipment: "dry van" });
      setNotice("Carrier added and ready for outreach.");
      await refreshAll();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to create carrier.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handleCreateShipment(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting("shipment");
    setError(null);
    try {
      await fetchJson<ShipmentRecord>("/api/freight/shipments", {
        method: "POST",
        body: JSON.stringify({
          client_id: shipmentForm.client_id || null,
          status: "received",
          origin: shipmentForm.origin,
          destination: shipmentForm.destination,
          pallets: Number(shipmentForm.pallets || 0),
          weight_lb: Number(shipmentForm.weight_lb || 0),
          equipment_type: shipmentForm.equipment_type,
          ready_at_local: shipmentForm.ready_at || null,
          delivery_at_local: shipmentForm.delivery_at || null,
          margin_policy: {
            percent: Number(shipmentForm.margin_percent || 0),
            floor_amount: Number(shipmentForm.margin_floor || 0),
          },
          notes: shipmentForm.notes,
        }),
      });
      setNotice("Shipment staged for pricing workflow.");
      await refreshAll();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to create shipment.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handleDryRunOutreach() {
    if (!selectedShipment) return;
    setSubmitting("outreach");
    setError(null);
    try {
      const response = await fetchJson<OutreachResponse>(`/api/freight/shipments/${selectedShipment.id}/outreach`, {
        method: "POST",
        body: JSON.stringify({ dry_run: true, carrier_ids: [] }),
      });
      setNotice(`Dry run prepared ${response.created_bids} outreach drafts for ${response.targeted} carriers.`);
      await refreshAll();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to prepare outreach.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handleIntakeBid(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedShipment) return;
    setSubmitting("bid");
    setError(null);
    try {
      await fetchJson("/api/freight/bids/intake", {
        method: "POST",
        body: JSON.stringify({
          shipment_id: selectedShipment.id,
          carrier_id: bidForm.carrier_id,
          amount: Number(bidForm.amount || 0),
          currency: "USD",
          eta_text: bidForm.eta_text,
          raw_email: bidForm.raw_email,
          subject: selectedShipment.quote_token ? `Re: Quote reply [${selectedShipment.quote_token}]` : "Carrier bid response",
        }),
      });
      setNotice("Bid captured and attached to the shipment.");
      await refreshAll();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to intake bid.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handleEvaluateBids() {
    if (!selectedShipment) return;
    setSubmitting("evaluate");
    setError(null);
    try {
      const response = await fetchJson<EvaluationResponse>(`/api/freight/shipments/${selectedShipment.id}/evaluate`, { method: "POST" });
      setEvaluation(response);
      setNotice(`Best option selected at $${response.selected_amount.toFixed(2)}; recommended customer quote is $${response.recommended_quote_amount.toFixed(2)}.`);
      await refreshAll();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to evaluate bids.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handlePreviewAcknowledgement() {
    if (!selectedShipment) return;
    setSubmitting("ack");
    setError(null);
    try {
      const response = await fetchJson<ClientAcknowledgementResponse>(
        `/api/freight/shipments/${selectedShipment.id}/acknowledge`,
        {
          method: "POST",
          body: JSON.stringify({ dry_run: true }),
        },
      );
      setAckPreview(response);
      setNotice(`Customer acknowledgment prepared for ${response.client_email}.`);
      await refreshAll();
    } catch (submitError) {
      setError(
        submitError instanceof Error
          ? submitError.message
          : "Failed to prepare customer acknowledgment.",
      );
    } finally {
      setSubmitting(null);
    }
  }

  async function handleOutlookSync() {
    setSubmitting("sync");
    setError(null);
    try {
      const response = await fetchJson<OutlookSyncResponse>("/api/freight/outlook/sync", {
        method: "POST",
        body: JSON.stringify({
          limit: 10,
          auto_acknowledge_new_shipments: true,
          acknowledgement_dry_run: false,
          auto_prepare_outreach_for_new_shipments: true,
          outreach_dry_run: false,
          auto_send_customer_quotes: true,
          customer_quote_dry_run: false,
        }),
      });
      setNotice(
        `Outlook sync imported ${response.imported} thread(s), skipped ${response.skipped}, parsed ${response.parsed_shipments} shipment(s), sent ${response.auto_acknowledgements} acknowledgment(s), sent ${response.auto_outreach} outreach flow(s), captured ${response.auto_bids} bid(s), triggered ${response.auto_evaluations} evaluation(s), sent ${response.auto_quotes} quote(s), sent ${response.auto_status_replies} status update(s), pushed ${response.auto_tms_status_updates} carrier update(s) to TMS, and flagged ${response.manual_reviews} review item(s).`,
      );
      setLastSyncSummary(response);
      await refreshAll();
    } catch (submitError) {
      setError(
        submitError instanceof Error ? submitError.message : "Failed to sync Outlook inbox.",
      );
    } finally {
      setSubmitting(null);
    }
  }

  async function handlePreviewCustomerQuote() {
    if (!selectedShipment) return;
    setSubmitting("quote");
    setError(null);
    try {
      const response = await fetchJson<CustomerQuoteResponse>(`/api/freight/shipments/${selectedShipment.id}/quote`, {
        method: "POST",
        body: JSON.stringify({ bid_id: evaluation?.selected_bid_id || selectedWinningBid?.id || null, dry_run: true }),
      });
      setQuotePreview(response);
      setNotice(`Customer quote preview ready at $${response.final_amount.toFixed(2)}.`);
      await refreshAll();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to preview customer quote.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handlePreviewStatusReply() {
    if (!selectedShipment) return;
    setSubmitting("status_preview");
    setError(null);
    try {
      const response = await fetchJson<CustomerStatusReplyResponse>(
        `/api/freight/shipments/${selectedShipment.id}/status-reply`,
        {
          method: "POST",
          body: JSON.stringify({ dry_run: true, custom_message: statusReplyMessage || null }),
        },
      );
      setStatusReplyPreview(response);
      setNotice(`Status reply draft prepared for ${response.client_email}.`);
      await refreshAll();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to preview status reply.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handleSendStatusReply() {
    if (!selectedShipment) return;
    setSubmitting("status_send");
    setError(null);
    try {
      const response = await fetchJson<CustomerStatusReplyResponse>(
        `/api/freight/shipments/${selectedShipment.id}/status-reply`,
        {
          method: "POST",
          body: JSON.stringify({ dry_run: false, custom_message: statusReplyMessage || null }),
        },
      );
      setStatusReplyPreview(response);
      setNotice(`Status reply sent to ${response.client_email}.`);
      await refreshAll();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to send status reply.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handlePreviewCarrierStatusUpdate() {
    if (!selectedShipment) return;
    setSubmitting("carrier_status_preview");
    setError(null);
    try {
      const response = await fetchJson<CarrierStatusUpdateResponse>(
        `/api/freight/shipments/${selectedShipment.id}/carrier-status-update`,
        {
          method: "POST",
          body: JSON.stringify({
            dry_run: true,
            status_text: carrierStatusForm.status_text || null,
            eta_text: carrierStatusForm.eta_text || null,
            location_text: carrierStatusForm.location_text || null,
            notes: carrierStatusForm.notes || null,
          }),
        },
      );
      setCarrierStatusPreview(response);
      setCarrierStatusForm({
        status_text: response.status_text || "",
        eta_text: response.eta_text || "",
        location_text: response.location_text || "",
        notes: response.notes || "",
      });
      setNotice("Carrier status update draft prepared.");
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to preview carrier status update.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handleSendCarrierStatusUpdate() {
    if (!selectedShipment) return;
    setSubmitting("carrier_status_send");
    setError(null);
    try {
      const response = await fetchJson<CarrierStatusUpdateResponse>(
        `/api/freight/shipments/${selectedShipment.id}/carrier-status-update`,
        {
          method: "POST",
          body: JSON.stringify({
            dry_run: false,
            status_text: carrierStatusForm.status_text || null,
            eta_text: carrierStatusForm.eta_text || null,
            location_text: carrierStatusForm.location_text || null,
            notes: carrierStatusForm.notes || null,
          }),
        },
      );
      setCarrierStatusPreview(response);
      setNotice("Carrier status update sent to TMS.");
      await refreshAll();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to send carrier status update.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handlePreviewTmsHandoff() {
    if (!selectedShipment) return;
    setSubmitting("tms");
    setError(null);
    try {
      const response = await fetchJson<TmsHandoffResponse>(`/api/freight/shipments/${selectedShipment.id}/tms-handoff`, {
        method: "POST",
        body: JSON.stringify({ bid_id: evaluation?.selected_bid_id || selectedWinningBid?.id || null, dry_run: true }),
      });
      setTmsPreview(response);
      setNotice("TMS handoff payload prepared.");
      await refreshAll();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to preview TMS handoff.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handleBookShipment() {
    if (!selectedShipment) return;
    setSubmitting("book");
    setError(null);
    try {
      const response = await fetchJson<BookingExecutionResponse>(`/api/freight/shipments/${selectedShipment.id}/book`, {
        method: "POST",
        body: JSON.stringify({ bid_id: evaluation?.selected_bid_id || selectedWinningBid?.id || null, dry_run: false }),
      });
      setBookingResult(response);
      setNotice(`Load booked in TMS and confirmation sent to ${response.confirmation.client_email}.`);
      await refreshAll();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to book shipment.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handleOperatorAction(action: OperatorAction, shipmentId?: string) {
    const targetShipmentId = shipmentId || selectedShipment?.id;
    if (!targetShipmentId) return;
    setSubmitting(action);
    setError(null);
    try {
      const response = await fetchJson<ShipmentOperatorActionResponse>(
        `/api/freight/shipments/${targetShipmentId}/operator-action`,
        {
          method: "POST",
          body: JSON.stringify({ action }),
        },
      );
      setNotice(response.message);
      setSelectedShipmentId(targetShipmentId);
      await refreshAll();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to run operator action.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handleStatusQueueAction(action: StatusQueueAction) {
    if (!selectedStatusTask) return;
    setSubmitting(`status-queue-${action}`);
    setError(null);
    try {
      const response = await fetchJson<StatusQueueActionResponse>(`/api/freight/status-queue/${selectedStatusTask.task_id}/action`, {
        method: "POST",
        body: JSON.stringify({
          action,
          custom_message: statusReplyMessage || null,
          draft_subject: statusReplyDraftSubject || null,
          draft_body: statusReplyDraftBody || null,
          status_text: carrierStatusForm.status_text || null,
          eta_text: carrierStatusForm.eta_text || null,
          location_text: carrierStatusForm.location_text || null,
          notes: carrierStatusForm.notes || null,
        }),
      });
      setNotice(response.message);
      await refreshAll();
      if (response.shipment_id) {
        setSelectedShipmentId(response.shipment_id);
      }
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to run status queue action.");
    } finally {
      setSubmitting(null);
    }
  }

  const metrics = [
    {
      label: "Need attention",
      value: reviewQueue.length + overview.status_metrics.review_required,
      detail: `${reviewQueue.length} review items total`,
      icon: Package2,
      accent: "from-rose-300/20 to-rose-500/5",
    },
    {
      label: "Active shipments",
      value: overview.counts.shipments,
      detail: `${overview.counts.workflow_events} workflow events`,
      icon: Truck,
      accent: "from-cyan-300/20 to-cyan-500/5",
    },
    {
      label: "Inbox traffic",
      value: overview.counts.email_messages,
      detail: `${overview.counts.email_threads} synced threads`,
      icon: Mail,
      accent: "from-slate-300/20 to-slate-500/5",
    },
    {
      label: "Status health",
      value: overview.status_metrics.stale_shipments,
      detail: `${overview.status_metrics.lookups} lookups, ${overview.status_metrics.replies_sent} replies sent`,
      icon: RadioTower,
      accent: "from-emerald-300/20 to-emerald-500/5",
    },
  ];

  const stageHighlights = Object.entries(overview.active_stages).slice(0, 4);
  const criticalReviewCount = reviewQueue.filter((item) => item.priority === "critical").length;
  const highPriorityReviewCount = reviewQueue.filter((item) => item.priority === "high").length;

  return (
    <main className="min-h-screen px-4 py-5 text-[var(--text-main)] sm:px-6 lg:px-8">
      <div className="mx-auto max-w-[1480px] space-y-6">
        <section className="glass-panel overflow-hidden px-5 py-5 sm:px-6">
          <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
            <div className="max-w-3xl space-y-4">
              <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs uppercase tracking-[0.2em] text-[var(--text-muted)]">
                <DashboardLogo className="h-4 w-4 shrink-0 text-white/85" />
                Logistic Copilot
              </div>
              <div className="space-y-3">
                <h1 className="max-w-3xl text-3xl font-semibold tracking-[-0.04em] text-white sm:text-4xl">
                  Simple freight inbox dashboard.
                </h1>
                <p className="max-w-2xl text-sm leading-6 text-[var(--text-muted)] sm:text-base">
                  Start with what needs attention, open one shipment, and see what the system already did and what should happen next.
                </p>
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-2 xl:min-w-[520px]">
              {metrics.map(({ label, value, detail, icon: Icon, accent }) => (
                <div key={label} className={`rounded-[24px] border border-white/10 bg-gradient-to-br ${accent} p-4`}>
                  <div className="mb-6 flex items-center justify-between">
                    <span className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">{label}</span>
                    <Icon size={18} className="text-white/80" />
                  </div>
                  <div className="space-y-1">
                    <div className="text-3xl font-semibold text-white">{value}</div>
                    <div className="text-xs leading-5 text-[var(--text-muted)]">{detail}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="mt-5 flex flex-wrap items-center gap-2">
            {stageHighlights.map(([stage, count]) => (
              <div key={stage} className="rounded-full border border-white/10 bg-white/5 px-3 py-2 text-xs text-[var(--text-muted)]">
                <span className="mr-2 font-medium text-white">{count}</span>
                {stage.replaceAll("_", " ")}
              </div>
            ))}
            <div className="rounded-full border border-cyan-300/15 bg-cyan-300/10 px-3 py-2 text-xs text-cyan-100">
              Mailbox: {overview.integrations.email_provider || "outlook"}
            </div>
          </div>
        </section>

        {error && <div className="glass-panel-strong border-red-400/20 px-5 py-4 text-sm text-red-100">{error}</div>}
        {notice && <div className="glass-panel-strong border-cyan-400/20 px-5 py-4 text-sm text-cyan-100">{notice}</div>}

        <section className="space-y-6">
          <aside className="glass-panel p-4">
            <div className="mb-4 px-2">
              <p className="text-xs uppercase tracking-[0.2em] text-[var(--text-muted)]">Navigation</p>
              <p className="mt-2 text-lg font-medium text-white">Choose what to work on</p>
            </div>
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
              {[
                { key: "shipments", label: "Shipments", icon: Package2 },
                { key: "status_ops", label: "Status Ops", icon: RadioTower },
                { key: "clients", label: "Clients", icon: Users },
                { key: "carriers", label: "Carriers", icon: Truck },
              ].map(({ key, label, icon: Icon }) => {
                const active = tab === key;
                return (
                  <button
                    key={key}
                    onClick={() => setTab(key as DashboardTab)}
                    className={`flex w-full items-center justify-between rounded-2xl px-4 py-3 text-left transition ${active ? "bg-white text-slate-950" : "bg-white/5 text-[var(--text-muted)] hover:bg-white/10 hover:text-white"}`}
                  >
                    <span className="flex items-center gap-3 font-medium"><Icon size={18} />{label}</span>
                    <ArrowRight size={16} />
                  </button>
                );
              })}
            </div>

            <div className="mt-6 grid gap-3 sm:grid-cols-3">
              <div className="rounded-[24px] border border-white/10 bg-slate-950/40 p-4 text-sm text-[var(--text-muted)]">
                <div className="flex items-center justify-between"><span>Inbox sync</span><ShieldCheck size={16} className="text-cyan-200" /></div>
                <p className="mt-2 text-white">Ready</p>
              </div>
              <div className="rounded-[24px] border border-white/10 bg-slate-950/40 p-4 text-sm text-[var(--text-muted)]">
                <div className="flex items-center justify-between"><span>Carrier outreach</span><Send size={16} className="text-amber-200" /></div>
                <p className="mt-2 text-white">Configured</p>
              </div>
              <div className="rounded-[24px] border border-white/10 bg-slate-950/40 p-4 text-sm text-[var(--text-muted)]">
                <div className="flex items-center justify-between"><span>Bid evaluation</span><Sparkles size={16} className="text-rose-200" /></div>
                <p className="mt-2 text-white">Available</p>
              </div>
            </div>
          </aside>

          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr),390px]">
          <section className="space-y-6">
            {loading ? (
              <div className="glass-panel flex min-h-[520px] items-center justify-center p-8">
                <div className="flex items-center gap-3 text-[var(--text-muted)]"><Loader2 className="animate-spin" size={18} />Loading freight control tower...</div>
              </div>
            ) : (
              <>
                {tab === "shipments" && (
                  <div className="glass-panel overflow-hidden">
                    <div className="flex items-center justify-between border-b border-white/10 px-6 py-5">
                      <div>
                        <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Live board</p>
                        <h2 className="mt-1 text-2xl font-semibold text-white">Shipment lanes</h2>
                      </div>
                      <div className="flex items-center gap-3">
                        <button onClick={() => void handleOutlookSync()} disabled={submitting === "sync"} className="action-button bg-cyan-300/15 text-cyan-100 hover:bg-cyan-300/20 disabled:opacity-50">{submitting === "sync" ? "Syncing..." : "Sync Outlook"}</button>
                        <button onClick={() => void refreshAll()} className="action-button bg-white/10 text-sm text-white hover:bg-white/15">Refresh</button>
                      </div>
                    </div>
                    <div className="grid gap-3 p-4">
                      {shipments.length === 0 && <div className="rounded-[24px] border border-dashed border-white/10 bg-white/5 p-8 text-sm text-[var(--text-muted)] lg:col-span-2">No shipments yet. Seed one from the form to start the quoting workflow.</div>}
                      {shipments.map((shipment) => (
                        <button
                          key={shipment.id}
                          onClick={() => setSelectedShipmentId(shipment.id)}
                          className={`rounded-[24px] border p-5 text-left transition ${shipment.id === selectedShipmentId ? "border-cyan-300/40 bg-cyan-300/10" : "border-white/10 bg-white/5 hover:bg-white/10"}`}
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <p className="text-lg font-medium text-white">{shipment.origin || "Origin TBD"} <ArrowRight className="mx-1 inline" size={16} /> {shipment.destination || "Destination TBD"}</p>
                              <p className="mt-1 text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">{shipment.quote_token || "Quote token pending"}</p>
                            </div>
                            <ShipmentStatusPill status={shipment.status} />
                          </div>
                          <div className="mt-5 grid gap-3 sm:grid-cols-3">
                            <div><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Pallets</p><p className="mt-1 text-base font-medium text-white">{shipment.pallets ?? "--"}</p></div>
                            <div><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Weight</p><p className="mt-1 text-base font-medium text-white">{shipment.weight_lb ?? "--"} lb</p></div>
                            <div><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Ready</p><p className="mt-1 text-base font-medium text-white">{formatShipmentSchedule(shipment.ready_at_display, shipment.ready_at_local)}</p></div>
                          </div>
                          {(shipment.status_stale || shipment.status_review_required) && (
                            <div className="mt-4 flex flex-wrap gap-2">
                              {shipment.status_stale && (
                                <span className="rounded-full bg-amber-300/10 px-3 py-1 text-xs text-amber-100">
                                  Status stale over {shipment.status_sla_hours || overview.sla.status_stale_after_hours}h
                                </span>
                              )}
                              {shipment.status_review_required && (
                                <span className="rounded-full bg-cyan-300/10 px-3 py-1 text-xs text-cyan-100">
                                  Status review required
                                </span>
                              )}
                            </div>
                          )}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {tab === "clients" && (
                  <div className="glass-panel overflow-hidden">
                    <div className="border-b border-white/10 px-6 py-5">
                      <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Account book</p>
                      <h2 className="mt-1 text-2xl font-semibold text-white">Client margins and accounts</h2>
                    </div>
                    <div className="grid gap-4 p-4 md:grid-cols-2">
                      {clients.map((client) => (
                        <button
                          key={client.id}
                          onClick={() => setSelectedClientId(client.id)}
                          className={`rounded-[24px] border p-5 text-left transition ${client.id === selectedClientId ? "border-cyan-300/40 bg-cyan-300/10" : "border-white/10 bg-white/5 hover:bg-white/10"}`}
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <p className="text-lg font-medium text-white">{client.name}</p>
                              <p className="mt-1 text-sm text-[var(--text-muted)]">{client.email}</p>
                            </div>
                            <span className="rounded-full bg-white/10 px-3 py-1 text-xs text-white">{client.default_margin_percent}%</span>
                          </div>
                          <div className="mt-4 text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Margin floor ${client.default_margin_floor}</div>
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {tab === "carriers" && (
                  <div className="glass-panel overflow-hidden">
                    <div className="border-b border-white/10 px-6 py-5">
                      <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Network</p>
                      <h2 className="mt-1 text-2xl font-semibold text-white">Carrier network</h2>
                    </div>
                    <div className="grid gap-4 p-4 md:grid-cols-2">
                      {carriers.map((carrier) => (
                        <button
                          key={carrier.id}
                          onClick={() => setSelectedCarrierId(carrier.id)}
                          className={`rounded-[24px] border p-5 text-left transition ${carrier.id === selectedCarrierId ? "border-cyan-300/40 bg-cyan-300/10" : "border-white/10 bg-white/5 hover:bg-white/10"}`}
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <p className="text-lg font-medium text-white">{carrier.name}</p>
                              <p className="mt-1 text-sm text-[var(--text-muted)]">{carrier.email}</p>
                            </div>
                            <span className="rounded-full bg-white/10 px-3 py-1 text-xs text-white">Rating {carrier.rating}</span>
                          </div>
                          <div className="mt-4 flex flex-wrap gap-2">
                            {carrier.regions.slice(0, 3).map((region) => <span key={region} className="rounded-full bg-white/10 px-3 py-1 text-xs text-[var(--text-muted)]">{region}</span>)}
                            {carrier.equipment.slice(0, 2).map((equipment) => <span key={equipment} className="rounded-full bg-cyan-300/10 px-3 py-1 text-xs text-cyan-100">{equipment}</span>)}
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {tab === "status_ops" && (
                  <div className="glass-panel overflow-hidden">
                    <div className="flex items-center justify-between border-b border-white/10 px-6 py-5">
                      <div>
                        <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Operator queue</p>
                        <h2 className="mt-1 text-2xl font-semibold text-white">Status tasks</h2>
                      </div>
                      <button onClick={() => void refreshAll()} className="action-button bg-white/10 text-sm text-white hover:bg-white/15">Refresh</button>
                    </div>
                    <div className="grid gap-3 p-4">
                      <div className="lg:col-span-2 flex gap-2">
                        <button onClick={() => setStatusQueueScope("active")} className={`action-button ${statusQueueScope === "active" ? "bg-cyan-300/15 text-cyan-100" : "bg-white/5 text-[var(--text-muted)] hover:bg-white/10"}`}>Active</button>
                        <button onClick={() => setStatusQueueScope("resolved")} className={`action-button ${statusQueueScope === "resolved" ? "bg-cyan-300/15 text-cyan-100" : "bg-white/5 text-[var(--text-muted)] hover:bg-white/10"}`}>Recent resolved</button>
                      </div>
                      {filteredStatusQueue.length === 0 && <div className="rounded-[24px] border border-dashed border-white/10 bg-white/5 p-8 text-sm text-[var(--text-muted)] lg:col-span-2">No {statusQueueScope === "active" ? "active" : "resolved"} status tasks in this view yet.</div>}
                      {filteredStatusQueue.map((task) => (
                        <button
                          key={task.task_id}
                          onClick={() => {
                            setSelectedStatusTaskId(task.task_id);
                            setSelectedShipmentId(task.shipment_id);
                          }}
                          className={`rounded-[24px] border p-5 text-left transition ${task.task_id === selectedStatusTaskId ? "border-cyan-300/40 bg-cyan-300/10" : "border-white/10 bg-white/5 hover:bg-white/10"}`}
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <p className="text-lg font-medium text-white">{task.task_type.replaceAll("_", " ")}</p>
                              <p className="mt-1 text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">{task.task_state.replaceAll("_", " ")}</p>
                            </div>
                            <span className={`rounded-full border px-3 py-1 text-xs ${reviewPriorityClasses(task.priority)}`}>{task.priority}</span>
                          </div>
                          {task.alert_label && <p className="mt-3 text-sm text-cyan-100">{task.alert_label}</p>}
                          <p className="mt-2 text-sm text-[var(--text-muted)]">{task.reason || "Operator attention required."}</p>
                          {task.resolution_reason && <p className="mt-2 text-xs uppercase tracking-[0.16em] text-emerald-100">{task.resolution_reason.replaceAll("_", " ")}</p>}
                          <div className="mt-4 grid gap-3 sm:grid-cols-2">
                            <div><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Status</p><p className="mt-1 text-white">{payloadValue(task.latest_status_snapshot, "status")}</p></div>
                            <div><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">ETA</p><p className="mt-1 text-white">{payloadValue(task.latest_status_snapshot, "eta")}</p></div>
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </section>

          <section className="space-y-6">
            <div className="glass-panel p-5">
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Create</p>
                  <h3 className="mt-1 text-xl font-semibold text-white">{tab === "shipments" ? "New shipment" : tab === "status_ops" ? "Status task detail" : tab === "clients" ? "New client" : "New carrier"}</h3>
                </div>
                {submitting && <Loader2 size={16} className="animate-spin text-[var(--text-muted)]" />}
              </div>

              {tab === "shipments" && (
                <form className="space-y-3" onSubmit={handleCreateShipment}>
                  <select className="field-input" value={shipmentForm.client_id} onChange={(event) => setShipmentForm((current) => ({ ...current, client_id: event.target.value }))}>
                    <option value="">No linked client</option>
                    {clients.map((client) => <option key={client.id} value={client.id}>{client.name}</option>)}
                  </select>
                  <input className="field-input" placeholder="Origin" value={shipmentForm.origin} onChange={(event) => setShipmentForm((current) => ({ ...current, origin: event.target.value }))} />
                  <input className="field-input" placeholder="Destination" value={shipmentForm.destination} onChange={(event) => setShipmentForm((current) => ({ ...current, destination: event.target.value }))} />
                  <div className="grid grid-cols-2 gap-3">
                    <input className="field-input" placeholder="Pallets" value={shipmentForm.pallets} onChange={(event) => setShipmentForm((current) => ({ ...current, pallets: event.target.value }))} />
                    <input className="field-input" placeholder="Weight lb" value={shipmentForm.weight_lb} onChange={(event) => setShipmentForm((current) => ({ ...current, weight_lb: event.target.value }))} />
                  </div>
                  <input className="field-input" placeholder="Equipment" value={shipmentForm.equipment_type} onChange={(event) => setShipmentForm((current) => ({ ...current, equipment_type: event.target.value }))} />
                  <DateTimePickerField
                    value={shipmentForm.ready_at}
                    placeholder="Choose pickup-ready time"
                    onChange={(nextValue) => setShipmentForm((current) => ({ ...current, ready_at: nextValue }))}
                  />
                  <div className="grid grid-cols-2 gap-3">
                    <input className="field-input" placeholder="Margin %" value={shipmentForm.margin_percent} onChange={(event) => setShipmentForm((current) => ({ ...current, margin_percent: event.target.value }))} />
                    <input className="field-input" placeholder="Margin floor" value={shipmentForm.margin_floor} onChange={(event) => setShipmentForm((current) => ({ ...current, margin_floor: event.target.value }))} />
                  </div>
                  <textarea className="field-input min-h-[120px] resize-none" placeholder="Notes" value={shipmentForm.notes} onChange={(event) => setShipmentForm((current) => ({ ...current, notes: event.target.value }))} />
                  <button className="action-button w-full bg-[var(--accent-cyan)] text-slate-950 hover:brightness-110" disabled={submitting === "shipment"}>Stage shipment</button>
                </form>
              )}

              {tab === "clients" && (
                <form className="space-y-3" onSubmit={handleCreateClient}>
                  <input className="field-input" placeholder="Client name" value={clientForm.name} onChange={(event) => setClientForm((current) => ({ ...current, name: event.target.value }))} />
                  <input className="field-input" placeholder="Client email" value={clientForm.email} onChange={(event) => setClientForm((current) => ({ ...current, email: event.target.value }))} />
                  <div className="grid grid-cols-2 gap-3">
                    <input className="field-input" placeholder="Margin %" value={clientForm.default_margin_percent} onChange={(event) => setClientForm((current) => ({ ...current, default_margin_percent: event.target.value }))} />
                    <input className="field-input" placeholder="Margin floor" value={clientForm.default_margin_floor} onChange={(event) => setClientForm((current) => ({ ...current, default_margin_floor: event.target.value }))} />
                  </div>
                  <button className="action-button w-full bg-[var(--accent-cyan)] text-slate-950 hover:brightness-110" disabled={submitting === "client"}>Add client</button>
                </form>
              )}

              {tab === "carriers" && (
                <form className="space-y-3" onSubmit={handleCreateCarrier}>
                  <input className="field-input" placeholder="Carrier name" value={carrierForm.name} onChange={(event) => setCarrierForm((current) => ({ ...current, name: event.target.value }))} />
                  <input className="field-input" placeholder="Carrier email" value={carrierForm.email} onChange={(event) => setCarrierForm((current) => ({ ...current, email: event.target.value }))} />
                  <input className="field-input" placeholder="Rating" value={carrierForm.rating} onChange={(event) => setCarrierForm((current) => ({ ...current, rating: event.target.value }))} />
                  <input className="field-input" placeholder="Regions, comma separated" value={carrierForm.regions} onChange={(event) => setCarrierForm((current) => ({ ...current, regions: event.target.value }))} />
                  <input className="field-input" placeholder="Equipment, comma separated" value={carrierForm.equipment} onChange={(event) => setCarrierForm((current) => ({ ...current, equipment: event.target.value }))} />
                  <button className="action-button w-full bg-[var(--accent-cyan)] text-slate-950 hover:brightness-110" disabled={submitting === "carrier"}>Add carrier</button>
                </form>
              )}

              {tab === "status_ops" && selectedStatusTask && (
                <div className="space-y-4">
                  <div className="rounded-2xl bg-white/5 p-4 text-sm text-[var(--text-muted)]">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-white">{selectedStatusTask.task_type.replaceAll("_", " ")}</p>
                      <span className={`rounded-full border px-3 py-1 text-xs ${reviewPriorityClasses(selectedStatusTask.priority)}`}>{selectedStatusTask.priority}</span>
                    </div>
                    <p className="mt-2">{selectedStatusTask.reason || "Operator task"}</p>
                    {selectedStatusTask.resolution_reason && <p className="mt-2 text-xs uppercase tracking-[0.16em] text-emerald-100">Resolved: {selectedStatusTask.resolution_reason.replaceAll("_", " ")}</p>}
                    {selectedStatusTask.recommended_next_action && <p className="mt-2 text-xs uppercase tracking-[0.16em] text-cyan-100">Next: {selectedStatusTask.recommended_next_action.replaceAll("_", " ")}</p>}
                  </div>
                  {selectedStatusTask.queue_scope === "resolved" ? (
                    <div className="rounded-2xl border border-emerald-300/20 bg-emerald-300/10 p-4 text-sm text-emerald-50">
                      This task is already resolved. You can inspect the shipment timeline for the full audit trail.
                    </div>
                  ) : selectedStatusTask.task_type === "status_reply" ? (
                    <div className="space-y-3">
                      <input className="field-input" placeholder="Reply subject" value={statusReplyDraftSubject} onChange={(event) => setStatusReplyDraftSubject(event.target.value)} />
                      <textarea className="field-input min-h-[160px] resize-none" placeholder="Reply body" value={statusReplyDraftBody} onChange={(event) => setStatusReplyDraftBody(event.target.value)} />
                      <textarea className="field-input min-h-[100px] resize-none" placeholder="Optional operator note" value={statusReplyMessage} onChange={(event) => setStatusReplyMessage(event.target.value)} />
                      <div className="grid gap-2 sm:grid-cols-2">
                        <button onClick={() => void handleStatusQueueAction("rebuild_draft")} disabled={submitting === "status-queue-rebuild_draft"} className="action-button w-full bg-cyan-300/15 text-cyan-100 hover:bg-cyan-300/20 disabled:opacity-50">Rebuild draft</button>
                        <button onClick={() => void handleStatusQueueAction("approve_and_send")} disabled={submitting === "status-queue-approve_and_send"} className="action-button w-full bg-emerald-300/15 text-emerald-100 hover:bg-emerald-300/20 disabled:opacity-50">Approve and send</button>
                        <button onClick={() => void handleStatusQueueAction("preview")} disabled={submitting === "status-queue-preview"} className="action-button w-full bg-sky-300/15 text-sky-100 hover:bg-sky-300/20 disabled:opacity-50">Preview</button>
                        <button onClick={() => void handleStatusQueueAction("dismiss")} disabled={submitting === "status-queue-dismiss"} className="action-button w-full bg-white/10 text-white hover:bg-white/15 disabled:opacity-50">Dismiss</button>
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      <input className="field-input" placeholder="Status text" value={carrierStatusForm.status_text} onChange={(event) => setCarrierStatusForm((current) => ({ ...current, status_text: event.target.value }))} />
                      <input className="field-input" placeholder="ETA text" value={carrierStatusForm.eta_text} onChange={(event) => setCarrierStatusForm((current) => ({ ...current, eta_text: event.target.value }))} />
                      <input className="field-input" placeholder="Location text" value={carrierStatusForm.location_text} onChange={(event) => setCarrierStatusForm((current) => ({ ...current, location_text: event.target.value }))} />
                      <input className="field-input" placeholder="Notes" value={carrierStatusForm.notes} onChange={(event) => setCarrierStatusForm((current) => ({ ...current, notes: event.target.value }))} />
                      <div className="grid gap-2 sm:grid-cols-2">
                        <button onClick={() => void handleStatusQueueAction("approve_and_push")} disabled={submitting === "status-queue-approve_and_push"} className="action-button w-full bg-blue-300/15 text-blue-100 hover:bg-blue-300/20 disabled:opacity-50">Approve and push</button>
                        <button onClick={() => void handleStatusQueueAction("retry_push")} disabled={submitting === "status-queue-retry_push"} className="action-button w-full bg-sky-300/15 text-sky-100 hover:bg-sky-300/20 disabled:opacity-50">Retry push</button>
                        <button onClick={() => void handleStatusQueueAction("preview")} disabled={submitting === "status-queue-preview"} className="action-button w-full bg-cyan-300/15 text-cyan-100 hover:bg-cyan-300/20 disabled:opacity-50">Preview</button>
                        <button onClick={() => void handleStatusQueueAction("dismiss")} disabled={submitting === "status-queue-dismiss"} className="action-button w-full bg-white/10 text-white hover:bg-white/15 disabled:opacity-50">Dismiss</button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="glass-panel p-5">
              {tab === "shipments" && selectedShipment && (
                <div className="space-y-5">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Shipment detail</p>
                      <h3 className="mt-1 text-xl font-semibold text-white">{selectedShipment.origin || "Origin TBD"} to {selectedShipment.destination || "Destination TBD"}</h3>
                    </div>
                    <ShipmentStatusPill status={selectedShipment.status} />
                  </div>

                  <div className="grid grid-cols-2 gap-3 text-sm text-[var(--text-muted)]">
                    <div className="rounded-2xl bg-white/5 p-4"><p className="text-xs uppercase tracking-[0.18em]">Equipment</p><p className="mt-2 text-base text-white">{selectedShipment.equipment_type || "TBD"}</p></div>
                    <div className="rounded-2xl bg-white/5 p-4"><p className="text-xs uppercase tracking-[0.18em]">Ready time</p><p className="mt-2 text-base text-white">{formatShipmentSchedule(selectedShipment.ready_at_display, selectedShipment.ready_at_local)}</p></div>
                    {shipmentShowsDeliveryTime(selectedShipment) && <div className="rounded-2xl bg-white/5 p-4"><p className="text-xs uppercase tracking-[0.18em]">Delivery time</p><p className="mt-2 text-base text-white">{formatShipmentSchedule(selectedShipment.delivery_at_display, selectedShipment.delivery_at_local)}</p></div>}
                  </div>

                  <div className="rounded-[24px] border border-white/10 bg-white/5 p-4">
                    <div className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]"><RadioTower size={14} />Status tracking</div>
                    <div className="mt-3 grid gap-3 text-sm sm:grid-cols-4">
                      <div className="rounded-2xl bg-slate-950/30 p-4"><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Status</p><p className="mt-2 text-white">{selectedShipment.last_known_status ? selectedShipment.last_known_status.replaceAll("_", " ") : "Unknown"}</p></div>
                      <div className="rounded-2xl bg-slate-950/30 p-4"><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">ETA</p><p className="mt-2 text-white">{selectedShipment.last_known_eta || "Not available"}</p></div>
                      <div className="rounded-2xl bg-slate-950/30 p-4"><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Location</p><p className="mt-2 text-white">{selectedShipment.last_known_location || "Not available"}</p></div>
                      <div className="rounded-2xl bg-slate-950/30 p-4"><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Source</p><p className="mt-2 text-white">{selectedShipment.last_status_source ? selectedShipment.last_status_source.replaceAll("_", " ") : "No updates yet"}</p></div>
                    </div>
                    <div className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
                      <div className="rounded-2xl bg-slate-950/30 p-4"><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Last status activity</p><p className="mt-2 text-white">{formatAge(selectedShipment.last_status_event_at)}</p><p className="mt-1 text-xs text-[var(--text-muted)]">{selectedShipment.last_status_event_at ? formatDate(selectedShipment.last_status_event_at) : "No timeline signal yet"}</p></div>
                      <div className="rounded-2xl bg-slate-950/30 p-4"><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">SLA health</p><p className="mt-2 text-white">{selectedShipment.status_stale ? "Needs operator attention" : "Within SLA"}</p><p className="mt-1 text-xs text-[var(--text-muted)]">Threshold: {selectedShipment.status_sla_hours || overview.sla.status_stale_after_hours}h without status activity</p></div>
                    </div>
                    {(selectedShipment.status_stale || selectedShipment.status_review_required) && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {selectedShipment.status_stale && <span className="rounded-full bg-amber-300/10 px-3 py-1 text-xs text-amber-100">Status follow-up overdue</span>}
                        {selectedShipment.status_review_required && <span className="rounded-full bg-cyan-300/10 px-3 py-1 text-xs text-cyan-100">Status review queued</span>}
                      </div>
                    )}
                  </div>

                  <div className="rounded-[24px] border border-white/10 bg-white/5 p-4">
                    <div className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]"><ClipboardCheck size={14} />Booking state</div>
                    <div className="mt-3 grid gap-3 text-sm sm:grid-cols-3">
                      <div className="rounded-2xl bg-slate-950/30 p-4"><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">State</p><p className="mt-2 text-white">{selectedShipment.booking_state ? selectedShipment.booking_state.replaceAll("_", " ") : "Not started"}</p></div>
                      <div className="rounded-2xl bg-slate-950/30 p-4"><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">TMS handoff</p><p className="mt-2 text-white">{selectedShipment.tms_handoff_status || "Not sent"}</p></div>
                      <div className="rounded-2xl bg-slate-950/30 p-4"><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Failure</p><p className="mt-2 text-white">{selectedShipment.booking_error || "None"}</p></div>
                    </div>
                    <div className="mt-3 grid gap-3 text-sm sm:grid-cols-4">
                      <div className="rounded-2xl bg-slate-950/30 p-4"><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Document health</p><p className="mt-2 text-white">{selectedShipment.document_health_status ? selectedShipment.document_health_status.replaceAll("_", " ") : "Unknown"}</p></div>
                      <div className="rounded-2xl bg-slate-950/30 p-4"><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">OCR pending</p><p className="mt-2 text-white">{selectedShipment.ocr_pending_count}</p></div>
                      <div className="rounded-2xl bg-slate-950/30 p-4"><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Conflicts</p><p className="mt-2 text-white">{selectedShipment.document_conflict_count}</p></div>
                      <div className="rounded-2xl bg-slate-950/30 p-4"><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Enriched values</p><p className="mt-2 text-white">{Object.keys(selectedShipment.document_enrichment).length}</p></div>
                    </div>
                    <div className="mt-3 rounded-2xl bg-slate-950/30 p-4 text-sm">
                      <p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Documents in thread</p>
                      <p className="mt-2 text-white">{selectedShipment.attachment_count} attachment(s) available for TMS handoff</p>
                      {selectedShipment.document_health_status && (
                        <div className="mt-3">
                          <span className={`inline-flex rounded-full border px-3 py-1 text-xs ${healthBadgeClasses(selectedShipment.document_health_status)}`}>
                            {selectedShipment.document_health_status.replaceAll("_", " ")}
                          </span>
                        </div>
                      )}
                      {Object.keys(selectedShipment.document_summary).length > 0 && (
                        <div className="mt-3 flex flex-wrap gap-2">
                          {Object.entries(selectedShipment.document_summary).map(([documentType, count]) => (
                            <span key={documentType} className="rounded-full bg-cyan-300/10 px-3 py-1 text-xs text-cyan-100">
                              {documentType.replaceAll("_", " ")}: {count}
                            </span>
                          ))}
                        </div>
                      )}
                      {selectedShipment.missing_document_types.length > 0 && (
                        <div className="mt-3 flex flex-wrap gap-2">
                          {selectedShipment.missing_document_types.map((documentType) => (
                            <span key={documentType} className="rounded-full bg-amber-300/10 px-3 py-1 text-xs text-amber-100">
                              Missing {documentType.replaceAll("_", " ")}
                            </span>
                          ))}
                        </div>
                      )}
                      {Object.keys(selectedShipment.document_enrichment).length > 0 && (
                        <div className="mt-3 flex flex-wrap gap-2">
                          {Object.entries(selectedShipment.document_enrichment).map(([field, value]) => (
                            <span key={field} className="rounded-full bg-emerald-300/10 px-3 py-1 text-xs text-emerald-100">
                              {field.replaceAll("_", " ")}: {String(value)}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                    {selectedShipment.booking_review_warning && (
                      <div className="mt-3 rounded-2xl border border-amber-300/20 bg-amber-300/10 p-4 text-sm text-amber-50">
                        <p className="text-xs uppercase tracking-[0.16em] text-amber-100">Booking review warning</p>
                        <p className="mt-2">{selectedShipment.booking_review_warning}</p>
                      </div>
                    )}
                    {selectedShipment.booking_review_required && (
                      <div className="mt-3 rounded-2xl border border-rose-300/20 bg-rose-300/10 p-4 text-sm text-rose-50">
                        <p className="text-xs uppercase tracking-[0.16em] text-rose-100">Operator follow-up</p>
                        <p className="mt-2">Review document coverage before relying on this booking as fully complete.</p>
                      </div>
                    )}
                  </div>

                  <div className="rounded-[24px] border border-white/10 bg-white/5 p-4">
                    <div className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]"><Mail size={14} />Documents</div>
                    <div className="mt-3 grid gap-3 sm:grid-cols-3">
                      <button onClick={() => void handleOperatorAction("rerun_document_extraction")} disabled={submitting === "rerun_document_extraction"} className="action-button w-full bg-cyan-300/15 text-cyan-100 hover:bg-cyan-300/20 disabled:opacity-50">{submitting === "rerun_document_extraction" ? "Reprocessing..." : "Re-run document extraction"}</button>
                      <button onClick={() => void handleOperatorAction("approve_document_values")} disabled={submitting === "approve_document_values"} className="action-button w-full bg-emerald-300/15 text-emerald-100 hover:bg-emerald-300/20 disabled:opacity-50">{submitting === "approve_document_values" ? "Approving..." : "Approve document values"}</button>
                      <button onClick={() => void handleOperatorAction("ignore_document_warning")} disabled={submitting === "ignore_document_warning"} className="action-button w-full bg-amber-300/15 text-amber-100 hover:bg-amber-300/20 disabled:opacity-50">{submitting === "ignore_document_warning" ? "Ignoring..." : "Ignore document warning"}</button>
                    </div>
                    <div className="mt-3 space-y-3">
                      {documents.length === 0 && <div className="rounded-2xl border border-dashed border-white/10 bg-white/5 px-4 py-4 text-sm text-[var(--text-muted)]">No document metadata found in this thread.</div>}
                      {documents.map((document) => (
                        <div key={`${document.source_email_id}-${document.id || document.name || "doc"}`} className="rounded-2xl bg-slate-950/30 p-4 text-sm">
                          <div className="flex items-center justify-between gap-3">
                            <p className="text-white">{document.name || "Unnamed attachment"}</p>
                            <span className="rounded-full bg-cyan-300/10 px-3 py-1 text-xs text-cyan-100">{document.document_type.replaceAll("_", " ")}</span>
                          </div>
                          <div className="mt-2 flex flex-wrap gap-3 text-xs text-[var(--text-muted)]">
                            <span>{document.content_type || "unknown type"}</span>
                            <span>{document.size ? `${document.size} bytes` : "size unknown"}</span>
                            {document.extraction_method && <span>{document.extraction_method.replaceAll("_", " ")}</span>}
                            {document.ocr_status && <span>OCR: {document.ocr_status.replaceAll("_", " ")}</span>}
                            <span>OCR confidence: {formatConfidence(document.ocr_confidence)}</span>
                            <span>Field confidence: {formatConfidence(document.field_confidence)}</span>
                          </div>
                          <div className="mt-3 flex flex-wrap gap-2">
                            {document.review_required && (
                              <span className="rounded-full bg-amber-300/10 px-3 py-1 text-xs text-amber-100">
                                Review required
                              </span>
                            )}
                            {document.ocr_status && (
                              <span className={`rounded-full border px-3 py-1 text-xs ${healthBadgeClasses(
                                document.ocr_status === "ocr_complete" || document.ocr_status === "not_needed"
                                  ? "healthy"
                                  : document.ocr_status === "ocr_failed"
                                    ? "blocking"
                                    : "review_required",
                              )}`}>
                                {document.ocr_status.replaceAll("_", " ")}
                              </span>
                            )}
                          </div>
                          {Object.keys(document.extracted_fields).length > 0 && (
                            <div className="mt-3 flex flex-wrap gap-2">
                              {Object.entries(document.extracted_fields).map(([field, value]) => (
                                <span key={field} className="rounded-full bg-emerald-300/10 px-3 py-1 text-xs text-emerald-100">
                                  {field.replaceAll("_", " ")}: {String(value)}
                                </span>
                              ))}
                            </div>
                          )}
                          {document.review_reason && (
                            <div className="mt-3 rounded-2xl border border-amber-300/20 bg-amber-300/10 px-3 py-3 text-xs text-amber-50">
                              {document.review_reason}
                            </div>
                          )}
                          {document.extracted_text_preview && (
                            <div className="mt-3 rounded-2xl border border-white/10 bg-white/5 px-3 py-3 text-xs text-[var(--text-muted)]">
                              {document.extracted_text_preview}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="rounded-[24px] border border-white/10 bg-white/5 p-4">
                    <div className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]"><Sparkles size={14} />AI decision</div>
                    <div className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
                      <div className="rounded-2xl bg-slate-950/30 p-4"><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Intent</p><p className="mt-2 text-white">{selectedShipment.ai_intent || "Not classified yet"}</p></div>
                      <div className="rounded-2xl bg-slate-950/30 p-4"><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Next action</p><p className="mt-2 text-white">{selectedShipment.ai_next_action || "Pending"}</p></div>
                      <div className="rounded-2xl bg-slate-950/30 p-4"><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Confidence</p><p className="mt-2 text-white">{selectedShipment.ai_confidence !== null && selectedShipment.ai_confidence !== undefined ? `${(selectedShipment.ai_confidence * 100).toFixed(0)}%` : "--"}</p></div>
                      <div className="rounded-2xl bg-slate-950/30 p-4"><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Manual review</p><p className="mt-2 text-white">{selectedShipment.manual_review_required ? "Required" : "No"}</p></div>
                    </div>
                    {selectedShipment.ai_missing_fields.length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {selectedShipment.ai_missing_fields.map((field) => (
                          <span key={field} className="rounded-full bg-amber-300/10 px-3 py-1 text-xs text-amber-100">{field}</span>
                        ))}
                      </div>
                    )}
                    {selectedShipment.ai_ambiguity_reasons.length > 0 ? (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {selectedShipment.ai_ambiguity_reasons.map((reason) => (
                            <span key={reason} className="rounded-full bg-rose-300/10 px-3 py-1 text-xs text-rose-100">
                              {reason.replaceAll("_", " ")}
                            </span>
                        ))}
                      </div>
                    ) : null}
                  </div>

                  <div className="grid gap-3 sm:grid-cols-2">
                    <button onClick={() => void handleOperatorAction("resume_workflow")} disabled={submitting === "resume_workflow"} className="action-button w-full bg-emerald-300/15 text-emerald-100 hover:bg-emerald-300/20 disabled:opacity-50">{submitting === "resume_workflow" ? "Resuming..." : "Resume workflow"}</button>
                    <button onClick={() => void handleOperatorAction("approve_and_continue")} disabled={submitting === "approve_and_continue"} className="action-button w-full bg-lime-300/15 text-lime-100 hover:bg-lime-300/20 disabled:opacity-50">{submitting === "approve_and_continue" ? "Approving..." : "Approve and continue"}</button>
                    <button onClick={() => void handleOperatorAction("rerun_parsing")} disabled={submitting === "rerun_parsing"} className="action-button w-full bg-sky-300/15 text-sky-100 hover:bg-sky-300/20 disabled:opacity-50">{submitting === "rerun_parsing" ? "Re-running..." : "Re-run parsing"}</button>
                    <button onClick={() => void handleOperatorAction("rerun_outreach")} disabled={submitting === "rerun_outreach"} className="action-button w-full bg-orange-300/15 text-orange-100 hover:bg-orange-300/20 disabled:opacity-50">{submitting === "rerun_outreach" ? "Sending..." : "Re-run outreach"}</button>
                    <button onClick={() => void handleOperatorAction("rerun_evaluation")} disabled={submitting === "rerun_evaluation" || bids.length === 0} className="action-button w-full bg-fuchsia-300/15 text-fuchsia-100 hover:bg-fuchsia-300/20 disabled:opacity-50">{submitting === "rerun_evaluation" ? "Evaluating..." : "Re-run evaluation"}</button>
                    <button onClick={() => void handleOperatorAction("rerun_status_lookup")} disabled={submitting === "rerun_status_lookup"} className="action-button w-full bg-cyan-300/15 text-cyan-100 hover:bg-cyan-300/20 disabled:opacity-50">{submitting === "rerun_status_lookup" ? "Refreshing..." : "Re-run status lookup"}</button>
                    <button onClick={() => void handleOperatorAction("rerun_tms_update")} disabled={submitting === "rerun_tms_update"} className="action-button w-full bg-sky-300/15 text-sky-100 hover:bg-sky-300/20 disabled:opacity-50">{submitting === "rerun_tms_update" ? "Re-sending..." : "Re-run TMS update"}</button>
                    <button onClick={() => void handleOperatorAction("approve_status_reply")} disabled={submitting === "approve_status_reply"} className="action-button w-full bg-teal-300/15 text-teal-100 hover:bg-teal-300/20 disabled:opacity-50">{submitting === "approve_status_reply" ? "Sending..." : "Approve status reply"}</button>
                    <button onClick={() => void handleOperatorAction("rerun_document_extraction")} disabled={submitting === "rerun_document_extraction"} className="action-button w-full bg-cyan-300/15 text-cyan-100 hover:bg-cyan-300/20 disabled:opacity-50">{submitting === "rerun_document_extraction" ? "Reprocessing..." : "Re-run document extraction"}</button>
                    <button onClick={() => void handleOperatorAction("approve_document_values")} disabled={submitting === "approve_document_values"} className="action-button w-full bg-emerald-300/15 text-emerald-100 hover:bg-emerald-300/20 disabled:opacity-50">{submitting === "approve_document_values" ? "Approving..." : "Approve document values"}</button>
                    <button onClick={() => void handleOperatorAction("ignore_document_warning")} disabled={submitting === "ignore_document_warning"} className="action-button w-full bg-amber-300/15 text-amber-100 hover:bg-amber-300/20 disabled:opacity-50">{submitting === "ignore_document_warning" ? "Ignoring..." : "Ignore document warning"}</button>
                    <button onClick={() => void handlePreviewStatusReply()} disabled={submitting === "status_preview"} className="action-button w-full bg-cyan-300/15 text-cyan-100 hover:bg-cyan-300/20 disabled:opacity-50">{submitting === "status_preview" ? "Preparing..." : "Preview status reply"}</button>
                    <button onClick={() => void handleSendStatusReply()} disabled={submitting === "status_send"} className="action-button w-full bg-emerald-300/15 text-emerald-100 hover:bg-emerald-300/20 disabled:opacity-50">{submitting === "status_send" ? "Sending..." : "Send status reply"}</button>
                    <button onClick={() => void handlePreviewCarrierStatusUpdate()} disabled={submitting === "carrier_status_preview"} className="action-button w-full bg-sky-300/15 text-sky-100 hover:bg-sky-300/20 disabled:opacity-50">{submitting === "carrier_status_preview" ? "Preparing..." : "Preview carrier update"}</button>
                    <button onClick={() => void handleSendCarrierStatusUpdate()} disabled={submitting === "carrier_status_send"} className="action-button w-full bg-blue-300/15 text-blue-100 hover:bg-blue-300/20 disabled:opacity-50">{submitting === "carrier_status_send" ? "Sending..." : "Send carrier update"}</button>
                    <button onClick={() => void handlePreviewAcknowledgement()} disabled={submitting === "ack"} className="action-button w-full bg-violet-300/15 text-violet-100 hover:bg-violet-300/20 disabled:opacity-50">{submitting === "ack" ? "Preparing acknowledgment..." : "Preview customer ack"}</button>
                    <button onClick={() => void handleDryRunOutreach()} disabled={submitting === "outreach"} className="action-button w-full bg-[var(--accent-amber)] text-slate-950 hover:brightness-110">{submitting === "outreach" ? "Preparing..." : "Dry-run outreach"}</button>
                    <button onClick={() => void handleEvaluateBids()} disabled={submitting === "evaluate" || bids.length === 0} className="action-button w-full bg-white/10 text-white hover:bg-white/15 disabled:opacity-50">{submitting === "evaluate" ? "Evaluating..." : "Evaluate bids"}</button>
                    <button onClick={() => void handlePreviewCustomerQuote()} disabled={submitting === "quote" || bids.length === 0} className="action-button w-full bg-cyan-300/15 text-cyan-100 hover:bg-cyan-300/20 disabled:opacity-50">{submitting === "quote" ? "Building quote..." : "Preview customer quote"}</button>
                    <button onClick={() => void handlePreviewTmsHandoff()} disabled={submitting === "tms" || bids.length === 0} className="action-button w-full bg-rose-300/15 text-rose-100 hover:bg-rose-300/20 disabled:opacity-50">{submitting === "tms" ? "Preparing handoff..." : "Preview TMS handoff"}</button>
                    <button onClick={() => void handleBookShipment()} disabled={submitting === "book" || bids.length === 0} className="action-button w-full bg-lime-300/15 text-lime-100 hover:bg-lime-300/20 disabled:opacity-50">{submitting === "book" ? "Booking..." : "Book load"}</button>
                  </div>

                  <div className="rounded-[24px] border border-white/10 bg-white/5 p-4">
                    <div className="mb-3 flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]"><RadioTower size={14} />Manual bid intake</div>
                    <form className="space-y-3" onSubmit={handleIntakeBid}>
                      <select className="field-input" value={bidForm.carrier_id} onChange={(event) => setBidForm((current) => ({ ...current, carrier_id: event.target.value }))}>
                        {carriers.map((carrier) => <option key={carrier.id} value={carrier.id}>{carrier.name}</option>)}
                      </select>
                      <div className="grid grid-cols-2 gap-3">
                        <input className="field-input" placeholder="Amount" value={bidForm.amount} onChange={(event) => setBidForm((current) => ({ ...current, amount: event.target.value }))} />
                        <input className="field-input" placeholder="ETA / timing" value={bidForm.eta_text} onChange={(event) => setBidForm((current) => ({ ...current, eta_text: event.target.value }))} />
                      </div>
                      <textarea className="field-input min-h-[100px] resize-none" placeholder="Carrier reply" value={bidForm.raw_email} onChange={(event) => setBidForm((current) => ({ ...current, raw_email: event.target.value }))} />
                      <button className="action-button w-full bg-white/10 text-white hover:bg-white/15" disabled={submitting === "bid"}>{submitting === "bid" ? "Recording bid..." : "Record bid"}</button>
                    </form>
                  </div>

                  <div className="space-y-3">
                    <div className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]"><CircleDollarSign size={14} />Bid board</div>
                    {bids.length === 0 && <div className="rounded-2xl border border-dashed border-white/10 bg-white/5 px-4 py-6 text-sm text-[var(--text-muted)]">No bids captured yet for this shipment.</div>}
                    {bids.map((bid) => (
                      <div key={bid.id} className="rounded-2xl border border-white/10 bg-white/5 p-4">
                        <div className="flex items-center justify-between gap-3">
                          <div><p className="text-sm font-medium text-white">{bid.carrier_name}</p><p className="mt-1 text-xs text-[var(--text-muted)]">{bid.carrier_email}</p></div>
                          <span className="rounded-full bg-white/10 px-3 py-1 text-xs text-white">{bid.status}</span>
                        </div>
                        <div className="mt-4 grid grid-cols-3 gap-3 text-sm">
                          <div><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Rate</p><p className="mt-1 text-white">{bid.amount ? `$${bid.amount.toFixed(2)}` : "--"}</p></div>
                          <div><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">ETA</p><p className="mt-1 text-white">{bid.eta_text || "--"}</p></div>
                          <div><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Score</p><p className="mt-1 text-white">{bid.score.total ?? "--"}</p></div>
                        </div>
                      </div>
                    ))}
                  </div>

                  {ackPreview && <div className="rounded-[24px] border border-violet-300/20 bg-violet-300/10 p-4"><div className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-violet-100"><Mail size={14} />Customer acknowledgment preview</div><p className="mt-3 text-sm text-white">{ackPreview.subject}</p><p className="mt-2 whitespace-pre-wrap text-sm text-violet-50">{ackPreview.body}</p></div>}

                  {evaluation && <div className="rounded-[24px] border border-cyan-300/20 bg-cyan-300/10 p-4"><div className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-cyan-100"><Sparkles size={14} />Evaluation result</div><p className="mt-3 text-sm text-white">Winner: {selectedWinningBid?.carrier_name || evaluation.selected_carrier_id} at ${evaluation.selected_amount.toFixed(2)}.</p><p className="mt-1 text-sm text-cyan-100">Recommended customer quote: ${evaluation.recommended_quote_amount.toFixed(2)}</p></div>}

                  {quotePreview && <div className="rounded-[24px] border border-emerald-300/20 bg-emerald-300/10 p-4"><div className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-emerald-100"><Mail size={14} />Customer quote preview</div><p className="mt-3 text-sm text-white">{quotePreview.subject}</p><p className="mt-2 whitespace-pre-wrap text-sm text-emerald-50">{quotePreview.body}</p></div>}

                  <div className="rounded-[24px] border border-cyan-300/20 bg-cyan-300/10 p-4">
                    <div className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-cyan-100"><Mail size={14} />Status reply draft</div>
                    <textarea
                      className="field-input mt-3 min-h-[110px] resize-none"
                      placeholder="Optional operator note to append to the status reply"
                      value={statusReplyMessage}
                      onChange={(event) => setStatusReplyMessage(event.target.value)}
                    />
                    {statusReplyPreview ? (
                      <div className="mt-3">
                        <p className="text-sm text-white">{statusReplyPreview.subject}</p>
                        <p className="mt-2 whitespace-pre-wrap text-sm text-cyan-50">{statusReplyPreview.body}</p>
                      </div>
                    ) : (
                      <p className="mt-3 text-sm text-cyan-50">Preview a status reply to review the exact customer-facing message before sending.</p>
                    )}
                  </div>

                  <div className="rounded-[24px] border border-sky-300/20 bg-sky-300/10 p-4">
                    <div className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-sky-100"><RadioTower size={14} />Carrier status update review</div>
                    <div className="mt-3 grid gap-3 sm:grid-cols-2">
                      <input
                        className="field-input"
                        placeholder="Status text"
                        value={carrierStatusForm.status_text}
                        onChange={(event) => setCarrierStatusForm((current) => ({ ...current, status_text: event.target.value }))}
                      />
                      <input
                        className="field-input"
                        placeholder="ETA text"
                        value={carrierStatusForm.eta_text}
                        onChange={(event) => setCarrierStatusForm((current) => ({ ...current, eta_text: event.target.value }))}
                      />
                      <input
                        className="field-input"
                        placeholder="Location text"
                        value={carrierStatusForm.location_text}
                        onChange={(event) => setCarrierStatusForm((current) => ({ ...current, location_text: event.target.value }))}
                      />
                      <input
                        className="field-input"
                        placeholder="Notes"
                        value={carrierStatusForm.notes}
                        onChange={(event) => setCarrierStatusForm((current) => ({ ...current, notes: event.target.value }))}
                      />
                    </div>
                    {carrierStatusPreview ? (
                      <div className="mt-3 rounded-2xl border border-sky-300/20 bg-slate-950/30 p-4 text-sm text-sky-50">
                        <p className="text-xs uppercase tracking-[0.16em] text-sky-100">Prepared payload</p>
                        <div className="mt-3 grid gap-3 sm:grid-cols-3">
                          <div><p className="text-xs uppercase tracking-[0.16em] text-sky-100">Status</p><p className="mt-1 text-white">{carrierStatusPreview.status_text || "None"}</p></div>
                          <div><p className="text-xs uppercase tracking-[0.16em] text-sky-100">ETA</p><p className="mt-1 text-white">{carrierStatusPreview.eta_text || "None"}</p></div>
                          <div><p className="text-xs uppercase tracking-[0.16em] text-sky-100">Location</p><p className="mt-1 text-white">{carrierStatusPreview.location_text || "None"}</p></div>
                        </div>
                        {carrierStatusPreview.notes && <p className="mt-3 text-sky-50">{carrierStatusPreview.notes}</p>}
                      </div>
                    ) : (
                      <p className="mt-3 text-sm text-sky-50">Preview the structured carrier update, adjust any field if needed, then send it to TMS.</p>
                    )}
                  </div>

                  {tmsPreview && <div className="rounded-[24px] border border-rose-300/20 bg-rose-300/10 p-4"><div className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-rose-100"><ClipboardCheck size={14} />TMS preview</div><pre className="mt-3 overflow-x-auto whitespace-pre-wrap rounded-2xl bg-slate-950/40 p-4 text-xs text-rose-50">{JSON.stringify(tmsPreview.payload, null, 2)}</pre></div>}

                  {bookingResult && <div className="rounded-[24px] border border-lime-300/20 bg-lime-300/10 p-4"><div className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-lime-100"><ClipboardCheck size={14} />Booking completed</div><p className="mt-3 text-sm text-white">TMS status: {bookingResult.handoff.status}</p><p className="mt-1 text-sm text-lime-100">Confirmation sent to {bookingResult.confirmation.client_email}</p><p className="mt-3 text-sm text-white">{bookingResult.confirmation.subject}</p></div>}

                  <div className="space-y-3">
                    <div className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]"><Map size={14} />TMS status timeline</div>
                    <div className="space-y-3">
                      {statusEvents.length === 0 && <div className="rounded-2xl border border-dashed border-white/10 bg-white/5 px-4 py-6 text-sm text-[var(--text-muted)]">No status sync events yet for this shipment.</div>}
                      {statusEvents.map((eventRecord) => (
                        <div key={`status-${eventRecord.id}`} className="rounded-2xl border border-white/10 bg-white/5 p-4">
                          <div className="flex items-center justify-between gap-3">
                            <p className="text-sm font-medium text-white">{statusAuditLabel(eventRecord)}</p>
                            <span className="text-xs text-[var(--text-muted)]">{formatDate(eventRecord.created_at)}</span>
                          </div>
                          <p className="mt-1 text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">{eventRecord.event_type.replaceAll("_", " ")}</p>
                          <div className="mt-3 grid gap-3 text-sm sm:grid-cols-3">
                            <div><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Status</p><p className="mt-1 text-white">{payloadValue(eventRecord.payload, "status_label", "status", "status_text", "resolution_state").replaceAll("_", " ")}</p></div>
                            <div><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">ETA</p><p className="mt-1 text-white">{payloadValue(eventRecord.payload, "eta_label", "eta", "eta_text", "resolution_reason")}</p></div>
                            <div><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Location</p><p className="mt-1 text-white">{payloadValue(eventRecord.payload, "location_label", "location", "location_text", "source")}</p></div>
                          </div>
                          <div className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
                            <div><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Milestone</p><p className="mt-1 text-white">{payloadValue(eventRecord.payload, "milestone_label", "milestone")}</p></div>
                            <div><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Source</p><p className="mt-1 text-white">{payloadValue(eventRecord.payload, "status_source", "source")}</p></div>
                          </div>
                          {typeof eventRecord.payload.reason === "string" && eventRecord.payload.reason.length > 0 && (
                            <p className="mt-3 text-sm text-[var(--text-muted)]">{eventRecord.payload.reason}</p>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="space-y-3">
                    <div className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]"><Clock3 size={14} />Workflow timeline</div>
                    <div className="space-y-3">
                      {events.length === 0 && <div className="rounded-2xl border border-dashed border-white/10 bg-white/5 px-4 py-6 text-sm text-[var(--text-muted)]">No events yet for this shipment.</div>}
                      {events.map((eventRecord) => (
                        <div key={eventRecord.id} className="rounded-2xl border border-white/10 bg-white/5 p-4">
                          <div className="flex items-center justify-between gap-3">
                            <p className="text-sm font-medium text-white">{eventRecord.event_type.replaceAll("_", " ")}</p>
                            <span className="text-xs text-[var(--text-muted)]">{formatDate(eventRecord.created_at)}</span>
                          </div>
                          <p className="mt-1 text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">{eventRecord.stage.replaceAll("_", " ")}</p>
                          {Boolean(eventRecord.payload.reason || eventRecord.payload.next_action) && (
                            <p className="mt-2 text-sm text-[var(--text-muted)]">
                              {String(eventRecord.payload.reason || eventRecord.payload.next_action).replaceAll("_", " ")}
                            </p>
                          )}
                          {Array.isArray(eventRecord.payload.missing_fields) && eventRecord.payload.missing_fields.length > 0 && (
                            <div className="mt-3 flex flex-wrap gap-2">
                              {(eventRecord.payload.missing_fields as string[]).map((field) => (
                                <span key={field} className="rounded-full bg-amber-300/10 px-2 py-1 text-[11px] text-amber-100">{field}</span>
                              ))}
                            </div>
                          )}
                          {Array.isArray(eventRecord.payload.ambiguity_reasons) && eventRecord.payload.ambiguity_reasons.length > 0 && (
                            <div className="mt-3 flex flex-wrap gap-2">
                              {(eventRecord.payload.ambiguity_reasons as string[]).map((reason) => (
                                <span key={reason} className="rounded-full bg-rose-300/10 px-2 py-1 text-[11px] text-rose-100">{reason.replaceAll("_", " ")}</span>
                              ))}
                            </div>
                          )}
                          {typeof eventRecord.payload.booking_review_warning === "string" && eventRecord.payload.booking_review_warning.length > 0 && (
                            <div className="mt-3 rounded-2xl border border-amber-300/20 bg-amber-300/10 px-3 py-3 text-xs text-amber-50">
                              {eventRecord.payload.booking_review_warning}
                            </div>
                          )}
                          {Array.isArray(eventRecord.payload.missing_document_types) && eventRecord.payload.missing_document_types.length > 0 && (
                            <div className="mt-3 flex flex-wrap gap-2">
                              {(eventRecord.payload.missing_document_types as string[]).map((documentType) => (
                                <span key={documentType} className="rounded-full bg-amber-300/10 px-2 py-1 text-[11px] text-amber-100">
                                  Missing {documentType.replaceAll("_", " ")}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {tab === "clients" && selectedClient && <div className="space-y-4"><div><p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Client detail</p><h3 className="mt-1 text-xl font-semibold text-white">{selectedClient.name}</h3></div><div className="rounded-2xl bg-white/5 p-4 text-sm text-[var(--text-muted)]"><div className="flex items-center gap-3 text-white"><Building2 size={16} /> {selectedClient.email}</div><div className="mt-4 flex items-center justify-between"><span>Margin rule</span><span className="text-white">{selectedClient.default_margin_percent}%</span></div><div className="mt-2 flex items-center justify-between"><span>Floor price</span><span className="text-white">${selectedClient.default_margin_floor}</span></div></div></div>}

              {tab === "carriers" && selectedCarrier && <div className="space-y-4"><div><p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Carrier detail</p><h3 className="mt-1 text-xl font-semibold text-white">{selectedCarrier.name}</h3></div><div className="rounded-2xl bg-white/5 p-4 text-sm text-[var(--text-muted)]"><div className="flex items-center gap-3 text-white"><Map size={16} /> {selectedCarrier.email}</div><div className="mt-4 flex items-center justify-between"><span>Rating</span><span className="text-white">{selectedCarrier.rating}</span></div><div className="mt-4 flex flex-wrap gap-2">{selectedCarrier.regions.map((region) => <span key={region} className="rounded-full bg-white/10 px-3 py-1 text-xs text-white">{region}</span>)}</div><div className="mt-3 flex flex-wrap gap-2">{selectedCarrier.equipment.map((equipment) => <span key={equipment} className="rounded-full bg-cyan-300/10 px-3 py-1 text-xs text-cyan-100">{equipment}</span>)}</div></div></div>}

              {tab === "status_ops" && selectedStatusTask && (
                <div className="space-y-4">
                  <div>
                    <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Status task</p>
                    <h3 className="mt-1 text-xl font-semibold text-white">{selectedStatusTask.task_type.replaceAll("_", " ")}</h3>
                  </div>
                  <div className="rounded-2xl bg-white/5 p-4 text-sm text-[var(--text-muted)]">
                    <div className="flex items-center justify-between"><span>Task state</span><span className="text-white">{selectedStatusTask.task_state.replaceAll("_", " ")}</span></div>
                    <div className="mt-3 flex items-center justify-between"><span>Queue scope</span><span className="text-white">{selectedStatusTask.queue_scope.replaceAll("_", " ")}</span></div>
                    <div className="mt-3 flex items-center justify-between"><span>Resolution state</span><span className="text-white">{selectedStatusTask.resolution_state ? selectedStatusTask.resolution_state.replaceAll("_", " ") : "Open"}</span></div>
                    <div className="mt-3 flex items-center justify-between"><span>Resolution reason</span><span className="text-white">{selectedStatusTask.resolution_reason ? selectedStatusTask.resolution_reason.replaceAll("_", " ") : "Open"}</span></div>
                    <div className="mt-3 flex items-center justify-between"><span>Resolved at</span><span className="text-white">{formatDate(selectedStatusTask.resolution_at)}</span></div>
                    <div className="mt-3 flex items-center justify-between"><span>Status sync health</span><span className="text-white">{selectedStatusTask.status_sync_health || "unknown"}</span></div>
                    <div className="mt-3 flex items-center justify-between"><span>TMS load</span><span className="text-white">{selectedStatusTask.tms_load_id || "Not linked"}</span></div>
                    <div className="mt-3 flex items-center justify-between"><span>TMS system</span><span className="text-white">{selectedStatusTask.tms_system || "Generic"}</span></div>
                  </div>
                  <div className="rounded-2xl bg-white/5 p-4 text-sm text-[var(--text-muted)]">
                    <p className="text-xs uppercase tracking-[0.16em]">Latest status snapshot</p>
                    <div className="mt-3 grid gap-3 sm:grid-cols-2">
                      <div><p className="text-xs uppercase tracking-[0.16em]">Status</p><p className="mt-1 text-white">{payloadValue(selectedStatusTask.latest_status_snapshot, "status")}</p></div>
                      <div><p className="text-xs uppercase tracking-[0.16em]">ETA</p><p className="mt-1 text-white">{payloadValue(selectedStatusTask.latest_status_snapshot, "eta")}</p></div>
                      <div><p className="text-xs uppercase tracking-[0.16em]">Location</p><p className="mt-1 text-white">{payloadValue(selectedStatusTask.latest_status_snapshot, "location")}</p></div>
                      <div><p className="text-xs uppercase tracking-[0.16em]">Source</p><p className="mt-1 text-white">{payloadValue(selectedStatusTask.latest_status_snapshot, "source")}</p></div>
                    </div>
                  </div>
                  {selectedStatusTask.last_failure && <div className="rounded-2xl border border-rose-300/20 bg-rose-300/10 p-4 text-sm text-rose-50">{selectedStatusTask.last_failure}</div>}
                </div>
              )}
            </div>

            <div className="glass-panel p-5">
              <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Connected systems</p>
              <div className="mt-4 space-y-3 text-sm text-[var(--text-muted)]">
                <div className="flex items-center justify-between rounded-2xl bg-white/5 px-4 py-3"><span className="flex items-center gap-3"><Mail size={16} /> Outlook inbox</span><span className="text-white">Ready</span></div>
                <div className="flex items-center justify-between rounded-2xl bg-white/5 px-4 py-3"><span className="flex items-center gap-3"><CircleDollarSign size={16} /> Margin defaults</span><span className="text-white">{overview.integrations.quote_wait_minutes_default || "20"} min window</span></div>
                <div className="flex items-center justify-between rounded-2xl bg-white/5 px-4 py-3"><span className="flex items-center gap-3"><ClipboardCheck size={16} /> TMS connector</span><span className="text-white">Preview-ready</span></div>
              </div>

              <div className="mt-6 rounded-[24px] border border-white/10 bg-white/5 p-4">
                <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Status ops health</p>
                <div className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
                  <div className="rounded-2xl bg-slate-950/30 p-4 text-white">Replies sent: {overview.status_metrics.replies_sent}</div>
                  <div className="rounded-2xl bg-slate-950/30 p-4 text-white">Lookups: {overview.status_metrics.lookups}</div>
                  <div className="rounded-2xl bg-slate-950/30 p-4 text-white">Carrier pushes: {overview.status_metrics.carrier_updates_pushed}</div>
                  <div className="rounded-2xl bg-slate-950/30 p-4 text-white">Status reviews: {overview.status_metrics.review_required}</div>
                  <div className="rounded-2xl bg-slate-950/30 p-4 text-white">Draft replies: {overview.status_metrics.replies_drafted}</div>
                  <div className="rounded-2xl bg-slate-950/30 p-4 text-white">Stale shipments: {overview.status_metrics.stale_shipments}</div>
                </div>
                <p className="mt-3 text-xs text-[var(--text-muted)]">SLA baseline: a shipment is marked stale after {overview.sla.status_stale_after_hours}h without status activity while still in an active status workflow.</p>
              </div>

              {lastSyncSummary && (
                <div className="mt-6 rounded-[24px] border border-cyan-300/20 bg-cyan-300/10 p-4">
                  <p className="text-xs uppercase tracking-[0.18em] text-cyan-100">Last sync summary</p>
                  <div className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
                    <div className="rounded-2xl bg-slate-950/30 p-4 text-white">Parsed shipments: {lastSyncSummary.parsed_shipments}</div>
                    <div className="rounded-2xl bg-slate-950/30 p-4 text-white">Auto acknowledgements: {lastSyncSummary.auto_acknowledgements}</div>
                    <div className="rounded-2xl bg-slate-950/30 p-4 text-white">Auto outreach: {lastSyncSummary.auto_outreach}</div>
                    <div className="rounded-2xl bg-slate-950/30 p-4 text-white">Auto bids: {lastSyncSummary.auto_bids}</div>
                    <div className="rounded-2xl bg-slate-950/30 p-4 text-white">Auto evaluations: {lastSyncSummary.auto_evaluations}</div>
                    <div className="rounded-2xl bg-slate-950/30 p-4 text-white">Auto quotes: {lastSyncSummary.auto_quotes}</div>
                    <div className="rounded-2xl bg-slate-950/30 p-4 text-white">Status replies: {lastSyncSummary.auto_status_replies}</div>
                    <div className="rounded-2xl bg-slate-950/30 p-4 text-white">TMS status updates: {lastSyncSummary.auto_tms_status_updates}</div>
                  </div>
                </div>
              )}

              <div className="mt-6">
                <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Review queue</p>
                <div className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
                  <div className="rounded-2xl border border-rose-300/20 bg-rose-300/10 p-4 text-rose-50">
                    <p className="text-xs uppercase tracking-[0.16em] text-rose-100">Critical alerts</p>
                    <p className="mt-2 text-xl font-semibold text-white">{criticalReviewCount}</p>
                    <p className="mt-1 text-xs text-rose-100">Primarily stale status workflows needing immediate operator follow-up.</p>
                  </div>
                  <div className="rounded-2xl border border-amber-300/20 bg-amber-300/10 p-4 text-amber-50">
                    <p className="text-xs uppercase tracking-[0.16em] text-amber-100">High priority reviews</p>
                    <p className="mt-2 text-xl font-semibold text-white">{highPriorityReviewCount}</p>
                    <p className="mt-1 text-xs text-amber-100">Status ambiguities and booking warnings that should be resolved next.</p>
                  </div>
                </div>
                <div className="mt-4 space-y-3">
                  {reviewQueue.length === 0 && <div className="rounded-2xl border border-dashed border-white/10 bg-white/5 px-4 py-5 text-sm text-[var(--text-muted)]">No manual review items.</div>}
                  {reviewQueue.slice(0, 5).map((item) => (
                    <div key={item.workflow_event_id} className={`rounded-2xl border p-4 ${item.priority === "critical" ? "border-rose-300/20 bg-rose-300/10" : item.priority === "high" ? "border-amber-300/20 bg-amber-300/10" : "border-white/10 bg-white/5"}`}>
                      <button onClick={() => setSelectedShipmentId(item.shipment_id)} className="w-full text-left transition hover:bg-white/0">
                      <div className="flex items-center justify-between gap-3">
                        <p className="text-sm font-medium text-white">{item.event_type.replaceAll("_", " ")}</p>
                        <span className="text-xs text-[var(--text-muted)]">{formatDate(item.created_at)}</span>
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        {item.review_type && (
                          <span className={`rounded-full px-2 py-1 text-[11px] ${item.review_type.includes("status") ? "bg-cyan-300/10 text-cyan-100" : "bg-white/10 text-white"}`}>
                            {item.review_type.replaceAll("_", " ")}
                          </span>
                        )}
                        <span className={`rounded-full border px-2 py-1 text-[11px] ${reviewPriorityClasses(item.priority)}`}>
                          {item.priority} priority
                        </span>
                        {item.alert_label && (
                          <span className={`rounded-full border px-2 py-1 text-[11px] ${reviewPriorityClasses(item.priority)}`}>
                            {item.alert_label}
                          </span>
                        )}
                      </div>
                      <p className="mt-2 text-sm text-[var(--text-muted)]">{item.reason || "Operator review requested"}</p>
                      {item.next_action && <p className="mt-2 text-xs uppercase tracking-[0.16em] text-cyan-100">Next: {item.next_action.replaceAll("_", " ")}</p>}
                      {item.missing_fields.length > 0 && <div className="mt-3 flex flex-wrap gap-2">{item.missing_fields.map((field) => <span key={field} className="rounded-full bg-amber-300/10 px-2 py-1 text-[11px] text-amber-100">{field}</span>)}</div>}
                      {item.ambiguity_reasons.length > 0 && <div className="mt-3 flex flex-wrap gap-2">{item.ambiguity_reasons.map((reason) => <span key={reason} className="rounded-full bg-rose-300/10 px-2 py-1 text-[11px] text-rose-100">{reason.replaceAll("_", " ")}</span>)}</div>}
                      {item.status_stale && <div className="mt-3 rounded-2xl border border-rose-300/20 bg-rose-300/10 px-3 py-3 text-xs text-rose-50">This status workflow is beyond the current SLA window and should be handled first.</div>}
                      {item.status_review_required && !item.status_stale && <div className="mt-3 rounded-2xl border border-cyan-300/20 bg-cyan-300/10 px-3 py-3 text-xs text-cyan-50">This case needs a status-specific operator decision before automation continues.</div>}
                      {item.document_conflict_fields.length > 0 && <div className="mt-3 flex flex-wrap gap-2">{item.document_conflict_fields.map((field) => <span key={field} className="rounded-full bg-rose-300/10 px-2 py-1 text-[11px] text-rose-100">Conflict: {field.replaceAll("_", " ")}</span>)}</div>}
                      {item.missing_document_types.length > 0 && <div className="mt-3 flex flex-wrap gap-2">{item.missing_document_types.map((documentType) => <span key={documentType} className="rounded-full bg-amber-300/10 px-2 py-1 text-[11px] text-amber-100">Missing {documentType.replaceAll("_", " ")}</span>)}</div>}
                      {item.booking_review_warning && <div className="mt-3 rounded-2xl border border-amber-300/20 bg-amber-300/10 px-3 py-3 text-xs text-amber-50">{item.booking_review_warning}</div>}
                      </button>
                      <div className="mt-4 grid gap-2 sm:grid-cols-2">
                        {item.review_type === "customer_status_request_review" ? (
                          <>
                            <button onClick={() => void handleOperatorAction("rerun_status_lookup", item.shipment_id)} disabled={submitting === "rerun_status_lookup"} className="action-button w-full bg-cyan-300/15 text-cyan-100 hover:bg-cyan-300/20 disabled:opacity-50">Refresh status</button>
                            <button onClick={() => void handleOperatorAction("approve_status_reply", item.shipment_id)} disabled={submitting === "approve_status_reply"} className="action-button w-full bg-teal-300/15 text-teal-100 hover:bg-teal-300/20 disabled:opacity-50">Approve reply</button>
                          </>
                        ) : item.review_type === "carrier_status_update_review" ? (
                          <>
                            <button onClick={() => void handleOperatorAction("rerun_tms_update", item.shipment_id)} disabled={submitting === "rerun_tms_update"} className="action-button w-full bg-sky-300/15 text-sky-100 hover:bg-sky-300/20 disabled:opacity-50">Replay update</button>
                            <button onClick={() => void handleOperatorAction("rerun_status_lookup", item.shipment_id)} disabled={submitting === "rerun_status_lookup"} className="action-button w-full bg-cyan-300/15 text-cyan-100 hover:bg-cyan-300/20 disabled:opacity-50">Check TMS status</button>
                          </>
                        ) : item.review_type === "document_conflict_review" || item.review_type === "ocr_review_required" || item.review_type === "document_parse_low_confidence" ? (
                          <>
                            <button onClick={() => void handleOperatorAction("rerun_document_extraction", item.shipment_id)} disabled={submitting === "rerun_document_extraction"} className="action-button w-full bg-cyan-300/15 text-cyan-100 hover:bg-cyan-300/20 disabled:opacity-50">Reprocess docs</button>
                            <button onClick={() => void handleOperatorAction("approve_document_values", item.shipment_id)} disabled={submitting === "approve_document_values"} className="action-button w-full bg-emerald-300/15 text-emerald-100 hover:bg-emerald-300/20 disabled:opacity-50">Approve values</button>
                            <button onClick={() => void handleOperatorAction("ignore_document_warning", item.shipment_id)} disabled={submitting === "ignore_document_warning"} className="action-button w-full bg-amber-300/15 text-amber-100 hover:bg-amber-300/20 disabled:opacity-50 sm:col-span-2">Ignore warning</button>
                          </>
                        ) : (
                          <>
                            <button onClick={() => void handleOperatorAction("resume_workflow", item.shipment_id)} disabled={submitting === "resume_workflow"} className="action-button w-full bg-emerald-300/15 text-emerald-100 hover:bg-emerald-300/20 disabled:opacity-50">Resume</button>
                            <button onClick={() => void handleOperatorAction("approve_and_continue", item.shipment_id)} disabled={submitting === "approve_and_continue"} className="action-button w-full bg-lime-300/15 text-lime-100 hover:bg-lime-300/20 disabled:opacity-50">Approve</button>
                          </>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </section>
        </div>
      </section>
      </div>
    </main>
  );
}

export { FreightDashboardWorkspace as FreightDashboard } from "./FreightDashboardWorkspace";
