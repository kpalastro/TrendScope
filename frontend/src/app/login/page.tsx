"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  BarChart3,
  Bookmark,
  Database,
  Lock,
  Mail,
  Radar,
  ShieldCheck,
} from "lucide-react";
import { useAuth } from "@/components/AuthProvider";
import { getToken } from "@/lib/api";

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("admin@trendscope.app");
  const [password, setPassword] = useState("admin123");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (getToken()) router.replace("/");
  }, [router]);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(email.trim(), password);
      const next = new URLSearchParams(window.location.search).get("next");
      router.replace(next && next.startsWith("/") ? next : "/");
    } catch (err) {
      setError((err as Error)?.message || "Sign in failed.");
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[1.05fr_1fr]">
      <section className="relative hidden flex-col justify-between overflow-hidden border-r border-line bg-surface p-10 lg:flex xl:p-14">
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.55]"
          style={{
            backgroundImage:
              "linear-gradient(to right, var(--grid-line) 1px, transparent 1px), linear-gradient(to bottom, var(--grid-line) 1px, transparent 1px)",
            backgroundSize: "44px 44px",
            maskImage: "radial-gradient(ellipse at 30% 20%, black, transparent 72%)",
          }}
          aria-hidden="true"
        />
        <div className="relative">
          <div className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 items-center justify-center rounded-md bg-accent text-accent-ink">
              <Radar className="h-5 w-5" aria-hidden="true" />
            </span>
            <div className="leading-tight">
              <p className="text-sm font-semibold tracking-tight">TrendScope AI</p>
              <p className="text-[0.63rem] font-medium uppercase tracking-[0.16em] text-muted">
                Australian product intelligence
              </p>
            </div>
          </div>

          <h1 className="mt-14 max-w-lg text-4xl font-semibold leading-[1.08] tracking-tight xl:text-[2.75rem]">
            Find the products worth researching, not the ones with the loudest anecdote.
          </h1>
          <p className="mt-5 max-w-md text-[0.95rem] leading-relaxed text-muted">
            TrendScope combines relative search interest, marketplace listings and supplier offers
            into one evidence-aware opportunity score — with missing data left missing, not filled
            with zero.
          </p>

          <dl className="mt-10 grid max-w-lg gap-4 sm:grid-cols-2">
            {[
              {
                icon: BarChart3,
                term: "Trend comparisons",
                detail: "7 / 30 / 90-day windows against a complete baseline.",
              },
              {
                icon: ShieldCheck,
                term: "Honest scoring",
                detail: "Coverage gates and confidence shrinkage, never fabrication.",
              },
              {
                icon: Bookmark,
                term: "Watchlists",
                detail: "Track candidates through research to decision.",
              },
              {
                icon: Database,
                term: "Authorised sources",
                detail: "Mock and CSV in Phase 1; every synthetic row labelled.",
              },
            ].map((item) => {
              const Icon = item.icon;
              return (
                <div key={item.term} className="rounded-md border border-line bg-bg/60 p-3.5">
                  <dt className="flex items-center gap-2 text-sm font-medium">
                    <Icon className="h-4 w-4 text-accent" aria-hidden="true" />
                    {item.term}
                  </dt>
                  <dd className="mt-1 text-xs leading-relaxed text-muted">{item.detail}</dd>
                </div>
              );
            })}
          </dl>
        </div>

        <p className="relative mt-10 max-w-md text-xs leading-relaxed text-muted">
          Growth is relative search interest, not sales. Opportunity scores are estimates, and
          synthetic demo records are not market facts.
        </p>
      </section>

      <section className="flex min-h-screen items-center justify-center px-4 py-12 sm:px-8">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-2.5 lg:hidden">
            <span className="flex h-9 w-9 items-center justify-center rounded-md bg-accent text-accent-ink">
              <Radar className="h-5 w-5" aria-hidden="true" />
            </span>
            <div className="leading-tight">
              <p className="text-sm font-semibold tracking-tight">TrendScope AI</p>
              <p className="text-[0.63rem] font-medium uppercase tracking-[0.16em] text-muted">
                Australian product intelligence
              </p>
            </div>
          </div>

          <p className="eyebrow">Sign in</p>
          <h2 className="mt-1.5 text-2xl font-semibold tracking-tight">Your research desk</h2>
          <p className="mt-2 text-sm leading-relaxed text-muted">
            Use your workspace credentials. The seeded local account is prefilled.
          </p>

          <form onSubmit={onSubmit} className="mt-7 space-y-4">
            <div>
              <label htmlFor="email" className="mb-1.5 block text-xs font-medium text-muted">
                Email
              </label>
              <div className="relative">
                <Mail
                  className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted"
                  aria-hidden="true"
                />
                <input
                  id="email"
                  type="email"
                  className="field pl-8"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  autoComplete="email"
                  required
                />
              </div>
            </div>
            <div>
              <label htmlFor="password" className="mb-1.5 block text-xs font-medium text-muted">
                Password
              </label>
              <div className="relative">
                <Lock
                  className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted"
                  aria-hidden="true"
                />
                <input
                  id="password"
                  type="password"
                  className="field pl-8"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete="current-password"
                  required
                />
              </div>
            </div>

            {error ? (
              <p
                role="alert"
                className="rounded-md border border-line px-3 py-2 text-sm"
                style={{ color: "var(--color-danger)" }}
              >
                {error}
              </p>
            ) : null}

            <button type="submit" className="btn btn-primary w-full" disabled={submitting}>
              {submitting ? "Signing in…" : "Sign in"}
              {!submitting ? <ArrowRight className="h-4 w-4" aria-hidden="true" /> : null}
            </button>
          </form>

          <div className="mt-6 rounded-md border border-line bg-raised px-3.5 py-3">
            <p className="eyebrow">Local demo account</p>
            <p className="mt-1 text-xs leading-relaxed text-muted">
              <span className="num">admin@trendscope.app</span> ·{" "}
              <span className="num">admin123</span>
              <br />
              Seeded by the backend on first boot. Change it before any shared deployment.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
