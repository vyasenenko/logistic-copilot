import { PRODUCT_DISPLAY_NAME } from "@/constants/brand";

export const LANDING_NAV = [
  { href: "#preview", label: "Product" },
  { href: "#workflow", label: "Workflow" },
  { href: "#features", label: "Features" },
  { href: "#extension", label: "Extension" },
  { href: "#open-source", label: "Open source" },
  { href: "#faq", label: "FAQ" },
] as const;

export const PRODUCT_PREVIEW = {
  eyebrow: "AI workspace agent",
  headline: "One agent understands your inbox, shipments, documents, and workflow",
  subcopy:
    "A representative view of how Logistic Copilot monitors Outlook intake, shipment statuses, document signals, and live workflow events — so your team can ask what happened and what needs attention.",
  inboxTitle: "Outlook · Triage",
  boardTitle: "Agent workspace",
  inboxThreads: [
    { sender: "acme@shipper.com", subject: "Quote: Dallas → Chicago · 26 pallets", badge: "Quote", active: true },
    { sender: "carrier@linehaul.net", subject: "Re: RFQ Q-8842 — $2,450 all-in", badge: null, active: false },
    { sender: "ops@customer.com", subject: "Status on PRO 441209?", badge: "Status", active: false },
  ],
  metrics: [
    { label: "Active", value: "24" },
    { label: "Attention", value: "5" },
    { label: "Bids", value: "12" },
  ],
  shipment: {
    route: "Dallas, TX → Chicago, IL",
    token: "Q-8842A1",
    status: "Awaiting bid",
    tags: ["3 carrier replies", "Sender verified", "Ready today"],
  },
  liveHint: "The agent keeps workflow status and document context current in real time",
  flowLabels: ["Email understood", "Status explained", "Documents analyzed"],
} as const;

export const HERO_BADGE = "AI agent for freight workflow visibility";

export const HERO_HEADLINE = "AI agent for your freight workspace.";

export const HERO_SUBCOPY =
  "Logistic Copilot monitors your freight workspace: Outlook threads, shipment statuses, carrier replies, documents, bids, and workflow events. Ask what is happening, what changed, and what needs action — from the dashboard or the Chrome extension.";

export const HERO_PILLS = [
  { title: "Workflow awareness", body: "The agent understands statuses, handoffs, and next steps" },
  { title: "Inbox context", body: "Ask about emails, senders, quote requests, and carrier replies" },
  { title: "Document analysis", body: "BOLs, rate confirmations, and attachments become usable context" },
  { title: "Chrome side panel", body: "Work from Outlook or any browser tab with the same AI agent" },
] as const;

export const PAIN_ITEMS = [
  {
    before: "Inbox chaos",
    after: "Structured shipments",
    detail: "Every logistics thread becomes a trackable case with context.",
  },
  {
    before: "Scattered tools",
    after: "One AI workspace agent",
    detail: "Ask about triage, bids, documents, shipment status, and workflow history in one place.",
  },
  {
    before: "Blind automation",
    after: "Human-in-the-loop",
    detail: "Operators approve, edit, or block before quotes and outreach send.",
  },
  {
    before: "Slow handoffs",
    after: "TMS-ready booking",
    detail: "Customer quotes and carrier booking sync when your team is ready.",
  },
] as const;

export const WORKFLOW_STEPS = [
  { step: "01", title: "Intake email", body: "Outlook sync surfaces quote and status threads for your org." },
  { step: "02", title: "Parse shipment", body: "AI extracts lanes, equipment, dates, and missing fields." },
  { step: "03", title: "Outreach carriers", body: "RFQs and follow-ups stay in-thread with your carriers." },
  { step: "04", title: "Collect & score bids", body: "Bids land on the shipment; evaluation picks a winner." },
  { step: "05", title: "Quote customer", body: "Preview and send customer quotes from the selected bid." },
  { step: "06", title: "Book & sync", body: "Hand off to TMS and run status workflows from the same board." },
] as const;

export const FEATURES = [
  {
    title: "AI workflow agent",
    body: "Ask what is happening across your workspace: email threads, shipment status, carrier replies, bids, documents, and next actions.",
  },
  {
    title: "Carrier bid automation",
    body: "Outreach, intake, and bid scoring without leaving the shipment context.",
  },
  {
    title: "Document OCR & parsing",
    body: "Attachments become reviewable fields and agent context — ask what a document says before it drives workflow.",
  },
  {
    title: "Operator review queue",
    body: "Manual review, sender verification, and triage for anything that needs a human.",
  },
  {
    title: "Status workflows",
    body: "Status lookups, customer replies, and ops queues for in-transit freight, with the agent explaining what changed.",
  },
  {
    title: "Outlook and Chrome context",
    body: "Mailbox sync plus a Chrome side panel, so the agent can help while you are working inside email or the web.",
  },
] as const;

