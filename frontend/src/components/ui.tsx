"use client";

import Link from "next/link";
import { AlertTriangle, ArrowDownRight, ArrowUpRight, Minus, Sparkles } from "lucide-react";
import { CLASSIFICATION_LABEL, CLASSIFICATION_TONE, GROWTH_REASON, pct, score } from "@/lib/format";
import type { DataQuality, Growth } from "@/lib/types";

export type Tone = "good" | "accent" | "amber" | "muted" | "danger";

export function Card({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <div className={`card ${className}`}>{children}</div>;
}

export function Pill({ tone = "muted", children }: { tone?: Tone; children: React.ReactNode }) {
  return <span className={`pill pill-${tone}`}>{children}</span>;
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 border-b border-line pb-5">
      <div className="min-w-0">
        {eyebrow ? <p className="eyebrow mb-1.5">{eyebrow}</p> : null}
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{title}</h1>
        {description ? (
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2.5 text-sm text-muted" role="status">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-line border-t-accent" />
      {label ?? "Loading"}
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden="true" />;
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <Card className="p-5">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber" aria-hidden="true" />
        <div className="min-w-0">
          <p className="text-sm font-medium">Could not load this view</p>
          <p className="mt-1 text-sm text-muted">{message}</p>
          {onRetry ? (
            <button type="button" className="btn btn-sm mt-3" onClick={onRetry}>
              Try again
            </button>
          ) : null}
        </div>
      </div>
    </Card>
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
      <div className="flex h-11 w-11 items-center justify-center rounded-full border border-line bg-raised text-muted">
        {icon ?? <Sparkles className="h-5 w-5" aria-hidden="true" />}
      </div>
      <div>
        <p className="text-sm font-medium">{title}</p>
        {description ? <p className="mx-auto mt-1 max-w-md text-sm text-muted">{description}</p> : null}
      </div>
      {action}
    </div>
  );
}

export function ScoreBadge({
  value,
  classification,
  size = "md",
}: {
  value: number | null;
  classification: string | null;
  size?: "sm" | "md";
}) {
  const tone = classification ? CLASSIFICATION_TONE[classification] ?? "muted" : "muted";
  const label = classification ? CLASSIFICATION_LABEL[classification] ?? classification : "Not scored";
  return (
    <span className={`score-badge score-badge-${tone} ${size === "sm" ? "score-badge-sm" : ""}`}>
      <span className="num score-badge-value">{score(value)}</span>
      <span className="score-badge-label">{label}</span>
    </span>
  );
}

export function GrowthValue({
  growth,
  showWindow = false,
  className = "",
}: {
  growth: Growth | undefined;
  showWindow?: boolean;
  className?: string;
}) {
  if (!growth) return <span className={`text-muted ${className}`}>—</span>;
  if (growth.pct === null) {
    return (
      <span
        className={`text-muted ${className}`}
        title={GROWTH_REASON[growth.reason] ?? "Growth unavailable"}
      >
        —{showWindow ? <span className="ml-1 text-[0.68rem]">{growth.window_days}d</span> : null}
      </span>
    );
  }
  const positive = growth.pct > 0;
  const flat = growth.pct === 0;
  const Icon = flat ? Minus : positive ? ArrowUpRight : ArrowDownRight;
  const tone = flat ? "text-muted" : positive ? "text-good" : "text-danger";
  return (
    <span className={`num inline-flex items-center gap-0.5 ${tone} ${className}`}>
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {pct(growth.pct)}
      {showWindow ? <span className="ml-1 text-[0.68rem] text-muted">{growth.window_days}d</span> : null}
    </span>
  );
}

export function DataQualityChip({ quality }: { quality: DataQuality }) {
  const tone: Tone =
    quality.coverage_pct >= 70 ? "good" : quality.coverage_pct >= 60 ? "amber" : "danger";
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <Pill tone={tone}>{quality.coverage_pct.toFixed(0)}% coverage</Pill>
      {quality.synthetic ? <Pill tone="amber">Synthetic</Pill> : null}
    </span>
  );
}

export function SyntheticNote({ text }: { text?: string }) {
  return (
    <p className="flex items-start gap-2 rounded-md border border-line bg-raised px-3 py-2 text-xs leading-relaxed text-muted">
      <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber" aria-hidden="true" />
      <span>
        {text ??
          "Synthetic demo data. Values are generated for the prototype and are not market facts."}
      </span>
    </p>
  );
}

export function ProductLink({
  slug,
  name,
  className = "",
}: {
  slug: string;
  name: string;
  className?: string;
}) {
  return (
    <Link href={`/products/${slug}`} className={`link ${className}`}>
      {name}
    </Link>
  );
}

export function KeyValue({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-2 py-2 text-sm">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 text-right font-medium">{children}</dd>
    </div>
  );
}

export function Modal({
  title,
  description,
  onClose,
  children,
  width = "max-w-lg",
}: {
  title: string;
  description?: string;
  onClose: () => void;
  children: React.ReactNode;
  width?: string;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto p-4 sm:items-center">
      <button
        type="button"
        className="fixed inset-0 bg-black/45"
        aria-label="Close dialog"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`card relative my-8 w-full ${width} p-5`}
      >
        <div className="flex items-start justify-between gap-4 border-b border-line pb-3">
          <div>
            <h2 className="text-base font-semibold tracking-tight">{title}</h2>
            {description ? <p className="mt-1 text-xs leading-relaxed text-muted">{description}</p> : null}
          </div>
          <button type="button" className="btn btn-sm h-7 w-7 !p-0" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="pt-4">{children}</div>
      </div>
    </div>
  );
}

