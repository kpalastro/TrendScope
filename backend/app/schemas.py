"""Request bodies and response models.

Response payloads are mostly assembled in ``app.services.presenters`` so that
money stays a decimal string and missing values stay ``null`` with a reason —
both contract requirements. The models here document the stable shapes.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models import WATCH_STATUSES


class ErrorDetail(BaseModel):
    field: str | None = None
    issue: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


# --- auth -----------------------------------------------------------------


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    id: UUID
    email: str
    display_name: str | None
    role: str
    permissions: list[str] = Field(default_factory=list)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


# --- shared payloads ------------------------------------------------------


class DataQuality(BaseModel):
    coverage_pct: float
    confidence: float
    synthetic: bool
    synthetic_share: float
    sources: list[str] = Field(default_factory=list)
    missing_components: list[str] = Field(default_factory=list)
    last_updated: datetime | None = None
    warnings: list[str] = Field(default_factory=list)


class Growth(BaseModel):
    pct: float | None
    reason: str
    window_days: int


class ComponentScore(BaseModel):
    label: str | None = None
    score: float | None
    weight: float
    status: str
    reason: str | None = None
    raw: dict[str, Any] | None = None


class ScoreBreakdown(BaseModel):
    score: float
    score_raw: float
    classification: str
    coverage_pct: float
    confidence: float
    components: dict[str, ComponentScore]
    profile: dict[str, Any]
    calculated_on: date


class PriceRange(BaseModel):
    min: str | None
    max: str | None
    market_avg: str | None
    currency: str = "AUD"


class CategoryOut(BaseModel):
    id: UUID
    name: str
    slug: str
    parent_id: UUID | None
    path: str
    level: int
    product_count: int = 0


class ProductSummary(BaseModel):
    id: UUID
    name: str
    slug: str
    category: CategoryOut | None
    brand: str | None
    image_url: str | None
    country: str
    currency: str
    price_range: PriceRange
    opportunity_score: float | None
    classification: str | None
    growth: dict[str, Growth]
    competition_class: str
    trend_direction: str
    estimated_margin_pct: float | None
    supplier_available: bool
    data_quality: DataQuality
    first_seen_at: datetime
    updated_at: datetime


class PaginationMeta(BaseModel):
    page: int
    per_page: int
    total: int
    total_pages: int
    generated_at: datetime
    filters_applied: dict[str, Any] = Field(default_factory=dict)


class ProductList(BaseModel):
    data: list[ProductSummary]
    meta: PaginationMeta


class TrendPoint(BaseModel):
    date: date
    value: float


class ObservationOut(BaseModel):
    metric_name: str
    unit: str | None
    granularity: str
    country: str
    is_synthetic: bool
    points: list[TrendPoint]


class ListingOut(BaseModel):
    id: UUID
    marketplace: str
    title: str | None
    seller_name: str | None
    price: str | None
    currency: str
    rating: float | None
    review_count: int | None
    is_active: bool


class SupplierOfferOut(BaseModel):
    id: UUID
    supplier_id: UUID
    supplier_name: str
    country: str | None
    supplier_rating: float | None
    product_cost: str
    shipping_cost: str
    currency: str
    minimum_order_quantity: int
    lead_time_days: int | None
    availability: str
    is_synthetic: bool


class CompetitionOut(BaseModel):
    product_id: UUID
    index: float | None
    classification: str
    coverage: float
    evidence: dict[str, Any]
    unavailable: list[str]
    caveats: list[str]
    classified_at: date | None


class ProductDetail(ProductSummary):
    description: str | None
    keywords: list[str]
    model: str | None
    attributes: dict[str, Any]
    score_breakdown: ScoreBreakdown | None
    competition: CompetitionOut | None
    listings: list[ListingOut]
    suppliers: list[SupplierOfferOut]
    trend_series: list[ObservationOut]
    recent_scores: list[ScoreBreakdown]
    sources: list[dict[str, Any]]
    disclaimer: str


# --- products -------------------------------------------------------------


class ProductCreate(BaseModel):
    name: str = Field(min_length=2, max_length=300)
    category_id: UUID | None = None
    brand: str | None = Field(default=None, max_length=160)
    description: str | None = None
    price: str | None = None
    keywords: list[str] = Field(default_factory=list)


class ProductPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=300)
    category_id: UUID | None = None
    brand: str | None = Field(default=None, max_length=160)
    description: str | None = None
    status: Literal["discovered", "active", "archived"] | None = None


# --- dashboard ------------------------------------------------------------


class WidgetItem(BaseModel):
    id: UUID
    name: str
    slug: str
    opportunity_score: float | None
    classification: str | None
    growth_7d_pct: float | None
    growth_30d_pct: float | None
    competition_class: str
    trend_direction: str
    category: str | None
    is_synthetic: bool


class DashboardWidget(BaseModel):
    key: str
    title: str
    items: list[WidgetItem]
    note: str | None = None


class SourceHealth(BaseModel):
    id: UUID
    provider_key: str
    provider_name: str
    sync_status: str
    last_sync_at: datetime | None
    is_synthetic: bool
    enabled: bool


class DashboardSummary(BaseModel):
    country: str
    products_monitored: int
    new_this_week: int
    increasing_demand: int
    declining_demand: int
    high_opportunity: int
    average_opportunity_score: float | None
    data_sources: list[SourceHealth]
    last_sync_at: datetime | None
    generated_at: datetime


class DashboardResponse(BaseModel):
    summary: DashboardSummary
    widgets: list[DashboardWidget]


# --- watchlist ------------------------------------------------------------


class WatchlistCreate(BaseModel):
    product_id: UUID
    status: str = "discovered"
    notes: str | None = Field(default=None, max_length=4000)
    priority: int | None = Field(default=None, ge=1, le=5)

    @field_validator("status")
    @classmethod
    def _valid_status(cls, value: str) -> str:
        if value not in WATCH_STATUSES:
            raise ValueError(f"status must be one of {', '.join(WATCH_STATUSES)}")
        return value


class WatchlistUpdate(BaseModel):
    status: str | None = None
    notes: str | None = Field(default=None, max_length=4000)
    priority: int | None = Field(default=None, ge=1, le=5)

    @field_validator("status")
    @classmethod
    def _valid_status(cls, value: str | None) -> str | None:
        if value is not None and value not in WATCH_STATUSES:
            raise ValueError(f"status must be one of {', '.join(WATCH_STATUSES)}")
        return value


class WatchlistOut(BaseModel):
    id: UUID
    product_id: UUID
    status: str
    notes: str | None
    priority: int | None
    created_at: datetime
    updated_at: datetime
    product: ProductSummary


# --- sources, jobs, reports ----------------------------------------------


class DataSourceOut(BaseModel):
    id: UUID
    provider_key: str
    provider_name: str
    source_type: str
    enabled: bool
    configured: bool
    is_synthetic: bool
    config: dict[str, Any]
    secret_ref: list[str]
    rate_limit_per_min: int
    sync_status: str
    last_sync_at: datetime | None
    last_error: str | None
    consecutive_failures: int


class SourcePatch(BaseModel):
    enabled: bool | None = None
    config: dict[str, Any] | None = None
    rate_limit_per_min: int | None = Field(default=None, ge=1, le=6000)


class RunOut(BaseModel):
    id: UUID
    source_id: UUID
    job_name: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    records_fetched: int
    records_written: int
    records_rejected: int
    error_count: int
    error_summary: str | None


class JobOut(BaseModel):
    id: str
    type: str
    status: str
    progress: dict[str, Any]
    result_url: str | None
    error: str | None
    created_at: datetime
    poll_url: str


class ReportCreate(BaseModel):
    type: Literal["weekly_trends"] = "weekly_trends"
    country: str = Field(default="AU", min_length=2, max_length=2)
    period_start: date
    period_end: date


class ReportOut(BaseModel):
    id: UUID
    report_type: str
    country: str
    period_start: date
    period_end: date
    status: str
    summary: str | None
    report_data: dict[str, Any]
    sources: list[Any]
    generated_at: datetime | None
    error: str | None


class ScoringProfileOut(BaseModel):
    id: UUID
    name: str
    country: str
    version: int
    weights: dict[str, float]
    thresholds: dict[str, float]
    is_active: bool
    is_default: bool
    created_at: datetime
