"use client";

import type { FormEvent } from "react";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, LockKeyhole, Mail, ShieldCheck, Sparkles } from "lucide-react";
import { DashboardLogo } from "@/components/DashboardLogo";
import { PUBLIC_API_URL as API_URL } from "@/constants/publicApi";
const AUTH_TOKEN_KEY = "logistic_copilot_auth_token";
const TURNSTILE_SITE_KEY = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY || "";
const TURNSTILE_THEME = (process.env.NEXT_PUBLIC_TURNSTILE_THEME || "light") as "light" | "dark" | "auto";
const TURNSTILE_LANGUAGE = process.env.NEXT_PUBLIC_TURNSTILE_LANGUAGE || "en";
const TURNSTILE_SIZE = (process.env.NEXT_PUBLIC_TURNSTILE_SIZE || "flexible") as "normal" | "flexible" | "compact";

declare global {
  interface Window {
    turnstile?: {
      render: (
        element: HTMLElement,
        options: {
          sitekey: string;
          callback: (token: string) => void;
          "expired-callback"?: () => void;
          "error-callback"?: () => void;
          theme?: "light" | "dark" | "auto";
          language?: string;
          size?: "normal" | "flexible" | "compact";
          appearance?: "always" | "execute" | "interaction-only";
        }
      ) => string;
      reset: (widgetId?: string) => void;
    };
  }
}

async function readLoginError(response: Response): Promise<string> {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    const payload = await response.json().catch(() => null);
    const detail = payload?.detail;
    if (typeof detail === "string") {
      if (detail.toLowerCase().includes("invalid credentials")) {
        return "Invalid email or password.";
      }
      return detail;
    }
    if (Array.isArray(detail) && detail.length > 0) {
      const firstMessage = detail
        .map((item) => (typeof item?.msg === "string" ? item.msg : ""))
        .find(Boolean);
      return firstMessage || "Please check the form and try again.";
    }
  }

  const message = await response.text().catch(() => "");
  if (message.toLowerCase().includes("invalid credentials")) {
    return "Invalid email or password.";
  }
  return message || "We could not sign you in. Please try again.";
}

