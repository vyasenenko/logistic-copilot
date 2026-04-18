"use client";

import { startTransition, useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  Building2,
  CircleDollarSign,
  ClipboardCheck,
  Clock3,
  LayoutDashboard,
  Loader2,
  Mail,
  Map,
  Package2,
  RadioTower,
  Send,
  ShieldCheck,
  Sparkles,
  Truck,
  Users,
} from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type DashboardTab = "shipments" | "clients" | "carriers";

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
  margin_policy: Record<string, number>;
  notes: string;
  ai_intent: string | null;
  ai_confidence: number | null;
  ai_missing_fields: string[];
  ai_next_action: string | null;
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
  manual_review_required: boolean;
  next_action: string | null;
  evaluation_triggered: boolean;
  quote_auto_sent: boolean;
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
  manual_reviews: number;
  results: OutlookIngestResult[];
}

interface ReviewQueueItem {
  workflow_event_id: string;
  shipment_id: string;
  stage: string;
  event_type: string;
  reason: string;
  created_at: string;
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

const SHIPMENT_STATUS_STYLES: Record<string, string> = {
  received: "bg-sky-400/15 text-sky-200 border-sky-300/20",
  parsing: "bg-teal-400/15 text-teal-200 border-teal-300/20",
  client_acknowledged: "bg-violet-400/15 text-violet-200 border-violet-300/20",
  outreaching: "bg-amber-400/15 text-amber-200 border-amber-300/20",
  waiting_bids: "bg-orange-400/15 text-orange-200 border-orange-300/20",
  evaluating: "bg-rose-400/15 text-rose-200 border-rose-300/20",
  quoted: "bg-emerald-400/15 text-emerald-200 border-emerald-300/20",
  awaiting_confirmation: "bg-fuchsia-400/15 text-fuchsia-200 border-fuchsia-300/20",
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

export function FreightDashboard() {
  const [tab, setTab] = useState<DashboardTab>("shipments");
  const [overview, setOverview] = useState<OverviewResponse>(EMPTY_OVERVIEW);
  const [clients, setClients] = useState<ClientRecord[]>([]);
  const [carriers, setCarriers] = useState<CarrierRecord[]>([]);
  const [shipments, setShipments] = useState<ShipmentRecord[]>([]);
  const [events, setEvents] = useState<WorkflowEventRecord[]>([]);
  const [bids, setBids] = useState<BidRecord[]>([]);
  const [reviewQueue, setReviewQueue] = useState<ReviewQueueItem[]>([]);
  const [evaluation, setEvaluation] = useState<EvaluationResponse | null>(null);
  const [ackPreview, setAckPreview] = useState<ClientAcknowledgementResponse | null>(null);
  const [quotePreview, setQuotePreview] = useState<CustomerQuoteResponse | null>(null);
  const [tmsPreview, setTmsPreview] = useState<TmsHandoffResponse | null>(null);
  const [selectedShipmentId, setSelectedShipmentId] = useState<string | null>(null);
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

  async function loadDashboard() {
    setLoading(true);
    setError(null);
    try {
      const [overviewData, clientData, carrierData, shipmentData, reviewData] = await Promise.all([
        fetchJson<OverviewResponse>("/api/freight/overview"),
        fetchJson<ClientRecord[]>("/api/freight/clients"),
        fetchJson<CarrierRecord[]>("/api/freight/carriers"),
        fetchJson<ShipmentRecord[]>("/api/freight/shipments"),
        fetchJson<ReviewQueueItem[]>("/api/freight/reviews"),
      ]);

      startTransition(() => {
        setOverview(overviewData);
        setClients(clientData);
        setCarriers(carrierData);
        setShipments(shipmentData);
        setReviewQueue(reviewData);
        setSelectedShipmentId((current) =>
          current && shipmentData.some((shipment) => shipment.id === current)
            ? current
            : shipmentData[0]?.id || null,
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
    const [eventData, bidData] = await Promise.all([
      fetchJson<WorkflowEventRecord[]>(`/api/freight/shipments/${shipmentId}/events`),
      fetchJson<BidRecord[]>(`/api/freight/shipments/${shipmentId}/bids`),
    ]);
    setEvents(eventData);
    setBids(bidData);
  }

  useEffect(() => {
    void loadDashboard();
  }, []);

  useEffect(() => {
    if (!selectedShipmentId) {
      setEvents([]);
      setBids([]);
      setEvaluation(null);
      setAckPreview(null);
      setQuotePreview(null);
      setTmsPreview(null);
      return;
    }

    setEvaluation(null);
    setAckPreview(null);
    setQuotePreview(null);
    setTmsPreview(null);
    void loadShipmentContext(selectedShipmentId).catch(() => {
      setEvents([]);
      setBids([]);
    });
  }, [selectedShipmentId]);

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
          ready_at: shipmentForm.ready_at ? new Date(shipmentForm.ready_at).toISOString() : null,
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
          acknowledgement_dry_run: true,
          auto_prepare_outreach_for_new_shipments: true,
          outreach_dry_run: true,
        }),
      });
      setNotice(
        `Outlook sync imported ${response.imported} thread(s), skipped ${response.skipped}, parsed ${response.parsed_shipments} shipment(s), sent ${response.auto_acknowledgements} acknowledgment(s), sent ${response.auto_outreach} outreach flow(s), captured ${response.auto_bids} bid(s), triggered ${response.auto_evaluations} evaluation(s), sent ${response.auto_quotes} quote(s), and flagged ${response.manual_reviews} review item(s).`,
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

  const metrics = [
    {
      label: "Active shipments",
      value: overview.counts.shipments,
      detail: `${overview.counts.workflow_events} workflow events recorded`,
      icon: Package2,
      accent: "from-cyan-300/30 to-cyan-500/5",
    },
    {
      label: "Carrier network",
      value: overview.counts.carriers,
      detail: `${overview.counts.bids} bid records across all lanes`,
      icon: Truck,
      accent: "from-amber-300/30 to-amber-500/5",
    },
    {
      label: "Inbox traffic",
      value: overview.counts.email_messages,
      detail: `${overview.counts.email_threads} normalized threads in Outlook`,
      icon: Mail,
      accent: "from-rose-300/30 to-rose-500/5",
    },
  ];

  const stageHighlights = Object.entries(overview.active_stages).slice(0, 4);

  return (
    <main className="min-h-screen px-4 py-5 text-[var(--text-main)] sm:px-6 lg:px-8">
      <div className="mx-auto max-w-[1600px] space-y-6">
        <section className="glass-panel overflow-hidden px-6 py-6 sm:px-8">
          <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-3xl space-y-4">
              <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs uppercase tracking-[0.24em] text-[var(--text-muted)]">
                <LayoutDashboard size={14} /> Freight Control Tower
              </div>
              <div className="space-y-3">
                <h1 className="max-w-3xl text-4xl font-semibold tracking-[-0.04em] text-white sm:text-5xl">
                  Outlook-native quoting workflow for your brokerage desk.
                </h1>
                <p className="max-w-2xl text-sm leading-7 text-[var(--text-muted)] sm:text-base">
                  Manage inbound requests, build carrier competition, evaluate bids, quote the customer, and preview TMS handoff from one operations surface.
                </p>
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-3 lg:min-w-[520px]">
              {metrics.map(({ label, value, detail, icon: Icon, accent }) => (
                <div key={label} className={`rounded-[24px] border border-white/10 bg-gradient-to-br ${accent} p-4 shadow-lg`}>
                  <div className="mb-10 flex items-center justify-between">
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

          <div className="mt-6 flex flex-wrap items-center gap-3">
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

        <section className="grid gap-6 xl:grid-cols-[260px,minmax(0,1fr),390px]">
          <aside className="glass-panel p-4">
            <div className="mb-4 px-2">
              <p className="text-xs uppercase tracking-[0.2em] text-[var(--text-muted)]">Surfaces</p>
              <p className="mt-2 text-lg font-medium text-white">Operations console</p>
            </div>
            <div className="space-y-2">
              {[
                { key: "shipments", label: "Shipments", icon: Package2 },
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

            <div className="mt-6 rounded-[24px] border border-white/10 bg-slate-950/40 p-4">
              <p className="text-xs uppercase tracking-[0.2em] text-[var(--text-muted)]">Ready state</p>
              <div className="mt-4 space-y-4 text-sm text-[var(--text-muted)]">
                <div className="flex items-center justify-between"><span>Inbox sync</span><ShieldCheck size={16} className="text-cyan-200" /></div>
                <div className="flex items-center justify-between"><span>Carrier outreach</span><Send size={16} className="text-amber-200" /></div>
                <div className="flex items-center justify-between"><span>Bid evaluation</span><Sparkles size={16} className="text-rose-200" /></div>
              </div>
            </div>
          </aside>

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
                    <div className="grid gap-3 p-4 lg:grid-cols-2">
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
                            <div><p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">Ready</p><p className="mt-1 text-base font-medium text-white">{formatDate(shipment.ready_at)}</p></div>
                          </div>
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
              </>
            )}
          </section>

          <section className="space-y-6">
            <div className="glass-panel p-5">
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Create</p>
                  <h3 className="mt-1 text-xl font-semibold text-white">{tab === "shipments" ? "New shipment" : tab === "clients" ? "New client" : "New carrier"}</h3>
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
                  <input type="datetime-local" className="field-input" value={shipmentForm.ready_at} onChange={(event) => setShipmentForm((current) => ({ ...current, ready_at: event.target.value }))} />
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
                    <div className="rounded-2xl bg-white/5 p-4"><p className="text-xs uppercase tracking-[0.18em]">Ready time</p><p className="mt-2 text-base text-white">{formatDate(selectedShipment.ready_at)}</p></div>
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
                  </div>

                  <div className="grid gap-3 sm:grid-cols-2">
                    <button onClick={() => void handlePreviewAcknowledgement()} disabled={submitting === "ack"} className="action-button w-full bg-violet-300/15 text-violet-100 hover:bg-violet-300/20 disabled:opacity-50">{submitting === "ack" ? "Preparing acknowledgment..." : "Preview customer ack"}</button>
                    <button onClick={() => void handleDryRunOutreach()} disabled={submitting === "outreach"} className="action-button w-full bg-[var(--accent-amber)] text-slate-950 hover:brightness-110">{submitting === "outreach" ? "Preparing..." : "Dry-run outreach"}</button>
                    <button onClick={() => void handleEvaluateBids()} disabled={submitting === "evaluate" || bids.length === 0} className="action-button w-full bg-white/10 text-white hover:bg-white/15 disabled:opacity-50">{submitting === "evaluate" ? "Evaluating..." : "Evaluate bids"}</button>
                    <button onClick={() => void handlePreviewCustomerQuote()} disabled={submitting === "quote" || bids.length === 0} className="action-button w-full bg-cyan-300/15 text-cyan-100 hover:bg-cyan-300/20 disabled:opacity-50">{submitting === "quote" ? "Building quote..." : "Preview customer quote"}</button>
                    <button onClick={() => void handlePreviewTmsHandoff()} disabled={submitting === "tms" || bids.length === 0} className="action-button w-full bg-rose-300/15 text-rose-100 hover:bg-rose-300/20 disabled:opacity-50">{submitting === "tms" ? "Preparing handoff..." : "Preview TMS handoff"}</button>
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

                  {tmsPreview && <div className="rounded-[24px] border border-rose-300/20 bg-rose-300/10 p-4"><div className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-rose-100"><ClipboardCheck size={14} />TMS preview</div><pre className="mt-3 overflow-x-auto whitespace-pre-wrap rounded-2xl bg-slate-950/40 p-4 text-xs text-rose-50">{JSON.stringify(tmsPreview.payload, null, 2)}</pre></div>}

                  <div className="space-y-3">
                    <div className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]"><Clock3 size={14} />Workflow timeline</div>
                    <div className="space-y-3">
                      {events.length === 0 && <div className="rounded-2xl border border-dashed border-white/10 bg-white/5 px-4 py-6 text-sm text-[var(--text-muted)]">No events yet for this shipment.</div>}
                      {events.map((eventRecord) => <div key={eventRecord.id} className="rounded-2xl border border-white/10 bg-white/5 p-4"><div className="flex items-center justify-between gap-3"><p className="text-sm font-medium text-white">{eventRecord.event_type.replaceAll("_", " ")}</p><span className="text-xs text-[var(--text-muted)]">{formatDate(eventRecord.created_at)}</span></div><p className="mt-1 text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">{eventRecord.stage.replaceAll("_", " ")}</p></div>)}
                    </div>
                  </div>
                </div>
              )}

              {tab === "clients" && selectedClient && <div className="space-y-4"><div><p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Client detail</p><h3 className="mt-1 text-xl font-semibold text-white">{selectedClient.name}</h3></div><div className="rounded-2xl bg-white/5 p-4 text-sm text-[var(--text-muted)]"><div className="flex items-center gap-3 text-white"><Building2 size={16} /> {selectedClient.email}</div><div className="mt-4 flex items-center justify-between"><span>Margin rule</span><span className="text-white">{selectedClient.default_margin_percent}%</span></div><div className="mt-2 flex items-center justify-between"><span>Floor price</span><span className="text-white">${selectedClient.default_margin_floor}</span></div></div></div>}

              {tab === "carriers" && selectedCarrier && <div className="space-y-4"><div><p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Carrier detail</p><h3 className="mt-1 text-xl font-semibold text-white">{selectedCarrier.name}</h3></div><div className="rounded-2xl bg-white/5 p-4 text-sm text-[var(--text-muted)]"><div className="flex items-center gap-3 text-white"><Map size={16} /> {selectedCarrier.email}</div><div className="mt-4 flex items-center justify-between"><span>Rating</span><span className="text-white">{selectedCarrier.rating}</span></div><div className="mt-4 flex flex-wrap gap-2">{selectedCarrier.regions.map((region) => <span key={region} className="rounded-full bg-white/10 px-3 py-1 text-xs text-white">{region}</span>)}</div><div className="mt-3 flex flex-wrap gap-2">{selectedCarrier.equipment.map((equipment) => <span key={equipment} className="rounded-full bg-cyan-300/10 px-3 py-1 text-xs text-cyan-100">{equipment}</span>)}</div></div></div>}
            </div>

            <div className="glass-panel p-5">
              <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Connected systems</p>
              <div className="mt-4 space-y-3 text-sm text-[var(--text-muted)]">
                <div className="flex items-center justify-between rounded-2xl bg-white/5 px-4 py-3"><span className="flex items-center gap-3"><Mail size={16} /> Outlook inbox</span><span className="text-white">Ready</span></div>
                <div className="flex items-center justify-between rounded-2xl bg-white/5 px-4 py-3"><span className="flex items-center gap-3"><CircleDollarSign size={16} /> Margin defaults</span><span className="text-white">{overview.integrations.quote_wait_minutes_default || "20"} min window</span></div>
                <div className="flex items-center justify-between rounded-2xl bg-white/5 px-4 py-3"><span className="flex items-center gap-3"><ClipboardCheck size={16} /> TMS connector</span><span className="text-white">Preview-ready</span></div>
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
                  </div>
                </div>
              )}

              <div className="mt-6">
                <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">Review queue</p>
                <div className="mt-4 space-y-3">
                  {reviewQueue.length === 0 && <div className="rounded-2xl border border-dashed border-white/10 bg-white/5 px-4 py-5 text-sm text-[var(--text-muted)]">No manual review items.</div>}
                  {reviewQueue.slice(0, 5).map((item) => (
                    <button key={item.workflow_event_id} onClick={() => setSelectedShipmentId(item.shipment_id)} className="w-full rounded-2xl border border-white/10 bg-white/5 p-4 text-left transition hover:bg-white/10">
                      <div className="flex items-center justify-between gap-3">
                        <p className="text-sm font-medium text-white">{item.event_type.replaceAll("_", " ")}</p>
                        <span className="text-xs text-[var(--text-muted)]">{formatDate(item.created_at)}</span>
                      </div>
                      <p className="mt-2 text-sm text-[var(--text-muted)]">{item.reason || "Operator review requested"}</p>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </section>
        </section>
      </div>
    </main>
  );
}
