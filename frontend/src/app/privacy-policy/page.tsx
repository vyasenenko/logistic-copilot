import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft, Shield } from "lucide-react";
import { DashboardLogo } from "@/components/DashboardLogo";
import { PRODUCT_DISPLAY_NAME } from "@/constants/brand";

const EXTENSION_PRODUCT = `${PRODUCT_DISPLAY_NAME} Chrome Extension`;

export const metadata: Metadata = {
  title: `Privacy Policy | ${PRODUCT_DISPLAY_NAME}`,
  description: `Privacy Policy for ${EXTENSION_PRODUCT}`,
};

const sections = [
  {
    title: "1. Who We Are",
    body: [
      "Publisher: Vitalii Yasenenko",
      `Product: ${EXTENSION_PRODUCT}`,
      "Contact email: vyasenenko@logisticopilot.com",
    ],
  },
  {
    title: "2. Scope",
    body: [
      `This Privacy Policy applies to the ${EXTENSION_PRODUCT} and related backend services used by the extension.`,
    ],
  },
  {
    title: "3. Information We Collect",
    body: [
      "Chat content you type in the extension.",
      "Optional voice audio you provide when starting voice dictation.",
      "Current tab context (URL, title, selected text, visible excerpt, headings, action labels) when page context is enabled.",
      "Conversation metadata such as timestamps and conversation identifiers.",
      "Local extension settings (for example backend/frontend endpoint values).",
    ],
  },
  {
    title: "4. How We Use Information",
    body: [
      "To provide chat and context-aware assistant responses.",
      "To support optional voice transcription.",
      "To maintain conversation continuity and history.",
      "To improve reliability, security, and quality of the service.",
    ],
  },
  {
    title: "5. Data Sharing",
    body: [
      "We may share data with service providers strictly required to operate the product, including AI model providers, audio transcription providers, and cloud infrastructure vendors.",
      "We do not sell personal information.",
    ],
  },
  {
    title: "6. Storage and Retention",
    body: [
      "Extension-side settings and UI state are stored locally via Chrome extension storage.",
      "Conversation data may be stored on backend systems to support chat history.",
      "If you delete a conversation from the extension UI, related backend conversation records are removed from conversation storage.",
      "Data is retained only as long as needed for service operation, legal obligations, and security.",
    ],
  },
  {
    title: "7. Chrome Permissions",
    body: [
      "storage: saves local settings and UI state.",
      "tabs / activeTab / scripting: captures and refreshes active tab context.",
      "sidePanel: displays extension UI.",
      "host_permissions: enables API requests to configured backend hosts.",
    ],
  },
  {
    title: "8. Your Controls",
    body: [
      "Enable or disable page context in the extension.",
      "Delete conversations from the UI.",
      "Use or avoid optional voice input.",
      "Uninstall the extension at any time.",
    ],
  },
  {
    title: "9. Security",
    body: [
      "We apply reasonable technical and organizational safeguards. No method of transmission or storage can be guaranteed 100% secure.",
    ],
  },
  {
    title: "10. Children",
    body: [
      "The extension is not intended for children under 13 (or a higher local legal age where applicable).",
    ],
  },
  {
    title: "11. Policy Updates",
    body: [
      "We may update this Policy from time to time. The latest version will always include an updated date.",
    ],
  },
  {
    title: "12. Contact",
    body: [
      "Privacy requests: vyasenenko@logisticopilot.com",
      "Controller/Publisher: Vitalii Yasenenko",
    ],
  },
];

export default function PrivacyPolicyPage() {
  return (
    <main className="min-h-screen overflow-hidden bg-[#07111f] px-4 py-6 text-slate-100 sm:px-6 lg:px-8">
      <section className="relative mx-auto w-full max-w-7xl overflow-hidden rounded-[2.25rem] border border-white/10 bg-[linear-gradient(135deg,_rgba(15,23,42,0.98),_rgba(8,47,73,0.72)_48%,_rgba(28,25,23,0.96))] p-5 shadow-2xl shadow-cyan-950/30 sm:p-8 lg:p-12">
        <div className="pointer-events-none absolute -left-24 top-12 h-72 w-72 rounded-full bg-cyan-300/20 blur-3xl" />
        <div className="pointer-events-none absolute bottom-0 right-0 h-80 w-80 rounded-full bg-amber-200/16 blur-3xl" />
        <div className="pointer-events-none absolute left-[38%] top-[-10%] h-64 w-64 rounded-full bg-emerald-300/10 blur-3xl" />

        <div className="relative z-10">
          <div className="mb-8 flex flex-col gap-6 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex items-center gap-4">
              <DashboardLogo className="h-14 w-14 object-contain sm:h-16 sm:w-16" />
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.24em] text-cyan-200">{PRODUCT_DISPLAY_NAME}</p>
                <p className="mt-1 text-sm text-slate-400">Extension &amp; backend</p>
              </div>
            </div>
            <Link
              href="/"
              className="group inline-flex items-center gap-2 self-start rounded-2xl border border-white/12 bg-white/[0.05] px-4 py-2.5 text-sm font-medium text-slate-200 transition hover:border-cyan-200/25 hover:bg-cyan-300/10 hover:text-cyan-50"
            >
              <ArrowLeft size={16} className="transition group-hover:-translate-x-0.5" aria-hidden />
              Back to home
            </Link>
          </div>

          <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-cyan-200/25 bg-cyan-300/10 px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-cyan-100">
            <Shield size={14} className="shrink-0 opacity-90" aria-hidden />
            Legal &amp; Chrome Web Store
          </div>

          <h1 className="max-w-4xl bg-gradient-to-r from-cyan-200 via-slate-100 to-amber-200 bg-clip-text text-4xl font-semibold tracking-tight text-transparent sm:text-5xl lg:text-6xl">
            Privacy Policy
          </h1>

          <p className="mt-5 max-w-3xl text-base leading-8 text-slate-300 sm:text-lg">
            This page is designed for public publishing as {EXTENSION_PRODUCT} Privacy Policy URL.
          </p>

          <div className="mt-8 grid max-w-3xl gap-3 sm:grid-cols-2 lg:max-w-none">
            <div className="rounded-3xl border border-white/10 bg-white/[0.04] p-4">
              <p className="text-xs font-medium uppercase tracking-[0.16em] text-slate-500">Effective date</p>
              <p className="mt-2 text-sm font-semibold text-slate-100">April 30, 2026</p>
            </div>
            <div className="rounded-3xl border border-white/10 bg-white/[0.04] p-4">
              <p className="text-xs font-medium uppercase tracking-[0.16em] text-slate-500">Last updated</p>
              <p className="mt-2 text-sm font-semibold text-slate-100">April 30, 2026</p>
            </div>
          </div>

          <div className="mt-12 space-y-5 border-t border-white/10 pt-10">
            {sections.map((section) => (
              <article
                key={section.title}
                className="rounded-3xl border border-white/10 bg-slate-950/50 p-5 shadow-lg shadow-slate-950/20 backdrop-blur-sm sm:p-6"
              >
                <h2 className="text-lg font-semibold tracking-tight text-slate-50 sm:text-xl">{section.title}</h2>
                <ul className="mt-4 list-disc space-y-2.5 pl-5 text-sm leading-7 text-slate-300 marker:text-cyan-300/50 sm:text-[15px]">
                  {section.body.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
        </div>
      </section>
    </main>
  );
}
