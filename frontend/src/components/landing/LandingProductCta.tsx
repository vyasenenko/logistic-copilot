"use client";

import { useRouter } from "next/navigation";
import { ArrowRight } from "lucide-react";

interface LandingProductCtaProps {
  hasSession: boolean;
  className?: string;
}

export function LandingProductCta({ hasSession, className = "" }: LandingProductCtaProps) {
  const router = useRouter();

  if (hasSession) {
    return (
      <button
        type="button"
        onClick={() => router.push("/dashboard")}
        className={`group inline-flex items-center justify-center gap-2 rounded-2xl border border-cyan-200/30 bg-cyan-300/20 px-5 py-2.5 text-sm font-semibold text-cyan-50 transition hover:bg-cyan-300/30 ${className}`}
      >
        Continue to dashboard
        <ArrowRight size={16} className="transition group-hover:translate-x-0.5" />
      </button>
    );
  }

  return (
    <a
      href="#sign-in"
      className={`inline-flex items-center justify-center rounded-2xl border border-cyan-200/30 bg-cyan-300/20 px-5 py-2.5 text-sm font-semibold text-cyan-50 transition hover:bg-cyan-300/30 ${className}`}
    >
      Sign In
    </a>
  );
}
