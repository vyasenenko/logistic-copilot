/** Must match chrome-extension/content-dash-auth-bridge.js filter + version. */
export const DASHBOARD_EXTENSION_LOGOUT_MESSAGE = {
  source: "logistic-copilot-dashboard",
  action: "extension-session-clear",
  v: 1 as const,
};

/**
 * After dashboard web logout: clear the extension's stored JWT.
 * Primary path: postMessage → content script → background (no extension ID env required).
 * Optional: NEXT_PUBLIC_CHROME_EXTENSION_ID triggers chrome.runtime.sendMessage as extra path.
 *
 * Backend note: `/api/auth/logout` revokes only the bearer session presented there; extension
 * OAuth issues a separate server session — this call only wipes local extension storage + UI refresh.
 */
export function notifyCopilotChromeExtensionLogout(): void {
  if (typeof window === "undefined") return;
  try {
    const origin = window.location.origin;
    if (!origin || origin === "null") return;
    window.postMessage(DASHBOARD_EXTENSION_LOGOUT_MESSAGE, origin);
  } catch {
    /* ignore */
  }

  const extId = process.env.NEXT_PUBLIC_CHROME_EXTENSION_ID?.trim();
  if (!extId) return;
  const runtime = (window as Window & { chrome?: { runtime?: ChromeRuntimeShim } }).chrome?.runtime;
  if (!runtime?.sendMessage) return;
  try {
    runtime.sendMessage(extId, { type: "EXTENSION_SESSION_LOGOUT" }, () => {
      void runtime.lastError?.message;
    });
  } catch {
    /* ignore */
  }
}

type ChromeRuntimeShim = {
  sendMessage: (
    extensionId: string,
    message: unknown,
    responseCallback?: (response: unknown) => void,
  ) => void;
  lastError?: { message?: string };
};
