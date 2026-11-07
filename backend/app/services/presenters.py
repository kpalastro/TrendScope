"""Serialisation helpers shared by every read endpoint."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Category,
    DataSource,
    OpportunityScore,
    Product,
    ProductKeyword,
    ProductMetric,
    ScoringProfile,
    TrendObservation,
)

DISCLAIMER = (
    "Growth is derived from relative search interest, not sales. Scores are "
    "estimates that combine available evidence and shrink toward the midpoint "
    "when coverage is low. Synthetic records are demo data, not market facts."
)

REASON_TEXT = {
    "ok": None,
    "no_source": "No trend source returned data for this product.",
    "insufficient_current_data": "The current window has too few observations.",
    "insufficient_baseline": "The baseline window has too few observations.",
    "zero_baseline": "The baseline average is zero, so a percentage change is undefined.",
    "stale_data": "The latest observation is older than three days.",
}

COMPONENT_RAW = {
    "demand": ("growth_7d_pct", "growth_30d_pct"),
    "marketplace": ("listing_count", "review_velocity"),
    "competition": ("competition_index",),
    "profitability": ("margin_pct",),
    "seasonal": ("seasonality_index",),
}


def as_float(value) -> float | None:
    return float(value) if value is not None else None


def public_score(score: OpportunityScore | None) -> float | None:
    """Return the score, or ``None`` when it rests on no evidence at all.

    The stored row keeps the non-nullable 0.0 that the scoring contract requires,
    but a reader must not see "0" as though it were a measured low score: zero
    coverage means nothing was measurable.
    """
    if score is None or float(score.coverage_pct) <= 0:
        return None
    return as_float(score.score)


def public_score_raw(score: OpportunityScore | None) -> float | None:
    if score is None or float(score.coverage_pct) <= 0:
        return None
    return as_float(score.score_raw)


def money(value) -> str | None:
    return f"{float(value):.2f}" if value is not None else None


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def growth_payload(metric: ProductMetric | None, window: int) -> dict:
    if metric is None:
        return {"pct": None, "reason": "no_source", "window_days": window}
    pct = getattr(metric, f"search_growth_{window}d_pct", None)
    reason = getattr(metric, f"growth_reason_{window}d", "no_source")
    return {
        "pct": as_float(pct),
        "reason": reason or "no_source",
        "window_days": window,
    }


def _sources(db: Session, product_id) -> list[str]:
    rows = db.execute(
        select(DataSource.provider_key)
        .join(TrendObservation, TrendObservation.source_id == DataSource.id)
        .where(TrendObservation.product_id == product_id)
        .distinct()
    ).scalars()
    return sorted(set(rows))


def data_quality(
    db: Session, product: Product, metric: ProductMetric | None, score: OpportunityScore | None
) -> dict:
    missing: list[str] = []
    warnings: list[str] = []
    if metric is not None:
        for window in (7, 30, 90):
            reason = getattr(metric, f"growth_reason_{window}d", "no_source")
            text = REASON_TEXT.get(reason)
            if text and reason != "ok":
                warnings.append(f"{window}d growth unavailable: {text}")
    if score is not None:
        detail = score.components or {}
        for key, component in (detail.get("components") or {}).items():
            if component.get("status") == "unavailable":
                missing.append(key)
                if component.get("reason"):
                    warnings.append(f"{key} unavailable: {component['reason']}")
    else:
        missing = ["demand", "marketplace", "social", "competition", "profitability", "seasonal"]

    if score is not None:
        coverage_pct = round(float(score.coverage_pct), 2)
        confidence = round(float(score.confidence_score), 3)
    elif metric is not None:
        coverage_pct = round(float(metric.data_coverage_pct), 2)
        confidence = round(float(metric.confidence), 3)
    else:
        coverage_pct = 0.0
        confidence = 0.0

    return {
        "coverage_pct": coverage_pct,
        "confidence": confidence,
        "synthetic": bool(product.is_synthetic),
        "synthetic_share": round(float(metric.synthetic_share), 3) if metric else 0.0,
        "sources": _sources(db, product.id),
        "missing_components": missing,
        "last_updated": iso(metric.computed_at if metric else product.updated_at),
        "warnings": warnings,
    }


def category_payload(category: Category | None, product_count: int | None = None) -> dict | None:
    if category is None:
        return None
    payload = {
        "id": category.id,
        "name": category.name,
        "slug": category.slug,
        "parent_id": category.parent_id,
        "path": category.path,
        "level": category.level,
    }
    if product_count is not None:
        payload["product_count"] = product_count
    return payload


def score_breakdown(score: OpportunityScore, profile: ScoringProfile | None) -> dict:
    detail = score.components or {}
    raw = detail.get("raw") or {}
    components: dict = {}
    for key, component in (detail.get("components") or {}).items():
        raw_fields = COMPONENT_RAW.get(key, ())
        components[key] = {
            "label": component.get("label"),
            "score": as_float(component.get("score")),
            "weight": component.get("weight", 0.0),
            "status": component.get("status", "unavailable"),
            "reason": component.get("reason"),
            "raw": {field: raw.get(field) for field in raw_fields} or None,
        }
    return {
        "score": public_score(score),
        "score_raw": public_score_raw(score),
        "classification": score.classification,
        "coverage_pct": round(float(score.coverage_pct), 2),
        "confidence": round(float(score.confidence_score), 3),
        "components": components,
        "profile": (
            {"id": profile.id, "name": profile.name, "version": profile.version}
            if profile
            else {}
        ),
        "calculated_on": score.calculated_on,
    }


def product_summary(
    db: Session,
    product: Product,
    category: Category | None,
    metric: ProductMetric | None,
    score: OpportunityScore | None,
    profile: ScoringProfile | None,
    supplier_available: bool = False,
) -> dict:
    margin = as_float(score.estimated_margin_pct) if score else None
    return {
        "id": product.id,
        "name": product.name,
        "slug": product.slug,
        "category": category_payload(category),
        "brand": product.brand,
        "image_url": product.image_url,
        "country": product.country,
        "currency": product.currency,
        "price_range": {
            "min": money(metric.market_price_p25) if metric else None,
            "max": money(metric.market_price_p75) if metric else None,
            "market_avg": money(metric.market_avg_price) if metric else None,
            "currency": product.currency,
        },
        "opportunity_score": public_score(score),
        "classification": score.classification if score else None,
        "growth": {
            "d7": growth_payload(metric, 7),
            "d30": growth_payload(metric, 30),
            "d90": growth_payload(metric, 90),
        },
        "competition_class": metric.competition_class if metric else "unknown",
        "trend_direction": metric.trend_direction if metric else "unknown",
        "estimated_margin_pct": round(margin, 2) if margin is not None else None,
        "supplier_available": supplier_available,
        "data_quality": data_quality(db, product, metric, score),
        "first_seen_at": product.first_seen_at,
        "updated_at": product.updated_at,
    }


def trend_series(db: Session, product_id, limit_days: int = 365) -> list[dict]:
    rows = db.execute(
        select(
            TrendObservation.metric_name,
            TrendObservation.unit,
            TrendObservation.granularity,
            TrendObservation.country,
            TrendObservation.is_synthetic,
            TrendObservation.observation_date,
            TrendObservation.metric_value,
        )
        .where(TrendObservation.product_id == product_id)
        .order_by(TrendObservation.metric_name, TrendObservation.observation_date)
    ).all()

    grouped: dict[str, dict] = {}
    for row in rows:
        entry = grouped.setdefault(
            row.metric_name,
            {
                "metric_name": row.metric_name,
                "unit": row.unit,
                "granularity": row.granularity,
                "country": row.country,
                "is_synthetic": row.is_synthetic,
                "points": [],
            },
        )
        entry["points"].append(
            {"date": row.observation_date, "value": as_float(row.metric_value)}
        )
    series = []
    for entry in grouped.values():
        entry["points"] = entry["points"][-limit_days:]
        series.append(entry)
    return sorted(series, key=lambda item: item["metric_name"])


def product_sources(db: Session, product_id) -> list[dict]:
    rows = db.execute(
        select(
            DataSource.provider_key,
            DataSource.provider_name,
            TrendObservation.observation_date,
            TrendObservation.is_synthetic.label("obs_synthetic"),
        )
        .join(TrendObservation, TrendObservation.source_id == DataSource.id)
        .where(TrendObservation.product_id == product_id)
        .order_by(TrendObservation.observation_date.desc())
    ).all()
    seen: dict[str, dict] = {}
    for row in rows:
        if row.provider_key in seen:
            continue
        seen[row.provider_key] = {
            "provider_key": row.provider_key,
            "provider_name": row.provider_name,
            "collection_date": row.observation_date,
            "is_synthetic": bool(row.obs_synthetic),
        }
    return list(seen.values())


def keywords(db: Session, product_id) -> list[str]:
    return list(
        db.execute(
            select(ProductKeyword.keyword)
            .where(ProductKeyword.product_id == product_id)
            .order_by(ProductKeyword.keyword)
        ).scalars()
    )


def today() -> date:
    return date.today()
