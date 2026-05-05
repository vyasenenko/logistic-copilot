"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Building2,
  CheckCircle2,
  ClipboardCheck,
  ExternalLink,
  KeyRound,
  type LucideIcon,
  Loader2,
  Mail,
  Save,
  ShieldCheck,
  Users,
  Zap,
} from "lucide-react";

import { AuthGate } from "@/components/AuthGate";
import { DashboardLogo } from "@/components/DashboardLogo";
import { PUBLIC_API_URL as API_URL } from "@/constants/publicApi";

const AUTH_TOKEN_KEY = "logistic_copilot_auth_token";

interface OutlookCredentialsResponse {
  tenant_id?: string | null;
  client_id?: string | null;
  mailbox?: string | null;
  client_secret_configured?: boolean;
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

const OUTLOOK_SETUP_PHASES: Array<{ title: string; subtitle: string; steps: Array<{ title: string; body: string }> }> = [
  {
    title: "App registration",
    subtitle: "Links Microsoft 365 with Logistic Copilot once per tenant.",
    steps: [
      { title: "Open Azure Portal", body: "Go to portal.azure.com → Microsoft Entra ID." },
      { title: "App registrations", body: "Create a new registration or open your existing Logistic Copilot app." },
    ],
  },
  {
    title: "IDs & client secret",
    subtitle: "Copied from the app Overview and Certificates & secrets.",
    steps: [
      { title: "Directory (tenant) ID", body: "On Overview, copy Directory (tenant) ID → first field in the form." },
      { title: "Application (client) ID", body: "On the same screen, copy Application (client) ID → second field." },
      {
        title: "Create a client secret",
        body: "Certificates & secrets → New client secret → copy the VALUE immediately (Azure hides it later).",
      },
    ],
  },
  {
    title: "Microsoft Graph access",
    subtitle: "Application permissions + admin consent — required for mailbox sync.",
    steps: [
      {
        title: "API permissions",
        body: "Add Microsoft Graph Application permissions. Mail.Read at minimum; Mail.ReadWrite if you need send/update or archive workflows.",
      },
      {
        title: "Grant admin consent",
        body: "Tenant admin must grant consent or Graph calls will fail for every mailbox.",
      },
      {
        title: "Exchange application policies",
        body: "If your tenant uses Exchange Online application access policies, allow this app for mailboxes that will sync.",
      },
    ],
  },
];

function FlowArrow({ className }: { className?: string }) {
  return (
    <div className={`flex items-center justify-center text-cyan-300/40 ${className ?? ""}`} aria-hidden>
      <ArrowRight className="hidden h-6 w-6 lg:block" />
      <span className="block py-1 text-lg leading-none lg:hidden">↓</span>
    </div>
  );
}

function OutlookSetupPageContent() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [tenantId, setTenantId] = useState("");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [secretConfigured, setSecretConfigured] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const configured = Boolean(tenantId && clientId && secretConfigured);
  const callouts: Array<{ title: string; body: string; Icon: LucideIcon }> = [
    {
      title: "Secret VALUE, not Secret ID",
      body: "Azure shows both fields. Logistic Copilot needs the secret value. If you leave the page, Microsoft will not show it again.",
      Icon: KeyRound,
    },
    {
      title: "Application permissions only",
      body: "Delegated permissions are not enough for app-only background access to mailboxes through Microsoft Graph.",
      Icon: ShieldCheck,
    },
    {
      title: "Admin consent is required",
      body: "Until a tenant admin grants consent, Graph requests for mailboxes will be denied.",
      Icon: CheckCircle2,
    },
    {
      title: "Encrypted at rest",
      body: "Client secrets are stored encrypted on the server.",
      Icon: KeyRound,
    },
  ];

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch<OutlookCredentialsResponse>("/api/organizations/current/outlook-credentials");
      setTenantId(data.tenant_id || "");
      setClientId(data.client_id || "");
      setSecretConfigured(Boolean(data.client_secret_configured));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load Outlook settings.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function saveSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      await apiFetch<OutlookCredentialsResponse>("/api/organizations/current/outlook-credentials", {
        method: "PUT",
        body: JSON.stringify({
          tenant_id: tenantId.trim(),
          client_id: clientId.trim(),
          client_secret: clientSecret,
        }),
      });
      setClientSecret("");
      setSecretConfigured(true);
      setNotice("Microsoft Graph credentials saved. Your team can enable Outlook auto-sync from the Organization drawer on the dashboard.");
      await load();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Failed to save Outlook settings.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="min-h-screen bg-[radial-gradient(ellipse_120%_80%_at_50%_-20%,rgba(34,211,238,0.12),transparent),linear-gradient(180deg,#07111f,#060b13)] px-4 py-8 text-slate-100 sm:px-6 lg:px-10 lg:py-10">
      <div className="mx-auto max-w-6xl space-y-10">
        {/* Hero */}
        <header className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
            <DashboardLogo className="h-10 w-10 shrink-0 object-contain sm:h-11 sm:w-11" />
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-cyan-200/70">Integrations · Email</p>
              <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white sm:text-4xl">Microsoft Outlook &amp; Graph</h1>
              <p className="mt-3 max-w-xl text-sm leading-relaxed text-slate-400">
                Configure the Azure app once for your whole organization. After you save, each user turns on sync for their own work mailbox from the Organization drawer on the dashboard.
              </p>
            </div>
          </div>
          <Link
            href="/dashboard"
            className="inline-flex shrink-0 items-center gap-2 self-start rounded-full border border-white/12 bg-white/[0.06] px-4 py-2 text-sm font-medium text-cyan-50 transition hover:bg-white/10"
          >
            <ArrowLeft size={16} /> Back to dashboard
          </Link>
        </header>

