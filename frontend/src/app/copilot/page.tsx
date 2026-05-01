import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "LogistiCopilot | Freight Control Tower",
  description: "Minimal Copilot hero page",
};

export default function CopilotPage() {
  return (
    <main className="min-h-screen px-4 py-8 sm:px-6 lg:px-8">
      <section className="glass-panel mx-auto flex min-h-[78vh] w-full max-w-6xl items-center justify-center p-8 sm:p-12">
        <h1 className="text-5xl font-semibold tracking-tight text-slate-100 sm:text-7xl">
          Copilot
        </h1>
      </section>
    </main>
  );
}
