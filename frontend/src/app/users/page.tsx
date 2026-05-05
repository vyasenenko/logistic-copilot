"use client";

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { ArrowLeft, Clock3, Loader2, MailPlus, ShieldCheck, Trash2, UserCog, Users, X } from "lucide-react";

import { AuthGate } from "@/components/AuthGate";
import { DashboardLogo } from "@/components/DashboardLogo";
import { PUBLIC_API_URL as API_URL } from "@/constants/publicApi";

const AUTH_TOKEN_KEY = "logistic_copilot_auth_token";

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

interface OrganizationMemberRecord {
  id: string;
  user_id: string;
  organization_id: string;
  email: string;
  name?: string | null;
  role: string;
  status: string;
  created_at: string;
  updated_at: string;
}

interface OrganizationInviteRecord {
  id: string;
  organization_id: string;
  email: string;
  role: string;
  status: string;
  expires_at: string;
  accepted_at?: string | null;
  created_at: string;
}

interface InviteResponse {
  id: string;
  organization_id: string;
  invite_token: string;
  email: string;
  role: string;
  expires_at: string;
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

function canManageUsers(user: CurrentUserResponse | null) {
  return Boolean(user?.permissions.includes("*") || user?.permissions.includes("members:invite"));
}

function emailDomain(email: string) {
  const normalized = email.trim().toLowerCase();
  return normalized.includes("@") ? normalized.split("@").pop() || "" : "";
}

/** Must stay in sync with backend FREE_EMAIL_DOMAINS (consumer mail → Viewer-only invites). */
const PERSONAL_EMAIL_DOMAINS = new Set([
  "gmail.com",
  "googlemail.com",
  "yahoo.com",
  "outlook.com",
  "hotmail.com",
  "live.com",
  "icloud.com",
  "me.com",
  "aol.com",
  "proton.me",
  "protonmail.com",
]);

function isPersonalEmailDomain(domain: string) {
  const d = domain.trim().toLowerCase();
  return Boolean(d && PERSONAL_EMAIL_DOMAINS.has(d));
}

function emailRequiresViewerOnly(domain: string, orgDomain: string) {
  const d = domain.trim().toLowerCase();
  const od = orgDomain.trim().toLowerCase();
  if (!d) return false;
  if (isPersonalEmailDomain(d)) return true;
  if (od && d !== od) return true;
  return false;
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function UserManagementContent() {
  const [me, setMe] = useState<CurrentUserResponse | null>(null);
  const [organization, setOrganization] = useState<OrganizationRecord | null>(null);
  const [members, setMembers] = useState<OrganizationMemberRecord[]>([]);
  const [invites, setInvites] = useState<OrganizationInviteRecord[]>([]);
  const [selectedMemberId, setSelectedMemberId] = useState<string | null>(null);
  const [selectedRole, setSelectedRole] = useState("member");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("member");
  const [invite, setInvite] = useState<InviteResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [memberAction, setMemberAction] = useState<"save" | "remove" | null>(null);
  const [revokingInviteId, setRevokingInviteId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const organizationDomain = organization?.primary_domain?.trim().toLowerCase() || "";
  const inviteDomain = emailDomain(email);
  const inviteRequiresViewerOnly = emailRequiresViewerOnly(inviteDomain, organizationDomain);
  const blockedViewerOnlyInvite = inviteRequiresViewerOnly && role !== "viewer";
  const selectedMember = members.find((member) => member.id === selectedMemberId) || null;
  const selectedMemberDomain = selectedMember ? emailDomain(selectedMember.email) : "";
  const selectedMemberRequiresViewerOnly = selectedMember
    ? emailRequiresViewerOnly(selectedMemberDomain, organizationDomain)
    : false;
  const selectedMemberReadOnly = !selectedMember || selectedMember.user_id === me?.user_id || selectedMember.role === "owner";
  const blockedSelectedRole = Boolean(selectedMemberRequiresViewerOnly && selectedRole !== "viewer");

  async function loadState() {
    setLoading(true);
    setError(null);
    try {
      const [meData, organizationData] = await Promise.all([
        apiFetch<CurrentUserResponse>("/api/auth/me"),
        apiFetch<OrganizationRecord>("/api/organizations/current"),
      ]);
      setMe(meData);
      setOrganization(organizationData);
      const allowed = canManageUsers(meData);
      if (allowed) {
        const [memberData, inviteData] = await Promise.all([
          apiFetch<OrganizationMemberRecord[]>("/api/auth/organization-members"),
          apiFetch<OrganizationInviteRecord[]>("/api/auth/invites?status=pending"),
        ]);
        setMembers(memberData);
        setInvites(inviteData);
        const nextSelected = selectedMemberId
          ? memberData.find((member) => member.id === selectedMemberId) || null
          : null;
        setSelectedMemberId(nextSelected?.id || null);
        setSelectedRole(nextSelected?.role || "member");
      } else {
        setMembers([]);
        setInvites([]);
        setSelectedMemberId(null);
        setSelectedRole("member");
      }
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load user management.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let mounted = true;
    async function load() {
      if (mounted) await loadState();
    }
    void load();
    return () => {
      mounted = false;
    };
  }, []);

  async function submitInvite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!me) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    setInvite(null);
    if (blockedViewerOnlyInvite) {
      setError("This email can only be invited with the Viewer role.");
      setSaving(false);
      return;
    }
    try {
      const response = await apiFetch<InviteResponse>("/api/auth/invites", {
        method: "POST",
        body: JSON.stringify({
          organization_id: me.organization_id,
          email: email.trim(),
          role,
        }),
      });
      setInvite(response);
      setNotice(`Invite created for ${response.email}.`);
      setEmail("");
      setRole("member");
      await loadState();
    } catch (inviteError) {
      setError(inviteError instanceof Error ? inviteError.message : "Failed to create invite.");
    } finally {
      setSaving(false);
    }
  }

  async function revokeInvite(inviteId: string, inviteEmail: string) {
    const token = typeof window !== "undefined" ? window.localStorage.getItem(AUTH_TOKEN_KEY) : null;
    if (!token) return;
    setRevokingInviteId(inviteId);
    setError(null);
    setNotice(null);
    try {
      const response = await fetch(`${API_URL}/api/auth/invites/${inviteId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        const detail = payload?.detail;
        throw new Error(typeof detail === "string" ? detail : `Request failed: ${response.status}`);
      }
      setNotice(`Invite revoked for ${inviteEmail}.`);
      const inviteData = await apiFetch<OrganizationInviteRecord[]>("/api/auth/invites?status=pending");
      setInvites(inviteData);
    } catch (revokeErr) {
      setError(revokeErr instanceof Error ? revokeErr.message : "Failed to revoke invite.");
    } finally {
      setRevokingInviteId(null);
    }
  }

  function selectMember(member: OrganizationMemberRecord) {
    setSelectedMemberId(member.id);
    setSelectedRole(member.role);
    setError(null);
    setNotice(null);
  }

  async function updateSelectedMemberRole() {
    if (!selectedMember) return;
    setMemberAction("save");
    setError(null);
    setNotice(null);
    try {
      const updated = await apiFetch<OrganizationMemberRecord>(`/api/auth/organization-members/${selectedMember.id}`, {
        method: "PATCH",
        body: JSON.stringify({ role: selectedRole }),
      });
      setNotice(`Updated ${updated.email} to ${updated.role}.`);
      setSelectedMemberId(updated.id);
      setSelectedRole(updated.role);
      await loadState();
    } catch (roleError) {
      setError(roleError instanceof Error ? roleError.message : "Failed to update user role.");
    } finally {
      setMemberAction(null);
    }
  }

  async function removeSelectedMember() {
    if (!selectedMember) return;
    const confirmed = window.confirm(`Remove organization access for ${selectedMember.email}?`);
    if (!confirmed) return;
    setMemberAction("remove");
    setError(null);
    setNotice(null);
    try {
      const removed = await apiFetch<OrganizationMemberRecord>(`/api/auth/organization-members/${selectedMember.id}`, {
        method: "DELETE",
      });
      setNotice(`Removed access for ${removed.email}.`);
      setSelectedMemberId(null);
      setSelectedRole("member");
      await loadState();
    } catch (removeError) {
      setError(removeError instanceof Error ? removeError.message : "Failed to remove user access.");
    } finally {
      setMemberAction(null);
    }
  }

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_10%_0%,rgba(84,210,255,0.14),transparent_30%),linear-gradient(180deg,#07111f,#060b13)] px-4 py-8 text-slate-100 sm:px-6 lg:px-8">
      <section className="mx-auto max-w-5xl space-y-6">
        <div className="rounded-[2rem] border border-cyan-200/12 bg-slate-950/62 p-6 shadow-2xl shadow-cyan-950/20 backdrop-blur">
          <Link href="/dashboard" className="mb-5 inline-flex items-center gap-2 text-sm text-cyan-100/75 transition hover:text-cyan-50">
            <ArrowLeft size={16} /> Back to dashboard
          </Link>
          <div className="flex flex-col justify-between gap-5 md:flex-row md:items-start">
            <div className="min-w-0 flex-1">
              <div className="mb-4 inline-flex items-center gap-3">
                <DashboardLogo className="h-9 w-9" />
                <span className="text-[11px] font-semibold uppercase tracking-[0.24em] text-cyan-100">Logistic Copilot</span>
              </div>
              <h1 className="text-3xl font-semibold tracking-[-0.05em] text-white sm:text-4xl">User management</h1>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300">
                Invite teammates into {organization?.name || "the current organization"}. Same-domain work emails can be
                Admin, Member, or Viewer. Personal email domains (Gmail, Yahoo, etc.) and addresses outside your
                organization domain can only be Viewer.
              </p>
            </div>
            <div className="w-full shrink-0 text-right md:ml-auto md:w-auto md:pt-1">
              <p className="text-[10px] uppercase tracking-[0.2em] text-slate-500">Signed in as</p>
              <p className="mt-1 truncate text-sm font-medium text-slate-200">{me?.email || "Loading..."}</p>
              <p className="mt-0.5 text-xs capitalize text-slate-500">{me?.role || "—"}</p>
            </div>
          </div>
        </div>

        {loading ? (
          <div className="rounded-[2rem] border border-white/10 bg-white/[0.04] p-6 text-sm text-slate-300">
            <Loader2 className="mr-2 inline animate-spin" size={17} /> Loading access...
          </div>
        ) : null}

        {!loading && !canManageUsers(me) ? (
          <div className="rounded-[2rem] border border-red-300/20 bg-red-400/10 p-6 text-red-100">
            <ShieldCheck className="mb-3" size={22} />
            You do not have permission to manage users for this organization.
          </div>
        ) : null}

        {!loading && canManageUsers(me) ? (
          <div className="grid gap-6 lg:grid-cols-[0.9fr_1.1fr]">
            <form onSubmit={(event) => void submitInvite(event)} className="rounded-[2rem] border border-white/10 bg-white/[0.045] p-6">
              <div className="mb-5 flex items-center gap-3">
                <MailPlus className="text-cyan-100" size={22} />
                <div>
                  <h2 className="text-xl font-semibold text-white">Invite user</h2>
                  <p className="mt-1 text-sm text-slate-400">
                    Organization domain: <span className="text-cyan-100">{organizationDomain || "not configured"}</span>
                  </p>
                </div>
              </div>
              <div className="space-y-4">
                <label className="block">
                  <span className="mb-2 block text-xs uppercase tracking-[0.18em] text-slate-400">Email</span>
                  <input
                    className="w-full rounded-2xl border border-white/10 bg-slate-950/70 px-4 py-3 text-sm text-white outline-none transition focus:border-cyan-200/45"
                    type="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    placeholder="teammate@company.com"
                    required
                  />
                  {inviteRequiresViewerOnly ? (
                    <p className="mt-2 rounded-2xl border border-amber-300/20 bg-amber-300/10 px-3 py-2 text-xs leading-5 text-amber-100">
                      Personal or external-domain address — this invite can only use the Viewer role.
                    </p>
                  ) : (
                    <p className="mt-2 text-xs leading-5 text-slate-500">
                      Same-domain work email: Admin, Member, or Viewer.
                    </p>
                  )}
                </label>
                <label className="block">
                  <span className="mb-2 block text-xs uppercase tracking-[0.18em] text-slate-400">Role</span>
                  <select
                    className="w-full rounded-2xl border border-white/10 bg-slate-950/70 px-4 py-3 text-sm text-white outline-none transition focus:border-cyan-200/45"
                    value={role}
                    onChange={(event) => setRole(event.target.value)}
                  >
                    <option value="member" disabled={inviteRequiresViewerOnly}>Member</option>
                    <option value="admin" disabled={inviteRequiresViewerOnly}>Admin</option>
                    <option value="viewer">Viewer</option>
                  </select>
                  {blockedViewerOnlyInvite && (
                    <p className="mt-2 text-xs text-red-200">Choose Viewer for this email address.</p>
                  )}
                </label>
                <button
                  className="inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-cyan-200 px-4 py-3 text-sm font-semibold text-slate-950 transition hover:bg-cyan-100 disabled:opacity-60"
                  disabled={saving || blockedViewerOnlyInvite}
                  type="submit"
                >
                  {saving ? <Loader2 className="animate-spin" size={17} /> : <Users size={17} />} Create invite
                </button>
              </div>
            </form>

            <div className="space-y-6">
              <section className="rounded-[2rem] border border-white/10 bg-white/[0.035] p-6">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <h2 className="text-xl font-semibold text-white">Current users</h2>
                    <p className="mt-1 text-sm text-slate-400">Active users in this organization.</p>
                  </div>
                  <Users className="text-cyan-100" size={22} />
                </div>
                <div className="mt-5 space-y-2">
                  {members.length === 0 ? (
                    <p className="rounded-2xl border border-dashed border-white/10 bg-white/[0.03] p-4 text-sm text-slate-400">
                      No users found.
                    </p>
                  ) : (
                    members.map((member) => (
                      <button
                        key={member.id}
                        type="button"
                        onClick={() => selectMember(member)}
                        className={`w-full rounded-2xl border px-4 py-3 text-left transition ${
                          selectedMemberId === member.id
                            ? "border-cyan-200/35 bg-cyan-200/10"
                            : "border-white/10 bg-slate-950/42 hover:border-white/18 hover:bg-white/[0.06]"
                        }`}
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div>
                            <p className="font-medium text-white">{member.name || member.email}</p>
                            <p className="text-xs text-slate-400">{member.email}</p>
                          </div>
                          <div className="flex flex-wrap justify-end gap-2">
                            <span className="rounded-full border border-cyan-200/14 bg-cyan-200/8 px-3 py-1 text-xs text-cyan-100">{member.role}</span>
                            <span className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-xs text-slate-300">{member.status}</span>
                          </div>
                        </div>
                        {member.user_id === me?.user_id && (
                          <p className="mt-2 text-xs text-slate-500">You cannot change your own role.</p>
                        )}
                        {emailRequiresViewerOnly(emailDomain(member.email), organizationDomain) && (
                          <p className="mt-2 text-xs text-amber-100">Personal or external-domain users can only be viewers.</p>
                        )}
                        <p className="mt-2 text-xs text-slate-500">Joined {formatDate(member.created_at)}</p>
                      </button>
                    ))
                  )}
                </div>
              </section>

              <section className="rounded-[2rem] border border-white/10 bg-white/[0.035] p-6">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <h2 className="text-xl font-semibold text-white">Pending invites</h2>
                    <p className="mt-1 text-sm text-slate-400">Invites that have not been accepted yet.</p>
                  </div>
                  <Clock3 className="text-cyan-100" size={22} />
                </div>
                <div className="mt-5 space-y-2">
                  {invites.length === 0 ? (
                    <p className="rounded-2xl border border-dashed border-white/10 bg-white/[0.03] p-4 text-sm text-slate-400">
                      No pending invites.
                    </p>
                  ) : (
                    invites.map((item) => (
                      <div
                        key={item.id}
                        className="group rounded-2xl border border-white/10 bg-slate-950/42 px-4 py-3"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="font-medium text-white">{item.email}</p>
                          <div className="flex flex-wrap items-center justify-end gap-2">
                            <span className="rounded-full border border-cyan-200/14 bg-cyan-200/8 px-3 py-1 text-xs text-cyan-100">{item.role}</span>
                            <span className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-xs text-slate-300">{item.status}</span>
                            {item.status === "pending" ? (
                              <button
                                type="button"
                                title="Revoke invite"
                                onClick={() => void revokeInvite(item.id, item.email)}
                                disabled={revokingInviteId !== null}
                                className="inline-flex shrink-0 items-center justify-center rounded-md p-1 text-slate-500 transition hover:bg-white/[0.06] hover:text-red-300/90 disabled:cursor-not-allowed disabled:opacity-25 opacity-50 md:opacity-0 md:group-hover:opacity-70 hover:opacity-100 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-cyan-400/35"
                                aria-label={`Revoke invite for ${item.email}`}
                              >
                                {revokingInviteId === item.id ? (
                                  <Loader2 className="animate-spin" size={12} />
                                ) : (
                                  <Trash2 size={12} strokeWidth={2} />
                                )}
                              </button>
                            ) : null}
                          </div>
                        </div>
                        <p className="mt-2 text-xs text-slate-500">Expires {formatDate(item.expires_at)}</p>
                      </div>
                    ))
                  )}
                </div>
              </section>

              <section className="rounded-[2rem] border border-white/10 bg-white/[0.035] p-6">
                <h2 className="text-xl font-semibold text-white">Invite result</h2>
                <p className="mt-2 text-sm leading-6 text-slate-400">
                  The generated token is single-use and should be sent through the invite email flow. This screen exposes it for operator testing.
                </p>
                {notice && <p className="mt-4 rounded-2xl border border-emerald-300/15 bg-emerald-300/10 px-4 py-3 text-sm text-emerald-100">{notice}</p>}
                {error && <p className="mt-4 rounded-2xl border border-red-300/20 bg-red-400/10 px-4 py-3 text-sm text-red-100">{error}</p>}
                {invite ? (
                  <div className="mt-4 space-y-3 rounded-2xl border border-cyan-200/12 bg-slate-950/45 p-4 text-sm">
                    <p className="text-white">{invite.email} · {invite.role}</p>
                    <p className="text-slate-400">Expires: {new Date(invite.expires_at).toLocaleString()}</p>
                    <p className="break-all rounded-xl bg-white/[0.04] p-3 font-mono text-xs text-cyan-100">{invite.invite_token}</p>
                  </div>
                ) : (
                  <div className="mt-4 rounded-2xl border border-dashed border-white/10 bg-white/[0.03] p-6 text-sm text-slate-400">
                    No invite created yet.
                  </div>
                )}
              </section>
            </div>
          </div>
        ) : null}
        {selectedMember ? (
          <div
            className="fixed inset-0 z-50 !mt-0 flex items-center justify-center bg-slate-950/75 px-4 py-6 backdrop-blur-sm"
            onClick={() => setSelectedMemberId(null)}
          >
            <div
              role="dialog"
              aria-modal="true"
              aria-labelledby="selected-user-title"
              onClick={(event) => event.stopPropagation()}
              className="w-full max-w-lg rounded-[2rem] border border-cyan-100/16 bg-[#081524] p-6 text-slate-100 shadow-2xl shadow-cyan-950/40"
            >
              <div className="mb-5 flex items-start justify-between gap-4">
                <div className="flex items-center gap-3">
                  <div className="rounded-2xl border border-cyan-100/12 bg-cyan-200/10 p-3">
                    <UserCog className="text-cyan-100" size={22} />
                  </div>
                  <div>
                    <h2 id="selected-user-title" className="text-xl font-semibold text-white">Manage user</h2>
                    <p className="mt-1 text-sm text-slate-400">Edit role or remove organization access.</p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setSelectedMemberId(null)}
                  className="rounded-full border border-white/10 bg-white/[0.04] p-2 text-slate-300 transition hover:bg-white/[0.08] hover:text-white"
                  aria-label="Close user management dialog"
                >
                  <X size={17} />
                </button>
              </div>

              <div className="space-y-4">
                <div className="rounded-2xl border border-white/10 bg-slate-950/42 p-4">
                  <p className="font-medium text-white">{selectedMember.name || selectedMember.email}</p>
                  <p className="mt-1 text-xs text-slate-400">{selectedMember.email}</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <span className="rounded-full border border-cyan-200/14 bg-cyan-200/8 px-3 py-1 text-xs text-cyan-100">{selectedMember.role}</span>
                    <span className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-xs text-slate-300">{selectedMember.status}</span>
                  </div>
                </div>
                <label className="block">
                  <span className="mb-2 block text-xs uppercase tracking-[0.18em] text-slate-400">Role</span>
                  <select
                    className="w-full rounded-2xl border border-white/10 bg-slate-950/70 px-4 py-3 text-sm text-white outline-none transition focus:border-cyan-200/45 disabled:opacity-50"
                    value={selectedRole}
                    onChange={(event) => setSelectedRole(event.target.value)}
                    disabled={selectedMemberReadOnly}
                  >
                    <option value="admin" disabled={selectedMemberRequiresViewerOnly}>Admin</option>
                    <option value="member" disabled={selectedMemberRequiresViewerOnly}>Member</option>
                    <option value="viewer">Viewer</option>
                    {selectedMember.role === "owner" && <option value="owner">Owner</option>}
                  </select>
                  {selectedMember.user_id === me?.user_id && (
                    <p className="mt-2 text-xs text-slate-500">You cannot change your own role or remove your own access.</p>
                  )}
                  {selectedMember.role === "owner" && (
                    <p className="mt-2 text-xs text-slate-500">Owner access is managed outside this screen.</p>
                  )}
                  {selectedMemberRequiresViewerOnly && (
                    <p className="mt-2 text-xs text-amber-100">This user can only have the Viewer role.</p>
                  )}
                  {blockedSelectedRole && (
                    <p className="mt-2 text-xs text-red-200">Switch role to Viewer before saving.</p>
                  )}
                </label>
                <div className="grid gap-2 sm:grid-cols-2">
                  <button
                    type="button"
                    onClick={() => void updateSelectedMemberRole()}
                    disabled={
                      memberAction !== null ||
                      selectedMemberReadOnly ||
                      blockedSelectedRole ||
                      selectedRole === selectedMember.role
                    }
                    className="inline-flex items-center justify-center gap-2 rounded-2xl border border-cyan-200/16 bg-cyan-300/10 px-4 py-3 text-sm font-semibold text-cyan-50 transition hover:bg-cyan-300/16 disabled:opacity-50"
                  >
                    {memberAction === "save" ? <Loader2 className="animate-spin" size={16} /> : null}
                    Save role
                  </button>
                  <button
                    type="button"
                    onClick={() => void removeSelectedMember()}
                    disabled={memberAction !== null || selectedMemberReadOnly}
                    className="inline-flex items-center justify-center gap-2 rounded-2xl border border-red-300/20 bg-red-400/10 px-4 py-3 text-sm font-semibold text-red-100 transition hover:bg-red-400/16 disabled:opacity-50"
                  >
                    {memberAction === "remove" ? <Loader2 className="animate-spin" size={16} /> : <Trash2 size={16} />}
                    Remove access
                  </button>
                </div>
              </div>
            </div>
          </div>
        ) : null}
      </section>
    </main>
  );
}

export default function UsersPage() {
  return (
    <AuthGate>
      <UserManagementContent />
    </AuthGate>
  );
}
