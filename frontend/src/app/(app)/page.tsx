"use client";

import Link from "next/link";
import { RefreshCw } from "lucide-react";
import {
  Card,
  EmptyState,
  ErrorState,
  GrowthValue,
  PageHeader,
  Pill,
  ScoreBadge,
  Skeleton,
} from "@/components/ui";
import { useApi } from "@/lib/useApi";
import type { DashboardResponse, DashboardWidget, WidgetItem } from "@/lib/types";
import { COMPETITION_LABEL, formatDateTime, relativeDays, titleCase } from "@/lib/format";

function Kpi({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="card px-4 py-3.5">
      <p className="eyebrow">{label}</p>
      <p className="num mt-1.5 text-2xl font-semibold leading-none">{value}</p>
      {hint ? <p className="mt-1.5 text-xs text-muted">{hint}</p> : null}
    </div>
  );
}

function WidgetRow({ item }: { item: WidgetItem }) {
  return (
    <li className="flex items-center justify-between gap-3 py-2">
      <div className="min-w-0">
        <Link href={`/products/${item.slug}`} className="link block truncate text-sm">
          {item.name}
        </Link>
        <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[0.7rem] text-muted">
          <span>{item.category ?? "Uncategorised"}</span>
          <span aria-hidden="true">·</span>
          <span>{COMPETITION_LABEL[item.competition_class] ?? titleCase(item.competition_class)} competition</span>
          {item.is_synthetic ? <span className="pill px-1.5 py-0 text-[0.6rem]">synthetic</span> : null}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <div className="hidden text-right sm:block">
          <p className="eyebrow text-[0.6rem]">7d</p>
          <p className="text-xs">
            <GrowthValue growth={{ pct: item.growth_7d_pct, reason: "ok", window_days: 7 }} />
          </p>
        </div>
        <ScoreBadge value={item.opportunity_score} classification={item.classification} size="sm" />
      </div>
    </li>
  );
}

function WidgetCard({ widget }: { widget: DashboardWidget }) {
  return (
    <Card className="flex h-full flex-col p-4">
      <div className="flex items-start justify-between gap-2">
        <h2 className="text-sm font-semibold tracking-tight">{widget.title}</h2>
        <span className="pill">{widget.items.length}</span>
      </div>
      {widget.note ? <p className="mt-1 text-[0.7rem] leading-relaxed text-muted">{widget.note}</p> : null}
      {widget.items.length === 0 ? (
        <p className="mt-6 text-sm text-muted">
          No product currently meets this widget&apos;s conditions. That is a valid result, not an
          error.
        </p>
      ) : (
        <ol className="mt-2 divide-y divide-line">
          {widget.items.map((item) => (
            <WidgetRow key={item.id} item={item} />
          ))}
        </ol>
      )}
    </Card>
  );
}

export default function DashboardPage() {
  const { data, error, loading, reload } = useApi<DashboardResponse>("/dashboard");

  if (loading && !data) {
    return (
      <div className="space-y-6">
        <PageHeader eyebrow="Overview" title="Dashboard" description="Loading the latest snapshot…" />
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton key={index} className="h-[86px]" />
          ))}
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-56" />
          ))}
        </div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="space-y-6">
        <PageHeader eyebrow="Overview" title="Dashboard" />
        <ErrorState message={error} onRetry={reload} />
      </div>
    );
  }

  if (!data) return null;

  const { summary, widgets } = data;
  const syntheticSources = summary.data_sources.filter((source) => source.is_synthetic);

  return (
    <div className="space-y-7">
      <PageHeader
        eyebrow={`Market overview · ${summary.country}`}
        title="Dashboard"
        description={`Snapshot generated ${formatDateTime(summary.generated_at)}. Last ingestion ${relativeDays(summary.last_sync_at)}.`}
        actions={
          <button type="button" className="btn btn-sm" onClick={reload} disabled={loading}>
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} aria-hidden="true" />
            Refresh
          </button>
        }
      />

      {error ? <ErrorState message={error} onRetry={reload} /> : null}

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6" aria-label="Summary">
        <Kpi label="Products monitored" value={summary.products_monitored.toString()} />
        <Kpi label="New this week" value={summary.new_this_week.toString()} hint="First seen in the last 7 days" />
        <Kpi label="Rising demand" value={summary.increasing_demand.toString()} hint="Latest 7-day direction" />
        <Kpi label="Declining demand" value={summary.declining_demand.toString()} hint="Latest 7-day direction" />
        <Kpi label="High opportunity" value={summary.high_opportunity.toString()} hint="Excellent or strong" />
        <Kpi
          label="Average score"
          value={summary.average_opportunity_score === null ? "—" : summary.average_opportunity_score.toFixed(1)}
          hint="Across scored products"
        />
      </section>

      <Card className="flex flex-wrap items-center justify-between gap-4 p-4">
        <div className="min-w-0">
          <p className="eyebrow">Sources</p>
          <ul className="mt-2 flex flex-wrap items-center gap-2">
            {summary.data_sources.map((source) => (
              <li key={source.id} className="flex items-center gap-1.5">
                <span
                  className={`h-1.5 w-1.5 rounded-full ${source.enabled ? "bg-good" : "bg-muted"}`}
                  aria-hidden="true"
                />
                <span className="text-xs">{source.provider_name}</span>
                {source.is_synthetic ? <Pill tone="amber">synthetic</Pill> : null}
                {!source.enabled ? <Pill>disabled</Pill> : null}
              </li>
            ))}
          </ul>
        </div>
        <p className="max-w-sm text-[0.7rem] leading-relaxed text-muted">
          {syntheticSources.length
            ? `${syntheticSources.length} synthetic source${syntheticSources.length === 1 ? "" : "s"} active. Synthetic records are labelled throughout and are not market facts.`
            : "No synthetic sources active."}
        </p>
      </Card>

      <section className="grid gap-4 lg:grid-cols-2" aria-label="Trend widgets">
        {widgets.map((widget) => (
          <WidgetCard key={widget.key} widget={widget} />
        ))}
      </section>

      {widgets.every((widget) => widget.items.length === 0) ? (
        <EmptyState
          title="No scored products yet"
          description="Run a mock sync from the Data sources page to populate trends, metrics and opportunity scores."
        />
      ) : null}
    </div>
  );
}
