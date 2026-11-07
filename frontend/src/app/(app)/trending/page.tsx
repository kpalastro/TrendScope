"use client";

import { useState } from "react";
import {
  CalendarClock,
  Gauge,
  LineChart,
  RefreshCw,
  Rocket,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { ProductTable } from "@/components/ProductTable";
import {
  Card,
  EmptyState,
  ErrorState,
  PageHeader,
  Skeleton,
} from "@/components/ui";
import { queryString } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { DiscoverResponse } from "@/lib/types";

type View = "rising" | "declining" | "emerging" | "opportunities" | "seasonal";

const VIEWS: { key: View; label: string; icon: typeof TrendingUp; blurb: string }[] = [
  {
    key: "rising",
    label: "Rising",
    icon: TrendingUp,
    blurb: "Products whose search interest grew over the selected window.",
  },
  {
    key: "declining",
    label: "Declining",
    icon: TrendingDown,
    blurb: "Products losing search interest — useful for exit and pricing calls.",
  },
  {
    key: "emerging",
    label: "Emerging",
    icon: Rocket,
    blurb: "Newly discovered and rising. Both conditions must hold.",
  },
  {
    key: "opportunities",
    label: "Opportunities",
    icon: Gauge,
    blurb: "Coverage-gated opportunity scores. Low-coverage products are excluded.",
  },
  {
    key: "seasonal",
    label: "Seasonal",
    icon: CalendarClock,
    blurb: "Seasonality index above 1.0 needs at least 12 months of history.",
  },
];

export default function TrendingPage() {
  const [view, setView] = useState<View>("rising");
  const [windowDays, setWindowDays] = useState(7);
  const [sinceDays, setSinceDays] = useState(30);
  const [minScore, setMinScore] = useState(60);
  const [horizon, setHorizon] = useState(90);

  const path = (() => {
    if (view === "rising" || view === "declining") {
      return `/trending${queryString({
        window: windowDays,
        direction: view === "rising" ? "rising" : "declining",
        limit: 50,
      })}`;
    }
    if (view === "emerging") return `/emerging${queryString({ since_days: sinceDays, limit: 50 })}`;
    if (view === "opportunities")
      return `/opportunities${queryString({ min_score: minScore, min_coverage: 60, limit: 50 })}`;
    return `/seasonal${queryString({ horizon_days: horizon, limit: 50 })}`;
  })();

  const { data, error, loading, reload } = useApi<DiscoverResponse>(path);
  const activeView = VIEWS.find((item) => item.key === view) ?? VIEWS[0];
  const items = data?.data ?? [];

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Discovery"
        title="Trending"
        description="Ranked views over stored observations. Every list states its ranking rule and refuses to treat missing growth as zero."
        actions={
          <button type="button" className="btn btn-sm" onClick={reload} disabled={loading}>
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} aria-hidden="true" />
            Refresh
          </button>
        }
      />

      <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Trend views">
        {VIEWS.map((item) => {
          const Icon = item.icon;
          const active = view === item.key;
          return (
            <button
              key={item.key}
              type="button"
              role="tab"
              aria-selected={active}
              className={`btn btn-sm ${active ? "border-accent text-accent" : ""}`}
              onClick={() => setView(item.key)}
              style={active ? { background: "color-mix(in srgb, var(--color-accent) 10%, transparent)" } : undefined}
            >
              <Icon className="h-3.5 w-3.5" aria-hidden="true" />
              {item.label}
            </button>
          );
        })}
      </div>

      <Card className="flex flex-wrap items-end justify-between gap-3 p-3.5">
        <div className="min-w-0">
          <p className="text-sm font-medium">{activeView.label}</p>
          <p className="mt-0.5 text-xs text-muted">{activeView.blurb}</p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          {(view === "rising" || view === "declining") && (
            <div>
              <label htmlFor="window" className="eyebrow mb-1 block">
                Window
              </label>
              <select
                id="window"
                className="field w-auto"
                value={windowDays}
                onChange={(event) => setWindowDays(Number(event.target.value))}
              >
                <option value={7}>7 days</option>
                <option value={30}>30 days</option>
                <option value={90}>90 days</option>
              </select>
            </div>
          )}
          {view === "emerging" && (
            <div>
              <label htmlFor="since" className="eyebrow mb-1 block">
                Discovered within
              </label>
              <select
                id="since"
                className="field w-auto"
                value={sinceDays}
                onChange={(event) => setSinceDays(Number(event.target.value))}
              >
                <option value={7}>7 days</option>
                <option value={30}>30 days</option>
                <option value={90}>90 days</option>
              </select>
            </div>
          )}
          {view === "opportunities" && (
            <div>
              <label htmlFor="min-score" className="eyebrow mb-1 block">
                Min score
              </label>
              <select
                id="min-score"
                className="field w-auto"
                value={minScore}
                onChange={(event) => setMinScore(Number(event.target.value))}
              >
                <option value={0}>Any score</option>
                <option value={50}>50+</option>
                <option value={60}>60+</option>
                <option value={70}>70+</option>
                <option value={80}>80+</option>
              </select>
            </div>
          )}
          {view === "seasonal" && (
            <div>
              <label htmlFor="horizon" className="eyebrow mb-1 block">
                Upcoming horizon
              </label>
              <select
                id="horizon"
                className="field w-auto"
                value={horizon}
                onChange={(event) => setHorizon(Number(event.target.value))}
              >
                <option value={45}>45 days</option>
                <option value={90}>90 days</option>
              </select>
            </div>
          )}
        </div>
      </Card>

      {data?.meta?.note ? (
        <p className="rounded-md border border-line bg-raised px-3.5 py-2.5 text-xs leading-relaxed text-muted">
          {data.meta.note}
        </p>
      ) : null}

      {error ? <ErrorState message={error} onRetry={reload} /> : null}

      <Card>
        {loading && !data ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 6 }).map((_, index) => (
              <Skeleton key={index} className="h-11" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <EmptyState
            icon={<LineChart className="h-5 w-5" aria-hidden="true" />}
            title="Nothing meets this view's conditions"
            description="That is a valid outcome. Try a wider window, a lower score threshold, or run a fresh sync — products with insufficient baseline data are deliberately excluded."
          />
        ) : (
          <ProductTable items={items} />
        )}
      </Card>

      {items.length ? (
        <p className="text-xs text-muted">
          Showing {items.length} product{items.length === 1 ? "" : "s"}. Growth is relative search
          interest, not sales.
        </p>
      ) : null}
    </div>
  );
}
