"""Dashboard summary and widgets.

Widgets are queries over ``product_metrics`` and ``opportunity_scores``; they do
not introduce new data, and every widget carries a note saying what it ranks.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    DataSource,
    OpportunityScore,
    Product,
    ProductMetric,
)
from app.services.catalog import top_rows
from app.services.presenters import public_score

WIDGETS = {
    "weekly_trending": ("Fastest growing this week", "-growth_7d"),
    "monthly_trending": ("Fastest growing this month", "-growth_30d"),
    "fastest_growing": ("Fastest growing (30 days)", "-growth_30d"),
    "emerging": ("Emerging products", "-growth_7d"),
    "low_competition": ("High score, low competition", "-opportunity_score"),
    "seasonal": ("Seasonal opportunities", "-seasonality"),
    "best_margins": ("Best estimated margins", "-estimated_margin"),
    "recently_discovered": ("Recently discovered", "-first_seen_at"),
}

WIDGET_NOTES = {
    "weekly_trending": "Ranked by 7-day search growth. Products without a valid baseline are excluded.",
    "monthly_trending": "Ranked by 30-day search growth.",
    "fastest_growing": "Ranked by 30-day search growth.",
    "emerging": "Discovered in the last 30 days and rising over 7 days; a new product without growth is not emerging.",
    "low_competition": "Low or moderate competition first, then opportunity score.",
    "seasonal": "Ranked by seasonality index; requires at least 12 months of history.",
    "best_margins": "Estimated contribution margin from the cheapest supplier offer. Estimate only, not verified.",
    "recently_discovered": "Newest products in the catalogue.",
}


def summary(db: Session, country: str = "AU") -> dict:
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    products_monitored = int(
        db.execute(
            select(func.count(Product.id)).where(
                Product.status == "active", Product.country == country
            )
        ).scalar()
        or 0
    )
    new_this_week = int(
        db.execute(
            select(func.count(Product.id)).where(
                Product.status == "active",
                Product.country == country,
                Product.first_seen_at >= week_ago,
            )
        ).scalar()
        or 0
    )

    latest_metric = (
        select(func.max(ProductMetric.as_of_date))
        .where(ProductMetric.product_id == Product.id)
        .correlate(Product)
        .scalar_subquery()
    )
    increasing = int(
        db.execute(
            select(func.count(Product.id))
            .select_from(Product)
            .join(
                ProductMetric,
                (ProductMetric.product_id == Product.id)
                & (ProductMetric.as_of_date == latest_metric),
            )
            .where(
                Product.status == "active",
                Product.country == country,
                ProductMetric.trend_direction == "rising",
            )
        ).scalar()
        or 0
    )
    declining = int(
        db.execute(
            select(func.count(Product.id))
            .select_from(Product)
            .join(
                ProductMetric,
                (ProductMetric.product_id == Product.id)
                & (ProductMetric.as_of_date == latest_metric),
            )
            .where(
                Product.status == "active",
                Product.country == country,
                ProductMetric.trend_direction == "declining",
            )
        ).scalar()
        or 0
    )

    latest_score = (
        select(OpportunityScore.id)
        .where(OpportunityScore.product_id == Product.id)
        .order_by(
            OpportunityScore.calculated_on.desc(),
            OpportunityScore.calculated_at.desc(),
        )
        .limit(1)
        .correlate(Product)
        .scalar_subquery()
    )
    score_rows = db.execute(
        select(OpportunityScore.score, OpportunityScore.classification)
        .select_from(Product)
        .join(
            OpportunityScore,
            (OpportunityScore.product_id == Product.id)
            & (OpportunityScore.id == latest_score),
        )
        .where(
            Product.status == "active",
            Product.country == country,
            OpportunityScore.coverage_pct > 0,
        )
    ).all()
    high_opportunity = sum(
        1 for row in score_rows if row.classification in ("excellent", "strong")
    )
    average_score = (
        round(sum(float(row.score) for row in score_rows) / len(score_rows), 1)
        if score_rows
        else None
    )

    sources = db.execute(
        select(DataSource).order_by(DataSource.provider_key)
    ).scalars().all()
    last_sync = max((s.last_sync_at for s in sources if s.last_sync_at), default=None)

    return {
        "country": country,
        "products_monitored": products_monitored,
        "new_this_week": new_this_week,
        "increasing_demand": increasing,
        "declining_demand": declining,
        "high_opportunity": high_opportunity,
        "average_opportunity_score": average_score,
        "data_sources": [
            {
                "id": source.id,
                "provider_key": source.provider_key,
                "provider_name": source.provider_name,
                "sync_status": source.sync_status,
                "last_sync_at": source.last_sync_at,
                "is_synthetic": source.is_synthetic,
                "enabled": source.enabled,
            }
            for source in sources
        ],
        "last_sync_at": last_sync,
        "generated_at": now,
    }


def _conditions(key: str):
    if key == "weekly_trending":
        return [ProductMetric.search_growth_7d_pct.is_not(None)]
    if key in ("monthly_trending", "fastest_growing"):
        return [ProductMetric.search_growth_30d_pct.is_not(None)]
    if key == "emerging":
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        return [
            Product.first_seen_at >= cutoff,
            ProductMetric.search_growth_7d_pct.is_not(None),
            ProductMetric.search_growth_7d_pct > 0,
        ]
    if key == "low_competition":
        return [ProductMetric.competition_class.in_(("low", "moderate"))]
    if key == "seasonal":
        return [ProductMetric.seasonality_index.is_not(None)]
    if key == "best_margins":
        return [OpportunityScore.estimated_margin_pct.is_not(None)]
    return []


def widget(db: Session, key: str, limit: int = 10, country: str = "AU") -> dict:
    if key not in WIDGETS:
        raise KeyError(key)
    title, sort = WIDGETS[key]
    rows = top_rows(
        db,
        sort,
        limit=limit,
        conditions=[*_conditions(key), Product.country == country],
    )
    items = []
    for row in rows:
        items.append(
            {
                "id": row.product.id,
                "name": row.product.name,
                "slug": row.product.slug,
                "opportunity_score": public_score(row.score),
                "classification": row.score.classification if row.score else None,
                "growth_7d_pct": (
                    float(row.metric.search_growth_7d_pct)
                    if row.metric and row.metric.search_growth_7d_pct is not None
                    else None
                ),
                "growth_30d_pct": (
                    float(row.metric.search_growth_30d_pct)
                    if row.metric and row.metric.search_growth_30d_pct is not None
                    else None
                ),
                "competition_class": row.metric.competition_class if row.metric else "unknown",
                "trend_direction": row.metric.trend_direction if row.metric else "unknown",
                "category": row.category.name if row.category else None,
                "is_synthetic": bool(row.product.is_synthetic),
            }
        )
    return {"key": key, "title": title, "items": items, "note": WIDGET_NOTES.get(key)}


def all_widgets(db: Session, limit: int = 10, country: str = "AU") -> list[dict]:
    return [widget(db, key, limit=limit, country=country) for key in WIDGETS]
