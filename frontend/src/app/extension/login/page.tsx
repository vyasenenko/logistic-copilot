"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowRight, Loader2, ShieldCheck } from "lucide-react";
import { PUBLIC_API_URL as API_URL } from "@/constants/publicApi";

const AUTH_TOKEN_KEY = "logistic_copilot_auth_token";

export default function ExtensionLoginPage() {
  const [status, setStatus] = useState<"working" | "needs_login" | "error">("working");
  const [message, setMessage] = useState("Preparing secure extension sign-in...");

  const currentPath = useMemo(() => {
    if (typeof window === "undefined") return "/extension/login";
    return `${window.location.pathname}${window.location.search}`;
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function authorize() {
      const params = new URLSearchParams(window.location.search);
      const redirectUri = params.get("redirect_uri") || "";
      const state = params.get("state") || "";
      if (!redirectUri || !state) {
        setStatus("error");
        setMessage("Missing extension redirect parameters. Please start sign-in from the Chrome extension.");
        return;
      }
      const token = window.localStorage.getItem(AUTH_TOKEN_KEY);
      if (!token) {
        setStatus("needs_login");
        setMessage("Sign in to Logistic Copilot first, then we will connect the extension automatically.");
        return;
      }
      try {
        const response = await fetch(`${API_URL}/api/auth/extension/authorize`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ redirect_uri: redirectUri, state }),
        });
        if (response.status === 401 || response.status === 403) {
          window.localStorage.removeItem(AUTH_TOKEN_KEY);
          setStatus("needs_login");
          setMessage("Your web session expired. Sign in again to connect the extension.");
          return;
        }
        if (!response.ok) {
          const text = await response.text().catch(() => "");
          throw new Error(text || `HTTP ${response.status}`);
        }
        const payload = await response.json();
        if (!cancelled) {
          window.location.href = payload.redirect_url;
        }
      } catch (error) {
        if (!cancelled) {
          setStatus("error");
          setMessage(error instanceof Error ? error.message : "Extension authorization failed.");
        }
      }
    }

    void authorize();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="min-h-screen bg-[#07111f] px-6 py-10 text-slate-100">
      <section className="mx-auto flex min-h-[calc(100vh-5rem)] max-w-2xl items-center justify-center">
        <div className="w-full rounded-[2rem] border border-white/12 bg-slate-950/70 p-8 shadow-2xl shadow-cyan-950/30">
          <div className="mb-6 inline-flex h-14 w-14 items-center justify-center rounded-2xl border border-cyan-200/20 bg-cyan-200/10 text-cyan-100">
            {status === "working" ? <Loader2 className="animate-spin" size={24} /> : <ShieldCheck size={24} />}
          </div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-200">
            Chrome extension access
          </p>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight">
            Connect Logistic Copilot Agent
          </h1>
          <p className="mt-4 text-sm leading-6 text-slate-300">{message}</p>

          {status === "needs_login" ? (
            <Link
              href={`/?next=${encodeURIComponent(currentPath)}`}
              className="mt-7 inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-cyan-200 px-4 py-3 text-sm font-semibold text-slate-950 transition hover:bg-cyan-100"
            >
              Sign in and continue
              <ArrowRight size={16} />
            </Link>
          ) : null}

          {status === "error" ? (
            <p className="mt-6 rounded-2xl border border-red-300/30 bg-red-500/10 px-4 py-3 text-sm text-red-100">
              Please close this tab and start sign-in again from the extension.
            </p>
          ) : null}
        </div>
      </section>
    </main>
  );
}
