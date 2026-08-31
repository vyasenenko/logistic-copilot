import type { MetadataRoute } from "next";

import { absoluteUrl, SITE_URL } from "@/constants/site";

/** Authenticated app surfaces — no SEO value, keep crawlers out. */
const DISALLOWED_PATHS = [
  "/admin",
  "/copilot",
  "/dashboard",
  "/users",
  "/settings/",
  "/invite",
  "/extension/",
];

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: DISALLOWED_PATHS,
    },
    sitemap: absoluteUrl("/sitemap.xml"),
    host: SITE_URL,
  };
}
