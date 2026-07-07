"use client";

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import {
  ArrowRight,
  BookOpen,
  ExternalLink,
  Github,
  Inbox,
  Mail,
  Package2,
  Puzzle,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Truck,
} from "lucide-react";
import { DashboardLogo } from "@/components/DashboardLogo";
import { PRODUCT_DISPLAY_NAME } from "@/constants/brand";
import { CHROME_WEB_STORE_LOGISTIC_COPILOT_URL } from "@/constants/chromeExtension";
import { PUBLIC_API_URL as API_URL } from "@/constants/publicApi";
import { LandingProductCta } from "@/components/landing/LandingProductCta";
import { LandingProductPreview } from "@/components/landing/LandingProductPreview";
import { LoginPanel, AUTH_TOKEN_KEY } from "@/components/landing/LoginPanel";
import {
  FAQ_ITEMS,
  FEATURES,
  FINAL_CTA_HEADLINE,
  FINAL_CTA_SUBCOPY,
  FOOTER_TAGLINE,
  HERO_BADGE,
  HERO_HEADLINE,
  HERO_PILLS,
  HERO_SUBCOPY,
  EXTENSION_SECTION,
  INTEGRATIONS,
  LANDING_NAV,
  OPEN_SOURCE_SECTION,
  PAIN_ITEMS,
  TRUST_POINTS,
  WORKFLOW_STEPS,
} from "@/components/landing/landing-content";

const FEATURE_ICONS = [Inbox, Package2, BookOpen, ShieldCheck, Truck, Mail] as const;

function SectionEyebrow({ children }: { children: ReactNode }) {
  return (
    <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-cyan-200/60">{children}</p>
  );
}

function SectionTitle({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <h2 className={`mt-3 max-w-2xl text-2xl font-semibold tracking-[-0.03em] text-white sm:text-[2rem] sm:leading-tight ${className}`}>
      {children}
    </h2>
  );
}

