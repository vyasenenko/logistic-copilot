import type { Metadata } from "next";

import { AppShell } from "@/components/AppShell";
import { GoogleAnalytics } from "@/components/GoogleAnalytics";
import { SITE_URL } from "@/constants/site";

import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: "Freight Control Tower",
  description: "Outlook-first logistics workflow dashboard",
  icons: {
    icon: [
      { url: "/icons/favicon.ico", sizes: "any" },
      { url: "/icons/logo.png", type: "image/png" },
    ],
    apple: "/icons/apple-touch-icon.png",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="antialiased" suppressHydrationWarning>
        <GoogleAnalytics />
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
