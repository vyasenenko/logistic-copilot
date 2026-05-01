import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Privacy Policy | Freight Control Tower",
  description: "Privacy Policy for Logistic Copilot Chrome Extension",
};

const sections = [
  {
    title: "1. Who We Are",
    body: [
      "Publisher: Vitalii Yasenenko",
      "Product: Logistic Copilot Chrome Extension",
      "Contact email: vyasenenko@logisticopilot.com",
    ],
  },
  {
    title: "2. Scope",
    body: [
      "This Privacy Policy applies to the Logistic Copilot Chrome Extension and related backend services used by the extension.",
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
    <main className="min-h-screen px-4 py-8 sm:px-6 lg:px-8">
      <div className="mx-auto w-full max-w-5xl">
        <header className="glass-panel mb-6 overflow-hidden p-6 sm:p-8">
          <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs font-semibold uppercase tracking-[0.14em] text-cyan-200">
            Logistic Copilot
          </div>
          <h1 className="mt-4 text-3xl font-semibold tracking-tight text-slate-100 sm:text-4xl">
            Privacy Policy
          </h1>
          <p className="mt-3 max-w-3xl text-sm leading-7 text-slate-300 sm:text-base">
            This page is designed for public publishing as your Chrome Web Store Privacy Policy URL.
            Replace placeholder fields before submission.
          </p>
          <div className="mt-6 grid gap-3 text-sm text-slate-300 sm:grid-cols-2">
            <div className="rounded-2xl border border-white/10 bg-slate-900/40 px-4 py-3">
              <span className="text-slate-400">Effective date:</span> April 30, 2026
            </div>
            <div className="rounded-2xl border border-white/10 bg-slate-900/40 px-4 py-3">
              <span className="text-slate-400">Last updated:</span> April 30, 2026
            </div>
          </div>
        </header>

        <section className="glass-panel-strong p-4 sm:p-6">
          <div className="space-y-4">
            {sections.map((section) => (
              <article
                key={section.title}
                className="rounded-2xl border border-white/10 bg-slate-950/35 p-4 sm:p-5"
              >
                <h2 className="text-base font-semibold text-slate-100 sm:text-lg">
                  {section.title}
                </h2>
                <ul className="mt-3 space-y-2">
                  {section.body.map((line) => (
                    <li
                      key={line}
                      className="rounded-xl border border-white/5 bg-slate-900/40 px-3 py-2 text-sm leading-6 text-slate-300"
                    >
                      {line}
                    </li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
