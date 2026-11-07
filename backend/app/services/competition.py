"""Competition estimation from listing evidence. Pure functions."""

from __future__ import annotations

import math
import statistics

COMPETITION_LABELS = {
    "low": "Low competition",
    "moderate": "Moderate competition",
    "high": "High competition",
    "saturated": "Highly saturated",
    "unknown": "Unknown",
}


def listing_component(listing_count: int | None) -> float | None:
    if listing_count is None:
        return None
    count = max(1, int(listing_count))
    # 10 listings -> ~33, 100 -> ~66, 1000 -> ~99
    return max(0.0, min(100.0, 33.0 * math.log10(count + 1) / 1.05))


def price_dispersion_component(prices: list[float]) -> float | None:
    prices = [p for p in prices if p and p > 0]
    if len(prices) < 3:
        return None
    mean = statistics.fmean(prices)
    if mean <= 0:
        return None
    cv = statistics.pstdev(prices) / mean
    # Low dispersion (commoditised) reads as more competitive.
    return max(0.0, min(100.0, 100.0 - cv * 120.0))


def review_concentration_component(review_counts: list[int]) -> float | None:
    counts = [max(0, int(c or 0)) for c in review_counts]
    counts = [c for c in counts if c > 0]
    if len(counts) < 3:
        return None
    total = sum(counts)
    if total <= 0:
        return None
    hhi = sum((c / total) ** 2 for c in counts)
    # HHI is already 0..1, so it maps directly onto the 0..100 component scale.
    return max(0.0, min(100.0, hhi * 100.0))


def competition_index(
    listing_count: int | None,
    prices: list[float] | None = None,
    review_counts: list[int] | None = None,
) -> tuple[float | None, float, dict]:
    """Return (index, coverage 0..1, evidence detail).

    Fewer than two independent signals yields ``None``: a thin listing count is
    not evidence of an open market.
    """
    parts: list[tuple[float, float, str]] = []
    lc = listing_component(listing_count)
    if lc is not None:
        parts.append((lc, 0.70, "listing_count"))
    pc = price_dispersion_component(prices or [])
    if pc is not None:
        parts.append((pc, 0.15, "price_dispersion"))
    rc = review_concentration_component(review_counts or [])
    if rc is not None:
        parts.append((rc, 0.15, "review_concentration"))

    detail = {
        "listing_count": listing_count,
        "listing_component": round(lc, 2) if lc is not None else None,
        "price_dispersion_component": round(pc, 2) if pc is not None else None,
        "review_concentration_component": round(rc, 2) if rc is not None else None,
        "evidence": [p[2] for p in parts],
    }

    if len(parts) < 2:
        return None, round(sum(p[1] for p in parts), 2), detail

    weight_available = sum(p[1] for p in parts)
    index = sum(p[0] * p[1] for p in parts) / weight_available
    coverage = weight_available
    return round(index, 2), round(coverage, 2), detail


def classify(index: float | None, coverage: float) -> str:
    if index is None or coverage < 0.6:
        return "unknown"
    if index < 25:
        return "low"
    if index < 50:
        return "moderate"
    if index < 75:
        return "high"
    return "saturated"