        {/* Visual flow */}
        <section className="rounded-[2rem] border border-cyan-200/12 bg-[linear-gradient(165deg,rgba(12,26,42,0.95),rgba(7,15,25,0.92))] p-6 shadow-[0_24px_80px_rgba(0,0,0,0.35)] sm:p-8">
          <div className="flex flex-wrap items-center gap-2">
            <Zap className="text-cyan-200" size={18} />
            <h2 className="text-lg font-semibold text-white">How it fits together</h2>
          </div>
          <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-400">
            The fields below are not user passwords. They connect your Microsoft 365 tenant to Logistic Copilot so that, when each user opts in, we can read mail through Microsoft Graph.
          </p>

          <div className="mt-8 flex flex-col items-stretch gap-4 lg:flex-row lg:items-stretch lg:justify-between lg:gap-3">
            <div className="flex flex-1 flex-col rounded-2xl border border-white/10 bg-slate-950/50 p-5">
              <div className="flex items-center gap-3">
                <div className="flex size-11 items-center justify-center rounded-xl border border-sky-300/20 bg-sky-400/10 text-sky-100">
                  <Building2 size={22} />
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Step 1</p>
                  <p className="font-semibold text-white">Microsoft 365</p>
                </div>
              </div>
              <p className="mt-3 flex-1 text-sm leading-relaxed text-slate-400">App registration and Graph permissions in your tenant.</p>
            </div>

            <FlowArrow className="lg:w-10 lg:shrink-0" />

            <div className="flex flex-1 flex-col rounded-2xl border border-cyan-200/18 bg-cyan-400/[0.06] p-5 ring-1 ring-cyan-300/10">
              <div className="flex items-center gap-3">
                <div className="flex size-11 items-center justify-center rounded-xl border border-cyan-200/25 bg-cyan-300/15 text-cyan-50">
                  <ShieldCheck size={22} />
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wider text-cyan-200/60">Step 2</p>
                  <p className="font-semibold text-white">Logistic Copilot (organization)</p>
                </div>
              </div>
              <p className="mt-3 flex-1 text-sm leading-relaxed text-slate-300">
                Tenant ID, Client ID, and client secret are stored at the organization level (encrypted on the server).
              </p>
            </div>

            <FlowArrow className="lg:w-10 lg:shrink-0" />

            <div className="flex flex-1 flex-col rounded-2xl border border-white/10 bg-slate-950/50 p-5">
              <div className="flex items-center gap-3">
                <div className="flex size-11 items-center justify-center rounded-xl border border-emerald-300/18 bg-emerald-400/10 text-emerald-100">
                  <Users size={22} />
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Step 3</p>
                  <p className="font-semibold text-white">Each user&apos;s mailbox</p>
                </div>
              </div>
              <p className="mt-3 flex-1 text-sm leading-relaxed text-slate-400">
                Auto-sync and webhook are enabled per mailbox in the Organization drawer on the dashboard.
              </p>
            </div>
          </div>

