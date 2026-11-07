"""Pure trend calculations. No database access, so every guard is cheap to test."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

MIN_BASELINE_INDEX = 5.0
MIN_COVERAGE = 0.7
STALE_AFTER_DAYS = 3
EXTREME_GROWTH_PCT = 900.0


@dataclass(frozen=True)
class GrowthResult:
    pct: float | None
    reason: str
    current_mean: float | None = None
    baseline_mean: float | None = None
    current_days: int = 0
    baseline_days: int = 0


def _window_values(values: dict[date, float], start: date, end: date) -> list[float]:
    return [float(v) for d, v in values.items() if start <= d <= end]


def compute_growth(
    values: dict[date, float],
    as_of: date,
    window: int,
    min_baseline: float = MIN_BASELINE_INDEX,
    min_coverage: float = MIN_COVERAGE,
) -> GrowthResult:
    """Compare two complete windows ending yesterday.

    Returns ``pct=None`` with a reason instead of zero whenever the comparison
    would be misleading: thin data, a vanishing baseline, or no data at all.
    """
    if not values:
        return GrowthResult(None, "no_source")

    required_days = max(1, math.ceil(window * min_coverage))
    current_start = as_of - timedelta(days=window)
    current_end = as_of - timedelta(days=1)
    baseline_start = as_of - timedelta(days=2 * window)
    baseline_end = as_of - timedelta(days=window + 1)

    current = _window_values(values, current_start, current_end)
    baseline = _window_values(values, baseline_start, baseline_end)

    if len(current) < required_days:
        return GrowthResult(
            None,
            "insufficient_current_data",
            current_days=len(current),
            baseline_days=len(baseline),
        )
    if len(baseline) < required_days:
        return GrowthResult(
            None,
            "insufficient_baseline",
            current_mean=sum(current) / len(current),
            current_days=len(current),
            baseline_days=len(baseline),
        )

    current_mean = sum(current) / len(current)
    baseline_mean = sum(baseline) / len(baseline)

    if baseline_mean == 0:
        return GrowthResult(
            None,
            "zero_baseline",
            current_mean=current_mean,
            baseline_mean=baseline_mean,
            current_days=len(current),
            baseline_days=len(baseline),
        )
    if baseline_mean < min_baseline:
        return GrowthResult(
            None,
            "insufficient_baseline",
            current_mean=current_mean,
            baseline_mean=baseline_mean,
            current_days=len(current),
            baseline_days=len(baseline),
        )

    pct = (current_mean / baseline_mean - 1.0) * 100.0
    if not math.isfinite(pct):
        pct = None
    return GrowthResult(
        round(pct, 2) if pct is not None else None,
        "ok" if pct is not None else "insufficient_baseline",
        current_mean=round(current_mean, 4),
        baseline_mean=round(baseline_mean, 4),
        current_days=len(current),
        baseline_days=len(baseline),
    )


def trend_direction(growth_7d: float | None, growth_30d: float | None) -> str:
    value = growth_7d if growth_7d is not None else growth_30d
    if value is None:
        return "unknown"
    if value > 5:
        return "rising"
    if value < -5:
        return "declining"
    return "stable"


def is_stale(latest: date | None, as_of: date, after_days: int = STALE_AFTER_DAYS) -> bool:
    if latest is None:
        return True
    return (as_of - latest).days > after_days


def monthly_means(values: dict[date, float]) -> dict[int, float]:
    buckets: dict[int, list[float]] = {}
    for day, value in values.items():
        buckets.setdefault(day.month, []).append(float(value))
    return {m: sum(v) / len(v) for m, v in buckets.items() if v}


def seasonality_index(values: dict[date, float], as_of: date, horizon_days: int = 90) -> float | None:
    """Ratio of the next 90 days' mean interest to the annual mean.

    Requires at least 365 days of spread and twelve populated months; below
    that the seasonal component is unavailable rather than guessed.
    """
    if not values:
        return None
    days = sorted(values)
    if (days[-1] - days[0]).days < 365 or len({d.month for d in days}) < 12:
        return None

    overall = sum(values.values()) / len(values)
    if overall <= 0:
        return None

    window_days = []
    for offset in range(horizon_days):
        window_days.append(as_of + timedelta(days=offset))
    window_months = {d.month for d in window_days}
    means = monthly_means(values)
    selected = [means[m] for m in window_months if m in means]
    if not selected:
        return None
    return round((sum(selected) / len(selected)) / overall, 3)
