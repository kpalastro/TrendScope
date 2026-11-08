from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Allowed values are validated in services; stored as portable strings so the
# schema works on PostgreSQL in production and SQLite in tests.
PRODUCT_STATUSES = ("discovered", "active", "archived", "merged")
WATCH_STATUSES = (
    "discovered",
    "researching",
    "shortlisted",
    "supplier_validation",
    "ready_for_catalogue",
    "published",
    "rejected",
)
COMPETITION_CLASSES = ("low", "moderate", "high", "saturated", "unknown")
TREND_DIRECTIONS = ("rising", "stable", "declining", "unknown")
SCORE_CLASSES = (
    "excellent",
    "strong",
    "worth_investigating",
    "weak",
    "low_priority",
    "insufficient_data",
)
GROWTH_REASONS = (
    "ok",
    "insufficient_baseline",
    "zero_baseline",
    "insufficient_current_data",
    "stale_data",
    "no_source",
)

# Free-first source metadata. Cost visibility is a first-class field rather than
# something inferred from a provider name: a free connector must stay free, and
# a paid plugin must declare what it costs before it is enabled.
COST_MODELS = ("free", "paid", "manual", "synthetic")
AVAILABILITY_STATES = (
    "available",
    "requires_credentials",
    "manual_fallback",
    "unavailable",
)
USAGE_RIGHTS = (
    "api_terms",
    "manual_research",
    "synthetic",
    "redistribution_not_granted",
    "unspecified",
)
METRIC_TYPES = (
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
VERIFICATION_STATUSES = ("verified", "estimated", "unverified", "synthetic")
DATA_QUALITY_LEVELS = ("high", "medium", "low", "unknown", "synthetic")

# Deterministic product-identity keys and the merge-review queue. Identifiers
# are what make deduplication safe: names are ambiguous, GTINs/ASINs are not.
IDENTIFIER_SCHEMES = (
    "gtin",
    "upc",
    "ean",
    "isbn",
    "asin",
    "ebay_item",
    "supplier_sku",
    "mpn",
    "shopify_sku",
)
MATCH_METHODS = ("identifier", "alias", "name_exact", "fuzzy")
MATCH_STATUSES = ("pending", "merged", "rejected")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(20), default="analyst", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuthRefreshToken(Base):
    """Rotating refresh tokens. Only a SHA-256 hash is stored, never the token."""

    __tablename__ = "auth_refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("auth_refresh_tokens.id", ondelete="SET NULL")
    )
    user_agent: Mapped[str | None] = mapped_column(String(300))
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_refresh_user_expires", "user_id", "expires_at"),
    )


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("categories.id", ondelete="RESTRICT")
    )
    path: Mapped[str] = mapped_column(String(400), nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_categories_parent", "parent_id"),)


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider_key: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    provider_name: Mapped[str] = mapped_column(String(160), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    secret_ref: Mapped[str | None] = mapped_column(String(400))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rate_limit_per_min: Mapped[int] = mapped_column(Integer, default=60)
    cost_model: Mapped[str] = mapped_column(String(20), default="free", nullable=False)
    monthly_cost: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    cost_currency: Mapped[str] = mapped_column(String(3), default="AUD", nullable=False)
    request_limit_month: Mapped[int | None] = mapped_column(Integer)
    requests_used_month: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usage_period: Mapped[str | None] = mapped_column(String(7))
    availability: Mapped[str] = mapped_column(String(30), default="available", nullable=False)
    availability_reason: Mapped[str | None] = mapped_column(Text)
    usage_rights: Mapped[str] = mapped_column(
        String(40), default="unspecified", nullable=False
    )
    docs_url: Mapped[str | None] = mapped_column(String(600))
    terms_url: Mapped[str | None] = mapped_column(String(600))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_status: Mapped[str] = mapped_column(String(20), default="never_run")
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False
    )
    job_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    records_fetched: Mapped[int] = mapped_column(Integer, default=0)
    records_written: Mapped[int] = mapped_column(Integer, default=0)
    records_rejected: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text)
    cursor: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (Index("ix_runs_source_started", "source_id", "started_at"),)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str | None] = mapped_column(String(200))
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("data_sources.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    normalised_name: Mapped[str] = mapped_column(String(300), nullable=False)
    slug: Mapped[str] = mapped_column(String(300), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("categories.id", ondelete="SET NULL")
    )
    brand: Mapped[str | None] = mapped_column(String(160))
    model: Mapped[str | None] = mapped_column(String(160))
    image_url: Mapped[str | None] = mapped_column(String(600))
    country: Mapped[str] = mapped_column(String(2), default="AU", nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="AUD", nullable=False)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    merged_into_product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="SET NULL")
    )
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_products_source_external"),
        Index("ix_products_category", "category_id"),
        Index("ix_products_normalised", "normalised_name"),
    )


