import pytest

from app.services.scoring import (
    DEFAULT_WEIGHTS,
    build_components,
    calculate_score,
    classify,
    demand_score,
    estimate_contribution_margin,
    profitability_score,
)


def test_missing_components_are_renormalised_not_zeroed():
    components = {
        "demand": 80.0,
        "marketplace": 60.0,
        "social": None,
        "competition": None,
        "profitability": None,
        "seasonal": None,
    }
    result = calculate_score(components, weights=DEFAULT_WEIGHTS, quality=1.0)
    assert result["score_raw"] == pytest.approx(70.0)
    assert result["coverage_pct"] == pytest.approx(50.0)
    # confidence = coverage (0.5) * quality (1.0); score shrinks toward 50
    assert result["score"] == pytest.approx(60.0)
    assert result["classification"] == "insufficient_data"


def test_confidence_shrinks_toward_midpoint():
    components = {key: 90.0 for key in DEFAULT_WEIGHTS}
    full = calculate_score(components, quality=1.0)
    half = calculate_score(components, quality=0.5)
    assert full["score"] == pytest.approx(90.0)
    assert half["score"] == pytest.approx(70.0)
    assert full["score_raw"] == half["score_raw"] == pytest.approx(90.0)


def test_no_evidence_is_insufficient_data():
    result = calculate_score({key: None for key in DEFAULT_WEIGHTS}, quality=1.0)
    assert result["score"] == 0.0
    assert result["score_raw"] == 0.0
    assert result["classification"] == "insufficient_data"
    assert result["coverage_pct"] == 0.0


def test_classification_thresholds():
    assert classify(85, 0.9) == "excellent"
    assert classify(70, 0.9) == "strong"
    assert classify(55, 0.9) == "worth_investigating"
    assert classify(40, 0.9) == "weak"
    assert classify(20, 0.9) == "low_priority"
    assert classify(95, 0.5) == "insufficient_data"


def test_demand_score_handles_missing_windows():
    assert demand_score(None, None) is None
    assert demand_score(10.0, None) == pytest.approx(70.0)
    assert demand_score(None, 10.0) == pytest.approx(62.0)


def test_contribution_margin_is_gst_aware():
    margin = estimate_contribution_margin(110.0, 30.0, 5.0)
    assert margin == pytest.approx(50.875, abs=0.01)
    assert estimate_contribution_margin(None, 30.0, 5.0) is None
    assert estimate_contribution_margin(110.0, None, 5.0) is None


def test_profitability_piecewise():
    assert profitability_score(None) is None
    assert profitability_score(0) == 0.0
    assert profitability_score(25) == pytest.approx(60.0)
    assert profitability_score(55) == pytest.approx(100.0)
    assert profitability_score(50.88) == pytest.approx(95.88, abs=0.05)


def test_competition_component_inverts_index():
    components = build_components(
        growth_7d=10.0,
        growth_30d=20.0,
        listing_count=100,
        review_velocity=2.0,
        competition_index=30.0,
        margin_pct=25.0,
        seasonality_index=1.0,
    )
    assert components["competition"] == pytest.approx(70.0)
    assert components["seasonal"] == pytest.approx(50.0)
    assert components["social"] is None
