"use client";

import Link from "next/link";
import { Eye, Plus } from "lucide-react";
import type { ProductSummary } from "@/lib/types";
import { COMPETITION_LABEL, money, titleCase } from "@/lib/format";
import { GrowthValue, Pill, ScoreBadge } from "./ui";

export function ProductTable({
  items,
  onWatch,
  watching,
  compact = false,
}: {
  items: ProductSummary[];
  onWatch?: (product: ProductSummary) => void;
  watching?: Set<string>;
  compact?: boolean;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="table">
        <thead>
          <tr>
            <th scope="col">Product</th>
            <th scope="col">Category</th>
            <th scope="col">Score</th>
            <th scope="col" className="text-right">7d</th>
            <th scope="col" className="text-right">30d</th>
            {!compact ? <th scope="col" className="text-right">Margin</th> : null}
            <th scope="col">Competition</th>
            {!compact ? <th scope="col" className="text-right">Coverage</th> : null}
            <th scope="col" className="w-16 text-right">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((product) => {
            const watched = watching?.has(product.id) ?? false;
            return (
              <tr key={product.id}>
                <td className="max-w-[22rem]">
                  <Link href={`/products/${product.slug}`} className="link block truncate">
                    {product.name}
                  </Link>
                  <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[0.7rem] text-muted">
                    {product.brand ? <span>{product.brand}</span> : null}
                    {money(product.price_range.market_avg, product.price_range.currency) !== "—" ? (
                      <span className="num">
                        avg {money(product.price_range.market_avg, product.price_range.currency)}
                      </span>
                    ) : null}
                    {product.data_quality.synthetic ? <Pill tone="amber">synthetic</Pill> : null}
                  </span>
                </td>
                <td className="whitespace-nowrap text-xs text-muted">
                  {product.category?.name ?? "—"}
                </td>
                <td>
                  <ScoreBadge value={product.opportunity_score} classification={product.classification} size="sm" />
                </td>
                <td className="text-right">
                  <GrowthValue growth={product.growth.d7} />
                </td>
                <td className="text-right">
                  <GrowthValue growth={product.growth.d30} />
                </td>
                {!compact ? (
                  <td className="num text-right text-sm">
                    {product.estimated_margin_pct === null ? "—" : `${product.estimated_margin_pct.toFixed(1)}%`}
                  </td>
                ) : null}
                <td>
                  <Pill
                    tone={
                      product.competition_class === "low"
                        ? "good"
                        : product.competition_class === "high" || product.competition_class === "saturated"
                          ? "danger"
                          : product.competition_class === "moderate"
                            ? "amber"
                            : "muted"
                    }
                  >
                    {COMPETITION_LABEL[product.competition_class] ?? titleCase(product.competition_class)}
                  </Pill>
                </td>
                {!compact ? (
                  <td className="num text-right text-sm">
                    {product.data_quality.coverage_pct.toFixed(0)}%
                  </td>
                ) : null}
                <td className="text-right">
                  <span className="inline-flex items-center gap-1">
                    <Link
                      href={`/products/${product.slug}`}
                      className="btn btn-sm h-7 w-7 !p-0"
                      title="Open product"
                      aria-label={`Open ${product.name}`}
                    >
                      <Eye className="h-3.5 w-3.5" aria-hidden="true" />
                    </Link>
                    {onWatch ? (
                      <button
                        type="button"
                        className="btn btn-sm h-7 w-7 !p-0"
                        title={watched ? "Already on watchlist" : "Add to watchlist"}
                        aria-label={watched ? `${product.name} is on the watchlist` : `Add ${product.name} to watchlist`}
                        onClick={() => onWatch(product)}
                        disabled={watched}
                      >
                        <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                      </button>
                    ) : null}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
