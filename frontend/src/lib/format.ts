const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return `${date.getDate()} ${MONTHS[date.getMonth()]} ${date.getFullYear()}`;
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const time = date.toLocaleTimeString("en-AU", { hour: "2-digit", minute: "2-digit" });
  return `${formatDate(value)}, ${time}`;
}

export function formatShortDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return `${date.getDate()} ${MONTHS[date.getMonth()]}`;
}

export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const rounded = Math.round(value * 10 ** digits) / 10 ** digits;
  return `${rounded > 0 ? "+" : ""}${rounded.toFixed(digits)}%`;
}

export function score(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(1);
}

export function money(value: string | number | null | undefined, currency = "AUD"): string {
  if (value === null || value === undefined || value === "") return "—";
  const number = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(number)) return "—";
  return new Intl.NumberFormat("en-AU", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(number);
}

export function compact(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("en-AU", { notation: "compact", maximumFractionDigits: 1 }).format(
    value,
  );
}

export const GROWTH_REASON: Record<string, string> = {
  no_source: "No trend source returned data for this product.",
  insufficient_current_data: "The current window has too few observations.",
  insufficient_baseline: "The baseline window has too few observations.",
  zero_baseline: "Baseline average is zero, so percentage change is undefined.",
  stale_data: "The latest observation is older than three days.",
};

export const CLASSIFICATION_LABEL: Record<string, string> = {
  excellent: "Excellent",
  strong: "Strong",
  worth_investigating: "Worth investigating",
  moderate: "Moderate",
  weak: "Weak",
  low_priority: "Low priority",
  insufficient_data: "Insufficient data",
};

export const CLASSIFICATION_TONE: Record<string, "good" | "accent" | "amber" | "muted" | "danger"> = {
  excellent: "good",
  strong: "accent",
  worth_investigating: "accent",
  moderate: "amber",
  weak: "muted",
  low_priority: "muted",
  insufficient_data: "muted",
};

export const COMPONENT_LABEL: Record<string, string> = {
  demand: "Demand",
  marketplace: "Marketplace",
  social: "Social",
  competition: "Competition",
  profitability: "Profitability",
  seasonal: "Seasonal",
};

export const WATCH_STATUSES = [
  "discovered",
  "researching",
  "shortlisted",
  "supplier_validation",
  "ready_for_catalogue",
  "published",
  "rejected",
] as const;

export const COMPETITION_LABEL: Record<string, string> = {
  low: "Low",
  moderate: "Moderate",
  high: "High",
  saturated: "Saturated",
  unknown: "Unknown",
};

export function titleCase(value: string | null | undefined): string {
  if (!value) return "—";
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export function relativeDays(value: string | null | undefined): string {
  if (!value) return "never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "never";
  const days = Math.floor((Date.now() - date.getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days} days ago`;
  const months = Math.floor(days / 30);
  return months === 1 ? "a month ago" : `${months} months ago`;
}
