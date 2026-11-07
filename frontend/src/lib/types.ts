export type GrowthReason =
  | "ok"
  | "no_source"
  | "insufficient_current_data"
  | "insufficient_baseline"
  | "zero_baseline"
  | "stale_data";

export type Growth = {
  pct: number | null;
  reason: GrowthReason | string;
  window_days: number;
};

export type DataQuality = {
  coverage_pct: number;
  confidence: number;
  synthetic: boolean;
  synthetic_share: number;
  sources: string[];
  missing_components: string[];
  last_updated: string | null;
  warnings: string[];
};

export type PriceRange = {
  min: string | null;
  max: string | null;
  market_avg: string | null;
  currency: string;
};

export type Category = {
  id: string;
  name: string;
  slug: string;
  parent_id: string | null;
  path: string;
  level: number;
  product_count?: number;
};

export type ProductSummary = {
  id: string;
  name: string;
  slug: string;
  category: Category | null;
  brand: string | null;
  image_url: string | null;
  country: string;
  currency: string;
  price_range: PriceRange;
  opportunity_score: number | null;
  classification: string | null;
  growth: { d7: Growth; d30: Growth; d90: Growth };
  competition_class: string;
  trend_direction: string;
  estimated_margin_pct: number | null;
  supplier_available: boolean;
  data_quality: DataQuality;
  first_seen_at: string;
  updated_at: string;
};

export type PaginationMeta = {
  page: number;
  per_page: number;
  total: number;
  total_pages: number;
  generated_at: string;
  filters_applied: Record<string, unknown>;
};

export type ProductList = { data: ProductSummary[]; meta: PaginationMeta };

export type TrendPoint = { date: string; value: number | null };

export type ObservationSeries = {
  metric_name: string;
  unit: string | null;
  granularity: string;
  country: string;
  is_synthetic: boolean;
  points: TrendPoint[];
};

export type ComponentScore = {
  label: string | null;
  score: number | null;
  weight: number;
  status: string;
  reason: string | null;
  raw: Record<string, number | null> | null;
};

export type ScoreBreakdown = {
  score: number;
  score_raw: number;
  classification: string;
  coverage_pct: number;
  confidence: number;
  components: Record<string, ComponentScore>;
  profile: { id?: string; name?: string; version?: number };
  calculated_on: string;
};

export type Listing = {
  id: string;
  marketplace: string;
  title: string | null;
  seller_name: string | null;
  price: string | null;
  currency: string;
  rating: number | null;
  review_count: number | null;
  is_active: boolean;
};

export type SupplierOffer = {
  id: string;
  supplier_id: string;
  supplier_name: string;
  country: string | null;
  supplier_rating: number | null;
  product_cost: string;
  shipping_cost: string;
  currency: string;
  minimum_order_quantity: number;
  lead_time_days: number | null;
  availability: string;
  is_synthetic: boolean;
};

export type Competition = {
  product_id: string;
  index: number | null;
  classification: string;
  coverage: number;
  evidence: Record<string, unknown>;
  unavailable: string[];
  caveats: string[];
  classified_at: string | null;
};

export type ProductDetail = ProductSummary & {
  description: string | null;
  keywords: string[];
  model: string | null;
  attributes: Record<string, unknown>;
  score_breakdown: ScoreBreakdown | null;
  competition: Competition | null;
  listings: Listing[];
  suppliers: SupplierOffer[];
  trend_series: ObservationSeries[];
  recent_scores: ScoreBreakdown[];
  sources: {
    provider_key: string;
    provider_name: string;
    collection_date: string | null;
    is_synthetic: boolean;
  }[];
  disclaimer: string;
};

export type WidgetItem = {
  id: string;
  name: string;
  slug: string;
  opportunity_score: number | null;
  classification: string | null;
  growth_7d_pct: number | null;
  growth_30d_pct: number | null;
  competition_class: string;
  trend_direction: string;
  category: string | null;
  is_synthetic: boolean;
};

export type DashboardWidget = {
  key: string;
  title: string;
  items: WidgetItem[];
  note: string | null;
};

export type SourceHealth = {
  id: string;
  provider_key: string;
  provider_name: string;
  sync_status: string;
  last_sync_at: string | null;
  is_synthetic: boolean;
  enabled: boolean;
};

export type DashboardSummary = {
  country: string;
  products_monitored: number;
  new_this_week: number;
  increasing_demand: number;
  declining_demand: number;
  high_opportunity: number;
  average_opportunity_score: number | null;
  data_sources: SourceHealth[];
  last_sync_at: string | null;
  generated_at: string;
};

export type DashboardResponse = {
  summary: DashboardSummary;
  widgets: DashboardWidget[];
};

export type User = {
  id: string;
  email: string;
  display_name: string | null;
  role: "admin" | "analyst" | "viewer" | string;
  permissions: string[];
};

export type LoginResponse = {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
};

export type DiscoverResponse = {
  data: ProductSummary[];
  meta: {
    generated_at: string;
    note: string;
    [key: string]: unknown;
  };
};

export type DataSource = {
  id: string;
  provider_key: string;
  provider_name: string;
  source_type: string;
  enabled: boolean;
  configured: boolean;
  is_synthetic: boolean;
  config: Record<string, unknown>;
  secret_ref: string[];
  rate_limit_per_min: number;
  sync_status: string;
  last_sync_at: string | null;
  last_error: string | null;
  consecutive_failures: number;
};

export type IngestionRun = {
  id: string;
  source_id: string;
  job_name: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  records_fetched: number;
  records_written: number;
  records_rejected: number;
  error_count: number;
  error_summary: string | null;
};

export type SourceStatus = DataSource & { latest_run: IngestionRun | null };

export type Job = {
  id: string;
  type: string;
  status: string;
  progress: Record<string, number>;
  result_url: string | null;
  error: string | null;
  created_at: string;
  poll_url: string;
};

export type WatchlistEntry = {
  id: string;
  product_id: string;
  status: string;
  notes: string | null;
  priority: number | null;
  created_at: string;
  updated_at: string;
  product: ProductSummary;
};

export type ReportRow = {
  product_id: string;
  name: string;
  slug: string;
  category: string | null;
  opportunity_score: number | null;
  classification: string | null;
  growth_7d_pct: number | null;
  growth_30d_pct: number | null;
  growth_reason_30d: string;
  competition_class: string;
  trend_direction: string;
  estimated_margin_pct: number | null;
  is_synthetic: boolean;
};

export type ReportData = {
  period?: { start: string; end: string };
  generated_at?: string;
  top_growth?: ReportRow[];
  top_opportunities?: ReportRow[];
  emerging?: ReportRow[];
  new_products?: number;
  categories?: { name: string; product_count: number }[];
  watchlist?: Record<string, number>;
  growth_unavailable?: Record<string, number>;
  sources?: {
    provider_key: string;
    provider_name: string;
    collection_date: string | null;
    is_synthetic: boolean;
    sync_status: string;
  }[];
  limitations?: string[];
  disclaimer?: string;
};

export type Report = {
  id: string;
  report_type: string;
  country: string;
  period_start: string;
  period_end: string;
  status: string;
  summary: string | null;
  report_data: ReportData;
  sources: unknown[];
  generated_at: string | null;
  error: string | null;
};

export type ImportResult = {
  job: Job;
  created: number;
  updated: number;
  rejected: number;
  errors: { row: number; issue: string }[];
};

export type ScoringProfile = {
  id: string;
  name: string;
  country: string;
  version: number;
  weights: Record<string, number>;
  thresholds: Record<string, number>;
  is_active: boolean;
  is_default: boolean;
  created_at: string;
};
