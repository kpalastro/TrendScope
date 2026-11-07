"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Bookmark, Download, GitCompareArrows, Pencil, RefreshCw, Trash2 } from "lucide-react";
import {
  Card,
  EmptyState,
  ErrorState,
  GrowthValue,
  Modal,
  PageHeader,
  Pill,
  ScoreBadge,
  Skeleton,
} from "@/components/ui";
import { useAuth } from "@/components/AuthProvider";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { ProductSummary, WatchlistEntry } from "@/lib/types";
import {
  CLASSIFICATION_LABEL,
  COMPETITION_LABEL,
  GROWTH_REASON,
  money,
  titleCase,
  WATCH_STATUSES,
} from "@/lib/format";

type WatchlistResponse = { data: WatchlistEntry[]; meta: { total: number } };

const STATUS_TONE: Record<string, "accent" | "good" | "amber" | "danger" | "muted"> = {
  discovered: "muted",
  researching: "accent",
  shortlisted: "good",
  supplier_validation: "amber",
  ready_for_catalogue: "good",
  published: "good",
  rejected: "danger",
};

export default function WatchlistPage() {
  const { canWrite } = useAuth();
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState("-updated_at");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [editing, setEditing] = useState<WatchlistEntry | null>(null);
  const [compareItems, setCompareItems] = useState<ProductSummary[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ message: string; tone: "ok" | "error" } | null>(null);

  const query = new URLSearchParams();
  if (status) query.set("status", status);
  query.set("sort", sort);
  const { data, error, loading, reload } = useApi<WatchlistResponse>(`/watchlist?${query.toString()}`);

  const entries = data?.data ?? [];
  const selectedIds = useMemo(() => Array.from(selected), [selected]);

  function toggle(id: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function patchStatus(entry: WatchlistEntry, nextStatus: string) {
    try {
      await api.patch(`/watchlist/${entry.id}`, { status: nextStatus });
      reload();
    } catch (err) {
      setNotice({ message: (err as Error).message, tone: "error" });
    }
  }

  async function remove(entry: WatchlistEntry) {
    if (!window.confirm(`Remove ${entry.product?.name ?? "this product"} from your watchlist?`)) return;
    try {
      await api.delete(`/watchlist/${entry.id}`);
      setSelected((current) => {
        const next = new Set(current);
        next.delete(entry.product_id);
        return next;
      });
      reload();
    } catch (err) {
      setNotice({ message: (err as Error).message, tone: "error" });
    }
  }

  async function compare() {
    if (selectedIds.length < 2 || selectedIds.length > 5) return;
    setBusy(true);
    try {
      const response = await api.post<{ data: ProductSummary[]; disclaimer: string }>(
        "/watchlist/compare",
        { product_ids: selectedIds },
      );
      setCompareItems(response.data);
    } catch (err) {
      setNotice({ message: (err as Error).message, tone: "error" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Research queue"
        title="Watchlist"
        description="Track candidates through research to a decision. Your watchlist is private to your account."
        actions={
          <>
            <button
              type="button"
              className="btn btn-sm"
              onClick={() =>
                api.download("/watchlist/export", "trendscope-watchlist.csv").catch((err) =>
                  setNotice({ message: (err as Error).message, tone: "error" }),
                )
              }
            >
              <Download className="h-3.5 w-3.5" aria-hidden="true" /> Export CSV
            </button>
            <button type="button" className="btn btn-sm" onClick={reload} disabled={loading}>
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} aria-hidden="true" />
              Refresh
            </button>
          </>
        }
      />

      <Card className="flex flex-wrap items-end justify-between gap-3 p-3.5">
        <div className="flex flex-wrap items-end gap-2.5">
          <div>
            <label htmlFor="status-filter" className="eyebrow mb-1 block">
              Status
            </label>
            <select
              id="status-filter"
              className="field w-auto"
              value={status}
              onChange={(event) => setStatus(event.target.value)}
            >
              <option value="">All statuses</option>
              {WATCH_STATUSES.map((item) => (
                <option key={item} value={item}>
                  {titleCase(item)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="sort-watch" className="eyebrow mb-1 block">
              Sort
            </label>
            <select
              id="sort-watch"
              className="field w-auto"
              value={sort}
              onChange={(event) => setSort(event.target.value)}
            >
              <option value="-updated_at">Recently updated</option>
              <option value="-priority">Priority</option>
              <option value="status">Status</option>
            </select>
          </div>
        </div>
        <div className="flex items-center gap-2.5">
          <p className="text-xs text-muted">
            {selectedIds.length ? `${selectedIds.length} selected` : "Select 2–5 to compare"}
          </p>
          <button
            type="button"
            className="btn btn-sm"
            onClick={compare}
            disabled={selectedIds.length < 2 || selectedIds.length > 5 || busy}
          >
            <GitCompareArrows className="h-3.5 w-3.5" aria-hidden="true" />
            {busy ? "Comparing…" : "Compare"}
          </button>
        </div>
      </Card>

      {error ? <ErrorState message={error} onRetry={reload} /> : null}

      <Card>
        {loading && !data ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 5 }).map((_, index) => (
              <Skeleton key={index} className="h-12" />
            ))}
          </div>
        ) : entries.length === 0 ? (
          <EmptyState
            icon={<Bookmark className="h-5 w-5" aria-hidden="true" />}
            title={status ? "No entries with this status" : "Your watchlist is empty"}
            description={
              status
                ? "Try another status, or clear the filter."
                : "Open a product and choose “Add to watchlist”, or use the plus button in the product table."
            }
            action={
              <Link href="/products" className="btn btn-sm">
                Browse products
              </Link>
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col" className="w-8">
                    <span className="sr-only">Select</span>
                  </th>
                  <th scope="col">Product</th>
                  <th scope="col">Score</th>
                  <th scope="col" className="text-right">7d</th>
                  <th scope="col" className="text-right">30d</th>
                  <th scope="col">Status</th>
                  <th scope="col" className="text-right">Updated</th>
                  <th scope="col" className="w-20 text-right">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => (
                  <tr key={entry.id}>
                    <td>
                      <input
                        type="checkbox"
                        className="h-3.5 w-3.5 accent-[var(--color-accent)]"
                        checked={selected.has(entry.product_id)}
                        onChange={() => toggle(entry.product_id)}
                        aria-label={`Select ${entry.product?.name ?? "product"} for comparison`}
                      />
                    </td>
                    <td className="max-w-[20rem]">
                      {entry.product ? (
                        <>
                          <Link href={`/products/${entry.product.slug}`} className="link block truncate">
                            {entry.product.name}
                          </Link>
                          <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[0.7rem] text-muted">
                            <span>{entry.product.category?.name ?? "Uncategorised"}</span>
                            {entry.product.data_quality.synthetic ? <Pill tone="amber">synthetic</Pill> : null}
                          </span>
                        </>
                      ) : (
                        <span className="text-muted">Product unavailable</span>
                      )}
                      {entry.notes ? (
                        <p className="mt-0.5 line-clamp-1 text-[0.7rem] italic text-muted">{entry.notes}</p>
                      ) : null}
                    </td>
                    <td>
                      {entry.product ? (
                        <ScoreBadge
                          value={entry.product.opportunity_score}
                          classification={entry.product.classification}
                          size="sm"
                        />
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="text-right">
                      {entry.product ? <GrowthValue growth={entry.product.growth.d7} /> : "—"}
                    </td>
                    <td className="text-right">
                      {entry.product ? <GrowthValue growth={entry.product.growth.d30} /> : "—"}
                    </td>
                    <td>
                      <select
                        className="field w-auto py-1 text-xs"
                        value={entry.status}
                        onChange={(event) => patchStatus(entry, event.target.value)}
                        disabled={!canWrite}
                        aria-label={`Status for ${entry.product?.name ?? "product"}`}
                      >
                        {WATCH_STATUSES.map((item) => (
                          <option key={item} value={item}>
                            {titleCase(item)}
                          </option>
                        ))}
                      </select>
                      {entry.priority ? (
                        <span className="ml-1.5 align-middle">
                          <Pill tone={STATUS_TONE[entry.status] ?? "muted"}>P{entry.priority}</Pill>
                        </span>
                      ) : null}
                    </td>
                    <td className="whitespace-nowrap text-right text-xs text-muted">
                      {new Date(entry.updated_at).toLocaleDateString("en-AU", {
                        day: "numeric",
                        month: "short",
                      })}
                    </td>
                    <td className="text-right">
                      {canWrite ? (
                        <span className="inline-flex gap-1">
                          <button
                            type="button"
                            className="btn btn-sm h-7 w-7 !p-0"
                            onClick={() => setEditing(entry)}
                            title="Edit notes and priority"
                            aria-label={`Edit ${entry.product?.name ?? "entry"}`}
                          >
                            <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                          </button>
                          <button
                            type="button"
                            className="btn btn-sm h-7 w-7 !p-0"
                            onClick={() => remove(entry)}
                            title="Remove from watchlist"
                            aria-label={`Remove ${entry.product?.name ?? "entry"}`}
                            style={{ color: "var(--color-danger)" }}
                          >
                            <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                          </button>
                        </span>
                      ) : (
                        <span className="text-xs text-muted">View only</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {editing ? (
        <EditDialog
          entry={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            reload();
          }}
        />
      ) : null}

      {compareItems ? (
        <Modal
          title="Compare products"
          description="Comparison surfaces available evidence only; unavailable components are null, not zero."
          onClose={() => setCompareItems(null)}
          width="max-w-4xl"
        >
          <CompareTable items={compareItems} />
        </Modal>
      ) : null}

      {notice ? (
        <div
          role="status"
          className="card fixed bottom-4 right-4 z-50 max-w-sm px-4 py-3 text-sm"
          style={{ borderColor: notice.tone === "error" ? "var(--color-danger)" : "var(--color-good)" }}
        >
          {notice.message}
        </div>
      ) : null}
    </div>
  );
}

function EditDialog({
  entry,
  onClose,
  onSaved,
}: {
  entry: WatchlistEntry;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [status, setStatus] = useState(entry.status);
  const [priority, setPriority] = useState(entry.priority ? String(entry.priority) : "");
  const [notes, setNotes] = useState(entry.notes ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.patch(`/watchlist/${entry.id}`, {
        status,
        priority: priority ? Number(priority) : null,
        notes: notes.trim() || null,
      });
      onSaved();
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <Modal
      title={`Edit — ${entry.product?.name ?? "watchlist entry"}`}
      description="Status, priority and notes are private to your account."
      onClose={onClose}
    >
      <form onSubmit={submit} className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor="edit-status" className="mb-1 block text-xs font-medium text-muted">
              Status
            </label>
            <select id="edit-status" className="field" value={status} onChange={(event) => setStatus(event.target.value)}>
              {WATCH_STATUSES.map((item) => (
                <option key={item} value={item}>
                  {titleCase(item)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="edit-priority" className="mb-1 block text-xs font-medium text-muted">
              Priority (1–5)
            </label>
            <input
              id="edit-priority"
              type="number"
              min={1}
              max={5}
              className="field"
              value={priority}
              onChange={(event) => setPriority(event.target.value)}
            />
          </div>
        </div>
        <div>
          <label htmlFor="edit-notes" className="mb-1 block text-xs font-medium text-muted">
            Notes
          </label>
          <textarea
            id="edit-notes"
            className="field min-h-[100px]"
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            maxLength={4000}
          />
        </div>
        {error ? (
          <p role="alert" className="text-sm" style={{ color: "var(--color-danger)" }}>
            {error}
          </p>
        ) : null}
        <div className="flex justify-end gap-2 border-t border-line pt-3">
          <button type="button" className="btn btn-sm" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-sm btn-primary" disabled={busy}>
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function CompareTable({ items }: { items: ProductSummary[] }) {
  const rows: { label: string; render: (item: ProductSummary) => React.ReactNode }[] = [
    {
      label: "Opportunity score",
      render: (item) => <ScoreBadge value={item.opportunity_score} classification={item.classification} size="sm" />,
    },
    {
      label: "Classification",
      render: (item) => (item.classification ? CLASSIFICATION_LABEL[item.classification] ?? item.classification : "—"),
    },
    { label: "Growth 7d", render: (item) => <GrowthValue growth={item.growth.d7} /> },
    { label: "Growth 30d", render: (item) => <GrowthValue growth={item.growth.d30} /> },
    { label: "Growth 90d", render: (item) => <GrowthValue growth={item.growth.d90} /> },
    {
      label: "Competition",
      render: (item) => COMPETITION_LABEL[item.competition_class] ?? titleCase(item.competition_class),
    },
    {
      label: "Est. margin",
      render: (item) =>
        item.estimated_margin_pct === null ? "—" : `${item.estimated_margin_pct.toFixed(1)}%`,
    },
    { label: "Market average", render: (item) => money(item.price_range.market_avg, item.price_range.currency) },
    { label: "Coverage", render: (item) => `${item.data_quality.coverage_pct.toFixed(0)}%` },
    {
      label: "7d growth note",
      render: (item) => (
        <span className="text-[0.7rem] text-muted">
          {item.growth.d7.pct === null ? GROWTH_REASON[item.growth.d7.reason] ?? "Unavailable" : "Measured"}
        </span>
      ),
    },
  ];

  return (
    <div className="overflow-x-auto">
      <table className="table">
        <thead>
          <tr>
            <th>Metric</th>
            {items.map((item) => (
              <th key={item.id}>{item.name}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label}>
              <td className="whitespace-nowrap text-xs text-muted">{row.label}</td>
              {items.map((item) => (
                <td key={item.id} className="text-sm">
                  {row.render(item)}
                </td>
              ))}
            </tr>
          ))}
          <tr>
            <td className="text-xs text-muted">Open</td>
            {items.map((item) => (
              <td key={item.id}>
                <Link href={`/products/${item.slug}`} className="link text-sm">
                  View
                </Link>
              </td>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  );
}
