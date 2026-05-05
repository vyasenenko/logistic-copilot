export type ToastTone = "success" | "info" | "error";

export type ToastOptions = {
  tone?: ToastTone;
  /** Auto-dismiss delay; set 0 to keep until dismissed. Default 4800ms. */
  durationMs?: number;
};

export type ToastRecord = {
  id: string;
  message: string;
  tone: ToastTone;
};

const MAX_VISIBLE = 5;

/** Stable empty snapshot for `useSyncExternalStore` server snapshot (must not allocate a new `[]` each call). */
const SERVER_TOAST_SNAPSHOT: ToastRecord[] = [];

let toasts: ToastRecord[] = [];
const listeners = new Set<() => void>();
const dismissTimers = new Map<string, ReturnType<typeof setTimeout>>();

function emit() {
  listeners.forEach((listener) => listener());
}

function nextId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `toast_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
}

export function subscribeToasts(onStoreChange: () => void) {
  listeners.add(onStoreChange);
  return () => listeners.delete(onStoreChange);
}

export function getToastSnapshot(): ToastRecord[] {
  return toasts;
}

export function getServerToastSnapshot(): ToastRecord[] {
  return SERVER_TOAST_SNAPSHOT;
}

export function dismissToast(id: string) {
  const timer = dismissTimers.get(id);
  if (timer) {
    clearTimeout(timer);
    dismissTimers.delete(id);
  }
  const next = toasts.filter((item) => item.id !== id);
  if (next.length === toasts.length) return;
  toasts = next;
  emit();
}

/**
 * Show a transient toast at the bottom of the viewport (see ToastViewport in layout).
 * Safe to call from any client-side code; no-op on the server.
 */
export function showToast(message: string, options?: ToastOptions) {
  if (typeof window === "undefined") return;
  const trimmed = message.trim();
  if (!trimmed) return;

  const id = nextId();
  const tone: ToastTone = options?.tone ?? "success";
  const durationMs = options?.durationMs ?? 4800;

  const previousIds = new Set(toasts.map((item) => item.id));
  toasts = [...toasts, { id, message: trimmed, tone }].slice(-MAX_VISIBLE);
  const nextIds = new Set(toasts.map((item) => item.id));
  for (const oldId of previousIds) {
    if (!nextIds.has(oldId)) {
      const timer = dismissTimers.get(oldId);
      if (timer) clearTimeout(timer);
      dismissTimers.delete(oldId);
    }
  }
  emit();

  if (durationMs > 0) {
    const timer = window.setTimeout(() => dismissToast(id), durationMs);
    dismissTimers.set(id, timer);
  }
}
