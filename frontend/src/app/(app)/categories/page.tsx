"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { FolderTree, Layers, Plus, RefreshCw } from "lucide-react";
import { useAuth } from "@/components/AuthProvider";
import {
  Card,
  ErrorState,
  Modal,
  PageHeader,
  Pill,
  Skeleton,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { Category } from "@/lib/types";

type CategoryNode = Category & { children: CategoryNode[] };

function flatten(nodes: CategoryNode[], depth = 0): { node: CategoryNode; depth: number }[] {
  return nodes.flatMap((node) => [
    { node, depth },
    ...flatten(node.children ?? [], depth + 1),
  ]);
}

export default function CategoriesPage() {
  const { isAdmin } = useAuth();
  const { data, error, loading, reload } = useApi<{ data: CategoryNode[] }>("/categories?tree=true");
  const [createOpen, setCreateOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const roots = data?.data ?? [];
  const flat = useMemo(() => flatten(roots), [roots]);
  const totalProducts = flat.reduce((sum, item) => sum + (item.node.product_count ?? 0), 0);

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Taxonomy"
        title="Categories"
        description="A flat, 16-category taxonomy in Phase 1. Counts are active products with a latest metric."
        actions={
          <>
            <button type="button" className="btn btn-sm" onClick={reload} disabled={loading}>
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} aria-hidden="true" />
              Refresh
            </button>
            {isAdmin ? (
              <button type="button" className="btn btn-sm btn-primary" onClick={() => setCreateOpen(true)}>
                <Plus className="h-3.5 w-3.5" aria-hidden="true" /> Add category
              </button>
            ) : null}
          </>
        }
      />

      <div className="grid gap-3 sm:grid-cols-3">
        <Card className="p-4">
          <p className="eyebrow">Categories</p>
          <p className="num mt-1.5 text-2xl font-semibold">{flat.length}</p>
        </Card>
        <Card className="p-4">
          <p className="eyebrow">Top-level</p>
          <p className="num mt-1.5 text-2xl font-semibold">{roots.length}</p>
        </Card>
        <Card className="p-4">
          <p className="eyebrow">Categorised products</p>
          <p className="num mt-1.5 text-2xl font-semibold">{totalProducts}</p>
        </Card>
      </div>

      {error ? <ErrorState message={error} onRetry={reload} /> : null}

      {loading && !data ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 9 }).map((_, index) => (
            <Skeleton key={index} className="h-[74px]" />
          ))}
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {flat.map(({ node, depth }) => (
            <Link
              key={node.id}
              href={`/products?category_id=${node.id}`}
              className="card group flex items-center justify-between gap-3 p-4 transition-colors hover:border-accent"
              style={{ marginLeft: depth ? depth * 8 : 0 }}
            >
              <span className="flex min-w-0 items-center gap-2.5">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-line bg-raised text-muted group-hover:text-accent">
                  {depth ? <Layers className="h-4 w-4" aria-hidden="true" /> : <FolderTree className="h-4 w-4" aria-hidden="true" />}
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium">{node.name}</span>
                  <span className="num block truncate text-[0.68rem] text-muted">{node.path}</span>
                </span>
              </span>
              <Pill tone={node.product_count ? "accent" : "muted"}>{node.product_count ?? 0}</Pill>
            </Link>
          ))}
        </div>
      )}

      {!loading && data && flat.length === 0 ? (
        <Card className="p-6 text-sm text-muted">
          No categories yet. Run <span className="num">python -m app.cli init --demo</span> or seed the
          backend to load the 16-category catalogue.
        </Card>
      ) : null}

      {createOpen ? (
        <CreateCategoryDialog
          categories={flat.map((item) => item.node)}
          onClose={() => setCreateOpen(false)}
          onCreated={(name) => {
            setCreateOpen(false);
            setToast(`${name} created.`);
            reload();
          }}
        />
      ) : null}

      {toast ? (
        <div role="status" className="card fixed bottom-4 right-4 z-50 max-w-sm px-4 py-3 text-sm">
          {toast}
        </div>
      ) : null}
    </div>
  );
}

function CreateCategoryDialog({
  categories,
  onClose,
  onCreated,
}: {
  categories: Category[];
  onClose: () => void;
  onCreated: (name: string) => void;
}) {
  const [name, setName] = useState("");
  const [parentId, setParentId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/categories", { name: name.trim(), parent_id: parentId || null });
      onCreated(name.trim());
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Add a category"
      description="Categories are ordered by their path. Duplicate slugs are rejected with a conflict."
      onClose={onClose}
    >
      <form onSubmit={submit} className="space-y-3">
        <div>
          <label htmlFor="category-name" className="mb-1 block text-xs font-medium text-muted">
            Name *
          </label>
          <input
            id="category-name"
            className="field"
            value={name}
            onChange={(event) => setName(event.target.value)}
            minLength={2}
            required
          />
        </div>
        <div>
          <label htmlFor="parent-category" className="mb-1 block text-xs font-medium text-muted">
            Parent category
          </label>
          <select
            id="parent-category"
            className="field"
            value={parentId}
            onChange={(event) => setParentId(event.target.value)}
          >
            <option value="">None — top level</option>
            {categories.map((category) => (
              <option key={category.id} value={category.id}>
                {category.path}
              </option>
            ))}
          </select>
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
            {busy ? "Creating…" : "Create category"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
