"use client";

import type { FormEvent } from "react";
import { useEffect, useState } from "react";
import { Building2, MailPlus, RefreshCw, ShieldCheck, Users } from "lucide-react";
import { PUBLIC_API_URL as API_URL } from "@/constants/publicApi";

const AUTH_TOKEN_KEY = "logistic_copilot_auth_token";

interface AdminOverview {
  organizations_count: number;
  users_count: number;
  pending_access_requests_count: number;
  pending_invites_count: number;
  active_email_connections_count: number;
  shipments_count: number;
  workflow_events_count: number;
}

interface AdminOrganization {
  id: string;
  name: string;
  primary_domain: string | null;
  status: string;
  members_count: number;
  email_connections_count: number;
  active_shipments_count: number;
  shipments_count: number;
  workflow_events_count: number;
}

interface AccessRequest {
  id: string;
  email: string;
  company_name: string;
  domain: string | null;
  status: string;
  created_at: string;
}

interface AdminInvite {
  id: string;
  organization_name: string | null;
  email: string;
  role: string;
  status: string;
  expires_at: string;
}

interface InviteResponse {
  invite_token: string;
  email: string;
  organization_id: string;
  expires_at: string;
}

async function adminFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = window.localStorage.getItem(AUTH_TOKEN_KEY);
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function metricLabel(value: number) {
  return new Intl.NumberFormat("en").format(value || 0);
}

