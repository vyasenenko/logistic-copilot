/** Fallback when NEXT_PUBLIC_API_URL is unset or empty: prod API in production builds, localhost in dev. */
function defaultPublicApiOrigin(): string {
  return process.env.NODE_ENV === "production"
    ? "https://api.logisticopilot.com"
    : "http://localhost:8000";
}

/** Same origin as the empty-env fallback (WebSocket error-path). */
export const DEFAULT_PUBLIC_API_URL = defaultPublicApiOrigin();

function resolvePublicApiUrl(): string {
  const raw = process.env.NEXT_PUBLIC_API_URL;
  if (typeof raw === "string") {
    const trimmed = raw.trim();
    if (trimmed.length > 0) {
      return trimmed;
    }
  }
  return DEFAULT_PUBLIC_API_URL;
}

/** Backend HTTP origin for browser fetch/WebSocket (inlined at Next.js build). */
export const PUBLIC_API_URL = resolvePublicApiUrl();
