from datetime import date, timedelta

import pytest

from app.services.growth import (
    compute_growth,
    is_stale,
    seasonality_index,
    trend_direction,
)

AS_OF = date(2026, 11, 8)


def _series(window: int, baseline: float, current: float) -> dict[date, float]:
    values = {}
    for offset in range(1, window + 1):
        values[AS_OF - timedelta(days=offset)] = current
        values[AS_OF - timedelta(days=window + offset)] = baseline
    return values


def test_growth_ok():
    result = compute_growth(_series(30, 10.0, 20.0), AS_OF, 30)
    assert result.reason == "ok"
    assert result.pct == pytest.approx(100.0)
    assert result.current_days == 30
    assert result.baseline_days == 30


def test_growth_no_source():
    result = compute_growth({}, AS_OF, 7)
    assert result.pct is None
    assert result.reason == "no_source"


def test_growth_insufficient_current_data():
    values = {AS_OF - timedelta(days=offset): 10.0 for offset in range(1, 20)}
    result = compute_growth(values, AS_OF, 30)
    assert result.pct is None
    assert result.reason == "insufficient_current_data"
    assert result.current_days == 19


def test_growth_insufficient_baseline():
    values = {AS_OF - timedelta(days=offset): 10.0 for offset in range(1, 30)}
    result = compute_growth(values, AS_OF, 30)
    assert result.pct is None
    assert result.reason == "insufficient_baseline"
    assert result.current_days == 29


def test_growth_zero_baseline_is_not_infinite():
    result = compute_growth(_series(7, 0.0, 5.0), AS_OF, 7)
    assert result.pct is None
    assert result.reason == "zero_baseline"


def test_growth_thin_baseline_rejected():
    result = compute_growth(_series(7, 1.0, 5.0), AS_OF, 7)
    assert result.pct is None
    assert result.reason == "insufficient_baseline"


def test_trend_direction_thresholds():
    assert trend_direction(6.0, None) == "rising"
    assert trend_direction(-6.0, None) == "declining"
    assert trend_direction(4.0, 100.0) == "stable"
    assert trend_direction(None, None) == "unknown"


def test_staleness():
    assert is_stale(None, AS_OF) is True
    assert is_stale(AS_OF, AS_OF) is False
    assert is_stale(AS_OF - timedelta(days=3), AS_OF) is False
    assert is_stale(AS_OF - timedelta(days=4), AS_OF) is True


def test_seasonality_requires_a_year():
    short = {AS_OF - timedelta(days=offset): 10.0 for offset in range(100)}
    assert seasonality_index(short, AS_OF) is None


def test_seasonality_detects_peak_window():
    values = {}
    for offset in range(0, 400):
        day = AS_OF - timedelta(days=offset)
        values[day] = 100.0 if day.month == 12 else 40.0
    index = seasonality_index(values, date(2026, 12, 1), horizon_days=45)
    assert index is not None
    assert index > 1.2
