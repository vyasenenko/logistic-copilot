import { PRODUCT_DISPLAY_NAME } from "@/constants/brand";

export const LANDING_NAV = [
  { href: "#preview", label: "Product" },
  { href: "#workflow", label: "Workflow" },
  { href: "#features", label: "Features" },
  { href: "#extension", label: "Extension" },
  { href: "#faq", label: "FAQ" },
] as const;

export const PRODUCT_PREVIEW = {
  eyebrow: "See the control tower",
  headline: "Inbox threads become shipments your team can run",
  subcopy:
    "A representative view of how Logistic Copilot connects Outlook intake, structured lanes, and the live operations board — without leaving email context behind.",
  inboxTitle: "Outlook · Triage",
  boardTitle: "Operations board",
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
  liveHint: "Workflow events stream to your org in real time",
  flowLabels: ["Email classified", "Shipment structured", "Ops board updated"],
} as const;

export const HERO_BADGE = "AI logistics workflow for brokers & dispatch";

export const HERO_HEADLINE = "Turn your Outlook inbox into a freight operating system.";

export const HERO_SUBCOPY =
  "Quote intake, shipment parsing, carrier outreach, bid evaluation, customer quotes, document processing, and status workflows — with operator control where automation should pause.";

export const HERO_PILLS = [
  { title: "Faster response", body: "Quote and status email handled in one flow" },
  { title: "Less manual work", body: "Stop re-keying lanes, dates, and bids" },
  { title: "Operator control", body: "Review gates before anything goes out" },
] as const;

export const PAIN_ITEMS = [
  {
    before: "Inbox chaos",
    after: "Structured shipments",
    detail: "Every logistics thread becomes a trackable case with context.",
  },
  {
    before: "Scattered tools",
    after: "One control tower",
    detail: "Triage, bids, documents, and status in a single workspace.",
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
    title: "AI shipment extraction",
    body: "Turn customer and carrier email into structured shipment records with confidence signals.",
  },
  {
    title: "Carrier bid automation",
    body: "Outreach, intake, and bid scoring without leaving the shipment context.",
  },
  {
    title: "Document OCR & parsing",
    body: "Attachments become reviewable fields — approve or correct before they drive workflow.",
  },
  {
    title: "Operator review queue",
    body: "Manual review, sender verification, and triage for anything that needs a human.",
  },
  {
    title: "Status workflows",
    body: "Status lookups, customer replies, and ops queues for in-transit freight.",
  },
  {
    title: "Outlook-first ops",
    body: "Mailbox sync and thread context built for how brokers actually work.",
  },
] as const;

export const TRUST_POINTS = [
  {
    title: "Human-in-the-loop",
    body: "Automation proposes; your team approves quotes, outreach, and risky senders.",
  },
  {
    title: "Team visibility",
    body: "Organization-scoped board with real-time workflow events across shipments.",
  },
  {
    title: "Role-based access",
    body: "Viewer, member, and admin roles — read-only agents and UI where required.",
  },
] as const;

export const EXTENSION_SECTION = {
  label: "Chrome extension",
  headline: "Your AI copilot lives in Chrome — next to Outlook and the web.",
  subcopy:
    "Install the Logistic Copilot side panel to ask freight questions, use page context from the tab you are on, and stay signed in with your workspace — the same agent powers the dashboard and the extension.",
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
  installHint: "Free to install · Side panel · Uses your workspace sign-in",
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
      "It classifies email, extracts shipment data, drafts outreach, and scores bids. Operators stay in control — review gates, edits, and blocks before anything customer-facing sends.",
  },
];

export const FINAL_CTA_HEADLINE = "Ready to run freight from your inbox?";

export const FINAL_CTA_SUBCOPY =
  `Sign in to your ${PRODUCT_DISPLAY_NAME} workspace or book a walkthrough with our team.`;

export const FOOTER_TAGLINE = `${PRODUCT_DISPLAY_NAME} — AI logistics workflow for freight brokers and dispatch teams.`;