export function MarketingLanding() {
  const [hasSession, setHasSession] = useState(false);
  const [sessionChecked, setSessionChecked] = useState(false);

  useEffect(() => {
    const token = window.localStorage.getItem(AUTH_TOKEN_KEY);
    if (!token) {
      setHasSession(false);
      setSessionChecked(true);
      return;
    }

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
      })
      .finally(() => setSessionChecked(true));
  }, []);

  return (
    <div className="min-h-screen overflow-x-hidden bg-[#07111f] text-slate-100">
      {/* Ambient background */}
      <div className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
        <div className="absolute -left-[20%] top-0 h-[55vh] w-[55vw] rounded-full bg-cyan-400/[0.12] blur-[120px]" />
        <div className="absolute -right-[15%] top-[30%] h-[45vh] w-[45vw] rounded-full bg-amber-300/[0.09] blur-[100px]" />
        <div className="absolute bottom-0 left-[30%] h-[40vh] w-[40vw] rounded-full bg-violet-500/[0.07] blur-[110px]" />
      </div>

      <header className="sticky top-0 z-50 border-b border-white/[0.06] bg-[#07111f]/80 backdrop-blur-2xl">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3.5 sm:px-6 lg:px-8">
          <Link href="/" className="flex min-w-0 items-center gap-2.5">
            <DashboardLogo className="h-8 w-8 shrink-0 sm:h-9 sm:w-9" />
            <span className="truncate text-sm font-medium tracking-tight text-slate-100">{PRODUCT_DISPLAY_NAME}</span>
          </Link>
          <nav className="hidden items-center gap-8 md:flex">
            {LANDING_NAV.map((item) => (
              <a
                key={item.href}
                href={item.href}
                className="text-[11px] font-medium uppercase tracking-[0.18em] text-slate-500 transition hover:text-cyan-100"
              >
                {item.label}
              </a>
            ))}
          </nav>
          <div className="flex shrink-0 items-center gap-2">
            {sessionChecked ? (
              <LandingProductCta
                hasSession={hasSession}
                className="!rounded-full px-4 py-2 text-xs sm:text-sm"
              />
            ) : null}
          </div>
        </div>
      </header>

      <main className="relative">
        {/* Hero */}
        <section className="relative px-4 pb-20 pt-12 sm:px-6 sm:pb-28 sm:pt-16 lg:px-8">
          <div className="landing-grid-bg pointer-events-none absolute inset-x-0 top-0 h-[min(520px,70vh)] opacity-80" />
          <div className="relative mx-auto max-w-6xl">
            <div className="overflow-hidden rounded-[2rem] border border-white/[0.08] bg-[linear-gradient(145deg,rgba(12,22,38,0.92),rgba(8,18,32,0.88))] shadow-[0_40px_120px_rgba(0,0,0,0.45)] sm:rounded-[2.5rem]">
              <div className="grid lg:grid-cols-[1.08fr_0.92fr] lg:items-stretch">
                <div className="border-b border-white/[0.06] p-8 sm:p-10 lg:border-b-0 lg:border-r lg:p-12">
                  <div className="inline-flex items-center gap-2 rounded-full border border-cyan-300/20 bg-cyan-400/[0.08] px-3.5 py-1.5 text-[10px] font-semibold uppercase tracking-[0.2em] text-cyan-100/90">
                    <Sparkles size={12} />
                    {HERO_BADGE}
                  </div>
                  <h1 className="mt-6 text-[2.35rem] font-semibold leading-[1.08] tracking-[-0.04em] text-slate-50 sm:text-5xl lg:text-[3.25rem]">
                    {HERO_HEADLINE}
                  </h1>
                  <p className="mt-5 max-w-xl text-base leading-relaxed text-slate-400 sm:text-[1.05rem]">{HERO_SUBCOPY}</p>
                  <ul className="mt-10 grid gap-3 border-t border-white/[0.06] pt-8 sm:grid-cols-2">
                    {HERO_PILLS.map((pill) => (
                      <li
                        key={pill.title}
                        className="min-w-0 rounded-2xl bg-white/[0.025] p-4 transition duration-300 hover:bg-white/[0.045]"
                      >
                        <p className="text-sm font-medium text-slate-200">{pill.title}</p>
                        <p className="mt-0.5 text-xs text-slate-500">{pill.body}</p>
                      </li>
                    ))}
                  </ul>
                </div>

                <section id="sign-in" className="scroll-mt-24 bg-black/20 p-6 sm:p-8 lg:scroll-mt-28 lg:p-10">
                  {sessionChecked ? (
                    <LoginPanel hasSession={hasSession} className="border-0 bg-transparent p-0 shadow-none" />
                  ) : (
                    <div className="h-full min-h-[280px] animate-pulse rounded-2xl bg-white/[0.04]" />
                  )}
                </section>
              </div>
            </div>
          </div>
        </section>

        <LandingProductPreview />

        {/* Pain — comparison strip */}
        <section className="border-y border-white/[0.06] bg-slate-950/50 px-4 py-16 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-6xl">
            <SectionEyebrow>Why teams switch</SectionEyebrow>
            <SectionTitle>From reactive inbox to proactive freight ops</SectionTitle>
            <div className="mt-12 space-y-0 divide-y divide-white/[0.06] rounded-2xl border border-white/[0.06] bg-white/[0.02]">
              {PAIN_ITEMS.map((item) => (
                <div
                  key={item.before}
                  className="grid gap-4 px-5 py-5 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1.2fr)] sm:items-center sm:gap-6 sm:px-8"
                >
                  <p className="text-sm text-slate-500 line-through decoration-slate-600/80">{item.before}</p>
                  <ArrowRight size={18} className="hidden shrink-0 text-cyan-300/50 sm:block" aria-hidden />
                  <div>
                    <p className="text-base font-semibold text-cyan-100/95">{item.after}</p>
                    <p className="mt-1 text-sm leading-relaxed text-slate-500">{item.detail}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Workflow — timeline */}
        <section id="workflow" className="scroll-mt-24 px-4 py-20 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-6xl lg:grid lg:grid-cols-[280px_1fr] lg:gap-16">
            <div className="lg:sticky lg:top-28 lg:self-start">
              <SectionEyebrow>Core workflow</SectionEyebrow>
              <SectionTitle>Email to booked load</SectionTitle>
              <p className="mt-4 text-sm leading-relaxed text-slate-500">
                One continuous loop — no tab hopping between inbox, spreadsheets, and TMS.
              </p>
            </div>
            <ol className="relative mt-10 space-y-0 lg:mt-0">
              <div className="absolute bottom-4 left-[11px] top-4 w-px bg-gradient-to-b from-cyan-400/40 via-cyan-400/15 to-transparent lg:left-[15px]" aria-hidden />
              {WORKFLOW_STEPS.map((step, index) => (
                <li key={step.step} className="relative flex gap-5 pb-10 last:pb-0 sm:gap-6">
                  <div className="relative z-[1] flex size-6 shrink-0 items-center justify-center rounded-full border border-cyan-300/30 bg-[#0c1828] text-[10px] font-bold text-cyan-200 sm:size-8 sm:text-xs">
                    {step.step}
                  </div>
                  <div className="min-w-0 flex-1 pt-0.5">
                    <h3 className="text-lg font-semibold tracking-tight text-white">{step.title}</h3>
                    <p className="mt-1.5 max-w-lg text-sm leading-relaxed text-slate-500">{step.body}</p>
                    {index < WORKFLOW_STEPS.length - 1 ? (
                      <div className="mt-6 h-px max-w-xs bg-gradient-to-r from-white/10 to-transparent sm:hidden" aria-hidden />
                    ) : null}
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* Features — bento */}
        <section id="features" className="scroll-mt-24 border-t border-white/[0.06] px-4 py-20 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-6xl">
            <div className="max-w-2xl">
              <SectionEyebrow>Platform</SectionEyebrow>
              <SectionTitle>Everything dispatch needs in one layer</SectionTitle>
            </div>
            <div className="mt-12 grid gap-3 sm:grid-cols-2 lg:grid-cols-12 lg:grid-rows-[auto_auto_auto]">
              {FEATURES.map((feature, index) => {
                const Icon = FEATURE_ICONS[index] ?? Sparkles;
                const spans =
                  index === 0
                    ? "sm:col-span-2 lg:col-span-7 lg:row-span-2"
                    : index === 1
                      ? "lg:col-span-5"
                      : index === 2
                        ? "lg:col-span-5"
                        : index === 3
                          ? "lg:col-span-4"
                          : index === 4
                            ? "lg:col-span-4"
                            : "lg:col-span-4";
                const isHero = index === 0;
                return (
                  <div
                    key={feature.title}
                    className={`group rounded-2xl border border-white/[0.07] bg-white/[0.02] p-6 transition duration-300 hover:border-cyan-300/20 hover:bg-white/[0.04] ${spans} ${isHero ? "sm:p-8" : ""}`}
                  >
                    <Icon
                      size={isHero ? 22 : 18}
                      className="text-cyan-300/70 transition group-hover:text-cyan-200"
                      strokeWidth={1.75}
                    />
                    <h3 className={`mt-4 font-semibold text-white ${isHero ? "text-xl sm:text-2xl" : "text-base"}`}>
                      {feature.title}
                    </h3>
                    <p className={`mt-2 leading-relaxed text-slate-500 ${isHero ? "max-w-md text-sm sm:text-base" : "text-sm"}`}>
                      {feature.body}
                    </p>
                  </div>
                );
              })}
            </div>
          </div>
        </section>

        {/* Trust — single panel */}
        <section className="px-4 py-20 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-6xl overflow-hidden rounded-[2rem] border border-emerald-300/15 bg-[linear-gradient(135deg,rgba(16,185,129,0.08),rgba(8,18,32,0.6))]">
            <div className="border-b border-white/[0.06] px-8 py-10 sm:px-12">
              <SectionEyebrow>Operator control</SectionEyebrow>
              <p className="mt-3 max-w-xl text-xl font-semibold tracking-tight text-emerald-50/95 sm:text-2xl">
                Automation with guardrails your team actually trusts
              </p>
            </div>
            <div className="grid divide-y divide-white/[0.06] md:grid-cols-3 md:divide-x md:divide-y-0">
              {TRUST_POINTS.map((point) => (
                <div key={point.title} className="px-8 py-8 sm:px-10">
                  <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-emerald-200/80">{point.title}</h3>
                  <p className="mt-3 text-sm leading-relaxed text-slate-400">{point.body}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Extension */}
        <section
          id="extension"
          className="scroll-mt-24 px-4 py-20 sm:px-6 lg:px-8"
        >
          <div className="mx-auto max-w-6xl overflow-hidden rounded-[2rem] border border-violet-300/15 bg-[linear-gradient(160deg,rgba(139,92,246,0.1),rgba(8,18,32,0.85)_50%,rgba(34,211,238,0.06))]">
            <div className="grid lg:grid-cols-2">
              <div className="p-8 sm:p-12 lg:border-r lg:border-white/[0.06]">
                <SectionEyebrow>{EXTENSION_SECTION.label}</SectionEyebrow>
                <h2 className="mt-3 text-2xl font-semibold tracking-tight text-white sm:text-3xl">{EXTENSION_SECTION.headline}</h2>
                <p className="mt-4 text-sm leading-relaxed text-slate-400 sm:text-base">{EXTENSION_SECTION.subcopy}</p>
                <a
                  href={CHROME_WEB_STORE_LOGISTIC_COPILOT_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-8 inline-flex items-center gap-2 rounded-full bg-violet-400/20 px-5 py-3 text-sm font-semibold text-violet-50 ring-1 ring-violet-300/25 transition hover:bg-violet-400/28"
                >
                  <Puzzle size={18} aria-hidden />
                  {EXTENSION_SECTION.installLabel}
                  <ExternalLink size={15} className="opacity-70" aria-hidden />
                </a>
                <p className="mt-3 text-xs text-slate-600">{EXTENSION_SECTION.installHint}</p>
              </div>
              <div className="border-t border-white/[0.06] bg-black/25 p-8 sm:p-12 lg:border-t-0">
                <div className="flex items-center gap-2 text-cyan-100/90">
                  <Sparkles size={18} aria-hidden />
                  <span className="text-xs font-semibold uppercase tracking-[0.2em]">{EXTENSION_SECTION.agentHeadline}</span>
                </div>
                <p className="mt-4 text-sm leading-relaxed text-slate-400">{EXTENSION_SECTION.agentBody}</p>
                <ul className="mt-6 space-y-4">
                  {EXTENSION_SECTION.agentBullets.map((bullet) => (
                    <li key={bullet} className="flex gap-3 text-sm text-slate-300">
                      <span className="mt-2 size-1 shrink-0 rounded-full bg-cyan-400/80" aria-hidden />
                      {bullet}
                    </li>
                  ))}
                </ul>
                <div className="mt-8 border-t border-white/[0.06] pt-8">
                  <div className="flex items-center gap-2 text-rose-200/90">
                    <ShieldAlert size={18} aria-hidden />
                    <span className="text-xs font-semibold uppercase tracking-[0.2em]">{EXTENSION_SECTION.antiFraudHeadline}</span>
                  </div>
                  <p className="mt-4 text-sm leading-relaxed text-slate-400">{EXTENSION_SECTION.antiFraudBody}</p>
                  <ul className="mt-6 space-y-4">
                    {EXTENSION_SECTION.antiFraudBullets.map((bullet) => (
                      <li key={bullet} className="flex gap-3 text-sm text-slate-300">
                        <span className="mt-2 size-1 shrink-0 rounded-full bg-rose-300/80" aria-hidden />
                        {bullet}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Integrations — inline row */}
        <section className="border-t border-white/[0.06] px-4 py-16 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-6xl">
            <SectionEyebrow>Integrations</SectionEyebrow>
            <div className="mt-8 flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between">
              <SectionTitle className="!mt-0 lg:max-w-md">Outlook, documents, and TMS — connected</SectionTitle>
              <div className="flex flex-col gap-6 sm:flex-row sm:gap-12 lg:gap-16">
                {INTEGRATIONS.map((item, i) => (
                  <div key={item.title} className="max-w-xs">
                    <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-600">
                      {String(i + 1).padStart(2, "0")}
                    </p>
                    <h3 className="mt-2 text-base font-semibold text-slate-200">{item.title}</h3>
                    <p className="mt-1.5 text-sm leading-relaxed text-slate-500">{item.body}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* Open source */}
        <section
          id="open-source"
          className="scroll-mt-24 border-t border-white/[0.06] px-4 py-20 sm:px-6 lg:px-8"
        >
          <div className="mx-auto grid max-w-6xl gap-8 rounded-[2rem] border border-cyan-300/15 bg-[linear-gradient(135deg,rgba(34,211,238,0.08),rgba(8,18,32,0.78))] p-8 sm:p-12 lg:grid-cols-[1fr_auto] lg:items-end">
            <div className="max-w-2xl">
              <SectionEyebrow>{OPEN_SOURCE_SECTION.label}</SectionEyebrow>
              <h2 className="mt-3 text-2xl font-semibold tracking-tight text-white sm:text-3xl">
                {OPEN_SOURCE_SECTION.headline}
              </h2>
              <p className="mt-4 text-sm leading-relaxed text-slate-400 sm:text-base">
                {OPEN_SOURCE_SECTION.subcopy}
              </p>
            </div>
            <div className="flex flex-col gap-3 sm:flex-row lg:flex-col">
              <a
                href={OPEN_SOURCE_SECTION.githubHref}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center justify-center gap-2 rounded-full border border-cyan-200/25 bg-cyan-300/12 px-5 py-3 text-sm font-semibold text-cyan-50 transition hover:bg-cyan-300/20"
              >
                <Github size={18} aria-hidden />
                {OPEN_SOURCE_SECTION.githubLabel}
                <ExternalLink size={15} className="opacity-70" aria-hidden />
              </a>
              <a
                href={`mailto:${OPEN_SOURCE_SECTION.contactEmail}`}
                className="inline-flex items-center justify-center gap-2 rounded-full border border-white/10 px-5 py-3 text-sm font-semibold text-slate-200 transition hover:border-white/20 hover:bg-white/[0.04]"
              >
                <Mail size={18} aria-hidden />
                {OPEN_SOURCE_SECTION.contactEmail}
              </a>
            </div>
          </div>
        </section>

        {/* FAQ — minimal list */}
        <section id="faq" className="scroll-mt-24 border-t border-white/[0.06] bg-slate-950/40 px-4 py-20 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-6xl lg:grid lg:grid-cols-[220px_1fr] lg:gap-20">
            <div>
              <SectionEyebrow>FAQ</SectionEyebrow>
              <SectionTitle className="text-xl sm:text-2xl">Questions</SectionTitle>
            </div>
            <dl className="mt-10 divide-y divide-white/[0.08] lg:mt-0">
              {FAQ_ITEMS.map((item) => (
                <div key={item.question} className="py-8 first:pt-0 last:pb-0">
                  <dt className="text-base font-semibold text-slate-100">{item.question}</dt>
                  <dd className="mt-3 text-sm leading-relaxed text-slate-500">{item.answer}</dd>
                  {item.linkHref ? (
                    <dd className="mt-3">
                      <Link
                        href={item.linkHref}
                        className="inline-flex items-center gap-1 text-sm font-medium text-cyan-300/90 transition hover:text-cyan-200"
                      >
                        {item.linkLabel}
                        <ArrowRight size={14} />
                      </Link>
                    </dd>
                  ) : null}
                </div>
              ))}
            </dl>
          </div>
        </section>

        {/* Final CTA */}
        <section className="px-4 py-24 sm:px-6 lg:px-8">
          <div className="relative mx-auto max-w-4xl overflow-hidden rounded-[2.5rem] px-8 py-14 text-center sm:px-14 sm:py-16">
            <div
              className="pointer-events-none absolute inset-0 rounded-[2.5rem] border border-cyan-300/20 bg-[linear-gradient(180deg,rgba(34,211,238,0.12),rgba(8,18,32,0.9))]"
              aria-hidden
            />
            <div className="pointer-events-none absolute inset-0 rounded-[2.5rem] landing-grid-bg opacity-40" aria-hidden />
            <div className="relative">
              <h2 className="text-2xl font-semibold tracking-tight text-white sm:text-4xl">{FINAL_CTA_HEADLINE}</h2>
              <p className="mx-auto mt-4 max-w-lg text-sm leading-relaxed text-slate-400 sm:text-base">{FINAL_CTA_SUBCOPY}</p>
              <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
                {sessionChecked ? (
                  <LandingProductCta hasSession={hasSession} className="!rounded-full px-6" />
                ) : null}
              </div>
              <p className="mt-8 text-xs text-slate-600">
                Invited to a workspace?{" "}
                <Link href="/invite" className="text-cyan-300/80 underline-offset-2 hover:text-cyan-200 hover:underline">
                  Accept your invite
                </Link>
              </p>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-white/[0.06] px-4 py-12 sm:px-6 lg:px-8">
        <div className="mx-auto flex max-w-6xl flex-col gap-8 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <DashboardLogo className="mb-4 h-8 w-8 opacity-80" />
            <p className="max-w-sm text-sm text-slate-400">{FOOTER_TAGLINE}</p>
            <p className="mt-4 text-xs text-slate-600">
              © {new Date().getFullYear()} {PRODUCT_DISPLAY_NAME}
            </p>
          </div>
          <div className="flex flex-wrap gap-x-8 gap-y-3 text-sm">
            <a
              href={CHROME_WEB_STORE_LOGISTIC_COPILOT_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="text-slate-500 transition hover:text-slate-200"
            >
              Extension
            </a>
            <Link href="/privacy-policy" className="text-slate-500 transition hover:text-slate-200">
              Privacy
            </Link>
            <a
              href={OPEN_SOURCE_SECTION.githubHref}
              target="_blank"
              rel="noopener noreferrer"
              className="text-slate-500 transition hover:text-slate-200"
            >
              GitHub
            </a>
            <a
              href={`mailto:${OPEN_SOURCE_SECTION.contactEmail}`}
              className="text-slate-500 transition hover:text-slate-200"
            >
              Contact
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}
