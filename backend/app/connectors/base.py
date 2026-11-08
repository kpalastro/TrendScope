from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

METRIC_TYPE_BY_NAME = {
    "search_interest": "search_interest",
    "search_interest_rank": "search_interest",
    "marketplace_listing_count": "marketplace_listing",
    "marketplace_avg_price": "marketplace_price",
    "marketplace_review_velocity": "marketplace_review",
    "meta_active_ads": "advertising",
    "supplier_product_cost": "supplier_cost",
}


def infer_metric_type(metric_name: str) -> str:
    """Map a metric name to a semantic type.

    The type is deliberately separate from the metric name so sales, estimated
    sales, search interest and social engagement are never blended just because
    a provider called two columns ``value``.
    """
    return METRIC_TYPE_BY_NAME.get(metric_name, "other")


@dataclass(frozen=True)
class ProductCandidate:
    external_id: str
    name: str
    category_slug: str
    brand: str | None
    price: float | None
    description: str | None
    keywords: list[str] = field(default_factory=list)
    is_synthetic: bool = True
    first_seen_at: datetime | None = None
    source_url: str | None = None


@dataclass(frozen=True)
class ObservationPoint:
    external_id: str
    observation_date: date
    metric_name: str
    metric_value: float
    unit: str
    granularity: str = "daily"
    confidence: float = 1.0
    meta: dict = field(default_factory=dict)
    metric_type: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    source_url: str | None = None
    verification_status: str = "unverified"
    data_quality: str = "unknown"
    original_metric: str | None = None
    source_timestamp: datetime | None = None

    def resolved_metric_type(self) -> str:
        return self.metric_type or infer_metric_type(self.metric_name)



@dataclass(frozen=True)
class ListingRecord:
    external_id: str
    marketplace: str
    listing_id: str
    title: str
    seller_name: str
    price: float
    rating: float
    review_count: int
    listing_url: str = ""


@dataclass(frozen=True)
class SupplierRecord:
    supplier_name: str
    platform_key: str
    country: str
    rating: float
    url: str = ""


@dataclass(frozen=True)
class SupplierOfferRecord:
    external_id: str
    supplier_name: str
    external_product_id: str
    product_cost: float
    shipping_cost: float
    minimum_order_quantity: int
    lead_time_days: int
    availability: str


@dataclass
class ConnectorDataset:
    products: list[ProductCandidate] = field(default_factory=list)
    observations: list[ObservationPoint] = field(default_factory=list)
    listings: list[ListingRecord] = field(default_factory=list)
    suppliers: list[SupplierRecord] = field(default_factory=list)
    offers: list[SupplierOfferRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    request_count: int = 0
    source_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TrackedProduct:
    """Read-only product context handed to a connector.

    Connectors never query the database themselves. The ingestion service
    supplies exactly the products and keywords the provider may look up.
    """

    id: Any
    external_id: str
    name: str
    keywords: tuple[str, ...] = ()
    category_slug: str | None = None
    price: float | None = None

    def search_terms(self) -> list[str]:
        terms = [self.name, *self.keywords]
        seen: set[str] = set()
        result: list[str] = []
        for term in terms:
            normalised = " ".join((term or "").split()).lower()
            if normalised and normalised not in seen:
                seen.add(normalised)
                result.append(term.strip())
        return result


@dataclass(frozen=True)
class ConnectorContext:
    source: Any
    config: dict
    since: date
    until: date
    products: tuple[TrackedProduct, ...] = ()
    timeout_seconds: float = 20.0

