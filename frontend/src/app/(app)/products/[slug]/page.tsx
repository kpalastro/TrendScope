"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  BookmarkPlus,
  CheckCircle2,
  ClipboardCheck,
  Database,
  Info,
  LineChart as LineChartIcon,
  Plus,
  Sparkles,
  TriangleAlert,
  XCircle,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useAuth } from "@/components/AuthProvider";
import {
  Card,
  DataQualityChip,
  ErrorState,
  GrowthValue,
  KeyValue,
  Pill,
  ScoreBadge,
  Skeleton,
} from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { ObservationRow, ProductDetail, Recommendation } from "@/lib/types";
import {
  CLASSIFICATION_LABEL,
  COMPETITION_LABEL,
  COMPONENT_LABEL,
  formatDate,
  formatDateTime,
  formatShortDate,
  GROWTH_REASON,
  money,
  pct,
  titleCase,
} from "@/lib/format";

function ScoreDial({ value, classification }: { value: number | null; classification: string | null }) {
  const radius = 52;
  const circumference = 2 * Math.PI * radius;
  const filled = value === null ? 0 : Math.max(0, Math.min(100, value)) / 100;
  const tone =
    classification === "excellent" || classification === "strong"
      ? "var(--color-good)"
      : classification === "moderate"
        ? "var(--color-amber)"
        : "var(--color-accent)";
  return (
    <div className="flex w-[132px] shrink-0 flex-col items-center">
      <div className="h-[132px] w-[132px]">
        <svg viewBox="0 0 120 120" className="h-full w-full" role="img" aria-label={`Opportunity score ${value === null ? "unavailable" : value.toFixed(1)} out of 100`}>
          <circle cx="60" cy="60" r={radius} fill="none" stroke="var(--color-line)" strokeWidth="8" />
          {value !== null ? (
            <circle
              cx="60"
              cy="60"
              r={radius}
              fill="none"
              stroke={tone}
              strokeWidth="8"
              strokeLinecap="round"
              strokeDasharray={`${circumference * filled} ${circumference}`}
              transform="rotate(-90 60 60)"
            />
          ) : null}
          <text
            x="60"
            y="66"
            textAnchor="middle"
            fontSize="26"
            fontWeight="600"
            fill="var(--color-ink)"
            fontFamily="IBM Plex Mono, monospace"
          >
            {value === null ? "—" : value.toFixed(1)}
          </text>
        </svg>
      </div>
      <span className="mt-1 text-center text-[0.68rem] leading-tight text-muted">
        {classification ? CLASSIFICATION_LABEL[classification] ?? classification : "Not scored"}
      </span>
    </div>
  );
}

function seriesKey(item: ProductDetail["trend_series"][number]): string {
  return `${item.metric_name}|${item.metric_type}`;
}

function TrendChart({ detail }: { detail: ProductDetail }) {
  const [mounted, setMounted] = useState(false);
  const series = detail.trend_series;
  const [metric, setMetric] = useState(series[0] ? seriesKey(series[0]) : "search_interest|search_interest");
  useEffect(() => setMounted(true), []);

  const active = series.find((item) => seriesKey(item) === metric) ?? series[0];
  const points = useMemo(
    () => (active?.points ?? []).filter((point) => point.value !== null),
    [active],
  );
  const unitLabel =
    active?.metric_name === "search_interest"
      ? "Relative search interest (index, not sales)"
      : active?.metric_name === "marketplace_avg_price"
        ? "Marketplace average price (AUD)"
        : titleCase(active?.metric_name ?? "");

  if (!series.length) {
    return (
      <Card className="p-5">
        <p className="flex items-center gap-2 text-sm text-muted">
          <LineChartIcon className="h-4 w-4" aria-hidden="true" />
          No trend observations recorded for this product.
        </p>
      </Card>
    );
  }

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold tracking-tight">Trend history</h2>
          <p className="mt-1 text-xs text-muted">{unitLabel}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {active?.is_synthetic ? <Pill tone="amber">synthetic source</Pill> : null}
          {series.length > 1 ? (
            <select
              className="field w-auto text-xs"
              value={metric}
              onChange={(event) => setMetric(event.target.value)}
              aria-label="Trend metric"
            >
              {series.map((item) => (
                <option key={seriesKey(item)} value={seriesKey(item)}>
                  {titleCase(item.metric_name)} · {titleCase(item.metric_type)}
                </option>
              ))}
            </select>
          ) : null}
        </div>
      </div>

      <div className="mt-4 h-[280px] w-full">
        {mounted ? (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={points} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
              <defs>
                <linearGradient id="trend-fill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--color-accent)" stopOpacity={0.28} />
                  <stop offset="100%" stopColor="var(--color-accent)" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="var(--color-line)" strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="date"
                tickFormatter={(value) => formatShortDate(String(value))}
                minTickGap={36}
                tick={{ fill: "var(--color-muted)", fontSize: 10 }}
                axisLine={{ stroke: "var(--color-line)" }}
                tickLine={false}
              />
              <YAxis
                tick={{ fill: "var(--color-muted)", fontSize: 10 }}
                axisLine={false}
                tickLine={false}
                width={54}
                domain={active?.metric_name === "search_interest" ? [0, 100] : ["auto", "auto"]}
              />
              <Tooltip
                labelFormatter={(value) => formatDate(String(value))}
                formatter={(value: number) => [
                  active?.metric_name === "marketplace_avg_price"
                    ? money(value)
                    : Number(value).toFixed(1),
                  titleCase(active?.metric_name ?? "value"),
                ]}
                contentStyle={{
                  background: "var(--color-surface)",
                  border: "1px solid var(--color-line)",
                  borderRadius: 8,
                  fontSize: 12,
                  color: "var(--color-ink)",
                }}
              />
              <Area
                type="monotone"
                dataKey="value"
                stroke="var(--color-accent)"
                strokeWidth={2}
                fill="url(#trend-fill)"
                dot={false}
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <Skeleton className="h-full w-full" />
        )}
      </div>
      <p className="mt-3 text-[0.7rem] text-muted">
        {points.length} observations · latest {formatDate(points[points.length - 1]?.date)}. Search
        interest is relative, not search volume or sales.
      </p>
    </Card>
  );
}

