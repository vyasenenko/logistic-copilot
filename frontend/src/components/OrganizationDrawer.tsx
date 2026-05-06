"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useLayoutEffect, useState, type ReactNode } from "react";
import {
  ArrowRight,
  CheckCircle2,
  ExternalLink,
  Loader2,
  LogOut,
  Mail,
  Settings,
  Power,
  RefreshCcw,
  ShieldCheck,
  Sparkles,
  Truck,
  Users,
  X,
} from "lucide-react";
import { PUBLIC_API_URL as API_URL } from "@/constants/publicApi";
import { notifyCopilotChromeExtensionLogout } from "@/lib/notifyChromeExtensionLogout";
import { showToast } from "@/lib/toast-store";

const AUTH_TOKEN_KEY = "logistic_copilot_auth_token";

/** Logistic Copilot — Chrome Web Store listing (AI agent side panel). */
const CHROME_WEB_STORE_LOGISTIC_COPILOT_URL =
  "https://chromewebstore.google.com/detail/logistic-copilot/cgjgjfdnbdaahgmnalcjkockkogijhfj";

interface CurrentUserResponse {
  user_id: string;
  organization_id: string;
  role: string;
  permissions: string[];
  email: string;
}

interface OrganizationRecord {
  id: string;
  name: string;
  primary_domain: string | null;
  status: string;
}

interface EmailConnectionRecord {
  id: string;
  user_id: string;
  organization_id: string;
  provider: string;
  mailbox: string;
  status: string;
  visibility_mode?: string;
  graph_subscription_id?: string | null;
  subscription_expires_at?: string | null;
  auto_sync_enabled?: boolean;
}

interface OutlookCredentialsResponse {
  tenant_id?: string | null;
  client_id?: string | null;
  mailbox?: string | null;
  client_secret_configured?: boolean;
  graph_subscription_id?: string | null;
  subscription_expires_at?: string | null;
}

interface OutlookUserSyncStatusResponse {
  mailbox: string;
  organization_domain?: string | null;
  connection?: EmailConnectionRecord | null;
  microsoft_configured: boolean;
  webhook_public_url_configured: boolean;
  can_enable: boolean;
  status: string;
  message?: string | null;
}

interface OutlookSyncResponse {
  imported: number;
  skipped: number;
  parsed_shipments: number;
  manual_reviews: number;
}

interface OutlookWebhookStatusResponse {
  configured: boolean;
  status: string;
  missing_fields: string[];
  expected_notification_url?: string | null;
  expected_resource?: string | null;
  expected_change_type?: string | null;
  subscription_id?: string | null;
  subscription_action?: string | null;
  expires_at?: string | null;
  matching_count: number;
  active_matching_count: number;
  total_subscriptions: number;
  last_checked_at?: string | null;
}

interface OrganizationDrawerProps {
  open: boolean;
  onClose: () => void;
}

const ORG_DRAWER_CACHE_KEY = "logistic-copilot-organization-drawer-v1";
const ORG_DRAWER_CACHE_TTL_MS = 10 * 60 * 1000;

type OrgDrawerCachePayload = {
  me: CurrentUserResponse;
  organization: OrganizationRecord;
  connections: EmailConnectionRecord[];
  syncStatus: OutlookUserSyncStatusResponse;
  credentials: OutlookCredentialsResponse;
  webhookStatus: OutlookWebhookStatusResponse | null;
};

type OrgDrawerCacheEnvelope = {
  savedAt: number;
  payload: OrgDrawerCachePayload;
};

let memoryOrgDrawerCache: OrgDrawerCacheEnvelope | null = null;

