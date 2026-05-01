import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "LogistiCopilot | Freight Control Tower",
  description: "Logistic Copilot hero page",
};

export default function Home() {
  return (
    <main className="min-h-screen px-4 py-8 sm:px-6 lg:px-8">
      <section className="glass-panel relative mx-auto flex min-h-[78vh] w-full max-w-6xl items-center justify-center overflow-hidden p-8 sm:p-12">
        <div className="pointer-events-none absolute -left-16 top-8 h-40 w-40 rounded-full bg-cyan-300/20 blur-3xl" />
        <div className="pointer-events-none absolute -right-12 bottom-8 h-44 w-44 rounded-full bg-amber-300/20 blur-3xl" />

        <div className="relative z-10 text-center">
          <div className="mb-5 inline-flex items-center rounded-full border border-cyan-200/30 bg-slate-900/40 px-4 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-cyan-200">
            Freight AI Experience
          </div>
          <h1 className="bg-gradient-to-r from-cyan-200 via-slate-100 to-amber-200 bg-clip-text text-5xl font-semibold tracking-tight text-transparent sm:text-7xl">
            LogistiCopilot
          </h1>
          <p className="mx-auto mt-4 max-w-xl text-sm leading-7 text-slate-300 sm:text-base">
            Smart command center for modern freight operations.
          </p>
          <div className="mt-8 flex items-center justify-center gap-3">
            <a
              href="/dashboard"
              className="rounded-2xl border border-cyan-200/40 bg-cyan-300/15 px-5 py-2.5 text-sm font-medium text-cyan-100 transition hover:bg-cyan-300/25"
            >
              Open Dashboard
            </a>
            <a
              href="/privacy-policy"
              className="rounded-2xl border border-white/20 bg-slate-900/40 px-5 py-2.5 text-sm font-medium text-slate-200 transition hover:bg-slate-800/60"
            >
              Privacy Policy
            </a>
          </div>
        </div>
      </section>
    </main>
  );
}