export function HeroLogin() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [turnstileToken, setTurnstileToken] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [hasSession, setHasSession] = useState(false);
  const turnstileRef = useRef<HTMLDivElement | null>(null);
  const widgetIdRef = useRef<string | null>(null);

  useEffect(() => {
    const token = window.localStorage.getItem(AUTH_TOKEN_KEY);
    if (!token) return;

    fetch(`${API_URL}/api/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((response) => {
        if (!response.ok) throw new Error("Expired session");
        setHasSession(true);
      })
      .catch(() => {
        window.localStorage.removeItem(AUTH_TOKEN_KEY);
        setHasSession(false);
      });
  }, []);

  useEffect(() => {
    if (!TURNSTILE_SITE_KEY || hasSession) return;

    const renderWidget = () => {
      if (!turnstileRef.current || !window.turnstile || widgetIdRef.current) return;
      widgetIdRef.current = window.turnstile.render(turnstileRef.current, {
        sitekey: TURNSTILE_SITE_KEY,
        theme: TURNSTILE_THEME,
        language: TURNSTILE_LANGUAGE,
        size: TURNSTILE_SIZE,
        callback: (token) => setTurnstileToken(token),
        "expired-callback": () => setTurnstileToken(""),
        "error-callback": () => setTurnstileToken(""),
      });
    };

    if (window.turnstile) {
      renderWidget();
      return;
    }

    const script = document.createElement("script");
    script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
    script.async = true;
    script.defer = true;
    script.onload = renderWidget;
    document.body.appendChild(script);
  }, [hasSession]);

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);
    try {
      const response = await fetch(`${API_URL}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email,
          password,
          turnstile_token: turnstileToken || null,
        }),
      });
      if (!response.ok) {
        throw new Error(await readLoginError(response));
      }
      const payload = await response.json();
      window.localStorage.setItem(AUTH_TOKEN_KEY, payload.access_token);
      const searchParams = new URLSearchParams(window.location.search);
      const next = searchParams.get("next") || "/dashboard";
      router.push(next.startsWith("/") && !next.startsWith("//") ? next : "/dashboard");
    } catch (loginError) {
      let message = loginError instanceof Error ? loginError.message : "Login failed";
      if (
        message.toLowerCase().includes("turnstile") &&
        !TURNSTILE_SITE_KEY
      ) {
        message =
          "Server requires Turnstile, but this frontend build has no NEXT_PUBLIC_TURNSTILE_SITE_KEY. Rebuild the Docker image with the Cloudflare site key (see README / Makefile).";
      }
      setError(message);
      if (window.turnstile && widgetIdRef.current) {
        window.turnstile.reset(widgetIdRef.current);
        setTurnstileToken("");
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="min-h-screen overflow-hidden bg-[#07111f] px-4 py-6 text-slate-100 sm:px-6 lg:px-8">
      <section className="relative mx-auto grid min-h-[calc(100vh-3rem)] w-full max-w-7xl items-center gap-8 overflow-hidden rounded-[2.25rem] border border-white/10 bg-[linear-gradient(135deg,_rgba(15,23,42,0.98),_rgba(8,47,73,0.72)_48%,_rgba(28,25,23,0.96))] p-5 shadow-2xl shadow-cyan-950/30 sm:p-8 lg:grid-cols-[1.1fr_0.9fr] lg:p-12">
        <div className="pointer-events-none absolute -left-24 top-12 h-72 w-72 rounded-full bg-cyan-300/20 blur-3xl" />
        <div className="pointer-events-none absolute bottom-0 right-0 h-80 w-80 rounded-full bg-amber-200/16 blur-3xl" />
        <div className="pointer-events-none absolute left-[42%] top-[-12%] h-64 w-64 rounded-full bg-emerald-300/10 blur-3xl" />

        <div className="relative z-10 max-w-3xl">
          <div className="mb-8 flex items-center gap-4">
            <DashboardLogo className="h-14 w-14 object-contain sm:h-16 sm:w-16" />
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-cyan-200">
                Logistic Copilot
              </p>
              <p className="mt-1 text-sm text-slate-400">Freight automation</p>
            </div>
          </div>

          <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-cyan-200/25 bg-cyan-300/10 px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-cyan-100">
            <Sparkles size={14} />
            AI inbox to shipment control tower
          </div>

          <h1 className="max-w-4xl text-5xl font-semibold tracking-tight text-slate-50 sm:text-6xl lg:text-7xl">
            Turn freight email chaos into a controlled operating flow.
          </h1>
          <p className="mt-6 max-w-2xl text-base leading-8 text-slate-300 sm:text-lg">
            Quote intake, carrier replies, booking handoff, status workflows, and operator review
            in one organization-scoped command center.
          </p>

          <div className="mt-9 grid max-w-2xl gap-3 sm:grid-cols-3">
            {[
              ["Inbox AI", "Classifies logistics emails"],
              ["Anti-fraud", "Flags risky email and carriers"],
              ["Ops Queue", "Human control where needed"],
            ].map(([title, body]) => (
              <div key={title} className="rounded-3xl border border-white/10 bg-white/[0.04] p-4">
                <p className="text-sm font-semibold text-slate-100">{title}</p>
                <p className="mt-1 text-xs leading-5 text-slate-400">{body}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="relative z-10 mx-auto w-full max-w-md">
          <div className="rounded-[2rem] border border-white/12 bg-slate-950/72 p-6 shadow-2xl shadow-slate-950/40 backdrop-blur-xl sm:p-7">
            <div className="mb-6 flex items-start justify-between gap-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-amber-100">
                  Secure access
                </p>
                <h2 className="mt-2 text-2xl font-semibold tracking-tight">Sign in to dashboard</h2>
              </div>
              <div className="rounded-2xl border border-emerald-200/20 bg-emerald-300/10 p-3 text-emerald-100">
                <ShieldCheck size={22} />
              </div>
            </div>

            {hasSession ? (
              <button
                className="group flex w-full items-center justify-center gap-2 rounded-2xl border border-cyan-200/30 bg-cyan-300/20 px-5 py-3 text-sm font-semibold text-cyan-50 transition hover:bg-cyan-300/30"
                onClick={() => router.push("/dashboard")}
                type="button"
              >
                Continue to dashboard
                <ArrowRight size={16} className="transition group-hover:translate-x-0.5" />
              </button>
            ) : (
              <form className="space-y-4" onSubmit={handleLogin}>
                <label className="block">
                  <span className="text-xs font-medium uppercase tracking-[0.16em] text-slate-400">
                    Business email
                  </span>
                  <div className="mt-2 flex items-center gap-3 rounded-2xl border border-white/10 bg-slate-900/80 px-4 py-3 transition focus-within:border-cyan-300/60">
                    <Mail size={17} className="text-slate-500" />
                    <input
                      className="w-full bg-transparent text-sm text-slate-100 outline-none placeholder:text-slate-600"
                      type="email"
                      autoComplete="email"
                      value={email}
                      onChange={(event) => setEmail(event.target.value)}
                      placeholder="dispatcher@company.com"
                      required
                    />
                  </div>
                </label>

                <label className="block">
                  <span className="text-xs font-medium uppercase tracking-[0.16em] text-slate-400">
                    Password
                  </span>
                  <div className="mt-2 flex items-center gap-3 rounded-2xl border border-white/10 bg-slate-900/80 px-4 py-3 transition focus-within:border-cyan-300/60">
                    <LockKeyhole size={17} className="text-slate-500" />
                    <input
                      className="w-full bg-transparent text-sm text-slate-100 outline-none placeholder:text-slate-600"
                      type="password"
                      autoComplete="current-password"
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      placeholder="Your password"
                      required
                    />
                  </div>
                </label>

                {TURNSTILE_SITE_KEY ? <div ref={turnstileRef} /> : null}

                {error ? (
                  <div className="rounded-2xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-100">
                    {error}
                  </div>
                ) : null}

                <button
                  className="group flex w-full items-center justify-center gap-2 rounded-2xl border border-cyan-200/30 bg-cyan-300/20 px-5 py-3 text-sm font-semibold text-cyan-50 transition hover:bg-cyan-300/30 disabled:cursor-not-allowed disabled:opacity-60"
                  type="submit"
                  disabled={isSubmitting || (!!TURNSTILE_SITE_KEY && !turnstileToken)}
                >
                  {isSubmitting ? "Signing in..." : "Enter dashboard"}
                  {!isSubmitting ? (
                    <ArrowRight size={16} className="transition group-hover:translate-x-0.5" />
                  ) : null}
                </button>
              </form>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}
