"""Request bodies and response models.

Response payloads are mostly assembled in ``app.services.presenters`` so that
money stays a decimal string and missing values stay ``null`` with a reason —
both contract requirements. The models here document the stable shapes.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
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


METRIC_TYPE_VALUES = (
    "actual_sales",
    "estimated_sales",
    "search_interest",
    "marketplace_listing",
    "marketplace_price",
    "marketplace_review",
    "social_engagement",
    "advertising",
    "supplier_cost",
    "other",
)


class ObservationCreate(BaseModel):
    """A hand-recorded observation, with the provenance the operator must supply.

    ``value`` stays a number on its own; ``metric_type`` says what that number
    means so search interest, listings and engagement are never summed.
    """

    metric_name: str = Field(min_length=1, max_length=60)
    metric_type: Literal[
        "actual_sales",
        "estimated_sales",
        "search_interest",
        "marketplace_listing",
        "marketplace_price",
        "marketplace_review",
        "social_engagement",
        "advertising",
        "supplier_cost",
        "other",
    ] = "search_interest"
    value: float
    unit: str | None = Field(default=None, max_length=20)
    granularity: Literal["daily", "weekly", "monthly"] = "daily"
    observation_date: date
    period_start: date | None = None
    period_end: date | None = None
    country: str | None = Field(default=None, min_length=2, max_length=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    provider_name: str = Field(default="Manual research", min_length=1, max_length=160)
    source_url: str | None = Field(default=None, max_length=600)
    verification_status: Literal["verified", "estimated", "unverified", "synthetic"] = (
        "unverified"
    )
    data_quality: Literal["high", "medium", "low", "unknown", "synthetic"] = "unknown"
    original_metric: str | None = Field(default=None, max_length=120)
    confidence: float = Field(default=0.6, ge=0, le=1)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("value")
    @classmethod
    def _finite_value(cls, value: float) -> float:
        import math

        if not math.isfinite(value):
            raise ValueError("value must be a finite number")
        return value

    @field_validator("observation_date", "period_start", "period_end")
    @classmethod
    def _not_in_future(cls, value: date | None) -> date | None:
        if value is not None and value > date.today():
            raise ValueError("observation dates cannot be in the future")
        return value


class ObservationCorrect(BaseModel):
    """Correction to a hand-entered observation.

    Only operator-entered rows (the ``csv_import`` source) can be corrected;
    connector history stays append-only. The previous value is retained in the
    row's ``metadata.corrections`` log so the change remains auditable.
    """

    value: float | None = None
    verification_status: Literal["verified", "estimated", "unverified"] | None = None
    data_quality: Literal["high", "medium", "low", "unknown"] | None = None
    source_url: str | None = Field(default=None, max_length=600)
    notes: str | None = Field(default=None, max_length=2000)
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("value")
    @classmethod
    def _finite_value(cls, value: float | None) -> float | None:
        import math

        if value is not None and not math.isfinite(value):
            raise ValueError("value must be a finite number")
        return value


class SupplierOfferCreate(BaseModel):
    supplier_name: str = Field(min_length=2, max_length=200)
    supplier_url: str | None = Field(default=None, max_length=600)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    supplier_rating: float | None = Field(default=None, ge=0, le=5)
    product_cost: Decimal = Field(gt=0)
    shipping_cost: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(default="AUD", min_length=3, max_length=3)
    minimum_order_quantity: int = Field(default=1, ge=1)
    lead_time_days: int | None = Field(default=None, ge=0)
    availability: Literal["in_stock", "out_of_stock", "unknown"] = "in_stock"
    external_product_id: str | None = Field(default=None, max_length=200)
    platform_key: str = Field(default="manual", min_length=1, max_length=40)


class SupplierOfferPatch(BaseModel):
    supplier_name: str | None = Field(default=None, min_length=2, max_length=200)
    supplier_url: str | None = Field(default=None, max_length=600)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    supplier_rating: float | None = Field(default=None, ge=0, le=5)
    product_cost: Decimal | None = Field(default=None, gt=0)
    shipping_cost: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    minimum_order_quantity: int | None = Field(default=None, ge=1)
    lead_time_days: int | None = Field(default=None, ge=0)
    availability: Literal["in_stock", "out_of_stock", "unknown"] | None = None


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
    last_success_at: datetime | None
    last_error: str | None
    consecutive_failures: int
    cost_model: str
    monthly_cost: str | None
    cost_currency: str
    estimated_monthly_spend: str | None
    request_limit_month: int | None
    requests_used_month: int
    usage_period: str | None
    availability: str
    availability_reason: str | None
    usage_rights: str
    docs_url: str | None
    terms_url: str | None
    health: str
    connector: dict[str, Any]


class SourcePatch(BaseModel):
    enabled: bool | None = None
    config: dict[str, Any] | None = None
    rate_limit_per_min: int | None = Field(default=None, ge=1, le=6000)
    cost_model: Literal["free", "paid", "manual", "synthetic"] | None = None
    monthly_cost: Decimal | None = Field(default=None, ge=0)
    cost_currency: str | None = Field(default=None, min_length=3, max_length=3)
    request_limit_month: int | None = Field(default=None, ge=0)
    usage_rights: (
        Literal[
            "api_terms",
            "manual_research",
            "synthetic",
            "redistribution_not_granted",
            "unspecified",
        ]
        | None
    ) = None
    docs_url: str | None = Field(default=None, max_length=600)
    terms_url: str | None = Field(default=None, max_length=600)


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
