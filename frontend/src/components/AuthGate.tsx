"use client";

import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { PUBLIC_API_URL as API_URL } from "@/constants/publicApi";
const AUTH_TOKEN_KEY = "logistic_copilot_auth_token";

interface AuthGateProps {
  children: ReactNode;
}

export function AuthGate({ children }: AuthGateProps) {
  const router = useRouter();
  const [isChecking, setIsChecking] = useState(true);
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  useEffect(() => {
    const token = window.localStorage.getItem(AUTH_TOKEN_KEY);
    if (!token) {
      router.replace("/");
      return;
    }

    fetch(`${API_URL}/api/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((response) => {
        if (response.status === 401 || response.status === 403) {
          window.localStorage.removeItem(AUTH_TOKEN_KEY);
          router.replace("/");
          return;
        }
        if (!response.ok) throw new Error("Session check failed");
        setIsAuthenticated(true);
      })
      .catch(() => {
        window.localStorage.removeItem(AUTH_TOKEN_KEY);
        router.replace("/");
      })
      .finally(() => setIsChecking(false));
  }, [router]);

  if (isChecking || !isAuthenticated) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-200">
        Checking secure session...
      </main>
    );
  }

  return <>{children}</>;
}