function readOrgDrawerCache(): OrgDrawerCachePayload | null {
  if (typeof window === "undefined") {
    return memoryOrgDrawerCache && Date.now() - memoryOrgDrawerCache.savedAt <= ORG_DRAWER_CACHE_TTL_MS
      ? memoryOrgDrawerCache.payload
      : null;
  }
  if (memoryOrgDrawerCache && Date.now() - memoryOrgDrawerCache.savedAt <= ORG_DRAWER_CACHE_TTL_MS) {
    return memoryOrgDrawerCache.payload;
  }
  try {
    const raw = window.sessionStorage.getItem(ORG_DRAWER_CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as OrgDrawerCacheEnvelope;
    if (!parsed?.savedAt || !parsed?.payload?.me?.user_id) return null;
    if (Date.now() - parsed.savedAt > ORG_DRAWER_CACHE_TTL_MS) {
      window.sessionStorage.removeItem(ORG_DRAWER_CACHE_KEY);
      return null;
    }
    memoryOrgDrawerCache = parsed;
    return parsed.payload;
  } catch {
    return null;
  }
}

function writeOrgDrawerCache(payload: OrgDrawerCachePayload) {
  const envelope: OrgDrawerCacheEnvelope = { savedAt: Date.now(), payload };
  memoryOrgDrawerCache = envelope;
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(ORG_DRAWER_CACHE_KEY, JSON.stringify(envelope));
  } catch {
    /* quota or private mode */
  }
}

