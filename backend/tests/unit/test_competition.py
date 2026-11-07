import pytest

from app.services.competition import (
    classify,
    competition_index,
    listing_component,
    price_dispersion_component,
    review_concentration_component,
)


def test_listing_component_is_monotonic_and_bounded():
    low = listing_component(10)
    mid = listing_component(100)
    high = listing_component(1000)
    assert low < mid < high <= 100
    assert listing_component(None) is None


def test_price_dispersion_needs_three_prices():
    assert price_dispersion_component([10.0, 12.0]) is None
    tight = price_dispersion_component([10.0, 10.1, 9.9])
    wide = price_dispersion_component([5.0, 20.0, 60.0])
    assert tight > wide


def test_review_concentration_needs_three_listings():
    assert review_concentration_component([1, 2]) is None
    concentrated = review_concentration_component([1000, 10, 10])
    spread = review_concentration_component([300, 300, 300])
    assert concentrated > spread


def test_competition_requires_two_signals():
    index, coverage, _ = competition_index(120)
    assert index is None
    assert coverage == pytest.approx(0.7)

    index, coverage, _ = competition_index(120, [10, 12, 14])
    assert index is not None
    assert coverage == pytest.approx(0.85)


def test_classification_bounds():
    assert classify(None, 0.0) == "unknown"
    assert classify(20, 0.5) == "unknown"
    assert classify(10, 0.9) == "low"
    assert classify(35, 0.9) == "moderate"
    assert classify(60, 0.9) == "high"
    assert classify(90, 0.9) == "saturated"
