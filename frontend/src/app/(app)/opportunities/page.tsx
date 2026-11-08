"use client";

import Link from "next/link";
import { useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  CircleHelp,
  RefreshCw,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import {
  Card,
  ErrorState,
  GrowthValue,
  PageHeader,
  Pill,
  ScoreBadge,
  Skeleton,
} from "@/components/ui";
import { queryString } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { RecommendationCheck, RecommendationsResponse } from "@/lib/types";
import { money, titleCase } from "@/lib/format";

const VERDICTS = [
  { value: "all", label: "All evidence states" },
  { value: "recommended", label: "Recommended" },
  { value: "investigate", label: "Investigate" },
  { value: "not_recommended", label: "Not recommended" },
] as const;

function verdictTone(verdict: string): "good" | "amber" | "danger" | "muted" {
  if (verdict === "recommended") return "good";
  if (verdict === "investigate") return "amber";
  if (verdict === "not_recommended") return "danger";
  return "muted";
}

const CHECK_ICON: Record<string, typeof CheckCircle2> = {
  pass: CheckCircle2,
  fail: XCircle,
  missing: CircleHelp,
};

function checkTone(status: string): "good" | "danger" | "amber" {
  if (status === "pass") return "good";
  if (status === "fail") return "danger";
  return "amber";
}

function Checks({ checks }: { checks: RecommendationCheck[] }) {
  return (
    <ul className="mt-3 grid gap-2 sm:grid-cols-2">
      {checks.map((check) => {
        const Icon = CHECK_ICON[check.status] ?? CircleHelp;
        return (
          <li key={check.key} className="rounded-md border border-line bg-raised px-3 py-2">
            <p className="flex items-center justify-between gap-2 text-xs font-medium">
              <span className="flex items-center gap-1.5">
                <Icon
                  className="h-3.5 w-3.5 shrink-0"
                  style={{
                    color:
                      check.status === "pass"
                        ? "var(--color-good)"
                        : check.status === "fail"
                          ? "var(--color-danger)"
                          : "var(--color-amber)",
                  }}
                  aria-hidden="true"
                />
                {check.label}
              </span>
              <Pill tone={checkTone(check.status)}>{check.status}</Pill>
            </p>
            <p className="mt-1 text-[0.7rem] leading-relaxed text-muted">{check.detail}</p>
          </li>
        );
      })}
    </ul>
  );
}

export default function OpportunitiesPage() {
  const [verdict, setVerdict] = useState<(typeof VERDICTS)[number]["value"]>("all");
  const [minCoverage, setMinCoverage] = useState(60);
  const [limit, setLimit] = useState(20);
  const path = `/opportunities/recommendations${queryString({
    verdict,
    min_coverage: minCoverage,
    limit,
  })}`;
  const { data, error, loading, reload } = useApi<RecommendationsResponse>(path);
  const items = data?.data ?? [];
  const counts = data?.meta.counts ?? {};

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Decision support"
        title="Opportunity recommendations"
        description="A high opportunity score is not a recommendation. Each product must also show a supplier price, a delivery cost and a contribution margin before it can be marked recommended."
        actions={
          <button type="button" className="btn btn-sm" onClick={reload} disabled={loading}>
            <RefreshCw
              className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`}
              aria-hidden="true"
            />
            Refresh
          </button>
        }
      />

      <div className="flex flex-wrap items-end gap-3">
        <label className="text-xs">
          <span className="eyebrow block">Verdict</span>
          <select
            className="field mt-1 w-auto text-xs"
            value={verdict}
            onChange={(event) => setVerdict(event.target.value as typeof verdict)}
          >
            {VERDICTS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs">
          <span className="eyebrow block">Min coverage</span>
          <input
            type="number"
            min={0}
            max={100}
            step={5}
            className="field mt-1 w-24 text-xs"
            value={minCoverage}
            onChange={(event) => setMinCoverage(Number(event.target.value))}
          />
        </label>
        <label className="text-xs">
          <span className="eyebrow block">Limit</span>
          <input
            type="number"
            min={1}
            max={50}
            className="field mt-1 w-20 text-xs"
            value={limit}
            onChange={(event) => setLimit(Number(event.target.value))}
          />
        </label>
        <div className="ml-auto flex flex-wrap gap-1.5">
          {Object.entries(counts).map(([key, value]) => (
            <Pill key={key} tone={verdictTone(key)}>
              {titleCase(key)}: {value}
            </Pill>
          ))}
        </div>
      </div>

      <p className="flex items-start gap-2 rounded-md border border-line bg-raised px-3 py-2 text-xs leading-relaxed text-muted">
        <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" aria-hidden="true" />
        {data?.meta.note ??
          "Supplier cost, delivery cost and margin must be investigated before a product is added to the catalogue."}
      </p>

      {error ? <ErrorState message={error} onRetry={reload} /> : null}

      {loading && !data ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-48" />
          ))}
        </div>
      ) : items.length ? (
        <div className="space-y-3">
          {items.map(({ product, recommendation }) => (
            <Card key={product.id} className="p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <Link href={`/products/${product.slug}`} className="link text-sm font-semibold tracking-tight">
                      {product.name}
                    </Link>
                    <Pill tone={verdictTone(recommendation.verdict)}>{recommendation.label}</Pill>
                    {product.data_quality.synthetic ? <Pill tone="amber">synthetic</Pill> : null}
                  </div>
                  <p className="mt-1 text-xs leading-relaxed text-muted">{recommendation.summary}</p>
                </div>
                <div className="flex items-center gap-3">
                  <div className="text-right">
                    <p className="eyebrow">7d / 30d</p>
                    <p className="num text-xs">
                      <GrowthValue growth={product.growth.d7} /> ·{" "}
                      <GrowthValue growth={product.growth.d30} />
                    </p>
                  </div>
                  <ScoreBadge value={product.opportunity_score} classification={product.classification} />
                </div>
              </div>

              <Checks checks={recommendation.checks} />

              <div className="mt-3 grid gap-3 border-t border-line pt-3 text-xs sm:grid-cols-2">
                <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5">
                  <div>
                    <dt className="text-muted">Market price</dt>
                    <dd className="num">{money(recommendation.economics.market_price)}</dd>
                  </div>
                  <div>
                    <dt className="text-muted">Supplier cost</dt>
                    <dd className="num">{money(recommendation.economics.product_cost)}</dd>
                  </div>
                  <div>
                    <dt className="text-muted">Delivery</dt>
                    <dd className="num">{money(recommendation.economics.delivery_cost)}</dd>
                  </div>
                  <div>
                    <dt className="text-muted">Contribution</dt>
                    <dd className="num">
                      {money(recommendation.economics.estimated_profit_per_unit)} /{" "}
                      {recommendation.economics.estimated_margin_pct === null
                        ? "—"
                        : `${recommendation.economics.estimated_margin_pct.toFixed(1)}%`}
                    </dd>
                  </div>
                </dl>
                <div>
                  <p className="eyebrow">Next actions</p>
                  {recommendation.next_actions.length ? (
                    <ul className="mt-1 space-y-1 text-[0.7rem] leading-relaxed text-muted">
                      {recommendation.next_actions.map((action) => (
                        <li key={action.key} className="flex items-start gap-1.5">
                          <ArrowRight className="mt-0.5 h-3 w-3 shrink-0" aria-hidden="true" />
                          {action.action}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-1 flex items-start gap-1.5 text-[0.7rem] leading-relaxed text-muted">
                      <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-good" aria-hidden="true" />
                      All required evidence is recorded. Confirm the supplier quote before committing
                      stock.
                    </p>
                  )}
                </div>
              </div>

              {recommendation.missing_evidence.length ? (
                <p className="mt-3 flex items-start gap-1.5 text-[0.7rem] leading-relaxed text-muted">
                  <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-amber" aria-hidden="true" />
                  Missing evidence: {recommendation.missing_evidence.join(", ")}.
                </p>
              ) : null}
            </Card>
          ))}
        </div>
      ) : (
        <Card className="p-5">
          <p className="text-sm text-muted">
            No products match this verdict and coverage filter. Lower the coverage threshold or
            collect more observations.
          </p>
        </Card>
      )}

      <p className="text-[0.7rem] leading-relaxed text-muted">
        {items[0]?.recommendation.disclaimer ??
          "Recommendations are estimates from available evidence, not sales forecasts."}
      </p>
    </div>
  );
}
