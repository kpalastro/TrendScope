"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  BookmarkPlus,
  CheckCircle2,
  Database,
  Info,
  LineChart as LineChartIcon,
  Sparkles,
  TriangleAlert,
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
import type { ProductDetail } from "@/lib/types";
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
    <div className="relative h-[132px] w-[132px] shrink-0">
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
          y="58"
          textAnchor="middle"
          fontSize="26"
          fontWeight="600"
          fill="var(--color-ink)"
          fontFamily="IBM Plex Mono, monospace"
        >
          {value === null ? "—" : value.toFixed(1)}
        </text>
        <text x="60" y="78" textAnchor="middle" fontSize="9" fill="var(--color-muted)" letterSpacing="1.5">
          {classification ? CLASSIFICATION_LABEL[classification] ?? classification : "Not scored"}
        </text>
      </svg>
    </div>
  );
}

function TrendChart({ detail }: { detail: ProductDetail }) {
  const [mounted, setMounted] = useState(false);
  const series = detail.trend_series;
  const [metric, setMetric] = useState(series[0]?.metric_name ?? "search_interest");
  useEffect(() => setMounted(true), []);

  const active = series.find((item) => item.metric_name === metric) ?? series[0];
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
                <option key={item.metric_name} value={item.metric_name}>
                  {titleCase(item.metric_name)}
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
          <Breakdown detail={data} />
          <DataQualityPanel detail={data} />

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

          <Card className="p-5">
            <h2 className="flex items-center gap-2 text-sm font-semibold tracking-tight">
              <Database className="h-4 w-4" aria-hidden="true" /> Provenance
            </h2>
            <ul className="mt-2 space-y-2">
              {data.sources.length ? (
                data.sources.map((source) => (
                  <li key={source.provider_key} className="flex items-start justify-between gap-2 text-xs">
                    <span>
                      <span className="font-medium">{source.provider_name}</span>
                      <span className="block text-muted">
                        latest {formatDate(source.collection_date)}
                      </span>
                    </span>
                    {source.is_synthetic ? <Pill tone="amber">synthetic</Pill> : <Pill tone="good">observed</Pill>}
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