function Breakdown({ detail }: { detail: ProductDetail }) {
  const breakdown = detail.score_breakdown;
  if (!breakdown) {
    return (
      <Card className="p-5">
        <h2 className="text-sm font-semibold tracking-tight">Score breakdown</h2>
        <p className="mt-2 text-sm text-muted">
          Not scored yet. A score appears once an active scoring profile is applied to this product.
        </p>
      </Card>
    );
  }
  const components = Object.entries(breakdown.components);
  const available = components.filter(([, component]) => component.status !== "unavailable");
  const missing = components.filter(([, component]) => component.status === "unavailable");

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold tracking-tight">Score breakdown</h2>
          <p className="mt-1 text-xs text-muted">
            Profile {breakdown.profile.name ?? "—"} v{breakdown.profile.version ?? "—"} · calculated{" "}
            {formatDate(breakdown.calculated_on)}
          </p>
        </div>
        <div className="text-right">
          <p className="eyebrow">Adjusted / raw</p>
          <p className="num text-sm font-semibold">
            {breakdown.score.toFixed(1)} <span className="text-muted">/ {breakdown.score_raw.toFixed(1)}</span>
          </p>
        </div>
      </div>

      <dl className="mt-4 space-y-3">
        {available.map(([key, component]) => {
          const value = component.score ?? 0;
          const tone =
            value >= 70 ? "var(--color-good)" : value >= 45 ? "var(--color-amber)" : "var(--color-danger)";
          return (
            <div key={key}>
              <div className="flex items-baseline justify-between gap-3 text-sm">
                <dt className="font-medium">
                  {component.label ?? COMPONENT_LABEL[key] ?? titleCase(key)}
                  <span className="ml-2 text-[0.68rem] font-normal text-muted">
                    weight {(component.weight * 100).toFixed(0)}%
                  </span>
                </dt>
                <dd className="num text-sm">{value.toFixed(1)}</dd>
              </div>
              <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-raised" aria-hidden="true">
                <div className="h-full rounded-full" style={{ width: `${value}%`, background: tone }} />
              </div>
              {component.raw ? (
                <p className="num mt-1 text-[0.65rem] text-muted">
                  {Object.entries(component.raw)
                    .filter(([, raw]) => raw !== null && raw !== undefined)
                    .map(([field, raw]) =>
                      field.includes("pct") ? `${field}: ${pct(Number(raw))}` : `${field}: ${raw}`,
                    )
                    .join(" · ")}
                </p>
              ) : null}
            </div>
          );
        })}
      </dl>

      {missing.length ? (
        <div className="mt-4 rounded-md border border-line bg-raised px-3 py-2.5">
          <p className="text-xs font-medium">Unavailable components (weights renormalised)</p>
          <ul className="mt-1.5 space-y-1 text-xs text-muted">
            {missing.map(([key, component]) => (
              <li key={key}>
                <span className="font-medium text-ink">{component.label ?? COMPONENT_LABEL[key] ?? titleCase(key)}</span>
                {" — "}
                {component.reason ?? "insufficient evidence"}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap gap-x-5 gap-y-1 border-t border-line pt-3 text-[0.7rem] text-muted">
        <span>Coverage {breakdown.coverage_pct.toFixed(0)}%</span>
        <span>Confidence {(breakdown.confidence * 100).toFixed(0)}%</span>
        <span>Shrunk toward 50 when coverage is low</span>
      </div>
    </Card>
  );
}

function DataQualityPanel({ detail }: { detail: ProductDetail }) {
  const quality = detail.data_quality;
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between gap-2">
        <h2 className="text-sm font-semibold tracking-tight">Data quality</h2>
        <DataQualityChip quality={quality} />
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
        <div>
          <p className="eyebrow">Coverage</p>
          <p className="num mt-0.5">{quality.coverage_pct.toFixed(0)}%</p>
        </div>
        <div>
          <p className="eyebrow">Confidence</p>
          <p className="num mt-0.5">{(quality.confidence * 100).toFixed(0)}%</p>
        </div>
        <div>
          <p className="eyebrow">Synthetic share</p>
          <p className="num mt-0.5">{(quality.synthetic_share * 100).toFixed(0)}%</p>
        </div>
        <div>
          <p className="eyebrow">Last updated</p>
          <p className="mt-0.5 text-xs">{formatDateTime(quality.last_updated)}</p>
        </div>
      </div>

      <div className="mt-3 border-t border-line pt-3">
        <p className="eyebrow">Sources</p>
        <ul className="mt-1.5 flex flex-wrap gap-1.5">
          {quality.sources.length ? (
            quality.sources.map((source) => <Pill key={source}>{source}</Pill>)
          ) : (
            <li className="text-xs text-muted">No source has returned data for this product.</li>
          )}
        </ul>
      </div>

      {quality.missing_components.length ? (
        <div className="mt-3 border-t border-line pt-3">
          <p className="eyebrow">Missing components</p>
          <p className="mt-1 text-xs text-muted">
            {quality.missing_components
              .map((key) => COMPONENT_LABEL[key] ?? titleCase(key))
              .join(", ")}
          </p>
        </div>
      ) : null}

      {quality.warnings.length ? (
        <ul className="mt-3 space-y-1.5 border-t border-line pt-3">
          {quality.warnings.map((warning, index) => (
            <li key={index} className="flex items-start gap-2 text-xs leading-relaxed text-muted">
              <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber" aria-hidden="true" />
              {warning}
            </li>
          ))}
        </ul>
      ) : null}

      <p className="mt-3 border-t border-line pt-3 text-[0.7rem] leading-relaxed text-muted">
        {detail.disclaimer}
      </p>
    </Card>
  );
}

function verdictTone(verdict: string): "good" | "amber" | "danger" {
  if (verdict === "recommended") return "good";
  if (verdict === "not_recommended") return "danger";
  return "amber";
}

function RecommendationPanel({ recommendation }: { recommendation: Recommendation }) {
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold tracking-tight">
          <ClipboardCheck className="h-4 w-4 text-accent" aria-hidden="true" /> Recommendation
        </h2>
        <Pill tone={verdictTone(recommendation.verdict)}>{recommendation.label}</Pill>
      </div>
      <p className="mt-2 text-xs leading-relaxed text-muted">{recommendation.summary}</p>

      <ul className="mt-3 divide-y divide-line">
        {recommendation.checks.map((check) => (
          <li key={check.key} className="flex items-start justify-between gap-3 py-2 text-xs">
            <span className="min-w-0">
              <span className="font-medium">{check.label}</span>
              <span className="mt-0.5 block text-[0.7rem] leading-relaxed text-muted">
                {check.detail}
              </span>
            </span>
            <span className="shrink-0 pt-0.5">
              {check.status === "pass" ? (
                <CheckCircle2 className="h-4 w-4 text-good" aria-label="pass" />
              ) : check.status === "fail" ? (
                <XCircle className="h-4 w-4 text-danger" aria-label="fail" />
              ) : (
                <Pill tone="amber">missing</Pill>
              )}
            </span>
          </li>
        ))}
      </ul>

      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 border-t border-line pt-3 text-xs">
        <div>
          <dt className="text-muted">Supplier cost</dt>
          <dd className="num">{money(recommendation.economics.product_cost)}</dd>
        </div>
        <div>
          <dt className="text-muted">Delivery</dt>
          <dd className="num">{money(recommendation.economics.delivery_cost)}</dd>
        </div>
        <div>
          <dt className="text-muted">Est. profit / unit</dt>
          <dd className="num">{money(recommendation.economics.estimated_profit_per_unit)}</dd>
        </div>
        <div>
          <dt className="text-muted">Est. margin</dt>
          <dd className="num">
            {recommendation.economics.estimated_margin_pct === null
              ? "—"
              : `${recommendation.economics.estimated_margin_pct.toFixed(1)}%`}
          </dd>
        </div>
      </dl>

      {recommendation.next_actions.length ? (
        <div className="mt-3 border-t border-line pt-3">
          <p className="eyebrow">Before recommending</p>
          <ul className="mt-1 space-y-1 text-[0.7rem] leading-relaxed text-muted">
            {recommendation.next_actions.map((action) => (
              <li key={action.key}>• {action.action}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <p className="mt-3 border-t border-line pt-3 text-[0.65rem] leading-relaxed text-muted">
        {recommendation.disclaimer}
      </p>
    </Card>
  );
}

const METRIC_TYPES = [
  "search_interest",
  "marketplace_listing",
  "marketplace_price",
  "marketplace_review",
  "social_engagement",
  "advertising",
  "actual_sales",
  "estimated_sales",
  "supplier_cost",
  "other",
];

function ManualEvidence({ slug, onSaved }: { slug: string; onSaved: () => void }) {
  const [tab, setTab] = useState<"observation" | "supplier">("supplier");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ message: string; tone: "ok" | "error" } | null>(null);
  const [observation, setObservation] = useState({
    metric_name: "search_interest",
    metric_type: "search_interest",
    value: "",
    observation_date: new Date().toISOString().slice(0, 10),
    provider_name: "Manual research",
    source_url: "",
    verification_status: "unverified",
    data_quality: "unknown",
    notes: "",
  });
  const [quote, setQuote] = useState({
    supplier_name: "",
    country: "CN",
    product_cost: "",
    shipping_cost: "",
    currency: "AUD",
    minimum_order_quantity: "1",
    lead_time_days: "",
  });

  async function submitObservation(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setNotice(null);
    try {
      await api.post(`/products/${slug}/observations`, {
        ...observation,
        value: Number(observation.value),
        granularity: "daily",
        source_url: observation.source_url || null,
        notes: observation.notes || null,
      });
      setNotice({ message: "Observation recorded with provenance.", tone: "ok" });
      setObservation((current) => ({ ...current, value: "", notes: "", source_url: "" }));
      onSaved();
    } catch (err) {
      setNotice({ message: (err as Error).message, tone: "error" });
    } finally {
      setBusy(false);
    }
  }

  async function submitQuote(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setNotice(null);
    try {
      await api.post(`/products/${slug}/suppliers`, {
        supplier_name: quote.supplier_name,
        country: quote.country || null,
        product_cost: quote.product_cost,
        shipping_cost: quote.shipping_cost || "0",
        currency: quote.currency,
        minimum_order_quantity: Number(quote.minimum_order_quantity) || 1,
        lead_time_days: quote.lead_time_days ? Number(quote.lead_time_days) : null,
      });
      setNotice({ message: "Supplier quote recorded; recommendation recalculated.", tone: "ok" });
      setQuote((current) => ({ ...current, supplier_name: "", product_cost: "", shipping_cost: "" }));
      onSaved();
    } catch (err) {
      setNotice({ message: (err as Error).message, tone: "error" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold tracking-tight">
          <Plus className="h-4 w-4" aria-hidden="true" /> Record evidence
        </h2>
        <div className="flex gap-1.5">
          <button
            type="button"
            className={`btn btn-sm ${tab === "supplier" ? "btn-primary" : ""}`}
            onClick={() => setTab("supplier")}
          >
            Supplier quote
          </button>
          <button
            type="button"
            className={`btn btn-sm ${tab === "observation" ? "btn-primary" : ""}`}
            onClick={() => setTab("observation")}
          >
            Observation
          </button>
        </div>
      </div>
      <p className="mt-1 text-[0.7rem] leading-relaxed text-muted">
        Manual evidence is allowed; invented evidence is not. Supplier prices and delivery costs are
        required before a recommendation can pass.
      </p>

      {notice ? (
        <p
          role="status"
          className="mt-2 text-xs"
          style={{ color: notice.tone === "error" ? "var(--color-danger)" : "var(--color-good)" }}
        >
          {notice.message}
        </p>
      ) : null}

      {tab === "supplier" ? (
        <form className="mt-3 grid gap-2 sm:grid-cols-2" onSubmit={submitQuote}>
          <label className="text-xs sm:col-span-2">
            <span className="eyebrow block">Supplier name</span>
            <input
              className="field mt-1 w-full"
              required
              minLength={2}
              value={quote.supplier_name}
              onChange={(event) => setQuote({ ...quote, supplier_name: event.target.value })}
            />
          </label>
          <label className="text-xs">
            <span className="eyebrow block">Unit cost</span>
            <input
              className="field mt-1 w-full"
              required
              inputMode="decimal"
              value={quote.product_cost}
              onChange={(event) => setQuote({ ...quote, product_cost: event.target.value })}
            />
          </label>
          <label className="text-xs">
            <span className="eyebrow block">Delivery / unit</span>
            <input
              className="field mt-1 w-full"
              inputMode="decimal"
              value={quote.shipping_cost}
              onChange={(event) => setQuote({ ...quote, shipping_cost: event.target.value })}
            />
          </label>
          <label className="text-xs">
            <span className="eyebrow block">Supplier country</span>
            <input
              className="field mt-1 w-full"
              maxLength={2}
              value={quote.country}
              onChange={(event) => setQuote({ ...quote, country: event.target.value.toUpperCase() })}
            />
          </label>
          <label className="text-xs">
            <span className="eyebrow block">Currency</span>
            <input
              className="field mt-1 w-full"
              maxLength={3}
              value={quote.currency}
              onChange={(event) => setQuote({ ...quote, currency: event.target.value.toUpperCase() })}
            />
          </label>
          <label className="text-xs">
            <span className="eyebrow block">MOQ</span>
            <input
              className="field mt-1 w-full"
              inputMode="numeric"
              value={quote.minimum_order_quantity}
              onChange={(event) =>
                setQuote({ ...quote, minimum_order_quantity: event.target.value })
              }
            />
          </label>
          <label className="text-xs">
            <span className="eyebrow block">Lead time (days)</span>
            <input
              className="field mt-1 w-full"
              inputMode="numeric"
              value={quote.lead_time_days}
              onChange={(event) => setQuote({ ...quote, lead_time_days: event.target.value })}
            />
          </label>
          <div className="sm:col-span-2">
            <button type="submit" className="btn btn-sm btn-primary" disabled={busy}>
              {busy ? "Saving…" : "Save supplier quote"}
            </button>
          </div>
        </form>
      ) : (
        <form className="mt-3 grid gap-2 sm:grid-cols-2" onSubmit={submitObservation}>
          <label className="text-xs">
            <span className="eyebrow block">Metric name</span>
            <input
              className="field mt-1 w-full"
              required
              value={observation.metric_name}
              onChange={(event) =>
                setObservation({ ...observation, metric_name: event.target.value })
              }
            />
          </label>
          <label className="text-xs">
            <span className="eyebrow block">Metric type</span>
            <select
              className="field mt-1 w-full"
              value={observation.metric_type}
              onChange={(event) =>
                setObservation({ ...observation, metric_type: event.target.value })
              }
            >
              {METRIC_TYPES.map((value) => (
                <option key={value} value={value}>
                  {titleCase(value)}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs">
            <span className="eyebrow block">Value</span>
            <input
              className="field mt-1 w-full"
              required
              inputMode="decimal"
              value={observation.value}
              onChange={(event) => setObservation({ ...observation, value: event.target.value })}
            />
          </label>
          <label className="text-xs">
            <span className="eyebrow block">Observation date</span>
            <input
              type="date"
              className="field mt-1 w-full"
              required
              max={new Date().toISOString().slice(0, 10)}
              value={observation.observation_date}
              onChange={(event) =>
                setObservation({ ...observation, observation_date: event.target.value })
              }
            />
          </label>
          <label className="text-xs">
            <span className="eyebrow block">Provider / method</span>
            <input
              className="field mt-1 w-full"
              value={observation.provider_name}
              onChange={(event) =>
                setObservation({ ...observation, provider_name: event.target.value })
              }
            />
          </label>
          <label className="text-xs">
            <span className="eyebrow block">Source URL</span>
            <input
              className="field mt-1 w-full"
              value={observation.source_url}
              onChange={(event) =>
                setObservation({ ...observation, source_url: event.target.value })
              }
            />
          </label>
          <label className="text-xs">
            <span className="eyebrow block">Verification</span>
            <select
              className="field mt-1 w-full"
              value={observation.verification_status}
              onChange={(event) =>
                setObservation({ ...observation, verification_status: event.target.value })
              }
            >
              <option value="unverified">Unverified</option>
              <option value="estimated">Estimated</option>
              <option value="verified">Verified</option>
            </select>
          </label>
          <label className="text-xs">
            <span className="eyebrow block">Data quality</span>
            <select
              className="field mt-1 w-full"
              value={observation.data_quality}
              onChange={(event) =>
                setObservation({ ...observation, data_quality: event.target.value })
              }
            >
              <option value="unknown">Unknown</option>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </select>
          </label>
          <label className="text-xs sm:col-span-2">
            <span className="eyebrow block">Notes</span>
            <input
              className="field mt-1 w-full"
              value={observation.notes}
              onChange={(event) => setObservation({ ...observation, notes: event.target.value })}
            />
          </label>
          <div className="sm:col-span-2">
            <button type="submit" className="btn btn-sm btn-primary" disabled={busy}>
              {busy ? "Saving…" : "Save observation"}
            </button>
          </div>
        </form>
      )}
    </Card>
  );
}

function RecentObservations({ slug }: { slug: string }) {
  const { data, error, loading } = useApi<{ observations: ObservationRow[] }>(
    `/products/${slug}/observations?limit=8`,
  );
  return (
    <Card className="p-5">
      <h2 className="text-sm font-semibold tracking-tight">Recent observations</h2>
      <p className="mt-0.5 text-xs leading-relaxed text-muted">
        Provider, verification and revision are stored on every observation. When a provider
        revises a value for the same date and metric, the row is updated in place, its revision
        increases and the earlier values stay in its history.
      </p>
      {loading && !data ? (
        <Skeleton className="mt-3 h-28" />
      ) : data?.observations.length ? (
        <div className="mt-3 overflow-x-auto">
          <table className="table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Metric</th>
                <th className="text-right">Value</th>
                <th>Provider</th>
                <th>Revision</th>
              </tr>
            </thead>
            <tbody>
              {data.observations.map((observation) => (
                <tr key={observation.id}>
                  <td className="whitespace-nowrap text-xs">
                    {formatDate(observation.observation_date)}
                  </td>
                  <td className="text-xs">
                    {observation.metric_name}
                    <span className="block text-[0.65rem] text-muted">
                      {observation.metric_type} · {observation.granularity}
                    </span>
                  </td>
                  <td className="num whitespace-nowrap text-right text-xs">
                    {observation.value}
                    {observation.unit ? (
                      <span className="text-muted"> {observation.unit}</span>
                    ) : null}
                  </td>
                  <td className="text-xs">
                    {observation.provider_name ?? "—"}
                    <span className="block text-[0.65rem] text-muted">
                      {observation.verification_status} · {observation.data_quality}
                      {observation.is_synthetic ? " · synthetic" : ""}
                    </span>
                  </td>
                  <td>
                    <Pill tone={observation.revision > 1 ? "accent" : "muted"}>
                      v{observation.revision}
                    </Pill>
                    {observation.updated_at ? (
                      <span className="mt-0.5 block text-[0.65rem] text-muted">
                        revised {formatDateTime(observation.updated_at)}
                      </span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="mt-3 text-sm text-muted">
          {error ?? "No observations recorded for this product yet."}
        </p>
      )}
    </Card>
  );
}

export default function ProductDetailPage() {
  const params = useParams<{ slug: string }>();
  const slug = Array.isArray(params?.slug) ? params.slug[0] : params?.slug;
  const { canWrite } = useAuth();
  const { data, error, loading, reload } = useApi<ProductDetail>(slug ? `/products/${slug}` : null);
  const [watchState, setWatchState] = useState<"idle" | "busy" | "done" | "exists">("idle");
  const [watchError, setWatchError] = useState<string | null>(null);

  async function addToWatchlist() {
    if (!data) return;
    setWatchState("busy");
    setWatchError(null);
    try {
      await api.post("/watchlist", { product_id: data.id, status: "discovered" });
      setWatchState("done");
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setWatchState("exists");
      } else {
        setWatchState("idle");
        setWatchError((err as Error).message);
      }
    }
  }

  if (loading && !data) {
    return (
      <div className="space-y-5">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-44" />
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
          <Skeleton className="h-80" />
          <Skeleton className="h-80" />
        </div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="space-y-5">
        <Link href="/products" className="link inline-flex items-center gap-1.5 text-sm">
          <ArrowLeft className="h-4 w-4" aria-hidden="true" /> Back to products
        </Link>
        <ErrorState message={error} onRetry={reload} />
      </div>
    );
  }

  if (!data) return null;

  const growthItems = [
    { label: "7 days", growth: data.growth.d7 },
    { label: "30 days", growth: data.growth.d30 },
    { label: "90 days", growth: data.growth.d90 },
  ];

  return (
    <div className="space-y-5">
      <Link href="/products" className="link inline-flex items-center gap-1.5 text-sm">
        <ArrowLeft className="h-4 w-4" aria-hidden="true" /> Back to products
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-line pb-5">
        <div className="min-w-0">
          <p className="eyebrow">
            {data.category ? (
              <Link href={`/products?category_id=${data.category.id}`} className="hover:text-ink">
                {data.category.path.replace(/\//g, " / ")}
              </Link>
            ) : (
              "Uncategorised"
            )}
          </p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight sm:text-3xl">{data.name}</h1>
          <p className="mt-1.5 flex flex-wrap items-center gap-2 text-sm text-muted">
            {data.brand ? <span>{data.brand}</span> : null}
            <span className="num">
              {money(data.price_range.min)} – {money(data.price_range.max)}
            </span>
            <span>{data.country}</span>
            {data.data_quality.synthetic ? <Pill tone="amber">synthetic catalogue</Pill> : null}
            {data.supplier_available ? <Pill tone="good">supplier offers</Pill> : <Pill>no supplier offers</Pill>}
          </p>
        </div>
        <div className="flex flex-col items-end gap-2">
          {canWrite ? (
            <button
              type="button"
              className="btn btn-primary"
              onClick={addToWatchlist}
              disabled={watchState === "busy" || watchState === "done" || watchState === "exists"}
            >
              {watchState === "done" || watchState === "exists" ? (
                <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
              ) : (
                <BookmarkPlus className="h-4 w-4" aria-hidden="true" />
              )}
              {watchState === "busy"
                ? "Adding…"
                : watchState === "done"
                  ? "On watchlist"
                  : watchState === "exists"
                    ? "Already watching"
                    : "Add to watchlist"}
            </button>
          ) : null}
          {watchError ? (
            <p role="alert" className="text-xs" style={{ color: "var(--color-danger)" }}>
              {watchError}
            </p>
          ) : (
            <p className="max-w-[16rem] text-right text-[0.7rem] leading-relaxed text-muted">
              Discovered {formatDate(data.first_seen_at)} · updated {formatDateTime(data.updated_at)}
            </p>
          )}
        </div>
      </div>

      <Card className="p-5">
        <div className="flex flex-wrap items-center gap-6">
          <ScoreDial value={data.opportunity_score} classification={data.classification} />
          <div className="grid min-w-0 flex-1 grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
            {growthItems.map((item) => (
              <div key={item.label}>
                <p className="eyebrow">{item.label} growth</p>
                <p className="mt-1 text-lg font-semibold">
                  <GrowthValue growth={item.growth} />
                </p>
                {item.growth.pct === null ? (
                  <p className="mt-0.5 text-[0.65rem] leading-snug text-muted">
                    {GROWTH_REASON[item.growth.reason] ?? "Unavailable"}
                  </p>
                ) : null}
              </div>
            ))}
            <div>
              <p className="eyebrow">Est. margin</p>
              <p className="num mt-1 text-lg font-semibold">
                {data.estimated_margin_pct === null ? "—" : `${data.estimated_margin_pct.toFixed(1)}%`}
              </p>
              <p className="mt-0.5 text-[0.65rem] text-muted">Estimate, not verified</p>
            </div>
            <div>
              <p className="eyebrow">Competition</p>
              <p className="mt-1 text-lg font-semibold">
                {COMPETITION_LABEL[data.competition_class] ?? titleCase(data.competition_class)}
              </p>
            </div>
            <div>
              <p className="eyebrow">Trend</p>
              <p className="mt-1 text-lg font-semibold">{titleCase(data.trend_direction)}</p>
            </div>
            <div>
              <p className="eyebrow">Market average</p>
              <p className="num mt-1 text-lg font-semibold">{money(data.price_range.market_avg)}</p>
            </div>
          </div>
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)]">
        <div className="space-y-4">
          <TrendChart detail={data} />
          <Card className="p-5">
            <h2 className="text-sm font-semibold tracking-tight">Marketplace listings</h2>
            <p className="mt-1 text-xs text-muted">
              Active listings only. Review counts are a demand proxy, not sales.
            </p>
            {data.listings.length ? (
              <div className="mt-3 overflow-x-auto">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Marketplace</th>
                      <th>Title</th>
                      <th>Seller</th>
                      <th className="text-right">Price</th>
                      <th className="text-right">Rating</th>
                      <th className="text-right">Reviews</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.listings.map((listing) => (
                      <tr key={listing.id}>
                        <td className="whitespace-nowrap text-xs">{titleCase(listing.marketplace)}</td>
                        <td className="max-w-[16rem] truncate text-xs">{listing.title ?? "—"}</td>
                        <td className="text-xs text-muted">{listing.seller_name ?? "—"}</td>
                        <td className="num text-right text-xs">{money(listing.price, listing.currency)}</td>
                        <td className="num text-right text-xs">{listing.rating?.toFixed(1) ?? "—"}</td>
                        <td className="num text-right text-xs">{listing.review_count ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="mt-3 text-sm text-muted">No marketplace listings recorded.</p>
            )}
          </Card>

          <Card className="p-5">
            <h2 className="text-sm font-semibold tracking-tight">Supplier offers</h2>
            <p className="mt-1 text-xs text-muted">
              Costs are landed supplier quotes in the prototype dataset. Margin uses the cheapest
              offer and GST-aware fees.
            </p>
            {data.suppliers.length ? (
              <div className="mt-3 overflow-x-auto">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Supplier</th>
                      <th>Country</th>
                      <th className="text-right">Unit cost</th>
                      <th className="text-right">Shipping</th>
                      <th className="text-right">MOQ</th>
                      <th className="text-right">Lead time</th>
                      <th>Availability</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.suppliers.map((offer) => (
                      <tr key={offer.id}>
                        <td className="text-xs">
                          {offer.supplier_name}
                          {offer.is_synthetic ? (
                            <span className="ml-1.5 align-middle">
                              <Pill tone="amber">synthetic</Pill>
                            </span>
                          ) : null}
                        </td>
                        <td className="text-xs">{offer.country ?? "—"}</td>
                        <td className="num text-right text-xs">{money(offer.product_cost, offer.currency)}</td>
                        <td className="num text-right text-xs">{money(offer.shipping_cost, offer.currency)}</td>
                        <td className="num text-right text-xs">{offer.minimum_order_quantity}</td>
                        <td className="num text-right text-xs">
                          {offer.lead_time_days === null ? "—" : `${offer.lead_time_days}d`}
                        </td>
                        <td className="text-xs">{titleCase(offer.availability)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="mt-3 text-sm text-muted">
                No supplier offers. Profitability is unavailable rather than assumed.
              </p>
            )}
          </Card>

          {data.recent_scores.length > 1 ? (
            <Card className="p-5">
              <h2 className="text-sm font-semibold tracking-tight">Score history</h2>
              <ol className="mt-3 divide-y divide-line">
                {data.recent_scores.map((entry) => (
                  <li key={entry.calculated_on} className="flex items-center justify-between gap-3 py-2 text-sm">
                    <span className="text-xs text-muted">{formatDate(entry.calculated_on)}</span>
                    <span className="flex items-center gap-3">
                      <span className="text-[0.7rem] text-muted">
                        coverage {entry.coverage_pct.toFixed(0)}%
                      </span>
                      <ScoreBadge value={entry.score} classification={entry.classification} size="sm" />
                    </span>
                  </li>
                ))}
              </ol>
            </Card>
          ) : null}
        </div>

        <div className="space-y-4">
          <RecommendationPanel recommendation={data.recommendation} />
          <Breakdown detail={data} />
          <DataQualityPanel detail={data} />
          {canWrite ? <ManualEvidence slug={data.slug} onSaved={reload} /> : null}

          <Card className="p-5">
            <h2 className="text-sm font-semibold tracking-tight">Competition evidence</h2>
            {data.competition ? (
              <>
                <dl className="mt-2 divide-y divide-line">
                  <KeyValue label="Index">
                    <span className="num">
                      {data.competition.index === null ? "—" : data.competition.index.toFixed(1)}
                    </span>
                  </KeyValue>
                  <KeyValue label="Class">{titleCase(data.competition.classification)}</KeyValue>
                  <KeyValue label="Evidence coverage">
                    <span className="num">{(data.competition.coverage * 100).toFixed(0)}%</span>
                  </KeyValue>
                  <KeyValue label="Listings">
                    <span className="num">
                      {String(
                        (data.competition.evidence.active_listing_count as { value?: number } | undefined)
                          ?.value ?? "—",
                      )}
                    </span>
                  </KeyValue>
                </dl>
                {data.competition.unavailable.length ? (
                  <p className="mt-2 text-[0.7rem] leading-relaxed text-muted">
                    Unavailable: {data.competition.unavailable.map((item) => titleCase(item)).join(", ")}
                  </p>
                ) : null}
                <ul className="mt-3 space-y-1.5 border-t border-line pt-3">
                  {data.competition.caveats.map((caveat, index) => (
                    <li key={index} className="flex items-start gap-2 text-[0.7rem] leading-relaxed text-muted">
                      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                      {caveat}
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="mt-2 text-sm text-muted">No competition evidence recorded.</p>
            )}
          </Card>

          <Card className="p-5">
            <h2 className="text-sm font-semibold tracking-tight">Details</h2>
            {data.description ? (
              <p className="mt-2 text-sm leading-relaxed text-muted">{data.description}</p>
            ) : null}
            <dl className="mt-2 divide-y divide-line">
              <KeyValue label="Model">{data.model ?? "—"}</KeyValue>
              <KeyValue label="Keywords">{data.keywords.length ? data.keywords.join(", ") : "—"}</KeyValue>
              {Object.entries(data.attributes).slice(0, 8).map(([key, value]) => (
                <KeyValue key={key} label={titleCase(key)}>
                  {String(value)}
                </KeyValue>
              ))}
            </dl>
          </Card>

          <RecentObservations slug={data.slug} />

          <Card className="p-5">
            <h2 className="flex items-center gap-2 text-sm font-semibold tracking-tight">
              <Database className="h-4 w-4" aria-hidden="true" /> Provenance
            </h2>
            <ul className="mt-2 space-y-2">
              {data.sources.length ? (
                data.sources.map((source) => (
                  <li key={source.provider_key} className="text-xs">
                    <span className="flex items-start justify-between gap-2">
                      <span>
                        <span className="font-medium">{source.provider_name}</span>
                        <span className="block text-muted">
                          latest {formatDate(source.collection_date)} · {source.cost_model} ·{" "}
                          {source.verification_statuses.join(", ") || "unverified"}
                        </span>
                        <span className="block text-[0.65rem] text-muted">
                          {source.metric_types.join(", ")}
                          {source.source_url ? (
                            <>
                              {" · "}
                              <a
                                href={source.source_url}
                                target="_blank"
                                rel="noreferrer"
                                className="link"
                              >
                                source
                              </a>
                            </>
                          ) : null}
                        </span>
                      </span>
                      {source.is_synthetic ? <Pill tone="amber">synthetic</Pill> : <Pill tone="good">observed</Pill>}
                    </span>
                  </li>
                ))
              ) : (
                <li className="text-xs text-muted">No provenance recorded.</li>
              )}
            </ul>
            {data.data_quality.synthetic ? (
              <p className="mt-3 flex items-start gap-2 border-t border-line pt-3 text-[0.7rem] leading-relaxed text-muted">
                <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber" aria-hidden="true" />
                This product comes from the deterministic synthetic catalogue. Its figures illustrate
                the product, not the market.
              </p>
            ) : null}
          </Card>
        </div>
      </div>
    </div>
  );
}
