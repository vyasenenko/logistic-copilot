import type { Metadata } from "next";
import { MarketingLanding } from "@/components/landing/MarketingLanding";

export const metadata: Metadata = {
  title: "Logistic Copilot | AI Logistics Workflow",
  description:
    "Outlook-first AI workflow for brokers and dispatch — quote intake, bids, documents, TMS handoff, and operator control.",
};

export default function Home() {
  return <MarketingLanding />;
}
