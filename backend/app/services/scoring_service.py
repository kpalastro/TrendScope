from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    OpportunityScore,
    Product,
    ProductMetric,
    ScoringProfile,
    SupplierProduct,
)
from app.services.scoring import (
    COMPONENT_LABELS,
    DEFAULT_THRESHOLDS,
    DEFAULT_WEIGHTS,
    build_components,
    calculate_score,
    estimate_contribution_margin,
)


def get_active_profile(db: Session, country: str = "AU") -> ScoringProfile | None:
    return db.execute(
        select(ScoringProfile)
        .where(ScoringProfile.country == country, ScoringProfile.is_active.is_(True))
        .order_by(ScoringProfile.version.desc())
        .limit(1)
    ).scalar_one_or_none()


def _cheapest_offer(db: Session, product_id):
    return db.execute(
        select(SupplierProduct)
        .where(SupplierProduct.product_id == product_id)
        .order_by(SupplierProduct.product_cost + SupplierProduct.shipping_cost)
        .limit(1)
    ).scalar_one_or_none()


def compute_product_score(
    db: Session,
    product: Product,
    metric: ProductMetric,
    profile: ScoringProfile,
    as_of: date,
) -> OpportunityScore:
    offer = _cheapest_offer(db, product.id)
    margin_pct = None
    if offer is not None and metric.market_avg_price is not None:
        margin_pct = estimate_contribution_margin(
            float(metric.market_avg_price),
            float(offer.product_cost),
            float(offer.shipping_cost or 0),
        )

    comp_index = (
        float(metric.competition_index) if metric.competition_index is not None else None
    )
    seasonal = (
        float(metric.seasonality_index) if metric.seasonality_index is not None else None
    )
    listing_count = metric.market_listing_count
    review_velocity = (
        float(metric.review_velocity_30d)
        if metric.review_velocity_30d is not None
        else None
    )
    growth_7d = (
        float(metric.search_growth_7d_pct)
        if metric.search_growth_7d_pct is not None
        else None
    )
    growth_30d = (
        float(metric.search_growth_30d_pct)
        if metric.search_growth_30d_pct is not None
        else None
    )

    components = build_components(
        growth_7d=growth_7d,
        growth_30d=growth_30d,
        listing_count=listing_count,
        review_velocity=review_velocity,
        competition_index=comp_index,
        margin_pct=margin_pct,
        seasonality_index=seasonal,
    )

    weights = profile.weights or DEFAULT_WEIGHTS
    thresholds = profile.thresholds or DEFAULT_THRESHOLDS
    result = calculate_score(components, weights=weights, quality=metric.confidence, thresholds=thresholds)

    detail: dict = {
        "weights": weights,
        "thresholds": thresholds,
        "margin_pct": margin_pct,
        "raw": {
            "growth_7d_pct": growth_7d,
            "growth_30d_pct": growth_30d,
            "listing_count": listing_count,
            "review_velocity": review_velocity,
            "competition_index": comp_index,
            "seasonality_index": seasonal,
        },
        "components": {},
    }
    reasons = {
        "social": "No social source configured for this market.",
        "seasonal": "Fewer than 12 months of history.",
        "profitability": "No supplier offer matched to this product.",
        "demand": "No usable search history.",
        "marketplace": "No marketplace observations.",
        "competition": "Fewer than two competition signals.",
    }
    for key, value in components.items():
        detail["components"][key] = {
            "label": COMPONENT_LABELS[key],
            "score": value,
            "weight": weights.get(key, 0.0),
            "status": (
                "estimated"
                if key == "profitability" and value is not None
                else "available"
                if value is not None
                else "unavailable"
            ),
            "reason": None if value is not None else reasons.get(key),
        }

    row = db.execute(
        select(OpportunityScore).where(
            OpportunityScore.product_id == product.id,
            OpportunityScore.scoring_profile_id == profile.id,
            OpportunityScore.calculated_on == as_of,
        )
    ).scalar_one_or_none()
    if row is None:
        row = OpportunityScore(
            product_id=product.id,
            scoring_profile_id=profile.id,
            calculated_on=as_of,
        )
        db.add(row)

    row.score = result["score"]
    row.score_raw = result["score_raw"]
    row.classification = result["classification"]
    row.demand_score = components["demand"]
    row.marketplace_score = components["marketplace"]
    row.social_score = components["social"]
    row.competition_score = components["competition"]
    row.profitability_score = components["profitability"]
    row.seasonal_score = components["seasonal"]
    row.estimated_margin_pct = round(margin_pct, 2) if margin_pct is not None else None
    row.confidence_score = result["confidence"]
    row.coverage_pct = result["coverage_pct"]
    row.components = detail
    row.calculated_at = datetime.now(timezone.utc)
    return row


def compute_all_scores(db: Session, as_of: date | None = None) -> int:
    as_of = as_of or date.today()
    profile = get_active_profile(db)
    if profile is None:
        return 0

    rows = db.execute(
        select(Product, ProductMetric)
        .join(ProductMetric, ProductMetric.product_id == Product.id)
        .where(ProductMetric.as_of_date == as_of, Product.status == "active")
    ).all()

    for product, metric in rows:
        compute_product_score(db, product, metric, profile, as_of)
    db.commit()
    return len(rows)
