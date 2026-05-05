"use client";

import {
  startTransition,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { createPortal } from "react-dom";

import { useFreightSocket } from "@/hooks/useFreightSocket";
import { DateTimePickerField } from "@/components/DateTimePickerField";
import { DashboardLogo } from "@/components/DashboardLogo";
import { OrganizationDrawer } from "@/components/OrganizationDrawer";
import {
  AlertTriangle,
  Archive,
  ArrowRight,
  Bell,
  Calendar,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleDollarSign,
  ClipboardCheck,
  Clock3,
  Inbox,
  Loader2,
  LucideIcon,
  Mail,
  MapPin,
  Package2,
  PencilLine,
  RadioTower,
  RefreshCcw,
  Search,
  Send,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Truck,
  Users,
  X,
} from "lucide-react";
import { PUBLIC_API_URL as API_URL } from "@/constants/publicApi";
import { showToast } from "@/lib/toast-store";

function reportDashboardError(message: string | null | undefined) {
  const trimmed = (message ?? "").trim();
  if (trimmed) showToast(trimmed, { tone: "error", durationMs: 9000 });
}

const OUTLOOK_STATUS_CACHE_TTL_MS = 5 * 60 * 1000;

type DashboardTab = "shipments" | "triage" | "status_ops" | "clients" | "carriers" | "archive";
type WorkspaceSection = "overview" | "bids" | "timeline" | "status" | "docs";
type DrawerMode = "overview" | "edit";
type DrawerMobileTab = "details" | "thread";
type ThreadTab = "timeline" | "client" | "carrier_quotes" | "system";
type ArchiveReasonCode = "duplicate" | "cancelled" | "parsed_error" | "fraud" | "test" | "non_delivery_bounce" | "other";
type FraudBlockScope = "sender_email" | "sender_domain";
type SenderIdentityRole = "customer" | "carrier";
type SenderTrustScope = FraudBlockScope;
type EditFocusTarget = "client_id" | "equipment_type" | "origin" | "destination" | "pallets" | "weight_lb" | "ready_at" | "delivery_at" | "notes";
type StatusQueueAction = "preview" | "approve_and_send" | "approve_and_push" | "rebuild_draft" | "retry_push" | "dismiss";
type EmailTriageAction = "create_shipment" | "mark_not_shipment" | "mark_fraud_email" | "mark_fraud_domain" | "link_to_existing_shipment";
type PartyDrawerState = { kind: "client" | "carrier"; id: string } | null;
type OperatorAction =
  | "resume_workflow"
  | "approve_and_continue"
  | "request_customer_details"
  | "rerun_parsing"
  | "rerun_outreach"
  | "rerun_evaluation"
  | "rerun_status_lookup"
  | "rerun_tms_update"
  | "approve_status_reply"
  | "rerun_document_extraction"
  | "approve_document_values"
  | "ignore_document_warning"
  | "verify_sender"
  | "mark_sender_fraud"
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
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

interface CurrentUserResponse {
  user_id: string;
  organization_id: string;
  role: string;
  permissions: string[];
  email: string;
}

interface FraudDenylistEntryRecord {
  id: string;
  scope: FraudBlockScope;
  value: string;
  reason: string | null;
  source_shipment_id: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

interface ShipmentRecord {
  id: string;
  client_id: string | null;
  email_thread_id: string | null;
  source_mailbox: string | null;
  source_mailbox_owner_user_id: string | null;
  source_mailbox_visibility_mode: string | null;
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
  customer_clarification_requested: boolean;
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
  sender_known: boolean;
  sender_verification_required: boolean;
  fraud_risk_level: string | null;
  fraud_risk_reasons: string[];
  fraud_score: number | null;
  sender_email: string | null;
  sender_domain: string | null;
  sender_verified_at: string | null;
  sender_verified_for_email: string | null;
  sender_verified_for_domain: string | null;
  sender_verified_role: SenderIdentityRole | null;
  sender_verified_scope: SenderTrustScope | null;
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

interface EmailTriageItem {
  id: string;
  email_message_id: string;
  thread_id: string;
  shipment_id: string | null;
  mailbox?: string | null;
  mailbox_owner_user_id?: string | null;
  visibility_mode?: string;
  can_view_body?: boolean;
  can_take_action?: boolean;
  classification: string;
  confidence: number;
  reason: string | null;
  recommended_action: string | null;
  resolved_at: string | null;
  resolved_action: string | null;
  created_shipment_id: string | null;
  sender: string | null;
  subject: string | null;
  body_preview: string | null;
  received_at: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}

interface EmailTriageQueuePage {
  items: EmailTriageItem[];
  has_more: boolean;
  next_offset: number;
}

const TRIAGE_PAGE_SIZE = 25;

interface ShipmentArchivePage {
  items: ShipmentRecord[];
  has_more: boolean;
  next_offset: number;
}

const ARCHIVE_PAGE_SIZE = 25;

interface ClientListPage {
  items: ClientRecord[];
  has_more: boolean;
  next_offset: number;
}

interface CarrierListPage {
  items: CarrierRecord[];
  has_more: boolean;
  next_offset: number;
}

const CUSTOMERS_TAB_PAGE_SIZE = 25;
const CARRIERS_TAB_PAGE_SIZE = 25;
const PARTY_DIRECTORY_PAGE_LIMIT = 100;
const PARTY_DIRECTORY_MAX_ROWS = 5000;

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

interface OutlookWebhookStatusResponse {
  configured: boolean;
  status: string;
  missing_fields: string[];
  expected_notification_url: string | null;
  expected_resource: string | null;
  expected_change_type: string | null;
  subscription_id: string | null;
  subscription_action: string | null;
  expires_at: string | null;
  matching_count: number;
  active_matching_count: number;
  total_subscriptions: number;
  last_checked_at: string | null;
}

interface ShipmentOperatorActionResponse {
  shipment_id?: string;
  action?: OperatorAction;
  status?: string;
  message: string;
  next_action?: string;
  manual_review_required?: boolean;
  archived?: boolean;
  suppression_applied?: boolean;
  suppressed_thread_id?: string | null;
  denylist_entry_id?: string | null;
  denylist_scope?: FraudBlockScope | null;
  denylist_value?: string | null;
  sender_identity_role?: SenderIdentityRole | null;
  sender_trust_scope?: SenderTrustScope | null;
  verified_sender_email?: string | null;
  verified_sender_domain?: string | null;
  verified_client_id?: string | null;
  verified_carrier_id?: string | null;
  decision?: Record<string, unknown>;
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
  dry_run: boolean;
  message_type: string | null;
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
    if (message.dry_run) {
      return {
        card: "border-amber-300/18 bg-amber-300/10 shadow-[0_0_0_1px_rgba(252,211,77,0.04)]",
        label: "Preview",
      };
    }
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

interface FinancialShipmentSummary {
  shipment_id: string;
  best_bid_amount: number | null;
  best_bid_id: string | null;
  bid_count: number;
  priced_bid_count: number;
  margin_amount: number;
  margin_percent: number;
  recommended_quote_amount: number | null;
  selected_bid_amount: number | null;
  selected_quote_amount: number | null;
  currency: string;
}

interface FinancialSummaryResponse {
  shipments: FinancialShipmentSummary[];
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
  fraudBlockScope?: FraudBlockScope;
}

interface TriageActionDialogState {
  action: EmailTriageAction;
  itemId: string;
  subject: string;
  sender: string;
  shipmentId?: string | null;
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

function formatApiErrorBody(body: string, status: number): string {
  const trimmed = body.trim();
  if (!trimmed) return `Request failed: ${status}`;
  try {
    const parsed = JSON.parse(trimmed) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
    if (Array.isArray(parsed.detail)) {
      return parsed.detail
        .map((item: unknown) => {
          if (item && typeof item === "object" && "msg" in item && typeof (item as { msg: unknown }).msg === "string") {
            return (item as { msg: string }).msg;
          }
          return JSON.stringify(item);
        })
        .join("; ");
    }
  } catch {
    // Response body is not JSON; show as-is.
  }
  return trimmed;
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const authToken =
    typeof window !== "undefined"
      ? window.localStorage.getItem("logistic_copilot_auth_token")
      : null;
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
      ...(init?.headers || {}),
    },
  });

  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      if (typeof window !== "undefined") {
        window.localStorage.removeItem("logistic_copilot_auth_token");
        window.location.assign("/");
      }
    }
    const raw = await response.text();
    throw new Error(formatApiErrorBody(raw, response.status));
  }

  return response.json() as Promise<T>;
}

async function collectAllClientRecords(): Promise<ClientRecord[]> {
  const merged: ClientRecord[] = [];
  const seen = new Set<string>();
  let offset = 0;
  while (merged.length < PARTY_DIRECTORY_MAX_ROWS) {
    const params = new URLSearchParams();
    params.set("limit", String(PARTY_DIRECTORY_PAGE_LIMIT));
    params.set("offset", String(offset));
    const page = await fetchJson<ClientListPage>(`/api/freight/clients?${params.toString()}`);
    for (const row of page.items) {
      if (!seen.has(row.id)) {
        seen.add(row.id);
        merged.push(row);
      }
    }
    if (!page.has_more) break;
    offset = page.next_offset;
  }
  return merged;
}

async function collectAllCarrierRecords(): Promise<CarrierRecord[]> {
  const merged: CarrierRecord[] = [];
  const seen = new Set<string>();
  let offset = 0;
  while (merged.length < PARTY_DIRECTORY_MAX_ROWS) {
    const params = new URLSearchParams();
    params.set("limit", String(PARTY_DIRECTORY_PAGE_LIMIT));
    params.set("offset", String(offset));
    const page = await fetchJson<CarrierListPage>(`/api/freight/carriers?${params.toString()}`);
    for (const row of page.items) {
      if (!seen.has(row.id)) {
        seen.add(row.id);
        merged.push(row);
      }
    }
    if (!page.has_more) break;
    offset = page.next_offset;
  }
  return merged;
}

function readCachedOutlookStatus(cacheKey: string) {
  if (typeof window === "undefined") return null;
  try {
    const rawValue = window.localStorage.getItem(cacheKey);
    if (!rawValue) return null;
    const cached = JSON.parse(rawValue) as { cached_at?: number; data?: OutlookWebhookStatusResponse };
    if (!cached.cached_at || !cached.data) return null;
    if (Date.now() - cached.cached_at > OUTLOOK_STATUS_CACHE_TTL_MS) return null;
    return cached.data;
  } catch {
    return null;
  }
}

function writeCachedOutlookStatus(cacheKey: string, data: OutlookWebhookStatusResponse) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(cacheKey, JSON.stringify({ cached_at: Date.now(), data }));
  } catch {
    // Cache writes are best-effort; Outlook status should never block the board.
  }
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

function localDateKey(value: string | null | undefined) {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return new Intl.DateTimeFormat("en-CA").format(parsed);
}

function emailDomain(value: string | null | undefined) {
  const normalized = (value || "").trim().toLowerCase();
  return normalized.includes("@") ? normalized.split("@").pop() || "" : normalized;
}

function shipmentActivityTimestamp(shipment: ShipmentRecord) {
  const createdAt = new Date(shipment.created_at).getTime();
  const updatedAt = new Date(shipment.updated_at).getTime();
  return Math.max(Number.isNaN(createdAt) ? 0 : createdAt, Number.isNaN(updatedAt) ? 0 : updatedAt);
}

function webhookStatusLabel(status: string | null | undefined) {
  if (status === "active") return "Active";
  if (status === "expiring_soon") return "Renew soon";
  if (status === "expired") return "Expired";
  if (status === "not_installed") return "Not installed";
  if (status === "missing_configuration") return "Config missing";
  return "Unknown";
}

function webhookStatusClasses(status: string | null | undefined) {
  if (status === "active") return "border-emerald-300/24 bg-emerald-300/12 text-emerald-50";
  if (status === "expiring_soon") return "border-amber-300/24 bg-amber-300/12 text-amber-50";
  if (status === "expired" || status === "not_installed") return "border-rose-300/24 bg-rose-300/12 text-rose-50";
  return "border-white/10 bg-white/5 text-slate-300";
}

function formatShipmentSchedule(
  displayValue: string | null,
  localValue: string | null,
  utcIsoFallback: string | null = null,
) {
  const rawValue = displayValue
    ? displayValue.replace(/\s*\([^)]+\)\s*$/, "").trim()
    : localValue
      ? localValue.replace("T", " ").trim()
      : utcIsoFallback
        ? utcIsoFallback.trim()
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

function triageClassificationLabel(value: string | null | undefined) {
  if (!value) return "Unknown";
  return value.replaceAll("_", " ");
}

function triageClassificationClasses(value: string | null | undefined) {
  if (value === "fraud_or_phishing") return "border-rose-300/24 bg-rose-300/12 text-rose-50";
  if (value === "needs_operator_triage") return "border-amber-300/24 bg-amber-300/12 text-amber-50";
  if (value === "freight_quote_request") return "border-emerald-300/24 bg-emerald-300/12 text-emerald-50";
  if (value === "carrier_reply" || value === "status_or_ops") return "border-cyan-300/24 bg-cyan-300/12 text-cyan-50";
  return "border-white/10 bg-white/5 text-slate-300";
}

/** Muted text accent for triage list rows (no pill chrome). */
function triageClassificationTextClass(value: string | null | undefined) {
  if (value === "fraud_or_phishing") return "text-rose-200/85";
  if (value === "needs_operator_triage") return "text-amber-200/80";
  if (value === "freight_quote_request") return "text-emerald-200/80";
  if (value === "carrier_reply" || value === "status_or_ops") return "text-cyan-200/80";
  return "text-slate-400";
}

function emailVisibilityLabel(value: string | null | undefined) {
  if (value === "shared_ops") return "Shared";
  if (value === "metadata_only") return "Metadata only";
  return "Private";
}

function emailVisibilityClasses(value: string | null | undefined) {
  if (value === "shared_ops") return "border-cyan-300/20 bg-cyan-300/10 text-cyan-100";
  if (value === "metadata_only") return "border-amber-300/20 bg-amber-300/10 text-amber-100";
  return "border-slate-300/16 bg-white/[0.06] text-slate-200";
}

function hasPermission(user: CurrentUserResponse | null, permission: string) {
  return Boolean(user?.permissions.includes("*") || user?.permissions.includes(permission));
}

function mailboxSourceMeta(mailbox: string | null | undefined, currentUserEmail: string | null | undefined) {
  if (!mailbox) return null;
  const normalizedMailbox = mailbox.trim().toLowerCase();
  const normalizedUser = (currentUserEmail || "").trim().toLowerCase();
  const isMine = Boolean(normalizedMailbox && normalizedMailbox === normalizedUser);
  return {
    caption: isMine ? "My inbox" : "Shared ops inbox",
    address: mailbox.trim(),
  };
}

function mailboxSourceLabel(mailbox: string | null | undefined, currentUserEmail: string | null | undefined) {
  const meta = mailboxSourceMeta(mailbox, currentUserEmail);
  if (!meta) return null;
  return `${meta.caption}: ${meta.address}`;
}

/** Shipments whose intake mailbox belongs to the signed-in user (address match or mailbox owner id). */
function shipmentMatchesMyMailbox(
  shipment: ShipmentRecord,
  userEmail: string | null | undefined,
  userId: string | null | undefined,
): boolean {
  const normalizedUser = (userEmail || "").trim().toLowerCase();
  const mailbox = (shipment.source_mailbox || "").trim().toLowerCase();
  if (normalizedUser && mailbox && mailbox === normalizedUser) {
    return true;
  }
  const uid = (userId || "").trim();
  if (uid && shipment.source_mailbox_owner_user_id && shipment.source_mailbox_owner_user_id === uid) {
    return true;
  }
  return false;
}

function triageActionDialogCopy(action: EmailTriageAction) {
  const copy: Record<EmailTriageAction, { title: string; description: string; confirmLabel: string; tone: "primary" | "danger" }> = {
    create_shipment: {
      title: "Create shipment from this email?",
      description: "This will turn the selected triage email into an active shipment visible to the organization.",
      confirmLabel: "Create shipment",
      tone: "primary",
    },
    mark_not_shipment: {
      title: "Mark this email as not a shipment?",
      description: "This will suppress the source thread so future syncs do not recreate a shipment from it.",
      confirmLabel: "Mark not shipment",
      tone: "primary",
    },
    mark_fraud_email: {
      title: "Block this sender email?",
      description: "Future messages from this exact email address will be treated as fraud/spam and kept out of automation.",
      confirmLabel: "Block email",
      tone: "danger",
    },
    mark_fraud_domain: {
      title: "Block this sender domain?",
      description: "This is a broad action. Future messages from the sender domain will be treated as fraud/spam.",
      confirmLabel: "Block domain",
      tone: "danger",
    },
    link_to_existing_shipment: {
      title: "Link this email to an existing shipment?",
      description: "This will attach the triage email thread to the selected shipment and resolve the triage item.",
      confirmLabel: "Link shipment",
      tone: "primary",
    },
  };
  return copy[action];
}

function formatCurrency(value: number | null | undefined, options?: { compact?: boolean }) {
  if (value === null || value === undefined || Number.isNaN(value)) return "--";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: options?.compact ? 1 : 0,
    notation: options?.compact ? "compact" : "standard",
  }).format(value);
}

function formatRoute(shipment: ShipmentRecord) {
  return `${shipment.origin || "Origin TBD"} -> ${shipment.destination || "Destination TBD"}`;
}

function suggestedContactNameFromEmail(email: string | null) {
  const localPart = (email || "").split("@", 1)[0] || "";
  return localPart.replace(/[._-]+/g, " ").replace(/\b\w/g, (char) => char.toUpperCase()) || "New contact";
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
    ready_at: toDateTimeLocal(shipment?.ready_at_local || shipment?.ready_at || null),
    delivery_at: toDateTimeLocal(shipment?.delivery_at_local || shipment?.delivery_at || null),
    notes: shipment?.notes || "",
  };
}

function statusPillClass(status: string) {
  return SHIPMENT_STATUS_STYLES[status] || "bg-white/10 text-white border-white/10";
}

function shipmentNeedsAttention(shipment: ShipmentRecord) {
  return (
    shipment.sender_verification_required ||
    shipment.fraud_risk_level === "high" ||
    shipment.fraud_risk_level === "medium" ||
    shipment.attention_state !== "none" ||
    shipment.has_active_review
  );
}

function shipmentShowsDeliveryTime(shipment: ShipmentRecord | null) {
  if (!shipment) return false;
  return ["booking_in_progress", "booking_failed", "booked"].includes(shipment.status);
}

/** Inbound identity still blocks automation until operator confirms trust. */
function senderTrustGateActive(shipment: ShipmentRecord): boolean {
  return (
    shipment.sender_verification_required ||
    shipment.fraud_risk_level === "high" ||
    shipment.fraud_risk_level === "medium"
  );
}

function shipmentBlockingBadge(shipment: ShipmentRecord) {
  if (shipment.fraud_risk_level === "high") return "Probable fraud";
  if (shipment.fraud_risk_level === "medium") return "Verify sender";
  if (shipment.sender_verification_required) return "Verify sender";
  if (shipment.attention_state === "missing_details") return "Missing details";
  if (shipment.attention_state === "ambiguous") return "Ambiguous";
  if (shipment.attention_state === "review") return "Needs review";
  if (shipment.attention_state === "docs_warning") return "Docs warning";
  if (shipment.attention_state === "status_review") return "Status review";
  if (shipment.attention_state === "stale") return "Status stale";
  return null;
}

