"use client";

import type { FormEvent } from "react";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowRight, LockKeyhole, ShieldCheck, UserRound } from "lucide-react";
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
        },
      ) => string;
      reset: (widgetId?: string) => void;
    };
  }
}

async function readAcceptError(response: Response): Promise<string> {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    const payload = await response.json().catch(() => null);
    const detail = payload?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length > 0) {
      const firstMessage = detail.map((item) => (typeof item?.msg === "string" ? item.msg : "")).find(Boolean);
      return firstMessage || "Please check the form and try again.";
    }
  }
  const message = await response.text().catch(() => "");
  return message || "We could not complete your invitation. Please try again.";
}

export function InviteAcceptClient() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token")?.trim() ?? "";
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [turnstileToken, setTurnstileToken] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const turnstileRef = useRef<HTMLDivElement | null>(null);
  const widgetIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (!TURNSTILE_SITE_KEY || !token) return;

    const renderWidget = () => {
      if (!turnstileRef.current || !window.turnstile || widgetIdRef.current) return;
      widgetIdRef.current = window.turnstile.render(turnstileRef.current, {
        sitekey: TURNSTILE_SITE_KEY,
        theme: TURNSTILE_THEME,
        language: TURNSTILE_LANGUAGE,
        size: TURNSTILE_SIZE,
        callback: (t) => setTurnstileToken(t),
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
  }, [token]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);
    try {
      const response = await fetch(`${API_URL}/api/auth/invites/accept`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          token,
          name: name.trim() || null,
          password,
          turnstile_token: turnstileToken || null,
        }),
      });
      if (!response.ok) {
        throw new Error(await readAcceptError(response));
      }
      const payload = await response.json();
      window.localStorage.setItem(AUTH_TOKEN_KEY, payload.access_token);
      router.push("/dashboard");
    } catch (acceptError) {
      let message = acceptError instanceof Error ? acceptError.message : "Invitation acceptance failed.";
      if (message.toLowerCase().includes("turnstile") && !TURNSTILE_SITE_KEY) {
        message =
          "Server requires Turnstile, but this frontend build has no NEXT_PUBLIC_TURNSTILE_SITE_KEY.";
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

  if (!token) {
    return (
      <main className="min-h-screen overflow-hidden bg-[#07111f] px-4 py-10 text-slate-100 sm:px-6">
        <div className="mx-auto max-w-lg rounded-[2rem] border border-white/12 bg-slate-950/72 p-8 backdrop-blur-xl">
          <DashboardLogo className="mx-auto mb-6 block h-12 w-12 object-contain" />
          <h1 className="text-center text-xl font-semibold text-white">Missing invitation link</h1>
          <p className="mt-3 text-center text-sm leading-6 text-slate-400">
            Open the invitation link from your email, or ask your admin to resend the invite.
          </p>
          <Link
            href="/"
            className="mt-6 flex items-center justify-center gap-2 rounded-2xl border border-cyan-200/30 bg-cyan-300/20 px-5 py-3 text-sm font-semibold text-cyan-50 transition hover:bg-cyan-300/30"
          >
            Back to sign in
            <ArrowRight size={16} />
          </Link>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen overflow-hidden bg-[#07111f] px-4 py-6 text-slate-100 sm:px-6 lg:px-8">
      <div className="mx-auto flex min-h-[calc(100vh-3rem)] max-w-lg flex-col justify-center">
        <div className="rounded-[2rem] border border-white/12 bg-slate-950/72 p-6 shadow-2xl shadow-slate-950/40 backdrop-blur-xl sm:p-8">
          <div className="mb-6 flex items-start justify-between gap-4">
            <div className="flex items-start gap-4">
              <DashboardLogo className="h-11 w-11 shrink-0 object-contain sm:h-12 sm:w-12" />
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-amber-100">Invitation</p>
                <h1 className="mt-2 text-2xl font-semibold tracking-tight text-white">Accept invite</h1>
                <p className="mt-1 text-sm text-slate-400">Create your password to join the workspace.</p>
              </div>
            </div>
            <div className="rounded-2xl border border-emerald-200/20 bg-emerald-300/10 p-3 text-emerald-100">
              <ShieldCheck size={22} />
            </div>
          </div>

          <form className="space-y-4" onSubmit={(e) => void handleSubmit(e)}>
            <label className="block">
              <span className="text-xs font-medium uppercase tracking-[0.16em] text-slate-400">
                Display name <span className="normal-case text-slate-500">(optional)</span>
              </span>
              <div className="mt-2 flex items-center gap-3 rounded-2xl border border-white/10 bg-slate-900/80 px-4 py-3 transition focus-within:border-cyan-300/60">
                <UserRound size={17} className="text-slate-500" />
                <input
                  className="w-full bg-transparent text-sm text-slate-100 outline-none placeholder:text-slate-600"
                  type="text"
                  autoComplete="name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Jordan Lee"
                />
              </div>
            </label>

            <label className="block">
              <span className="text-xs font-medium uppercase tracking-[0.16em] text-slate-400">
                Password <span className="text-slate-500">(min. 10 characters)</span>
              </span>
              <div className="mt-2 flex items-center gap-3 rounded-2xl border border-white/10 bg-slate-900/80 px-4 py-3 transition focus-within:border-cyan-300/60">
                <LockKeyhole size={17} className="text-slate-500" />
                <input
                  className="w-full bg-transparent text-sm text-slate-100 outline-none placeholder:text-slate-600"
                  type="password"
                  autoComplete="new-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="Choose a strong password"
                  required
                  minLength={10}
                  maxLength={200}
                />
              </div>
            </label>

            {TURNSTILE_SITE_KEY ? <div ref={turnstileRef} /> : null}

            {error ? (
              <div className="rounded-2xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-100">{error}</div>
            ) : null}

            <button
              className="group flex w-full items-center justify-center gap-2 rounded-2xl border border-cyan-200/30 bg-cyan-300/20 px-5 py-3 text-sm font-semibold text-cyan-50 transition hover:bg-cyan-300/30 disabled:cursor-not-allowed disabled:opacity-60"
              type="submit"
              disabled={isSubmitting || (!!TURNSTILE_SITE_KEY && !turnstileToken)}
            >
              {isSubmitting ? "Creating account…" : "Accept & enter dashboard"}
              {!isSubmitting ? <ArrowRight size={16} className="transition group-hover:translate-x-0.5" /> : null}
            </button>

            <p className="text-center text-xs text-slate-500">
              <Link href="/" className="text-cyan-200/80 underline-offset-2 hover:underline">
                Already have an account? Sign in
              </Link>
            </p>
          </form>
        </div>
      </div>
    </main>
  );
}