export const TRUST_POINTS = [
  {
    title: "Human-in-the-loop",
    body: "Automation proposes; your team approves quotes, outreach, and risky senders.",
  },
  {
    title: "Team visibility",
    body: "Organization-scoped board with real-time workflow events the AI agent can summarize and explain.",
  },
  {
    title: "Role-based access",
    body: "Viewer, member, and admin roles — read-only agents and UI where required.",
  },
] as const;

export const EXTENSION_SECTION = {
  label: "Chrome extension",
  headline: "Your AI agent lives in Chrome — next to Outlook and the web.",
  subcopy:
    "Install the Logistic Copilot side panel to ask freight questions while you are in Outlook or another browser tab. The agent can use workspace context to explain which email arrived, which shipment it belongs to, what status changed, what a document contains, and what should happen next.",
  agentHeadline: "Workspace-aware assistant",
  agentBody:
    "Use the extension as a live operations companion: ask about a sender, summarize a thread, check shipment status, review carrier bids, or understand documents without switching back to the dashboard.",
  agentBullets: [
    "Understands Outlook threads and sender context",
    "Explains shipment status and workflow history",
    "Answers questions about documents and attachments",
    "Works from the Chrome side panel while you stay in your current tab",
  ],
  antiFraudHeadline: "Built-in anti-fraud layer",
  antiFraudBody:
    "Suspicious senders are flagged before automation runs wild. Risk signals, sender verification gates, email and domain denylist actions, and operator review on triage keep bad threads off your live board.",
  antiFraudBullets: [
    "Fraud risk scoring on inbound logistics email",
    "Sender verification before quotes and outreach continue",
    "Block sender email or entire domain from triage and sync",
    "Human review queue for high-risk and ambiguous cases",
  ],
  installLabel: "Install on Chrome Web Store",
  installHint: "Free to install · Chrome side panel · Uses your workspace sign-in",
} as const;

export const INTEGRATIONS = [
  {
    title: "Microsoft Outlook",
    body: "Connect org mailboxes, sync threads, and triage with shared or private visibility.",
  },
  {
    title: "Documents",
    body: "BOLs, rate cons, and attachments parsed with OCR and operator sign-off.",
  },
  {
    title: "TMS handoff",
    body: "Preview and push booked loads to your configured TMS when the lane is won.",
  },
] as const;

export const OPEN_SOURCE_SECTION = {
  label: "Open source",
  headline: "Built in the open for logistics teams.",
  subcopy:
    "Logistic Copilot is open source. Review the code, follow the roadmap, or reach out if you want to run it with your freight workflow.",
  githubHref: "https://github.com/vyasenenko/logistic-copilot",
  githubLabel: "View on GitHub",
  contactEmail: "vitalii@logisticopilot.com",
} as const;

export type FaqItem = {
  question: string;
  answer: string;
  linkHref?: string;
  linkLabel?: string;
};

export const FAQ_ITEMS: FaqItem[] = [
  {
    question: "How do I get access?",
    answer:
      "Workspaces are invite-based. Your admin sends an invite; accept it on the invite page to create your account, then sign in here.",
    linkHref: "/invite",
    linkLabel: "Open invite page",
  },
  {
    question: "Do I connect Outlook on this page?",
    answer:
      "Mailbox setup happens after sign-in. Owners and admins configure Microsoft Graph credentials in organization settings; members connect their inbox from the dashboard.",
  },
  {
    question: "What does the AI actually do?",
    answer:
      "It works as a workspace-aware freight agent: it classifies email, extracts shipment data, understands statuses, reads document context, drafts outreach, scores bids, and explains what is happening across your workflow. Operators stay in control — review gates, edits, and blocks before anything customer-facing sends.",
  },
  {
    question: "Can I use it directly from email?",
    answer:
      "Yes. The Chrome extension opens Logistic Copilot as a side panel next to Outlook and the web, so you can ask about emails, shipment status, documents, bids, and workflow activity without leaving the tab you are working in.",
  },
];

export const FINAL_CTA_HEADLINE = "Ready to run freight from your inbox?";

export const FINAL_CTA_SUBCOPY =
  `Sign in to your ${PRODUCT_DISPLAY_NAME} workspace to continue working with shipments, documents, bids, and status workflows.`;

export const FOOTER_TAGLINE = `${PRODUCT_DISPLAY_NAME} — AI logistics workflow for freight brokers and dispatch teams.`;
