"use client";

import { startTransition, useEffect, useMemo, useRef, useState, type FormEvent, type MouseEvent as ReactMouseEvent } from "react";
import { createPortal } from "react-dom";

import { useFreightSocket } from "@/hooks/useFreightSocket";
import { DateTimePickerField } from "@/components/DateTimePickerField";
import { DashboardLogo } from "@/components/DashboardLogo";
import {
  AlertTriangle,
  Archive,
  ArrowRight,
  Bell,
  Building2,
  Calendar,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronUp,
  ChevronRight,
  CircleDollarSign,
  ClipboardCheck,
  Clock3,
  Loader2,
  Mail,
  MapPin,
  MoreHorizontal,
  Package2,
  PencilLine,
  RadioTower,
  RefreshCcw,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  Truck,
  Users,
  X,
} from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type DashboardTab = "shipments" | "status_ops" | "clients" | "carriers" | "archive";
type WorkspaceSection = "overview" | "bids" | "timeline" | "status" | "docs";
type DrawerMode = "overview" | "edit";
type ThreadTab = "timeline" | "client" | "carrier_quotes" | "system";
type ArchiveReasonCode = "duplicate" | "cancelled" | "parsed_error" | "fraud" | "test" | "non_delivery_bounce" | "other";
type EditFocusTarget = "client_id" | "equipment_type" | "origin" | "destination" | "pallets" | "weight_lb" | "ready_at" | "delivery_at" | "notes";
type StatusQueueAction = "preview" | "approve_and_send" | "approve_and_push" | "rebuild_draft" | "retry_push" | "dismiss";
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
  | "ignore_document_warning"
  | "archive_shipment";

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
}

interface CarrierRecord {
  id: string;
  name: string;
  email: string;
  rating: number;
  is_active: boolean;
  regions: string[];
  equipment: string[];
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
  board_stage: string | null;
  attention_state: string;
  attention_reason: string | null;
  attention_level: string;
  has_active_review: boolean;
  has_active_status_review: boolean;
  has_active_booking_warning: boolean;
  next_step_label: string | null;
  is_archived: boolean;
  archive_reason_code: ArchiveReasonCode | null;
  archive_reason_note: string | null;
  archived_reason: string | null;
  archived_at: string | null;
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
  extracted_text_preview: string | null;
  extracted_fields: Record<string, string | number>;
  review_required: boolean;
  review_reason: string | null;
  extraction_method: string | null;
  ocr_status: string | null;
  ocr_confidence: number | null;
  field_confidence: number | null;
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
}

interface ReviewQueueItem {
  workflow_event_id: string;
  shipment_id: string;
  event_type: string;
  review_type: string | null;
  priority: string;
  alert_label: string | null;
  reason: string;
  next_action: string | null;
  missing_fields: string[];
  ambiguity_reasons: string[];
  booking_review_warning: string | null;
  status_stale: boolean;
  status_review_required: boolean;
  created_at: string;
}

interface StatusQueueItem {
  task_id: string;
  task_type: string;
  task_state: string;
  queue_scope: string;
  resolution_state: string | null;
  resolution_reason: string | null;
  shipment_id: string;
  priority: string;
  alert_label: string | null;
  reason: string;
  recommended_next_action: string | null;
  ambiguity_reasons: string[];
  latest_status_snapshot: Record<string, unknown>;
  draft_subject: string | null;
  draft_body: string | null;
  structured_payload: Record<string, unknown>;
  last_failure: string | null;
}

interface OutlookIngestResult {
  intent: string | null;
  manual_review_required: boolean;
  next_action: string | null;
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

interface ShipmentOperatorActionResponse {
  message: string;
  archived?: boolean;
  suppression_applied?: boolean;
  suppressed_thread_id?: string | null;
}

interface ShipmentMagicFillResponse {
  shipment_id: string;
  field: "ready_at_local";
  status: string;
  message: string;
  confidence: number;
  suggested_value: string | null;
  ambiguity_reasons: string[];
  source_messages: number;
  shipment: ShipmentRecord | null;
}

interface ShipmentThreadMessageRecord {
  id: string;
  thread_id: string;
  provider_message_id: string | null;
  direction: string;
  sender: string;
  recipients: string[];
  subject: string;
  received_at: string;
  body_preview: string;
  display_body: string;
  has_raw_payload: boolean;
}

interface ShipmentThreadResponse {
  shipment_id: string;
  thread_id: string | null;
  thread_subject: string | null;
  quote_token: string | null;
  messages: ShipmentThreadMessageRecord[];
}

type NotificationKind = "email" | "shipment" | "bid" | "review" | "status" | "archive" | "system";

interface NotificationItem {
  id: string;
  kind: NotificationKind;
  title: string;
  detail: string;
  created_at: string;
  shipment_id: string | null;
  quote_token: string | null;
  unread: boolean;
  toast_visible: boolean;
  archived: boolean;
}

interface NotificationFeedResponse {
  items: Array<
    Omit<NotificationItem, "unread" | "toast_visible"> & {
      event_type: string;
      stage: string;
      route: string | null;
      status: string | null;
    }
  >;
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

function threadMessageVisual(message: ShipmentThreadMessageRecord) {
  const sender = message.sender.toLowerCase();
  const recipients = message.recipients.join(" ").toLowerCase();
  const combined = `${sender} ${recipients}`;
  if (combined.includes("mailer-daemon") || combined.includes("postmaster") || combined.includes("microsoftexchange") || combined.includes("delivery")) {
    return {
      card: "border-rose-300/18 bg-rose-300/10",
      label: "System",
    };
  }
  if (message.direction === "outbound") {
    return {
      card: "border-cyan-300/18 bg-cyan-300/10 shadow-[0_0_0_1px_rgba(134,239,255,0.04)]",
      label: "Outbound",
    };
  }
  return {
    card: "border-white/10 bg-white/5",
    label: "Inbound",
  };
}

function isSystemThreadMessage(message: ShipmentThreadMessageRecord) {
  const sender = message.sender.toLowerCase();
  const recipients = message.recipients.join(" ").toLowerCase();
  const combined = `${sender} ${recipients}`;
  return combined.includes("mailer-daemon") || combined.includes("postmaster") || combined.includes("microsoftexchange") || combined.includes("delivery");
}

interface StatusQueueActionResponse {
  message: string;
  shipment_id: string;
}

interface EvaluationResponse {
  selected_bid_id: string;
  selected_amount: number;
  recommended_quote_amount: number;
}

interface CustomerQuoteResponse {
  subject: string;
  body: string;
  final_amount: number;
}

interface CustomerStatusReplyResponse {
  client_email: string;
  subject: string;
  body: string;
}

interface TmsHandoffResponse {
  payload: Record<string, unknown>;
}

interface BookingExecutionResponse {
  handoff: {
    status: string;
  };
  confirmation: {
    client_email: string;
    subject: string;
  };
}

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
  operatorAction?: OperatorAction;
  requiresSave?: boolean;
  tone?: "primary" | "success" | "warning" | "neutral";
}

interface ShipmentActionModel {
  label: string | null;
  reason: string;
  blockingReason: string | null;
  operatorAction: OperatorAction | null;
  requiresSave: boolean;
  contextActions: ShipmentContextAction[];
}

interface ArchiveDialogState {
  shipmentId: string;
  shipmentLabel: string;
}

const ARCHIVE_REASON_OPTIONS: Array<{ value: ArchiveReasonCode | "all"; label: string; helper: string }> = [
  { value: "duplicate", label: "Duplicate", helper: "Same request already exists." },
  { value: "cancelled", label: "Cancelled", helper: "Customer or operator cancelled it." },
  { value: "parsed_error", label: "Parsed error", helper: "AI/system created an invalid shipment." },
  { value: "fraud", label: "Fraud / spam", helper: "Suspicious or unwanted request." },
  { value: "test", label: "Test", helper: "Internal or test data." },
  { value: "non_delivery_bounce", label: "Non-delivery bounce", helper: "Email bounce or delivery failure." },
  { value: "other", label: "Other", helper: "Anything else." },
];

function archiveReasonLabel(value: string | null | undefined) {
  return ARCHIVE_REASON_OPTIONS.find((item) => item.value === value)?.label || "Other";
}

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

function currentMonthValue() {
  return new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
  }).format(new Date()).slice(0, 7);
}

function formatMonthLabel(value: string) {
  const [year, month] = value.split("-");
  const parsed = new Date(Number(year), Number(month) - 1, 1);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "long",
    year: "numeric",
  }).format(parsed);
}

function shiftMonthValue(value: string, delta: number) {
  const [year, month] = value.split("-");
  const parsed = new Date(Number(year), Number(month) - 1 + delta, 1);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
  }).format(parsed).slice(0, 7);
}

function monthGridForYear(year: number) {
  return Array.from({ length: 12 }, (_, index) => {
    const monthValue = `${year}-${String(index + 1).padStart(2, "0")}`;
    return {
      value: monthValue,
      shortLabel: new Intl.DateTimeFormat("en-US", { month: "short" }).format(new Date(year, index, 1)),
    };
  });
}

function formatAge(value: string | null) {
  if (!value) return "No recent activity";
  const diffMs = Date.now() - new Date(value).getTime();
  if (Number.isNaN(diffMs)) return "Unknown";
  const diffMinutes = Math.max(0, Math.round(diffMs / 60000));
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 48) return `${diffHours}h ago`;
  return `${Math.round(diffHours / 24)}d ago`;
}

function formatConfidence(value: number | null) {
  if (value === null || value === undefined) return "--";
  return `${Math.round(value * 100)}%`;
}

function formatRoute(shipment: ShipmentRecord) {
  return `${shipment.origin || "Origin TBD"} -> ${shipment.destination || "Destination TBD"}`;
}

function toDateTimeLocal(value: string | null) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 16);
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function buildShipmentEditor(shipment: ShipmentRecord | null): ShipmentEditorState {
  return {
    client_id: shipment?.client_id || "",
    origin: shipment?.origin || "",
    destination: shipment?.destination || "",
    pallets: shipment?.pallets?.toString() || "",
    weight_lb: shipment?.weight_lb?.toString() || "",
    equipment_type: shipment?.equipment_type || "",
    ready_at: toDateTimeLocal(shipment?.ready_at_local || null),
    delivery_at: toDateTimeLocal(shipment?.delivery_at_local || null),
    notes: shipment?.notes || "",
  };
}

function statusPillClass(status: string) {
  return SHIPMENT_STATUS_STYLES[status] || "bg-white/10 text-white border-white/10";
}

function shipmentNeedsAttention(shipment: ShipmentRecord) {
  return shipment.attention_state !== "none" || shipment.has_active_review;
}

function shipmentShowsDeliveryTime(shipment: ShipmentRecord | null) {
  if (!shipment) return false;
  return ["booking_in_progress", "booking_failed", "booked"].includes(shipment.status);
}

function shipmentBlockingBadge(shipment: ShipmentRecord) {
  if (shipment.attention_state === "missing_details") return "Missing details";
  if (shipment.attention_state === "ambiguous") return "Ambiguous";
  if (shipment.attention_state === "review") return "Needs review";
  if (shipment.attention_state === "docs_warning") return "Docs warning";
  if (shipment.attention_state === "status_review") return "Status review";
  if (shipment.attention_state === "stale") return "Status stale";
  if (shipment.status === "waiting_bids") return "Waiting bids";
  return "Ready";
}

function hasMinimumFields(editor: ShipmentEditorState) {
  return Boolean(
    editor.origin.trim() &&
      editor.destination.trim() &&
      editor.pallets.trim() &&
      editor.weight_lb.trim() &&
      editor.equipment_type.trim() &&
      editor.ready_at.trim(),
  );
}