class ProductKeyword(Base):
    __tablename__ = "product_keywords"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    keyword: Mapped[str] = mapped_column(String(200), nullable=False)
    normalised_keyword: Mapped[str] = mapped_column(String(200), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("data_sources.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "product_id", "normalised_keyword", "source_id", name="uq_keyword_product_source"
        ),
        Index("ix_keywords_normalised", "normalised_keyword"),
    )


class ProductIdentifier(Base):
    """A deterministic external identity (GTIN, ASIN, supplier SKU, …)."""

    __tablename__ = "product_identifiers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    scheme: Mapped[str] = mapped_column(String(30), nullable=False)
    value: Mapped[str] = mapped_column(String(200), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("data_sources.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("scheme", "value", name="uq_identifier_scheme_value"),
        Index("ix_identifiers_product", "product_id"),
    )


class ProductAlias(Base):
    """An alternate name observed at a source, used by the matcher."""

    __tablename__ = "product_aliases"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(String(300), nullable=False)
    normalised_alias: Mapped[str] = mapped_column(String(300), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("data_sources.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("product_id", "normalised_alias", name="uq_alias_product_normalised"),
        Index("ix_aliases_normalised", "normalised_alias"),
    )


class ProductMatch(Base):
    """A candidate duplicate awaiting an admin's merge/reject decision."""

    __tablename__ = "product_matches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    product_a_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    product_b_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    similarity: Mapped[float | None] = mapped_column(Numeric(4, 3))
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("product_a_id", "product_b_id", name="uq_match_pair"),
        Index("ix_matches_status", "status"),
    )


class TrendObservation(Base):
    __tablename__ = "trend_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False
    )
    ingestion_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ingestion_runs.id", ondelete="SET NULL")
    )
    observation_date: Mapped[date] = mapped_column(Date, nullable=False)
    granularity: Mapped[str] = mapped_column(String(12), default="daily", nullable=False)
    metric_name: Mapped[str] = mapped_column(String(60), nullable=False)
    metric_type: Mapped[str] = mapped_column(
        String(30), default="search_interest", nullable=False
    )
    metric_value: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(20))
    country: Mapped[str] = mapped_column(String(2), default="AU", nullable=False)
    currency: Mapped[str | None] = mapped_column(String(3))
    provider_name: Mapped[str | None] = mapped_column(String(160))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    source_url: Mapped[str | None] = mapped_column(String(600))
    verification_status: Mapped[str] = mapped_column(
        String(20), default="unverified", nullable=False
    )
    data_quality: Mapped[str] = mapped_column(
        String(20), default="unknown", nullable=False
    )
    original_metric: Mapped[str | None] = mapped_column(String(120))
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    meta: Mapped[dict] = mapped_column("metadata", JSON, default=dict, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "source_id",
            "observation_date",
            "metric_name",
            "granularity",
            "country",
            name="uq_observation_natural_key",
        ),
        Index("ix_obs_product_metric_date", "product_id", "metric_name", "observation_date"),
        Index("ix_obs_date", "observation_date"),
    )


class MarketplaceListing(Base):
    __tablename__ = "marketplace_listings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    marketplace: Mapped[str] = mapped_column(String(30), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("data_sources.id", ondelete="SET NULL")
    )
    external_listing_id: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str | None] = mapped_column(String(300))
    listing_url: Mapped[str | None] = mapped_column(String(600))
    seller_name: Mapped[str | None] = mapped_column(String(200))
    price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="AUD")
    rating: Mapped[float | None] = mapped_column(Numeric(3, 2))
    review_count: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("marketplace", "external_listing_id", name="uq_listing_external"),
        Index("ix_listings_product", "product_id"),
    )


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    supplier_name: Mapped[str] = mapped_column(String(200), nullable=False)
    supplier_url: Mapped[str | None] = mapped_column(String(600))
    country: Mapped[str | None] = mapped_column(String(2))
    supplier_rating: Mapped[float | None] = mapped_column(Numeric(3, 2))
    platform_key: Mapped[str] = mapped_column(String(40), default="mock")
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("data_sources.id", ondelete="SET NULL")
    )
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("platform_key", "supplier_name", name="uq_supplier_platform_name"),
    )


class SupplierProduct(Base):
    __tablename__ = "supplier_products"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False
    )
    external_product_id: Mapped[str] = mapped_column(String(200), nullable=False)
    supplier_url: Mapped[str | None] = mapped_column(String(600))
    product_cost: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    shipping_cost: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    currency: Mapped[str] = mapped_column(String(3), default="AUD")
    minimum_order_quantity: Mapped[int] = mapped_column(Integer, default=1)
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    availability: Mapped[str] = mapped_column(String(20), default="in_stock")
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("supplier_id", "external_product_id", name="uq_supplier_product_ext"),
        Index("ix_supplier_products_product", "product_id"),
    )


