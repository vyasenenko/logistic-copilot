import type { Metadata } from "next";
import { Suspense } from "react";
import { InviteAcceptClient } from "./InviteAcceptClient";

export const metadata: Metadata = {
  title: "Accept invitation | Logistic Copilot",
  description: "Complete your Logistic Copilot workspace invitation.",
};

export default function InvitePage() {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-screen items-center justify-center bg-[#07111f] text-slate-300">
          Loading…
        </main>
      }
    >
      <InviteAcceptClient />
    </Suspense>
  );
}