function deriveShipmentActionModel(
  shipment: ShipmentRecord,
  editor: ShipmentEditorState,
  shipmentStatusTasks: StatusQueueItem[],
  bidCount: number,
): ShipmentActionModel {
  const statusReplyTask = shipmentStatusTasks.find((task) => task.task_type === "status_reply");
  const carrierUpdateTask = shipmentStatusTasks.find((task) => task.task_type === "carrier_update");
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
    baseActions.push({ key: "refresh_status", label: "Refresh status", operatorAction: "rerun_status_lookup" });
  }
  if (carrierUpdateTask) {
    baseActions.push({ key: "rerun_tms_update", label: "Re-run TMS update", operatorAction: "rerun_tms_update" });
  }
  if (statusReplyTask) {
    baseActions.push({ key: "approve_status_reply", label: "Preview status reply", operatorAction: "approve_status_reply" });
  }
  baseActions.push({ key: "archive_shipment", label: "Archive and ignore source", operatorAction: "archive_shipment", tone: "warning" });

  if (!hasMinimumFields(editor)) {
    const missing = ["origin", "destination", "pallets", "weight_lb", "equipment_type", "ready_at"].filter(
      (field) => !editor[field as keyof ShipmentEditorState],
    );
    return {
      label: null,
      reason: "Fill in the missing shipment fields first. Until then, the system should not continue automation.",
      blockingReason: `Missing: ${missing.map((field) => field.replaceAll("_", " ")).join(", ")}`,
      operatorAction: null,
      requiresSave: false,
      contextActions: baseActions,
    };
  }

  if (shipment.status === "parsing" || shipment.status === "received" || shipment.status === "client_acknowledged") {
    return {
      label: "Approve and send outreach",
      reason: "The parsed shipment is complete enough. This will save the current values and continue the quote workflow.",
      blockingReason: null,
      operatorAction: "approve_and_continue",
      requiresSave: true,
      contextActions: [
        { key: "approve_and_continue", label: "Approve parsed details", operatorAction: "approve_and_continue", requiresSave: true, tone: "success" },
        ...baseActions,
      ],
    };
  }

  if ((shipment.status === "waiting_bids" || shipment.status === "evaluating") && bidCount > 0) {
    return {
      label: "Approve and evaluate bids",
      reason: "Carrier quotes are already here. This step will evaluate the bids and advance the customer quote flow.",
      blockingReason: null,
      operatorAction: "rerun_evaluation",
      requiresSave: false,
      contextActions: [
        { key: "approve_and_evaluate", label: "Approve and evaluate", operatorAction: "rerun_evaluation", tone: "success" },
        ...baseActions,
      ],
    };
  }

  if (statusReplyTask) {
    return {
      label: "Approve and send status reply",
      reason: "A customer status reply is waiting for operator approval.",
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
      reason: "Document extraction needs operator confirmation before this shipment can be trusted for booking decisions.",
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

  return {
    label: "Continue workflow",
    reason: "No critical blocker is active for this shipment. Continue workflow to let the backend choose the next safe step.",
    blockingReason: null,
    operatorAction: "resume_workflow",
    requiresSave: false,
    contextActions: [{ key: "resume_workflow", label: "Approve and continue workflow", operatorAction: "resume_workflow", tone: "primary" }, ...baseActions],
  };
}

function reviewPriorityClasses(priority: string) {
  if (priority === "critical") return "bg-rose-300/10 text-rose-100 border-rose-300/20";
  if (priority === "high") return "bg-amber-300/10 text-amber-100 border-amber-300/20";
  return "bg-white/10 text-white border-white/10";
}

function notificationAccent(kind: NotificationKind) {
  if (kind === "email") return "border-cyan-300/18 bg-cyan-300/10 text-cyan-100";
  if (kind === "shipment") return "border-emerald-300/18 bg-emerald-300/10 text-emerald-100";
  if (kind === "bid") return "border-orange-300/18 bg-orange-300/10 text-orange-100";
  if (kind === "review") return "border-amber-300/18 bg-amber-300/10 text-amber-100";
  if (kind === "status") return "border-violet-300/18 bg-violet-300/10 text-violet-100";
  if (kind === "archive") return "border-rose-300/18 bg-rose-300/10 text-rose-100";
  return "border-white/10 bg-white/10 text-white";
}

function notificationBadgeLabel(kind: NotificationKind) {
  if (kind === "email") return "Email";
  if (kind === "shipment") return "Shipment";
  if (kind === "bid") return "Bid";
  if (kind === "review") return "Review";
  if (kind === "status") return "Status";
  if (kind === "archive") return "Archive";
  return "System";
}

function buildNotificationFromWorkflowEvent(
  event: WorkflowEventRecord,
  shipment: ShipmentRecord | null,
): NotificationItem | null {
  const route = shipment ? formatRoute(shipment) : "Shipment";
  const quoteToken = shipment?.quote_token || (typeof event.payload?.quote_token === "string" ? event.payload.quote_token : null);
  const sender = typeof event.payload?.sender === "string" ? event.payload.sender : null;
  switch (event.event_type) {
    case "email_received":
      return {
        id: event.id,
        kind: "email",
        title: sender ? `New email from ${sender}` : "New inbound email",
        detail: quoteToken ? `${route} · ${quoteToken}` : route,
        created_at: event.created_at,
        shipment_id: event.shipment_id,
        quote_token: quoteToken,
        unread: true,
        toast_visible: true,
        archived: false,
      };
    case "shipment_parsed":
    case "parsing_completed":
      return {
        id: event.id,
        kind: "shipment",
        title: "Shipment captured from inbox",
        detail: quoteToken ? `${route} · ${quoteToken}` : route,
        created_at: event.created_at,
        shipment_id: event.shipment_id,
        quote_token: quoteToken,
        unread: true,
        toast_visible: true,
        archived: false,
      };
    case "bid_received":
      return {
        id: event.id,
        kind: "bid",
        title: "Carrier bid received",
        detail: quoteToken ? `${route} · ${quoteToken}` : route,
        created_at: event.created_at,
        shipment_id: event.shipment_id,
        quote_token: quoteToken,
        unread: true,
        toast_visible: true,
        archived: false,
      };
    case "manual_review_required":
      return {
        id: event.id,
        kind: "review",
        title: "Needs operator review",
        detail: typeof event.payload?.reason === "string" ? event.payload.reason : route,
        created_at: event.created_at,
        shipment_id: event.shipment_id,
        quote_token: quoteToken,
        unread: true,
        toast_visible: true,
        archived: false,
      };
    case "customer_status_sent":
    case "tms_status_ingested":
    case "tms_status_updated":
      return {
        id: event.id,
        kind: "status",
        title: event.event_type === "customer_status_sent" ? "Status reply updated" : "Status feed updated",
        detail: quoteToken ? `${route} · ${quoteToken}` : route,
        created_at: event.created_at,
        shipment_id: event.shipment_id,
        quote_token: quoteToken,
        unread: true,
        toast_visible: true,
        archived: false,
      };
    case "shipment_archived":
      return {
        id: event.id,
        kind: "archive",
        title: "Shipment archived",
        detail: quoteToken ? `${route} · ${quoteToken}` : route,
        created_at: event.created_at,
        shipment_id: event.shipment_id,
        quote_token: quoteToken,
        unread: true,
        toast_visible: true,
        archived: true,
      };
    default:
      return null;
  }
}

function ShipmentStatusPill({ status }: { status: string }) {
  return (
    <span className={`inline-flex h-6 shrink-0 items-center whitespace-nowrap rounded-full border px-2.5 text-[10px] font-medium capitalize leading-none ${statusPillClass(status)}`}>
      {status.replaceAll("_", " ")}
    </span>
  );
}

export function FreightDashboardWorkspace() {
  const BOARD_FILTER_STORAGE_KEY = "logistic-copilot-board-filter";
  const BOARD_MONTH_STORAGE_KEY = "logistic-copilot-board-month";
  const BOARD_CONTROLS_STORAGE_KEY = "logistic-copilot-board-controls-expanded";
  const [tab, setTab] = useState<DashboardTab>("shipments");
  const [workspaceSection, setWorkspaceSection] = useState<WorkspaceSection>("overview");
  const [drawerMode, setDrawerMode] = useState<DrawerMode>("overview");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [activeBoardFilter, setActiveBoardFilter] = useState<"all" | "today" | "attention">("all");
  const [shipmentSearch, setShipmentSearch] = useState("");
  const [selectedBoardMonth, setSelectedBoardMonth] = useState(currentMonthValue());
  const [boardControlsExpanded, setBoardControlsExpanded] = useState(false);
  const [monthPickerOpen, setMonthPickerOpen] = useState(false);
  const [monthPickerYear, setMonthPickerYear] = useState(() => Number(currentMonthValue().slice(0, 4)));
  const [overview, setOverview] = useState<OverviewResponse>(EMPTY_OVERVIEW);
  const [clients, setClients] = useState<ClientRecord[]>([]);
  const [carriers, setCarriers] = useState<CarrierRecord[]>([]);
  const [shipments, setShipments] = useState<ShipmentRecord[]>([]);
  const [archivedShipments, setArchivedShipments] = useState<ShipmentRecord[]>([]);
  const [archiveSearch, setArchiveSearch] = useState("");
  const [archiveReasonFilter, setArchiveReasonFilter] = useState<ArchiveReasonCode | "all">("all");
  const [archiveMonth, setArchiveMonth] = useState(currentMonthValue());
  const [reviewQueue, setReviewQueue] = useState<ReviewQueueItem[]>([]);
  const [statusQueue, setStatusQueue] = useState<StatusQueueItem[]>([]);
  const [events, setEvents] = useState<WorkflowEventRecord[]>([]);
  const [bids, setBids] = useState<BidRecord[]>([]);
  const [documents, setDocuments] = useState<ShipmentDocumentRecord[]>([]);
  const [initialLoading, setInitialLoading] = useState(true);
  const [backgroundRefreshing, setBackgroundRefreshing] = useState(false);
  const [submitting, setSubmitting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [lastSyncSummary, setLastSyncSummary] = useState<OutlookSyncResponse | null>(null);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [notificationCenterOpen, setNotificationCenterOpen] = useState(false);
  const [notificationLoading, setNotificationLoading] = useState(false);
  const [notificationHasMore, setNotificationHasMore] = useState(false);
  const [notificationOffset, setNotificationOffset] = useState(0);
  const [notificationTotal, setNotificationTotal] = useState(0);
  const [selectedShipmentId, setSelectedShipmentId] = useState<string | null>(null);
  const [selectedStatusTaskId, setSelectedStatusTaskId] = useState<string | null>(null);
  const [statusQueueScope, setStatusQueueScope] = useState<"active" | "resolved">("active");
  const [shipmentEditor, setShipmentEditor] = useState<ShipmentEditorState>(buildShipmentEditor(null));
  const [evaluation, setEvaluation] = useState<EvaluationResponse | null>(null);
  const [quotePreview, setQuotePreview] = useState<CustomerQuoteResponse | null>(null);
  const [statusReplyPreview, setStatusReplyPreview] = useState<CustomerStatusReplyResponse | null>(null);
  const [tmsPreview, setTmsPreview] = useState<TmsHandoffResponse | null>(null);
  const [bookingResult, setBookingResult] = useState<BookingExecutionResponse | null>(null);
  const [statusReplyMessage, setStatusReplyMessage] = useState("");
  const [statusReplyDraftSubject, setStatusReplyDraftSubject] = useState("");
  const [statusReplyDraftBody, setStatusReplyDraftBody] = useState("");
  const [carrierStatusForm, setCarrierStatusForm] = useState({ status_text: "", eta_text: "", location_text: "", notes: "" });
  const [magicFillingField, setMagicFillingField] = useState<string | null>(null);
  const [activeThreadTab, setActiveThreadTab] = useState<ThreadTab>("timeline");
  const [contextMenu, setContextMenu] = useState<{ shipmentId: string; x: number; y: number } | null>(null);
  const [archiveDialog, setArchiveDialog] = useState<ArchiveDialogState | null>(null);
  const [archiveReasonCode, setArchiveReasonCode] = useState<ArchiveReasonCode>("parsed_error");
  const [archiveReasonNote, setArchiveReasonNote] = useState("invalid shipment from non-delivery email");
  const [threadLoading, setThreadLoading] = useState(false);
  const [threadError, setThreadError] = useState<string | null>(null);
  const [threadCache, setThreadCache] = useState<Record<string, ShipmentThreadResponse>>({});
  const [pendingEditFocus, setPendingEditFocus] = useState<EditFocusTarget | null>(null);
  const [readyPickerOpenSignal, setReadyPickerOpenSignal] = useState(0);
  const [deliveryPickerOpenSignal, setDeliveryPickerOpenSignal] = useState(0);
  const [clientForm, setClientForm] = useState({ name: "", email: "", default_margin_percent: "15", default_margin_floor: "0" });
  const [carrierForm, setCarrierForm] = useState({ name: "", email: "", rating: "0", regions: "midwest,northeast", equipment: "dry van" });
  const drawerScrollRef = useRef<HTMLDivElement | null>(null);
  const monthPickerRef = useRef<HTMLDivElement | null>(null);
  const overviewRefreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const notificationTimersRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const resolvingQuoteTokenRef = useRef<string | null>(null);
  const editFieldRefs = useRef<Partial<Record<EditFocusTarget, HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement | null>>>({});
  const shipmentsRef = useRef<ShipmentRecord[]>([]);
  const archivedShipmentsRef = useRef<ShipmentRecord[]>([]);
  const [shipmentCreateForm, setShipmentCreateForm] = useState({
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

  const selectedShipment = useMemo(
    () =>
      shipments.find((shipment) => shipment.id === selectedShipmentId) ||
      archivedShipments.find((shipment) => shipment.id === selectedShipmentId) ||
      null,
    [archivedShipments, shipments, selectedShipmentId],
  );
  const selectedClient = useMemo(
    () => (selectedShipment?.client_id ? clients.find((client) => client.id === selectedShipment.client_id) || null : null),
    [clients, selectedShipment],
  );
  const threadData = useMemo(
    () => (selectedShipmentId ? threadCache[selectedShipmentId] || null : null),
    [selectedShipmentId, threadCache],
  );
  const selectedClientEmail = selectedClient?.email.trim().toLowerCase() || null;
  const filteredThreadMessages = useMemo(() => {
    const messages = threadData?.messages || [];
    if (activeThreadTab === "timeline") {
      return messages;
    }
    if (activeThreadTab === "system") {
      return messages.filter((message) => isSystemThreadMessage(message));
    }
    if (activeThreadTab === "client") {
      if (!selectedClientEmail) return [];
      return messages.filter((message) => {
        const sender = message.sender.toLowerCase();
        const recipients = message.recipients.map((recipient) => recipient.toLowerCase());
        return sender.includes(selectedClientEmail) || recipients.some((recipient) => recipient.includes(selectedClientEmail));
      });
    }
    return messages.filter((message) => {
      if (isSystemThreadMessage(message)) return false;
      if (!selectedClientEmail) return true;
      const sender = message.sender.toLowerCase();
      const recipients = message.recipients.map((recipient) => recipient.toLowerCase());
      const touchesClient = sender.includes(selectedClientEmail) || recipients.some((recipient) => recipient.includes(selectedClientEmail));
      return !touchesClient;
    });
  }, [activeThreadTab, selectedClientEmail, threadData]);
  const filteredStatusQueue = useMemo(
    () => statusQueue.filter((task) => task.queue_scope === statusQueueScope),
    [statusQueue, statusQueueScope],
  );
  const selectedStatusTask = useMemo(
    () => filteredStatusQueue.find((task) => task.task_id === selectedStatusTaskId) || null,
    [filteredStatusQueue, selectedStatusTaskId],
  );
  const shipmentStatusTasks = useMemo(
    () => statusQueue.filter((task) => task.shipment_id === selectedShipmentId && task.queue_scope === "active"),
    [selectedShipmentId, statusQueue],
  );
  const actionModel = useMemo(
    () => (selectedShipment ? deriveShipmentActionModel(selectedShipment, shipmentEditor, shipmentStatusTasks, bids.length) : null),
    [selectedShipment, shipmentEditor, shipmentStatusTasks, bids.length],
  );
  const shipmentFormDirty = useMemo(() => {
    if (!selectedShipment) return false;
    const baseline = buildShipmentEditor(selectedShipment);
    return JSON.stringify(baseline) !== JSON.stringify(shipmentEditor);
  }, [selectedShipment, shipmentEditor]);
  const selectedWinningBid = useMemo(() => {
    if (!evaluation?.selected_bid_id) return null;
    return bids.find((bid) => bid.id === evaluation.selected_bid_id) || null;
  }, [bids, evaluation]);
  const boardShipments = useMemo(() => {
    const today = new Intl.DateTimeFormat("en-CA").format(new Date());
    const query = shipmentSearch.trim().toLowerCase();
    return shipments.filter((shipment) => {
      if (activeBoardFilter === "attention" && !shipmentNeedsAttention(shipment)) {
        return false;
      }
      if (activeBoardFilter === "today") {
        if (!shipment.ready_at_local) return shipmentNeedsAttention(shipment);
        if (shipment.ready_at_local.slice(0, 10) !== today) {
          return false;
        }
      }
      if (!query) return true;
      const searchHaystack = [
        formatRoute(shipment),
        shipment.origin || "",
        shipment.destination || "",
        shipment.quote_token || "",
        shipment.notes || "",
        shipment.status || "",
        shipment.next_step_label || "",
        shipment.ai_next_action || "",
      ]
        .join(" ")
        .toLowerCase();
      return searchHaystack.includes(query);
    });
  }, [shipments, activeBoardFilter, shipmentSearch]);
  const groupedShipmentsByStatus = useMemo(() => {
    const groups: Record<string, ShipmentRecord[]> = {
      parsing: [],
      waiting_bids: [],
      quoted: [],
      booked: [],
    };
    boardShipments.forEach((shipment) => {
      if (shipment.board_stage === "closed") {
        return;
      }
      if (shipment.board_stage === "parsing") {
        groups.parsing.push(shipment);
      } else if (shipment.board_stage === "waiting_bids") {
        groups.waiting_bids.push(shipment);
      } else if (shipment.board_stage === "quoted") {
        groups.quoted.push(shipment);
      } else {
        groups.booked.push(shipment);
      }
    });
    return groups;
  }, [boardShipments]);
  const unreadNotificationCount = useMemo(
    () => notifications.reduce((total, item) => total + (item.unread ? 1 : 0), 0),
    [notifications],
  );
  const visibleToasts = useMemo(
    () => notifications.filter((item) => item.toast_visible).slice(0, 4),
    [notifications],
  );

  function mergeShipmentIntoState(shipment: ShipmentRecord) {
    setShipments((current) => {
      const index = current.findIndex((item) => item.id === shipment.id);
      if (index === -1) {
        return [shipment, ...current];
      }
      const next = [...current];
      next[index] = shipment;
      return next;
    });
  }

  function appendNotification(item: NotificationItem) {
    setNotifications((current) => {
      const alreadyExists = current.some((existing) => existing.id === item.id);
      if (!alreadyExists) {
        setNotificationTotal((total) => total + 1);
      }
      const deduped = current.filter((existing) => existing.id !== item.id);
      return [item, ...deduped].slice(0, 40);
    });
  }

  function markNotificationRead(id: string) {
    setNotifications((current) => current.map((item) => (item.id === id ? { ...item, unread: false, toast_visible: false } : item)));
  }

  function hideNotificationToast(id: string) {
    setNotifications((current) => current.map((item) => (item.id === id ? { ...item, toast_visible: false } : item)));
  }

  function markAllNotificationsRead() {
    setNotifications((current) => current.map((item) => ({ ...item, unread: false, toast_visible: false })));
  }

  function createSystemNotification(title: string, detail: string): NotificationItem {
    return {
      id: `system-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      kind: "system",
      title,
      detail,
      created_at: new Date().toISOString(),
      shipment_id: null,
      quote_token: null,
      unread: true,
      toast_visible: true,
      archived: false,
    };
  }

  async function loadNotifications(options?: { reset?: boolean }) {
    const reset = options?.reset ?? false;
    const nextOffset = reset ? 0 : notificationOffset;
    setNotificationLoading(true);
    try {
      const response = await fetchJson<NotificationFeedResponse>(
        `/api/freight/notifications?limit=20&offset=${encodeURIComponent(String(nextOffset))}`,
      );
      const incoming = response.items.map((item) => ({
        ...item,
        unread: false,
        toast_visible: false,
      }));
      setNotifications((current) => {
        const mergedBase = reset ? [] : current;
        const deduped = mergedBase.filter((existing) => !incoming.some((item) => item.id === existing.id));
        return [...deduped, ...incoming].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
      });
      setNotificationHasMore(response.has_more);
      setNotificationOffset(response.offset + response.items.length);
      setNotificationTotal(response.total);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load notifications.");
    } finally {
      setNotificationLoading(false);
    }
  }

  function currentQuoteParam() {
    if (typeof window === "undefined") return null;
    return new URLSearchParams(window.location.search).get("quote");
  }

  function setQuoteParam(quoteToken: string | null, mode: "push" | "replace" = "push") {
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    if (quoteToken) {
      url.searchParams.set("quote", quoteToken);
    } else {
      url.searchParams.delete("quote");
    }
    const next = `${url.pathname}${url.search}${url.hash}`;
    const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    if (next === current) return;
    if (mode === "replace") {
      window.history.replaceState({}, "", next);
    } else {
      window.history.pushState({}, "", next);
    }
  }

  async function openShipmentByQuoteToken(quoteToken: string, options?: { replaceUrl?: boolean }) {
    const normalized = quoteToken.trim().toUpperCase();
    if (!normalized) return;
    const existing = shipments.find((shipment) => shipment.quote_token?.toUpperCase() === normalized);
    if (existing) {
      if (selectedShipmentId === existing.id && drawerOpen) {
        setQuoteParam(existing.quote_token || normalized, options?.replaceUrl ? "replace" : "push");
        return;
      }
      if (selectShipment(existing.id, { openDrawer: true })) {
        setQuoteParam(existing.quote_token || normalized, options?.replaceUrl ? "replace" : "push");
      }
      return;
    }
    if (resolvingQuoteTokenRef.current === normalized) return;
    resolvingQuoteTokenRef.current = normalized;
    try {
      const shipment = await fetchJson<ShipmentRecord>(`/api/freight/shipments/by-token/${encodeURIComponent(normalized)}`);
      mergeShipmentIntoState(shipment);
      setSelectedShipmentId(shipment.id);
      setDrawerOpen(true);
      setDrawerMode("overview");
      setQuoteParam(shipment.quote_token || normalized, options?.replaceUrl ? "replace" : "push");
    } catch {
      setNotice(`Shipment ${normalized} was not found.`);
      setQuoteParam(null, "replace");
    } finally {
      resolvingQuoteTokenRef.current = null;
    }
  }

  function removeShipmentFromState(shipmentId: string) {
    setShipments((current) => {
      const next = current.filter((item) => item.id !== shipmentId);
      if (selectedShipmentId === shipmentId) {
        setSelectedShipmentId(next[0]?.id || null);
      }
      return next;
    });
  }

  async function refreshOverview() {
    const overviewData = await fetchJson<OverviewResponse>("/api/freight/overview");
    setOverview(overviewData);
  }

  async function refreshReviewQueue() {
    const reviewData = await fetchJson<ReviewQueueItem[]>("/api/freight/reviews");
    setReviewQueue(reviewData);
  }

  async function refreshStatusQueue() {
    const statusQueueData = await fetchJson<StatusQueueItem[]>("/api/freight/status-queue?include_resolved=true");
    setStatusQueue(statusQueueData);
    setSelectedStatusTaskId((current) => current && statusQueueData.some((item) => item.task_id === current) ? current : statusQueueData[0]?.task_id || null);
  }

  async function refreshShipmentList(month = selectedBoardMonth) {
    const shipmentData = await fetchJson<ShipmentRecord[]>(`/api/freight/shipments?month=${encodeURIComponent(month)}`);
    setShipments(shipmentData);
    setSelectedShipmentId((current) => {
      if (currentQuoteParam() && current) return current;
      return current && shipmentData.some((item) => item.id === current) ? current : shipmentData[0]?.id || null;
    });
  }

  async function refreshArchivedShipments() {
    const params = new URLSearchParams();
    params.set("month", archiveMonth);
    params.set("limit", "200");
    if (archiveSearch.trim()) {
      params.set("query", archiveSearch.trim());
    }
    if (archiveReasonFilter !== "all") {
      params.set("reason_code", archiveReasonFilter);
    }
    const archiveData = await fetchJson<ShipmentRecord[]>(`/api/freight/shipments/archive?${params.toString()}`);
    setArchivedShipments(archiveData);
  }

  async function refreshSelectedShipment(shipmentId: string) {
    try {
      const shipment = await fetchJson<ShipmentRecord>(`/api/freight/shipments/${shipmentId}`);
      mergeShipmentIntoState(shipment);
      return shipment;
    } catch (refreshError) {
      if (refreshError instanceof Error && refreshError.message.includes("404")) {
        removeShipmentFromState(shipmentId);
        return null;
      }
      throw refreshError;
    }
  }

  async function refreshSelectedShipmentContext(shipmentId: string) {
    await loadShipmentContext(shipmentId);
    if (drawerOpen) {
      await loadShipmentThread(shipmentId, true);
    }
  }

  async function hardRefreshDashboard(options?: { initial?: boolean }) {
    if (options?.initial) {
      setInitialLoading(true);
    } else {
      setBackgroundRefreshing(true);
    }
    setError(null);
    try {
      const [overviewData, clientData, carrierData, shipmentData, reviewData, statusQueueData] = await Promise.all([
        fetchJson<OverviewResponse>("/api/freight/overview"),
        fetchJson<ClientRecord[]>("/api/freight/clients"),
        fetchJson<CarrierRecord[]>("/api/freight/carriers"),
        fetchJson<ShipmentRecord[]>(`/api/freight/shipments?month=${encodeURIComponent(selectedBoardMonth)}`),
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
        setSelectedShipmentId((current) => {
          if (currentQuoteParam() && current) return current;
          return current && shipmentData.some((item) => item.id === current) ? current : shipmentData[0]?.id || null;
        });
        setSelectedStatusTaskId((current) => current && statusQueueData.some((item) => item.task_id === current) ? current : statusQueueData[0]?.task_id || null);
        if (!bidForm.carrier_id && carrierData[0]) {
          setBidForm((current) => ({ ...current, carrier_id: carrierData[0].id }));
        }
      });
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load dashboard.");
    } finally {
      if (options?.initial) {
        setInitialLoading(false);
      } else {
        setBackgroundRefreshing(false);
      }
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

  async function loadShipmentThread(shipmentId: string, force = false) {
    if (!force && threadCache[shipmentId]) {
      setThreadError(null);
      return;
    }
    setThreadLoading(true);
    setThreadError(null);
    try {
      const response = await fetchJson<ShipmentThreadResponse>(`/api/freight/shipments/${shipmentId}/thread`);
      setThreadCache((current) => ({ ...current, [shipmentId]: response }));
    } catch (loadError) {
      setThreadError(loadError instanceof Error ? loadError.message : "Failed to load thread.");
    } finally {
      setThreadLoading(false);
    }
  }

  function enterEditMode(target?: EditFocusTarget) {
    if (!selectedShipment) return;
    setPendingEditFocus(target || null);
    setDrawerMode("edit");
  }

  function clearDrawerContext(shipmentId: string | null) {
    setEvents([]);
    setBids([]);
    setDocuments([]);
    setEvaluation(null);
    setQuotePreview(null);
    setStatusReplyPreview(null);
    setTmsPreview(null);
    setBookingResult(null);
    setThreadError(null);
    setThreadLoading(false);
    setActiveThreadTab("timeline");
    if (!shipmentId) return;
    setThreadCache((current) => {
      if (!(shipmentId in current)) return current;
      const next = { ...current };
      delete next[shipmentId];
      return next;
    });
  }

  function closeDrawer() {
    if (drawerMode === "edit" && shipmentFormDirty) {
      const confirmed = window.confirm("You have unsaved shipment edits. Close without saving?");
      if (!confirmed) return;
      setShipmentEditor(buildShipmentEditor(selectedShipment));
    }
    clearDrawerContext(selectedShipmentId);
    setDrawerOpen(false);
    setDrawerMode("overview");
    setQuoteParam(null);
  }

  function backToOverview() {
    if (shipmentFormDirty) {
      const confirmed = window.confirm("Discard unsaved shipment edits and return to overview?");
      if (!confirmed) return;
      setShipmentEditor(buildShipmentEditor(selectedShipment));
    }
    setDrawerMode("overview");
  }

  function selectShipment(shipmentId: string, options?: { openDrawer?: boolean }) {
    if (drawerMode === "edit" && shipmentFormDirty && shipmentId !== selectedShipmentId) {
      const confirmed = window.confirm("You have unsaved shipment edits. Switch shipments without saving?");
      if (!confirmed) return false;
    }
    setSelectedShipmentId(shipmentId);
    if (options?.openDrawer) {
      setDrawerOpen(true);
      const shipment = shipments.find((item) => item.id === shipmentId);
      const archivedShipment = archivedShipments.find((item) => item.id === shipmentId);
      if (archivedShipment) {
        setQuoteParam(null);
      } else if (shipment?.quote_token) {
        setQuoteParam(shipment.quote_token);
      }
    }
    return true;
  }

  function openNotification(item: NotificationItem) {
    markNotificationRead(item.id);
    if (!item.shipment_id) {
      setNotificationCenterOpen(false);
      return;
    }
    const archivedShipment = archivedShipmentsRef.current.find((shipment) => shipment.id === item.shipment_id);
    if (archivedShipment) {
      setTab("archive");
      setSelectedShipmentId(item.shipment_id);
      setDrawerOpen(true);
      setDrawerMode("overview");
      setQuoteParam(null);
      setNotificationCenterOpen(false);
      return;
    }
    setTab("shipments");
    const existingShipment = shipmentsRef.current.find((shipment) => shipment.id === item.shipment_id);
    if (!existingShipment && item.quote_token) {
      void openShipmentByQuoteToken(item.quote_token);
      setNotificationCenterOpen(false);
      return;
    }
    if (selectShipment(item.shipment_id, { openDrawer: true })) {
      setNotificationCenterOpen(false);
    }
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

  function scheduleDashboardWideBackgroundRefresh() {
    if (overviewRefreshTimerRef.current) {
      clearTimeout(overviewRefreshTimerRef.current);
    }
    overviewRefreshTimerRef.current = setTimeout(() => {
      setBackgroundRefreshing(true);
      void Promise.all([refreshOverview(), refreshReviewQueue(), refreshStatusQueue(), refreshShipmentList()])
        .catch((loadError) => {
          setError(loadError instanceof Error ? loadError.message : "Failed to refresh dashboard.");
        })
        .finally(() => {
          setBackgroundRefreshing(false);
        });
    }, 180);
  }

  useEffect(() => {
    void hardRefreshDashboard({ initial: true });
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const storedFilter = window.localStorage.getItem(BOARD_FILTER_STORAGE_KEY);
    if (storedFilter === "today" || storedFilter === "attention" || storedFilter === "all") {
      setActiveBoardFilter(storedFilter);
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(BOARD_FILTER_STORAGE_KEY, activeBoardFilter);
  }, [activeBoardFilter]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const storedMonth = window.localStorage.getItem(BOARD_MONTH_STORAGE_KEY);
    if (storedMonth && /^\d{4}-\d{2}$/.test(storedMonth)) {
      setSelectedBoardMonth(storedMonth);
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(BOARD_MONTH_STORAGE_KEY, selectedBoardMonth);
  }, [selectedBoardMonth]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const storedControlsState = window.localStorage.getItem(BOARD_CONTROLS_STORAGE_KEY);
    if (storedControlsState === "true") {
      setBoardControlsExpanded(true);
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(BOARD_CONTROLS_STORAGE_KEY, String(boardControlsExpanded));
  }, [boardControlsExpanded]);

  useEffect(() => {
    setMonthPickerYear(Number(selectedBoardMonth.slice(0, 4)));
  }, [selectedBoardMonth]);

  useEffect(() => {
    if (initialLoading || tab !== "shipments") {
      return;
    }
    void refreshShipmentList(selectedBoardMonth).catch((loadError) => {
      setError(loadError instanceof Error ? loadError.message : "Failed to refresh shipments for selected month.");
    });
  }, [selectedBoardMonth]);

  useEffect(() => {
    if (initialLoading || tab !== "archive") {
      return;
    }
    void refreshArchivedShipments().catch((loadError) => {
      setError(loadError instanceof Error ? loadError.message : "Failed to refresh archived shipments.");
    });
  }, [archiveMonth, archiveReasonFilter, archiveSearch, initialLoading, tab]);

  useEffect(() => {
    if (initialLoading) return;
    const quoteToken = currentQuoteParam();
    if (!quoteToken) return;
    void openShipmentByQuoteToken(quoteToken, { replaceUrl: true });
  }, [initialLoading, shipments]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const handlePopState = () => {
      const quoteToken = currentQuoteParam();
      if (quoteToken) {
        void openShipmentByQuoteToken(quoteToken, { replaceUrl: true });
        return;
      }
      setDrawerOpen(false);
      setDrawerMode("overview");
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [shipments, selectedShipmentId, drawerOpen, drawerMode, shipmentFormDirty, selectedShipment]);

  useEffect(() => {
    return () => {
      if (overviewRefreshTimerRef.current) {
        clearTimeout(overviewRefreshTimerRef.current);
      }
      Object.values(notificationTimersRef.current).forEach((timer) => clearTimeout(timer));
    };
  }, []);

  useEffect(() => {
    shipmentsRef.current = shipments;
  }, [shipments]);

  useEffect(() => {
    archivedShipmentsRef.current = archivedShipments;
  }, [archivedShipments]);

  useEffect(() => {
    const activeTimers = notificationTimersRef.current;
    visibleToasts.forEach((item) => {
      if (activeTimers[item.id]) return;
      activeTimers[item.id] = setTimeout(() => {
        hideNotificationToast(item.id);
        delete activeTimers[item.id];
      }, 6500);
    });
    Object.keys(activeTimers).forEach((id) => {
      if (!visibleToasts.some((item) => item.id === id)) {
        clearTimeout(activeTimers[id]);
        delete activeTimers[id];
      }
    });
  }, [visibleToasts]);

  useEffect(() => {
    void loadNotifications({ reset: true });
  }, []);

  useFreightSocket({
    onOverviewStale: () => {
      scheduleDashboardWideBackgroundRefresh();
    },
    onShipmentUpdated: (shipmentId) => {
      void refreshSelectedShipment(shipmentId).catch((loadError) => {
        setError(loadError instanceof Error ? loadError.message : "Failed to refresh shipment.");
      });
      if (shipmentId === selectedShipmentId) {
        void refreshSelectedShipmentContext(shipmentId).catch((loadError) => {
          setError(loadError instanceof Error ? loadError.message : "Failed to refresh shipment context.");
        });
      }
    },
    onWorkflowEvent: ({ shipment_id, event }) => {
      const shipmentSnapshot =
        shipmentsRef.current.find((shipment) => shipment.id === shipment_id) ||
        archivedShipmentsRef.current.find((shipment) => shipment.id === shipment_id) ||
        null;
      const notification = buildNotificationFromWorkflowEvent(event as WorkflowEventRecord, shipmentSnapshot);
      if (notification) {
        appendNotification(notification);
      }
      if (shipment_id === selectedShipmentId) {
        setEvents((prev) =>
          prev.some((e) => e.id === event.id) ? prev : [event as WorkflowEventRecord, ...prev],
        );
        if (refetchShipmentDetailTypes.has(event.event_type)) {
          void refreshSelectedShipmentContext(shipment_id).catch((loadError) => {
            setError(loadError instanceof Error ? loadError.message : "Failed to refresh shipment context.");
          });
        }
      }
      void refreshSelectedShipment(shipment_id).catch((loadError) => {
        setError(loadError instanceof Error ? loadError.message : "Failed to refresh shipment.");
      });
      scheduleDashboardWideBackgroundRefresh();
    },
  });

  useEffect(() => {
    if (!selectedShipmentId) {
      setEvents([]);
      setBids([]);
      setDocuments([]);
      setDrawerMode("overview");
      setThreadError(null);
      return;
    }
    setDrawerMode("overview");
    setEvaluation(null);
    setQuotePreview(null);
    setStatusReplyPreview(null);
    setTmsPreview(null);
    setBookingResult(null);
    setThreadError(null);
    void loadShipmentContext(selectedShipmentId);
  }, [selectedShipmentId]);

  useEffect(() => {
    setActiveThreadTab("timeline");
  }, [selectedShipmentId]);

  useEffect(() => {
    if (!drawerOpen || !selectedShipmentId) {
      return;
    }
    setThreadError(null);
    void loadShipmentThread(selectedShipmentId);
  }, [drawerOpen, selectedShipmentId]);

  useEffect(() => {
    setShipmentEditor(buildShipmentEditor(selectedShipment));
  }, [selectedShipment]);

  useEffect(() => {
    if (drawerMode !== "edit" || !pendingEditFocus) return;
    requestAnimationFrame(() => {
      if (pendingEditFocus === "ready_at") {
        setReadyPickerOpenSignal((current) => current + 1);
        return;
      }
      if (pendingEditFocus === "delivery_at") {
        setDeliveryPickerOpenSignal((current) => current + 1);
        return;
      }
      const field = editFieldRefs.current[pendingEditFocus];
      field?.focus();
      if (field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement) {
        field.select?.();
      }
    });
    setPendingEditFocus(null);
  }, [drawerMode, pendingEditFocus]);

  useEffect(() => {
    const activeSelectedTask = statusQueue.find((item) => item.task_id === selectedStatusTaskId) || null;
    if (!activeSelectedTask) return;
    setStatusReplyDraftSubject(activeSelectedTask.draft_subject || "");
    setStatusReplyDraftBody(activeSelectedTask.draft_body || "");
    setCarrierStatusForm({
      status_text: typeof activeSelectedTask.structured_payload.status_text === "string" ? activeSelectedTask.structured_payload.status_text : "",
      eta_text: typeof activeSelectedTask.structured_payload.eta_text === "string" ? activeSelectedTask.structured_payload.eta_text : "",
      location_text: typeof activeSelectedTask.structured_payload.location_text === "string" ? activeSelectedTask.structured_payload.location_text : "",
      notes: typeof activeSelectedTask.structured_payload.notes === "string" ? activeSelectedTask.structured_payload.notes : "",
    });
  }, [selectedStatusTaskId, statusQueue]);

  useEffect(() => {
    const close = () => setContextMenu(null);
    const handleEsc = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setContextMenu(null);
        setMonthPickerOpen(false);
      }
    };
    const handlePointerDown = (event: MouseEvent) => {
      if (!monthPickerRef.current) return;
      if (!monthPickerRef.current.contains(event.target as Node)) {
        setMonthPickerOpen(false);
      }
    };
    window.addEventListener("click", close);
    window.addEventListener("contextmenu", close);
    window.addEventListener("keydown", handleEsc);
    window.addEventListener("mousedown", handlePointerDown);
    window.addEventListener("scroll", close, true);
    return () => {
      window.removeEventListener("click", close);
      window.removeEventListener("contextmenu", close);
      window.removeEventListener("keydown", handleEsc);
      window.removeEventListener("mousedown", handlePointerDown);
      window.removeEventListener("scroll", close, true);
    };
  }, []);

  useEffect(() => {
    if (!drawerOpen) return;
    drawerScrollRef.current?.scrollTo({ top: 0, behavior: "auto" });
  }, [drawerOpen, selectedShipmentId]);

  async function handleOperatorAction(action: OperatorAction, shipmentId?: string) {
    const targetShipmentId = shipmentId || selectedShipment?.id;
    if (!targetShipmentId) return;
    let reason: string | null = null;
    let suppressSourceThread = true;
    if (action === "archive_shipment") {
      const targetShipment = shipments.find((shipment) => shipment.id === targetShipmentId) || selectedShipment;
      setContextMenu(null);
      setArchiveReasonCode("parsed_error");
      setArchiveReasonNote("invalid shipment from non-delivery email");
      setArchiveDialog({
        shipmentId: targetShipmentId,
        shipmentLabel: targetShipment ? formatRoute(targetShipment) : "this shipment",
      });
      return;
    }
    setSubmitting(action);
    setError(null);
    try {
      const response = await fetchJson<ShipmentOperatorActionResponse>(`/api/freight/shipments/${targetShipmentId}/operator-action`, {
        method: "POST",
        body: JSON.stringify({ action, reason, suppress_source_thread: suppressSourceThread }),
      });
      setNotice(response.message);
      await Promise.all([
        refreshSelectedShipment(targetShipmentId),
        refreshOverview(),
        refreshReviewQueue(),
        refreshStatusQueue(),
      ]);
      if (targetShipmentId === selectedShipmentId) {
        await refreshSelectedShipmentContext(targetShipmentId);
      }
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to run action.");
    } finally {
      setSubmitting(null);
    }
  }

  function updateBoardMonth(nextMonth: string) {
    setSelectedBoardMonth(nextMonth);
  }

  function shiftBoardMonth(delta: number) {
    updateBoardMonth(shiftMonthValue(selectedBoardMonth, delta));
  }

  async function confirmArchiveShipment() {
    if (!archiveDialog) return;
    setSubmitting("archive_shipment");
    setError(null);
    try {
      const response = await fetchJson<ShipmentOperatorActionResponse>(`/api/freight/shipments/${archiveDialog.shipmentId}/operator-action`, {
        method: "POST",
        body: JSON.stringify({
          action: "archive_shipment",
          reason_code: archiveReasonCode,
          reason_note: archiveReasonNote.trim() || null,
          suppress_source_thread: true,
        }),
      });
      setNotice(response.message);
      setDrawerOpen(false);
      setContextMenu(null);
      setArchiveDialog(null);
      removeShipmentFromState(archiveDialog.shipmentId);
      await refreshArchivedShipments();
      await Promise.all([refreshOverview(), refreshReviewQueue(), refreshStatusQueue()]);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to archive shipment.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handleStatusQueueAction(action: StatusQueueAction) {
    if (!selectedStatusTask) return;
    setSubmitting(`status-${action}`);
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
      setSelectedShipmentId(response.shipment_id);
      await Promise.all([
        refreshSelectedShipment(response.shipment_id),
        refreshOverview(),
        refreshStatusQueue(),
      ]);
      await refreshSelectedShipmentContext(response.shipment_id);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to process status task.");
    } finally {
      setSubmitting(null);
    }
  }

  async function persistShipmentEdits() {
    if (!selectedShipment) return false;
    setSubmitting("save_shipment");
    setError(null);
    try {
      const updatedShipment = await fetchJson<ShipmentRecord>(`/api/freight/shipments/${selectedShipment.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          client_id: shipmentEditor.client_id || null,
          status: selectedShipment.status,
          origin: shipmentEditor.origin || null,
          destination: shipmentEditor.destination || null,
          pallets: shipmentEditor.pallets ? Number(shipmentEditor.pallets) : null,
          weight_lb: shipmentEditor.weight_lb ? Number(shipmentEditor.weight_lb) : null,
          equipment_type: shipmentEditor.equipment_type || null,
          ready_at_local: shipmentEditor.ready_at || null,
          delivery_at_local: shipmentEditor.delivery_at || null,
          margin_policy: {
            percent: Number(selectedShipment.margin_policy.percent || 0),
            floor_amount: Number(selectedShipment.margin_policy.floor_amount || 0),
          },
          notes: shipmentEditor.notes,
        }),
      });
      mergeShipmentIntoState(updatedShipment);
      setNotice("Shipment details saved.");
      await Promise.all([
        refreshOverview(),
        refreshReviewQueue(),
        refreshStatusQueue(),
      ]);
      await refreshSelectedShipmentContext(selectedShipment.id);
      setDrawerMode("overview");
      return true;
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to save shipment.");
      return false;
    } finally {
      setSubmitting(null);
    }
  }

  async function runMagicFill(field: "ready_at_local") {
    if (!selectedShipment) return;
    setMagicFillingField(field);
    setError(null);
    setNotice(null);
    try {
      console.debug("[magic-fill] request", {
        shipmentId: selectedShipment.id,
        field,
      });
      const response = await fetchJson<ShipmentMagicFillResponse>(`/api/freight/shipments/${selectedShipment.id}/magic-fill`, {
        method: "POST",
        body: JSON.stringify({
          field,
          apply_value: true,
        }),
      });
      console.debug("[magic-fill] response", response);
      if (response.shipment) {
        mergeShipmentIntoState(response.shipment);
        setShipmentEditor(buildShipmentEditor(response.shipment));
        await refreshSelectedShipmentContext(response.shipment.id);
      }
      setNotice(response.message);
    } catch (actionError) {
      console.error("[magic-fill] failed", actionError);
      setError(actionError instanceof Error ? actionError.message : "Magic fill failed.");
    } finally {
      setMagicFillingField(null);
    }
  }

  async function runStatefulPrimaryAction() {
    if (!selectedShipment || !actionModel?.operatorAction) return;
    if (actionModel.requiresSave || shipmentFormDirty) {
      const saved = await persistShipmentEdits();
      if (!saved) return;
    }
    await handleOperatorAction(actionModel.operatorAction, selectedShipment.id);
  }

  async function handleContextAction(action: ShipmentContextAction) {
    setContextMenu(null);
    if (action.key === "edit") {
      enterEditMode();
      return;
    }
    if (!selectedShipment || !action.operatorAction) return;
    if (action.requiresSave || shipmentFormDirty) {
      const saved = await persistShipmentEdits();
      if (!saved) return;
    }
    await handleOperatorAction(action.operatorAction, selectedShipment.id);
  }

  async function handleCreateShipment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting("create_shipment");
    try {
      const createdShipment = await fetchJson<ShipmentRecord>("/api/freight/shipments", {
        method: "POST",
        body: JSON.stringify({
          client_id: shipmentCreateForm.client_id || null,
          status: "received",
          origin: shipmentCreateForm.origin,
          destination: shipmentCreateForm.destination,
          pallets: Number(shipmentCreateForm.pallets || 0),
          weight_lb: Number(shipmentCreateForm.weight_lb || 0),
          equipment_type: shipmentCreateForm.equipment_type,
          ready_at_local: shipmentCreateForm.ready_at || null,
          delivery_at_local: shipmentCreateForm.delivery_at || null,
          margin_policy: {
            percent: Number(shipmentCreateForm.margin_percent || 0),
            floor_amount: Number(shipmentCreateForm.margin_floor || 0),
          },
          notes: shipmentCreateForm.notes,
        }),
      });
      mergeShipmentIntoState(createdShipment);
      setSelectedShipmentId(createdShipment.id);
      setNotice("Shipment created.");
      await Promise.all([refreshOverview(), refreshReviewQueue(), refreshStatusQueue()]);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to create shipment.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handleCreateClient(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting("create_client");
    try {
      const createdClient = await fetchJson<ClientRecord>("/api/freight/clients", {
        method: "POST",
        body: JSON.stringify({
          name: clientForm.name,
          email: clientForm.email,
          is_active: true,
          default_margin_percent: Number(clientForm.default_margin_percent || 0),
          default_margin_floor: Number(clientForm.default_margin_floor || 0),
        }),
      });
      setClients((current) => [createdClient, ...current]);
      setNotice("Client added.");
      setClientForm({ name: "", email: "", default_margin_percent: "15", default_margin_floor: "0" });
      await refreshOverview();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to create client.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handleCreateCarrier(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting("create_carrier");
    try {
      const createdCarrier = await fetchJson<CarrierRecord>("/api/freight/carriers", {
        method: "POST",
        body: JSON.stringify({
          name: carrierForm.name,
          email: carrierForm.email,
          rating: Number(carrierForm.rating || 0),
          is_active: true,
          regions: carrierForm.regions.split(",").map((item) => item.trim()).filter(Boolean),
          equipment: carrierForm.equipment.split(",").map((item) => item.trim()).filter(Boolean),
          metadata: {},
        }),
      });
      setCarriers((current) => [createdCarrier, ...current]);
      setNotice("Carrier added.");
      setCarrierForm({ name: "", email: "", rating: "0", regions: "midwest,northeast", equipment: "dry van" });
      await refreshOverview();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to create carrier.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handleOutlookSync() {
    setSubmitting("sync");
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
      setLastSyncSummary(response);
      setNotice(`Sync imported ${response.imported} messages and flagged ${response.manual_reviews} review items.`);
      appendNotification(
        createSystemNotification(
          "Outlook sync completed",
          `Imported ${response.imported} messages, parsed ${response.parsed_shipments} shipments, flagged ${response.manual_reviews} review items.`,
        ),
      );
      await hardRefreshDashboard();
      if (selectedShipmentId) {
        await refreshSelectedShipmentContext(selectedShipmentId);
      }
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to sync Outlook.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handleEvaluateBids() {
    if (!selectedShipment) return;
    setSubmitting("evaluate");
    try {
      const response = await fetchJson<EvaluationResponse>(`/api/freight/shipments/${selectedShipment.id}/evaluate`, { method: "POST" });
      setEvaluation(response);
      setNotice(`Best bid selected at $${response.selected_amount.toFixed(2)}.`);
      await Promise.all([
        refreshSelectedShipment(selectedShipment.id),
        refreshOverview(),
      ]);
      await refreshSelectedShipmentContext(selectedShipment.id);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to evaluate bids.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handlePreviewCustomerQuote() {
    if (!selectedShipment) return;
    setSubmitting("quote");
    try {
      const response = await fetchJson<CustomerQuoteResponse>(`/api/freight/shipments/${selectedShipment.id}/quote`, {
        method: "POST",
        body: JSON.stringify({ bid_id: evaluation?.selected_bid_id || selectedWinningBid?.id || null, dry_run: true }),
      });
      setQuotePreview(response);
      setNotice(`Customer quote preview ready at $${response.final_amount.toFixed(2)}.`);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to build quote preview.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handlePreviewStatusReply() {
    if (!selectedShipment) return;
    setSubmitting("status_preview");
    try {
      const response = await fetchJson<CustomerStatusReplyResponse>(`/api/freight/shipments/${selectedShipment.id}/status-reply`, {
        method: "POST",
        body: JSON.stringify({ dry_run: true, custom_message: statusReplyMessage || null }),
      });
      setStatusReplyPreview(response);
      setNotice(`Status reply prepared for ${response.client_email}.`);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to preview status reply.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handlePreviewTmsHandoff() {
    if (!selectedShipment) return;
    setSubmitting("tms");
    try {
      const response = await fetchJson<TmsHandoffResponse>(`/api/freight/shipments/${selectedShipment.id}/tms-handoff`, {
        method: "POST",
        body: JSON.stringify({ bid_id: evaluation?.selected_bid_id || selectedWinningBid?.id || null, dry_run: true }),
      });
      setTmsPreview(response);
      setNotice("TMS handoff preview ready.");
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to preview TMS handoff.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handleBookShipment() {
    if (!selectedShipment) return;
    setSubmitting("book");
    try {
      const response = await fetchJson<BookingExecutionResponse>(`/api/freight/shipments/${selectedShipment.id}/book`, {
        method: "POST",
        body: JSON.stringify({ bid_id: evaluation?.selected_bid_id || selectedWinningBid?.id || null, dry_run: false }),
      });
      setBookingResult(response);
      setNotice(`Shipment booked and confirmation sent to ${response.confirmation.client_email}.`);
      await Promise.all([
        refreshSelectedShipment(selectedShipment.id),
        refreshOverview(),
        refreshStatusQueue(),
      ]);
      await refreshSelectedShipmentContext(selectedShipment.id);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to book shipment.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handleIntakeBid(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedShipment) return;
    setSubmitting("bid");
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
      setNotice("Bid recorded.");
      await Promise.all([
        refreshSelectedShipment(selectedShipment.id),
        refreshOverview(),
      ]);
      await refreshSelectedShipmentContext(selectedShipment.id);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to intake bid.");
    } finally {
      setSubmitting(null);
    }
  }

  const metrics = [
    { label: "Active", value: overview.counts.shipments, detail: "live shipments" },
    { label: "Attention", value: shipments.filter((item) => shipmentNeedsAttention(item)).length, detail: "need operator" },
    { label: "Bids", value: overview.active_stages.waiting_bids || 0, detail: "waiting carriers" },
    { label: "Booked", value: overview.active_stages.booked || 0, detail: "moving loads" },
  ];

  const uniqueReviewShipmentCount = new Set(reviewQueue.map((item) => item.shipment_id)).size;
  const attentionShipmentCount = shipments.filter((item) => shipmentNeedsAttention(item)).length;
  const attentionItems = [
    `${uniqueReviewShipmentCount} shipments in review`,
    `${overview.status_metrics.stale_shipments} stale`,
    `${overview.active_stages.waiting_bids || 0} waiting bids`,
    `${attentionShipmentCount} awaiting operator`,
  ];

  const secondaryActions =
    actionModel?.contextActions.filter(
      (action) => action.operatorAction !== actionModel.operatorAction && action.key !== "archive_shipment",
    ) || [];
  const quickActions = actionModel?.contextActions.filter((action) => action.operatorAction !== actionModel.operatorAction) || [];
  const boardColumns = [
    { key: "parsing", label: "Parsing", accent: "from-teal-300/18 to-teal-500/0" },
    { key: "waiting_bids", label: "Waiting Bids", accent: "from-orange-300/18 to-orange-500/0" },
    { key: "quoted", label: "Quoted", accent: "from-emerald-300/18 to-emerald-500/0" },
    { key: "booked", label: "Booked / Active", accent: "from-cyan-300/18 to-lime-500/0" },
  ] as const;

  const renderShipmentWorkspace = () => {
    if (!selectedShipment) {
      return (
        <div className="flex h-full items-center justify-center p-8 text-sm text-[var(--text-muted)]">
          Select a shipment to open the operator workspace.
        </div>
      );
    }

    const editableMetricCard = (
      label: string,
      value: string,
      onClick: () => void,
      magicAction?: { label: string; tooltip: string; onClick: () => void; loading?: boolean },
    ) => (
      <div
        role="button"
        tabIndex={0}
        onClick={onClick}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onClick();
          }
        }}
        className="rounded-2xl bg-white/5 p-3 text-left transition hover:bg-white/9 hover:ring-1 hover:ring-cyan-200/20"
      >
        <div className="flex items-start justify-between gap-3">
          <p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">{label}</p>
          <span className="text-[10px] uppercase tracking-[0.16em] text-cyan-100/70">Edit</span>
        </div>
        <div className="mt-1.5 flex items-center justify-between gap-2">
          <p className="min-w-0 flex-1 text-white">{value}</p>
          {magicAction && (
            <div className="group/magic relative shrink-0">
              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  magicAction.onClick();
                }}
                disabled={Boolean(magicAction.loading)}
                aria-label={magicAction.loading ? "Reading thread..." : magicAction.label}
                className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-cyan-200/16 bg-cyan-200/8 text-cyan-50 transition hover:bg-cyan-200/14 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Sparkles size={10} className={magicAction.loading ? "animate-pulse" : ""} />
                <span className="sr-only">{magicAction.loading ? "Reading thread..." : magicAction.label}</span>
              </button>
              <div className="pointer-events-none absolute right-0 top-full z-30 mt-1.5 w-72 translate-y-1 rounded-xl border border-cyan-200/18 bg-slate-950/95 px-3 py-2 text-[11px] leading-4 text-slate-200 opacity-0 shadow-xl transition group-hover/magic:translate-y-0 group-hover/magic:opacity-100 group-focus-within/magic:translate-y-0 group-focus-within/magic:opacity-100">
                {magicAction.tooltip}
              </div>
            </div>
          )}
        </div>
      </div>
    );

    if (selectedShipment.is_archived) {
      return (
        <div className="flex flex-col gap-4">
          <div className="rounded-[28px] border border-amber-300/18 bg-amber-300/[0.06] p-5">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full border border-amber-300/20 bg-amber-300/12 px-3 py-1 text-xs text-amber-100">
                Archived
              </span>
              <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-[var(--text-muted)]">
                {archiveReasonLabel(selectedShipment.archive_reason_code)}
              </span>
              <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-[var(--text-muted)]">
                {selectedShipment.quote_token || "No quote token"}
              </span>
            </div>
            <h2 className="mt-4 text-2xl font-semibold tracking-[-0.04em] text-white">{formatRoute(selectedShipment)}</h2>
            <p className="mt-2 text-sm leading-6 text-slate-300">
              This shipment is archived and excluded from active automation, board counters, active search, and active agent tools.
            </p>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div className="rounded-2xl bg-white/5 p-4">
                <p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Archive note</p>
                <p className="mt-2 text-white">{selectedShipment.archive_reason_note || selectedShipment.archived_reason || "No note"}</p>
              </div>
              <div className="rounded-2xl bg-white/5 p-4">
                <p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Archived at</p>
                <p className="mt-2 text-white">{formatDate(selectedShipment.archived_at)}</p>
              </div>
              <div className="rounded-2xl bg-white/5 p-4">
                <p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Original status</p>
                <p className="mt-2 text-white capitalize">{selectedShipment.status.replaceAll("_", " ")}</p>
              </div>
              <div className="rounded-2xl bg-white/5 p-4">
                <p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Source thread</p>
                <p className="mt-2 break-all text-white">{selectedShipment.email_thread_id || "No linked thread"}</p>
              </div>
            </div>
          </div>
          <div className="rounded-[28px] border border-white/10 bg-white/[0.03] p-5">
            <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Archive timeline</p>
            <div className="mt-4 space-y-3">
              {events.length === 0 && <div className="rounded-2xl border border-dashed border-white/10 bg-white/5 p-5 text-sm text-[var(--text-muted)]">No archive events loaded yet.</div>}
              {events.map((eventRecord) => (
                <div key={eventRecord.id} className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-white">{eventRecord.event_type.replaceAll("_", " ")}</p>
                    <span className="text-xs text-[var(--text-muted)]">{formatDate(eventRecord.created_at)}</span>
                  </div>
                  {typeof eventRecord.payload.reason === "string" && (
                    <p className="mt-2 text-sm text-[var(--text-muted)]">{eventRecord.payload.reason}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      );
    }

    if (drawerMode === "edit") {
      const fieldLabelClass = "mb-2 block text-[11px] uppercase tracking-[0.16em] text-[var(--text-muted)]";

      return (
        <div className="rounded-[28px] border border-white/10 bg-white/[0.03] p-5">
          <div className="mb-4">
            <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Edit shipment</p>
            <h3 className="mt-1 text-xl font-semibold text-white">{formatRoute(selectedShipment)}</h3>
            <p className="mt-2 text-sm leading-6 text-[var(--text-muted)]">
              Correct shipment values here while the linked email thread stays visible in the context rail.
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className={fieldLabelClass}>Linked customer</span>
              <select
                ref={(node) => {
                  editFieldRefs.current.client_id = node;
                }}
                className="field-input"
                value={shipmentEditor.client_id}
                onChange={(event) => setShipmentEditor((current) => ({ ...current, client_id: event.target.value }))}
              >
                <option value="">No linked customer</option>
                {clients.map((client) => <option key={client.id} value={client.id}>{client.name}</option>)}
              </select>
            </label>
            <label className="block">
              <span className={fieldLabelClass}>Equipment type</span>
              <input
                ref={(node) => {
                  editFieldRefs.current.equipment_type = node;
                }}
                className="field-input"
                placeholder="Dry Van, Reefer, Flatbed..."
                value={shipmentEditor.equipment_type}
                onChange={(event) => setShipmentEditor((current) => ({ ...current, equipment_type: event.target.value }))}
              />
            </label>
            <label className="block">
              <span className={fieldLabelClass}>Origin</span>
              <input
                ref={(node) => {
                  editFieldRefs.current.origin = node;
                }}
                className="field-input"
                placeholder="Chicago, IL"
                value={shipmentEditor.origin}
                onChange={(event) => setShipmentEditor((current) => ({ ...current, origin: event.target.value }))}
              />
            </label>
            <label className="block">
              <span className={fieldLabelClass}>Destination</span>
              <input
                ref={(node) => {
                  editFieldRefs.current.destination = node;
                }}
                className="field-input"
                placeholder="New York, NY"
                value={shipmentEditor.destination}
                onChange={(event) => setShipmentEditor((current) => ({ ...current, destination: event.target.value }))}
              />
            </label>
            <label className="block">
              <span className={fieldLabelClass}>Pallets</span>
              <input
                ref={(node) => {
                  editFieldRefs.current.pallets = node;
                }}
                className="field-input"
                inputMode="numeric"
                placeholder="5"
                value={shipmentEditor.pallets}
                onChange={(event) => setShipmentEditor((current) => ({ ...current, pallets: event.target.value }))}
              />
            </label>
            <label className="block">
              <span className={fieldLabelClass}>Weight (lb)</span>
              <input
                ref={(node) => {
                  editFieldRefs.current.weight_lb = node;
                }}
                className="field-input"
                inputMode="decimal"
                placeholder="10000"
                value={shipmentEditor.weight_lb}
                onChange={(event) => setShipmentEditor((current) => ({ ...current, weight_lb: event.target.value }))}
              />
            </label>
            <label className="block sm:col-span-2">
              <span className={fieldLabelClass}>Ready time</span>
              <DateTimePickerField
                value={shipmentEditor.ready_at}
                placeholder="Choose pickup-ready time"
                autoOpenSignal={readyPickerOpenSignal}
                onChange={(nextValue) => setShipmentEditor((current) => ({ ...current, ready_at: nextValue }))}
              />
            </label>
            {shipmentShowsDeliveryTime(selectedShipment) && (
              <label className="block sm:col-span-2">
                <span className={fieldLabelClass}>Delivery time</span>
                <DateTimePickerField
                  value={shipmentEditor.delivery_at}
                  placeholder="Choose delivery time"
                  autoOpenSignal={deliveryPickerOpenSignal}
                  onChange={(nextValue) => setShipmentEditor((current) => ({ ...current, delivery_at: nextValue }))}
                />
              </label>
            )}
            <label className="block sm:col-span-2">
              <span className={fieldLabelClass}>Operator notes</span>
              <textarea
                ref={(node) => {
                  editFieldRefs.current.notes = node;
                }}
                className="field-input min-h-[140px] resize-none"
                placeholder="Shipment notes, handling requirements, clarification details..."
                value={shipmentEditor.notes}
                onChange={(event) => setShipmentEditor((current) => ({ ...current, notes: event.target.value }))}
              />
            </label>
          </div>
          <div className="mt-5 border-t border-white/10 pt-4">
            <div className="grid gap-2 sm:grid-cols-2">
              <button
                onClick={backToOverview}
                className="action-button w-full border border-white/15 bg-white/8 px-4 py-2.5 text-sm font-medium text-white hover:bg-white/14"
              >
                Back to overview
              </button>
              <button
                onClick={() => void persistShipmentEdits()}
                disabled={!shipmentFormDirty || submitting !== null}
                className="action-button w-full bg-[var(--accent-cyan)] px-4 py-2.5 text-sm font-semibold text-slate-950 shadow-[0_10px_24px_rgba(103,232,249,0.24)] hover:brightness-110 disabled:opacity-50"
              >
                {submitting === "save_shipment" ? "Saving..." : "Save changes"}
              </button>
            </div>
          </div>
        </div>
      );
    }

    return (
      <div className="flex flex-col gap-4">
        <div className="rounded-[28px] border border-white/10 bg-white/[0.03] px-5 pb-5 pt-3.5">
          <div className="flex flex-col gap-4">
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <ShipmentStatusPill status={selectedShipment.status} />
                {shipmentNeedsAttention(selectedShipment) && (
                  <span className="rounded-full border border-amber-300/20 bg-amber-300/10 px-3 py-1 text-xs text-amber-100">
                    {shipmentBlockingBadge(selectedShipment)}
                  </span>
                )}
                <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-[var(--text-muted)]">
                  {selectedShipment.quote_token || "No quote token"}
                </span>
              </div>
              <div>
                <h2 className="text-2xl font-semibold tracking-[-0.04em] text-white">{formatRoute(selectedShipment)}</h2>
                <p className="mt-2 text-sm text-[var(--text-muted)]">
                  Customer {selectedShipment.client_id ? "linked" : "not linked"} • Created {formatDate(selectedShipment.created_at)} • Confidence {formatConfidence(selectedShipment.ai_confidence)} • Last agent decision {selectedShipment.next_step_label || selectedShipment.ai_next_action || "pending"}
                </p>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                {editableMetricCard("Pallets", String(selectedShipment.pallets ?? "--"), () => enterEditMode("pallets"))}
                {editableMetricCard("Weight", `${selectedShipment.weight_lb ?? "--"} lb`, () => enterEditMode("weight_lb"))}
                {editableMetricCard("Equipment", selectedShipment.equipment_type || "--", () => enterEditMode("equipment_type"))}
                {editableMetricCard(
                  "Ready",
                  formatShipmentSchedule(selectedShipment.ready_at_display, selectedShipment.ready_at_local),
                  () => enterEditMode("ready_at"),
                  {
                    label: "Auto-fill from thread",
                    tooltip:
                      "We will re-read the customer email thread and try to auto-fill this field if the required details are present in the messages.",
                    onClick: () => void runMagicFill("ready_at_local"),
                    loading: magicFillingField === "ready_at_local",
                  },
                )}
                {shipmentShowsDeliveryTime(selectedShipment) &&
                  editableMetricCard("Delivery", formatShipmentSchedule(selectedShipment.delivery_at_display, selectedShipment.delivery_at_local), () => enterEditMode("delivery_at"))}
              </div>
            </div>
            <div className="rounded-[24px] border border-white/10 bg-slate-950/35 p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">What happens next</p>
              <h3 className="mt-2 text-xl font-semibold text-white">{actionModel?.label || "Operator input needed"}</h3>
              <p className="mt-2 text-sm leading-6 text-[var(--text-muted)]">{actionModel?.reason}</p>
              {actionModel?.blockingReason && (
                <div className="mt-3 rounded-2xl border border-amber-300/20 bg-amber-300/10 px-3 py-3 text-sm text-amber-50">
                  {actionModel.blockingReason}
                </div>
              )}
              <div className="mt-4 flex flex-col gap-3">
                {actionModel?.label ? (
                  <button
                    onClick={() => void runStatefulPrimaryAction()}
                    disabled={!actionModel.operatorAction || submitting !== null}
                    className="action-button w-full bg-[var(--accent-cyan)] text-slate-950 hover:brightness-110 disabled:opacity-50"
                  >
                    {submitting ? "Working..." : actionModel.label}
                  </button>
                ) : (
                  <button
                    onClick={() => enterEditMode()}
                    disabled={submitting !== null}
                    className="action-button w-full bg-white/10 text-white hover:bg-white/15 disabled:opacity-50"
                  >
                    Edit shipment
                  </button>
                )}
                <p className="text-xs text-[var(--text-muted)]">
                  The main button always maps to the current shipment state.
                </p>
              </div>
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-4">
          <div className="rounded-[28px] border border-white/10 bg-white/[0.03] p-5">
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Operational context</p>
                  <h3 className="mt-1 text-xl font-semibold text-white">Open only what you need</h3>
                </div>
                <div className="flex flex-wrap gap-2">
                  {(["overview", "bids", "timeline", "status", "docs"] as WorkspaceSection[]).map((section) => (
                    <button
                      key={section}
                      onClick={() => setWorkspaceSection(section)}
                      className={`rounded-full px-3 py-2 text-xs capitalize transition ${workspaceSection === section ? "bg-white text-slate-950" : "bg-white/5 text-[var(--text-muted)] hover:bg-white/10 hover:text-white"}`}
                    >
                      {section}
                    </button>
                  ))}
                </div>
              </div>

              {workspaceSection === "overview" && (
                <div className="space-y-4">
                  <div className="grid gap-3 md:grid-cols-2">
                    <div className="rounded-2xl bg-white/5 p-4">
                      <p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">AI parsing</p>
                      <p className="mt-2 text-white">Intent: {selectedShipment.ai_intent || "not classified"}</p>
                      <p className="mt-1 text-sm text-[var(--text-muted)]">Confidence: {formatConfidence(selectedShipment.ai_confidence)}</p>
                      {selectedShipment.ai_missing_fields.length > 0 && (
                        <div className="mt-3 flex flex-wrap gap-2">
                          {selectedShipment.ai_missing_fields.map((field) => (
                            <span key={field} className="rounded-full bg-amber-300/10 px-3 py-1 text-xs text-amber-100">{field}</span>
                          ))}
                        </div>
                      )}
                    </div>
                    <div className="rounded-2xl bg-white/5 p-4">
                      <p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Operator context</p>
                      <p className="mt-2 text-white">Review required: {selectedShipment.has_active_review ? "yes" : "no"}</p>
                      <p className="mt-1 text-sm text-[var(--text-muted)]">Next agent action: {selectedShipment.next_step_label || selectedShipment.ai_next_action || "pending"}</p>
                      {selectedShipment.ai_ambiguity_reasons.length > 0 && (
                        <div className="mt-3 flex flex-wrap gap-2">
                          {selectedShipment.ai_ambiguity_reasons.map((reason) => (
                            <span key={reason} className="rounded-full bg-rose-300/10 px-3 py-1 text-xs text-rose-100">{reason.replaceAll("_", " ")}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>

                  {quotePreview && (
                    <div className="rounded-2xl border border-emerald-300/20 bg-emerald-300/10 p-4">
                      <p className="text-xs uppercase tracking-[0.16em] text-emerald-100">Customer quote preview</p>
                      <p className="mt-2 text-white">{quotePreview.subject}</p>
                      <p className="mt-2 whitespace-pre-wrap text-sm text-emerald-50">{quotePreview.body}</p>
                    </div>
                  )}

                  {bookingResult && (
                    <div className="rounded-2xl border border-lime-300/20 bg-lime-300/10 p-4">
                      <p className="text-xs uppercase tracking-[0.16em] text-lime-100">Booking result</p>
                      <p className="mt-2 text-white">TMS status: {bookingResult.handoff.status}</p>
                      <p className="mt-1 text-sm text-lime-50">Confirmation sent to {bookingResult.confirmation.client_email}</p>
                    </div>
                  )}
                </div>
              )}

              {workspaceSection === "bids" && (
                <div className="space-y-4">
                  <div className="grid gap-3 md:grid-cols-3">
                    <button onClick={() => void handleEvaluateBids()} disabled={bids.length === 0 || submitting !== null} className="action-button bg-white/10 text-white hover:bg-white/15 disabled:opacity-50">
                      Evaluate bids
                    </button>
                    <button onClick={() => void handlePreviewCustomerQuote()} disabled={bids.length === 0 || submitting !== null} className="action-button bg-cyan-300/15 text-cyan-100 hover:bg-cyan-300/20 disabled:opacity-50">
                      Preview customer quote
                    </button>
                    <button onClick={() => void handleBookShipment()} disabled={bids.length === 0 || submitting !== null} className="action-button bg-emerald-300/15 text-emerald-100 hover:bg-emerald-300/20 disabled:opacity-50">
                      Book shipment
                    </button>
                  </div>
                  {evaluation && (
                    <div className="rounded-2xl bg-cyan-300/10 p-4 text-sm">
                      Winner: {selectedWinningBid?.carrier_name || "selected bid"} at ${evaluation.selected_amount.toFixed(2)}. Customer quote: ${evaluation.recommended_quote_amount.toFixed(2)}.
                    </div>
                  )}
                  <div className="space-y-3">
                    {bids.length === 0 && <div className="rounded-2xl border border-dashed border-white/10 bg-white/5 p-5 text-sm text-[var(--text-muted)]">No bids captured yet.</div>}
                    {bids.map((bid) => (
                      <div key={bid.id} className="rounded-2xl border border-white/10 bg-white/5 p-4">
                        <div className="flex items-center justify-between gap-3">
                          <div>
                            <p className="text-white">{bid.carrier_name}</p>
                            <p className="text-xs text-[var(--text-muted)]">{bid.carrier_email}</p>
                          </div>
                          <span className="rounded-full bg-white/10 px-3 py-1 text-xs text-white">{bid.status}</span>
                        </div>
                        <div className="mt-3 grid gap-3 sm:grid-cols-3 text-sm">
                          <div><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Amount</p><p className="mt-1 text-white">{bid.amount ? `$${bid.amount.toFixed(2)}` : "--"}</p></div>
                          <div><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">ETA</p><p className="mt-1 text-white">{bid.eta_text || "--"}</p></div>
                          <div><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Score</p><p className="mt-1 text-white">{bid.score.total ?? "--"}</p></div>
                        </div>
                      </div>
                    ))}
                  </div>

                  <form className="rounded-2xl bg-white/5 p-4" onSubmit={handleIntakeBid}>
                    <p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Manual bid intake</p>
                    <div className="mt-3 grid gap-3 sm:grid-cols-2">
                      <select className="field-input" value={bidForm.carrier_id} onChange={(event) => setBidForm((current) => ({ ...current, carrier_id: event.target.value }))}>
                        {carriers.map((carrier) => <option key={carrier.id} value={carrier.id}>{carrier.name}</option>)}
                      </select>
                      <input className="field-input" value={bidForm.amount} onChange={(event) => setBidForm((current) => ({ ...current, amount: event.target.value }))} placeholder="Amount" />
                      <input className="field-input sm:col-span-2" value={bidForm.eta_text} onChange={(event) => setBidForm((current) => ({ ...current, eta_text: event.target.value }))} placeholder="ETA / timing" />
                      <textarea className="field-input min-h-[100px] resize-none sm:col-span-2" value={bidForm.raw_email} onChange={(event) => setBidForm((current) => ({ ...current, raw_email: event.target.value }))} placeholder="Carrier reply" />
                    </div>
                    <button className="action-button mt-3 bg-white/10 text-white hover:bg-white/15" disabled={submitting !== null}>Record bid</button>
                  </form>
                </div>
              )}

              {workspaceSection === "timeline" && (
                <div className="space-y-3">
                  {events.length === 0 && <div className="rounded-2xl border border-dashed border-white/10 bg-white/5 p-5 text-sm text-[var(--text-muted)]">No shipment events yet.</div>}
                  {events.map((eventRecord) => (
                    <div key={eventRecord.id} className="rounded-2xl border border-white/10 bg-white/5 p-4">
                      <div className="flex items-center justify-between gap-3">
                        <p className="text-white">{eventRecord.event_type.replaceAll("_", " ")}</p>
                        <span className="text-xs text-[var(--text-muted)]">{formatDate(eventRecord.created_at)}</span>
                      </div>
                      <p className="mt-1 text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">{eventRecord.stage.replaceAll("_", " ")}</p>
                      {typeof eventRecord.payload.reason === "string" && (
                        <p className="mt-2 text-sm text-[var(--text-muted)]">{eventRecord.payload.reason}</p>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {workspaceSection === "status" && (
                <div className="space-y-4">
                  <div className="grid gap-3 sm:grid-cols-4">
                    <div className="rounded-2xl bg-white/5 p-4"><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Status</p><p className="mt-2 text-white">{selectedShipment.last_known_status || "Unknown"}</p></div>
                    <div className="rounded-2xl bg-white/5 p-4"><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">ETA</p><p className="mt-2 text-white">{selectedShipment.last_known_eta || "Not available"}</p></div>
                    <div className="rounded-2xl bg-white/5 p-4"><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Location</p><p className="mt-2 text-white">{selectedShipment.last_known_location || "Not available"}</p></div>
                    <div className="rounded-2xl bg-white/5 p-4"><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Age</p><p className="mt-2 text-white">{formatAge(selectedShipment.last_status_event_at)}</p></div>
                  </div>
                  <div className="grid gap-3 md:grid-cols-3">
                    <button onClick={() => void handleOperatorAction("rerun_status_lookup")} disabled={submitting !== null} className="action-button bg-cyan-300/15 text-cyan-100 hover:bg-cyan-300/20 disabled:opacity-50">Re-run status lookup</button>
                    <button onClick={() => void handlePreviewStatusReply()} disabled={submitting !== null} className="action-button bg-white/10 text-white hover:bg-white/15 disabled:opacity-50">Preview status reply</button>
                    <button onClick={() => void handlePreviewTmsHandoff()} disabled={submitting !== null} className="action-button bg-rose-300/15 text-rose-100 hover:bg-rose-300/20 disabled:opacity-50">Preview TMS handoff</button>
                  </div>
                  <textarea className="field-input min-h-[100px] resize-none" value={statusReplyMessage} onChange={(event) => setStatusReplyMessage(event.target.value)} placeholder="Optional note for customer status reply" />
                  {statusReplyPreview && (
                    <div className="rounded-2xl border border-cyan-300/20 bg-cyan-300/10 p-4">
                      <p className="text-white">{statusReplyPreview.subject}</p>
                      <p className="mt-2 whitespace-pre-wrap text-sm text-cyan-50">{statusReplyPreview.body}</p>
                    </div>
                  )}
                  {tmsPreview && (
                    <pre className="overflow-x-auto rounded-2xl border border-rose-300/20 bg-rose-300/10 p-4 text-xs text-rose-50">
                      {JSON.stringify(tmsPreview.payload, null, 2)}
                    </pre>
                  )}
                </div>
              )}

              {workspaceSection === "docs" && (
                <div className="space-y-4">
                  <div className="grid gap-3 md:grid-cols-3">
                    <button onClick={() => void handleOperatorAction("rerun_document_extraction")} disabled={submitting !== null} className="action-button bg-cyan-300/15 text-cyan-100 hover:bg-cyan-300/20 disabled:opacity-50">Re-run document extraction</button>
                    <button onClick={() => void handleOperatorAction("approve_document_values")} disabled={submitting !== null} className="action-button bg-emerald-300/15 text-emerald-100 hover:bg-emerald-300/20 disabled:opacity-50">Approve document values</button>
                    <button onClick={() => void handleOperatorAction("ignore_document_warning")} disabled={submitting !== null} className="action-button bg-amber-300/15 text-amber-100 hover:bg-amber-300/20 disabled:opacity-50">Ignore warning</button>
                  </div>
                  {documents.length === 0 && <div className="rounded-2xl border border-dashed border-white/10 bg-white/5 p-5 text-sm text-[var(--text-muted)]">No attachment metadata yet.</div>}
                  {documents.map((document) => (
                    <div key={`${document.id || document.name || "doc"}`} className="rounded-2xl border border-white/10 bg-white/5 p-4">
                      <div className="flex items-center justify-between gap-3">
                        <p className="text-white">{document.name || "Unnamed attachment"}</p>
                        <span className="rounded-full bg-cyan-300/10 px-3 py-1 text-xs text-cyan-100">{document.document_type.replaceAll("_", " ")}</span>
                      </div>
                      <div className="mt-2 flex flex-wrap gap-2 text-xs text-[var(--text-muted)]">
                        {document.extraction_method && <span>{document.extraction_method.replaceAll("_", " ")}</span>}
                        {document.ocr_status && <span>OCR: {document.ocr_status.replaceAll("_", " ")}</span>}
                        <span>OCR confidence: {formatConfidence(document.ocr_confidence)}</span>
                        <span>Field confidence: {formatConfidence(document.field_confidence)}</span>
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
                      {document.review_reason && <p className="mt-3 text-sm text-amber-100">{document.review_reason}</p>}
                      {document.extracted_text_preview && <p className="mt-3 text-sm text-[var(--text-muted)]">{document.extracted_text_preview}</p>}
                    </div>
                  ))}
                </div>
              )}
          </div>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr),220px]">
            <div className="rounded-[28px] border border-white/10 bg-white/[0.03] p-5">
              <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Secondary actions</p>
              <div className="mt-4 grid gap-2">
                {secondaryActions.length === 0 && (
                  <div className="rounded-2xl border border-dashed border-white/10 bg-white/5 p-4 text-sm text-[var(--text-muted)]">
                    No secondary actions for this shipment right now.
                  </div>
                )}
                {secondaryActions.map((action) => (
                  <button
                    key={action.key}
                    onClick={() => void handleContextAction(action)}
                    disabled={submitting !== null}
                    className={`action-button justify-start disabled:opacity-50 ${
                      action.tone === "warning"
                        ? "bg-amber-300/12 text-amber-100 hover:bg-amber-300/18"
                        : "bg-white/10 text-white hover:bg-white/15"
                    }`}
                  >
                    {action.label}
                  </button>
                ))}
              </div>
              {selectedShipment && (
                <div className="mt-4 rounded-[20px] border border-amber-300/18 bg-amber-300/6 p-3">
                  <div className="flex items-center gap-3">
                    <div className="rounded-full bg-amber-300/12 p-2 text-amber-100">
                      <Archive size={16} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium leading-5 text-amber-50">Archive invalid shipment</p>
                      <p className="text-xs leading-5 text-amber-100/70">
                        Remove from live board and ignore its source thread on future syncs.
                      </p>
                    </div>
                    <button
                      onClick={() => void handleOperatorAction("archive_shipment", selectedShipment.id)}
                      disabled={submitting !== null}
                      className="action-button shrink-0 bg-amber-300/16 px-3 py-2 text-sm text-amber-50 hover:bg-amber-300/22 disabled:opacity-50"
                    >
                      <Archive size={14} className="mr-2" /> Archive
                    </button>
                  </div>
                </div>
              )}
            </div>

            <div className="rounded-[28px] border border-white/10 bg-white/[0.03] p-5">
              <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Quick health</p>
              <div className="mt-4 space-y-3 text-sm">
                <div className="rounded-2xl bg-white/5 p-4">
                  <p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Status workflow</p>
                  <p className="mt-2 text-white">{selectedShipment.status_workflow_state || "not active"}</p>
                </div>
                <div className="rounded-2xl bg-white/5 p-4">
                  <p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Booking</p>
                  <p className="mt-2 text-white">{selectedShipment.booking_state || "not started"}</p>
                </div>
                <div className="rounded-2xl bg-white/5 p-4">
                  <p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Documents</p>
                  <p className="mt-2 text-white">{selectedShipment.attachment_count} attachments</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  };

  const renderThreadRail = () => {
    if (!drawerOpen || !selectedShipment) {
      return null;
    }

    return (
      <aside className="pointer-events-auto fixed top-6 right-[calc(50vw+160px)] bottom-6 z-[45] hidden w-[475px] overflow-hidden rounded-[30px] border border-cyan-300/14 bg-[linear-gradient(135deg,rgba(7,15,25,0.94),rgba(11,23,37,0.9)_46%,rgba(17,34,52,0.92)),radial-gradient(circle_at_0%_0%,rgba(108,213,255,0.13),transparent_28%),radial-gradient(circle_at_100%_0%,rgba(61,139,255,0.11),transparent_24%)] shadow-[-20px_22px_80px_rgba(0,0,0,0.32)] backdrop-blur-xl xl:flex">
        <div className="flex h-full min-h-0 w-full flex-col">
          <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(90deg,transparent,rgba(120,210,255,0.05)_18%,transparent_38%,transparent_62%,rgba(120,210,255,0.04)_82%,transparent)]" />
          <div className="pointer-events-none absolute inset-y-0 left-[22%] w-px bg-cyan-200/8" />
          <div className="pointer-events-none absolute inset-y-0 right-[24%] w-px bg-cyan-200/8" />

          <div className="relative border-b border-cyan-200/10 px-5 py-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="inline-flex h-8 items-center gap-2 rounded-[10px] border border-cyan-200/16 bg-cyan-200/6 px-3 text-[10px] uppercase tracking-[0.24em] text-cyan-100">
                  Thread context
                </div>
                <h3 className="mt-1 break-words text-lg font-semibold text-white">
                  {threadData?.thread_subject || formatRoute(selectedShipment)}
                </h3>
                <p className="mt-2 break-all text-sm text-[var(--text-muted)]">
                  {threadData?.quote_token || selectedShipment.quote_token || "No quote token"}
                </p>
              </div>
              <button
                onClick={() => void loadShipmentThread(selectedShipment.id, true)}
                disabled={threadLoading}
                className="action-button shrink-0 border border-cyan-200/16 bg-cyan-200/10 px-3 py-2 text-cyan-50 hover:bg-cyan-200/18 disabled:opacity-50"
              >
                {threadLoading ? "Loading..." : "Refresh"}
              </button>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {([
                { key: "timeline", label: "Timeline" },
                { key: "client", label: "Customer" },
                { key: "carrier_quotes", label: "Carrier Quotes" },
                { key: "system", label: "System" },
              ] as const).map((tab) => (
                <button
                  key={tab.key}
                  type="button"
                  onClick={() => setActiveThreadTab(tab.key)}
                  className={`rounded-[10px] px-3 py-2 text-[10px] uppercase tracking-[0.18em] transition ${
                    activeThreadTab === tab.key
                      ? "bg-cyan-100 text-slate-950"
                      : "border border-cyan-200/10 bg-slate-950/22 text-slate-300 hover:bg-cyan-200/8 hover:text-white"
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          </div>

          <div className="relative min-h-0 flex-1 overflow-x-hidden overflow-y-auto px-5 py-4">
            {threadLoading && !threadData && (
              <div className="space-y-3">
                {[1, 2, 3].map((item) => (
                  <div key={item} className="animate-pulse rounded-2xl border border-white/8 bg-white/5 p-4">
                    <div className="h-4 w-40 rounded bg-white/10" />
                    <div className="mt-3 h-3 w-full rounded bg-white/10" />
                    <div className="mt-2 h-3 w-4/5 rounded bg-white/10" />
                  </div>
                ))}
              </div>
            )}

            {!threadLoading && threadError && (
              <div className="rounded-2xl border border-rose-300/20 bg-rose-300/10 p-4 text-sm text-rose-100">
                <p>{threadError}</p>
                <button
                  onClick={() => void loadShipmentThread(selectedShipment.id, true)}
                  className="mt-3 text-sm font-medium text-white underline decoration-white/30 underline-offset-4"
                >
                  Retry thread load
                </button>
              </div>
            )}

            {!threadLoading && !threadError && (!threadData || threadData.messages.length === 0) && (
              <div className="rounded-2xl border border-dashed border-white/10 bg-white/5 p-5 text-sm text-[var(--text-muted)]">
                No linked email thread.
              </div>
            )}

            {!threadLoading && !threadError && threadData && threadData.messages.length > 0 && filteredThreadMessages.length === 0 && (
              <div className="rounded-2xl border border-dashed border-white/10 bg-white/5 p-5 text-sm text-[var(--text-muted)]">
                {activeThreadTab === "client" && "No customer conversation found for this shipment yet."}
                {activeThreadTab === "carrier_quotes" && "No carrier quote conversation found for this shipment yet."}
                {activeThreadTab === "system" && "No system or delivery-failure messages found for this shipment."}
              </div>
            )}

            {!threadLoading && !threadError && threadData && filteredThreadMessages.length > 0 && (
              <div className="space-y-4">
                {filteredThreadMessages.map((message) => {
                  const visual = threadMessageVisual(message);
                  return (
                    <div key={message.id} className={`min-w-0 overflow-hidden rounded-2xl border p-4 ${visual.card}`}>
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <p className="break-all text-sm font-medium text-white">{message.sender}</p>
                            <span className="rounded-full border border-white/10 bg-white/[0.05] px-2.5 py-1 text-[10px] uppercase tracking-[0.16em] text-slate-300">
                              {visual.label}
                            </span>
                          </div>
                          {message.recipients.length > 0 && (
                            <p className="mt-1 break-all text-xs uppercase tracking-[0.14em] text-[var(--text-muted)]">
                              To: {message.recipients.join(", ")}
                            </p>
                          )}
                          <p className="mt-1 text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">
                            {formatDate(message.received_at)}
                          </p>
                        </div>
                      </div>
                      <p className="mt-3 break-words text-sm font-medium text-white">{message.subject || "No subject"}</p>
                      <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-6 text-slate-200 [overflow-wrap:anywhere]">
                        {message.display_body || message.body_preview || "No message text available."}
                      </p>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </aside>
    );
  };

  const renderNotificationIcon = (kind: NotificationKind) => {
    if (kind === "email") return <Mail size={16} />;
    if (kind === "shipment") return <Package2 size={16} />;
    if (kind === "bid") return <CircleDollarSign size={16} />;
    if (kind === "review") return <AlertTriangle size={16} />;
    if (kind === "status") return <RadioTower size={16} />;
    if (kind === "archive") return <Archive size={16} />;
    return <Bell size={16} />;
  };

  return (
    <main className="min-h-screen px-4 py-5 text-[var(--text-main)] sm:px-6 lg:px-8">
      <div className="mx-auto max-w-[1540px] space-y-4">
        <section className="relative overflow-hidden rounded-[18px] border border-cyan-300/12 bg-[linear-gradient(135deg,rgba(7,15,25,0.96),rgba(11,23,37,0.92)_46%,rgba(17,34,52,0.94)),radial-gradient(circle_at_0%_0%,rgba(108,213,255,0.14),transparent_26%),radial-gradient(circle_at_100%_0%,rgba(61,139,255,0.12),transparent_24%)] px-4 py-4 shadow-[0_18px_60px_rgba(0,0,0,0.26)] sm:px-5">
          <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(90deg,transparent,rgba(120,210,255,0.05)_18%,transparent_38%,transparent_62%,rgba(120,210,255,0.04)_82%,transparent)]" />
          <div className="pointer-events-none absolute inset-y-0 left-[22%] w-px bg-cyan-200/8" />
          <div className="pointer-events-none absolute inset-y-0 right-[26%] w-px bg-cyan-200/8" />

          <div className="relative grid gap-4 xl:grid-cols-[minmax(0,1fr),minmax(680px,1.12fr)] xl:items-center">
            <div className="min-w-0 space-y-3">
              <div className="flex flex-wrap items-center gap-3">
                <div className="inline-flex h-9 items-center gap-2 rounded-[10px] border border-cyan-200/16 bg-cyan-200/6 px-3 text-[11px] uppercase tracking-[0.24em] text-cyan-100">
                  <DashboardLogo className="h-4 w-4 shrink-0 text-cyan-100" />
                  Logistic Copilot
                </div>
                <span className="hidden text-[11px] uppercase tracking-[0.24em] text-cyan-200/40 md:inline">
                  Live operations board
                </span>
              </div>
              <div className="space-y-2">
                <h1 className="text-xl font-semibold tracking-[-0.05em] text-white sm:text-[1.7rem]">
                  Monitor active lanes. Surface blockers. Move faster.
                </h1>
                <p className="max-w-2xl text-sm leading-6 text-slate-300">
                  A sharper command deck for today&apos;s shipments, operator decisions, and time-sensitive follow-up.
                </p>
              </div>
            </div>

            <div className="grid gap-1.5 sm:grid-cols-2 xl:grid-cols-6">
                {metrics.map((metric) => (
                  <div key={metric.label} className="min-h-[68px] rounded-[13px] border border-cyan-200/10 bg-slate-950/26 px-2.5 py-2 backdrop-blur">
                    <p className="text-[10px] uppercase tracking-[0.22em] text-cyan-200/48">{metric.label}</p>
                    <div className="mt-1 space-y-0.5">
                      <span className="block text-[1.45rem] font-semibold leading-none text-white">{metric.value}</span>
                      <span className="block text-[10px] leading-4 text-slate-300 break-words">{metric.detail}</span>
                    </div>
                  </div>
                ))}
                <button
                  onClick={() => setNotificationCenterOpen((open) => !open)}
                  className="relative min-h-[68px] overflow-hidden rounded-[13px] border border-cyan-200/16 bg-[linear-gradient(135deg,rgba(255,255,255,0.06),rgba(255,255,255,0.02))] px-2.5 py-2 text-left shadow-[inset_0_1px_0_rgba(255,255,255,0.06)] transition hover:border-cyan-200/24 hover:bg-cyan-200/10"
                >
                  <span className="pointer-events-none absolute right-1 top-1/2 -translate-y-1/2 text-[64px] font-black leading-none tracking-[-0.05em] text-cyan-100/[0.08]">
                    {unreadNotificationCount}
                  </span>
                  <div className="relative z-[1] flex items-center justify-between gap-2">
                    <div className="min-w-0 pr-4">
                      <p className="text-[10px] uppercase tracking-[0.22em] text-cyan-100/70">Signals</p>
                      <span className="mt-0.5 inline-flex items-center gap-1.5 text-[15px] font-semibold text-white">
                        <Bell size={16} /> Alerts
                      </span>
                      <p className="mt-0.5 truncate text-[10px] text-cyan-100/70">
                        {notifications[0]?.title || "Email, shipment, bid, review"}
                      </p>
                    </div>
                  </div>
                </button>
                <button
                  onClick={() => void handleOutlookSync()}
                  disabled={submitting !== null}
                  className="min-h-[68px] rounded-[13px] border border-cyan-200/16 bg-[linear-gradient(135deg,rgba(132,236,255,0.2),rgba(85,202,255,0.14))] px-2.5 py-2 text-left shadow-[0_12px_30px_rgba(44,164,214,0.14),inset_0_1px_0_rgba(255,255,255,0.08)] transition hover:brightness-110 disabled:opacity-50"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-[10px] uppercase tracking-[0.22em] text-cyan-100/70">Outlook</p>
                      <span className="mt-0.5 inline-flex items-center gap-1.5 text-[15px] font-semibold text-white">
                        <Mail size={16} /> {submitting === "sync" ? "Syncing..." : "Sync"}
                      </span>
                      <p className="mt-0.5 text-[10px] text-cyan-100/70">last 10 mails</p>
                    </div>
                  </div>
                </button>
            </div>
          </div>

        </section>

        {error && <div className="glass-panel-strong border-red-400/20 px-5 py-4 text-sm text-red-100">{error}</div>}
        {notice && <div className="glass-panel-strong border-cyan-400/20 px-5 py-4 text-sm text-cyan-100">{notice}</div>}

        <section className="glass-panel p-4">
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            {[
              { key: "shipments", label: "Shipments", icon: Package2 },
              { key: "clients", label: "Customers", icon: Users },
              { key: "carriers", label: "Carriers", icon: Truck },
              { key: "archive", label: "Archive", icon: Archive },
            ].map(({ key, label, icon: Icon }) => {
              const active = tab === key;
              return (
                <button
                  key={key}
                  onClick={() => setTab(key as DashboardTab)}
                  className={`flex items-center justify-between rounded-2xl px-4 py-3 text-left transition ${active ? "bg-white text-slate-950" : "bg-white/5 text-[var(--text-muted)] hover:bg-white/10 hover:text-white"}`}
                >
                  <span className="flex items-center gap-3 font-medium"><Icon size={18} />{label}</span>
                  <ArrowRight size={16} />
                </button>
              );
            })}
          </div>
        </section>

        {initialLoading ? (
          <div className="glass-panel flex min-h-[480px] items-center justify-center p-8 text-[var(--text-muted)]">
            <Loader2 className="mr-3 animate-spin" size={18} /> Loading dashboard...
          </div>
        ) : null}

        {!initialLoading && tab === "shipments" && (
          <section className="space-y-4">
            <div className="glass-panel overflow-visible px-4 py-4">
              <div className="flex flex-col gap-4">
                <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
                  <div>
                    <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Board controls</p>
                    <p className="mt-1 text-sm text-slate-300">
                      Search shipments, switch created month, and control the live board from one surface.
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {(["today", "attention", "all"] as const).map((filter) => (
                      <button
                        key={filter}
                        onClick={() => setActiveBoardFilter(filter)}
                        className={`rounded-[10px] px-3 py-2 text-[11px] uppercase tracking-[0.2em] transition ${
                          activeBoardFilter === filter
                            ? "bg-cyan-100 text-slate-950"
                            : "border border-cyan-200/10 bg-slate-950/22 text-slate-300 hover:bg-cyan-200/8 hover:text-white"
                        }`}
                      >
                        {filter === "today" ? "Today" : filter === "attention" ? "Attention" : "All"}
                      </button>
                    ))}
                  </div>
                </div>

                {boardControlsExpanded ? (
                  <>
                    <div className="grid gap-3 xl:grid-cols-[minmax(340px,430px),minmax(280px,1fr)] xl:items-end">
                      <div className="min-w-0">
                        <span className="mb-2 block text-[11px] uppercase tracking-[0.16em] text-[var(--text-muted)]">Month</span>
                        <div ref={monthPickerRef} className="relative">
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              onClick={() => shiftBoardMonth(-1)}
                              className="inline-flex h-[52px] w-[46px] shrink-0 items-center justify-center rounded-[16px] border border-cyan-200/10 bg-slate-950/24 text-slate-300 transition hover:border-cyan-200/20 hover:bg-cyan-200/8 hover:text-white"
                              aria-label="Previous month"
                            >
                              <ChevronLeft size={18} />
                            </button>
                            <button
                              type="button"
                              onClick={() => setMonthPickerOpen((open) => !open)}
                              className="flex h-[52px] min-w-[240px] flex-1 items-center justify-between gap-3 rounded-[16px] border border-cyan-200/12 bg-[linear-gradient(135deg,rgba(110,184,255,0.08),rgba(110,184,255,0.02))] px-4 text-left shadow-[inset_0_1px_0_rgba(255,255,255,0.03)] transition hover:border-cyan-200/20 hover:bg-cyan-200/8"
                            >
                              <span className="flex min-w-0 items-center gap-3">
                                <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-[12px] border border-cyan-200/12 bg-cyan-200/8 text-cyan-100">
                                  <Calendar size={16} />
                                </span>
                                <span className="min-w-0">
                                  <span className="block text-[10px] uppercase tracking-[0.18em] text-cyan-200/55">Created month</span>
                                  <span className="block truncate text-sm font-medium text-white">{formatMonthLabel(selectedBoardMonth)}</span>
                                </span>
                              </span>
                              <span className="text-[11px] uppercase tracking-[0.16em] text-slate-400">{monthPickerOpen ? "Close" : "Choose"}</span>
                            </button>
                            <button
                              type="button"
                              onClick={() => shiftBoardMonth(1)}
                              className="inline-flex h-[52px] w-[46px] shrink-0 items-center justify-center rounded-[16px] border border-cyan-200/10 bg-slate-950/24 text-slate-300 transition hover:border-cyan-200/20 hover:bg-cyan-200/8 hover:text-white"
                              aria-label="Next month"
                            >
                              <ChevronRight size={18} />
                            </button>
                          </div>
                        </div>
                      </div>

                      <label className="relative min-w-0">
                        <span className="mb-2 block text-[11px] uppercase tracking-[0.16em] text-[var(--text-muted)]">Search</span>
                        <Search size={16} className="pointer-events-none absolute left-3 top-[calc(50%+12px)] -translate-y-1/2 text-[var(--text-muted)]" />
                        <input
                          className="field-input h-[52px] rounded-[16px] pl-10"
                          value={shipmentSearch}
                          onChange={(event) => setShipmentSearch(event.target.value)}
                          placeholder="Search by route, city, token, notes..."
                        />
                      </label>
                    </div>

                    <div className="flex flex-wrap gap-2 border-t border-cyan-200/10 pt-4">
                      <span className="rounded-[10px] border border-cyan-200/10 bg-slate-950/22 px-3 py-2 text-[11px] text-slate-300">
                        {formatMonthLabel(selectedBoardMonth)}
                      </span>
                      <span className="rounded-[10px] border border-cyan-200/10 bg-slate-950/22 px-3 py-2 text-[11px] text-slate-300">
                        Showing {boardShipments.length} shipments
                      </span>
                      {attentionItems.slice(0, 3).map((item) => (
                        <span key={item} className="rounded-[10px] border border-cyan-200/10 bg-slate-950/20 px-3 py-2 text-[11px] text-slate-400">
                          {item}
                        </span>
                      ))}
                      <div className="ml-auto flex flex-wrap gap-2">
                        {shipmentSearch.trim() ? (
                          <button
                            onClick={() => setShipmentSearch("")}
                            className="rounded-[12px] border border-white/10 bg-slate-950/28 px-3.5 py-2 text-[11px] uppercase tracking-[0.16em] text-slate-300 transition hover:border-cyan-200/14 hover:bg-cyan-200/8 hover:text-white"
                          >
                            Clear search
                          </button>
                        ) : null}
                        <button
                          onClick={() => void hardRefreshDashboard()}
                          disabled={submitting !== null}
                          className="inline-flex items-center gap-2 rounded-[14px] bg-white/[0.025] px-4 py-2.5 text-sm font-medium text-slate-400 transition hover:bg-white/[0.04] hover:text-slate-200 disabled:opacity-50"
                        >
                          <RefreshCcw size={16} /> {backgroundRefreshing ? "Refreshing..." : "Refresh board"}
                        </button>
                        <button
                          type="button"
                          onClick={() => setBoardControlsExpanded(false)}
                          className="inline-flex items-center gap-2 rounded-[12px] border border-cyan-200/10 bg-slate-950/24 px-3.5 py-2 text-[11px] uppercase tracking-[0.16em] text-slate-300 transition hover:border-cyan-200/18 hover:bg-cyan-200/8 hover:text-white"
                        >
                          <ChevronUp size={14} /> Collapse controls
                        </button>
                      </div>
                    </div>
                  </>
                ) : (
                  <div
                    role="button"
                    tabIndex={0}
                    onClick={() => setBoardControlsExpanded(true)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        setBoardControlsExpanded(true);
                      }
                    }}
                    className="rounded-[20px] border border-cyan-200/10 bg-[linear-gradient(180deg,rgba(255,255,255,0.02),rgba(255,255,255,0.008))] px-3 py-3 transition hover:border-cyan-200/18 hover:bg-cyan-200/6"
                  >
                    <div className="flex items-center gap-2">
                      <div className="flex min-w-0 flex-1 items-center gap-1.5 overflow-hidden">
                        <div ref={monthPickerRef}>
                          <button
                            type="button"
                            onClick={(event) => {
                              event.stopPropagation();
                              setMonthPickerOpen(true);
                            }}
                            className="inline-flex items-center gap-1.5 rounded-[11px] border border-cyan-200/12 bg-cyan-200/8 px-2.5 py-1.5 text-[10px] text-cyan-100 transition hover:border-cyan-200/22 hover:bg-cyan-200/14"
                          >
                            <Calendar size={14} /> {formatMonthLabel(selectedBoardMonth)}
                          </button>
                        </div>
                        <span className="truncate rounded-[11px] border border-cyan-200/10 bg-slate-950/24 px-2.5 py-1.5 text-[10px] text-slate-300">
                          {boardShipments.length} shipments visible
                        </span>
                        <span className="hidden truncate rounded-[11px] border border-cyan-200/10 bg-slate-950/20 px-2.5 py-1.5 text-[10px] text-slate-400 sm:inline-flex">
                          {attentionShipmentCount} awaiting operator
                        </span>
                        {shipmentSearch.trim() ? (
                          <span className="hidden truncate rounded-[11px] border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[10px] text-slate-300 lg:inline-flex">
                            Search: {shipmentSearch}
                          </span>
                        ) : null}
                      </div>
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          setBoardControlsExpanded(true);
                        }}
                        className="ml-auto inline-flex shrink-0 items-center gap-2 rounded-[12px] border border-cyan-200/12 bg-[linear-gradient(135deg,rgba(110,184,255,0.08),rgba(110,184,255,0.02))] px-3 py-2 text-[12px] font-medium text-white transition hover:border-cyan-200/22 hover:bg-cyan-200/8"
                      >
                        <ChevronDown size={16} />
                        <span className="hidden sm:inline">Expand controls</span>
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
            <div className="overflow-x-auto rounded-[32px] border border-white/10 bg-[radial-gradient(circle_at_top_left,rgba(75,211,255,0.08),transparent_32%),linear-gradient(180deg,rgba(255,255,255,0.02),rgba(255,255,255,0.01))] p-4">
              <div className="flex min-w-[1320px] gap-4">
                {boardColumns.map((column) => {
                  const items = groupedShipmentsByStatus[column.key] || [];
                  return (
                    <div key={column.key} className="flex min-h-[72vh] w-[260px] flex-col rounded-[28px] border border-white/10 bg-slate-950/25">
                      <div className={`sticky top-0 z-10 rounded-t-[28px] border-b border-white/10 bg-gradient-to-b ${column.accent} px-4 py-4 backdrop-blur`}>
                        <div className="flex items-center justify-between gap-3">
                          <p className="text-sm font-medium text-white">{column.label}</p>
                          <span className="rounded-full bg-white/10 px-2.5 py-1 text-xs text-white">{items.length}</span>
                        </div>
                      </div>
                      <div className="flex-1 space-y-2 p-3">
                        {items.length === 0 && (
                          <div className="rounded-[22px] border border-dashed border-white/10 bg-white/5 p-4 text-sm text-[var(--text-muted)]">
                            Nothing here right now.
                          </div>
                        )}
                        {items.map((shipment) => {
                          const isSelected = shipment.id === selectedShipmentId;
                          return (
                            <div
                              key={shipment.id}
                              onContextMenu={(event: ReactMouseEvent<HTMLDivElement>) => {
                                event.preventDefault();
                                if (!selectShipment(shipment.id)) return;
                                setContextMenu({ shipmentId: shipment.id, x: event.clientX, y: event.clientY });
                              }}
                              className={`group relative overflow-hidden rounded-[18px] border px-3 pt-2 pb-1.5 transition ${
                                isSelected
                                  ? "border-cyan-300/40 bg-cyan-300/10 shadow-[0_0_0_1px_rgba(134,239,255,0.08)]"
                                  : "border-white/10 bg-white/[0.05] hover:-translate-y-0.5 hover:border-white/20 hover:bg-white/[0.08]"
                              }`}
                            >
                              <button
                                onClick={(event) => {
                                  event.stopPropagation();
                                  if (!selectShipment(shipment.id)) return;
                                  setContextMenu({ shipmentId: shipment.id, x: event.clientX, y: event.clientY });
                                }}
                                className="absolute right-2 top-2 inline-flex h-6 w-6 items-center justify-center rounded-full text-[var(--text-muted)] opacity-100 transition hover:bg-white/10 hover:text-white xl:opacity-0 xl:group-hover:opacity-100"
                              >
                                <MoreHorizontal size={14} />
                              </button>
                              <div className="flex items-start">
                                <button
                                  onClick={() => {
                                    selectShipment(shipment.id, { openDrawer: true });
                                  }}
                                  className="w-full text-left"
                                >
                                  <div className="flex items-center justify-between gap-2 pr-7">
                                    <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                                      <ShipmentStatusPill status={shipment.status} />
                                      <span className={`inline-flex h-5 shrink-0 items-center whitespace-nowrap rounded-full px-2 text-[9px] font-medium uppercase tracking-[0.1em] ${
                                        shipmentNeedsAttention(shipment) ? "bg-amber-300/10 text-amber-100" : "bg-emerald-300/10 text-emerald-100"
                                      }`}>
                                        {shipmentBlockingBadge(shipment)}
                                      </span>
                                    </div>
                                    <span className="shrink-0 rounded-full bg-cyan-300/10 px-2 py-0.5 text-[10px] text-cyan-100">
                                      {formatConfidence(shipment.ai_confidence)}
                                    </span>
                                  </div>
                                  <p className="mt-1.5 line-clamp-2 text-[13px] font-medium leading-4.5 text-white">{formatRoute(shipment)}</p>
                                  <div className="mt-1.5 grid grid-cols-[minmax(0,1.25fr)_minmax(0,0.95fr)] gap-x-2 gap-y-1 text-[10px] leading-4 text-[var(--text-muted)]">
                                    <p className="min-w-0 whitespace-normal">{formatShipmentSchedule(shipment.ready_at_display, shipment.ready_at_local || null) || "TBD"}</p>
                                    <p className="min-w-0 text-right whitespace-normal">Weight: {shipment.weight_lb ?? "--"} lb</p>
                                    <p className="min-w-0 whitespace-normal">Token: {shipment.quote_token || "--"}</p>
                                    <p className="min-w-0 text-right whitespace-normal">Pallets: {shipment.pallets ?? "--"}</p>
                                  </div>
                                  <div className="mt-1">
                                    <span className="line-clamp-2 text-[10px] uppercase tracking-[0.14em] text-[var(--text-muted)]">
                                      {shipment.next_step_label || (shipment.ai_next_action ? shipment.ai_next_action.replaceAll("_", " ") : "operator review")}
                                    </span>
                                  </div>
                                </button>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </section>
        )}

        {!initialLoading && tab === "status_ops" && (
          <section className="grid gap-4 xl:grid-cols-[380px,minmax(0,1fr)]">
            <div className="glass-panel p-4">
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Status queue</p>
                  <p className="mt-1 text-lg font-medium text-white">Separate customer and carrier reviews</p>
                </div>
                <div className="flex gap-2">
                  <button onClick={() => setStatusQueueScope("active")} className={`rounded-full px-3 py-2 text-xs ${statusQueueScope === "active" ? "bg-white text-slate-950" : "bg-white/5 text-[var(--text-muted)]"}`}>Active</button>
                  <button onClick={() => setStatusQueueScope("resolved")} className={`rounded-full px-3 py-2 text-xs ${statusQueueScope === "resolved" ? "bg-white text-slate-950" : "bg-white/5 text-[var(--text-muted)]"}`}>Resolved</button>
                </div>
              </div>
              <div className="space-y-2">
                {filteredStatusQueue.map((task) => (
                  <button
                    key={task.task_id}
                    onClick={() => {
                      setSelectedStatusTaskId(task.task_id);
                      selectShipment(task.shipment_id);
                    }}
                    className={`w-full rounded-2xl border p-4 text-left transition ${task.task_id === selectedStatusTaskId ? "border-cyan-300/40 bg-cyan-300/10" : "border-white/10 bg-white/5 hover:bg-white/10"}`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-white">{task.task_type.replaceAll("_", " ")}</p>
                        <p className="mt-1 text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">{task.task_state.replaceAll("_", " ")}</p>
                      </div>
                      <span className={`rounded-full border px-3 py-1 text-xs ${reviewPriorityClasses(task.priority)}`}>{task.priority}</span>
                    </div>
                    <p className="mt-2 text-sm text-[var(--text-muted)]">{task.reason}</p>
                  </button>
                ))}
              </div>
            </div>

            <div className="glass-panel p-5">
              {!selectedStatusTask ? (
                <div className="text-sm text-[var(--text-muted)]">Choose a status task to review it.</div>
              ) : (
                <div className="space-y-4">
                  <div>
                    <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Selected task</p>
                    <h2 className="mt-1 text-2xl font-semibold text-white">{selectedStatusTask.task_type.replaceAll("_", " ")}</h2>
                    <p className="mt-2 text-sm text-[var(--text-muted)]">{selectedStatusTask.reason}</p>
                  </div>
                  {selectedStatusTask.task_type === "status_reply" ? (
                    <div className="space-y-3">
                      <input className="field-input" value={statusReplyDraftSubject} onChange={(event) => setStatusReplyDraftSubject(event.target.value)} placeholder="Reply subject" />
                      <textarea className="field-input min-h-[140px] resize-none" value={statusReplyDraftBody} onChange={(event) => setStatusReplyDraftBody(event.target.value)} placeholder="Reply body" />
                      <textarea className="field-input min-h-[100px] resize-none" value={statusReplyMessage} onChange={(event) => setStatusReplyMessage(event.target.value)} placeholder="Operator note" />
                      <div className="grid gap-2 md:grid-cols-4">
                        <button onClick={() => void handleStatusQueueAction("preview")} disabled={submitting !== null} className="action-button bg-white/10 text-white hover:bg-white/15 disabled:opacity-50">Preview</button>
                        <button onClick={() => void handleStatusQueueAction("rebuild_draft")} disabled={submitting !== null} className="action-button bg-cyan-300/15 text-cyan-100 hover:bg-cyan-300/20 disabled:opacity-50">Rebuild draft</button>
                        <button onClick={() => void handleStatusQueueAction("approve_and_send")} disabled={submitting !== null} className="action-button bg-emerald-300/15 text-emerald-100 hover:bg-emerald-300/20 disabled:opacity-50">Approve and send</button>
                        <button onClick={() => void handleStatusQueueAction("dismiss")} disabled={submitting !== null} className="action-button bg-amber-300/15 text-amber-100 hover:bg-amber-300/20 disabled:opacity-50">Dismiss</button>
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      <div className="grid gap-3 md:grid-cols-2">
                        <input className="field-input" value={carrierStatusForm.status_text} onChange={(event) => setCarrierStatusForm((current) => ({ ...current, status_text: event.target.value }))} placeholder="Status text" />
                        <input className="field-input" value={carrierStatusForm.eta_text} onChange={(event) => setCarrierStatusForm((current) => ({ ...current, eta_text: event.target.value }))} placeholder="ETA text" />
                        <input className="field-input" value={carrierStatusForm.location_text} onChange={(event) => setCarrierStatusForm((current) => ({ ...current, location_text: event.target.value }))} placeholder="Location text" />
                        <input className="field-input" value={carrierStatusForm.notes} onChange={(event) => setCarrierStatusForm((current) => ({ ...current, notes: event.target.value }))} placeholder="Notes" />
                      </div>
                      <div className="grid gap-2 md:grid-cols-4">
                        <button onClick={() => void handleStatusQueueAction("preview")} disabled={submitting !== null} className="action-button bg-white/10 text-white hover:bg-white/15 disabled:opacity-50">Preview</button>
                        <button onClick={() => void handleStatusQueueAction("retry_push")} disabled={submitting !== null} className="action-button bg-cyan-300/15 text-cyan-100 hover:bg-cyan-300/20 disabled:opacity-50">Retry push</button>
                        <button onClick={() => void handleStatusQueueAction("approve_and_push")} disabled={submitting !== null} className="action-button bg-emerald-300/15 text-emerald-100 hover:bg-emerald-300/20 disabled:opacity-50">Approve and push</button>
                        <button onClick={() => void handleStatusQueueAction("dismiss")} disabled={submitting !== null} className="action-button bg-amber-300/15 text-amber-100 hover:bg-amber-300/20 disabled:opacity-50">Dismiss</button>
                      </div>
                    </div>
                  )}
                  {selectedStatusTask.last_failure && (
                    <div className="rounded-2xl border border-rose-300/20 bg-rose-300/10 p-4 text-sm text-rose-50">
                      {selectedStatusTask.last_failure}
                    </div>
                  )}
                </div>
              )}
            </div>
          </section>
        )}

        {visibleToasts.length > 0 && (
          <div className="pointer-events-none fixed right-6 top-6 z-[85] flex w-[min(360px,calc(100vw-2rem))] flex-col gap-3">
            {visibleToasts.map((item) => (
              <div
                key={item.id}
                className="pointer-events-auto overflow-hidden rounded-[20px] border border-cyan-200/14 bg-[linear-gradient(180deg,rgba(12,20,31,0.96),rgba(10,16,26,0.95))] p-4 shadow-[0_24px_80px_rgba(2,8,23,0.42)] backdrop-blur"
              >
                <div className="flex items-start gap-3">
                  <div className={`mt-0.5 inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-[14px] border ${notificationAccent(item.kind)}`}>
                    {renderNotificationIcon(item.kind)}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-[10px] uppercase tracking-[0.18em] text-cyan-200/52">{notificationBadgeLabel(item.kind)}</p>
                        <p className="mt-1 text-sm font-medium text-white">{item.title}</p>
                      </div>
                      <button
                        onClick={() => hideNotificationToast(item.id)}
                        className="rounded-full p-1 text-slate-400 transition hover:bg-white/8 hover:text-white"
                        aria-label="Dismiss notification"
                      >
                        <X size={14} />
                      </button>
                    </div>
                    <p className="mt-2 text-sm leading-6 text-slate-300">{item.detail}</p>
                    <div className="mt-3 flex items-center justify-between gap-3">
                      <span className="text-[11px] text-slate-400">{formatAge(item.created_at)}</span>
                      <button
                        onClick={() => openNotification(item)}
                        className="rounded-[12px] border border-cyan-200/12 bg-cyan-200/8 px-3 py-1.5 text-xs font-medium text-cyan-50 transition hover:border-cyan-200/24 hover:bg-cyan-200/14"
                      >
                        Open
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        <div
          className={`fixed inset-0 z-[88] bg-slate-950/30 backdrop-blur-[2px] transition ${
            notificationCenterOpen ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0"
          }`}
          onClick={() => setNotificationCenterOpen(false)}
        />
        <aside
          className={`fixed right-6 top-6 z-[89] flex h-[min(82vh,760px)] w-[min(390px,calc(100vw-2rem))] flex-col overflow-hidden rounded-[28px] border border-cyan-200/14 bg-[linear-gradient(180deg,rgba(12,20,31,0.97),rgba(9,15,25,0.96))] shadow-[0_28px_120px_rgba(2,8,23,0.56)] backdrop-blur transition-all duration-300 ${
            notificationCenterOpen ? "translate-y-0 opacity-100" : "pointer-events-none -translate-y-4 opacity-0"
          }`}
        >
          <div className="border-b border-cyan-200/10 px-5 py-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-[10px] uppercase tracking-[0.22em] text-cyan-200/52">Notification center</p>
                <h3 className="mt-1 text-lg font-semibold text-white">Live ops signals</h3>
                <p className="mt-1 text-sm text-slate-300">Inbound email, shipment creation, bids, reviews, and status updates land here.</p>
              </div>
              <button
                onClick={() => setNotificationCenterOpen(false)}
                className="rounded-full p-2 text-slate-400 transition hover:bg-white/8 hover:text-white"
                aria-label="Close notification center"
              >
                <X size={16} />
              </button>
            </div>
            <div className="mt-4 flex items-center gap-2">
              <span className="rounded-full border border-cyan-200/12 bg-cyan-200/8 px-3 py-1 text-xs text-cyan-50">
                {unreadNotificationCount} unread
              </span>
              <span className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-xs text-slate-300">
                {notificationTotal} total
              </span>
              <button
                onClick={markAllNotificationsRead}
                className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-xs text-slate-300 transition hover:border-cyan-200/18 hover:bg-cyan-200/8 hover:text-white"
              >
                Mark all read
              </button>
            </div>
          </div>
          <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
            {notificationLoading && notifications.length === 0 ? (
              <div className="rounded-[22px] border border-white/10 bg-white/[0.03] px-4 py-6 text-sm text-slate-400">
                <Loader2 className="mr-2 inline animate-spin" size={16} /> Loading notifications...
              </div>
            ) : notifications.length === 0 ? (
              <div className="rounded-[22px] border border-dashed border-white/10 bg-white/[0.03] px-4 py-6 text-sm text-slate-400">
                No notification history yet. New inbox and workflow activity will land here automatically.
              </div>
            ) : (
              <>
                {notifications.map((item) => (
                  <button
                    key={item.id}
                    onClick={() => openNotification(item)}
                    className={`w-full rounded-[22px] border px-4 py-4 text-left transition ${
                      item.unread
                        ? "border-cyan-200/16 bg-cyan-200/[0.06] hover:bg-cyan-200/[0.09]"
                        : "border-white/10 bg-white/[0.035] hover:bg-white/[0.055]"
                    }`}
                  >
                    <div className="flex items-start gap-3">
                      <div className={`mt-0.5 inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-[14px] border ${notificationAccent(item.kind)}`}>
                        {renderNotificationIcon(item.kind)}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-[10px] uppercase tracking-[0.18em] text-cyan-200/52">{notificationBadgeLabel(item.kind)}</span>
                              {item.unread && <span className="inline-flex h-2 w-2 rounded-full bg-cyan-200" />}
                            </div>
                            <p className="mt-1 text-sm font-medium text-white">{item.title}</p>
                          </div>
                          <span className="shrink-0 text-[11px] text-slate-400">{formatAge(item.created_at)}</span>
                        </div>
                        <p className="mt-2 text-sm leading-6 text-slate-300">{item.detail}</p>
                        {(item.quote_token || item.shipment_id) && (
                          <div className="mt-3 flex flex-wrap gap-2">
                            {item.quote_token && (
                              <span className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[10px] uppercase tracking-[0.16em] text-slate-300">
                                {item.quote_token}
                              </span>
                            )}
                            {item.archived && (
                              <span className="rounded-full border border-amber-300/18 bg-amber-300/10 px-2.5 py-1 text-[10px] uppercase tracking-[0.16em] text-amber-100">
                                Archive
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  </button>
                ))}
                {notificationHasMore && (
                  <button
                    onClick={() => void loadNotifications()}
                    disabled={notificationLoading}
                    className="w-full rounded-[18px] border border-white/10 bg-white/[0.04] px-4 py-3 text-sm text-slate-300 transition hover:border-cyan-200/18 hover:bg-cyan-200/8 hover:text-white disabled:opacity-50"
                  >
                    {notificationLoading ? "Loading more..." : "Load more"}
                  </button>
                )}
              </>
            )}
          </div>
        </aside>

        {monthPickerOpen && typeof document !== "undefined"
          ? createPortal(
              <div className="fixed inset-0 z-[170] flex items-center justify-center bg-slate-950/58 px-4 backdrop-blur-[6px]" onClick={() => setMonthPickerOpen(false)}>
                <div
                  ref={monthPickerRef}
                  className="relative w-full max-w-[620px] overflow-hidden rounded-[32px] border border-cyan-200/14 bg-[#0c1525] shadow-[0_30px_120px_rgba(2,8,23,0.68)] isolate"
                  onClick={(event) => event.stopPropagation()}
                >
                  <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(103,232,249,0.08),transparent_38%),linear-gradient(180deg,rgba(255,255,255,0.02),rgba(255,255,255,0))]" />
                  <div className="relative space-y-5 p-6">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <p className="text-[10px] uppercase tracking-[0.22em] text-cyan-200/55">Operational month</p>
                        <p className="mt-2 text-3xl font-semibold tracking-[-0.04em] text-white">{formatMonthLabel(selectedBoardMonth)}</p>
                        <p className="mt-1 text-sm text-slate-400">Choose the board window you want to operate in.</p>
                      </div>
                      <button
                        type="button"
                        onClick={() => setMonthPickerOpen(false)}
                        className="inline-flex h-10 items-center rounded-full border border-cyan-200/12 bg-white/[0.03] px-4 text-sm text-slate-300 transition hover:border-cyan-200/20 hover:bg-cyan-200/8 hover:text-white"
                      >
                        Close
                      </button>
                    </div>

                    <div className="flex items-center justify-between rounded-[22px] border border-cyan-200/10 bg-white/[0.03] px-4 py-3">
                      <button
                        type="button"
                        onClick={() => setMonthPickerYear((value) => value - 1)}
                        className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-cyan-200/12 bg-slate-950/24 text-slate-300 transition hover:border-cyan-200/20 hover:bg-cyan-200/8 hover:text-white"
                        aria-label="Previous year"
                      >
                        <ChevronLeft size={18} />
                      </button>
                      <div className="text-center">
                        <p className="text-[10px] uppercase tracking-[0.2em] text-cyan-200/48">Pick month</p>
                        <p className="mt-1 text-xl font-semibold text-white">{monthPickerYear}</p>
                      </div>
                      <button
                        type="button"
                        onClick={() => setMonthPickerYear((value) => value + 1)}
                        className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-cyan-200/12 bg-slate-950/24 text-slate-300 transition hover:border-cyan-200/20 hover:bg-cyan-200/8 hover:text-white"
                        aria-label="Next year"
                      >
                        <ChevronRight size={18} />
                      </button>
                    </div>

                    <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
                      {monthGridForYear(monthPickerYear).map((monthOption) => {
                        const active = monthOption.value === selectedBoardMonth;
                        return (
                          <button
                            key={monthOption.value}
                            type="button"
                            onClick={() => {
                              updateBoardMonth(monthOption.value);
                              setMonthPickerOpen(false);
                            }}
                            className={`rounded-[16px] px-3 py-3 text-left text-sm transition ${
                              active
                                ? "bg-cyan-100 text-slate-950 shadow-[0_10px_30px_rgba(180,255,250,0.18)]"
                                : "border border-cyan-200/10 bg-white/[0.03] text-slate-200 hover:border-cyan-200/18 hover:bg-cyan-200/8 hover:text-white"
                            }`}
                          >
                            {monthOption.shortLabel}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </div>
              </div>,
              document.body,
            )
          : null}

        {!initialLoading && tab === "archive" && (
          <section className="glass-panel p-5">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Archive</p>
                <h2 className="mt-1 text-2xl font-semibold tracking-[-0.04em] text-white">Ignored shipments</h2>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-300">
                  View-only archive for duplicates, cancelled loads, parsing errors, fraud/spam, tests, and non-delivery bounces.
                </p>
              </div>
              <button
                onClick={() => void refreshArchivedShipments()}
                disabled={submitting !== null}
                className="action-button bg-white/8 text-white hover:bg-white/12 disabled:opacity-50"
              >
                <RefreshCcw size={15} /> Refresh archive
              </button>
            </div>
            <div className="mt-5 grid gap-3 lg:grid-cols-[minmax(0,1fr),220px,180px]">
              <label className="block">
                <span className="mb-2 block text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Search archive</span>
                <div className="relative">
                  <Search className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-slate-500" size={16} />
                  <input
                    className="field-input pl-11"
                    value={archiveSearch}
                    onChange={(event) => setArchiveSearch(event.target.value)}
                    placeholder="Route, token, thread, reason..."
                  />
                </div>
              </label>
              <label className="block">
                <span className="mb-2 block text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Reason</span>
                <select className="field-input" value={archiveReasonFilter} onChange={(event) => setArchiveReasonFilter(event.target.value as ArchiveReasonCode | "all")}>
                  <option value="all">All reasons</option>
                  {ARCHIVE_REASON_OPTIONS.map((reason) => (
                    <option key={reason.value} value={reason.value}>{reason.label}</option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="mb-2 block text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Archive month</span>
                <input className="field-input" type="month" value={archiveMonth} onChange={(event) => setArchiveMonth(event.target.value)} />
              </label>
            </div>
            <div className="mt-5 grid gap-3 xl:grid-cols-2">
              {archivedShipments.length === 0 && (
                <div className="rounded-[24px] border border-dashed border-white/10 bg-white/5 p-6 text-sm text-[var(--text-muted)]">
                  No archived shipments match these filters.
                </div>
              )}
              {archivedShipments.map((shipment) => (
                <button
                  key={shipment.id}
                  onClick={() => {
                    setSelectedShipmentId(shipment.id);
                    setDrawerOpen(true);
                    setDrawerMode("overview");
                    setQuoteParam(null);
                  }}
                  className="rounded-[24px] border border-white/10 bg-white/[0.04] p-4 text-left transition hover:border-amber-300/24 hover:bg-amber-300/[0.06]"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full border border-amber-300/20 bg-amber-300/12 px-3 py-1 text-xs text-amber-100">
                      {archiveReasonLabel(shipment.archive_reason_code)}
                    </span>
                    <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-[var(--text-muted)]">
                      {shipment.status.replaceAll("_", " ")}
                    </span>
                    <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-[var(--text-muted)]">
                      {shipment.quote_token || "No token"}
                    </span>
                  </div>
                  <h3 className="mt-3 text-lg font-semibold text-white">{formatRoute(shipment)}</h3>
                  <div className="mt-3 grid gap-2 text-sm text-slate-300 sm:grid-cols-2">
                    <p>Archived: {formatDate(shipment.archived_at)}</p>
                    <p>Created: {formatDate(shipment.created_at)}</p>
                    <p className="sm:col-span-2">Reason: {shipment.archive_reason_note || shipment.archived_reason || "No note"}</p>
                    <p className="break-all sm:col-span-2">Thread: {shipment.email_thread_id || "No linked thread"}</p>
                  </div>
                </button>
              ))}
            </div>
          </section>
        )}

        {!initialLoading && tab === "clients" && (
          <section className="grid gap-4 xl:grid-cols-[420px,minmax(0,1fr)]">
            <form className="glass-panel p-5 space-y-3" onSubmit={handleCreateClient}>
              <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">New customer</p>
              <input className="field-input" value={clientForm.name} onChange={(event) => setClientForm((current) => ({ ...current, name: event.target.value }))} placeholder="Customer name" />
              <input className="field-input" value={clientForm.email} onChange={(event) => setClientForm((current) => ({ ...current, email: event.target.value }))} placeholder="Customer email" />
              <div className="grid gap-3 sm:grid-cols-2">
                <input className="field-input" value={clientForm.default_margin_percent} onChange={(event) => setClientForm((current) => ({ ...current, default_margin_percent: event.target.value }))} placeholder="Margin %" />
                <input className="field-input" value={clientForm.default_margin_floor} onChange={(event) => setClientForm((current) => ({ ...current, default_margin_floor: event.target.value }))} placeholder="Margin floor" />
              </div>
              <button className="action-button bg-[var(--accent-cyan)] text-slate-950 hover:brightness-110" disabled={submitting !== null}>Add customer</button>
            </form>
            <div className="glass-panel p-5 space-y-3">
              {clients.map((client) => (
                <div key={client.id} className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-white">{client.name}</p>
                      <p className="text-sm text-[var(--text-muted)]">{client.email}</p>
                    </div>
                    <span className="rounded-full bg-white/10 px-3 py-1 text-xs text-white">{client.default_margin_percent}%</span>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {!initialLoading && tab === "carriers" && (
          <section className="grid gap-4 xl:grid-cols-[420px,minmax(0,1fr)]">
            <form className="glass-panel p-5 space-y-3" onSubmit={handleCreateCarrier}>
              <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">New carrier</p>
              <input className="field-input" value={carrierForm.name} onChange={(event) => setCarrierForm((current) => ({ ...current, name: event.target.value }))} placeholder="Carrier name" />
              <input className="field-input" value={carrierForm.email} onChange={(event) => setCarrierForm((current) => ({ ...current, email: event.target.value }))} placeholder="Carrier email" />
              <input className="field-input" value={carrierForm.rating} onChange={(event) => setCarrierForm((current) => ({ ...current, rating: event.target.value }))} placeholder="Rating" />
              <input className="field-input" value={carrierForm.regions} onChange={(event) => setCarrierForm((current) => ({ ...current, regions: event.target.value }))} placeholder="Regions" />
              <input className="field-input" value={carrierForm.equipment} onChange={(event) => setCarrierForm((current) => ({ ...current, equipment: event.target.value }))} placeholder="Equipment" />
              <button className="action-button bg-[var(--accent-cyan)] text-slate-950 hover:brightness-110" disabled={submitting !== null}>Add carrier</button>
            </form>
            <div className="glass-panel p-5 space-y-3">
              {carriers.map((carrier) => (
                <div key={carrier.id} className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-white">{carrier.name}</p>
                      <p className="text-sm text-[var(--text-muted)]">{carrier.email}</p>
                    </div>
                    <span className="rounded-full bg-white/10 px-3 py-1 text-xs text-white">Rating {carrier.rating}</span>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {contextMenu && selectedShipment && actionModel && (
          <div
            className="fixed z-50 min-w-[240px] rounded-2xl border border-white/10 bg-slate-950/95 p-2 shadow-2xl backdrop-blur"
            style={{ left: contextMenu.x, top: contextMenu.y }}
            onClick={(event) => event.stopPropagation()}
          >
            <button onClick={() => { selectShipment(contextMenu.shipmentId, { openDrawer: true }); setContextMenu(null); }} className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-sm text-white transition hover:bg-white/10">
              <Package2 size={16} /> Open shipment
            </button>
            {actionModel.label && actionModel.operatorAction && (
              <button onClick={() => void runStatefulPrimaryAction()} className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-sm text-cyan-100 transition hover:bg-cyan-300/10">
                <CheckCircle2 size={16} /> {actionModel.label}
              </button>
            )}
            <button onClick={() => { enterEditMode(); setContextMenu(null); }} className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-sm text-white transition hover:bg-white/10">
              <PencilLine size={16} /> Edit details
            </button>
            {quickActions.map((action) => (
              <button
                key={action.key}
                onClick={() => void handleContextAction(action)}
                className={`flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-sm transition ${
                  action.tone === "warning" ? "text-amber-100 hover:bg-amber-300/10" : "text-white hover:bg-white/10"
                }`}
              >
                {action.key === "archive_shipment" ? <Archive size={16} /> : <RefreshCcw size={16} />} {action.label}
              </button>
            ))}
          </div>
        )}

        {!initialLoading && (tab === "shipments" || tab === "archive") && (
          <>
            <div
              className={`fixed inset-0 z-40 !mt-0 bg-slate-950/45 backdrop-blur-sm transition ${drawerOpen ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0"}`}
              onClick={closeDrawer}
            />
            {renderThreadRail()}
            <div
              className={`fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/55 px-4 backdrop-blur-sm transition ${
                archiveDialog ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0"
              }`}
              onClick={() => setArchiveDialog(null)}
            >
              <div
                className="w-full max-w-[560px] rounded-[30px] border border-amber-300/20 bg-[linear-gradient(180deg,rgba(15,21,31,0.98),rgba(10,16,24,0.98))] p-6 shadow-[0_32px_100px_rgba(0,0,0,0.45)]"
                onClick={(event) => event.stopPropagation()}
              >
                <div className="flex items-start gap-4">
                  <div className="rounded-full bg-amber-300/12 p-3 text-amber-100">
                    <AlertTriangle size={18} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-xs uppercase tracking-[0.18em] text-amber-200/70">Archive shipment</p>
                    <h3 className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-white">Move this shipment to archive?</h3>
                    <p className="mt-3 text-sm leading-6 text-slate-300">
                      <span className="font-medium text-white">{archiveDialog?.shipmentLabel || "This shipment"}</span> will be removed from the active board,
                      and its email source thread will be ignored during future syncs so it does not get recreated again.
                    </p>
                    <div className="mt-4 rounded-2xl border border-white/10 bg-white/5 p-4 text-sm leading-6 text-slate-300">
                      Use this for bounced emails, malformed AI-created shipments, duplicate noise, or any thread you want the automation loop to stop processing.
                    </div>
                    <div className="mt-4">
                      <label className="mb-2 block text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Archive reason</label>
                      <select
                        className="field-input"
                        value={archiveReasonCode}
                        onChange={(event) => setArchiveReasonCode(event.target.value as ArchiveReasonCode)}
                      >
                        {ARCHIVE_REASON_OPTIONS.map((reason) => (
                          <option key={reason.value} value={reason.value}>{reason.label} - {reason.helper}</option>
                        ))}
                      </select>
                    </div>
                    <div className="mt-4">
                      <label className="mb-2 block text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Optional note</label>
                      <textarea
                        className="field-input min-h-[90px] resize-none"
                        value={archiveReasonNote}
                        onChange={(event) => setArchiveReasonNote(event.target.value)}
                        placeholder="Add context for future audit..."
                      />
                    </div>
                    <div className="mt-5 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
                      <button
                        onClick={() => setArchiveDialog(null)}
                        disabled={submitting !== null}
                        className="action-button bg-white/10 text-white hover:bg-white/15 disabled:opacity-50"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={() => void confirmArchiveShipment()}
                        disabled={submitting !== null}
                        className="action-button bg-amber-300 text-slate-950 hover:brightness-105 disabled:opacity-50"
                      >
                        {submitting === "archive_shipment" ? "Archiving..." : "Archive and ignore source"}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <aside
              className={`fixed inset-y-0 top-0 right-0 z-50 !mt-0 h-[100dvh] w-full max-w-[760px] border-l border-white/10 bg-[linear-gradient(180deg,rgba(13,21,32,0.98),rgba(9,16,26,0.96))] shadow-2xl transition-transform duration-300 ${
                drawerOpen ? "translate-x-0" : "translate-x-full"
              }`}
            >
              <div className="flex h-full flex-col">
                <div className="flex items-start justify-between gap-3 border-b border-white/10 px-5 py-2.5">
                  <div className="min-w-0">
                    <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Shipment workspace</p>
                    <p className="mt-0.5 text-lg font-medium text-white">{selectedShipment ? formatRoute(selectedShipment) : "No shipment selected"}</p>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      {selectedShipment?.quote_token && (
                        <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[10px] uppercase tracking-[0.16em] text-[var(--text-muted)]">
                          {selectedShipment.quote_token}
                        </span>
                      )}
                      {selectedShipment && <ShipmentStatusPill status={selectedShipment.status} />}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {drawerMode !== "edit" && !selectedShipment?.is_archived && (
                      <button
                        onClick={() => enterEditMode()}
                        disabled={!selectedShipment}
                        className="action-button bg-white/10 px-3 py-1.5 text-sm text-white hover:bg-white/15 disabled:opacity-50"
                      >
                        Edit shipment
                      </button>
                    )}
                    <button
                      onClick={closeDrawer}
                      className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-sm text-white transition hover:bg-white/10"
                    >
                      Close
                    </button>
                  </div>
                </div>
                <div ref={drawerScrollRef} className="flex-1 overflow-y-auto px-5 pb-5 pt-4">
                  {renderShipmentWorkspace()}
                </div>
              </div>
            </aside>
          </>
        )}
      </div>
    </main>
  );
}