export function AdminConsole() {
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [organizations, setOrganizations] = useState<AdminOrganization[]>([]);
  const [accessRequests, setAccessRequests] = useState<AccessRequest[]>([]);
  const [invites, setInvites] = useState<AdminInvite[]>([]);
  const [organizationName, setOrganizationName] = useState("");
  const [organizationDomain, setOrganizationDomain] = useState("");
  const [ownerEmail, setOwnerEmail] = useState("");
  const [inviteToken, setInviteToken] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isCreating, setIsCreating] = useState(false);

  async function loadAdminState() {
    setError("");
    setIsLoading(true);
    try {
      const [overviewData, orgData, accessData, inviteData] = await Promise.all([
        adminFetch<AdminOverview>("/api/admin/overview"),
        adminFetch<AdminOrganization[]>("/api/admin/organizations"),
        adminFetch<AccessRequest[]>("/api/admin/access-requests?include_resolved=true"),
        adminFetch<AdminInvite[]>("/api/admin/invites?include_accepted=true"),
      ]);
      setOverview(overviewData);
      setOrganizations(orgData);
      setAccessRequests(accessData);
      setInvites(inviteData);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load admin console.");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    loadAdminState();
  }, []);

  async function createOrganizationInvite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setInviteToken("");
    setIsCreating(true);
    try {
      const payload = await adminFetch<InviteResponse>("/api/admin/organizations/invite-owner", {
        method: "POST",
        body: JSON.stringify({
          organization_name: organizationName,
          organization_domain: organizationDomain,
          owner_email: ownerEmail,
          role: "owner",
        }),
      });
      setInviteToken(payload.invite_token);
      setOrganizationName("");
      setOrganizationDomain("");
      setOwnerEmail("");
      await loadAdminState();
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : "Failed to create invite.");
    } finally {
      setIsCreating(false);
    }
  }

  return (
    <main className="min-h-screen bg-[#07111f] px-4 py-6 text-slate-100 sm:px-6 lg:px-8">
      <section className="mx-auto max-w-7xl">
        <div className="mb-6 flex flex-col justify-between gap-4 rounded-[2rem] border border-white/10 bg-slate-950/70 p-6 shadow-2xl shadow-cyan-950/20 backdrop-blur sm:flex-row sm:items-center">
          <div>
            <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-amber-200/25 bg-amber-300/10 px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-amber-100">
              <ShieldCheck size={14} />
              Platform admin
            </div>
            <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
              Logistic Copilot Admin
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">
              Create customer organizations, issue owner invites, and monitor platform activity.
            </p>
          </div>
          <button
            className="inline-flex items-center justify-center gap-2 rounded-2xl border border-cyan-200/30 bg-cyan-300/15 px-4 py-3 text-sm font-semibold text-cyan-50 transition hover:bg-cyan-300/25"
            onClick={loadAdminState}
            type="button"
          >
            <RefreshCw size={16} />
            Refresh
          </button>
        </div>

        {error ? (
          <div className="mb-6 rounded-2xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-100">
            {error}
          </div>
        ) : null}

        <div className="grid gap-4 md:grid-cols-4">
          {[
            ["Organizations", overview?.organizations_count || 0, Building2],
            ["Users", overview?.users_count || 0, Users],
            ["Pending invites", overview?.pending_invites_count || 0, MailPlus],
            ["Shipments", overview?.shipments_count || 0, RefreshCw],
          ].map(([label, value, Icon]) => {
            const MetricIcon = Icon as typeof Building2;
            return (
              <div key={String(label)} className="rounded-[1.5rem] border border-white/10 bg-white/[0.04] p-5">
                <MetricIcon className="mb-4 text-cyan-100" size={22} />
                <p className="text-2xl font-semibold text-slate-50">{metricLabel(Number(value))}</p>
                <p className="mt-1 text-xs uppercase tracking-[0.16em] text-slate-500">{String(label)}</p>
              </div>
            );
          })}
        </div>

        <div className="mt-6 grid gap-6 lg:grid-cols-[0.9fr_1.1fr]">
          <form
            className="rounded-[2rem] border border-white/10 bg-slate-950/65 p-6 shadow-xl shadow-slate-950/30"
            onSubmit={createOrganizationInvite}
          >
            <h2 className="text-xl font-semibold">Create organization invite</h2>
            <p className="mt-2 text-sm leading-6 text-slate-400">
              This creates or updates the organization and generates an owner invite token.
            </p>
            <div className="mt-5 space-y-4">
              <input
                className="w-full rounded-2xl border border-white/10 bg-slate-900/80 px-4 py-3 text-sm outline-none focus:border-cyan-300/60"
                placeholder="Organization name"
                value={organizationName}
                onChange={(event) => setOrganizationName(event.target.value)}
                required
              />
              <input
                className="w-full rounded-2xl border border-white/10 bg-slate-900/80 px-4 py-3 text-sm outline-none focus:border-cyan-300/60"
                placeholder="company.com"
                value={organizationDomain}
                onChange={(event) => setOrganizationDomain(event.target.value)}
                required
              />
              <input
                className="w-full rounded-2xl border border-white/10 bg-slate-900/80 px-4 py-3 text-sm outline-none focus:border-cyan-300/60"
                placeholder="owner@company.com"
                type="email"
                value={ownerEmail}
                onChange={(event) => setOwnerEmail(event.target.value)}
                required
              />
              <button
                className="w-full rounded-2xl border border-emerald-200/30 bg-emerald-300/15 px-4 py-3 text-sm font-semibold text-emerald-50 transition hover:bg-emerald-300/25 disabled:opacity-60"
                disabled={isCreating}
                type="submit"
              >
                {isCreating ? "Creating..." : "Create owner invite"}
              </button>
            </div>
            {inviteToken ? (
              <div className="mt-5 rounded-2xl border border-cyan-200/25 bg-cyan-300/10 p-4">
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-100">
                  Invite token
                </p>
                <p className="mt-2 break-all text-sm text-slate-100">{inviteToken}</p>
              </div>
            ) : null}
          </form>

          <div className="rounded-[2rem] border border-white/10 bg-slate-950/65 p-6 shadow-xl shadow-slate-950/30">
            <h2 className="text-xl font-semibold">Organizations</h2>
            <div className="mt-5 space-y-3">
              {isLoading ? <p className="text-sm text-slate-400">Loading...</p> : null}
              {organizations.map((org) => (
                <div key={org.id} className="rounded-2xl border border-white/10 bg-white/[0.04] p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="font-semibold text-slate-50">{org.name}</p>
                      <p className="mt-1 text-xs text-slate-400">{org.primary_domain || "No domain"}</p>
                    </div>
                    <span className="rounded-full border border-emerald-200/20 bg-emerald-300/10 px-3 py-1 text-xs text-emerald-100">
                      {org.status}
                    </span>
                  </div>
                  <p className="mt-3 text-xs text-slate-500">
                    {org.members_count} users · {org.email_connections_count} inboxes ·{" "}
                    {org.active_shipments_count} active shipments · {org.workflow_events_count} events
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="mt-6 grid gap-6 lg:grid-cols-2">
          <div className="rounded-[2rem] border border-white/10 bg-slate-950/65 p-6">
            <h2 className="text-xl font-semibold">Access requests</h2>
            <div className="mt-4 space-y-3">
              {accessRequests.slice(0, 8).map((item) => (
                <div key={item.id} className="rounded-2xl border border-white/10 bg-white/[0.04] p-4">
                  <p className="font-medium">{item.company_name}</p>
                  <p className="mt-1 text-sm text-slate-400">{item.email}</p>
                  <p className="mt-2 text-xs uppercase tracking-[0.14em] text-slate-500">{item.status}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-[2rem] border border-white/10 bg-slate-950/65 p-6">
            <h2 className="text-xl font-semibold">Invites</h2>
            <div className="mt-4 space-y-3">
              {invites.slice(0, 8).map((item) => (
                <div key={item.id} className="rounded-2xl border border-white/10 bg-white/[0.04] p-4">
                  <p className="font-medium">{item.email}</p>
                  <p className="mt-1 text-sm text-slate-400">{item.organization_name || "Unknown org"}</p>
                  <p className="mt-2 text-xs uppercase tracking-[0.14em] text-slate-500">
                    {item.role} · {item.status}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
