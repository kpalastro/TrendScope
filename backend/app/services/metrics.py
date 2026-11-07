from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    MarketplaceListing,
    Product,
    ProductMetric,
    TrendObservation,
)
from app.services.competition import classify, competition_index
from app.services.growth import (
    GrowthResult,
    compute_growth,
    is_stale,
    seasonality_index,
    trend_direction,
)

SEARCH_METRIC = "search_interest"


def _series(db: Session, product_id) -> dict[date, float]:
    rows = db.execute(
        select(TrendObservation.observation_date, TrendObservation.metric_value)
        .where(
            TrendObservation.product_id == product_id,
            TrendObservation.metric_name == SEARCH_METRIC,
        )
        .order_by(TrendObservation.observation_date)
    ).all()
    return {row[0]: float(row[1]) for row in rows}


def _latest_metric(db: Session, product_id, metric: str):
    row = db.execute(
        select(TrendObservation.observation_date, TrendObservation.metric_value)
        .where(
            TrendObservation.product_id == product_id,
            TrendObservation.metric_name == metric,
        )
        .order_by(TrendObservation.observation_date.desc())
        .limit(1)
    ).first()
    return (row[0], float(row[1])) if row else (None, None)


def _source_diversity(db: Session, product_id) -> int:
    rows = db.execute(
        select(TrendObservation.source_id)
        .where(TrendObservation.product_id == product_id)
        .distinct()
    ).all()
    return max(1, len(rows))


def compute_product_metrics(db: Session, product: Product, as_of: date | None = None) -> ProductMetric:
    as_of = as_of or date.today()
    values = _series(db, product.id)

    stale = is_stale(max(values) if values else None, as_of)
    g7 = compute_growth(values, as_of, 7)
    g30 = compute_growth(values, as_of, 30)
    g90 = compute_growth(values, as_of, 90)

    if values and stale:
        g7 = GrowthResult(None, "stale_data")
        g30 = GrowthResult(None, "stale_data")
        g90 = GrowthResult(None, "stale_data")

    listing_date, listing_count = _latest_metric(
        db, product.id, "marketplace_listing_count"
    )
    _, avg_price = _latest_metric(db, product.id, "marketplace_avg_price")
    _, review_velocity = _latest_metric(
        db, product.id, "marketplace_review_velocity"
    )

    listings = db.execute(
        select(MarketplaceListing).where(
            MarketplaceListing.product_id == product.id,
            MarketplaceListing.is_active.is_(True),
        )
    ).scalars().all()
    prices = [float(li.price) for li in listings if li.price]
    reviews = [int(li.review_count) for li in listings if li.review_count]
    if avg_price and not prices:
        prices = [float(avg_price)]

    comp_index, comp_coverage, _detail = competition_index(
        listing_count, prices, reviews
    )
    comp_class = classify(comp_index, comp_coverage)

    seasonal = seasonality_index(values, as_of)
    synthetic_rows = db.execute(
        select(TrendObservation.is_synthetic).where(TrendObservation.product_id == product.id)
    ).scalars().all()
    synthetic_share = (
        sum(1 for s in synthetic_rows if s) / len(synthetic_rows) if synthetic_rows else 0.0
    )

    search_available = g30.pct is not None or g7.pct is not None
    weight_available = 0.0
    weight_available += 0.25 if search_available else 0
    weight_available += 0.25 if listing_count is not None else 0
    weight_available += 0.15 if comp_index is not None else 0
    weight_available += 0.05 if seasonal is not None else 0
    data_coverage = round(weight_available / 0.70 * 100, 2)

    freshness = 1.0 if not stale else 0.5
    sample = min(1.0, len(values) / 30.0)
    diversity = 1.0 if _source_diversity(db, product.id) > 1 else 0.85
    quality = round(max(0.05, min(1.0, freshness * sample * diversity)), 3)

    metric = db.execute(
        select(ProductMetric).where(
            ProductMetric.product_id == product.id,
            ProductMetric.as_of_date == as_of,
        )
    ).scalar_one_or_none()
    if metric is None:
        metric = ProductMetric(product_id=product.id, as_of_date=as_of)
        db.add(metric)

    metric.search_index_avg_7d = g7.current_mean
    metric.search_index_avg_30d = g30.current_mean
    metric.search_index_avg_90d = g90.current_mean
    metric.search_growth_7d_pct = g7.pct
    metric.search_growth_30d_pct = g30.pct
    metric.search_growth_90d_pct = g90.pct
    metric.growth_reason_7d = g7.reason
    metric.growth_reason_30d = g30.reason
    metric.growth_reason_90d = g90.reason
    metric.market_listing_count = int(listing_count) if listing_count is not None else None
    metric.market_avg_price = avg_price
    if prices:
        ordered = sorted(prices)
        metric.market_price_p25 = round(ordered[len(ordered) // 4], 2)
        metric.market_price_p75 = round(ordered[(len(ordered) * 3) // 4], 2)
    metric.review_velocity_30d = review_velocity
    metric.competition_index = comp_index
    metric.competition_class = comp_class
    metric.competition_coverage = comp_coverage
    metric.seasonality_index = seasonal
    metric.trend_direction = trend_direction(g7.pct, g30.pct)
    metric.data_coverage_pct = data_coverage
    metric.confidence = quality
    metric.synthetic_share = round(synthetic_share, 3)
    metric.computed_at = datetime.now(timezone.utc)
    return metric


def compute_all_metrics(db: Session, as_of: date | None = None) -> int:
    as_of = as_of or date.today()
    products = db.execute(select(Product).where(Product.status == "active")).scalars().all()
    for product in products:
        compute_product_metrics(db, product, as_of)
    db.commit()
    return len(products)
