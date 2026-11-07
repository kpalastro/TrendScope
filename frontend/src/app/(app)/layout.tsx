"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Radar } from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { useAuth } from "@/components/AuthProvider";
import { getToken } from "@/lib/api";

export default function ProtectedLayout({ children }: { children: React.ReactNode }) {
  const { ready } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (ready && !getToken()) {
      router.replace("/login");
    }
  }, [ready, router]);

  if (!ready || !getToken()) {
    return (
      <div className="flex min-h-screen items-center justify-center gap-3 text-sm text-muted">
        <span className="flex h-9 w-9 items-center justify-center rounded-md bg-accent text-accent-ink">
          <Radar className="h-4 w-4" aria-hidden="true" />
        </span>
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-line border-t-accent" />
        Checking your session
      </div>
    );
  }

  return <AppShell>{children}</AppShell>;
}
