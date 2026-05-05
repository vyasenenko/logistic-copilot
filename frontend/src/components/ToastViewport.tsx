"use client";

import { useSyncExternalStore, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { CheckCircle2, Info, X, XCircle } from "lucide-react";

import {
  dismissToast,
  getServerToastSnapshot,
  getToastSnapshot,
  subscribeToasts,
  type ToastRecord,
  type ToastTone,
} from "@/lib/toast-store";

function toneStyles(tone: ToastTone) {
  if (tone === "error") {
    return "border-rose-400/22 bg-[linear-gradient(135deg,rgba(30,10,16,0.94),rgba(18,8,12,0.92))] text-rose-50 shadow-[0_12px_40px_rgba(0,0,0,0.45)]";
  }
  if (tone === "info") {
    return "border-cyan-300/22 bg-[linear-gradient(135deg,rgba(8,18,28,0.94),rgba(6,14,24,0.92))] text-cyan-50 shadow-[0_12px_40px_rgba(0,0,0,0.42)]";
  }
  return "border-emerald-400/22 bg-[linear-gradient(135deg,rgba(6,22,18,0.94),rgba(6,16,14,0.92))] text-emerald-50 shadow-[0_12px_40px_rgba(0,0,0,0.42)]";
}

function ToneIcon({ tone }: { tone: ToastTone }) {
  if (tone === "error") return <XCircle className="shrink-0 text-rose-300" size={18} aria-hidden />;
  if (tone === "info") return <Info className="shrink-0 text-cyan-200" size={18} aria-hidden />;
  return <CheckCircle2 className="shrink-0 text-emerald-300" size={18} aria-hidden />;
}

function ToastRow({ toast }: { toast: ToastRecord }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={`pointer-events-auto flex max-w-[min(100vw-2rem,28rem)] items-start gap-3 rounded-2xl border px-4 py-3 backdrop-blur-md motion-safe:transition motion-safe:duration-200 motion-safe:ease-out ${toneStyles(toast.tone)}`}
    >
      <ToneIcon tone={toast.tone} />
      <p className="min-w-0 flex-1 text-sm font-medium leading-snug">{toast.message}</p>
      <button
        type="button"
        onClick={() => dismissToast(toast.id)}
        className="shrink-0 rounded-lg p-1 text-white/50 transition hover:bg-white/10 hover:text-white"
        aria-label="Dismiss notification"
      >
        <X size={16} strokeWidth={2.25} />
      </button>
    </div>
  );
}

export function ToastViewport() {
  const toasts = useSyncExternalStore(subscribeToasts, getToastSnapshot, getServerToastSnapshot);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted || typeof document === "undefined") {
    return null;
  }

  if (!toasts.length) {
    return null;
  }

  return createPortal(
    <div
      className="pointer-events-none fixed inset-x-0 bottom-0 z-[10000] flex flex-col items-center gap-2 px-4 pb-[max(1rem,env(safe-area-inset-bottom))] pt-2"
      aria-label="Notifications"
    >
      {toasts.map((toast) => (
        <ToastRow key={toast.id} toast={toast} />
      ))}
    </div>,
    document.body
  );
}
