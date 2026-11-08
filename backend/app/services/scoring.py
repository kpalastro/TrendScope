"""Opportunity scoring. Pure arithmetic with an explicit missing-data path."""

from __future__ import annotations

import math

DEFAULT_WEIGHTS: dict[str, float] = {
    "demand": 0.25,
    "marketplace": 0.25,
    "social": 0.15,
    "competition": 0.15,
    "profitability": 0.15,
    "seasonal": 0.05,
}

DEFAULT_THRESHOLDS: dict[str, float] = {
    "excellent": 80,
    "strong": 65,
    "worth_investigating": 50,
    "weak": 35,
}

COMPONENT_LABELS = {
    "demand": "Search demand and growth",
    "marketplace": "Marketplace popularity",
    "social": "Social momentum",
    "competition": "Competition opportunity",
    "profitability": "Profit potential",
    "seasonal": "Seasonal relevance",
}

# Assumptions used only for the profitability *score*, not for the calculator.
PAYMENT_FEE_PCT = 0.0175
PAYMENT_FEE_FIXED = 0.30
FULFILMENT = 8.50
PACKAGING = 1.20
RETURN_ALLOWANCE_PCT = 2.0
GST_RATE = 0.10

MIN_COVERAGE_FOR_RANKING = 0.60


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def piecewise(value: float, points: list[tuple[float, float]]) -> float:
    """Linear interpolation between (x, score) points, clamped at the ends."""
    if value <= points[0][0]:
        return points[0][1]
    if value >= points[-1][0]:
        return points[-1][1]
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        if x1 <= value <= x2:
            ratio = (value - x1) / (x2 - x1) if x2 != x1 else 0
            return y1 + ratio * (y2 - y1)
    return points[-1][1]


def demand_score(growth_7d: float | None, growth_30d: float | None) -> float | None:
    parts: list[tuple[float, float]] = []
    if growth_30d is not None:
        parts.append((clamp(50 + growth_30d * 1.2), 0.65))
    if growth_7d is not None:
        parts.append((clamp(50 + growth_7d * 2.0), 0.35))
    if not parts:
        return None
    weight = sum(w for _, w in parts)
    return round(sum(s * w for s, w in parts) / weight, 2)


def marketplace_score(listing_count: int | None, review_velocity: float | None) -> float | None:
    if listing_count is None and review_velocity is None:
        return None
    score = 0.0
    weight = 0.0
    if listing_count is not None:
        score += clamp(20 + 10 * math.log10(max(1, listing_count))) * 0.8
        weight += 0.8
    if review_velocity is not None:
        score += clamp(30 + review_velocity * 6) * 0.2
        weight += 0.2
    return round(score / weight, 2) if weight else None


def seasonal_score(index: float | None) -> float | None:
    if index is None:
        return None
    return round(clamp(50 + (index - 1.0) * 100), 2)


def estimate_contribution_margin(
    price_inc_gst: float | None, product_cost: float | None, shipping_cost: float | None
) -> float | None:
    """Return contribution margin percent after fees, fulfilment and returns."""
    profit = estimate_contribution_profit(price_inc_gst, product_cost, shipping_cost)
    if profit is None or not price_inc_gst or price_inc_gst <= 0:
        return None
    price_ex = price_inc_gst / (1 + GST_RATE)
    return round(profit / price_ex * 100.0, 2)


def estimate_contribution_profit(
    price_inc_gst: float | None, product_cost: float | None, shipping_cost: float | None
) -> float | None:
    """Return estimated contribution profit per unit, in the price currency."""
    if not price_inc_gst or price_inc_gst <= 0 or product_cost is None:
        return None
    price_ex = price_inc_gst / (1 + GST_RATE)
    landed = float(product_cost) + float(shipping_cost or 0)
    fees = price_inc_gst * PAYMENT_FEE_PCT + PAYMENT_FEE_FIXED
    returns = price_inc_gst * (RETURN_ALLOWANCE_PCT / 100.0)
    return round(price_ex - landed - fees - FULFILMENT - PACKAGING - returns, 2)


def profitability_score(margin_pct: float | None) -> float | None:
    if margin_pct is None:
        return None
    return round(
        piecewise(margin_pct, [(0, 0), (10, 30), (25, 60), (40, 85), (55, 100)]), 2
    )


def classify(score: float, coverage: float, thresholds: dict[str, float] | None = None) -> str:
    thresholds = thresholds or DEFAULT_THRESHOLDS
    if coverage < MIN_COVERAGE_FOR_RANKING:
        return "insufficient_data"
    if score >= thresholds.get("excellent", 80):
        return "excellent"
    if score >= thresholds.get("strong", 65):
        return "strong"
    if score >= thresholds.get("worth_investigating", 50):
        return "worth_investigating"
    if score >= thresholds.get("weak", 35):
        return "weak"
    return "low_priority"


def calculate_score(
    component_scores: dict[str, float | None],
    weights: dict[str, float] | None = None,
    quality: float = 1.0,
    thresholds: dict[str, float] | None = None,
) -> dict:
    """Combine components, renormalise available weights, shrink by confidence.

    ``quality`` is the data-quality factor (0..1) before coverage is applied.
    Both the raw and adjusted score are returned so the adjustment is auditable.
    """
    weights = weights or DEFAULT_WEIGHTS
    available = {k: v for k, v in component_scores.items() if v is not None}
    weight_available = sum(weights.get(k, 0.0) for k in available)
    coverage = clamp(weight_available, 0.0, 1.0)

    if not available or weight_available <= 0:
        return {
            "score": 0.0,
            "score_raw": 0.0,
            "classification": "insufficient_data",
            "coverage_pct": 0.0,
            "confidence": 0.0,
            "component_scores": component_scores,
        }

    score_raw = sum(available[k] * weights.get(k, 0.0) for k in available) / weight_available
    confidence = clamp(coverage * clamp(quality, 0.0, 1.0), 0.0, 1.0)
    score = 50 + (score_raw - 50) * confidence
    score = clamp(score)

    return {
        "score": round(score, 2),
        "score_raw": round(score_raw, 2),
        "classification": classify(score, coverage, thresholds),
        "coverage_pct": round(coverage * 100, 2),
        "confidence": round(confidence, 3),
        "component_scores": component_scores,
    }


def build_components(
    *,
    growth_7d: float | None,
    growth_30d: float | None,
    listing_count: int | None,
    review_velocity: float | None,
    competition_index: float | None,
    margin_pct: float | None,
    seasonality_index: float | None,
    social_engagement: float | None = None,
) -> dict[str, float | None]:
    return {
        "demand": demand_score(growth_7d, growth_30d),
        "marketplace": marketplace_score(listing_count, review_velocity),
        "social": clamp(social_engagement) if social_engagement is not None else None,
        "competition": round(100 - competition_index, 2)
        if competition_index is not None
        else None,
        "profitability": profitability_score(margin_pct),
        "seasonal": seasonal_score(seasonality_index),
    }