function clearOrgDrawerCache() {
  memoryOrgDrawerCache = null;
  if (typeof window !== "undefined") {
    try {
      window.sessionStorage.removeItem(ORG_DRAWER_CACHE_KEY);
    } catch {
      /* ignore */
    }
  }
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = typeof window !== "undefined" ? window.localStorage.getItem(AUTH_TOKEN_KEY) : null;
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail = payload?.detail;
    throw new Error(typeof detail === "string" ? detail : `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    auto_sync_on: "Auto-sync on",
    auto_sync_off: "Auto-sync off",
    ready: "Ready",
    not_configured: "Not configured",
    needs_microsoft_setup: "Needs Microsoft setup",
    needs_webhook_url: "Needs public webhook URL",
    domain_mismatch: "Domain mismatch",
    expired: "Expired",
  };
  return labels[status] || status.replaceAll("_", " ");
}

function statusClasses(status: string) {
  if (status === "auto_sync_on") return "border-emerald-300/20 bg-emerald-300/10 text-emerald-100";
  if (status === "ready" || status === "auto_sync_off") return "border-cyan-300/20 bg-cyan-300/10 text-cyan-100";
  return "border-amber-300/20 bg-amber-300/10 text-amber-100";
}

function webhookStatusLabel(status: string | null | undefined) {
  if (!status) return "Unknown";
  if (status === "active") return "Active";
  if (status === "expiring_soon") return "Expiring soon";
  if (status === "expired") return "Expired";
  if (status === "missing_configuration") return "Needs setup";
  if (status === "not_installed") return "Not installed";
  return status.replace(/_/g, " ");
}

function visibilityLabel(value: string | null | undefined) {
  if (value === "shared_ops") return "Shared with ops";
  if (value === "metadata_only") return "Metadata only";
  return "Private";
}

function visibilityDescription(value: string | null | undefined) {
  if (value === "shared_ops") {
    return "Authorized team members can review and act on triage emails from this mailbox.";
  }
  if (value === "metadata_only") {
    return "Your team can see limited metadata, but only you can read or act on raw emails.";
  }
  return "Only you can see and act on raw synced emails. Shipments created from them remain visible to your organization.";
}

function formatDate(value: string | null | undefined) {
  if (!value) return "Not available";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function SectionHeading({ children }: { children: ReactNode }) {
  return <p className="mb-2 px-0.5 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">{children}</p>;
}

/** Primary drawer actions — visual weight lives here, not on card frames. */
const drawerPrimaryBtn =
  "inline-flex shrink-0 items-center gap-1.5 rounded-full bg-cyan-400 px-3.5 py-1.5 text-xs font-semibold text-slate-950 shadow-[0_0_18px_-4px_rgba(34,211,238,0.55)] transition hover:bg-cyan-300 hover:shadow-[0_0_22px_-3px_rgba(34,211,238,0.65)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300/50 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0a121c]";

const drawerQuietCard = "rounded-2xl bg-white/[0.035]";

export function OrganizationDrawer({ open, onClose }: OrganizationDrawerProps) {
  const router = useRouter();
  const [me, setMe] = useState<CurrentUserResponse | null>(null);
  const [organization, setOrganization] = useState<OrganizationRecord | null>(null);
  const [connections, setConnections] = useState<EmailConnectionRecord[]>([]);
  const [syncStatus, setSyncStatus] = useState<OutlookUserSyncStatusResponse | null>(null);
  const [credentials, setCredentials] = useState<OutlookCredentialsResponse | null>(null);
  const [webhookStatus, setWebhookStatus] = useState<OutlookWebhookStatusResponse | null>(null);
  const [lastSyncSummary, setLastSyncSummary] = useState<OutlookSyncResponse | null>(null);
  const [syncLimit, setSyncLimit] = useState(10);
  const [loading, setLoading] = useState(false);
  const [revalidating, setRevalidating] = useState(false);
  const [working, setWorking] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [logoutWorking, setLogoutWorking] = useState(false);

  const canManageMicrosoft = me?.role === "owner" || me?.role === "admin";
  const isViewerRole = (me?.role || "").trim().toLowerCase() === "viewer";
  const canViewTeamMailboxes = canManageMicrosoft;
  const canManageUsers = Boolean(me?.permissions.includes("*") || me?.permissions.includes("members:invite"));
  const microsoftConfigured = Boolean(
    credentials?.tenant_id && credentials?.client_id && credentials?.client_secret_configured
  );

  const load = useCallback(
    async (options?: { silent?: boolean; quiet?: boolean; signal?: { cancelled: boolean } }) => {
      if (!open) return;
      const silent = Boolean(options?.silent);
      const quiet = Boolean(options?.quiet);
      const aborted = () => Boolean(options?.signal?.cancelled);

      if (!silent) setLoading(true);
      else if (!quiet) setRevalidating(true);

      setError(null);
      try {
        const [meData, orgData, syncData, credentialsData] = await Promise.all([
          apiFetch<CurrentUserResponse>("/api/auth/me"),
          apiFetch<OrganizationRecord>("/api/organizations/current"),
          apiFetch<OutlookUserSyncStatusResponse>("/api/auth/email-connections/me/outlook"),
          apiFetch<OutlookCredentialsResponse>("/api/organizations/current/outlook-credentials"),
        ]);

        const adminish = meData.role === "owner" || meData.role === "admin";
        const [connectionsData, webhookData] = await Promise.all([
          adminish ? apiFetch<EmailConnectionRecord[]>("/api/auth/email-connections") : Promise.resolve([] as EmailConnectionRecord[]),
          apiFetch<OutlookWebhookStatusResponse>("/api/freight/outlook/auto-sync/status").catch(() => null),
        ]);

        const payload: OrgDrawerCachePayload = {
          me: meData,
          organization: orgData,
          connections: connectionsData,
          syncStatus: syncData,
          credentials: credentialsData,
          webhookStatus: webhookData,
        };
        writeOrgDrawerCache(payload);

        if (aborted()) return;

        setMe(meData);
        setOrganization(orgData);
        setSyncStatus(syncData);
        setCredentials(credentialsData);
        setConnections(connectionsData);
        setWebhookStatus(webhookData);
      } catch (loadError) {
        if (!aborted()) {
          setError(loadError instanceof Error ? loadError.message : "Failed to load organization settings.");
        }
      } finally {
        if (aborted()) return;
        if (!silent) setLoading(false);
        if (silent && !quiet) setRevalidating(false);
      }
    },
    [open],
  );

  useLayoutEffect(() => {
    if (!open) {
      setRevalidating(false);
      return;
    }
    const snap = readOrgDrawerCache();
    if (snap) {
      setMe(snap.me);
      setOrganization(snap.organization);
      setConnections(snap.connections);
      setSyncStatus(snap.syncStatus);
      setCredentials(snap.credentials);
      setWebhookStatus(snap.webhookStatus);
      setLoading(false);
      setError(null);
    } else {
      setLoading(true);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const hadCache = readOrgDrawerCache() !== null;
    const signal = { cancelled: false };
    void load({ silent: hadCache, quiet: false, signal });
    return () => {
      signal.cancelled = true;
    };
  }, [open, load]);

  async function toggleAutoSync() {
    const isOn = syncStatus?.status === "auto_sync_on";
    setWorking(isOn ? "disable" : "enable");
    setError(null);
    try {
      const response = await apiFetch<OutlookUserSyncStatusResponse>(
        isOn ? "/api/auth/email-connections/me/outlook/disable" : "/api/auth/email-connections/me/outlook/enable",
        { method: "POST" }
      );
      setSyncStatus(response);
      showToast(response.message || (isOn ? "Auto-sync disabled." : "Auto-sync enabled."));
      await load({ silent: true, quiet: true });
    } catch (toggleError) {
      setError(toggleError instanceof Error ? toggleError.message : "Failed to update auto-sync.");
    } finally {
      setWorking(null);
    }
  }

  async function syncNow() {
    setWorking("sync");
    setError(null);
    try {
      const response = await apiFetch<OutlookSyncResponse>("/api/freight/outlook/sync", {
        method: "POST",
        body: JSON.stringify({
          limit: syncLimit,
          auto_acknowledge_new_shipments: true,
          acknowledgement_dry_run: false,
          auto_prepare_outreach_for_new_shipments: true,
          outreach_dry_run: false,
          auto_send_customer_quotes: true,
          customer_quote_dry_run: false,
        }),
      });
      setLastSyncSummary(response);
      showToast(
        `Synced ${response.imported} message(s) from your mailbox, skipped ${response.skipped}, parsed ${response.parsed_shipments} shipment(s), review ${response.manual_reviews}.`
      );
    } catch (syncError) {
      setError(syncError instanceof Error ? syncError.message : "Failed to sync inbox.");
    } finally {
      setWorking(null);
    }
  }

  async function updateEmailVisibility(visibilityMode: "private" | "shared_ops") {
    setWorking("visibility");
    setError(null);
    try {
      const response = await apiFetch<OutlookUserSyncStatusResponse>("/api/auth/email-connections/me/outlook", {
        method: "PATCH",
        body: JSON.stringify({ visibility_mode: visibilityMode }),
      });
      setSyncStatus(response);
      showToast("Outlook email privacy settings updated.");
      await load({ silent: true, quiet: true });
    } catch (visibilityError) {
      setError(visibilityError instanceof Error ? visibilityError.message : "Failed to update email privacy.");
    } finally {
      setWorking(null);
    }
  }

  async function handleLogout() {
    setLogoutWorking(true);
    const token = typeof window !== "undefined" ? window.localStorage.getItem(AUTH_TOKEN_KEY) : null;
    try {
      if (token) {
        await fetch(`${API_URL}/api/auth/logout`, {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
        });
      }
    } catch {
      /* still clear client session */
    } finally {
      clearOrgDrawerCache();
      if (typeof window !== "undefined") {
        window.localStorage.removeItem(AUTH_TOKEN_KEY);
        notifyCopilotChromeExtensionLogout();
      }
      setLogoutWorking(false);
      onClose();
      router.push("/");
      router.refresh();
    }
  }

  return (
    <>
      <div
        className={`fixed inset-0 z-[92] bg-slate-950/40 backdrop-blur-[2px] transition ${
          open ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0"
        }`}
        onClick={onClose}
      />
      <aside
        className={`fixed z-[93] flex flex-col overflow-hidden bg-[linear-gradient(180deg,rgba(7,15,25,0.98),rgba(11,23,37,0.97)_52%,rgba(7,12,20,0.98))] backdrop-blur-xl transition-transform duration-300 ease-out motion-reduce:transition-none ${
          open ? "translate-x-0" : "translate-x-full"
        } inset-0 left-0 right-0 top-0 h-[100dvh] max-h-[100dvh] w-full max-w-none border-0 shadow-none md:left-auto md:h-screen md:max-h-none md:w-[min(496px,calc(100vw-1rem))] md:border-l md:border-cyan-200/14 md:shadow-[-22px_0_90px_rgba(0,0,0,0.44)] pt-[env(safe-area-inset-top,0px)] pb-[env(safe-area-inset-bottom,0px)]`}
        role="dialog"
        aria-modal={open}
        aria-hidden={!open}
        aria-labelledby="organization-drawer-title"
      >
        <div className="shrink-0 border-b border-cyan-200/10">
          <div className="px-5 pb-4 pt-5">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-cyan-200/60">Organization</p>
                <h2 id="organization-drawer-title" className="mt-1 truncate text-xl font-semibold text-white">
                  {organization?.name || "Logistic Copilot"}
                </h2>
                <p className="mt-1 truncate text-sm text-slate-400">{organization?.primary_domain || me?.email || "Company workspace"}</p>
              </div>
              <button onClick={onClose} className="rounded-full p-2 text-slate-400 transition hover:bg-white/8 hover:text-white" aria-label="Close organization settings">
                <X size={18} />
              </button>
            </div>
            <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
              <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
                {me ? (
                  <>
                    <span className="rounded-full bg-cyan-400/15 px-3 py-1 text-xs text-cyan-50">{me.role}</span>
                    <span className="max-w-[min(100%,260px)] truncate rounded-full bg-white/[0.06] px-3 py-1 text-xs text-slate-300">
                      {me.email}
                    </span>
                  </>
                ) : null}
              </div>
              <button
                type="button"
                onClick={() => void handleLogout()}
                disabled={logoutWorking}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-cyan-400/35 bg-cyan-400/[0.12] px-3 py-1 text-xs font-semibold text-cyan-50 transition hover:border-cyan-300/50 hover:bg-cyan-400/20 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
                aria-label="Sign out"
              >
                {logoutWorking ? <Loader2 className="animate-spin" size={14} /> : <LogOut size={14} />}
                Sign out
              </button>
            </div>
          </div>
          {revalidating && !loading ? (
            <div
              className="h-[2px] w-full overflow-hidden bg-cyan-200/[0.07]"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label="Refreshing organization data"
            >
              <div className="h-full w-[34%] bg-cyan-300 motion-safe:animate-org-drawer-refresh-bar" />
            </div>
          ) : null}
        </div>

        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-4 py-4 overscroll-contain">
          {loading ? (
            <div className={`flex items-center gap-2 p-4 text-sm text-slate-300 ${drawerQuietCard}`}>
              <Loader2 className="animate-spin" size={16} /> Loading…
            </div>
          ) : null}

          {!loading && canManageUsers ? (
            <div>
              <SectionHeading>Team</SectionHeading>
              <div className={`flex items-center gap-3 px-3 py-3 ${drawerQuietCard}`}>
                <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-sky-400/15 text-sky-100">
                  <Users size={18} />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-white">Members & invites</p>
                  <p className="mt-0.5 text-xs text-slate-400">Invite teammates and roles.</p>
                </div>
                <Link href="/users" className={drawerPrimaryBtn} onClick={onClose}>
                  Open <ArrowRight size={13} />
                </Link>
              </div>
            </div>
          ) : null}

          {!loading ? (
            <div>
              <SectionHeading>AI agent</SectionHeading>
              <div className={`flex flex-wrap items-center gap-3 px-3 py-3 ${drawerQuietCard}`}>
                <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-violet-400/15 text-violet-100">
                  <Sparkles size={18} aria-hidden />
                </div>
                <div className="min-w-0 flex-1 basis-[min(100%,200px)]">
                  <p className="text-sm font-semibold text-white">Chrome extension</p>
                  <p className="mt-0.5 text-xs leading-relaxed text-slate-400">
                    Install the side-panel agent to work on RFQs and freight workflows next to Outlook on the web.
                  </p>
                </div>
                <a
                  href={CHROME_WEB_STORE_LOGISTIC_COPILOT_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={`${drawerPrimaryBtn} gap-1`}
                >
                  Chrome Web Store <ExternalLink size={13} aria-hidden />
                </a>
              </div>
            </div>
          ) : null}

          {!loading ? (
            <div>
              <SectionHeading>Integrations</SectionHeading>

              <div className={`overflow-hidden ${drawerQuietCard}`}>
                {!microsoftConfigured ? (
                  canManageMicrosoft ? (
                  <div className="flex items-center gap-3 px-4 py-4">
                    <div className="flex size-11 shrink-0 items-center justify-center rounded-2xl bg-[linear-gradient(145deg,rgba(14,165,233,0.22),rgba(15,23,42,0.35))] text-cyan-100">
                      <Mail size={20} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <h3 className="text-base font-semibold text-white">Microsoft Outlook</h3>
                      <p className="mt-1 text-xs leading-relaxed text-slate-500">
                        Configure organization Graph credentials on the settings page to enable mailbox sync.
                      </p>
                    </div>
                    <Link href="/settings/outlook" className={`${drawerPrimaryBtn} gap-1`} onClick={onClose}>
                      Settings <ArrowRight size={13} />
                    </Link>
                  </div>
                  ) : null
                ) : (
                  <>
                    <div className="border-b border-white/[0.06] px-4 py-4">
                      <div className="flex items-start gap-3">
                        <div className="flex size-11 shrink-0 items-center justify-center rounded-2xl bg-[linear-gradient(145deg,rgba(14,165,233,0.22),rgba(15,23,42,0.35))] text-cyan-100">
                          <Mail size={20} />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <h3 className="text-base font-semibold text-white">Microsoft Outlook</h3>
                            {syncStatus?.status === "auto_sync_on" ? (
                              <span className="rounded-full border border-emerald-300/25 bg-emerald-400/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-100">
                                Live sync
                              </span>
                            ) : (
                              <span className="rounded-full border border-amber-300/20 bg-amber-400/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-100">
                                Idle
                              </span>
                            )}
                          </div>
                          <p className="mt-1 text-xs leading-relaxed text-slate-400">
                            Mailbox sync, webhooks, and workflow intake for this organization.
                          </p>
                        </div>
                      </div>

                      {/* Org Graph */}
                      <div className="mt-4 rounded-xl bg-emerald-400/[0.09] px-3 py-2.5">
                        <div className="flex flex-wrap items-center gap-2">
                          <ShieldCheck className="text-emerald-200" size={16} />
                          <span className="text-xs font-medium text-white">Microsoft Graph (organization)</span>
                          <span className="rounded-full border border-emerald-300/25 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-100">
                            Ready
                          </span>
                          {canManageMicrosoft ? (
                            <Link
                              href="/settings/outlook"
                              className="ml-auto inline-flex items-center gap-1 text-[11px] font-semibold text-cyan-100 underline-offset-2 hover:underline"
                              onClick={onClose}
                            >
                              Configure <ArrowRight size={12} />
                            </Link>
                          ) : (
                            <span className="ml-auto text-[10px] text-slate-500">Owner / Admin</span>
                          )}
                        </div>
                      </div>
                    </div>

                    <div className="divide-y divide-white/[0.05]">
                      {/* Your mailbox + auto-sync */}
                      <div className="px-4 py-3.5">
                        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">Your mailbox</p>
                        <div className="mt-2 flex items-start justify-between gap-3">
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-sm font-medium text-white">{syncStatus?.mailbox || me?.email || "—"}</p>
                            <span className={`mt-1.5 inline-flex rounded-full border px-2 py-0.5 text-[11px] ${statusClasses(syncStatus?.status || "not_configured")}`}>
                              {statusLabel(syncStatus?.status || "not_configured")}
                            </span>
                            <div className="mt-2 flex flex-wrap gap-1.5 text-[10px] text-slate-500">
                              <span>Webhook {webhookStatusLabel(webhookStatus?.status)}</span>
                              <span className="text-slate-600">·</span>
                              <span title={formatDate(webhookStatus?.expires_at)}>Until {formatDate(webhookStatus?.expires_at)}</span>
                            </div>
                          </div>
                          <button
                            type="button"
                            role="switch"
                            aria-checked={syncStatus?.status === "auto_sync_on"}
                            onClick={() => void toggleAutoSync()}
                            disabled={Boolean(working) || (!syncStatus?.can_enable && syncStatus?.status !== "auto_sync_on")}
                            className={`flex h-8 w-[3.25rem] shrink-0 items-center rounded-full border p-[3px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400/35 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0c1522] disabled:opacity-50 ${
                              syncStatus?.status === "auto_sync_on"
                                ? "justify-end border-emerald-400/35 bg-emerald-500/[0.22]"
                                : "justify-start border-white/14 bg-white/[0.08]"
                            }`}
                            aria-label="Toggle Outlook auto-sync"
                          >
                            <span className="pointer-events-none size-[1.375rem] rounded-full bg-white shadow-[0_1px_2px_rgba(0,0,0,0.28)] ring-1 ring-black/10" />
                          </button>
                        </div>
                        <p className="mt-2 rounded-lg bg-amber-400/[0.08] px-2.5 py-1.5 text-[11px] leading-snug text-amber-50/95">
                          Auto-sync ingests new mail into shipments and workflow events.
                        </p>
                      </div>

                      {!isViewerRole ? (
                        <div className="px-4 py-3.5">
                          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">Triage visibility</p>
                          <p className="mt-1 text-[11px] leading-relaxed text-slate-500">
                            {visibilityDescription(syncStatus?.connection?.visibility_mode)}
                          </p>
                          <div className="mt-2 flex items-center justify-between gap-3">
                            <span className="text-sm font-medium text-white">{visibilityLabel(syncStatus?.connection?.visibility_mode)}</span>
                            <button
                              type="button"
                              role="switch"
                              aria-checked={syncStatus?.connection?.visibility_mode === "shared_ops"}
                              onClick={() =>
                                void updateEmailVisibility(syncStatus?.connection?.visibility_mode === "shared_ops" ? "private" : "shared_ops")
                              }
                              disabled={Boolean(working)}
                              className={`flex h-8 w-[3.25rem] shrink-0 items-center rounded-full border p-[3px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400/35 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0c1522] disabled:opacity-50 ${
                                syncStatus?.connection?.visibility_mode === "shared_ops"
                                  ? "justify-end border-cyan-300/35 bg-cyan-400/[0.24]"
                                  : "justify-start border-white/14 bg-white/[0.08]"
                              }`}
                              aria-label="Share synced email triage with organization team"
                            >
                              <span className="pointer-events-none size-[1.375rem] rounded-full bg-white shadow-[0_1px_2px_rgba(0,0,0,0.28)] ring-1 ring-black/10" />
                            </button>
                          </div>
                          <p className="mt-2 text-[10px] leading-relaxed text-slate-600">
                            Shipments and workflow events stay visible to the org regardless of this setting.
                          </p>
                        </div>
                      ) : null}

                      {!isViewerRole ? (
                        <div className="px-4 py-3.5">
                          <div className="flex items-center justify-between gap-2">
                            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">Manual pull</p>
                            <Settings className="text-slate-600" size={14} />
                          </div>
                          <p className="mt-1 text-[11px] text-slate-500">
                            One-off fetch from your mailbox (requires auto-sync on).
                          </p>
                          <div className="mt-2 grid grid-cols-4 gap-1.5">
                            {[5, 10, 25, 50].map((limit) => (
                              <button
                                key={limit}
                                type="button"
                                onClick={() => setSyncLimit(limit)}
                                className={`rounded-lg px-2 py-1.5 text-xs font-medium transition ${
                                  syncLimit === limit
                                    ? "bg-white text-slate-950"
                                    : "bg-white/[0.06] text-slate-400 hover:bg-white/10 hover:text-white"
                                }`}
                              >
                                {limit}
                              </button>
                            ))}
                          </div>
                          <button
                            type="button"
                            onClick={() => void syncNow()}
                            disabled={Boolean(working) || syncStatus?.status !== "auto_sync_on"}
                            className="mt-2 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-cyan-400 py-2 text-xs font-semibold text-slate-950 shadow-[0_0_18px_-5px_rgba(34,211,238,0.55)] transition hover:bg-cyan-300 disabled:opacity-45 disabled:shadow-none"
                          >
                            {working === "sync" ? <Loader2 className="animate-spin" size={14} /> : <RefreshCcw size={14} />}
                            Sync now
                          </button>
                        </div>
                      ) : null}

                      {lastSyncSummary ? (
                        <div className="bg-slate-950/25 px-4 py-3">
                          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">Last manual sync</p>
                          <div className="mt-2 grid grid-cols-2 gap-1.5 text-[11px]">
                            <div className="rounded-lg bg-white/[0.05] px-2 py-1.5 text-slate-200">
                              In <span className="font-semibold text-white">{lastSyncSummary.imported}</span>
                            </div>
                            <div className="rounded-lg bg-white/[0.05] px-2 py-1.5 text-slate-200">
                              Skip <span className="font-semibold text-white">{lastSyncSummary.skipped}</span>
                            </div>
                            <div className="rounded-lg bg-white/[0.05] px-2 py-1.5 text-slate-200">
                              Parsed <span className="font-semibold text-white">{lastSyncSummary.parsed_shipments}</span>
                            </div>
                            <div className="rounded-lg bg-white/[0.05] px-2 py-1.5 text-slate-200">
                              Review <span className="font-semibold text-white">{lastSyncSummary.manual_reviews}</span>
                            </div>
                          </div>
                        </div>
                      ) : null}

                      {canViewTeamMailboxes ? (
                        <div className="px-4 py-3.5">
                          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">Organization mailboxes</p>
                          <div className="mt-2 space-y-1.5">
                            {connections.length === 0 ? (
                              <p className="text-xs text-slate-500">No connections yet.</p>
                            ) : (
                              connections.map((connection) => (
                                <div key={connection.id} className="flex items-center justify-between gap-2 rounded-lg bg-white/[0.05] px-2.5 py-2">
                                  <div className="min-w-0">
                                    <p className="truncate text-xs font-medium text-white">{connection.mailbox}</p>
                                    <p className="text-[10px] text-slate-500">
                                      {connection.status} · {visibilityLabel(connection.visibility_mode)}
                                    </p>
                                  </div>
                                  {connection.auto_sync_enabled ? (
                                    <CheckCircle2 className="shrink-0 text-emerald-300/90" size={14} />
                                  ) : (
                                    <Power className="shrink-0 text-slate-600" size={14} />
                                  )}
                                </div>
                              ))
                            )}
                          </div>
                        </div>
                      ) : null}
                    </div>
                  </>
                )}
              </div>
            </div>
          ) : null}

          {error ? <p className="rounded-2xl bg-red-400/12 px-4 py-3 text-sm text-red-100">{error}</p> : null}
        </div>
      </aside>
    </>
  );
}
