from datetime import date, datetime, timezone

from app.models import (
    OpportunityScore,
    Product,
    ProductMetric,
    Supplier,
    SupplierProduct,
)
from app.services.recommendations import build_recommendation


def _product() -> Product:
    return Product(
        name="Test Product",
        normalised_name="test product",
        slug="test-product",
        country="AU",
        currency="AUD",
        status="active",
    )


def _metric(**overrides) -> ProductMetric:
    values = {
        "as_of_date": date.today(),
        "search_growth_7d_pct": 12.0,
        "search_growth_30d_pct": 30.0,
        "competition_class": "low",
        "market_avg_price": 59.95,
    }
    values.update(overrides)
    return ProductMetric(**values)


def _score(**overrides) -> OpportunityScore:
    values = {
        "calculated_on": date.today(),
        "score": 72.0,
        "score_raw": 72.0,
        "classification": "strong",
        "estimated_margin_pct": 35.0,
        "coverage_pct": 80.0,
        "confidence_score": 0.8,
        "components": {},
    }
    values.update(overrides)
    return OpportunityScore(**values)


def _offer(cost: float = 12.0, shipping: float = 4.0) -> SupplierProduct:
    return SupplierProduct(
        external_product_id="SUP-1",
        product_cost=cost,
        shipping_cost=shipping,
        currency="AUD",
    )


def _supplier() -> Supplier:
    return Supplier(supplier_name="Acme Supply", platform_key="manual", country="CN")


def test_missing_supplier_is_investigate_not_recommended():
    recommendation = build_recommendation(
        _product(), _metric(), _score(), None, None
    )
    assert recommendation["verdict"] == "investigate"
    assert set(recommendation["missing_evidence"]) >= {
        "supplier_cost",
        "delivery_cost",
        "margin",
    }
    assert recommendation["economics"]["supplier_name"] is None
    assert recommendation["next_actions"]


def test_complete_evidence_can_recommend():
    recommendation = build_recommendation(
        _product(), _metric(), _score(), _offer(), _supplier()
    )
    assert recommendation["verdict"] == "recommended"
    assert recommendation["missing_evidence"] == []
    assert recommendation["economics"]["estimated_profit_per_unit"] is not None
    assert recommendation["checks"][-1]["key"] == "evidence"


def test_low_margin_is_not_recommended():
    recommendation = build_recommendation(
        _product(),
        _metric(),
        _score(estimated_margin_pct=8.0),
        _offer(),
        _supplier(),
    )
    assert recommendation["verdict"] == "not_recommended"
    margin = next(c for c in recommendation["checks"] if c["key"] == "margin")
    assert margin["status"] == "fail"


def test_declining_demand_fails_the_demand_check():
    recommendation = build_recommendation(
        _product(),
        _metric(search_growth_7d_pct=-4.0, search_growth_30d_pct=-9.0),
        _score(),
        _offer(),
        _supplier(),
    )
    assert recommendation["verdict"] == "not_recommended"
    demand = next(c for c in recommendation["checks"] if c["key"] == "demand")
    assert demand["status"] == "fail"


def test_zero_delivery_is_recorded_not_treated_as_missing():
    recommendation = build_recommendation(
        _product(), _metric(), _score(), _offer(shipping=0.0), _supplier()
    )
    delivery = next(c for c in recommendation["checks"] if c["key"] == "delivery_cost")
    assert delivery["status"] == "pass"
    assert "zero" in delivery["detail"]


def test_missing_growth_does_not_become_zero_percent():
    recommendation = build_recommendation(
        _product(),
        _metric(search_growth_7d_pct=None, search_growth_30d_pct=None),
        _score(),
        _offer(),
        _supplier(),
    )
    demand = next(c for c in recommendation["checks"] if c["key"] == "demand")
    assert demand["status"] == "missing"
    assert recommendation["verdict"] == "investigate"


def test_low_coverage_blocks_a_recommendation():
    recommendation = build_recommendation(
        _product(), _metric(), _score(coverage_pct=40.0), _offer(), _supplier()
    )
    assert recommendation["verdict"] == "investigate"
    assert "evidence" in recommendation["missing_evidence"]


def test_generated_at_is_timezone_aware():
    recommendation = build_recommendation(
        _product(), _metric(), _score(), _offer(), _supplier()
    )
    generated = recommendation["generated_at"]
    assert isinstance(generated, datetime)
    assert generated.tzinfo is not None
    assert generated.tzinfo == timezone.utc
