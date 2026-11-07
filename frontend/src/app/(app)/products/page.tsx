"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Download,
  FileSpreadsheet,
  Plus,
  Search,
  SlidersHorizontal,
  Upload,
  X,
} from "lucide-react";
import { ProductTable } from "@/components/ProductTable";
import {
  Card,
  EmptyState,
  ErrorState,
  Modal,
  PageHeader,
  Pill,
  Skeleton,
} from "@/components/ui";
import { api, ApiError, queryString } from "@/lib/api";
import { useAuth } from "@/components/AuthProvider";
import type {
  Category,
  ImportResult,
  ProductDetail,
  ProductList,
  ProductSummary,
} from "@/lib/types";
import { useApi } from "@/lib/useApi";

const SORTS = [
  { value: "-opportunity_score", label: "Opportunity score" },
  { value: "-growth_7d", label: "7-day growth" },
  { value: "-growth_30d", label: "30-day growth" },
  { value: "-growth_90d", label: "90-day growth" },
  { value: "-estimated_margin", label: "Estimated margin" },
  { value: "-marketplace_popularity", label: "Marketplace listings" },
  { value: "competition_index", label: "Competition index" },
  { value: "-seasonality", label: "Seasonality" },
  { value: "-first_seen_at", label: "Recently discovered" },
  { value: "name", label: "Name" },
];

const COMPETITION = [
  { value: "", label: "Any competition" },
  { value: "low", label: "Low competition" },
  { value: "moderate", label: "Moderate competition" },
  { value: "high", label: "High competition" },
  { value: "unknown", label: "Unknown competition" },
];

function Toast({ message, tone }: { message: string; tone: "ok" | "error" }) {
  return (
    <div
      role="status"
      className="card fixed bottom-4 right-4 z-50 max-w-sm px-4 py-3 text-sm"
      style={{ borderColor: tone === "error" ? "var(--color-danger)" : "var(--color-good)" }}
    >
      {message}
    </div>
  );
}