          <div className="mt-6 flex flex-wrap items-center gap-3 rounded-2xl border border-white/8 bg-black/25 px-4 py-3 text-xs text-slate-400">
            <Mail className="shrink-0 text-slate-500" size={16} />
            <span>
              Without saved credentials, users cannot turn on sync. With credentials saved, they can—if an admin granted consent and Exchange policies allow access.
            </span>
          </div>
        </section>

        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)] lg:gap-10">
          {/* Form column */}
          <div className="space-y-6">
            <div
              className={`rounded-[1.75rem] border p-6 ${
                configured ? "border-emerald-300/22 bg-emerald-400/[0.07]" : "border-amber-300/20 bg-amber-400/[0.06]"
              }`}
            >
              <div className="flex flex-wrap gap-3">
                <div className="flex min-w-[140px] flex-1 flex-col gap-1 rounded-xl border border-white/10 bg-black/20 px-3 py-2">
                  <span className="text-[10px] uppercase tracking-wide text-slate-500">Tenant ID</span>
                  <span className="flex items-center gap-1.5 text-sm font-medium text-white">
                    {tenantId.trim() ? <CheckCircle2 className="text-emerald-300" size={16} /> : <span className="size-4 rounded-full border border-slate-600" />}
                    {tenantId.trim() ? "Set" : "Missing"}
                  </span>
                </div>
                <div className="flex min-w-[140px] flex-1 flex-col gap-1 rounded-xl border border-white/10 bg-black/20 px-3 py-2">
                  <span className="text-[10px] uppercase tracking-wide text-slate-500">Client ID</span>
                  <span className="flex items-center gap-1.5 text-sm font-medium text-white">
                    {clientId.trim() ? <CheckCircle2 className="text-emerald-300" size={16} /> : <span className="size-4 rounded-full border border-slate-600" />}
                    {clientId.trim() ? "Set" : "Missing"}
                  </span>
                </div>
                <div className="flex min-w-[140px] flex-1 flex-col gap-1 rounded-xl border border-white/10 bg-black/20 px-3 py-2">
                  <span className="text-[10px] uppercase tracking-wide text-slate-500">Client secret</span>
                  <span className="flex items-center gap-1.5 text-sm font-medium text-white">
                    {secretConfigured ? <CheckCircle2 className="text-emerald-300" size={16} /> : <span className="size-4 rounded-full border border-slate-600" />}
                    {secretConfigured ? "Stored" : "Missing"}
                  </span>
                </div>
              </div>
              <div className="mt-4 flex items-start gap-3">
                {configured ? (
                  <CheckCircle2 className="mt-0.5 shrink-0 text-emerald-200" size={22} />
                ) : (
                  <AlertTriangle className="mt-0.5 shrink-0 text-amber-200" size={22} />
                )}
                <div>
                  <p className="font-semibold text-white">{configured ? "Graph is ready" : "Enter all three values"}</p>
                  <p className="mt-1 text-sm leading-relaxed text-slate-300">
                    After you save, your team can enable Outlook auto-sync in the app. Rotate the secret using this same form (leave the secret field blank to keep the current one).
                  </p>
                </div>
              </div>
            </div>

            <form
              onSubmit={(event) => void saveSettings(event)}
              className="space-y-4 rounded-[1.75rem] border border-white/10 bg-white/[0.035] p-6 shadow-inner shadow-black/20"
            >
              <div className="flex items-center gap-2 border-b border-white/8 pb-4">
                <KeyRound className="text-cyan-200/80" size={20} />
                <div>
                  <h3 className="text-lg font-semibold text-white">Application credentials</h3>
                  <p className="text-xs text-slate-500">Organization owners and admins only</p>
                </div>
              </div>

              {loading ? (
                <div className="flex items-center gap-2 py-6 text-sm text-slate-400">
                  <Loader2 className="animate-spin" size={17} /> Loading…
                </div>
              ) : (
                <div className="space-y-4">
                  <label className="block space-y-1.5">
                    <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">Directory (tenant) ID</span>
                    <input
                      required
                      value={tenantId}
                      onChange={(event) => setTenantId(event.target.value)}
                      className="w-full rounded-xl border border-white/10 bg-slate-950/80 px-3 py-3 text-sm text-white outline-none transition placeholder:text-slate-600 focus:border-cyan-300/45"
                      placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                      autoComplete="off"
                    />
                  </label>
                  <label className="block space-y-1.5">
                    <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">Application (client) ID</span>
                    <input
                      required
                      value={clientId}
                      onChange={(event) => setClientId(event.target.value)}
                      className="w-full rounded-xl border border-white/10 bg-slate-950/80 px-3 py-3 text-sm text-white outline-none transition placeholder:text-slate-600 focus:border-cyan-300/45"
                      placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                      autoComplete="off"
                    />
                  </label>
                  <label className="block space-y-1.5">
                    <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">
                      Client secret {secretConfigured ? "(leave blank to keep current)" : ""}
                    </span>
                    <input
                      type="password"
                      required={!secretConfigured}
                      value={clientSecret}
                      onChange={(event) => setClientSecret(event.target.value)}
                      className="w-full rounded-xl border border-white/10 bg-slate-950/80 px-3 py-3 text-sm text-white outline-none transition placeholder:text-slate-600 focus:border-cyan-300/45"
                      placeholder={secretConfigured ? "Leave blank to keep the stored secret" : "Paste the secret VALUE from Azure"}
                      autoComplete="new-password"
                    />
                  </label>
                </div>
              )}

              {notice ? (
                <p className="rounded-xl border border-emerald-300/15 bg-emerald-300/10 px-3 py-2 text-sm text-emerald-100">{notice}</p>
              ) : null}
              {error ? <p className="rounded-xl border border-red-300/20 bg-red-400/10 px-3 py-2 text-sm text-red-100">{error}</p> : null}

              <button
                type="submit"
                disabled={saving || loading}
                className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-cyan-400/25 to-cyan-300/15 px-4 py-3.5 text-sm font-semibold text-cyan-50 ring-1 ring-cyan-300/25 transition hover:from-cyan-400/35 hover:to-cyan-300/22 disabled:opacity-50"
              >
                {saving ? <Loader2 className="animate-spin" size={17} /> : <Save size={17} />} Save credentials
              </button>
            </form>
          </div>

          {/* Guide column */}
          <div className="space-y-6">
            <div className="rounded-[1.75rem] border border-white/10 bg-slate-950/55 p-6 sm:p-8">
              <div className="flex items-start gap-3">
                <ClipboardCheck className="mt-1 shrink-0 text-cyan-200" size={24} />
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-cyan-200/65">Azure walkthrough</p>
                  <h2 className="mt-2 text-xl font-semibold text-white sm:text-2xl">From registration to admin consent</h2>
                  <p className="mt-2 text-sm leading-relaxed text-slate-400">
                    The three sections below follow the order you typically complete in the portal. Step numbers run through the whole checklist so you can track progress with your team.
                  </p>
                </div>
              </div>

              <a
                href="https://portal.azure.com/#view/Microsoft_AAD_IAM/ActiveDirectoryMenuBlade/~/RegisteredApps"
                target="_blank"
                rel="noreferrer"
                className="mt-6 inline-flex items-center gap-2 rounded-full border border-cyan-200/22 bg-cyan-400/10 px-4 py-2 text-sm font-semibold text-cyan-50 transition hover:bg-cyan-400/18"
              >
                Open App registrations <ExternalLink size={15} />
              </a>

              <div className="relative mt-8 space-y-8 pl-1">
                <div className="absolute left-[15px] top-6 bottom-6 w-px bg-gradient-to-b from-cyan-400/35 via-cyan-400/15 to-transparent" aria-hidden />
                {OUTLOOK_SETUP_PHASES.map((phase, phaseIndex) => {
                  let stepOffset = 0;
                  for (let i = 0; i < phaseIndex; i += 1) stepOffset += OUTLOOK_SETUP_PHASES[i].steps.length;
                  return (
                    <div key={phase.title} className="relative">
                      <div className="flex gap-4">
                        <span className="relative z-[1] flex size-8 shrink-0 items-center justify-center rounded-full border border-cyan-300/30 bg-[#0c1829] text-xs font-bold text-cyan-100">
                          {phaseIndex + 1}
                        </span>
                        <div className="min-w-0 flex-1 pb-2">
                          <h3 className="text-base font-semibold text-white">{phase.title}</h3>
                          <p className="mt-1 text-sm text-slate-500">{phase.subtitle}</p>
                          <ul className="mt-4 space-y-3">
                            {phase.steps.map((step, i) => (
                              <li
                                key={`${phase.title}-${step.title}`}
                                className="rounded-xl border border-white/8 bg-white/[0.03] px-4 py-3"
                              >
                                <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                                  Step {stepOffset + i + 1}
                                </p>
                                <p className="mt-1 font-medium text-slate-100">{step.title}</p>
                                <p className="mt-1 text-sm leading-relaxed text-slate-400">{step.body}</p>
                              </li>
                            ))}
                          </ul>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            <div>
              <p className="mb-3 px-1 text-[11px] font-semibold uppercase tracking-[0.2em] text-amber-200/55">Common pitfalls</p>
              <div className="grid gap-3 sm:grid-cols-2">
                {callouts.map(({ title, body, Icon }) => (
                  <div key={title} className="rounded-2xl border border-amber-200/14 bg-amber-300/[0.06] p-4">
                    <Icon className="text-amber-100/90" size={20} />
                    <p className="mt-3 text-sm font-semibold text-white">{title}</p>
                    <p className="mt-1 text-xs leading-relaxed text-slate-300">{body}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}

export default function OutlookSettingsPage() {
  return (
    <AuthGate>
      <OutlookSetupPageContent />
    </AuthGate>
  );
}