class ProductMetric(Base):
    __tablename__ = "product_metrics"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    search_index_avg_7d: Mapped[float | None] = mapped_column(Numeric(10, 4))
    search_index_avg_30d: Mapped[float | None] = mapped_column(Numeric(10, 4))
    search_index_avg_90d: Mapped[float | None] = mapped_column(Numeric(10, 4))
    search_growth_7d_pct: Mapped[float | None] = mapped_column(Numeric(10, 2))
    search_growth_30d_pct: Mapped[float | None] = mapped_column(Numeric(10, 2))
    search_growth_90d_pct: Mapped[float | None] = mapped_column(Numeric(10, 2))
    growth_reason_7d: Mapped[str] = mapped_column(String(40), default="no_source")
    growth_reason_30d: Mapped[str] = mapped_column(String(40), default="no_source")
    growth_reason_90d: Mapped[str] = mapped_column(String(40), default="no_source")
    market_listing_count: Mapped[int | None] = mapped_column(Integer)
    market_avg_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    market_price_p25: Mapped[float | None] = mapped_column(Numeric(12, 2))
    market_price_p75: Mapped[float | None] = mapped_column(Numeric(12, 2))
    review_velocity_30d: Mapped[float | None] = mapped_column(Numeric(10, 2))
    competition_index: Mapped[float | None] = mapped_column(Numeric(5, 2))
    competition_class: Mapped[str] = mapped_column(String(20), default="unknown")
    competition_coverage: Mapped[float] = mapped_column(Float, default=0.0)
    seasonality_index: Mapped[float | None] = mapped_column(Numeric(6, 3))
    trend_direction: Mapped[str] = mapped_column(String(20), default="unknown")
    data_coverage_pct: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    synthetic_share: Mapped[float] = mapped_column(Float, default=0.0)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("product_id", "as_of_date", name="uq_metrics_product_date"),
        Index("ix_metrics_date", "as_of_date"),
    )


class ScoringProfile(Base):
    __tablename__ = "scoring_profiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    country: Mapped[str] = mapped_column(String(2), default="AU", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    weights: Mapped[dict] = mapped_column(JSON, nullable=False)
    thresholds: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("country", "version", name="uq_profile_country_version"),)


class OpportunityScore(Base):
    __tablename__ = "opportunity_scores"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    scoring_profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("scoring_profiles.id", ondelete="CASCADE"), nullable=False
    )
    calculated_on: Mapped[date] = mapped_column(Date, nullable=False)
    score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    score_raw: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    classification: Mapped[str] = mapped_column(String(30), nullable=False)
    demand_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    marketplace_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    social_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    competition_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    profitability_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    seasonal_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    estimated_margin_pct: Mapped[float | None] = mapped_column(Numeric(6, 2))
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    coverage_pct: Mapped[float] = mapped_column(Float, default=0.0)
    components: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "product_id", "scoring_profile_id", "calculated_on", name="uq_score_product_profile"
        ),
        Index("ix_scores_date_score", "calculated_on", "score"),
    )


class WatchlistEntry(Base):
    __tablename__ = "watchlist"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), default="discovered", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="uq_watchlist_user_product"),
        Index("ix_watchlist_user_status", "user_id", "status"),
    )


class ProfitScenario(Base):
    """A saved profit-calculation snapshot for a product or a standalone case."""

    __tablename__ = "profit_scenarios"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="SET NULL")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="AUD", nullable=False)
    inputs: Mapped[dict] = mapped_column(JSON, nullable=False)
    outputs: Mapped[dict] = mapped_column(JSON, nullable=False)
    assumptions_version: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (Index("ix_profit_scenarios_user", "user_id", "updated_at"),)


class ResearchReport(Base):
    __tablename__ = "research_reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    report_type: Mapped[str] = mapped_column(String(30), nullable=False)
    country: Mapped[str] = mapped_column(String(2), default="AU")
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    report_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    file_paths: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    sources: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint(
            "report_type", "country", "period_start", name="uq_report_type_country_period"
        ),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(80))
    changes: Mapped[dict] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


__all__ = [
    "AuditLog",
    "AuthRefreshToken",
    "Category",
    "DataSource",
    "IngestionRun",
    "MarketplaceListing",
    "OpportunityScore",
    "Product",
    "ProductAlias",
    "ProductIdentifier",
    "ProductKeyword",
    "ProductMatch",
    "ProductMetric",
    "ProfitScenario",
    "ResearchReport",
    "ScoringProfile",
    "Supplier",
    "SupplierProduct",
    "TrendObservation",
    "User",
    "WatchlistEntry",
]