export default function ProductsPage() {
  const { canWrite } = useAuth();
  const [query, setQuery] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [competition, setCompetition] = useState("");
  const [minScore, setMinScore] = useState("");
  const [maxScore, setMaxScore] = useState("");
  const [minGrowth, setMinGrowth] = useState("");
  const [minPrice, setMinPrice] = useState("");
  const [maxPrice, setMaxPrice] = useState("");
  const [minMargin, setMinMargin] = useState("");
  const [supplier, setSupplier] = useState("");
  const [sort, setSort] = useState("-opportunity_score");
  const [page, setPage] = useState(1);
  const [watching, setWatching] = useState<Set<string>>(new Set());
  const [toast, setToast] = useState<{ message: string; tone: "ok" | "error" } | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function notify(message: string, tone: "ok" | "error" = "ok") {
    setToast({ message, tone });
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setToast(null), 4500);
  }

  const categories = useApi<{ data: Category[] }>("/categories");

  // Categories page links here with ?category_id=…; seed the filter once.
  useEffect(() => {
    const initial = new URLSearchParams(window.location.search).get("category_id");
    if (initial) {
      setCategoryId(initial);
      setPage(1);
    }
  }, []);

  const path = useMemo(
    () =>
      `/products${queryString({
        q: query || undefined,
        category_id: categoryId || undefined,
        competition: competition ? [competition] : undefined,
        min_score: minScore || undefined,
        max_score: maxScore || undefined,
        min_growth_7d: minGrowth || undefined,
        min_price: minPrice || undefined,
        max_price: maxPrice || undefined,
        min_margin: minMargin || undefined,
        supplier_available: supplier === "" ? undefined : supplier,
        sort,
        page,
        per_page: 25,
      })}`,
    [
      query,
      categoryId,
      competition,
      minScore,
      maxScore,
      minGrowth,
      minPrice,
      maxPrice,
      minMargin,
      supplier,
      sort,
      page,
    ],
  );

  const { data, error, loading, reload } = useApi<ProductList>(path);

  function submitSearch(event: React.FormEvent) {
    event.preventDefault();
    setPage(1);
    setQuery(searchInput.trim());
  }

  function resetFilters() {
    setQuery("");
    setSearchInput("");
    setCategoryId("");
    setCompetition("");
    setMinScore("");
    setMaxScore("");
    setMinGrowth("");
    setMinPrice("");
    setMaxPrice("");
    setMinMargin("");
    setSupplier("");
    setSort("-opportunity_score");
    setPage(1);
    // The category seed is read from the URL on mount; clear it so a refresh
    // does not bring the reset filter back.
    window.history.replaceState({}, "", "/products");
  }

  function exportHref() {
    return `/exports/products${queryString({
      q: query || undefined,
      category_id: categoryId || undefined,
      competition: competition ? [competition] : undefined,
      min_score: minScore || undefined,
      max_score: maxScore || undefined,
      min_growth_7d: minGrowth || undefined,
      min_price: minPrice || undefined,
      max_price: maxPrice || undefined,
      min_margin: minMargin || undefined,
      supplier_available: supplier === "" ? undefined : supplier,
      sort,
    })}`;
  }

  async function watch(product: ProductSummary) {
    try {
      await api.post("/watchlist", { product_id: product.id, status: "discovered" });
      setWatching((current) => new Set(current).add(product.id));
      notify(`${product.name} added to the watchlist.`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setWatching((current) => new Set(current).add(product.id));
        notify(`${product.name} is already on the watchlist.`, "error");
      } else {
        notify((err as Error).message, "error");
      }
    }
  }

  async function downloadTemplate() {
    try {
      await api.download("/products/import/csv/template", "trendscope-products-template.csv");
    } catch (err) {
      notify((err as Error).message, "error");
    }
  }

  const items = data?.data ?? [];
  const meta = data?.meta;
  const hasFilters = Boolean(
    query ||
      categoryId ||
      competition ||
      minScore ||
      maxScore ||
      minGrowth ||
      minPrice ||
      maxPrice ||
      minMargin ||
      supplier ||
      sort !== "-opportunity_score",
  );

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Catalogue"
        title="Products"
        description="Every product carries its own growth windows, score and data-quality record. Filters compose; missing values stay missing."
        actions={
          <>
            <button type="button" className="btn btn-sm" onClick={downloadTemplate}>
              <Download className="h-3.5 w-3.5" aria-hidden="true" /> CSV template
            </button>
            {canWrite ? (
              <>
                <button type="button" className="btn btn-sm" onClick={() => setImportOpen(true)}>
                  <Upload className="h-3.5 w-3.5" aria-hidden="true" /> Import CSV
                </button>
                <button type="button" className="btn btn-sm btn-primary" onClick={() => setCreateOpen(true)}>
                  <Plus className="h-3.5 w-3.5" aria-hidden="true" /> Add product
                </button>
              </>
            ) : null}
          </>
        }
      />

      <Card className="p-3">
        <form onSubmit={submitSearch} className="flex flex-wrap items-end gap-2.5">
          <div className="min-w-[220px] flex-1">
            <label htmlFor="product-search" className="eyebrow mb-1 block">
              Search
            </label>
            <div className="relative">
              <Search
                className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted"
                aria-hidden="true"
              />
              <input
                id="product-search"
                className="field pl-8"
                placeholder="Name, brand or keyword"
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
              />
            </div>
          </div>

          <div>
            <label htmlFor="category-filter" className="eyebrow mb-1 block">
              Category
            </label>
            <select
              id="category-filter"
              className="field min-w-[170px]"
              value={categoryId}
              onChange={(event) => {
                setCategoryId(event.target.value);
                setPage(1);
              }}
            >
              <option value="">All categories</option>
              {(categories.data?.data ?? []).map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="competition-filter" className="eyebrow mb-1 block">
              Competition
            </label>
            <select
              id="competition-filter"
              className="field min-w-[160px]"
              value={competition}
              onChange={(event) => {
                setCompetition(event.target.value);
                setPage(1);
              }}
            >
              {COMPETITION.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="score-filter" className="eyebrow mb-1 block">
              Min score
            </label>
            <input
              id="score-filter"
              type="number"
              min={0}
              max={100}
              className="field w-24"
              placeholder="0"
              value={minScore}
              onChange={(event) => {
                setMinScore(event.target.value);
                setPage(1);
              }}
            />
          </div>

          <div>
            <label htmlFor="max-score-filter" className="eyebrow mb-1 block">
              Max score
            </label>
            <input
              id="max-score-filter"
              type="number"
              min={0}
              max={100}
              className="field w-24"
              placeholder="100"
              value={maxScore}
              onChange={(event) => {
                setMaxScore(event.target.value);
                setPage(1);
              }}
            />
          </div>

          <div>
            <label htmlFor="growth-filter" className="eyebrow mb-1 block">
              Min 7d growth
            </label>
            <input
              id="growth-filter"
              type="number"
              className="field w-28"
              placeholder="%"
              value={minGrowth}
              onChange={(event) => {
                setMinGrowth(event.target.value);
                setPage(1);
              }}
            />
          </div>

          <div>
            <label htmlFor="min-price-filter" className="eyebrow mb-1 block">
              Min price
            </label>
            <input
              id="min-price-filter"
              type="number"
              min={0}
              step="0.01"
              className="field w-24"
              placeholder="A$"
              value={minPrice}
              onChange={(event) => {
                setMinPrice(event.target.value);
                setPage(1);
              }}
            />
          </div>

          <div>
            <label htmlFor="max-price-filter" className="eyebrow mb-1 block">
              Max price
            </label>
            <input
              id="max-price-filter"
              type="number"
              min={0}
              step="0.01"
              className="field w-24"
              placeholder="A$"
              value={maxPrice}
              onChange={(event) => {
                setMaxPrice(event.target.value);
                setPage(1);
              }}
            />
          </div>

          <div>
            <label htmlFor="margin-filter" className="eyebrow mb-1 block">
              Min margin
            </label>
            <input
              id="margin-filter"
              type="number"
              className="field w-24"
              placeholder="%"
              value={minMargin}
              onChange={(event) => {
                setMinMargin(event.target.value);
                setPage(1);
              }}
            />
          </div>

          <div>
            <label htmlFor="supplier-filter" className="eyebrow mb-1 block">
              Supplier
            </label>
            <select
              id="supplier-filter"
              className="field min-w-[150px]"
              value={supplier}
              onChange={(event) => {
                setSupplier(event.target.value);
                setPage(1);
              }}
            >
              <option value="">Any availability</option>
              <option value="true">Offer available</option>
              <option value="false">No offer</option>
            </select>
          </div>

          <div>
            <label htmlFor="sort" className="eyebrow mb-1 block">
              Sort
            </label>
            <select
              id="sort"
              className="field min-w-[180px]"
              value={sort}
              onChange={(event) => {
                setSort(event.target.value);
                setPage(1);
              }}
            >
              {SORTS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-2">
            <button type="submit" className="btn btn-sm btn-primary">
              <SlidersHorizontal className="h-3.5 w-3.5" aria-hidden="true" /> Apply
            </button>
            {hasFilters ? (
              <button type="button" className="btn btn-sm" onClick={resetFilters}>
                <X className="h-3.5 w-3.5" aria-hidden="true" /> Reset
              </button>
            ) : null}
            <button
              type="button"
              className="btn btn-sm"
              onClick={() =>
                api
                  .download(exportHref(), "trendscope-products.csv")
                  .catch((err) => notify((err as Error).message, "error"))
              }
            >
              <FileSpreadsheet className="h-3.5 w-3.5" aria-hidden="true" /> Export
            </button>
          </div>
        </form>
      </Card>

      {error ? <ErrorState message={error} onRetry={reload} /> : null}

      <Card>
        {loading && items.length === 0 ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 6 }).map((_, index) => (
              <Skeleton key={index} className="h-11" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <EmptyState
            icon={<Search className="h-5 w-5" aria-hidden="true" />}
            title={hasFilters ? "No products match these filters" : "No products yet"}
            description={
              hasFilters
                ? "Widen the filters or clear the search. Null growth is never treated as zero, so products with thin data may be missing from growth sorts."
                : "Import a CSV or run the mock sync from Data sources to populate the catalogue."
            }
            action={
              hasFilters ? (
                <button type="button" className="btn btn-sm" onClick={resetFilters}>
                  Clear filters
                </button>
              ) : null
            }
          />
        ) : (
          <ProductTable
            items={items}
            onWatch={canWrite ? watch : undefined}
            watching={watching}
          />
        )}
      </Card>

      {meta ? (
        <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-muted">
          <p>
            {meta.total} product{meta.total === 1 ? "" : "s"} · page {meta.page} of{" "}
            {Math.max(meta.total_pages, 1)} · {meta.per_page} per page
          </p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="btn btn-sm"
              disabled={meta.page <= 1 || loading}
              onClick={() => setPage((value) => Math.max(1, value - 1))}
            >
              Previous
            </button>
            <button
              type="button"
              className="btn btn-sm"
              disabled={meta.page >= meta.total_pages || loading}
              onClick={() => setPage((value) => value + 1)}
            >
              Next
            </button>
          </div>
        </div>
      ) : null}

      {importOpen ? (
        <ImportDialog
          onClose={() => setImportOpen(false)}
          onDone={() => {
            reload();
            notify("Import finished.");
          }}
        />
      ) : null}

      {createOpen ? (
        <CreateDialog
          categories={categories.data?.data ?? []}
          onClose={() => setCreateOpen(false)}
          onCreated={(product) => {
            setCreateOpen(false);
            reload();
            notify(`${product.name} created.`);
          }}
        />
      ) : null}

      {toast ? <Toast message={toast.message} tone={toast.tone} /> : null}
    </div>
  );
}

function ImportDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    const formData = new FormData();
    formData.append("file", file);
    try {
      const response = await api.upload<ImportResult>("/products/import/csv", formData);
      setResult(response);
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Import products from CSV"
      description="UTF-8 CSV. Rows are validated individually; rejected rows are reported with their line numbers and nothing is guessed."
      onClose={onClose}
    >
      <form onSubmit={submit} className="space-y-4">
        <div>
          <label htmlFor="csv-file" className="mb-1.5 block text-xs font-medium text-muted">
            CSV file (max 2 MB)
          </label>
          <input
            id="csv-file"
            type="file"
            accept=".csv,text/csv"
            className="field"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </div>

        {error ? (
          <p role="alert" className="text-sm" style={{ color: "var(--color-danger)" }}>
            {error}
          </p>
        ) : null}

        {result ? (
          <div className="space-y-3">
            <div className="flex flex-wrap gap-2">
              <Pill tone="good">{result.created} created</Pill>
              <Pill tone="accent">{result.updated} updated</Pill>
              <Pill tone={result.rejected ? "danger" : "muted"}>{result.rejected} rejected</Pill>
            </div>
            {result.errors.length ? (
              <div className="max-h-48 overflow-y-auto rounded-md border border-line">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Row</th>
                      <th>Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.errors.map((item, index) => (
                      <tr key={`${item.row}-${index}`}>
                        <td className="num">{item.row}</td>
                        <td className="text-xs">{item.issue}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </div>
        ) : null}

        <div className="flex justify-end gap-2 border-t border-line pt-3">
          <button type="button" className="btn btn-sm" onClick={onClose}>
            Close
          </button>
          <button type="submit" className="btn btn-sm btn-primary" disabled={!file || busy}>
            {busy ? "Importing…" : "Import"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function CreateDialog({
  categories,
  onClose,
  onCreated,
}: {
  categories: Category[];
  onClose: () => void;
  onCreated: (product: ProductDetail) => void;
}) {
  const [name, setName] = useState("");
  const [brand, setBrand] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [price, setPrice] = useState("");
  const [description, setDescription] = useState("");
  const [keywords, setKeywords] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const product = await api.post<ProductDetail>("/products", {
        name: name.trim(),
        brand: brand.trim() || null,
        category_id: categoryId || null,
        price: price || null,
        description: description.trim() || null,
        keywords: keywords
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
      });
      onCreated(product);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Add a product manually"
      description="Manual products have a price observation only. Without a trend source their growth stays unavailable, not zero."
      onClose={onClose}
    >
      <form onSubmit={submit} className="space-y-3">
        <div>
          <label htmlFor="new-name" className="mb-1 block text-xs font-medium text-muted">
            Name *
          </label>
          <input
            id="new-name"
            className="field"
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
            minLength={2}
          />
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor="new-brand" className="mb-1 block text-xs font-medium text-muted">
              Brand
            </label>
            <input id="new-brand" className="field" value={brand} onChange={(event) => setBrand(event.target.value)} />
          </div>
          <div>
            <label htmlFor="new-category" className="mb-1 block text-xs font-medium text-muted">
              Category
            </label>
            <select
              id="new-category"
              className="field"
              value={categoryId}
              onChange={(event) => setCategoryId(event.target.value)}
            >
              <option value="">Uncategorised</option>
              {categories.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div>
          <label htmlFor="new-price" className="mb-1 block text-xs font-medium text-muted">
            Observed market price (AUD)
          </label>
          <input
            id="new-price"
            className="field"
            inputMode="decimal"
            placeholder="e.g. 49.95"
            value={price}
            onChange={(event) => setPrice(event.target.value)}
          />
        </div>
        <div>
          <label htmlFor="new-description" className="mb-1 block text-xs font-medium text-muted">
            Description
          </label>
          <textarea
            id="new-description"
            className="field min-h-[80px]"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </div>
        <div>
          <label htmlFor="new-keywords" className="mb-1 block text-xs font-medium text-muted">
            Keywords (comma separated)
          </label>
          <input
            id="new-keywords"
            className="field"
            value={keywords}
            onChange={(event) => setKeywords(event.target.value)}
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
          <button type="submit" className="btn btn-sm btn-primary" disabled={busy || name.trim().length < 2}>
            {busy ? "Creating…" : "Create product"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