function shipmentFraudIndicators(shipment: ShipmentRecord) {
  const indicators: Array<{
    key: string;
    icon: LucideIcon;
    className: string;
    title: string;
  }> = [];

  if (shipment.sender_verified_at) {
    indicators.push({
      key: "sender-verified",
      icon: CheckCircle2,
      className: "border-emerald-300/30 bg-emerald-300/12 text-emerald-100",
      title: `Sender trust confirmed${
        shipment.sender_verified_for_email ? ` for ${shipment.sender_verified_for_email}` : ""
      } on ${formatDate(shipment.sender_verified_at)}.`,
    });
  }

  if (shipment.fraud_risk_level === "high") {
    indicators.push({
      key: "probable-fraud",
      icon: AlertTriangle,
      className: "border-rose-300/25 bg-rose-300/12 text-rose-100",
      title: `Probable fraud${shipment.fraud_risk_reasons.length ? `: ${shipment.fraud_risk_reasons.join(", ").replaceAll("_", " ")}` : ""}`,
    });
  } else if (shipment.sender_verification_required || shipment.fraud_risk_level === "medium") {
    indicators.push({
      key: "verify-sender",
      icon: Mail,
      className: "border-amber-300/25 bg-amber-300/12 text-amber-100",
      title: "Sender verification required before automation continues.",
    });
  } else if (shipment.sender_known) {
    indicators.push({
      key: "known-sender",
      icon: ShieldCheck,
      className: "border-emerald-300/25 bg-emerald-300/12 text-emerald-100",
      title: "Sender matches a known identity.",
    });
  }

  if (shipment.manual_review_required && shipment.fraud_risk_level !== "high" && !shipment.sender_verification_required) {
    indicators.push({
      key: "manual-review",
      icon: AlertTriangle,
      className: "border-amber-300/20 bg-amber-300/10 text-amber-100",
      title: shipment.attention_reason || "Operator review required.",
    });
  }

  return indicators;
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
  const canRequestCustomerDetails =
    !shipment.customer_clarification_requested &&
    (shipment.status === "waiting_customer_details" || shipment.ai_missing_fields.length > 0);

  if (canRequestCustomerDetails) {
    baseActions.push({
      key: "request_customer_details",
      label: "Request additional details",
      operatorAction: "request_customer_details",
      tone: "warning",
    });
  }

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

  if (senderTrustGateActive(shipment)) {
    return {
      label: "Resolve sender identity",
      reason: "Inbound identity was flagged. Use the Sender trust panel below to identify the sender as a customer or carrier, or block it as fraud.",
      blockingReason: "Choose Customer or Carrier in the Sender trust panel before automation can continue.",
      operatorAction: null,
      requiresSave: true,
      contextActions: baseActions,
    };
  }

  if (!hasMinimumFields(editor)) {
    const missing = ["origin", "destination", "pallets", "weight_lb", "equipment_type", "ready_at"].filter(
      (field) => !editor[field as keyof ShipmentEditorState],
    );
    return {
      label: canRequestCustomerDetails ? "Request additional details" : null,
      reason: shipment.customer_clarification_requested
        ? "Additional details were already requested from the customer. Waiting for their reply."
        : "Fill in the missing shipment fields first, or ask the customer for the missing details.",
      blockingReason: shipment.customer_clarification_requested
        ? "Customer details already requested."
        : `Missing: ${missing.map((field) => field.replaceAll("_", " ")).join(", ")}`,
      operatorAction: canRequestCustomerDetails ? "request_customer_details" : null,
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
  const BOARD_MAILBOX_SCOPE_STORAGE_KEY = "logistic-copilot-board-mailbox-scope";
  const OUTLOOK_STATUS_STORAGE_KEY = "logistic-copilot-outlook-webhook-status";
  const [tab, setTab] = useState<DashboardTab>("shipments");
  const [workspaceSection, setWorkspaceSection] = useState<WorkspaceSection>("overview");
  const [drawerMode, setDrawerMode] = useState<DrawerMode>("overview");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerMobileTab, setDrawerMobileTab] = useState<DrawerMobileTab>("details");
  const [activeBoardFilter, setActiveBoardFilter] = useState<"all" | "today" | "attention">("all");
  const [boardMailboxScope, setBoardMailboxScope] = useState<"org" | "mine">("org");
  const [shipmentSearch, setShipmentSearch] = useState("");
  const [selectedBoardMonth, setSelectedBoardMonth] = useState(currentMonthValue());
  const [monthPickerOpen, setMonthPickerOpen] = useState(false);
  const [monthPickerYear, setMonthPickerYear] = useState(() => Number(currentMonthValue().slice(0, 4)));
  const [overview, setOverview] = useState<OverviewResponse>(EMPTY_OVERVIEW);
  const [clients, setClients] = useState<ClientRecord[]>([]);
  const [carriers, setCarriers] = useState<CarrierRecord[]>([]);
  const [shipments, setShipments] = useState<ShipmentRecord[]>([]);
  const [financialSummary, setFinancialSummary] = useState<FinancialSummaryResponse>({ shipments: [] });
  const [financialSummaryLoading, setFinancialSummaryLoading] = useState(false);
  const [archivedShipments, setArchivedShipments] = useState<ShipmentRecord[]>([]);
  const [archiveSearch, setArchiveSearch] = useState("");
  const [archiveSearchDebounced, setArchiveSearchDebounced] = useState("");
  const [archiveReasonFilter, setArchiveReasonFilter] = useState<ArchiveReasonCode | "all">("all");
  const [archiveMonth, setArchiveMonth] = useState(currentMonthValue());
  const [archiveHasMore, setArchiveHasMore] = useState(false);
  const [archiveNextOffset, setArchiveNextOffset] = useState(0);
  const [archiveListLoading, setArchiveListLoading] = useState(false);
  const [archiveLoadingMore, setArchiveLoadingMore] = useState(false);
  const [customersTabSearch, setCustomersTabSearch] = useState("");
  const [customersTabSearchDebounced, setCustomersTabSearchDebounced] = useState("");
  const [customersTabList, setCustomersTabList] = useState<ClientRecord[]>([]);
  const [customersTabHasMore, setCustomersTabHasMore] = useState(false);
  const [customersTabNextOffset, setCustomersTabNextOffset] = useState(0);
  const [customersTabListLoading, setCustomersTabListLoading] = useState(false);
  const [customersTabLoadingMore, setCustomersTabLoadingMore] = useState(false);
  const [carriersTabSearch, setCarriersTabSearch] = useState("");
  const [carriersTabSearchDebounced, setCarriersTabSearchDebounced] = useState("");
  const [carriersTabList, setCarriersTabList] = useState<CarrierRecord[]>([]);
  const [carriersTabHasMore, setCarriersTabHasMore] = useState(false);
  const [carriersTabNextOffset, setCarriersTabNextOffset] = useState(0);
  const [carriersTabListLoading, setCarriersTabListLoading] = useState(false);
  const [carriersTabLoadingMore, setCarriersTabLoadingMore] = useState(false);
  const [reviewQueue, setReviewQueue] = useState<ReviewQueueItem[]>([]);
  const [statusQueue, setStatusQueue] = useState<StatusQueueItem[]>([]);
  const [emailTriageQueue, setEmailTriageQueue] = useState<EmailTriageItem[]>([]);
  const [events, setEvents] = useState<WorkflowEventRecord[]>([]);
  const [bids, setBids] = useState<BidRecord[]>([]);
  const [documents, setDocuments] = useState<ShipmentDocumentRecord[]>([]);
  const [initialLoading, setInitialLoading] = useState(true);
  const [backgroundRefreshing, setBackgroundRefreshing] = useState(false);
  const [submitting, setSubmitting] = useState<string | null>(null);
  const [userEmail, setUserEmail] = useState<string | null>(null);
  const [currentUserId, setCurrentUserId] = useState<string | null>(null);
  const [currentUser, setCurrentUser] = useState<CurrentUserResponse | null>(null);
  const [webhookStatus, setWebhookStatus] = useState<OutlookWebhookStatusResponse | null>(null);
  const [outlookStatusLoading, setOutlookStatusLoading] = useState(false);
  const [organizationDrawerOpen, setOrganizationDrawerOpen] = useState(false);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [notificationCenterOpen, setNotificationCenterOpen] = useState(false);
  const [notificationLoading, setNotificationLoading] = useState(false);
  const [notificationHasMore, setNotificationHasMore] = useState(false);
  const [notificationOffset, setNotificationOffset] = useState(0);
  const [notificationTotal, setNotificationTotal] = useState(0);
  const [selectedShipmentId, setSelectedShipmentId] = useState<string | null>(null);
  const [selectedStatusTaskId, setSelectedStatusTaskId] = useState<string | null>(null);
  const [selectedTriageItemId, setSelectedTriageItemId] = useState<string | null>(null);
  const [triageSearchInput, setTriageSearchInput] = useState("");
  const [triageSearchDebounced, setTriageSearchDebounced] = useState("");
  /** When false, API omits triage rows with AI confidence ≥ 85% (server-side). */
  const [triageIncludeHighConfidence, setTriageIncludeHighConfidence] = useState(false);
  const [emailTriageHasMore, setEmailTriageHasMore] = useState(false);
  const [emailTriageNextOffset, setEmailTriageNextOffset] = useState(0);
  const [emailTriageListLoading, setEmailTriageListLoading] = useState(false);
  const [emailTriageLoadingMore, setEmailTriageLoadingMore] = useState(false);
  const [triageLinkShipmentId, setTriageLinkShipmentId] = useState("");
  const [partyDrawer, setPartyDrawer] = useState<PartyDrawerState>(null);
  const [clientEditor, setClientEditor] = useState({ name: "", email: "", is_active: true, default_margin_percent: "15", default_margin_floor: "0" });
  const [carrierEditor, setCarrierEditor] = useState({ name: "", email: "", is_active: true, rating: "0", regions: "", equipment: "" });
  const [partyDenylistEntries, setPartyDenylistEntries] = useState<FraudDenylistEntryRecord[]>([]);
  const [partyDenylistReason, setPartyDenylistReason] = useState("");
  const [partyDenylistExpanded, setPartyDenylistExpanded] = useState(false);
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
  const [triageActionDialog, setTriageActionDialog] = useState<TriageActionDialogState | null>(null);
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
  const [senderIdentityRole, setSenderIdentityRole] = useState<SenderIdentityRole>("customer");
  const [senderTrustScope, setSenderTrustScope] = useState<SenderTrustScope>("sender_email");
  const [senderClientId, setSenderClientId] = useState("");
  const [senderCarrierId, setSenderCarrierId] = useState("");
  const [senderContactName, setSenderContactName] = useState("");
  const drawerScrollRef = useRef<HTMLDivElement | null>(null);
  /** Avoid overwriting localStorage with default "org" before hydrate-from-storage runs. */
  const skipMailboxScopePersistRef = useRef(true);
  const monthPickerRef = useRef<HTMLDivElement | null>(null);
  const overviewRefreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const notificationTimersRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const resolvingQuoteTokenRef = useRef<string | null>(null);
  const editFieldRefs = useRef<Partial<Record<EditFocusTarget, HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement | null>>>({});
  const triageDetailPanelRef = useRef<HTMLDivElement | null>(null);
  const triageScrollPendingRef = useRef(false);
  const emailTriageLoadMoreLockedRef = useRef(false);
  const archiveLoadMoreLockedRef = useRef(false);
  const customersTabLoadMoreLockedRef = useRef(false);
  const carriersTabLoadMoreLockedRef = useRef(false);
  const shipmentsRef = useRef<ShipmentRecord[]>([]);
  const archivedShipmentsRef = useRef<ShipmentRecord[]>([]);
  const canUseEmailTriage = hasPermission(currentUser, "freight:write");
  const isViewerRole = (currentUser?.role || "").trim().toLowerCase() === "viewer";
  const effectiveBoardMailboxScope: "org" | "mine" = isViewerRole ? "org" : boardMailboxScope;
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

  const fetchEmailTriageFirstPage = useCallback(async () => {
    if (!canUseEmailTriage) {
      setEmailTriageQueue([]);
      setEmailTriageHasMore(false);
      setEmailTriageNextOffset(0);
      setSelectedTriageItemId(null);
      return;
    }
    setEmailTriageListLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("limit", String(TRIAGE_PAGE_SIZE));
      params.set("offset", "0");
      if (triageSearchDebounced) {
        params.set("q", triageSearchDebounced);
      }
      if (triageIncludeHighConfidence) {
        params.set("include_high_confidence", "true");
      }
      const page = await fetchJson<EmailTriageQueuePage>(`/api/freight/email-triage?${params.toString()}`);
      setEmailTriageQueue(page.items);
      setEmailTriageHasMore(page.has_more);
      setEmailTriageNextOffset(page.next_offset);
      setSelectedTriageItemId((current) =>
        current && page.items.some((item) => item.id === current) ? current : page.items[0]?.id || null,
      );
    } catch (loadError) {
      reportDashboardError(loadError instanceof Error ? loadError.message : "Failed to load email triage.");
    } finally {
      setEmailTriageListLoading(false);
    }
  }, [canUseEmailTriage, triageSearchDebounced, triageIncludeHighConfidence]);

  const loadMoreEmailTriageQueue = useCallback(async () => {
    if (!canUseEmailTriage || !emailTriageHasMore || emailTriageListLoading || emailTriageLoadingMore) {
      return;
    }
    if (emailTriageLoadMoreLockedRef.current) return;
    emailTriageLoadMoreLockedRef.current = true;
    setEmailTriageLoadingMore(true);
    try {
      const params = new URLSearchParams();
      params.set("limit", String(TRIAGE_PAGE_SIZE));
      params.set("offset", String(emailTriageNextOffset));
      if (triageSearchDebounced) {
        params.set("q", triageSearchDebounced);
      }
      if (triageIncludeHighConfidence) {
        params.set("include_high_confidence", "true");
      }
      const page = await fetchJson<EmailTriageQueuePage>(`/api/freight/email-triage?${params.toString()}`);
      setEmailTriageQueue((prev) => {
        const seen = new Set(prev.map((row) => row.id));
        const merged = [...prev];
        for (const row of page.items) {
          if (!seen.has(row.id)) {
            seen.add(row.id);
            merged.push(row);
          }
        }
        return merged;
      });
      setEmailTriageHasMore(page.has_more);
      setEmailTriageNextOffset(page.next_offset);
    } catch (loadError) {
      reportDashboardError(loadError instanceof Error ? loadError.message : "Failed to load more triage emails.");
    } finally {
      emailTriageLoadMoreLockedRef.current = false;
      setEmailTriageLoadingMore(false);
    }
  }, [
    canUseEmailTriage,
    emailTriageHasMore,
    emailTriageListLoading,
    emailTriageLoadingMore,
    emailTriageNextOffset,
    triageSearchDebounced,
    triageIncludeHighConfidence,
  ]);

  useEffect(() => {
    const handle = window.setTimeout(() => setTriageSearchDebounced(triageSearchInput.trim()), 400);
    return () => window.clearTimeout(handle);
  }, [triageSearchInput]);

  useEffect(() => {
    if (!canUseEmailTriage || tab !== "triage") return;
    void fetchEmailTriageFirstPage();
  }, [tab, triageSearchDebounced, triageIncludeHighConfidence, canUseEmailTriage, fetchEmailTriageFirstPage]);

  useEffect(() => {
    const handle = window.setTimeout(() => setArchiveSearchDebounced(archiveSearch.trim()), 400);
    return () => window.clearTimeout(handle);
  }, [archiveSearch]);

  const fetchArchiveFirstPage = useCallback(async () => {
    setArchiveListLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("month", archiveMonth);
      params.set("limit", String(ARCHIVE_PAGE_SIZE));
      params.set("offset", "0");
      if (archiveSearchDebounced) {
        params.set("query", archiveSearchDebounced);
      }
      if (archiveReasonFilter !== "all") {
        params.set("reason_code", archiveReasonFilter);
      }
      const page = await fetchJson<ShipmentArchivePage>(`/api/freight/shipments/archive?${params.toString()}`);
      setArchivedShipments(page.items);
      setArchiveHasMore(page.has_more);
      setArchiveNextOffset(page.next_offset);
    } catch (loadError) {
      reportDashboardError(loadError instanceof Error ? loadError.message : "Failed to load archived shipments.");
    } finally {
      setArchiveListLoading(false);
    }
  }, [archiveMonth, archiveReasonFilter, archiveSearchDebounced]);

  const loadMoreArchivedShipments = useCallback(async () => {
    if (!archiveHasMore || archiveListLoading || archiveLoadingMore || archiveLoadMoreLockedRef.current) {
      return;
    }
    archiveLoadMoreLockedRef.current = true;
    setArchiveLoadingMore(true);
    try {
      const params = new URLSearchParams();
      params.set("month", archiveMonth);
      params.set("limit", String(ARCHIVE_PAGE_SIZE));
      params.set("offset", String(archiveNextOffset));
      if (archiveSearchDebounced) {
        params.set("query", archiveSearchDebounced);
      }
      if (archiveReasonFilter !== "all") {
        params.set("reason_code", archiveReasonFilter);
      }
      const page = await fetchJson<ShipmentArchivePage>(`/api/freight/shipments/archive?${params.toString()}`);
      setArchivedShipments((prev) => {
        const seen = new Set(prev.map((row) => row.id));
        const merged = [...prev];
        for (const row of page.items) {
          if (!seen.has(row.id)) {
            seen.add(row.id);
            merged.push(row);
          }
        }
        return merged;
      });
      setArchiveHasMore(page.has_more);
      setArchiveNextOffset(page.next_offset);
    } catch (loadError) {
      reportDashboardError(loadError instanceof Error ? loadError.message : "Failed to load more archived shipments.");
    } finally {
      archiveLoadMoreLockedRef.current = false;
      setArchiveLoadingMore(false);
    }
  }, [archiveHasMore, archiveListLoading, archiveLoadingMore, archiveMonth, archiveNextOffset, archiveReasonFilter, archiveSearchDebounced]);

  useEffect(() => {
    if (initialLoading || tab !== "archive") {
      return;
    }
    void fetchArchiveFirstPage();
  }, [initialLoading, tab, archiveMonth, archiveReasonFilter, archiveSearchDebounced, fetchArchiveFirstPage]);

  useEffect(() => {
    const handle = window.setTimeout(() => setCustomersTabSearchDebounced(customersTabSearch.trim()), 400);
    return () => window.clearTimeout(handle);
  }, [customersTabSearch]);

  useEffect(() => {
    const handle = window.setTimeout(() => setCarriersTabSearchDebounced(carriersTabSearch.trim()), 400);
    return () => window.clearTimeout(handle);
  }, [carriersTabSearch]);

  const fetchCustomersTabFirstPage = useCallback(async () => {
    setCustomersTabListLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("limit", String(CUSTOMERS_TAB_PAGE_SIZE));
      params.set("offset", "0");
      if (customersTabSearchDebounced) {
        params.set("q", customersTabSearchDebounced);
      }
      const page = await fetchJson<ClientListPage>(`/api/freight/clients?${params.toString()}`);
      setCustomersTabList(page.items);
      setCustomersTabHasMore(page.has_more);
      setCustomersTabNextOffset(page.next_offset);
    } catch (loadError) {
      reportDashboardError(loadError instanceof Error ? loadError.message : "Failed to load customers.");
    } finally {
      setCustomersTabListLoading(false);
    }
  }, [customersTabSearchDebounced]);

  const loadMoreCustomersTab = useCallback(async () => {
    if (!customersTabHasMore || customersTabListLoading || customersTabLoadingMore || customersTabLoadMoreLockedRef.current) {
      return;
    }
    customersTabLoadMoreLockedRef.current = true;
    setCustomersTabLoadingMore(true);
    try {
      const params = new URLSearchParams();
      params.set("limit", String(CUSTOMERS_TAB_PAGE_SIZE));
      params.set("offset", String(customersTabNextOffset));
      if (customersTabSearchDebounced) {
        params.set("q", customersTabSearchDebounced);
      }
      const page = await fetchJson<ClientListPage>(`/api/freight/clients?${params.toString()}`);
      setCustomersTabList((prev) => {
        const seen = new Set(prev.map((row) => row.id));
        const merged = [...prev];
        for (const row of page.items) {
          if (!seen.has(row.id)) {
            seen.add(row.id);
            merged.push(row);
          }
        }
        return merged;
      });
      setCustomersTabHasMore(page.has_more);
      setCustomersTabNextOffset(page.next_offset);
    } catch (loadError) {
      reportDashboardError(loadError instanceof Error ? loadError.message : "Failed to load more customers.");
    } finally {
      customersTabLoadMoreLockedRef.current = false;
      setCustomersTabLoadingMore(false);
    }
  }, [customersTabHasMore, customersTabListLoading, customersTabLoadingMore, customersTabNextOffset, customersTabSearchDebounced]);

  const fetchCarriersTabFirstPage = useCallback(async () => {
    setCarriersTabListLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("limit", String(CARRIERS_TAB_PAGE_SIZE));
      params.set("offset", "0");
      if (carriersTabSearchDebounced) {
        params.set("q", carriersTabSearchDebounced);
      }
      const page = await fetchJson<CarrierListPage>(`/api/freight/carriers?${params.toString()}`);
      setCarriersTabList(page.items);
      setCarriersTabHasMore(page.has_more);
      setCarriersTabNextOffset(page.next_offset);
    } catch (loadError) {
      reportDashboardError(loadError instanceof Error ? loadError.message : "Failed to load carriers.");
    } finally {
      setCarriersTabListLoading(false);
    }
  }, [carriersTabSearchDebounced]);

  const loadMoreCarriersTab = useCallback(async () => {
    if (!carriersTabHasMore || carriersTabListLoading || carriersTabLoadingMore || carriersTabLoadMoreLockedRef.current) {
      return;
    }
    carriersTabLoadMoreLockedRef.current = true;
    setCarriersTabLoadingMore(true);
    try {
      const params = new URLSearchParams();
      params.set("limit", String(CARRIERS_TAB_PAGE_SIZE));
      params.set("offset", String(carriersTabNextOffset));
      if (carriersTabSearchDebounced) {
        params.set("q", carriersTabSearchDebounced);
      }
      const page = await fetchJson<CarrierListPage>(`/api/freight/carriers?${params.toString()}`);
      setCarriersTabList((prev) => {
        const seen = new Set(prev.map((row) => row.id));
        const merged = [...prev];
        for (const row of page.items) {
          if (!seen.has(row.id)) {
            seen.add(row.id);
            merged.push(row);
          }
        }
        return merged;
      });
      setCarriersTabHasMore(page.has_more);
      setCarriersTabNextOffset(page.next_offset);
    } catch (loadError) {
      reportDashboardError(loadError instanceof Error ? loadError.message : "Failed to load more carriers.");
    } finally {
      carriersTabLoadMoreLockedRef.current = false;
      setCarriersTabLoadingMore(false);
    }
  }, [carriersTabHasMore, carriersTabListLoading, carriersTabLoadingMore, carriersTabNextOffset, carriersTabSearchDebounced]);

  useEffect(() => {
    if (initialLoading || tab !== "clients") {
      return;
    }
    void fetchCustomersTabFirstPage();
  }, [initialLoading, tab, customersTabSearchDebounced, fetchCustomersTabFirstPage]);

  useEffect(() => {
    if (initialLoading || tab !== "carriers") {
      return;
    }
    void fetchCarriersTabFirstPage();
  }, [initialLoading, tab, carriersTabSearchDebounced, fetchCarriersTabFirstPage]);

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
  const senderEmailNormalized = (selectedShipment?.sender_email || "").trim().toLowerCase();
  const senderDomainNormalized = (selectedShipment?.sender_domain || "").trim().toLowerCase();
  const matchingSenderClients = useMemo(
    () =>
      clients.filter((client) => {
        const email = client.email.trim().toLowerCase();
        const domain = email.includes("@") ? email.split("@", 2)[1] : "";
        return senderTrustScope === "sender_domain"
          ? Boolean(senderDomainNormalized && domain === senderDomainNormalized)
          : Boolean(senderEmailNormalized && email === senderEmailNormalized);
      }),
    [clients, senderDomainNormalized, senderEmailNormalized, senderTrustScope],
  );
  const matchingSenderCarriers = useMemo(
    () =>
      carriers.filter((carrier) => {
        const email = carrier.email.trim().toLowerCase();
        const domain = email.includes("@") ? email.split("@", 2)[1] : "";
        return senderTrustScope === "sender_domain"
          ? Boolean(senderDomainNormalized && domain === senderDomainNormalized)
          : Boolean(senderEmailNormalized && email === senderEmailNormalized);
      }),
    [carriers, senderDomainNormalized, senderEmailNormalized, senderTrustScope],
  );
  const selectedSenderClient = useMemo(
    () => (senderClientId ? clients.find((client) => client.id === senderClientId) || null : null),
    [clients, senderClientId],
  );
  const selectedSenderCarrier = useMemo(
    () => (senderCarrierId ? carriers.find((carrier) => carrier.id === senderCarrierId) || null : null),
    [carriers, senderCarrierId],
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
  const selectedTriageItem = useMemo(
    () => emailTriageQueue.find((item) => item.id === selectedTriageItemId) || emailTriageQueue[0] || null,
    [emailTriageQueue, selectedTriageItemId],
  );
  const selectedPartyClient = useMemo(
    () => (partyDrawer?.kind === "client" ? clients.find((client) => client.id === partyDrawer.id) || null : null),
    [clients, partyDrawer],
  );
  const selectedPartyCarrier = useMemo(
    () => (partyDrawer?.kind === "carrier" ? carriers.find((carrier) => carrier.id === partyDrawer.id) || null : null),
    [carriers, partyDrawer],
  );
  const selectedPartyEmail = selectedPartyClient?.email || selectedPartyCarrier?.email || "";
  const selectedPartyDomain = emailDomain(selectedPartyEmail);
  const shipmentStatusTasks = useMemo(
    () => statusQueue.filter((task) => task.shipment_id === selectedShipmentId && task.queue_scope === "active"),
    [selectedShipmentId, statusQueue],
  );
  const actionModel = useMemo(
    () => (selectedShipment ? deriveShipmentActionModel(selectedShipment, shipmentEditor, shipmentStatusTasks, bids.length) : null),
    [selectedShipment, shipmentEditor, shipmentStatusTasks, bids.length],
  );
  const contextMenuShipment = useMemo(
    () =>
      contextMenu
        ? shipments.find((shipment) => shipment.id === contextMenu.shipmentId) ||
          archivedShipments.find((shipment) => shipment.id === contextMenu.shipmentId) ||
          null
        : null,
    [archivedShipments, contextMenu, shipments],
  );
  const contextMenuStatusTasks = useMemo(
    () =>
      contextMenuShipment
        ? statusQueue.filter((task) => task.shipment_id === contextMenuShipment.id && task.queue_scope === "active")
        : [],
    [contextMenuShipment, statusQueue],
  );
  const contextMenuActionModel = useMemo(
    () =>
      contextMenuShipment
        ? deriveShipmentActionModel(
            contextMenuShipment,
            contextMenuShipment.id === selectedShipmentId ? shipmentEditor : buildShipmentEditor(contextMenuShipment),
            contextMenuStatusTasks,
            bids.length,
          )
        : null,
    [bids.length, contextMenuShipment, contextMenuStatusTasks, selectedShipmentId, shipmentEditor],
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
    const today = localDateKey(new Date().toISOString());
    const query = shipmentSearch.trim().toLowerCase();
    const filtered = shipments.filter((shipment) => {
      if (activeBoardFilter === "attention" && !shipmentNeedsAttention(shipment)) {
        return false;
      }
      if (activeBoardFilter === "today") {
        if (localDateKey(shipment.created_at) !== today && localDateKey(shipment.updated_at) !== today) {
          return false;
        }
      }
      if (effectiveBoardMailboxScope === "mine" && !shipmentMatchesMyMailbox(shipment, userEmail, currentUserId)) {
        return false;
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
    if (activeBoardFilter !== "today") {
      return filtered;
    }
    return [...filtered].sort((first, second) => shipmentActivityTimestamp(second) - shipmentActivityTimestamp(first));
  }, [shipments, activeBoardFilter, shipmentSearch, effectiveBoardMailboxScope, userEmail, currentUserId]);

  const mailboxMineEligibleCount = useMemo(() => {
    const today = localDateKey(new Date().toISOString());
    return shipments.filter((shipment) => {
      if (activeBoardFilter === "attention" && !shipmentNeedsAttention(shipment)) {
        return false;
      }
      if (activeBoardFilter === "today") {
        if (localDateKey(shipment.created_at) !== today && localDateKey(shipment.updated_at) !== today) {
          return false;
        }
      }
      return shipmentMatchesMyMailbox(shipment, userEmail, currentUserId);
    }).length;
  }, [shipments, activeBoardFilter, userEmail, currentUserId]);

  useLayoutEffect(() => {
    if (!triageScrollPendingRef.current) return;
    if (tab !== "triage") {
      triageScrollPendingRef.current = false;
      return;
    }
    triageScrollPendingRef.current = false;
    if (typeof window === "undefined" || !window.matchMedia("(max-width: 1279px)").matches) return;
    triageDetailPanelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [selectedTriageItemId, tab]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (currentQuoteParam()) return;
    setSelectedShipmentId((current) => {
      if (!current) return current;
      if (boardShipments.some((s) => s.id === current)) return current;
      return boardShipments[0]?.id ?? null;
    });
  }, [boardShipments]);

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
  const financialByShipmentId = useMemo(() => {
    return new Map(financialSummary.shipments.map((item) => [item.shipment_id, item]));
  }, [financialSummary]);
  const financialSnapshot = useMemo(() => {
    const rows = boardShipments.map((shipment) => ({
      shipment,
      financial: financialByShipmentId.get(shipment.id) || null,
    }));
    const quoteRows = rows
      .map((row) => ({
        ...row,
        projectedQuote: row.financial?.selected_quote_amount || row.financial?.recommended_quote_amount || 0,
        projectedMargin: row.financial?.margin_amount || 0,
        bestBid: row.financial?.selected_bid_amount || row.financial?.best_bid_amount || 0,
      }))
      .filter((row) => row.projectedQuote > 0);
    const pipelineValue = quoteRows.reduce((total, row) => total + row.projectedQuote, 0);
    const bookedValue = quoteRows
      .filter((row) => row.shipment.board_stage === "booked")
      .reduce((total, row) => total + row.projectedQuote, 0);
    const quotedValue = quoteRows
      .filter((row) => row.shipment.board_stage === "quoted")
      .reduce((total, row) => total + row.projectedQuote, 0);
    const waitingBidExposure = rows
      .filter((row) => row.shipment.board_stage === "waiting_bids")
      .reduce((total, row) => total + (row.financial?.best_bid_amount || 0), 0);
    const atRiskValue = quoteRows
      .filter((row) => shipmentNeedsAttention(row.shipment))
      .reduce((total, row) => total + row.projectedQuote, 0);
    const bidCostTotal = quoteRows.reduce((total, row) => total + row.bestBid, 0);
    const marginTotal = quoteRows.reduce((total, row) => total + row.projectedMargin, 0);
    const topOpportunity = [...quoteRows].sort((first, second) => second.projectedMargin - first.projectedMargin)[0] || null;

    return {
      rows,
      pipelineValue,
      bookedValue,
      quotedValue,
      waitingBidExposure,
      atRiskValue,
      avgMarginPercent: bidCostTotal > 0 ? Math.round((marginTotal / bidCostTotal) * 1000) / 10 : 0,
      noBidCount: rows.filter((row) => (row.financial?.priced_bid_count || 0) === 0).length,
      readyToQuoteCount: rows.filter((row) => (row.financial?.priced_bid_count || 0) > 0 && row.shipment.board_stage !== "booked").length,
      topOpportunity,
    };
  }, [boardShipments, financialByShipmentId]);
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
      reportDashboardError(loadError instanceof Error ? loadError.message : "Failed to load notifications.");
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
      showToast(`Shipment ${normalized} was not found.`, { tone: "error" });
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

  async function refreshFinancialSummary(month: string | null = activeBoardFilter === "today" ? null : selectedBoardMonth, options?: { silent?: boolean }) {
    if (!options?.silent) {
      setFinancialSummaryLoading(true);
    }
    try {
      const query = month ? `?month=${encodeURIComponent(month)}` : "";
      const financialData = await fetchJson<FinancialSummaryResponse>(`/api/freight/financial-summary${query}`);
      setFinancialSummary(financialData);
    } finally {
      if (!options?.silent) {
        setFinancialSummaryLoading(false);
      }
    }
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

  async function refreshPartyDenylist(email: string) {
    const normalized = email.trim().toLowerCase();
    if (!normalized) {
      setPartyDenylistEntries([]);
      return;
    }
    const entries = await fetchJson<FraudDenylistEntryRecord[]>(`/api/freight/fraud-denylist?value=${encodeURIComponent(normalized)}`);
    setPartyDenylistEntries(entries);
  }

  async function refreshShipmentList(month: string | null = activeBoardFilter === "today" ? null : selectedBoardMonth) {
    const query = month ? `?month=${encodeURIComponent(month)}` : "";
    const shipmentData = await fetchJson<ShipmentRecord[]>(`/api/freight/shipments${query}`);
    setShipments(shipmentData);
    setSelectedShipmentId((current) => {
      if (currentQuoteParam() && current) return current;
      return current && shipmentData.some((item) => item.id === current) ? current : shipmentData[0]?.id || null;
    });
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
    try {
      const boardMonthFilter = activeBoardFilter === "today" ? null : selectedBoardMonth;
      const shipmentQuery = boardMonthFilter ? `?month=${encodeURIComponent(boardMonthFilter)}` : "";
      const meData = await fetchJson<CurrentUserResponse>("/api/auth/me");
      const userCanUseEmailTriage = hasPermission(meData, "freight:write");
      const [overviewData, shipmentData, reviewData, statusQueueData, clientData, carrierData] = await Promise.all([
        fetchJson<OverviewResponse>("/api/freight/overview"),
        fetchJson<ShipmentRecord[]>(`/api/freight/shipments${shipmentQuery}`),
        fetchJson<ReviewQueueItem[]>("/api/freight/reviews"),
        fetchJson<StatusQueueItem[]>("/api/freight/status-queue?include_resolved=true"),
        collectAllClientRecords(),
        collectAllCarrierRecords(),
      ]);

      startTransition(() => {
        setCurrentUser(meData);
        setUserEmail(meData.email);
        setCurrentUserId(meData.user_id);
        setOverview(overviewData);
        setClients(clientData);
        setCarriers(carrierData);
        setShipments(shipmentData);
        setReviewQueue(reviewData);
        setStatusQueue(statusQueueData);
        if (!userCanUseEmailTriage) {
          setEmailTriageQueue([]);
          setEmailTriageHasMore(false);
          setEmailTriageNextOffset(0);
          setSelectedTriageItemId(null);
        }
        if (!userCanUseEmailTriage && tab === "triage") {
          setTab("shipments");
        }
        setSelectedShipmentId((current) => {
          if (currentQuoteParam() && current) return current;
          return current && shipmentData.some((item) => item.id === current) ? current : shipmentData[0]?.id || null;
        });
        setSelectedStatusTaskId((current) => current && statusQueueData.some((item) => item.task_id === current) ? current : statusQueueData[0]?.task_id || null);
        if (!bidForm.carrier_id && carrierData[0]) {
          setBidForm((current) => ({ ...current, carrier_id: carrierData[0].id }));
        }
      });
      if (userCanUseEmailTriage && tab === "triage") {
        void fetchEmailTriageFirstPage();
      }
      void refreshFinancialSummary(boardMonthFilter).catch(() => undefined);
      void loadWebhookStatus({ silent: true, allowCache: true }).catch(() => undefined);
    } catch (loadError) {
      reportDashboardError(loadError instanceof Error ? loadError.message : "Failed to load dashboard.");
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
    setDrawerMobileTab("details");
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

  function openClientDrawer(client: ClientRecord) {
    setClientEditor({
      name: client.name,
      email: client.email,
      is_active: client.is_active,
      default_margin_percent: String(client.default_margin_percent),
      default_margin_floor: String(client.default_margin_floor),
    });
    setPartyDenylistReason("");
    setPartyDenylistExpanded(false);
    setPartyDrawer({ kind: "client", id: client.id });
    void refreshPartyDenylist(client.email).catch(() => undefined);
  }

  function openCarrierDrawer(carrier: CarrierRecord) {
    setCarrierEditor({
      name: carrier.name,
      email: carrier.email,
      is_active: carrier.is_active,
      rating: String(carrier.rating),
      regions: carrier.regions.join(", "),
      equipment: carrier.equipment.join(", "),
    });
    setPartyDenylistReason("");
    setPartyDenylistExpanded(false);
    setPartyDrawer({ kind: "carrier", id: carrier.id });
    void refreshPartyDenylist(carrier.email).catch(() => undefined);
  }

  function closePartyDrawer() {
    setPartyDrawer(null);
    setPartyDenylistEntries([]);
    setPartyDenylistReason("");
    setPartyDenylistExpanded(false);
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
      const boardMonthFilter = activeBoardFilter === "today" ? null : selectedBoardMonth;
      void Promise.all([refreshOverview(), refreshReviewQueue(), refreshStatusQueue(), refreshShipmentList(boardMonthFilter)])
        .catch((loadError) => {
          reportDashboardError(loadError instanceof Error ? loadError.message : "Failed to refresh dashboard.");
        })
        .finally(() => {
          setBackgroundRefreshing(false);
        });
      void refreshFinancialSummary(boardMonthFilter, { silent: true }).catch(() => undefined);
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
    const storedMailbox = window.localStorage.getItem(BOARD_MAILBOX_SCOPE_STORAGE_KEY);
    if (storedMailbox === "mine" || storedMailbox === "org") {
      setBoardMailboxScope(storedMailbox);
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (skipMailboxScopePersistRef.current) {
      skipMailboxScopePersistRef.current = false;
      return;
    }
    if (isViewerRole) return;
    window.localStorage.setItem(BOARD_MAILBOX_SCOPE_STORAGE_KEY, boardMailboxScope);
  }, [boardMailboxScope, isViewerRole]);

  useEffect(() => {
    if (!isViewerRole) return;
    setBoardMailboxScope("org");
  }, [isViewerRole]);

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
    setMonthPickerYear(Number(selectedBoardMonth.slice(0, 4)));
  }, [selectedBoardMonth]);

  useEffect(() => {
    if (initialLoading || tab !== "shipments") {
      return;
    }
    const boardMonthFilter = activeBoardFilter === "today" ? null : selectedBoardMonth;
    void refreshShipmentList(boardMonthFilter).catch((loadError) => {
      reportDashboardError(loadError instanceof Error ? loadError.message : "Failed to refresh shipments for selected month.");
    });
    void refreshFinancialSummary(boardMonthFilter).catch(() => undefined);
  }, [activeBoardFilter, selectedBoardMonth, initialLoading, tab]);

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
        reportDashboardError(loadError instanceof Error ? loadError.message : "Failed to refresh shipment.");
      });
      if (shipmentId === selectedShipmentId) {
        void refreshSelectedShipmentContext(shipmentId).catch((loadError) => {
          reportDashboardError(loadError instanceof Error ? loadError.message : "Failed to refresh shipment context.");
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
            reportDashboardError(loadError instanceof Error ? loadError.message : "Failed to refresh shipment context.");
          });
        }
      }
      void refreshSelectedShipment(shipment_id).catch((loadError) => {
        reportDashboardError(loadError instanceof Error ? loadError.message : "Failed to refresh shipment.");
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
      setDrawerMobileTab("details");
      return;
    }
    setDrawerMode("overview");
    setDrawerMobileTab("details");
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
    setSenderIdentityRole(selectedShipment?.sender_verified_role || "customer");
    setSenderTrustScope(selectedShipment?.sender_verified_scope || "sender_email");
    setSenderClientId(selectedShipment?.client_id || "");
    setSenderCarrierId("");
    setSenderContactName(suggestedContactNameFromEmail(selectedShipment?.sender_email || null));
  }, [selectedShipment?.id, selectedShipment?.sender_email, selectedShipment?.sender_verified_role, selectedShipment?.sender_verified_scope, selectedShipment?.client_id]);

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
    const handleWindowClick = () => {
      setContextMenu(null);
    };
    const closeContextMenuOnScroll = () => {
      setContextMenu(null);
    };
    const handleEsc = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setContextMenu(null);
        setMonthPickerOpen(false);
      }
    };
    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (monthPickerRef.current && !monthPickerRef.current.contains(target)) {
        setMonthPickerOpen(false);
      }
    };
    window.addEventListener("click", handleWindowClick);
    window.addEventListener("contextmenu", handleWindowClick);
    window.addEventListener("keydown", handleEsc);
    window.addEventListener("mousedown", handlePointerDown);
    window.addEventListener("scroll", closeContextMenuOnScroll, true);
    return () => {
      window.removeEventListener("click", handleWindowClick);
      window.removeEventListener("contextmenu", handleWindowClick);
      window.removeEventListener("keydown", handleEsc);
      window.removeEventListener("mousedown", handlePointerDown);
      window.removeEventListener("scroll", closeContextMenuOnScroll, true);
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
    try {
      const response = await fetchJson<ShipmentOperatorActionResponse>(`/api/freight/shipments/${targetShipmentId}/operator-action`, {
        method: "POST",
        body: JSON.stringify({ action, reason, suppress_source_thread: suppressSourceThread }),
      });
      showToast(response.message);
      await Promise.all([
        refreshSelectedShipment(targetShipmentId),
        refreshOverview(),
        refreshFinancialSummary(),
        refreshReviewQueue(),
        refreshStatusQueue(),
      ]);
      if (targetShipmentId === selectedShipmentId) {
        await refreshSelectedShipmentContext(targetShipmentId);
      }
    } catch (submitError) {
      reportDashboardError(submitError instanceof Error ? submitError.message : "Failed to run action.");
    } finally {
      setSubmitting(null);
    }
  }

  function openFraudArchiveDialog(shipmentId?: string, fraudBlockScope: FraudBlockScope = "sender_email") {
    const targetShipmentId = shipmentId || selectedShipment?.id;
    if (!targetShipmentId) return;
    const targetShipment = shipments.find((shipment) => shipment.id === targetShipmentId) || selectedShipment;
    setContextMenu(null);
    setArchiveReasonCode("fraud");
    setArchiveReasonNote(
      fraudBlockScope === "sender_domain"
        ? "sender domain flagged as fraud by operator"
        : "sender email flagged as fraud by operator",
    );
    setArchiveDialog({
      shipmentId: targetShipmentId,
      shipmentLabel: targetShipment ? formatRoute(targetShipment) : "this shipment",
      fraudBlockScope,
    });
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
    try {
      const response = await fetchJson<ShipmentOperatorActionResponse>(`/api/freight/shipments/${archiveDialog.shipmentId}/operator-action`, {
        method: "POST",
        body: JSON.stringify({
          action: archiveDialog.fraudBlockScope && archiveReasonCode === "fraud" ? "mark_sender_fraud" : "archive_shipment",
          reason_code: archiveReasonCode,
          reason_note: archiveReasonNote.trim() || null,
          suppress_source_thread: true,
          fraud_block_scope: archiveDialog.fraudBlockScope || null,
        }),
      });
      showToast(response.message);
      setDrawerOpen(false);
      setContextMenu(null);
      setArchiveDialog(null);
      removeShipmentFromState(archiveDialog.shipmentId);
      await fetchArchiveFirstPage();
      await Promise.all([refreshOverview(), refreshReviewQueue(), refreshStatusQueue()]);
    } catch (submitError) {
      reportDashboardError(submitError instanceof Error ? submitError.message : "Failed to archive shipment.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handleStatusQueueAction(action: StatusQueueAction) {
    if (!selectedStatusTask) return;
    setSubmitting(`status-${action}`);
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
      showToast(response.message);
      setSelectedShipmentId(response.shipment_id);
      await Promise.all([
        refreshSelectedShipment(response.shipment_id),
        refreshOverview(),
        refreshStatusQueue(),
      ]);
      await refreshSelectedShipmentContext(response.shipment_id);
    } catch (submitError) {
      reportDashboardError(submitError instanceof Error ? submitError.message : "Failed to process status task.");
    } finally {
      setSubmitting(null);
    }
  }

  function openTriageActionDialog(action: EmailTriageAction, item = selectedTriageItem) {
    if (!item || !canUseEmailTriage) return;
    setTriageActionDialog({
      action,
      itemId: item.id,
      subject: item.subject || "No subject",
      sender: item.sender || "Unknown sender",
      shipmentId: action === "link_to_existing_shipment" ? triageLinkShipmentId || null : null,
    });
  }

  async function handleEmailTriageAction(action: EmailTriageAction, itemId = selectedTriageItem?.id) {
    if (!canUseEmailTriage) {
      reportDashboardError("Email triage is available only to operators.");
      return;
    }
    if (!itemId) return;
    setSubmitting(`triage-${action}`);
    try {
      const response = await fetchJson<EmailTriageItem>(`/api/freight/email-triage/${itemId}/action`, {
        method: "POST",
        body: JSON.stringify({
          action,
          shipment_id: action === "link_to_existing_shipment" ? triageLinkShipmentId || null : null,
          reason: `operator_${action}`,
        }),
      });
      const createdShipmentId = response.created_shipment_id || response.shipment_id;
      showToast(`Email triage resolved as ${triageClassificationLabel(response.resolved_action || action)}.`);
      await Promise.all([fetchEmailTriageFirstPage(), refreshOverview(), refreshShipmentList(), refreshReviewQueue()]);
      if (createdShipmentId) {
        setSelectedShipmentId(createdShipmentId);
        setTab("shipments");
        await refreshSelectedShipmentContext(createdShipmentId);
      }
      setTriageLinkShipmentId("");
    } catch (submitError) {
      reportDashboardError(submitError instanceof Error ? submitError.message : "Failed to resolve triage item.");
    } finally {
      setSubmitting(null);
      setTriageActionDialog(null);
    }
  }

  async function confirmTriageAction() {
    if (!triageActionDialog) return;
    if (triageActionDialog.action === "link_to_existing_shipment" && triageActionDialog.shipmentId) {
      setTriageLinkShipmentId(triageActionDialog.shipmentId);
    }
    await handleEmailTriageAction(triageActionDialog.action, triageActionDialog.itemId);
  }

  async function persistShipmentEdits() {
    if (!selectedShipment) return false;
    setSubmitting("save_shipment");
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
      showToast("Shipment details saved.");
      await Promise.all([
        refreshOverview(),
        refreshReviewQueue(),
        refreshStatusQueue(),
      ]);
      await refreshSelectedShipmentContext(selectedShipment.id);
      setDrawerMode("overview");
      return true;
    } catch (submitError) {
      reportDashboardError(submitError instanceof Error ? submitError.message : "Failed to save shipment.");
      return false;
    } finally {
      setSubmitting(null);
    }
  }

  async function runMagicFill(field: "ready_at_local") {
    if (!selectedShipment) return;
    setMagicFillingField(field);
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
      showToast(response.message);
    } catch (actionError) {
      console.error("[magic-fill] failed", actionError);
      reportDashboardError(actionError instanceof Error ? actionError.message : "Magic fill failed.");
    } finally {
      setMagicFillingField(null);
    }
  }

  async function runStatefulPrimaryAction(shipmentId = selectedShipment?.id, model = actionModel) {
    if (!shipmentId || !selectedShipment || !model?.operatorAction) return;
    if (model.requiresSave || shipmentFormDirty) {
      const saved = await persistShipmentEdits();
      if (!saved) return;
    }
    await handleOperatorAction(model.operatorAction, shipmentId);
  }

  async function handleContextAction(action: ShipmentContextAction, shipmentId = selectedShipment?.id) {
    setContextMenu(null);
    if (action.key === "edit") {
      enterEditMode();
      return;
    }
    if (!shipmentId || !selectedShipment || !action.operatorAction) return;
    if (action.requiresSave || shipmentFormDirty) {
      const saved = await persistShipmentEdits();
      if (!saved) return;
    }
    await handleOperatorAction(action.operatorAction, shipmentId);
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
      showToast("Shipment created.");
      await Promise.all([refreshOverview(), refreshReviewQueue(), refreshStatusQueue()]);
    } catch (submitError) {
      reportDashboardError(submitError instanceof Error ? submitError.message : "Failed to create shipment.");
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
      showToast("Client added.");
      setClientForm({ name: "", email: "", default_margin_percent: "15", default_margin_floor: "0" });
      openClientDrawer(createdClient);
      void fetchCustomersTabFirstPage();
      await refreshOverview();
    } catch (submitError) {
      reportDashboardError(submitError instanceof Error ? submitError.message : "Failed to create client.");
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
      showToast("Carrier added.");
      setCarrierForm({ name: "", email: "", rating: "0", regions: "midwest,northeast", equipment: "dry van" });
      openCarrierDrawer(createdCarrier);
      void fetchCarriersTabFirstPage();
      await refreshOverview();
    } catch (submitError) {
      reportDashboardError(submitError instanceof Error ? submitError.message : "Failed to create carrier.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handleSaveClientDetails() {
    if (!selectedPartyClient) return;
    setSubmitting("save_client");
    try {
      const updatedClient = await fetchJson<ClientRecord>(`/api/freight/clients/${selectedPartyClient.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: clientEditor.name,
          email: clientEditor.email,
          is_active: clientEditor.is_active,
          default_margin_percent: Number(clientEditor.default_margin_percent || 0),
          default_margin_floor: Number(clientEditor.default_margin_floor || 0),
        }),
      });
      setClients((current) => current.map((client) => (client.id === updatedClient.id ? updatedClient : client)));
      setCustomersTabList((current) => current.map((client) => (client.id === updatedClient.id ? updatedClient : client)));
      showToast("Customer details saved.");
      await refreshPartyDenylist(updatedClient.email);
    } catch (submitError) {
      reportDashboardError(submitError instanceof Error ? submitError.message : "Failed to save customer.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handleSaveCarrierDetails() {
    if (!selectedPartyCarrier) return;
    setSubmitting("save_carrier");
    try {
      const updatedCarrier = await fetchJson<CarrierRecord>(`/api/freight/carriers/${selectedPartyCarrier.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: carrierEditor.name,
          email: carrierEditor.email,
          rating: Number(carrierEditor.rating || 0),
          is_active: carrierEditor.is_active,
          regions: carrierEditor.regions.split(",").map((item) => item.trim()).filter(Boolean),
          equipment: carrierEditor.equipment.split(",").map((item) => item.trim()).filter(Boolean),
          metadata: selectedPartyCarrier.metadata || {},
        }),
      });
      setCarriers((current) => current.map((carrier) => (carrier.id === updatedCarrier.id ? updatedCarrier : carrier)));
      setCarriersTabList((current) => current.map((carrier) => (carrier.id === updatedCarrier.id ? updatedCarrier : carrier)));
      showToast("Carrier details saved.");
      await refreshPartyDenylist(updatedCarrier.email);
    } catch (submitError) {
      reportDashboardError(submitError instanceof Error ? submitError.message : "Failed to save carrier.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handleCreatePartyDenylistEntry(scope: FraudBlockScope) {
    const value = scope === "sender_domain" ? selectedPartyDomain : selectedPartyEmail.trim().toLowerCase();
    if (!value) return;
    setSubmitting("party_denylist");
    try {
      await fetchJson<FraudDenylistEntryRecord>("/api/freight/fraud-denylist", {
        method: "POST",
        body: JSON.stringify({
          scope,
          value,
          reason: partyDenylistReason.trim() || `${partyDrawer?.kind === "carrier" ? "Carrier" : "Customer"} blocked by operator`,
          is_active: true,
        }),
      });
      setPartyDenylistReason("");
      await refreshPartyDenylist(selectedPartyEmail);
      showToast("Fraud denylist updated.");
    } catch (submitError) {
      reportDashboardError(submitError instanceof Error ? submitError.message : "Failed to update fraud denylist.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handleTogglePartyDenylistEntry(entry: FraudDenylistEntryRecord) {
    setSubmitting("party_denylist");
    try {
      await fetchJson<FraudDenylistEntryRecord>(`/api/freight/fraud-denylist/${entry.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          reason: entry.reason,
          is_active: !entry.is_active,
        }),
      });
      await refreshPartyDenylist(selectedPartyEmail);
      showToast(entry.is_active ? "Fraud denylist entry disabled." : "Fraud denylist entry enabled.");
    } catch (submitError) {
      reportDashboardError(submitError instanceof Error ? submitError.message : "Failed to update fraud denylist entry.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handleVerifySenderIdentity() {
    if (!selectedShipment?.sender_email) {
      reportDashboardError("No inbound sender email is available for verification.");
      return;
    }
    setSubmitting("verify_sender");
    try {
      let clientId = senderClientId || "";
      let carrierId = senderCarrierId || "";
      if (senderIdentityRole === "customer" && !clientId) {
        const createdClient = await fetchJson<ClientRecord>("/api/freight/clients", {
          method: "POST",
          body: JSON.stringify({
            name: senderContactName.trim() || suggestedContactNameFromEmail(selectedShipment.sender_email),
            email: selectedShipment.sender_email,
            is_active: true,
            default_margin_percent: Number(clientForm.default_margin_percent || 15),
            default_margin_floor: Number(clientForm.default_margin_floor || 0),
          }),
        });
        clientId = createdClient.id;
        setClients((current) => [createdClient, ...current]);
        setSenderClientId(createdClient.id);
      }
      if (senderIdentityRole === "carrier" && !carrierId) {
        const createdCarrier = await fetchJson<CarrierRecord>("/api/freight/carriers", {
          method: "POST",
          body: JSON.stringify({
            name: senderContactName.trim() || suggestedContactNameFromEmail(selectedShipment.sender_email),
            email: selectedShipment.sender_email,
            rating: 0,
            is_active: true,
            regions: [],
            equipment: [],
            metadata: {},
          }),
        });
        carrierId = createdCarrier.id;
        setCarriers((current) => [createdCarrier, ...current]);
        setSenderCarrierId(createdCarrier.id);
      }
      const response = await fetchJson<ShipmentOperatorActionResponse>(`/api/freight/shipments/${selectedShipment.id}/operator-action`, {
        method: "POST",
        body: JSON.stringify({
          action: "verify_sender",
          sender_identity_role: senderIdentityRole,
          sender_trust_scope: senderTrustScope,
          client_id: senderIdentityRole === "customer" ? clientId : null,
          carrier_id: senderIdentityRole === "carrier" ? carrierId : null,
        }),
      });
      showToast(response.message);
      await Promise.all([
        refreshSelectedShipment(selectedShipment.id),
        refreshOverview(),
        refreshFinancialSummary(),
        refreshReviewQueue(),
        refreshStatusQueue(),
      ]);
      await refreshSelectedShipmentContext(selectedShipment.id);
    } catch (submitError) {
      reportDashboardError(submitError instanceof Error ? submitError.message : "Failed to verify sender identity.");
    } finally {
      setSubmitting(null);
    }
  }

  async function loadWebhookStatus(options?: { silent?: boolean; allowCache?: boolean }) {
    if (options?.allowCache) {
      const cachedStatus = readCachedOutlookStatus(OUTLOOK_STATUS_STORAGE_KEY);
      if (cachedStatus) {
        setWebhookStatus(cachedStatus);
      }
    }
    setOutlookStatusLoading(true);
    try {
      const response = await fetchJson<OutlookWebhookStatusResponse>("/api/freight/outlook/auto-sync/status");
      setWebhookStatus(response);
      writeCachedOutlookStatus(OUTLOOK_STATUS_STORAGE_KEY, response);
      if (!options?.silent) {
        showToast(`Outlook auto-sync check: ${webhookStatusLabel(response.status)}.`, { tone: "info" });
      }
    } catch (statusError) {
      if (!options?.silent) {
        setWebhookStatus(null);
        reportDashboardError(statusError instanceof Error ? statusError.message : "Failed to check Outlook auto-sync.");
      }
    } finally {
      setOutlookStatusLoading(false);
    }
  }

  async function handleEvaluateBids() {
    if (!selectedShipment) return;
    setSubmitting("evaluate");
    try {
      const response = await fetchJson<EvaluationResponse>(`/api/freight/shipments/${selectedShipment.id}/evaluate`, { method: "POST" });
      setEvaluation(response);
      showToast(`Best bid selected at $${response.selected_amount.toFixed(2)}.`);
      await Promise.all([
        refreshSelectedShipment(selectedShipment.id),
        refreshOverview(),
        refreshFinancialSummary(),
      ]);
      await refreshSelectedShipmentContext(selectedShipment.id);
    } catch (submitError) {
      reportDashboardError(submitError instanceof Error ? submitError.message : "Failed to evaluate bids.");
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
      showToast(`Customer quote preview ready at $${response.final_amount.toFixed(2)}.`);
    } catch (submitError) {
      reportDashboardError(submitError instanceof Error ? submitError.message : "Failed to build quote preview.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handleSendCustomerQuote() {
    if (!selectedShipment) return;
    setSubmitting("send_quote");
    try {
      const response = await fetchJson<CustomerQuoteResponse>(`/api/freight/shipments/${selectedShipment.id}/quote`, {
        method: "POST",
        body: JSON.stringify({ bid_id: evaluation?.selected_bid_id || selectedWinningBid?.id || null, dry_run: false }),
      });
      setQuotePreview(response);
      showToast(`Customer quote sent at $${response.final_amount.toFixed(2)}.`);
      await Promise.all([
        refreshSelectedShipment(selectedShipment.id),
        refreshOverview(),
        refreshFinancialSummary(),
      ]);
      await refreshSelectedShipmentContext(selectedShipment.id);
      await loadShipmentThread(selectedShipment.id, true);
    } catch (submitError) {
      reportDashboardError(submitError instanceof Error ? submitError.message : "Failed to send customer quote.");
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
      showToast(`Status reply prepared for ${response.client_email}.`);
    } catch (submitError) {
      reportDashboardError(submitError instanceof Error ? submitError.message : "Failed to preview status reply.");
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
      showToast("TMS handoff preview ready.");
    } catch (submitError) {
      reportDashboardError(submitError instanceof Error ? submitError.message : "Failed to preview TMS handoff.");
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
      showToast(`Shipment booked and confirmation sent to ${response.confirmation.client_email}.`);
      await Promise.all([
        refreshSelectedShipment(selectedShipment.id),
        refreshOverview(),
        refreshFinancialSummary(),
        refreshStatusQueue(),
      ]);
      await refreshSelectedShipmentContext(selectedShipment.id);
    } catch (submitError) {
      reportDashboardError(submitError instanceof Error ? submitError.message : "Failed to book shipment.");
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
      showToast("Bid recorded.");
      await Promise.all([
        refreshSelectedShipment(selectedShipment.id),
        refreshOverview(),
        refreshFinancialSummary(),
      ]);
      await refreshSelectedShipmentContext(selectedShipment.id);
    } catch (submitError) {
      reportDashboardError(submitError instanceof Error ? submitError.message : "Failed to intake bid.");
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

  const secondaryActions =
    actionModel?.contextActions.filter(
      (action) => action.operatorAction !== actionModel.operatorAction && action.key !== "archive_shipment",
    ) || [];
  const contextMenuQuickActions =
    contextMenuActionModel?.contextActions.filter((action) => action.operatorAction !== contextMenuActionModel.operatorAction) || [];
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
                {shipmentBlockingBadge(selectedShipment) && (
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
                  Customer {selectedShipment.client_id ? "linked" : "not linked"} • Sender {selectedShipment.sender_verification_required ? "needs verification" : selectedShipment.sender_known ? "known" : "not linked"} • Created {formatDate(selectedShipment.created_at)} • Confidence {formatConfidence(selectedShipment.ai_confidence)} • Last agent decision {selectedShipment.next_step_label || selectedShipment.ai_next_action || "pending"}
                </p>
                {selectedShipment.source_mailbox && (
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <span className="rounded-full border border-sky-300/18 bg-sky-300/10 px-3 py-1 text-xs text-sky-100">
                      {mailboxSourceLabel(selectedShipment.source_mailbox, userEmail)}
                    </span>
                    {selectedShipment.source_mailbox_visibility_mode && (
                      <span className={`rounded-full border px-3 py-1 text-xs ${emailVisibilityClasses(selectedShipment.source_mailbox_visibility_mode)}`}>
                        {emailVisibilityLabel(selectedShipment.source_mailbox_visibility_mode)}
                      </span>
                    )}
                  </div>
                )}
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                {editableMetricCard("Pallets", String(selectedShipment.pallets ?? "--"), () => enterEditMode("pallets"))}
                {editableMetricCard("Weight", `${selectedShipment.weight_lb ?? "--"} lb`, () => enterEditMode("weight_lb"))}
                {editableMetricCard("Equipment", selectedShipment.equipment_type || "--", () => enterEditMode("equipment_type"))}
                {editableMetricCard(
                  "Ready",
                  formatShipmentSchedule(
                    selectedShipment.ready_at_display,
                    selectedShipment.ready_at_local,
                    selectedShipment.ready_at,
                  ),
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
                  editableMetricCard(
                    "Delivery",
                    formatShipmentSchedule(
                      selectedShipment.delivery_at_display,
                      selectedShipment.delivery_at_local,
                      selectedShipment.delivery_at,
                    ),
                    () => enterEditMode("delivery_at"),
                  )}
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
                      className={`rounded-[14px] px-3 py-2.5 text-xs uppercase tracking-[0.18em] transition ${workspaceSection === section ? "bg-white text-slate-950" : "bg-white/5 text-[var(--text-muted)] hover:bg-white/10 hover:text-white"}`}
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
                      {selectedShipment.customer_clarification_requested && (
                        <p className="mt-3 rounded-2xl border border-emerald-300/15 bg-emerald-300/10 px-3 py-2 text-xs text-emerald-100">
                          Additional details already requested from the customer.
                        </p>
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
                    <div
                      className={`rounded-[24px] border p-5 md:col-span-2 ${
                        senderTrustGateActive(selectedShipment)
                          ? "border-amber-300/35 bg-gradient-to-br from-amber-300/14 via-slate-950/50 to-rose-300/12 shadow-[0_20px_60px_rgba(0,0,0,0.35)]"
                          : selectedShipment.sender_verified_at
                            ? "border-emerald-300/28 bg-gradient-to-br from-emerald-300/10 via-slate-950/45 to-cyan-300/8"
                            : "border-white/10 bg-white/[0.04]"
                      }`}
                    >
                      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
                        <div className="space-y-2">
                          <div className="flex flex-wrap items-center gap-2">
                            {senderTrustGateActive(selectedShipment) ? (
                              <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-300/30 bg-amber-300/15 px-3 py-1 text-xs font-medium text-amber-50">
                                <AlertTriangle size={14} className="shrink-0" />
                                Action required
                              </span>
                            ) : selectedShipment.sender_verified_at ? (
                              <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-300/30 bg-emerald-300/15 px-3 py-1 text-xs font-medium text-emerald-50">
                                <CheckCircle2 size={14} className="shrink-0" />
                                Sender verified
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-white/8 px-3 py-1 text-xs font-medium text-white/90">
                                <ShieldCheck size={14} className="shrink-0 text-emerald-200" />
                                Identity
                              </span>
                            )}
                            <span className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Inbound sender</span>
                          </div>
                          <p className="break-all text-lg font-semibold tracking-tight text-white">{selectedShipment.sender_email || "Unknown sender"}</p>
                          <p className="text-sm text-[var(--text-muted)]">
                            Domain <span className="text-white/90">{selectedShipment.sender_domain || "—"}</span>
                            {" • "}
                            Risk <span className="text-white/90">{selectedShipment.fraud_risk_level || "none"}</span>
                            {selectedShipment.fraud_score !== null && selectedShipment.fraud_score !== undefined ? (
                              <>
                                {" • "}
                                Score{" "}
                                <span className="text-white/90">{`${Math.round(Number(selectedShipment.fraud_score) * 100)}%`}</span>
                              </>
                            ) : null}
                          </p>
                        </div>
                        <div className="min-w-[240px] max-w-md rounded-2xl border border-white/10 bg-slate-950/40 p-4 text-sm text-[var(--text-muted)]">
                          <p className="text-xs uppercase tracking-[0.16em] text-white/50">Verification status</p>
                          <p className="mt-2 text-white">
                            {selectedShipment.sender_verified_at
                              ? `Verified as ${selectedShipment.sender_verified_role || "sender"}`
                              : senderTrustGateActive(selectedShipment)
                                ? "Identity not confirmed"
                                : "No verification blocker"}
                          </p>
                          {selectedShipment.sender_verified_scope ? (
                            <p className="mt-1 break-all text-xs text-[var(--text-muted)]">
                              Scope: {selectedShipment.sender_verified_scope === "sender_domain" ? selectedShipment.sender_verified_for_domain : selectedShipment.sender_verified_for_email}
                            </p>
                          ) : (
                            <p className="mt-1 text-xs text-[var(--text-muted)]">
                              Choose Customer or Carrier below, then verify email/domain.
                            </p>
                          )}
                        </div>
                      </div>
                      {selectedShipment.sender_verified_at ? (
                        <p className="mt-4 border-t border-white/10 pt-4 text-sm text-emerald-100/90">
                          Trust recorded on {formatDate(selectedShipment.sender_verified_at)}
                          {selectedShipment.sender_verified_for_email ? (
                            <span className="block break-all text-xs text-[var(--text-muted)]">Address: {selectedShipment.sender_verified_for_email}</span>
                          ) : null}
                        </p>
                      ) : senderTrustGateActive(selectedShipment) ? (
                        <div className="mt-4 space-y-4 border-t border-white/10 pt-4">
                          <div className="rounded-[22px] border border-cyan-300/18 bg-cyan-300/[0.06] p-4">
                            <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                              <div>
                                <p className="text-xs uppercase tracking-[0.18em] text-cyan-100/70">Verify sender</p>
                                <h4 className="mt-1 text-lg font-semibold text-white">Identify who owns this email</h4>
                                <p className="mt-2 text-sm leading-6 text-cyan-50/80">
                                  Confirm the sender as a customer or carrier, choose whether trust applies to this email only or the whole domain, then continue automation.
                                </p>
                              </div>
                              <span className="w-fit rounded-full border border-amber-300/25 bg-amber-300/10 px-3 py-1 text-xs text-amber-100">
                                Required
                              </span>
                            </div>
                          </div>

                          <div className="grid gap-3 xl:grid-cols-3">
                            <div className="rounded-2xl border border-white/10 bg-slate-950/35 p-4">
                              <div className="flex items-center gap-2">
                                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-white/10 text-xs font-semibold text-white">1</span>
                                <p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Sender type</p>
                              </div>
                              <div className="mt-3 grid gap-2">
                                {(["customer", "carrier"] as SenderIdentityRole[]).map((role) => (
                                  <button
                                    key={role}
                                    type="button"
                                    onClick={() => {
                                      setSenderIdentityRole(role);
                                      setSenderClientId(role === "customer" ? selectedShipment.client_id || "" : "");
                                      setSenderCarrierId("");
                                    }}
                                    className={`rounded-2xl border px-4 py-3 text-left transition ${
                                      senderIdentityRole === role
                                        ? "border-cyan-300/45 bg-cyan-300/14 text-cyan-50"
                                        : "border-white/10 bg-white/5 text-white hover:bg-white/10"
                                    }`}
                                  >
                                    <span className="block text-sm font-semibold">{role === "customer" ? "Customer" : "Carrier"}</span>
                                    <span className="mt-1 block text-xs text-[var(--text-muted)]">
                                      {role === "customer" ? "Shipper, broker, or buyer requesting a quote." : "Carrier replying with bids or shipment updates."}
                                    </span>
                                  </button>
                                ))}
                              </div>
                            </div>

                            <div className="rounded-2xl border border-white/10 bg-slate-950/35 p-4">
                              <div className="flex items-center gap-2">
                                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-white/10 text-xs font-semibold text-white">2</span>
                                <p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Trust scope</p>
                              </div>
                              <div className="mt-3 grid gap-2">
                                {([
                                  ["sender_email", "Only this email", selectedShipment.sender_email || "Unknown sender"],
                                  ["sender_domain", "Entire domain", selectedShipment.sender_domain || "Unknown domain"],
                                ] as const).map(([scope, label, detail]) => (
                                  <button
                                    key={scope}
                                    type="button"
                                    onClick={() => {
                                      setSenderTrustScope(scope);
                                      setSenderClientId(selectedShipment.client_id || "");
                                      setSenderCarrierId("");
                                    }}
                                    className={`rounded-2xl border px-4 py-3 text-left transition ${
                                      senderTrustScope === scope
                                        ? "border-cyan-300/45 bg-cyan-300/14 text-cyan-50"
                                        : "border-white/10 bg-white/5 text-white hover:bg-white/10"
                                    }`}
                                  >
                                    <span className="block text-sm font-semibold">{label}</span>
                                    <span className="mt-1 block break-all text-xs text-[var(--text-muted)]">{detail}</span>
                                  </button>
                                ))}
                              </div>
                            </div>

                            <div className="rounded-2xl border border-white/10 bg-slate-950/35 p-4">
                              <div className="flex items-center gap-2">
                                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-white/10 text-xs font-semibold text-white">3</span>
                                <p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Contact record</p>
                              </div>
                              {(() => {
                                const matches = senderIdentityRole === "customer" ? matchingSenderClients : matchingSenderCarriers;
                                const selectedContact = senderIdentityRole === "customer" ? selectedSenderClient : selectedSenderCarrier;
                                const selectedId = senderIdentityRole === "customer" ? senderClientId : senderCarrierId;
                                return (
                                  <div className="mt-3 space-y-3">
                                    <select
                                      className="field-input"
                                      value={selectedId}
                                      onChange={(event) => {
                                        if (senderIdentityRole === "customer") setSenderClientId(event.target.value);
                                        else setSenderCarrierId(event.target.value);
                                      }}
                                    >
                                      <option value="">Create new from sender email</option>
                                      {matches.map((contact) => (
                                        <option key={contact.id} value={contact.id}>
                                          {contact.name} - {contact.email}
                                        </option>
                                      ))}
                                    </select>
                                    {selectedContact ? (
                                      <div className="rounded-2xl border border-emerald-300/20 bg-emerald-300/10 p-3 text-sm text-emerald-50">
                                        <p className="font-medium">{selectedContact.name}</p>
                                        <p className="mt-1 break-all text-xs text-emerald-100/75">{selectedContact.email}</p>
                                      </div>
                                    ) : (
                                      <label className="block">
                                        <span className="mb-2 block text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">New {senderIdentityRole} name</span>
                                        <input
                                          className="field-input"
                                          value={senderContactName}
                                          onChange={(event) => setSenderContactName(event.target.value)}
                                          placeholder={suggestedContactNameFromEmail(selectedShipment.sender_email)}
                                        />
                                        <span className="mt-2 block break-all text-xs text-[var(--text-muted)]">
                                          Will create {senderIdentityRole} with email {selectedShipment.sender_email || "unknown sender"}.
                                        </span>
                                      </label>
                                    )}
                                  </div>
                                );
                              })()}
                            </div>
                          </div>

                          <div className="rounded-2xl border border-white/10 bg-slate-950/35 p-4">
                            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                              <div>
                                <p className="text-sm font-semibold text-white">
                                  {senderIdentityRole === "customer" ? (senderClientId ? "Link customer" : "Create customer") : senderCarrierId ? "Link carrier" : "Create carrier"} and verify{" "}
                                  {senderTrustScope === "sender_domain" ? "domain" : "email"}
                                </p>
                                <p className="mt-1 text-xs leading-5 text-[var(--text-muted)]">
                                  This records operator trust and resumes the safe automation flow.
                                </p>
                              </div>
                              <button
                                type="button"
                                onClick={() => void handleVerifySenderIdentity()}
                                disabled={submitting !== null || !selectedShipment.sender_email}
                                className="action-button bg-cyan-300 px-5 text-slate-950 hover:brightness-110 disabled:opacity-50"
                              >
                                {submitting === "verify_sender" ? "Verifying..." : "Verify sender"}
                              </button>
                            </div>
                          </div>

                          <div className="rounded-2xl border border-rose-300/20 bg-rose-300/8 p-4">
                            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                              <div>
                                <p className="text-sm font-semibold text-rose-50">Fraud or spam?</p>
                                <p className="mt-1 text-xs leading-5 text-rose-100/75">
                                  Blocking creates a denylist entry and archives this thread.
                                </p>
                              </div>
                              <div className="grid gap-2 sm:grid-cols-2">
                                <button
                                  onClick={() => openFraudArchiveDialog(selectedShipment.id, "sender_email")}
                                  disabled={submitting !== null}
                                  className="action-button border border-rose-300/35 bg-rose-300/15 px-4 py-2.5 text-sm font-semibold text-rose-100 hover:bg-rose-300/20 disabled:opacity-50"
                                >
                                  Block this email
                                </button>
                                <button
                                  onClick={() => openFraudArchiveDialog(selectedShipment.id, "sender_domain")}
                                  disabled={submitting !== null}
                                  className="action-button border border-rose-300/25 bg-white/8 px-4 py-2.5 text-sm font-medium text-rose-50 hover:bg-rose-300/10 disabled:opacity-50"
                                >
                                  Block entire domain
                                </button>
                              </div>
                            </div>
                          </div>
                        </div>
                      ) : (
                        <p className="mt-4 border-t border-white/10 pt-4 text-sm text-[var(--text-muted)]">
                          {selectedShipment.sender_known
                            ? "Sender matches a known customer or carrier identity."
                            : "No elevated risk flags on this shipment right now."}
                        </p>
                      )}
                      <div className="mt-4 flex flex-wrap gap-2">
                        {(selectedShipment.fraud_risk_reasons.length > 0 ? selectedShipment.fraud_risk_reasons : ["no_specific_signals"]).map((reason) => (
                          <span key={reason} className="rounded-full bg-white/8 px-3 py-1 text-xs text-white/85">
                            {reason.replaceAll("_", " ")}
                          </span>
                        ))}
                      </div>
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
                  <div className="grid gap-3 md:grid-cols-4">
                    <button onClick={() => void handleEvaluateBids()} disabled={bids.length === 0 || submitting !== null} className="action-button bg-white/10 text-white hover:bg-white/15 disabled:opacity-50">
                      Evaluate bids
                    </button>
                    <button onClick={() => void handlePreviewCustomerQuote()} disabled={bids.length === 0 || submitting !== null} className="action-button bg-cyan-300/15 text-cyan-100 hover:bg-cyan-300/20 disabled:opacity-50">
                      Preview customer quote
                    </button>
                    <button onClick={() => void handleSendCustomerQuote()} disabled={bids.length === 0 || submitting !== null} className="action-button bg-emerald-300/15 text-emerald-100 hover:bg-emerald-300/20 disabled:opacity-50">
                      Send customer quote
                    </button>
                    <button onClick={() => void handleBookShipment()} disabled={bids.length === 0 || submitting !== null} className="action-button bg-emerald-300/15 text-emerald-100 hover:bg-emerald-300/20 disabled:opacity-50">
                      Book shipment
                    </button>
                  </div>
                  {quotePreview && (
                    <div className="rounded-2xl border border-cyan-300/20 bg-cyan-300/10 p-4">
                      <p className="text-xs uppercase tracking-[0.16em] text-cyan-100">Customer quote preview</p>
                      <p className="mt-2 text-white">{quotePreview.subject}</p>
                      <p className="mt-2 whitespace-pre-wrap text-sm text-cyan-50">{quotePreview.body}</p>
                    </div>
                  )}
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

  const threadTabOptions = [
    { key: "timeline", label: "Timeline" },
    { key: "client", label: "Customer" },
    { key: "carrier_quotes", label: "Carrier Quotes" },
    { key: "system", label: "System" },
  ] as const;

  const renderThreadPanel = ({ embedded = false }: { embedded?: boolean } = {}) => {
    if (!selectedShipment) {
      return null;
    }

    return (
      <div
        className={
          embedded
            ? "flex h-full min-h-0 w-full flex-col overflow-hidden rounded-[28px] border border-white/10 bg-white/[0.03] px-5 pb-5 pt-3.5"
            : "relative flex h-full min-h-0 w-full flex-col overflow-hidden rounded-[28px] border border-cyan-300/14 bg-[linear-gradient(135deg,rgba(7,15,25,0.94),rgba(11,23,37,0.9)_46%,rgba(17,34,52,0.92)),radial-gradient(circle_at_0%_0%,rgba(108,213,255,0.13),transparent_28%),radial-gradient(circle_at_100%_0%,rgba(61,139,255,0.11),transparent_24%)] shadow-[-20px_22px_80px_rgba(0,0,0,0.32)] backdrop-blur-xl"
        }
      >
        {!embedded ? (
          <>
            <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(90deg,transparent,rgba(120,210,255,0.05)_18%,transparent_38%,transparent_62%,rgba(120,210,255,0.04)_82%,transparent)]" />
            <div className="pointer-events-none absolute inset-y-0 left-[22%] w-px bg-cyan-200/8" />
            <div className="pointer-events-none absolute inset-y-0 right-[24%] w-px bg-cyan-200/8" />
          </>
        ) : null}

        <div
          className={
            embedded
              ? "relative shrink-0 border-b border-white/10 pb-4"
              : "relative border-b border-cyan-200/10 px-4 py-4 sm:px-5"
          }
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              {embedded ? (
                <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Thread context</p>
              ) : (
                <div className="inline-flex h-8 items-center gap-2 rounded-[10px] border border-cyan-200/16 bg-cyan-200/6 px-3 text-[10px] uppercase tracking-[0.24em] text-cyan-100">
                  Thread context
                </div>
              )}
              <h3
                className={
                  embedded
                    ? "mt-1 break-words text-2xl font-semibold tracking-[-0.04em] text-white"
                    : "mt-1 break-words text-lg font-semibold text-white"
                }
              >
                {threadData?.thread_subject || formatRoute(selectedShipment)}
              </h3>
              <p className="mt-2 break-all text-sm text-[var(--text-muted)]">
                {threadData?.quote_token || selectedShipment.quote_token || "No quote token"}
              </p>
            </div>
            <button
              type="button"
              onClick={() => void loadShipmentThread(selectedShipment.id, true)}
              disabled={threadLoading}
              aria-busy={threadLoading}
              className={`inline-flex shrink-0 items-center gap-2 rounded-full border text-xs font-semibold tracking-wide transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 disabled:pointer-events-none disabled:opacity-40 ${
                embedded
                  ? "group border-white/14 bg-white/[0.07] px-3.5 py-2 text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.1)] hover:border-white/22 hover:bg-white/[0.11] focus-visible:outline-white/40"
                  : "group border-cyan-200/22 bg-cyan-200/12 px-3 py-2 text-cyan-50 shadow-[inset_0_1px_0_rgba(165,243,252,0.12)] hover:border-cyan-200/35 hover:bg-cyan-200/18 focus-visible:outline-cyan-200/50"
              }`}
            >
              <RefreshCcw
                className={`h-3.5 w-3.5 shrink-0 transition duration-500 ease-out ${threadLoading ? "animate-spin" : "group-hover:-rotate-45"}`}
                strokeWidth={2.25}
                aria-hidden
              />
              {threadLoading ? (embedded ? "Updating…" : "Loading…") : "Refresh"}
            </button>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            {threadTabOptions.map((tab) => (
              <button
                key={tab.key}
                type="button"
                onClick={() => setActiveThreadTab(tab.key)}
                className={`rounded-[10px] px-3 py-2 text-[10px] uppercase tracking-[0.18em] transition ${
                  activeThreadTab === tab.key
                    ? embedded
                      ? "bg-white text-slate-950"
                      : "bg-cyan-100 text-slate-950"
                    : embedded
                      ? "border border-white/10 bg-white/5 text-slate-300 hover:bg-white/10 hover:text-white"
                      : "border border-cyan-200/10 bg-slate-950/22 text-slate-300 hover:bg-cyan-200/8 hover:text-white"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        <div
          className={
            embedded
              ? "relative min-h-0 flex-1 overflow-x-hidden overflow-y-auto pt-4"
              : "relative min-h-0 flex-1 overflow-x-hidden overflow-y-auto px-4 py-4 sm:px-5"
          }
        >
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
                        {message.dry_run && (
                          <p className="mt-1 text-xs uppercase tracking-[0.14em] text-amber-100">
                            Preview only. This email was not sent.
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
    );
  };

  const renderThreadRail = () => {
    if (!drawerOpen || !selectedShipment) {
      return null;
    }

    return (
      <aside className="pointer-events-auto fixed top-6 right-[calc(50vw+160px)] bottom-6 z-[45] hidden w-[475px] overflow-hidden rounded-[30px] border border-cyan-300/14 bg-[linear-gradient(135deg,rgba(7,15,25,0.94),rgba(11,23,37,0.9)_46%,rgba(17,34,52,0.92)),radial-gradient(circle_at_0%_0%,rgba(108,213,255,0.13),transparent_28%),radial-gradient(circle_at_100%_0%,rgba(61,139,255,0.11),transparent_24%)] shadow-[-20px_22px_80px_rgba(0,0,0,0.32)] backdrop-blur-xl xl:flex">
        {renderThreadPanel()}
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
      <OrganizationDrawer open={organizationDrawerOpen} onClose={() => setOrganizationDrawerOpen(false)} />
      <div className="mx-auto max-w-[1540px] space-y-4">
        <section className="relative overflow-hidden rounded-[18px] border border-cyan-300/12 bg-[linear-gradient(135deg,rgba(7,15,25,0.96),rgba(11,23,37,0.92)_46%,rgba(17,34,52,0.94)),radial-gradient(circle_at_0%_0%,rgba(108,213,255,0.14),transparent_26%),radial-gradient(circle_at_100%_0%,rgba(61,139,255,0.12),transparent_24%)] px-4 py-4 shadow-[0_18px_60px_rgba(0,0,0,0.26)] sm:px-5">
          <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(90deg,transparent,rgba(120,210,255,0.05)_18%,transparent_38%,transparent_62%,rgba(120,210,255,0.04)_82%,transparent)]" />
          <div className="pointer-events-none absolute inset-y-0 left-[22%] w-px bg-cyan-200/8" />
          <div className="pointer-events-none absolute inset-y-0 right-[26%] w-px bg-cyan-200/8" />

          <div className="relative grid gap-3 sm:gap-4 lg:grid-cols-[minmax(0,1fr),minmax(260px,480px)] lg:items-start xl:grid-cols-[minmax(0,1fr),minmax(280px,520px)]">
            <div className="min-w-0 max-w-xl space-y-2.5 self-start lg:max-w-lg xl:max-w-xl">
              <div className="flex w-full flex-wrap items-center gap-2.5">
                <div className="inline-flex items-center gap-2.5">
                  <DashboardLogo className="h-6 w-6 shrink-0 sm:h-7 sm:w-7" />
                  <span className="text-[11px] font-semibold uppercase tracking-[0.24em] text-cyan-100">
                    Logistic Copilot
                  </span>
                </div>
                <span className="hidden text-[11px] uppercase tracking-[0.24em] text-cyan-200/40 md:inline">
                  Live operations board
                </span>
              </div>
              <div className="space-y-1.5">
                <h1 className="text-lg font-semibold tracking-[-0.04em] text-white sm:text-xl">
                  Monitor active lanes. Surface blockers. Move faster.
                </h1>
                <p className="text-xs leading-snug text-slate-300 sm:text-sm sm:leading-relaxed">
                  A sharper command deck for today&apos;s shipments, operator decisions, and time-sensitive follow-up.
                </p>
              </div>
            </div>

            <div className="grid w-full max-w-[440px] shrink-0 grid-cols-3 grid-rows-2 gap-1 min-[1280px]:max-w-none min-[1280px]:grid-cols-6 min-[1280px]:grid-rows-1 min-[1280px]:gap-1.5 justify-self-start lg:justify-self-end">
                {metrics.map((metric) => (
                  <div key={metric.label} className="min-h-[58px] rounded-[11px] border border-cyan-200/10 bg-slate-950/26 px-2 py-1.5 backdrop-blur sm:min-h-[60px] sm:rounded-[12px] sm:px-2.5 sm:py-2">
                    <p className="text-[9px] uppercase tracking-[0.2em] text-cyan-200/48 sm:text-[10px] sm:tracking-[0.22em]">{metric.label}</p>
                    <div className="mt-0.5 space-y-0.5 sm:mt-1">
                      <span className="block text-xl font-semibold leading-none text-white sm:text-[1.35rem]">{metric.value}</span>
                      <span className="block text-[9px] leading-tight text-slate-300 sm:text-[10px] sm:leading-4">{metric.detail}</span>
                    </div>
                  </div>
                ))}
                <button
                  onClick={() => {
                    setNotificationCenterOpen((open) => !open);
                  }}
                  className="relative min-h-[58px] overflow-hidden rounded-[11px] border border-cyan-200/16 bg-[linear-gradient(135deg,rgba(255,255,255,0.06),rgba(255,255,255,0.02))] px-2 py-1.5 text-left shadow-[inset_0_1px_0_rgba(255,255,255,0.06)] transition hover:border-cyan-200/24 hover:bg-cyan-200/10 sm:min-h-[60px] sm:rounded-[12px] sm:px-2.5 sm:py-2"
                >
                  <span className="pointer-events-none absolute right-0.5 top-1/2 -translate-y-1/2 text-[48px] font-black leading-none tracking-[-0.05em] text-cyan-100/[0.08] sm:right-1 sm:text-[56px] min-[1280px]:text-[64px]">
                    {unreadNotificationCount}
                  </span>
                  <div className="relative z-[1] flex items-center justify-between gap-1.5 sm:gap-2">
                    <div className="min-w-0 pr-2 sm:pr-4">
                      <p className="text-[9px] uppercase tracking-[0.2em] text-cyan-100/70 sm:text-[10px] sm:tracking-[0.22em]">Signals</p>
                      <span className="mt-0.5 inline-flex items-center gap-1 text-[13px] font-semibold text-white sm:gap-1.5 sm:text-[15px]">
                        <Bell size={14} className="shrink-0" /> Alerts
                      </span>
                      <p className="mt-0.5 truncate text-[9px] text-cyan-100/70 sm:text-[10px]">
                        {notifications[0]?.title || "Email, shipment, bid, review"}
                      </p>
                    </div>
                  </div>
                </button>
                <div className="relative">
                  <button
                    onClick={() => {
                      setNotificationCenterOpen(false);
                      setOrganizationDrawerOpen(true);
                    }}
                    disabled={submitting !== null && submitting !== "sync" && submitting !== "webhook"}
                    className="min-h-[58px] w-full rounded-[11px] border border-cyan-200/16 bg-[linear-gradient(135deg,rgba(132,236,255,0.2),rgba(85,202,255,0.14))] px-2 py-1.5 text-left shadow-[0_12px_30px_rgba(44,164,214,0.14),inset_0_1px_0_rgba(255,255,255,0.08)] transition hover:brightness-110 disabled:opacity-50 sm:min-h-[60px] sm:rounded-[12px] sm:px-2.5 sm:py-2"
                  >
                    <div className="flex h-full min-w-0 flex-col justify-between gap-0.5 sm:gap-1">
                      <div className="flex min-w-0 items-center justify-between gap-1.5 sm:gap-2">
                        <p className="min-w-0 truncate text-[9px] uppercase tracking-[0.2em] text-cyan-100/70 sm:text-[10px] sm:tracking-[0.22em]">Organization</p>
                        <span className={`h-1.5 w-1.5 shrink-0 rounded-full sm:h-2 sm:w-2 ${outlookStatusLoading ? "animate-pulse bg-cyan-200" : webhookStatus?.status === "active" ? "bg-emerald-200" : webhookStatus?.status === "expiring_soon" ? "bg-amber-200" : "bg-rose-200"}`} />
                      </div>
                      <span className="flex min-w-0 items-center gap-1 text-[13px] font-semibold leading-tight text-white sm:gap-1.5 sm:text-[14px] sm:leading-5">
                          {submitting === "sync" ? <Loader2 className="shrink-0 animate-spin" size={14} /> : <SlidersHorizontal size={14} className="shrink-0" />}
                          <span className="min-w-0 truncate">Mailbox</span>
                      </span>
                      <p className="min-w-0 truncate text-[9px] leading-tight text-cyan-100/70 sm:text-[10px] sm:leading-4">
                        Your inbox · {outlookStatusLoading ? "Checking" : webhookStatusLabel(webhookStatus?.status)}
                      </p>
                    </div>
                  </button>
                </div>
            </div>
          </div>

        </section>

        <section className="glass-panel p-4">
          <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-5">
            {[
              ...(canUseEmailTriage ? [{ key: "triage", label: "Email triage", icon: Mail }] : []),
              { key: "shipments", label: "Shipments", icon: Package2 },
              // Status Ops is hidden until the workflow purpose is clearer.
              // { key: "status_ops", label: "Status ops", icon: RadioTower },
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
                  <span className="flex items-center gap-3 text-xs font-medium uppercase tracking-[0.18em]"><Icon size={18} />{label}</span>
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
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4 lg:items-center">
                  <div className="flex min-w-0 items-start gap-3">
                    <span className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-[12px] border border-cyan-200/12 bg-cyan-200/8 text-cyan-100">
                      <SlidersHorizontal size={18} />
                    </span>
                    <div className="min-w-0">
                      <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Board controls</p>
                      <p className="mt-1 text-sm text-slate-300">
                        Search shipments, switch created month, and control the live board from one surface.
                      </p>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2 sm:ml-auto sm:justify-end lg:ml-4">
                    {(["today", "attention", "all"] as const).map((filter) => (
                      <button
                        key={filter}
                        type="button"
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

                <div
                  className={`grid grid-cols-1 gap-4 sm:items-start sm:gap-x-4 sm:gap-y-4 xl:items-start xl:gap-x-5 xl:gap-y-0 ${
                    isViewerRole
                      ? "sm:grid-cols-1 xl:grid-cols-[minmax(280px,420px)_minmax(280px,1fr)]"
                      : "sm:grid-cols-2 xl:grid-cols-[minmax(280px,420px)_minmax(240px,340px)_minmax(280px,1fr)]"
                  }`}
                >
                  <div className="min-w-0">
                    <span className="mb-2 block text-[11px] uppercase tracking-[0.16em] text-[var(--text-muted)]">Month</span>
                    <div className="relative flex min-w-0 items-center gap-1.5 sm:gap-2">
                      <button
                        type="button"
                        onClick={() => shiftBoardMonth(-1)}
                        className="inline-flex h-[52px] w-10 shrink-0 items-center justify-center rounded-[16px] border border-cyan-200/10 bg-slate-950/24 text-slate-300 transition hover:border-cyan-200/20 hover:bg-cyan-200/8 hover:text-white sm:w-[46px]"
                        aria-label="Previous month"
                      >
                        <ChevronLeft size={18} />
                      </button>
                      <button
                        type="button"
                        onClick={() => setMonthPickerOpen((open) => !open)}
                        aria-expanded={monthPickerOpen}
                        aria-haspopup="dialog"
                        title={monthPickerOpen ? "Close month picker" : "Choose created month"}
                        className="flex h-[52px] min-w-0 flex-1 items-center justify-between gap-1.5 rounded-[16px] border border-cyan-200/12 bg-[linear-gradient(135deg,rgba(110,184,255,0.08),rgba(110,184,255,0.02))] px-2.5 text-left shadow-[inset_0_1px_0_rgba(255,255,255,0.03)] transition hover:border-cyan-200/20 hover:bg-cyan-200/8 sm:gap-2 sm:px-3"
                      >
                        <span className="flex min-w-0 flex-1 items-center gap-2 sm:gap-2.5">
                          <Calendar size={17} className="shrink-0 text-cyan-200/70" aria-hidden />
                          <span className="min-w-0 flex-1">
                            <span className="block text-[10px] uppercase tracking-[0.18em] text-cyan-200/55">Created month</span>
                            <span className="block truncate text-sm font-medium text-white">{formatMonthLabel(selectedBoardMonth)}</span>
                          </span>
                        </span>
                        <span className="shrink-0 whitespace-nowrap pl-1 text-[10px] uppercase tracking-[0.16em] text-slate-400 sm:hidden xl:inline xl:pl-2 xl:text-[11px]">
                          {monthPickerOpen ? "Close" : "Choose"}
                        </span>
                      </button>
                      <button
                        type="button"
                        onClick={() => shiftBoardMonth(1)}
                        className="inline-flex h-[52px] w-10 shrink-0 items-center justify-center rounded-[16px] border border-cyan-200/10 bg-slate-950/24 text-slate-300 transition hover:border-cyan-200/20 hover:bg-cyan-200/8 hover:text-white sm:w-[46px]"
                        aria-label="Next month"
                      >
                        <ChevronRight size={18} />
                      </button>
                    </div>
                  </div>

                  {!isViewerRole ? (
                    <div className="min-w-0">
                      <span className="mb-2 block text-[11px] uppercase tracking-[0.16em] text-[var(--text-muted)]">Mailbox</span>
                      <button
                        type="button"
                        aria-pressed={boardMailboxScope === "mine"}
                        disabled={!userEmail}
                        title={
                          userEmail
                            ? `${boardMailboxScope === "mine" ? "Showing" : "Include all"} · ${userEmail}`
                            : "Loading account…"
                        }
                        onClick={() => setBoardMailboxScope((prev) => (prev === "mine" ? "org" : "mine"))}
                        className={`flex h-[52px] w-full min-w-0 items-center gap-3 rounded-[16px] border px-3 text-left transition disabled:cursor-not-allowed disabled:opacity-45 ${
                          boardMailboxScope === "mine"
                            ? "border-cyan-200/18 bg-cyan-200/8 text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]"
                            : "border-cyan-200/10 bg-slate-950/24 text-slate-300 shadow-[inset_0_1px_0_rgba(255,255,255,0.02)] hover:border-cyan-200/20 hover:bg-cyan-200/8 hover:text-white"
                        }`}
                      >
                        <Inbox size={17} className="shrink-0 text-cyan-200/70" aria-hidden />
                        <span className="min-w-0 flex-1 leading-tight">
                          <span className="flex items-center gap-2">
                            <span className="truncate text-sm font-semibold text-white">My mailbox only</span>
                            <span className="shrink-0 rounded-[10px] border border-cyan-200/10 bg-slate-950/22 px-2 py-0.5 text-[11px] tabular-nums text-slate-300">
                              {mailboxMineEligibleCount}
                            </span>
                          </span>
                          <span className="mt-0.5 block truncate text-[10px] text-[var(--text-muted)]">
                            {userEmail ? <span className="font-medium text-slate-400">{userEmail}</span> : "Loading mailbox…"}
                          </span>
                        </span>
                        <span
                          className={`relative ml-1 inline-flex h-8 w-[3.25rem] shrink-0 items-center rounded-full border p-[3px] transition ${
                            boardMailboxScope === "mine"
                              ? "justify-end border-emerald-400/35 bg-emerald-500/[0.22]"
                              : "justify-start border border-white/14 bg-white/[0.08]"
                          }`}
                          aria-hidden
                        >
                          <span className="pointer-events-none size-[1.375rem] rounded-full bg-white shadow-[0_1px_2px_rgba(0,0,0,0.28)] ring-1 ring-black/10" />
                        </span>
                      </button>
                    </div>
                  ) : null}

                  <div className="min-w-0 sm:col-span-2 xl:col-span-1">
                    <span className="mb-2 block text-[11px] uppercase tracking-[0.16em] text-[var(--text-muted)]">Search</span>
                    <div
                      className={`flex h-[52px] items-center gap-2.5 rounded-[16px] border bg-slate-950/24 px-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.02)] transition-[border-color] sm:gap-3 ${
                        shipmentSearch.trim()
                          ? "border-white/22"
                          : "border-cyan-200/10 focus-within:border-white/22"
                      }`}
                    >
                      <Search size={17} className="shrink-0 text-cyan-200/65" aria-hidden />
                      <input
                        id="board-shipment-search-input"
                        type="text"
                        inputMode="search"
                        autoComplete="off"
                        aria-label="Search shipments"
                        className="min-w-0 flex-1 bg-transparent text-sm font-medium text-white outline-none placeholder:font-normal placeholder:text-slate-500"
                        value={shipmentSearch}
                        onChange={(event) => setShipmentSearch(event.target.value)}
                        placeholder="Route, city, token, notes…"
                      />
                      {shipmentSearch.trim() ? (
                        <button
                          type="button"
                          aria-label="Clear search"
                          onClick={() => setShipmentSearch("")}
                          className="inline-flex shrink-0 rounded-[10px] p-1.5 text-slate-400 transition hover:bg-white/10 hover:text-white"
                        >
                          <X size={17} strokeWidth={2} />
                        </button>
                      ) : null}
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <div className="overflow-x-auto rounded-[32px] border border-white/10 bg-[radial-gradient(circle_at_top_left,rgba(75,211,255,0.08),transparent_32%),linear-gradient(180deg,rgba(255,255,255,0.02),rgba(255,255,255,0.01))] p-4">
              <div className="flex min-w-[1414px] gap-4">
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
                          const fraudIndicators = shipmentFraudIndicators(shipment);
                          const blockingBadge = shipmentBlockingBadge(shipment);
                          const mailboxMeta = mailboxSourceMeta(shipment.source_mailbox, userEmail);
                          return (
                            <div
                              key={shipment.id}
                              onContextMenu={(event: ReactMouseEvent<HTMLDivElement>) => {
                                event.preventDefault();
                                event.stopPropagation();
                                if (!selectShipment(shipment.id)) return;
                                setContextMenu({ shipmentId: shipment.id, x: event.clientX, y: event.clientY });
                              }}
                              className={`group relative overflow-hidden rounded-[18px] border px-3 pt-2 pb-1.5 transition ${
                                isSelected
                                  ? "border-cyan-300/40 bg-cyan-300/10 shadow-[0_0_0_1px_rgba(134,239,255,0.08)]"
                                  : "border-white/10 bg-white/[0.05] hover:-translate-y-0.5 hover:border-white/20 hover:bg-white/[0.08]"
                              }`}
                            >
                              <div className="flex items-start">
                                <button
                                  onClick={() => {
                                    selectShipment(shipment.id, { openDrawer: true });
                                  }}
                                  className="w-full text-left"
                                >
                                  {mailboxMeta ? (
                                    <div className="-mx-3 -mt-2 mb-2 border-b border-white/[0.08] bg-black/25 px-3 py-2">
                                      <p className="text-[9px] font-semibold uppercase tracking-[0.14em] text-sky-200/55">{mailboxMeta.caption}</p>
                                      <p className="mt-1 truncate text-[12px] font-medium leading-snug text-white" title={mailboxMeta.address}>
                                        {mailboxMeta.address}
                                      </p>
                                    </div>
                                  ) : null}
                                  <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                                    {fraudIndicators.length > 0 && (
                                      <div className="flex items-center gap-1">
                                        {fraudIndicators.map((indicator) => {
                                          const Icon = indicator.icon;
                                          return (
                                            <span
                                              key={indicator.key}
                                              title={indicator.title}
                                              className={`inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full border ${indicator.className}`}
                                            >
                                              <Icon size={11} />
                                            </span>
                                          );
                                        })}
                                      </div>
                                    )}
                                    <ShipmentStatusPill status={shipment.status} />
                                    {blockingBadge && (
                                      <span className="inline-flex h-5 shrink-0 items-center whitespace-nowrap rounded-full bg-amber-300/10 px-2 text-[9px] font-medium uppercase tracking-[0.1em] text-amber-100">
                                        {blockingBadge}
                                      </span>
                                    )}
                                    <span
                                      title="AI confidence"
                                      className="inline-flex h-5 shrink-0 items-center whitespace-nowrap rounded-full border border-cyan-200/14 bg-cyan-300/10 px-2 text-[9px] font-medium uppercase tracking-[0.1em] text-cyan-100"
                                    >
                                      {formatConfidence(shipment.ai_confidence)}
                                    </span>
                                  </div>
                                  <p className="mt-1.5 line-clamp-2 text-[13px] font-medium leading-4.5 text-white">{formatRoute(shipment)}</p>
                                  <div className="mt-1.5 grid grid-cols-[minmax(0,1.25fr)_minmax(0,0.95fr)] gap-x-2 gap-y-1 text-[10px] leading-4 text-[var(--text-muted)]">
                                    <p className="min-w-0 whitespace-normal">
                                      {formatShipmentSchedule(
                                        shipment.ready_at_display,
                                        shipment.ready_at_local || null,
                                        shipment.ready_at,
                                      ) || "TBD"}
                                    </p>
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
                <div className="flex min-h-[72vh] w-[310px] flex-col rounded-[28px] border border-white/10 bg-slate-950/25">
                  <div className="sticky top-0 z-10 rounded-t-[28px] border-b border-white/10 bg-gradient-to-b from-cyan-300/12 to-slate-900/0 px-4 py-4 backdrop-blur">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-medium text-white">Financial Snapshot</p>
                      <span
                        title="Visible board value"
                        className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-cyan-300/10 text-cyan-100"
                      >
                        {financialSummaryLoading ? <Loader2 className="animate-spin" size={14} /> : <CircleDollarSign size={15} />}
                      </span>
                    </div>
                  </div>
                  <div className="flex-1 space-y-2 p-3">
                    <div className="rounded-[18px] border border-white/10 bg-white/[0.05] px-3 pt-3 pb-2.5">
                      <p className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-muted)]">Pipeline value</p>
                      <p className="mt-2 text-2xl font-semibold leading-none text-white">{formatCurrency(financialSnapshot.pipelineValue, { compact: true })}</p>
                      <div className="mt-3 grid grid-cols-2 gap-2 text-[10px]">
                        <div className="min-w-0 rounded-[12px] border border-white/10 bg-slate-950/24 p-2">
                          <p className="text-[var(--text-muted)]">Quoted</p>
                          <p className="mt-1 font-medium text-white">{formatCurrency(financialSnapshot.quotedValue, { compact: true })}</p>
                        </div>
                        <div className="min-w-0 rounded-[12px] border border-white/10 bg-slate-950/24 p-2">
                          <p className="text-[var(--text-muted)]">Booked</p>
                          <p className="mt-1 font-medium text-white">{formatCurrency(financialSnapshot.bookedValue, { compact: true })}</p>
                        </div>
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-2">
                      <div className="rounded-[18px] border border-white/10 bg-white/[0.05] p-3">
                        <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-muted)]">Avg margin</p>
                        <p className="mt-2 text-lg font-semibold text-white">{financialSnapshot.avgMarginPercent ? `${financialSnapshot.avgMarginPercent}%` : "--"}</p>
                      </div>
                      <div className="rounded-[18px] border border-white/10 bg-white/[0.05] p-3">
                        <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-muted)]">Bid exposure</p>
                        <p className="mt-2 text-lg font-semibold text-white">{formatCurrency(financialSnapshot.waitingBidExposure, { compact: true })}</p>
                      </div>
                      <div className="rounded-[18px] border border-amber-200/18 bg-amber-300/10 p-3">
                        <p className="text-[10px] uppercase tracking-[0.16em] text-amber-100/78">At risk</p>
                        <p className="mt-2 text-lg font-semibold text-white">{formatCurrency(financialSnapshot.atRiskValue, { compact: true })}</p>
                      </div>
                      <div className="rounded-[18px] border border-white/10 bg-white/[0.05] p-3">
                        <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-muted)]">No bid yet</p>
                        <p className="mt-2 text-lg font-semibold text-white">{financialSnapshot.noBidCount}</p>
                      </div>
                    </div>

                    {financialSnapshot.topOpportunity ? (
                      <button
                        type="button"
                        onClick={() => selectShipment(financialSnapshot.topOpportunity?.shipment.id || "", { openDrawer: true })}
                        className="group relative w-full overflow-hidden rounded-[18px] border border-white/10 bg-white/[0.05] px-3 pt-2.5 pb-3 text-left transition hover:-translate-y-0.5 hover:border-cyan-200/24 hover:bg-white/[0.08]"
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <p className="text-[10px] uppercase tracking-[0.18em] text-cyan-100/70">Top revenue move</p>
                            <p className="mt-2 line-clamp-2 text-sm font-medium text-white">{formatRoute(financialSnapshot.topOpportunity.shipment)}</p>
                          </div>
                          <ArrowRight className="mt-1 shrink-0 text-[var(--text-muted)] transition group-hover:text-cyan-100" size={16} />
                        </div>
                        <div className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
                          <div>
                            <p className="text-[var(--text-muted)]">Quote</p>
                            <p className="mt-1 font-medium text-white">{formatCurrency(financialSnapshot.topOpportunity.projectedQuote)}</p>
                          </div>
                          <div>
                            <p className="text-[var(--text-muted)]">Margin</p>
                            <p className="mt-1 font-medium text-cyan-100">{formatCurrency(financialSnapshot.topOpportunity.projectedMargin)}</p>
                          </div>
                        </div>
                      </button>
                    ) : (
                      <div className="rounded-[22px] border border-dashed border-white/10 bg-white/5 p-4 text-sm text-[var(--text-muted)]">
                        Priced bids will turn into margin opportunities here.
                      </div>
                    )}

                    <div className="rounded-[18px] border border-white/10 bg-white/[0.05] p-3">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-muted)]">Pipeline</p>
                        <span className="rounded-full bg-white/10 px-2 py-1 text-[10px] text-white">{financialSnapshot.readyToQuoteCount} priced</span>
                      </div>
                      <div className="mt-3 space-y-2">
                        {financialSnapshot.rows
                          .filter((row) => row.financial?.recommended_quote_amount || shipmentNeedsAttention(row.shipment))
                          .slice(0, 4)
                          .map((row) => (
                            <button
                              key={row.shipment.id}
                              type="button"
                              onClick={() => selectShipment(row.shipment.id, { openDrawer: true })}
                              className="flex w-full items-center justify-between gap-3 rounded-[14px] border border-white/10 bg-slate-950/20 px-3 py-2 text-left transition hover:border-white/20 hover:bg-white/[0.08]"
                            >
                              <div className="min-w-0">
                                <p className="truncate text-xs font-medium text-white">{formatRoute(row.shipment)}</p>
                                <p className="mt-0.5 text-[10px] uppercase tracking-[0.14em] text-[var(--text-muted)]">
                                  {shipmentNeedsAttention(row.shipment) ? "risk review" : "priced lane"}
                                </p>
                              </div>
                              <span className="shrink-0 text-xs font-medium text-cyan-100">
                                {formatCurrency(row.financial?.recommended_quote_amount, { compact: true })}
                              </span>
                            </button>
                          ))}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </section>
        )}

        {!initialLoading && canUseEmailTriage && tab === "triage" && (
          <section className="grid min-w-0 items-start gap-4 xl:grid-cols-[minmax(0,420px),minmax(0,1fr)]">
            <div className="glass-panel flex min-h-0 min-w-0 flex-col overflow-hidden p-4">
              <div className="mb-4 min-w-0">
                <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Email triage</p>
                <p className="mt-1 text-lg font-medium text-white">Emails that did not become shipments</p>
                <p className="mt-1 text-sm text-slate-300">Fraud, noise, and uncertain freight stay here until an operator resolves them.</p>
              </div>
              <div className="mb-3 shrink-0">
                <span className="mb-1.5 block text-[10px] uppercase tracking-[0.16em] text-[var(--text-muted)]">Search</span>
                <div
                  className={`flex h-11 items-center gap-2 rounded-[14px] border bg-slate-950/24 px-2.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.02)] transition-[border-color] ${
                    triageSearchInput.trim() ? "border-white/22" : "border-cyan-200/10 focus-within:border-white/22"
                  }`}
                >
                  <Search size={15} className="shrink-0 text-cyan-200/65" aria-hidden />
                  <input
                    type="text"
                    inputMode="search"
                    autoComplete="off"
                    aria-label="Search triage emails"
                    className="min-w-0 flex-1 bg-transparent text-sm font-medium text-white outline-none placeholder:font-normal placeholder:text-slate-500"
                    value={triageSearchInput}
                    onChange={(event) => setTriageSearchInput(event.target.value)}
                    placeholder="Subject, sender, mailbox, classification…"
                  />
                  {triageSearchInput.trim() ? (
                    <button
                      type="button"
                      aria-label="Clear search"
                      onClick={() => setTriageSearchInput("")}
                      className="inline-flex shrink-0 rounded-[10px] p-1.5 text-slate-400 transition hover:bg-white/10 hover:text-white"
                    >
                      <X size={16} strokeWidth={2} />
                    </button>
                  ) : null}
                </div>
              </div>
              <label className="mb-3 flex cursor-pointer items-center gap-2.5 rounded-[12px] border border-white/10 bg-slate-950/25 px-3 py-2.5 text-left text-sm text-slate-200 transition hover:border-white/16 hover:bg-slate-950/35">
                <input
                  type="checkbox"
                  className="h-4 w-4 shrink-0 rounded border-white/20 bg-slate-950/60 text-cyan-400 focus:ring-cyan-400/40"
                  checked={triageIncludeHighConfidence}
                  onChange={(event) => setTriageIncludeHighConfidence(event.target.checked)}
                />
                <span className="min-w-0 leading-snug">
                  <span className="font-medium text-white">Show high-confidence</span>
                  <span className="mt-0.5 block text-[11px] text-slate-400">Include items with AI confidence ≥ 85% (hidden by default).</span>
                </span>
              </label>
              <div
                className="min-h-0 flex-1 space-y-2 overflow-y-auto overscroll-contain pr-0.5 [-webkit-overflow-scrolling:touch] max-h-[min(58dvh,26rem)] xl:max-h-[min(72vh,34rem)]"
                onScroll={(event) => {
                  const el = event.currentTarget;
                  if (el.scrollHeight - el.scrollTop - el.clientHeight > 140) return;
                  void loadMoreEmailTriageQueue();
                }}
              >
                {emailTriageListLoading && emailTriageQueue.length === 0 ? (
                  <div className="flex items-center justify-center gap-2 rounded-[22px] border border-dashed border-white/10 bg-white/5 py-10 text-sm text-[var(--text-muted)]">
                    <Loader2 className="animate-spin text-cyan-200/80" size={18} aria-hidden />
                    Loading triage…
                  </div>
                ) : null}
                {!emailTriageListLoading && emailTriageQueue.length === 0 && !triageSearchDebounced ? (
                  <div className="rounded-[22px] border border-dashed border-white/10 bg-white/5 p-4 text-sm text-[var(--text-muted)]">
                    <p>No active triage emails in this view right now.</p>
                    {!triageIncludeHighConfidence ? (
                      <p className="mt-2 text-xs leading-relaxed text-slate-400">
                        Rows with AI confidence ≥ 85% are excluded by default. Turn on &ldquo;Show high-confidence&rdquo; above to list them.
                      </p>
                    ) : null}
                  </div>
                ) : null}
                {!emailTriageListLoading && emailTriageQueue.length === 0 && triageSearchDebounced ? (
                  <div className="rounded-[22px] border border-dashed border-white/10 bg-white/5 p-4 text-sm text-[var(--text-muted)]">
                    No emails match this search. Try another keyword or clear the field.
                  </div>
                ) : null}
                {emailTriageQueue.map((item) => {
                  const triageMailboxMeta = mailboxSourceMeta(item.mailbox, userEmail);
                  const isTriageSelected = item.id === selectedTriageItem?.id;
                  const classificationTitle = triageClassificationLabel(item.classification);
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => {
                        triageScrollPendingRef.current = true;
                        setSelectedTriageItemId(item.id);
                      }}
                      className={`group relative w-full overflow-hidden rounded-[18px] border px-3 py-2.5 text-left transition ${
                        isTriageSelected
                          ? "border-cyan-300/40 bg-cyan-300/10 shadow-[0_0_0_1px_rgba(134,239,255,0.08)]"
                          : "border-white/10 bg-white/[0.05] hover:border-white/18 hover:bg-white/[0.07]"
                      }`}
                    >
                      <p
                        className="truncate text-[11px] leading-snug text-slate-500"
                        title={
                          triageMailboxMeta ? `${triageMailboxMeta.caption} · ${triageMailboxMeta.address}` : "Mailbox not recorded"
                        }
                      >
                        {triageMailboxMeta ? (
                          <>
                            <span className="text-slate-500">{triageMailboxMeta.caption}</span>
                            <span className="text-slate-600"> · </span>
                            <span className="text-slate-400">{triageMailboxMeta.address}</span>
                          </>
                        ) : (
                          <span className="text-slate-500">Mailbox not recorded</span>
                        )}
                      </p>
                      <p className="mt-1 flex min-w-0 flex-wrap items-baseline gap-x-1.5 gap-y-0.5 text-[10px] leading-snug text-slate-500">
                        <span>{emailVisibilityLabel(item.visibility_mode)}</span>
                        <span className="text-slate-600" aria-hidden>
                          ·
                        </span>
                        <span className={`min-w-0 truncate font-medium capitalize ${triageClassificationTextClass(item.classification)}`} title={classificationTitle}>
                          {classificationTitle}
                        </span>
                        <span className="text-slate-600" aria-hidden>
                          ·
                        </span>
                        <span className="shrink-0 tabular-nums text-slate-500" title="AI confidence">
                          {formatConfidence(item.confidence)}
                        </span>
                      </p>
                      <p className="mt-2 line-clamp-2 text-[13px] font-medium leading-snug text-white">{item.subject || "No subject"}</p>
                      <p className="mt-1 truncate text-[11px] text-slate-500">{item.sender || "Unknown sender"}</p>
                      <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-slate-500">{item.reason || item.body_preview || "No triage reason."}</p>
                    </button>
                  );
                })}
                {emailTriageLoadingMore ? (
                  <div className="flex items-center justify-center gap-2 py-3 text-xs text-[var(--text-muted)]">
                    <Loader2 className="animate-spin text-cyan-200/70" size={15} aria-hidden />
                    Loading more…
                  </div>
                ) : null}
              </div>
            </div>

            <div ref={triageDetailPanelRef} className="glass-panel min-w-0 overflow-hidden p-4 sm:p-5">
              {!selectedTriageItem ? (
                <div className="text-sm text-[var(--text-muted)]">Choose a triage email to review it.</div>
              ) : (
                <div className="space-y-5">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
                    <div className="min-w-0">
                      <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Selected email</p>
                      <h2 className="mt-1 break-words text-xl font-semibold text-white sm:text-2xl">{selectedTriageItem.subject || "No subject"}</h2>
                      <p className="mt-2 text-sm text-slate-300">{selectedTriageItem.sender || "Unknown sender"} · {formatAge(selectedTriageItem.received_at || selectedTriageItem.created_at)}</p>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        {selectedTriageItem.mailbox && (
                          <span className="rounded-full border border-sky-300/18 bg-sky-300/10 px-3 py-1 text-xs text-sky-100">
                            {mailboxSourceLabel(selectedTriageItem.mailbox, userEmail) || `Received by ${selectedTriageItem.mailbox}`}
                          </span>
                        )}
                        <span className={`rounded-full border px-3 py-1 text-xs ${emailVisibilityClasses(selectedTriageItem.visibility_mode)}`}>
                          {emailVisibilityLabel(selectedTriageItem.visibility_mode)}
                        </span>
                      </div>
                    </div>
                    <span className={`w-fit shrink-0 rounded-full border px-3 py-1.5 text-xs capitalize ${triageClassificationClasses(selectedTriageItem.classification)}`}>
                      {triageClassificationLabel(selectedTriageItem.classification)}
                    </span>
                  </div>

                  <div className="rounded-[22px] border border-white/10 bg-white/[0.04] p-4">
                    <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Why it stopped</p>
                    <p className="mt-2 text-sm leading-6 text-slate-200">{selectedTriageItem.reason || "Classifier did not find enough safe shipment signal."}</p>
                    <div className="mt-3 grid gap-2 md:grid-cols-2">
                      <div className="rounded-[14px] bg-slate-950/28 p-3">
                        <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-muted)]">Recommended</p>
                        <p className="mt-1 text-sm text-white">{triageClassificationLabel(selectedTriageItem.recommended_action)}</p>
                      </div>
                      <div className="rounded-[14px] bg-slate-950/28 p-3">
                        <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-muted)]">Confidence</p>
                        <p className="mt-1 text-sm text-white">{formatConfidence(selectedTriageItem.confidence)}</p>
                      </div>
                    </div>
                  </div>

                  <div className="rounded-[22px] border border-white/10 bg-slate-950/22 p-4">
                    <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Email preview</p>
                    {selectedTriageItem.can_view_body ? (
                      <p className="mt-3 break-words whitespace-pre-wrap text-sm leading-6 text-slate-300">{selectedTriageItem.body_preview || "No preview available."}</p>
                    ) : (
                      <p className="mt-3 rounded-2xl border border-amber-300/16 bg-amber-300/10 px-4 py-3 text-sm leading-6 text-amber-50">
                        Email body is private for this mailbox. Ask the mailbox owner to share triage access if team review is needed.
                      </p>
                    )}
                  </div>

                  {selectedTriageItem.can_take_action ? (
                  <div className="rounded-[22px] border border-cyan-200/12 bg-cyan-200/[0.04] p-4">
                    <p className="text-xs uppercase tracking-[0.18em] text-cyan-100/70">Operator actions</p>
                    <div className="mt-3 grid gap-2 md:grid-cols-2">
                      <button onClick={() => openTriageActionDialog("create_shipment")} disabled={submitting !== null} className="action-button bg-emerald-300/15 text-emerald-100 hover:bg-emerald-300/20 disabled:opacity-50">
                        Create shipment
                      </button>
                      <button onClick={() => openTriageActionDialog("mark_not_shipment")} disabled={submitting !== null} className="action-button bg-white/10 text-white hover:bg-white/15 disabled:opacity-50">
                        Not a shipment
                      </button>
                      <button onClick={() => openTriageActionDialog("mark_fraud_email")} disabled={submitting !== null} className="action-button bg-rose-300/15 text-rose-100 hover:bg-rose-300/20 disabled:opacity-50">
                        Block email
                      </button>
                      <button onClick={() => openTriageActionDialog("mark_fraud_domain")} disabled={submitting !== null} className="action-button bg-rose-300/10 text-rose-100 hover:bg-rose-300/18 disabled:opacity-50">
                        Block domain
                      </button>
                    </div>
                    <div className="mt-3 flex flex-col gap-2 md:flex-row">
                      <select className="field-input" value={triageLinkShipmentId} onChange={(event) => setTriageLinkShipmentId(event.target.value)}>
                        <option value="">Link to existing shipment...</option>
                        {shipments.slice(0, 80).map((shipment) => (
                          <option key={shipment.id} value={shipment.id}>
                            {shipment.quote_token || shipment.id.slice(0, 8)} · {formatRoute(shipment)}
                          </option>
                        ))}
                      </select>
                      <button onClick={() => openTriageActionDialog("link_to_existing_shipment")} disabled={submitting !== null || !triageLinkShipmentId} className="action-button shrink-0 bg-cyan-300/15 text-cyan-100 hover:bg-cyan-300/20 disabled:opacity-50">
                        Link
                      </button>
                    </div>
                  </div>
                  ) : (
                    <div className="rounded-[22px] border border-white/10 bg-white/[0.04] p-4">
                      <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Operator actions</p>
                      <p className="mt-2 text-sm leading-6 text-slate-300">
                        Actions are disabled because this mailbox has not shared raw email triage access with your account.
                      </p>
                    </div>
                  )}
                </div>
              )}
            </div>
          </section>
        )}

        {!initialLoading && tab === "status_ops" && (
          <section className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,380px),minmax(0,1fr)]">
            <div className="glass-panel flex min-h-0 min-w-0 flex-col overflow-hidden p-4">
              <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Status queue</p>
                  <p className="mt-1 text-lg font-medium text-white">Separate customer and carrier reviews</p>
                </div>
                <div className="flex shrink-0 gap-2">
                  <button onClick={() => setStatusQueueScope("active")} className={`rounded-[14px] px-3 py-2.5 text-xs uppercase tracking-[0.18em] ${statusQueueScope === "active" ? "bg-white text-slate-950" : "bg-white/5 text-[var(--text-muted)]"}`}>Active</button>
                  <button onClick={() => setStatusQueueScope("resolved")} className={`rounded-[14px] px-3 py-2.5 text-xs uppercase tracking-[0.18em] ${statusQueueScope === "resolved" ? "bg-white text-slate-950" : "bg-white/5 text-[var(--text-muted)]"}`}>Resolved</button>
                </div>
              </div>
              <div className="max-h-[min(58dvh,26rem)] min-h-0 flex-1 space-y-2 overflow-y-auto overscroll-contain pr-0.5 [-webkit-overflow-scrolling:touch] xl:max-h-none xl:flex-none xl:overflow-visible">
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
                      <div className="min-w-0">
                        <p className="text-white">{task.task_type.replaceAll("_", " ")}</p>
                        <p className="mt-1 text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">{task.task_state.replaceAll("_", " ")}</p>
                      </div>
                      <span className={`shrink-0 rounded-full border px-3 py-1 text-xs ${reviewPriorityClasses(task.priority)}`}>{task.priority}</span>
                    </div>
                    <p className="mt-2 break-words text-sm text-[var(--text-muted)]">{task.reason}</p>
                  </button>
                ))}
              </div>
            </div>

            <div className="glass-panel min-w-0 overflow-hidden p-4 sm:p-5">
              {!selectedStatusTask ? (
                <div className="text-sm text-[var(--text-muted)]">Choose a status task to review it.</div>
              ) : (
                <div className="space-y-4">
                  <div className="min-w-0">
                    <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Selected task</p>
                    <h2 className="mt-1 break-words text-xl font-semibold text-white sm:text-2xl">{selectedStatusTask.task_type.replaceAll("_", " ")}</h2>
                    <p className="mt-2 break-words text-sm text-[var(--text-muted)]">{selectedStatusTask.reason}</p>
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
                        <p className="mt-1 min-w-0 break-words text-sm font-medium text-white [overflow-wrap:anywhere]">{item.title}</p>
                      </div>
                      <button
                        onClick={() => hideNotificationToast(item.id)}
                        className="rounded-full p-1 text-slate-400 transition hover:bg-white/8 hover:text-white"
                        aria-label="Dismiss notification"
                      >
                        <X size={14} />
                      </button>
                    </div>
                    <p className="mt-2 min-w-0 break-words text-sm leading-6 text-slate-300 [overflow-wrap:anywhere]">{item.detail}</p>
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
          className={`fixed right-6 top-6 z-[89] flex h-[min(82vh,760px)] w-[min(390px,calc(100vw-2rem))] max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-[28px] border border-cyan-200/14 bg-[linear-gradient(180deg,rgba(12,20,31,0.97),rgba(9,15,25,0.96))] shadow-[0_28px_120px_rgba(2,8,23,0.56)] backdrop-blur transition-all duration-300 ${
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
                    className={`min-w-0 w-full rounded-[22px] border px-4 py-4 text-left transition ${
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
                            <p className="mt-1 min-w-0 break-words text-sm font-medium text-white [overflow-wrap:anywhere]">{item.title}</p>
                          </div>
                          <span className="shrink-0 text-[11px] text-slate-400">{formatAge(item.created_at)}</span>
                        </div>
                        <p className="mt-2 min-w-0 break-words text-sm leading-6 text-slate-300 [overflow-wrap:anywhere]">{item.detail}</p>
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
          <section className="glass-panel flex max-h-[min(92dvh,52rem)] min-h-0 flex-col overflow-hidden p-5 xl:max-h-[min(88vh,56rem)]">
            <div className="shrink-0">
              <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Archive</p>
              <h2 className="mt-1 text-2xl font-semibold tracking-[-0.04em] text-white">Ignored shipments</h2>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-300">
                View-only archive for duplicates, cancelled loads, parsing errors, fraud/spam, tests, and non-delivery bounces.
              </p>
            </div>
            <div className="mt-5 shrink-0 grid gap-3 lg:grid-cols-[minmax(0,1fr),220px,180px]">
              <label className="block min-w-0">
                <span className="mb-2 block text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Search archive</span>
                <div
                  className={`relative flex h-11 items-center gap-2 rounded-[14px] border bg-slate-950/24 pl-10 pr-2 shadow-[inset_0_1px_0_rgba(255,255,255,0.02)] transition-[border-color] ${
                    archiveSearch.trim() ? "border-white/22" : "border-cyan-200/10 focus-within:border-white/22"
                  }`}
                >
                  <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-cyan-200/65" size={15} aria-hidden />
                  <input
                    type="text"
                    inputMode="search"
                    autoComplete="off"
                    aria-label="Search archived shipments"
                    className="min-w-0 flex-1 bg-transparent py-2 text-sm font-medium text-white outline-none placeholder:font-normal placeholder:text-slate-500"
                    value={archiveSearch}
                    onChange={(event) => setArchiveSearch(event.target.value)}
                    placeholder="Route, token, thread, notes…"
                  />
                  {archiveSearch.trim() ? (
                    <button
                      type="button"
                      aria-label="Clear search"
                      onClick={() => setArchiveSearch("")}
                      className="inline-flex shrink-0 rounded-[10px] p-1.5 text-slate-400 transition hover:bg-white/10 hover:text-white"
                    >
                      <X size={16} strokeWidth={2} />
                    </button>
                  ) : null}
                </div>
              </label>
              <label className="block min-w-0">
                <span className="mb-2 block text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Reason</span>
                <select className="field-input" value={archiveReasonFilter} onChange={(event) => setArchiveReasonFilter(event.target.value as ArchiveReasonCode | "all")}>
                  <option value="all">All reasons</option>
                  {ARCHIVE_REASON_OPTIONS.map((reason) => (
                    <option key={reason.value} value={reason.value}>
                      {reason.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block min-w-0">
                <span className="mb-2 block text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Archive month</span>
                <input className="field-input" type="month" value={archiveMonth} onChange={(event) => setArchiveMonth(event.target.value)} />
              </label>
            </div>
            <div
              className="mt-5 flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto overscroll-contain px-2 pt-3 pb-3 [-webkit-overflow-scrolling:touch] max-h-[min(58dvh,26rem)] xl:max-h-[min(62vh,36rem)]"
              onScroll={(event) => {
                const el = event.currentTarget;
                if (el.scrollHeight - el.scrollTop - el.clientHeight > 140) return;
                void loadMoreArchivedShipments();
              }}
            >
              {archiveListLoading && archivedShipments.length === 0 ? (
                <div className="flex items-center justify-center gap-2 rounded-[22px] border border-dashed border-white/10 bg-white/5 py-12 text-sm text-[var(--text-muted)]">
                  <Loader2 className="animate-spin text-cyan-200/80" size={18} aria-hidden />
                  Loading archive…
                </div>
              ) : null}
              {!archiveListLoading && archivedShipments.length === 0 && !archiveSearchDebounced ? (
                <div className="rounded-[22px] border border-dashed border-white/10 bg-white/5 p-6 text-sm text-[var(--text-muted)]">
                  No archived shipments match these filters.
                </div>
              ) : null}
              {!archiveListLoading && archivedShipments.length === 0 && archiveSearchDebounced ? (
                <div className="rounded-[22px] border border-dashed border-white/10 bg-white/5 p-6 text-sm text-[var(--text-muted)]">
                  No archived shipments match this search. Try another keyword or clear the field.
                </div>
              ) : null}
              {archivedShipments.length > 0 ? (
                <div className="grid auto-rows-fr grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                  {archivedShipments.map((shipment) => {
                    const fraudIndicators = shipmentFraudIndicators(shipment);
                    const blockingBadge = shipmentBlockingBadge(shipment);
                    const mailboxMeta = mailboxSourceMeta(shipment.source_mailbox, userEmail);
                    const note = shipment.archive_reason_note || shipment.archived_reason || "No note";
                    return (
                      <button
                        key={shipment.id}
                        type="button"
                        onClick={() => {
                          setSelectedShipmentId(shipment.id);
                          setDrawerOpen(true);
                          setDrawerMode("overview");
                          setQuoteParam(null);
                        }}
                        className="group relative flex h-full min-h-0 w-full min-w-0 flex-col overflow-hidden rounded-[18px] border border-white/10 bg-white/[0.05] px-3 pt-2 pb-2 text-left transition hover:-translate-y-0.5 hover:border-white/20 hover:bg-white/[0.08]"
                      >
                        {mailboxMeta ? (
                          <div className="-mx-3 -mt-2 mb-2 border-b border-white/[0.08] bg-black/25 px-3 py-2">
                            <p className="text-[9px] font-semibold uppercase tracking-[0.14em] text-sky-200/55">{mailboxMeta.caption}</p>
                            <p className="mt-1 truncate text-[12px] font-medium leading-snug text-white" title={mailboxMeta.address}>
                              {mailboxMeta.address}
                            </p>
                          </div>
                        ) : null}
                        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                          {fraudIndicators.length > 0 && (
                            <div className="flex items-center gap-1">
                              {fraudIndicators.map((indicator) => {
                                const Icon = indicator.icon;
                                return (
                                  <span
                                    key={indicator.key}
                                    title={indicator.title}
                                    className={`inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full border ${indicator.className}`}
                                  >
                                    <Icon size={11} />
                                  </span>
                                );
                              })}
                            </div>
                          )}
                          <span className="inline-flex h-5 shrink-0 items-center whitespace-nowrap rounded-full border border-amber-300/20 bg-amber-300/12 px-2 text-[9px] font-medium uppercase tracking-[0.1em] text-amber-100">
                            {archiveReasonLabel(shipment.archive_reason_code)}
                          </span>
                          <ShipmentStatusPill status={shipment.status} />
                          {blockingBadge && (
                            <span className="inline-flex h-5 shrink-0 items-center whitespace-nowrap rounded-full bg-amber-300/10 px-2 text-[9px] font-medium uppercase tracking-[0.1em] text-amber-100">
                              {blockingBadge}
                            </span>
                          )}
                          <span
                            title="AI confidence"
                            className="inline-flex h-5 shrink-0 items-center whitespace-nowrap rounded-full border border-cyan-200/14 bg-cyan-300/10 px-2 text-[9px] font-medium uppercase tracking-[0.1em] text-cyan-100"
                          >
                            {formatConfidence(shipment.ai_confidence)}
                          </span>
                          <span className="inline-flex h-5 max-w-full shrink-0 items-center whitespace-nowrap rounded-full border border-white/10 bg-white/5 px-2 text-[9px] font-medium tracking-[0.06em] text-slate-300">
                            <span className="truncate">Archived {formatDate(shipment.archived_at)}</span>
                          </span>
                        </div>
                        <p className="mt-1.5 line-clamp-2 text-[14px] font-medium leading-snug text-white">{formatRoute(shipment)}</p>
                        <div className="mt-1.5 grid grid-cols-[minmax(0,1.25fr)_minmax(0,0.95fr)] gap-x-2 gap-y-1 text-[10px] leading-4 text-[var(--text-muted)]">
                          <p className="min-w-0 whitespace-normal">
                            {formatShipmentSchedule(shipment.ready_at_display, shipment.ready_at_local || null, shipment.ready_at) || "TBD"}
                          </p>
                          <p className="min-w-0 text-right whitespace-normal">Weight: {shipment.weight_lb ?? "--"} lb</p>
                          <p className="min-w-0 whitespace-normal">Token: {shipment.quote_token || "--"}</p>
                          <p className="min-w-0 text-right whitespace-normal">Pallets: {shipment.pallets ?? "--"}</p>
                        </div>
                        <p className="mt-1.5 line-clamp-2 text-[11px] leading-relaxed text-slate-400" title={note}>
                          {note}
                        </p>
                        <p className="mt-auto pt-1.5 text-[10px] text-slate-500">Created {formatDate(shipment.created_at)}</p>
                      </button>
                    );
                  })}
                </div>
              ) : null}
              {archiveLoadingMore ? (
                <div className="flex items-center justify-center gap-2 py-3 text-xs text-[var(--text-muted)]">
                  <Loader2 className="animate-spin text-cyan-200/70" size={14} aria-hidden />
                  Loading more…
                </div>
              ) : null}
            </div>
          </section>
        )}

        {!initialLoading && tab === "clients" && (
          <section className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,420px),minmax(0,1fr)]">
            <form className="glass-panel min-w-0 space-y-3 p-4 sm:p-5" onSubmit={handleCreateClient}>
              <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">New customer</p>
              <input className="field-input" value={clientForm.name} onChange={(event) => setClientForm((current) => ({ ...current, name: event.target.value }))} placeholder="Customer name" />
              <input className="field-input" value={clientForm.email} onChange={(event) => setClientForm((current) => ({ ...current, email: event.target.value }))} placeholder="Customer email" />
              <div className="grid gap-3 sm:grid-cols-2">
                <input className="field-input" value={clientForm.default_margin_percent} onChange={(event) => setClientForm((current) => ({ ...current, default_margin_percent: event.target.value }))} placeholder="Margin %" />
                <input className="field-input" value={clientForm.default_margin_floor} onChange={(event) => setClientForm((current) => ({ ...current, default_margin_floor: event.target.value }))} placeholder="Margin floor" />
              </div>
              <button className="action-button bg-[var(--accent-cyan)] text-slate-950 hover:brightness-110" disabled={submitting !== null}>Add customer</button>
            </form>
            <div className="glass-panel flex min-h-0 min-w-0 flex-col overflow-hidden p-4 sm:p-5 xl:max-h-[min(88vh,56rem)]">
              <div className="shrink-0">
                <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Directory</p>
                <h2 className="mt-1 text-xl font-semibold tracking-[-0.03em] text-white">Customers</h2>
                <p className="mt-1 max-w-xl text-sm text-slate-400">Search by name or email. Scroll to load more.</p>
              </div>
              <label className="mt-4 block min-w-0 shrink-0">
                <span className="mb-2 block text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Search</span>
                <div
                  className={`relative flex h-11 items-center gap-2 rounded-[14px] border bg-slate-950/24 pl-10 pr-2 shadow-[inset_0_1px_0_rgba(255,255,255,0.02)] transition-[border-color] ${
                    customersTabSearch.trim() ? "border-white/22" : "border-cyan-200/10 focus-within:border-white/22"
                  }`}
                >
                  <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-cyan-200/65" size={15} aria-hidden />
                  <input
                    type="text"
                    inputMode="search"
                    autoComplete="off"
                    aria-label="Search customers"
                    className="min-w-0 flex-1 bg-transparent py-2 text-sm font-medium text-white outline-none placeholder:font-normal placeholder:text-slate-500"
                    value={customersTabSearch}
                    onChange={(event) => setCustomersTabSearch(event.target.value)}
                    placeholder="Name or email…"
                  />
                  {customersTabSearch.trim() ? (
                    <button
                      type="button"
                      aria-label="Clear search"
                      onClick={() => setCustomersTabSearch("")}
                      className="inline-flex shrink-0 rounded-[10px] p-1.5 text-slate-400 transition hover:bg-white/10 hover:text-white"
                    >
                      <X size={16} strokeWidth={2} />
                    </button>
                  ) : null}
                </div>
              </label>
              <div
                className="mt-4 flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto overscroll-contain px-0.5 pt-1 pb-2 [-webkit-overflow-scrolling:touch] max-h-[min(58dvh,26rem)] xl:max-h-[min(62vh,36rem)]"
                onScroll={(event) => {
                  const el = event.currentTarget;
                  if (el.scrollHeight - el.scrollTop - el.clientHeight > 140) return;
                  void loadMoreCustomersTab();
                }}
              >
                {customersTabListLoading && customersTabList.length === 0 ? (
                  <div className="flex items-center justify-center gap-2 rounded-[22px] border border-dashed border-white/10 bg-white/5 py-12 text-sm text-[var(--text-muted)]">
                    <Loader2 className="animate-spin text-cyan-200/80" size={18} aria-hidden />
                    Loading customers…
                  </div>
                ) : null}
                {!customersTabListLoading && customersTabList.length === 0 && !customersTabSearchDebounced ? (
                  <div className="rounded-[22px] border border-dashed border-white/10 bg-white/5 p-6 text-sm text-[var(--text-muted)]">No customers yet.</div>
                ) : null}
                {!customersTabListLoading && customersTabList.length === 0 && customersTabSearchDebounced ? (
                  <div className="rounded-[22px] border border-dashed border-white/10 bg-white/5 p-6 text-sm text-[var(--text-muted)]">No matches for this search.</div>
                ) : null}
                {customersTabList.length > 0 ? (
                  <div className="flex flex-col gap-3">
                    {customersTabList.map((client) => (
                      <button
                        key={client.id}
                        type="button"
                        onClick={() => openClientDrawer(client)}
                        className="w-full rounded-2xl border border-white/10 bg-white/5 p-4 text-left transition hover:border-cyan-200/20 hover:bg-white/8"
                      >
                        <div className="flex items-center justify-between gap-3">
                          <div className="min-w-0 text-left">
                            <p className="truncate text-white">{client.name}</p>
                            <p className="truncate text-sm text-[var(--text-muted)]">{client.email}</p>
                          </div>
                          <div className="flex flex-wrap justify-end gap-2">
                            {!client.is_active && <span className="rounded-full bg-amber-300/12 px-3 py-1 text-xs text-amber-100">Inactive</span>}
                            <span className="rounded-full bg-white/10 px-3 py-1 text-xs text-white">{client.default_margin_percent}%</span>
                          </div>
                        </div>
                      </button>
                    ))}
                  </div>
                ) : null}
                {customersTabLoadingMore ? (
                  <div className="flex items-center justify-center gap-2 py-3 text-xs text-[var(--text-muted)]">
                    <Loader2 className="animate-spin text-cyan-200/70" size={14} aria-hidden />
                    Loading more…
                  </div>
                ) : null}
              </div>
            </div>
          </section>
        )}

        {!initialLoading && tab === "carriers" && (
          <section className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,420px),minmax(0,1fr)]">
            <form className="glass-panel min-w-0 space-y-3 p-4 sm:p-5" onSubmit={handleCreateCarrier}>
              <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">New carrier</p>
              <input className="field-input" value={carrierForm.name} onChange={(event) => setCarrierForm((current) => ({ ...current, name: event.target.value }))} placeholder="Carrier name" />
              <input className="field-input" value={carrierForm.email} onChange={(event) => setCarrierForm((current) => ({ ...current, email: event.target.value }))} placeholder="Carrier email" />
              <input className="field-input" value={carrierForm.rating} onChange={(event) => setCarrierForm((current) => ({ ...current, rating: event.target.value }))} placeholder="Rating" />
              <input className="field-input" value={carrierForm.regions} onChange={(event) => setCarrierForm((current) => ({ ...current, regions: event.target.value }))} placeholder="Regions" />
              <input className="field-input" value={carrierForm.equipment} onChange={(event) => setCarrierForm((current) => ({ ...current, equipment: event.target.value }))} placeholder="Equipment" />
              <button className="action-button bg-[var(--accent-cyan)] text-slate-950 hover:brightness-110" disabled={submitting !== null}>Add carrier</button>
            </form>
            <div className="glass-panel flex min-h-0 min-w-0 flex-col overflow-hidden p-4 sm:p-5 xl:max-h-[min(88vh,56rem)]">
              <div className="shrink-0">
                <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Directory</p>
                <h2 className="mt-1 text-xl font-semibold tracking-[-0.03em] text-white">Carriers</h2>
                <p className="mt-1 max-w-xl text-sm text-slate-400">Search by name, email, regions, or equipment. Scroll to load more.</p>
              </div>
              <label className="mt-4 block min-w-0 shrink-0">
                <span className="mb-2 block text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Search</span>
                <div
                  className={`relative flex h-11 items-center gap-2 rounded-[14px] border bg-slate-950/24 pl-10 pr-2 shadow-[inset_0_1px_0_rgba(255,255,255,0.02)] transition-[border-color] ${
                    carriersTabSearch.trim() ? "border-white/22" : "border-cyan-200/10 focus-within:border-white/22"
                  }`}
                >
                  <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-cyan-200/65" size={15} aria-hidden />
                  <input
                    type="text"
                    inputMode="search"
                    autoComplete="off"
                    aria-label="Search carriers"
                    className="min-w-0 flex-1 bg-transparent py-2 text-sm font-medium text-white outline-none placeholder:font-normal placeholder:text-slate-500"
                    value={carriersTabSearch}
                    onChange={(event) => setCarriersTabSearch(event.target.value)}
                    placeholder="Name, email, region, equipment…"
                  />
                  {carriersTabSearch.trim() ? (
                    <button
                      type="button"
                      aria-label="Clear search"
                      onClick={() => setCarriersTabSearch("")}
                      className="inline-flex shrink-0 rounded-[10px] p-1.5 text-slate-400 transition hover:bg-white/10 hover:text-white"
                    >
                      <X size={16} strokeWidth={2} />
                    </button>
                  ) : null}
                </div>
              </label>
              <div
                className="mt-4 flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto overscroll-contain px-0.5 pt-1 pb-2 [-webkit-overflow-scrolling:touch] max-h-[min(58dvh,26rem)] xl:max-h-[min(62vh,36rem)]"
                onScroll={(event) => {
                  const el = event.currentTarget;
                  if (el.scrollHeight - el.scrollTop - el.clientHeight > 140) return;
                  void loadMoreCarriersTab();
                }}
              >
                {carriersTabListLoading && carriersTabList.length === 0 ? (
                  <div className="flex items-center justify-center gap-2 rounded-[22px] border border-dashed border-white/10 bg-white/5 py-12 text-sm text-[var(--text-muted)]">
                    <Loader2 className="animate-spin text-cyan-200/80" size={18} aria-hidden />
                    Loading carriers…
                  </div>
                ) : null}
                {!carriersTabListLoading && carriersTabList.length === 0 && !carriersTabSearchDebounced ? (
                  <div className="rounded-[22px] border border-dashed border-white/10 bg-white/5 p-6 text-sm text-[var(--text-muted)]">No carriers yet.</div>
                ) : null}
                {!carriersTabListLoading && carriersTabList.length === 0 && carriersTabSearchDebounced ? (
                  <div className="rounded-[22px] border border-dashed border-white/10 bg-white/5 p-6 text-sm text-[var(--text-muted)]">No matches for this search.</div>
                ) : null}
                {carriersTabList.length > 0 ? (
                  <div className="flex flex-col gap-3">
                    {carriersTabList.map((carrier) => (
                      <button
                        key={carrier.id}
                        type="button"
                        onClick={() => openCarrierDrawer(carrier)}
                        className="w-full rounded-2xl border border-white/10 bg-white/5 p-4 text-left transition hover:border-cyan-200/20 hover:bg-white/8"
                      >
                        <div className="flex items-center justify-between gap-3">
                          <div className="min-w-0 text-left">
                            <p className="truncate text-white">{carrier.name}</p>
                            <p className="truncate text-sm text-[var(--text-muted)]">{carrier.email}</p>
                            {(carrier.regions?.length || carrier.equipment?.length) ? (
                              <p className="mt-1 line-clamp-2 text-[11px] text-slate-500">
                                {[...(carrier.regions || []), ...(carrier.equipment || [])].join(" · ") || null}
                              </p>
                            ) : null}
                          </div>
                          <div className="flex flex-wrap justify-end gap-2">
                            {!carrier.is_active && <span className="rounded-full bg-amber-300/12 px-3 py-1 text-xs text-amber-100">Inactive</span>}
                            <span className="rounded-full bg-white/10 px-3 py-1 text-xs text-white">Rating {carrier.rating}</span>
                          </div>
                        </div>
                      </button>
                    ))}
                  </div>
                ) : null}
                {carriersTabLoadingMore ? (
                  <div className="flex items-center justify-center gap-2 py-3 text-xs text-[var(--text-muted)]">
                    <Loader2 className="animate-spin text-cyan-200/70" size={14} aria-hidden />
                    Loading more…
                  </div>
                ) : null}
              </div>
            </div>
          </section>
        )}

        {partyDrawer && (selectedPartyClient || selectedPartyCarrier) && (
          <>
            <div
              className="fixed inset-0 z-40 !mt-0 bg-slate-950/45 backdrop-blur-sm"
              onClick={closePartyDrawer}
            />
            <aside className="fixed inset-y-0 top-0 right-0 z-[70] !mt-0 h-[100dvh] w-full max-w-[620px] overflow-y-auto border-l border-white/10 bg-[linear-gradient(180deg,rgba(13,21,32,0.98),rgba(9,16,26,0.97))] p-5 shadow-[0_24px_90px_rgba(0,0,0,0.5)]">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">
                    {partyDrawer.kind === "client" ? "Customer details" : "Carrier details"}
                  </p>
                  <h2 className="mt-1 text-2xl font-semibold text-white">
                    {selectedPartyClient?.name || selectedPartyCarrier?.name}
                  </h2>
                  <p className="mt-1 text-sm text-slate-400">{selectedPartyEmail}</p>
                </div>
                <button
                  type="button"
                  onClick={closePartyDrawer}
                  className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-slate-300 transition hover:bg-white/10 hover:text-white"
                >
                  Close
                </button>
              </div>

              <div className="mt-5 space-y-4">
                {partyDrawer.kind === "client" && selectedPartyClient ? (
                  <div className="rounded-[28px] border border-white/10 bg-[linear-gradient(180deg,rgba(255,255,255,0.055),rgba(255,255,255,0.025))] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.035)]">
                    <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Edit customer</p>
                    <div className="mt-4 space-y-3">
                      <input className="field-input" value={clientEditor.name} onChange={(event) => setClientEditor((current) => ({ ...current, name: event.target.value }))} placeholder="Customer name" />
                      <input className="field-input" value={clientEditor.email} onChange={(event) => setClientEditor((current) => ({ ...current, email: event.target.value }))} placeholder="Customer email" />
                      <div className="grid gap-3 sm:grid-cols-2">
                        <input className="field-input" value={clientEditor.default_margin_percent} onChange={(event) => setClientEditor((current) => ({ ...current, default_margin_percent: event.target.value }))} placeholder="Margin %" />
                        <input className="field-input" value={clientEditor.default_margin_floor} onChange={(event) => setClientEditor((current) => ({ ...current, default_margin_floor: event.target.value }))} placeholder="Margin floor" />
                      </div>
                      <label className="flex items-center gap-3 rounded-2xl border border-white/10 bg-slate-950/28 px-3 py-2 text-sm text-slate-200">
                        <input type="checkbox" checked={clientEditor.is_active} onChange={(event) => setClientEditor((current) => ({ ...current, is_active: event.target.checked }))} />
                        Active customer
                      </label>
                      <button type="button" onClick={() => void handleSaveClientDetails()} disabled={submitting !== null} className="action-button bg-[var(--accent-cyan)] text-slate-950 hover:brightness-110 disabled:opacity-50">
                        Save customer
                      </button>
                    </div>
                  </div>
                ) : null}

                {partyDrawer.kind === "carrier" && selectedPartyCarrier ? (
                  <div className="rounded-[28px] border border-white/10 bg-[linear-gradient(180deg,rgba(255,255,255,0.055),rgba(255,255,255,0.025))] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.035)]">
                    <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Edit carrier</p>
                    <div className="mt-4 space-y-3">
                      <input className="field-input" value={carrierEditor.name} onChange={(event) => setCarrierEditor((current) => ({ ...current, name: event.target.value }))} placeholder="Carrier name" />
                      <input className="field-input" value={carrierEditor.email} onChange={(event) => setCarrierEditor((current) => ({ ...current, email: event.target.value }))} placeholder="Carrier email" />
                      <input className="field-input" value={carrierEditor.rating} onChange={(event) => setCarrierEditor((current) => ({ ...current, rating: event.target.value }))} placeholder="Rating" />
                      <input className="field-input" value={carrierEditor.regions} onChange={(event) => setCarrierEditor((current) => ({ ...current, regions: event.target.value }))} placeholder="Regions, comma-separated" />
                      <input className="field-input" value={carrierEditor.equipment} onChange={(event) => setCarrierEditor((current) => ({ ...current, equipment: event.target.value }))} placeholder="Equipment, comma-separated" />
                      <label className="flex items-center gap-3 rounded-2xl border border-white/10 bg-slate-950/28 px-3 py-2 text-sm text-slate-200">
                        <input type="checkbox" checked={carrierEditor.is_active} onChange={(event) => setCarrierEditor((current) => ({ ...current, is_active: event.target.checked }))} />
                        Active carrier
                      </label>
                      <button type="button" onClick={() => void handleSaveCarrierDetails()} disabled={submitting !== null} className="action-button bg-[var(--accent-cyan)] text-slate-950 hover:brightness-110 disabled:opacity-50">
                        Save carrier
                      </button>
                    </div>
                  </div>
                ) : null}

                <div className="overflow-hidden rounded-[28px] border border-rose-300/18 bg-[linear-gradient(180deg,rgba(244,63,94,0.08),rgba(15,23,42,0.24))] shadow-[inset_0_1px_0_rgba(255,255,255,0.035)]">
                  <button
                    type="button"
                    onClick={() => setPartyDenylistExpanded((expanded) => !expanded)}
                    className="flex w-full items-center justify-between gap-4 p-4 text-left transition hover:bg-rose-300/[0.04]"
                  >
                    <span className="min-w-0">
                      <span className="block text-xs uppercase tracking-[0.18em] text-rose-100/70">Fraud denylist</span>
                      <span className="mt-1 block text-sm text-slate-300">
                        {partyDenylistEntries.filter((entry) => entry.is_active).length} active blocks for this {partyDrawer.kind === "client" ? "customer" : "carrier"}.
                      </span>
                    </span>
                    <span className="inline-flex shrink-0 items-center gap-2 rounded-full border border-rose-200/14 bg-rose-300/10 px-3 py-1.5 text-xs text-rose-50">
                      {partyDenylistExpanded ? "Hide" : "Manage"}
                      <ChevronDown size={14} className={`transition ${partyDenylistExpanded ? "rotate-180" : ""}`} />
                    </span>
                  </button>

                  {partyDenylistExpanded && (
                    <div className="border-t border-rose-200/10 p-4">
                      <p className="text-sm leading-6 text-slate-300">
                        Manage sender email and domain blocks connected to this {partyDrawer.kind === "client" ? "customer" : "carrier"}.
                      </p>
                      <div className="mt-3 grid gap-2 sm:grid-cols-2">
                        <div className="min-w-0 rounded-2xl border border-white/10 bg-slate-950/36 p-3 text-sm text-slate-200">
                          <span className="block text-[10px] uppercase tracking-[0.16em] text-[var(--text-muted)]">Email</span>
                          <span className="mt-1 block break-all text-white">{selectedPartyEmail || "--"}</span>
                        </div>
                        <div className="min-w-0 rounded-2xl border border-white/10 bg-slate-950/36 p-3 text-sm text-slate-200">
                          <span className="block text-[10px] uppercase tracking-[0.16em] text-[var(--text-muted)]">Domain</span>
                          <span className="mt-1 block break-all text-white">{selectedPartyDomain || "--"}</span>
                        </div>
                      </div>
                      <textarea
                        className="field-input mt-3 min-h-[88px]"
                        value={partyDenylistReason}
                        onChange={(event) => setPartyDenylistReason(event.target.value)}
                        placeholder="Reason for denylist change..."
                      />
                      <div className="mt-3 grid gap-2 sm:grid-cols-2">
                        <button type="button" onClick={() => void handleCreatePartyDenylistEntry("sender_email")} disabled={submitting !== null || !selectedPartyEmail} className="action-button bg-rose-300/16 text-rose-50 hover:bg-rose-300/24 disabled:opacity-50">
                          Block email
                        </button>
                        <button type="button" onClick={() => void handleCreatePartyDenylistEntry("sender_domain")} disabled={submitting !== null || !selectedPartyDomain} className="action-button bg-rose-300/12 text-rose-50 hover:bg-rose-300/20 disabled:opacity-50">
                          Block domain
                        </button>
                      </div>
                      <div className="mt-4 space-y-2">
                        {partyDenylistEntries.length === 0 && (
                          <div className="rounded-2xl border border-dashed border-white/10 bg-white/[0.04] p-4 text-sm text-[var(--text-muted)]">
                            No denylist entries for this email or domain.
                          </div>
                        )}
                        {partyDenylistEntries.map((entry) => (
                          <div key={entry.id} className="rounded-2xl border border-white/10 bg-slate-950/36 p-3">
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0">
                                <p className="break-all text-sm font-medium text-white">{entry.value}</p>
                                <p className="mt-1 text-xs uppercase tracking-[0.14em] text-[var(--text-muted)]">{entry.scope.replaceAll("_", " ")}</p>
                              </div>
                              <span className={`shrink-0 rounded-full px-2.5 py-1 text-xs ${entry.is_active ? "bg-rose-300/16 text-rose-100" : "bg-white/10 text-slate-300"}`}>
                                {entry.is_active ? "Active" : "Inactive"}
                              </span>
                            </div>
                            {entry.reason && <p className="mt-2 break-words text-sm text-slate-300">{entry.reason}</p>}
                            <button type="button" onClick={() => void handleTogglePartyDenylistEntry(entry)} disabled={submitting !== null} className="mt-3 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs text-slate-200 transition hover:bg-white/10 disabled:opacity-50">
                              {entry.is_active ? "Disable" : "Enable"}
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </aside>
          </>
        )}

        {contextMenu && contextMenuShipment && contextMenuActionModel && (
          <div
            className="fixed z-50 min-w-[240px] rounded-2xl border border-white/10 bg-slate-950/95 p-2 shadow-2xl backdrop-blur"
            style={{ left: contextMenu.x, top: contextMenu.y }}
            onClick={(event) => event.stopPropagation()}
            onContextMenu={(event) => event.stopPropagation()}
          >
            <button onClick={() => { selectShipment(contextMenu.shipmentId, { openDrawer: true }); setContextMenu(null); }} className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-sm text-white transition hover:bg-white/10">
              <Package2 size={16} /> Open shipment
            </button>
            {contextMenuActionModel.label && contextMenuActionModel.operatorAction && (
              <button
                onClick={() => void runStatefulPrimaryAction(contextMenu.shipmentId, contextMenuActionModel)}
                className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-sm text-cyan-100 transition hover:bg-cyan-300/10"
              >
                <CheckCircle2 size={16} /> {contextMenuActionModel.label}
              </button>
            )}
            <button onClick={() => { enterEditMode(); setContextMenu(null); }} className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-sm text-white transition hover:bg-white/10">
              <PencilLine size={16} /> Edit details
            </button>
            {contextMenuQuickActions.map((action) => (
              <button
                key={action.key}
                onClick={() => void handleContextAction(action, contextMenu.shipmentId)}
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
                      {archiveDialog?.fraudBlockScope
                        ? `This will block future messages from this ${
                            archiveDialog.fraudBlockScope === "sender_domain" ? "domain" : "email address"
                          }, archive the current shipment, and ignore the current source thread.`
                        : "Use this for bounced emails, malformed AI-created shipments, duplicate noise, or any thread you want the automation loop to stop processing."}
                    </div>
                    {archiveDialog?.fraudBlockScope && (
                      <div className="mt-4 rounded-2xl border border-rose-300/25 bg-rose-300/10 p-4 text-sm leading-6 text-rose-50">
                        <p className="font-semibold">
                          Fraud denylist: {archiveDialog.fraudBlockScope === "sender_domain" ? "Block entire domain" : "Block this email"}
                        </p>
                        <p className="mt-1 text-rose-100/80">
                          New matching emails will be saved for audit, tagged as fraud, archived, and will not start automation.
                        </p>
                      </div>
                    )}
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
                        {submitting === "archive_shipment"
                          ? "Working..."
                          : archiveDialog?.fraudBlockScope
                            ? "Block and archive"
                            : "Archive and ignore source"}
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
                <div className="shrink-0 border-b border-white/10">
                  <div className="flex items-start justify-between gap-3 px-5 py-2.5">
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
                  {selectedShipment ? (
                    <div className="flex gap-2 border-t border-white/[0.06] bg-black/15 px-5 py-2 xl:hidden">
                      {([
                        { key: "details", label: "Details" },
                        { key: "thread", label: "Thread" },
                      ] as const).map((tab) => (
                        <button
                          key={tab.key}
                          type="button"
                          onClick={() => setDrawerMobileTab(tab.key)}
                          className={`flex flex-1 items-center justify-between gap-2 rounded-[14px] px-3 py-2 text-xs uppercase tracking-[0.18em] transition ${
                            drawerMobileTab === tab.key
                              ? "bg-white text-slate-950"
                              : "bg-white/5 text-[var(--text-muted)] hover:bg-white/10 hover:text-white"
                          }`}
                        >
                          <span>{tab.label}</span>
                          <ArrowRight size={14} className="shrink-0" />
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
                <div ref={drawerScrollRef} className="flex-1 overflow-y-auto px-5 pb-5 pt-4">
                  {!selectedShipment ? (
                    renderShipmentWorkspace()
                  ) : (
                    <>
                      <div className="xl:hidden">
                        {drawerMobileTab === "details" ? (
                          renderShipmentWorkspace()
                        ) : (
                          <div className="flex h-[calc(100dvh-12rem)] min-h-0 max-h-[min(720px,85dvh)] w-full min-w-0 flex-col pb-2">
                            {renderThreadPanel({ embedded: true })}
                          </div>
                        )}
                      </div>

                      <div className="hidden xl:block">
                        {renderShipmentWorkspace()}
                      </div>
                    </>
                  )}
                </div>
              </div>
            </aside>
          </>
        )}

        <div
          className={`fixed inset-0 z-[65] flex items-center justify-center bg-slate-950/55 px-4 backdrop-blur-sm transition ${
            triageActionDialog ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0"
          }`}
          onClick={() => setTriageActionDialog(null)}
        >
          <div
            className="w-full max-w-[520px] rounded-[30px] border border-cyan-200/16 bg-[linear-gradient(180deg,rgba(15,22,33,0.98),rgba(9,16,25,0.98))] p-6 shadow-[0_32px_100px_rgba(0,0,0,0.45)]"
            onClick={(event) => event.stopPropagation()}
          >
            {triageActionDialog ? (
              (() => {
                const copy = triageActionDialogCopy(triageActionDialog.action);
                const isDanger = copy.tone === "danger";
                return (
                  <div className="flex items-start gap-4">
                    <div className={`rounded-full p-3 ${isDanger ? "bg-rose-300/12 text-rose-100" : "bg-cyan-300/12 text-cyan-100"}`}>
                      <AlertTriangle size={18} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className={`text-xs uppercase tracking-[0.18em] ${isDanger ? "text-rose-200/75" : "text-cyan-200/75"}`}>
                        Confirm email triage action
                      </p>
                      <h3 className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-white">{copy.title}</h3>
                      <p className="mt-3 text-sm leading-6 text-slate-300">{copy.description}</p>
                      <div className="mt-4 rounded-2xl border border-white/10 bg-white/5 p-4 text-sm leading-6 text-slate-300">
                        <p><span className="text-slate-500">From:</span> <span className="text-white">{triageActionDialog.sender}</span></p>
                        <p className="mt-1"><span className="text-slate-500">Subject:</span> <span className="text-white">{triageActionDialog.subject}</span></p>
                        {triageActionDialog.action === "link_to_existing_shipment" && (
                          <p className="mt-1"><span className="text-slate-500">Shipment:</span> <span className="text-white">{triageActionDialog.shipmentId}</span></p>
                        )}
                      </div>
                      {isDanger && (
                        <div className="mt-4 rounded-2xl border border-rose-300/25 bg-rose-300/10 p-4 text-sm leading-6 text-rose-50">
                          This action affects future synced emails. Use it only when the sender is truly spam, fraud, or irrelevant automation noise.
                        </div>
                      )}
                      <div className="mt-5 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
                        <button
                          onClick={() => setTriageActionDialog(null)}
                          disabled={submitting !== null}
                          className="action-button bg-white/10 text-white hover:bg-white/15 disabled:opacity-50"
                        >
                          Cancel
                        </button>
                        <button
                          onClick={() => void confirmTriageAction()}
                          disabled={submitting !== null}
                          className={`action-button disabled:opacity-50 ${
                            isDanger ? "bg-rose-300 text-slate-950 hover:brightness-105" : "bg-cyan-300 text-slate-950 hover:brightness-105"
                          }`}
                        >
                          {submitting === `triage-${triageActionDialog.action}` ? "Working..." : copy.confirmLabel}
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })()
            ) : null}
          </div>
        </div>
      </div>
    </main>
  );
}
