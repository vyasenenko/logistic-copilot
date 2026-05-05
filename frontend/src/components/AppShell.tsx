"use client";

import type { ReactNode } from "react";

import { ToastViewport } from "@/components/ToastViewport";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <>
      {children}
      <ToastViewport />
    </>
  );
}
