"use client";

import type { ReactNode } from "react";
import { ArrowRight, Inbox, Mail, Package2, Radio } from "lucide-react";
import { PRODUCT_PREVIEW } from "@/components/landing/landing-content";

function PreviewChrome({ children, title }: { children: ReactNode; title: string }) {
  return (
    <div className="overflow-hidden rounded-xl border border-white/[0.08] bg-[#0a1524]/90 shadow-[0_24px_60px_rgba(0,0,0,0.35)]">
      <div className="flex items-center gap-2 border-b border-white/[0.06] bg-black/30 px-3 py-2">
        <span className="size-2 rounded-full bg-rose-400/80" aria-hidden />
        <span className="size-2 rounded-full bg-amber-300/80" aria-hidden />
        <span className="size-2 rounded-full bg-emerald-400/80" aria-hidden />
        <span className="ml-2 truncate text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500">{title}</span>
      </div>
      {children}
    </div>
  );
}

export function LandingProductPreview() {
  return (
    <section
      id="preview"
      className="scroll-mt-24 border-y border-white/[0.06] bg-[linear-gradient(180deg,rgba(8,18,32,0.4),rgba(7,17,31,0.95))] px-4 py-16 sm:px-6 sm:py-20 lg:px-8"
      aria-label="Product preview"
    >
      <div className="mx-auto max-w-6xl">
        <p className="text-center text-[11px] font-semibold uppercase tracking-[0.28em] text-cyan-200/55">
          {PRODUCT_PREVIEW.eyebrow}
        </p>
        <h2 className="mx-auto mt-3 max-w-2xl text-center text-2xl font-semibold tracking-[-0.03em] text-white sm:text-3xl">
          {PRODUCT_PREVIEW.headline}
        </h2>
        <p className="mx-auto mt-3 max-w-xl text-center text-sm leading-relaxed text-slate-500">{PRODUCT_PREVIEW.subcopy}</p>

        <div className="mt-12 lg:mt-14">
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1.15fr)] lg:items-stretch lg:gap-5">
            {/* Inbox */}
            <PreviewChrome title={PRODUCT_PREVIEW.inboxTitle}>
              <div className="space-y-2 p-3">
                {PRODUCT_PREVIEW.inboxThreads.map((thread) => (
                  <div
                    key={thread.subject}
                    className={`rounded-lg border px-3 py-2.5 ${
                      thread.active
                        ? "border-cyan-300/25 bg-cyan-400/[0.08]"
                        : "border-white/[0.05] bg-white/[0.02]"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <p className="truncate text-[11px] font-medium text-slate-200">{thread.sender}</p>
                      {thread.badge ? (
                        <span className="shrink-0 rounded-full bg-amber-300/15 px-1.5 py-0.5 text-[9px] font-semibold uppercase text-amber-100">
                          {thread.badge}
                        </span>
                      ) : null}
                    </div>
                    <p className="mt-1 truncate text-[10px] text-slate-500">{thread.subject}</p>
                  </div>
                ))}
              </div>
            </PreviewChrome>

            <div className="hidden flex-col items-center justify-center gap-2 lg:flex" aria-hidden>
              <div className="flex size-10 items-center justify-center rounded-full border border-cyan-300/25 bg-cyan-400/10">
                <ArrowRight size={18} className="text-cyan-200" />
              </div>
              <p className="max-w-[4.5rem] text-center text-[9px] font-semibold uppercase tracking-[0.16em] text-cyan-200/60">
                AI
              </p>
            </div>

            {/* Control tower */}
            <PreviewChrome title={PRODUCT_PREVIEW.boardTitle}>
              <div className="p-3">
                <div className="grid grid-cols-3 gap-1.5">
                  {PRODUCT_PREVIEW.metrics.map((metric) => (
                    <div
                      key={metric.label}
                      className="rounded-lg border border-cyan-200/10 bg-slate-950/50 px-2 py-2 text-center"
                    >
                      <p className="text-[8px] uppercase tracking-[0.12em] text-slate-500">{metric.label}</p>
                      <p className="mt-0.5 text-sm font-semibold text-white">{metric.value}</p>
                    </div>
                  ))}
                </div>
                <div className="mt-3 rounded-xl border border-white/[0.08] bg-white/[0.03] p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-[10px] uppercase tracking-[0.14em] text-cyan-200/50">Active lane</p>
                      <p className="mt-1 truncate text-xs font-semibold text-white">{PRODUCT_PREVIEW.shipment.route}</p>
                      <p className="mt-0.5 text-[10px] text-slate-500">{PRODUCT_PREVIEW.shipment.token}</p>
                    </div>
                    <span className="shrink-0 rounded-full border border-amber-300/25 bg-amber-300/12 px-2 py-0.5 text-[9px] font-medium text-amber-100">
                      {PRODUCT_PREVIEW.shipment.status}
                    </span>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {PRODUCT_PREVIEW.shipment.tags.map((tag) => (
                      <span
                        key={tag}
                        className="rounded-md bg-white/[0.06] px-2 py-0.5 text-[9px] text-slate-400"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="mt-2 flex items-center gap-2 rounded-lg border border-violet-300/15 bg-violet-400/[0.06] px-2.5 py-2">
                  <Radio size={12} className="shrink-0 text-violet-200/80" aria-hidden />
                  <p className="text-[10px] text-violet-100/80">{PRODUCT_PREVIEW.liveHint}</p>
                </div>
              </div>
            </PreviewChrome>
          </div>

          {/* Mobile flow connector */}
          <div className="mt-4 flex items-center justify-center gap-2 lg:hidden" aria-hidden>
            <Inbox size={14} className="text-slate-600" />
            <ArrowRight size={14} className="text-cyan-400/60" />
            <Package2 size={14} className="text-slate-600" />
          </div>
        </div>

        <ul className="mx-auto mt-10 flex max-w-3xl flex-col gap-3 sm:flex-row sm:justify-center sm:gap-8">
          {PRODUCT_PREVIEW.flowLabels.map((label) => (
            <li key={label} className="flex items-center justify-center gap-2 text-xs text-slate-500">
              <Mail size={12} className="shrink-0 text-cyan-400/50" aria-hidden />
              {label}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
