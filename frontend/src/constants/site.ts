/** Fallback when NEXT_PUBLIC_SITE_URL is unset or empty: prod site in production builds, localhost in dev. */
function defaultSiteOrigin(): string {
  return process.env.NODE_ENV === "production"
    ? "https://logisticopilot.com"
    : "http://localhost:3000";
}

function resolveSiteUrl(): string {
  const raw = process.env.NEXT_PUBLIC_SITE_URL;
  if (typeof raw === "string") {
    const trimmed = raw.trim();
    if (trimmed.length > 0) {
      return trimmed.replace(/\/+$/, "");
    }
  }
  return defaultSiteOrigin();
}

/** Canonical public origin, no trailing slash (metadata, sitemap, robots). */
export const SITE_URL = resolveSiteUrl();

/** Absolute URL for a site-relative path. */
export function absoluteUrl(path: string): string {
  return path.startsWith("/") ? `${SITE_URL}${path}` : `${SITE_URL}/${path}`;
}
