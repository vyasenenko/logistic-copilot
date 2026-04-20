"use client";

import { startTransition, useEffect, useMemo, useState, type FormEvent, type MouseEvent as ReactMouseEvent } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Building2,
  CheckCircle2,
  CircleDollarSign,
  ClipboardCheck,
  Clock3,
  LayoutDashboard,
  Loader2,
  Mail,
  MapPin,
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
type WorkspaceSection = "overview" | "bids" | "timeline" | "status" | "docs";
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
  | "ignore_document_warning";

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
    ready_at: toDateTimeLocal(shipment?.ready_at || null),
    notes: shipment?.notes || "",
  };
}

function statusPillClass(status: string) {
  return SHIPMENT_STATUS_STYLES[status] || "bg-white/10 text-white border-white/10";
}

function shipmentNeedsAttention(shipment: ShipmentRecord) {
  return Boolean(
    shipment.manual_review_required ||
      shipment.ai_missing_fields.length ||
      shipment.ai_ambiguity_reasons.length ||
      shipment.status_review_required ||
      shipment.booking_review_required,
  );
}

function shipmentBlockingBadge(shipment: ShipmentRecord) {
  if (shipment.ai_missing_fields.length > 0) return "Missing details";
  if (shipment.ai_ambiguity_reasons.length > 0) return "Ambiguous";
  if (shipment.manual_review_required) return "Needs review";
  if (shipment.booking_review_required) return "Docs warning";
  if (shipment.status_review_required) return "Status review";
  if (shipment.status_stale) return "Status stale";
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

function ShipmentStatusPill({ status }: { status: string }) {
  return (
    <span className={`inline-flex rounded-full border px-3 py-1 text-xs font-medium capitalize ${statusPillClass(status)}`}>
      {status.replaceAll("_", " ")}
    </span>
  );
}

export function FreightDashboardWorkspace() {
  const [tab, setTab] = useState<DashboardTab>("shipments");
  const [workspaceSection, setWorkspaceSection] = useState<WorkspaceSection>("overview");
  const [overview, setOverview] = useState<OverviewResponse>(EMPTY_OVERVIEW);
  const [clients, setClients] = useState<ClientRecord[]>([]);
  const [carriers, setCarriers] = useState<CarrierRecord[]>([]);
  const [shipments, setShipments] = useState<ShipmentRecord[]>([]);
  const [reviewQueue, setReviewQueue] = useState<ReviewQueueItem[]>([]);
  const [statusQueue, setStatusQueue] = useState<StatusQueueItem[]>([]);
  const [events, setEvents] = useState<WorkflowEventRecord[]>([]);
  const [bids, setBids] = useState<BidRecord[]>([]);
  const [documents, setDocuments] = useState<ShipmentDocumentRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [lastSyncSummary, setLastSyncSummary] = useState<OutlookSyncResponse | null>(null);
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
  const [contextMenu, setContextMenu] = useState<{ shipmentId: string; x: number; y: number } | null>(null);
  const [clientForm, setClientForm] = useState({ name: "", email: "", default_margin_percent: "15", default_margin_floor: "0" });
  const [carrierForm, setCarrierForm] = useState({ name: "", email: "", rating: "0", regions: "midwest,northeast", equipment: "dry van" });
  const [shipmentCreateForm, setShipmentCreateForm] = useState({
    client_id: "",
    origin: "Chicago, IL",
    destination: "New York, NY",
    pallets: "5",
    weight_lb: "10000",
    equipment_type: "Dry Van",
    ready_at: "",
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
    () => shipments.find((shipment) => shipment.id === selectedShipmentId) || null,
    [shipments, selectedShipmentId],
  );
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
        setSelectedShipmentId((current) => current && shipmentData.some((item) => item.id === current) ? current : shipmentData[0]?.id || null);
        setSelectedStatusTaskId((current) => current && statusQueueData.some((item) => item.task_id === current) ? current : statusQueueData[0]?.task_id || null);
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

  async function refreshAll() {
    await loadDashboard();
    if (selectedShipmentId) {
      await loadShipmentContext(selectedShipmentId);
    }
  }

  useEffect(() => {
    void loadDashboard();
  }, []);

  useEffect(() => {
    if (!selectedShipmentId) {
      setEvents([]);
      setBids([]);
      setDocuments([]);
      return;
    }
    setEvaluation(null);
    setQuotePreview(null);
    setStatusReplyPreview(null);
    setTmsPreview(null);
    setBookingResult(null);
    void loadShipmentContext(selectedShipmentId);
  }, [selectedShipmentId]);

  useEffect(() => {
    setShipmentEditor(buildShipmentEditor(selectedShipment));
  }, [selectedShipment]);

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
      }
    };
    window.addEventListener("click", close);
    window.addEventListener("contextmenu", close);
    window.addEventListener("keydown", handleEsc);
    return () => {
      window.removeEventListener("click", close);
      window.removeEventListener("contextmenu", close);
      window.removeEventListener("keydown", handleEsc);
    };
  }, []);

  async function handleOperatorAction(action: OperatorAction, shipmentId?: string) {
    const targetShipmentId = shipmentId || selectedShipment?.id;
    if (!targetShipmentId) return;
    setSubmitting(action);
    setError(null);
    try {
      const response = await fetchJson<ShipmentOperatorActionResponse>(`/api/freight/shipments/${targetShipmentId}/operator-action`, {
        method: "POST",
        body: JSON.stringify({ action }),
      });
      setNotice(response.message);
      await refreshAll();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to run action.");
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
      await refreshAll();
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
      await fetchJson<ShipmentRecord>(`/api/freight/shipments/${selectedShipment.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          client_id: shipmentEditor.client_id || null,
          status: selectedShipment.status,
          origin: shipmentEditor.origin || null,
          destination: shipmentEditor.destination || null,
          pallets: shipmentEditor.pallets ? Number(shipmentEditor.pallets) : null,
          weight_lb: shipmentEditor.weight_lb ? Number(shipmentEditor.weight_lb) : null,
          equipment_type: shipmentEditor.equipment_type || null,
          ready_at: shipmentEditor.ready_at ? new Date(shipmentEditor.ready_at).toISOString() : null,
          margin_policy: {
            percent: Number(selectedShipment.margin_policy.percent || 0),
            floor_amount: Number(selectedShipment.margin_policy.floor_amount || 0),
          },
          notes: shipmentEditor.notes,
        }),
      });
      setNotice("Shipment details saved.");
      await refreshAll();
      return true;
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to save shipment.");
      return false;
    } finally {
      setSubmitting(null);
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
      setWorkspaceSection("overview");
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
      await fetchJson<ShipmentRecord>("/api/freight/shipments", {
        method: "POST",
        body: JSON.stringify({
          client_id: shipmentCreateForm.client_id || null,
          status: "received",
          origin: shipmentCreateForm.origin,
          destination: shipmentCreateForm.destination,
          pallets: Number(shipmentCreateForm.pallets || 0),
          weight_lb: Number(shipmentCreateForm.weight_lb || 0),
          equipment_type: shipmentCreateForm.equipment_type,
          ready_at: shipmentCreateForm.ready_at ? new Date(shipmentCreateForm.ready_at).toISOString() : null,
          margin_policy: {
            percent: Number(shipmentCreateForm.margin_percent || 0),
            floor_amount: Number(shipmentCreateForm.margin_floor || 0),
          },
          notes: shipmentCreateForm.notes,
        }),
      });
      setNotice("Shipment created.");
      await refreshAll();
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
      setNotice("Client added.");
      setClientForm({ name: "", email: "", default_margin_percent: "15", default_margin_floor: "0" });
      await refreshAll();
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
      await fetchJson<CarrierRecord>("/api/freight/carriers", {
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
      setNotice("Carrier added.");
      setCarrierForm({ name: "", email: "", rating: "0", regions: "midwest,northeast", equipment: "dry van" });
      await refreshAll();
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
      await refreshAll();
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
      await refreshAll();
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
      await refreshAll();
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
      await refreshAll();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to intake bid.");
    } finally {
      setSubmitting(null);
    }
  }

  const metrics = [
    { label: "Needs review", value: reviewQueue.length, detail: "operator tasks" },
    { label: "Active shipments", value: overview.counts.shipments, detail: "live workflow cases" },
    { label: "Waiting bids", value: overview.active_stages.waiting_bids || 0, detail: "awaiting carrier replies" },
    { label: "Status stale", value: overview.status_metrics.stale_shipments, detail: "need fresh lookup" },
  ];

  const attentionItems = [
    `${reviewQueue.length} needs review`,
    `${overview.status_metrics.stale_shipments} stale`,
    `${overview.active_stages.waiting_bids || 0} waiting bids`,
    `${shipments.filter((item) => shipmentNeedsAttention(item)).length} awaiting operator`,
  ];

  const secondaryActions = actionModel?.contextActions.filter((action) => action.operatorAction !== actionModel.operatorAction) || [];

  const renderShipmentWorkspace = () => {
    if (!selectedShipment) {
      return (
        <div className="glass-panel flex min-h-[560px] items-center justify-center p-8 text-sm text-[var(--text-muted)]">
          Select a shipment to open the operator workspace.
        </div>
      );
    }

    return (
      <div className="space-y-4">
        <div className="glass-panel p-5">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
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
                <h2 className="text-3xl font-semibold tracking-[-0.04em] text-white">{formatRoute(selectedShipment)}</h2>
                <p className="mt-2 text-sm text-[var(--text-muted)]">
                  Client {selectedShipment.client_id ? "linked" : "not linked"} • Confidence {formatConfidence(selectedShipment.ai_confidence)} • Last agent decision {selectedShipment.ai_next_action || "pending"}
                </p>
              </div>
              <div className="grid gap-3 sm:grid-cols-4">
                <div className="rounded-2xl bg-white/5 p-3">
                  <p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Pallets</p>
                  <p className="mt-2 text-white">{selectedShipment.pallets ?? "--"}</p>
                </div>
                <div className="rounded-2xl bg-white/5 p-3">
                  <p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Weight</p>
                  <p className="mt-2 text-white">{selectedShipment.weight_lb ?? "--"} lb</p>
                </div>
                <div className="rounded-2xl bg-white/5 p-3">
                  <p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Equipment</p>
                  <p className="mt-2 text-white">{selectedShipment.equipment_type || "--"}</p>
                </div>
                <div className="rounded-2xl bg-white/5 p-3">
                  <p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Ready</p>
                  <p className="mt-2 text-white">{formatDate(selectedShipment.ready_at)}</p>
                </div>
              </div>
            </div>

            <div className="w-full max-w-[360px] rounded-[28px] border border-white/10 bg-slate-950/35 p-4">
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
                    onClick={() => void persistShipmentEdits()}
                    disabled={submitting !== null || !shipmentFormDirty}
                    className="action-button w-full bg-white/10 text-white hover:bg-white/15 disabled:opacity-50"
                  >
                    Save changes
                  </button>
                )}
                <p className="text-xs text-[var(--text-muted)]">
                  {shipmentFormDirty ? "Unsaved shipment edits are waiting." : "The main button always maps to the current shipment state."}
                </p>
              </div>
            </div>
          </div>
        </div>

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr),minmax(340px,0.85fr)]">
          <div className="space-y-4">
            <div className="glass-panel p-5">
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Editable shipment details</p>
                  <h3 className="mt-1 text-xl font-semibold text-white">Fix fields and save in place</h3>
                </div>
                <button
                  onClick={() => void persistShipmentEdits()}
                  disabled={!shipmentFormDirty || submitting !== null}
                  className="action-button bg-white/10 text-white hover:bg-white/15 disabled:opacity-50"
                >
                  Save changes
                </button>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <select className="field-input" value={shipmentEditor.client_id} onChange={(event) => setShipmentEditor((current) => ({ ...current, client_id: event.target.value }))}>
                  <option value="">No linked client</option>
                  {clients.map((client) => <option key={client.id} value={client.id}>{client.name}</option>)}
                </select>
                <input className="field-input" placeholder="Equipment" value={shipmentEditor.equipment_type} onChange={(event) => setShipmentEditor((current) => ({ ...current, equipment_type: event.target.value }))} />
                <input className="field-input" placeholder="Origin" value={shipmentEditor.origin} onChange={(event) => setShipmentEditor((current) => ({ ...current, origin: event.target.value }))} />
                <input className="field-input" placeholder="Destination" value={shipmentEditor.destination} onChange={(event) => setShipmentEditor((current) => ({ ...current, destination: event.target.value }))} />
                <input className="field-input" placeholder="Pallets" value={shipmentEditor.pallets} onChange={(event) => setShipmentEditor((current) => ({ ...current, pallets: event.target.value }))} />
                <input className="field-input" placeholder="Weight lb" value={shipmentEditor.weight_lb} onChange={(event) => setShipmentEditor((current) => ({ ...current, weight_lb: event.target.value }))} />
                <input type="datetime-local" className="field-input sm:col-span-2" value={shipmentEditor.ready_at} onChange={(event) => setShipmentEditor((current) => ({ ...current, ready_at: event.target.value }))} />
                <textarea className="field-input min-h-[140px] resize-none sm:col-span-2" placeholder="Notes" value={shipmentEditor.notes} onChange={(event) => setShipmentEditor((current) => ({ ...current, notes: event.target.value }))} />
              </div>
            </div>

            <div className="glass-panel p-5">
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
                      <p className="mt-2 text-white">Review required: {selectedShipment.manual_review_required ? "yes" : "no"}</p>
                      <p className="mt-1 text-sm text-[var(--text-muted)]">Next agent action: {selectedShipment.ai_next_action || "pending"}</p>
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
          </div>

          <div className="space-y-4">
            <div className="glass-panel p-5">
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
                    className="action-button justify-start bg-white/10 text-white hover:bg-white/15 disabled:opacity-50"
                  >
                    {action.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="glass-panel p-5">
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

  return (
    <main className="min-h-screen px-4 py-5 text-[var(--text-main)] sm:px-6 lg:px-8">
      <div className="mx-auto max-w-[1480px] space-y-6">
        <section className="glass-panel overflow-hidden px-5 py-5 sm:px-6">
          <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
            <div className="space-y-4">
              <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs uppercase tracking-[0.2em] text-[var(--text-muted)]">
                <LayoutDashboard size={14} /> Logistic Copilot
              </div>
              <div>
                <h1 className="text-3xl font-semibold tracking-[-0.04em] text-white sm:text-4xl">
                  Simple operator workspace for every shipment.
                </h1>
                <p className="mt-3 max-w-3xl text-sm leading-6 text-[var(--text-muted)] sm:text-base">
                  Pick one shipment, see what blocks it, fix details inline, and run the next correct workflow step with one main button.
                </p>
              </div>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 xl:min-w-[520px]">
              {metrics.map((metric) => (
                <div key={metric.label} className="rounded-[24px] border border-white/10 bg-white/[0.04] p-4">
                  <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">{metric.label}</p>
                  <p className="mt-4 text-3xl font-semibold text-white">{metric.value}</p>
                  <p className="mt-1 text-sm text-[var(--text-muted)]">{metric.detail}</p>
                </div>
              ))}
            </div>
          </div>
          <div className="mt-5 flex flex-wrap gap-2">
            {attentionItems.map((item) => (
              <span key={item} className="rounded-full border border-white/10 bg-white/5 px-3 py-2 text-xs text-[var(--text-muted)]">
                {item}
              </span>
            ))}
          </div>
        </section>

        {error && <div className="glass-panel-strong border-red-400/20 px-5 py-4 text-sm text-red-100">{error}</div>}
        {notice && <div className="glass-panel-strong border-cyan-400/20 px-5 py-4 text-sm text-cyan-100">{notice}</div>}

        <section className="glass-panel p-4">
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
                  className={`flex items-center justify-between rounded-2xl px-4 py-3 text-left transition ${active ? "bg-white text-slate-950" : "bg-white/5 text-[var(--text-muted)] hover:bg-white/10 hover:text-white"}`}
                >
                  <span className="flex items-center gap-3 font-medium"><Icon size={18} />{label}</span>
                  <ArrowRight size={16} />
                </button>
              );
            })}
          </div>
        </section>

        {loading ? (
          <div className="glass-panel flex min-h-[480px] items-center justify-center p-8 text-[var(--text-muted)]">
            <Loader2 className="mr-3 animate-spin" size={18} /> Loading dashboard...
          </div>
        ) : null}

        {!loading && tab === "shipments" && (
          <section className="space-y-4">
            <div className="glass-panel p-4">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Attention strip</p>
                  <p className="mt-1 text-lg font-medium text-white">Start with blocked shipments, not with side panels.</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button onClick={() => void handleOutlookSync()} disabled={submitting !== null} className="action-button bg-cyan-300/15 text-cyan-100 hover:bg-cyan-300/20 disabled:opacity-50">
                    <Mail size={16} /> {submitting === "sync" ? "Syncing..." : "Sync Outlook"}
                  </button>
                  <button onClick={() => void refreshAll()} disabled={submitting !== null} className="action-button bg-white/10 text-white hover:bg-white/15 disabled:opacity-50">
                    <RefreshCcw size={16} /> Refresh
                  </button>
                </div>
              </div>
            </div>

            <div className="grid gap-4 xl:grid-cols-[360px,minmax(0,1fr)]">
              <div className="glass-panel p-3">
                <div className="mb-3 px-2">
                  <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Shipment list</p>
                  <p className="mt-1 text-lg font-medium text-white">Open one case at a time</p>
                </div>
                <div className="space-y-2">
                  {shipments.map((shipment) => {
                    const isSelected = shipment.id === selectedShipmentId;
                    return (
                      <div
                        key={shipment.id}
                        onContextMenu={(event: ReactMouseEvent<HTMLDivElement>) => {
                          event.preventDefault();
                          setSelectedShipmentId(shipment.id);
                          setContextMenu({ shipmentId: shipment.id, x: event.clientX, y: event.clientY });
                        }}
                        className={`rounded-[24px] border p-4 transition ${isSelected ? "border-cyan-300/40 bg-cyan-300/10" : "border-white/10 bg-white/5 hover:bg-white/10"}`}
                      >
                        <div className="flex items-start gap-3">
                          <button onClick={() => setSelectedShipmentId(shipment.id)} className="flex-1 text-left">
                            <div className="flex items-center justify-between gap-3">
                              <ShipmentStatusPill status={shipment.status} />
                              <span className={`rounded-full px-3 py-1 text-xs ${shipmentNeedsAttention(shipment) ? "bg-amber-300/10 text-amber-100" : "bg-emerald-300/10 text-emerald-100"}`}>
                                {shipmentBlockingBadge(shipment)}
                              </span>
                            </div>
                            <p className="mt-3 text-lg font-medium text-white">{formatRoute(shipment)}</p>
                            <p className="mt-1 text-sm text-[var(--text-muted)]">
                              Next: {shipment.ai_next_action ? shipment.ai_next_action.replaceAll("_", " ") : "operator review"}
                            </p>
                            <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
                              <div><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Ready</p><p className="mt-1 text-white">{formatDate(shipment.ready_at)}</p></div>
                              <div><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Confidence</p><p className="mt-1 text-white">{formatConfidence(shipment.ai_confidence)}</p></div>
                            </div>
                          </button>
                          <button
                            onClick={(event) => {
                              event.stopPropagation();
                              setSelectedShipmentId(shipment.id);
                              setContextMenu({ shipmentId: shipment.id, x: event.clientX, y: event.clientY });
                            }}
                            className="rounded-full p-2 text-[var(--text-muted)] transition hover:bg-white/10 hover:text-white"
                          >
                            <MoreHorizontal size={18} />
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {renderShipmentWorkspace()}
            </div>
          </section>
        )}

        {!loading && tab === "status_ops" && (
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
                      setSelectedShipmentId(task.shipment_id);
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

        {!loading && tab === "clients" && (
          <section className="grid gap-4 xl:grid-cols-[420px,minmax(0,1fr)]">
            <form className="glass-panel p-5 space-y-3" onSubmit={handleCreateClient}>
              <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">New client</p>
              <input className="field-input" value={clientForm.name} onChange={(event) => setClientForm((current) => ({ ...current, name: event.target.value }))} placeholder="Client name" />
              <input className="field-input" value={clientForm.email} onChange={(event) => setClientForm((current) => ({ ...current, email: event.target.value }))} placeholder="Client email" />
              <div className="grid gap-3 sm:grid-cols-2">
                <input className="field-input" value={clientForm.default_margin_percent} onChange={(event) => setClientForm((current) => ({ ...current, default_margin_percent: event.target.value }))} placeholder="Margin %" />
                <input className="field-input" value={clientForm.default_margin_floor} onChange={(event) => setClientForm((current) => ({ ...current, default_margin_floor: event.target.value }))} placeholder="Margin floor" />
              </div>
              <button className="action-button bg-[var(--accent-cyan)] text-slate-950 hover:brightness-110" disabled={submitting !== null}>Add client</button>
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

        {!loading && tab === "carriers" && (
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

        {!loading && tab === "shipments" && (
          <section className="glass-panel p-5">
            <div className="grid gap-4 xl:grid-cols-[420px,minmax(0,1fr)]">
              <form className="space-y-3" onSubmit={handleCreateShipment}>
                <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Create shipment</p>
                <select className="field-input" value={shipmentCreateForm.client_id} onChange={(event) => setShipmentCreateForm((current) => ({ ...current, client_id: event.target.value }))}>
                  <option value="">No linked client</option>
                  {clients.map((client) => <option key={client.id} value={client.id}>{client.name}</option>)}
                </select>
                <input className="field-input" value={shipmentCreateForm.origin} onChange={(event) => setShipmentCreateForm((current) => ({ ...current, origin: event.target.value }))} placeholder="Origin" />
                <input className="field-input" value={shipmentCreateForm.destination} onChange={(event) => setShipmentCreateForm((current) => ({ ...current, destination: event.target.value }))} placeholder="Destination" />
                <div className="grid gap-3 sm:grid-cols-2">
                  <input className="field-input" value={shipmentCreateForm.pallets} onChange={(event) => setShipmentCreateForm((current) => ({ ...current, pallets: event.target.value }))} placeholder="Pallets" />
                  <input className="field-input" value={shipmentCreateForm.weight_lb} onChange={(event) => setShipmentCreateForm((current) => ({ ...current, weight_lb: event.target.value }))} placeholder="Weight lb" />
                </div>
                <input className="field-input" value={shipmentCreateForm.equipment_type} onChange={(event) => setShipmentCreateForm((current) => ({ ...current, equipment_type: event.target.value }))} placeholder="Equipment" />
                <input type="datetime-local" className="field-input" value={shipmentCreateForm.ready_at} onChange={(event) => setShipmentCreateForm((current) => ({ ...current, ready_at: event.target.value }))} />
                <textarea className="field-input min-h-[100px] resize-none" value={shipmentCreateForm.notes} onChange={(event) => setShipmentCreateForm((current) => ({ ...current, notes: event.target.value }))} placeholder="Notes" />
                <button className="action-button bg-[var(--accent-cyan)] text-slate-950 hover:brightness-110" disabled={submitting !== null}>Create shipment</button>
              </form>
              <div className="space-y-3">
                <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Review queue snapshot</p>
                {reviewQueue.slice(0, 4).map((item) => (
                  <button key={item.workflow_event_id} onClick={() => setSelectedShipmentId(item.shipment_id)} className="w-full rounded-2xl border border-white/10 bg-white/5 p-4 text-left">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-white">{item.event_type.replaceAll("_", " ")}</p>
                      <span className={`rounded-full border px-3 py-1 text-xs ${reviewPriorityClasses(item.priority)}`}>{item.priority}</span>
                    </div>
                    <p className="mt-2 text-sm text-[var(--text-muted)]">{item.reason}</p>
                  </button>
                ))}
                {lastSyncSummary && (
                  <div className="rounded-2xl border border-cyan-300/20 bg-cyan-300/10 p-4 text-sm text-cyan-50">
                    Last sync: {lastSyncSummary.imported} imported, {lastSyncSummary.parsed_shipments} parsed, {lastSyncSummary.manual_reviews} manual reviews.
                  </div>
                )}
              </div>
            </div>
          </section>
        )}

        {contextMenu && selectedShipment && actionModel && (
          <div
            className="fixed z-50 min-w-[240px] rounded-2xl border border-white/10 bg-slate-950/95 p-2 shadow-2xl backdrop-blur"
            style={{ left: contextMenu.x, top: contextMenu.y }}
            onClick={(event) => event.stopPropagation()}
          >
            <button onClick={() => { setSelectedShipmentId(contextMenu.shipmentId); setContextMenu(null); }} className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-sm text-white transition hover:bg-white/10">
              <Package2 size={16} /> Open shipment
            </button>
            {actionModel.label && actionModel.operatorAction && (
              <button onClick={() => void runStatefulPrimaryAction()} className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-sm text-cyan-100 transition hover:bg-cyan-300/10">
                <CheckCircle2 size={16} /> {actionModel.label}
              </button>
            )}
            <button onClick={() => { setWorkspaceSection("overview"); setContextMenu(null); }} className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-sm text-white transition hover:bg-white/10">
              <PencilLine size={16} /> Edit details
            </button>
            {secondaryActions.map((action) => (
              <button key={action.key} onClick={() => void handleContextAction(action)} className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-sm text-white transition hover:bg-white/10">
                <RefreshCcw size={16} /> {action.label}
              </button>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
