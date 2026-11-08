"""Opportunity recommendation rules.

A high search/opportunity score is not a reason to add a product to the
catalogue. The recommendation workflow requires the operator to investigate
supplier price, delivery cost and contribution margin first. Missing evidence
produces ``investigate``, not a zero or a false pass.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.models import OpportunityScore, Product, ProductMetric, Supplier, SupplierProduct
from app.services.scoring import estimate_contribution_margin, estimate_contribution_profit

MIN_RECOMMENDED_MARGIN_PCT = 25.0
MIN_EVIDENCE_COVERAGE_PCT = 60.0

VERDICT_LABELS = {
    "recommended": "Recommended for catalogue review",
    "investigate": "Investigate before recommending",
    "not_recommended": "Not recommended on current evidence",
}


def _money(value: Any) -> str | None:
    return f"{float(value):.2f}" if value is not None else None


def cheapest_offer(db, product_id) -> tuple[SupplierProduct | None, Supplier | None]:
    row = db.execute(
        select(SupplierProduct, Supplier)
        .join(Supplier, Supplier.id == SupplierProduct.supplier_id)
        .where(SupplierProduct.product_id == product_id)
        .order_by(SupplierProduct.product_cost + SupplierProduct.shipping_cost)
        .limit(1)
    ).first()
    return (row[0], row[1]) if row is not None else (None, None)


def offers_by_product(db, product_ids) -> dict:
    """Cheapest supplier offer per product, in one query."""
    if not product_ids:
        return {}
    rows = db.execute(
        select(SupplierProduct, Supplier)
        .join(Supplier, Supplier.id == SupplierProduct.supplier_id)
        .where(SupplierProduct.product_id.in_(list(product_ids)))
        .order_by(SupplierProduct.product_cost + SupplierProduct.shipping_cost)
    ).all()
    offers: dict = {}
    for offer, supplier in rows:
        offers.setdefault(offer.product_id, (offer, supplier))
    return offers


def _growth_detail(metric: ProductMetric | None) -> str:
    if metric is None:
        return "No metric snapshot."
    parts = []
    for window in (7, 30):
        value = getattr(metric, f"search_growth_{window}d_pct", None)
        parts.append(
            f"{window}d {'unavailable' if value is None else f'{float(value):+.1f}%'}"
        )
    return ", ".join(parts)


def _check(key: str, label: str, status: str, detail: str) -> dict:
    return {"key": key, "label": label, "status": status, "detail": detail}


def build_recommendation(
    product: Product,
    metric: ProductMetric | None,
    score: OpportunityScore | None,
    offer: SupplierProduct | None,
    supplier: Supplier | None,
    *,
    min_margin_pct: float = MIN_RECOMMENDED_MARGIN_PCT,
) -> dict:
    checks: list[dict] = []

    growth_7d = (
        float(metric.search_growth_7d_pct)
        if metric is not None and metric.search_growth_7d_pct is not None
        else None
    )
    growth_30d = (
        float(metric.search_growth_30d_pct)
        if metric is not None and metric.search_growth_30d_pct is not None
        else None
    )
    if growth_7d is None and growth_30d is None:
        checks.append(
            _check("demand", "Search demand", "missing", "No usable search history.")
        )
    elif (growth_7d or 0) > 0 or (growth_30d or 0) > 0:
        checks.append(
            _check("demand", "Search demand", "pass", _growth_detail(metric))
        )
    else:
        checks.append(
            _check("demand", "Search demand", "fail", f"Not rising: {_growth_detail(metric)}.")
        )

    if offer is None:
        checks.append(
            _check(
                "supplier_cost",
                "Supplier price",
                "missing",
                "No supplier offer recorded. Add a quote before recommending.",
            )
        )
        checks.append(
            _check(
                "delivery_cost",
                "Delivery cost",
                "missing",
                "No delivery cost recorded for a supplier offer.",
            )
        )
    else:
        product_cost = float(offer.product_cost) if offer.product_cost is not None else None
        if product_cost is None or product_cost <= 0:
            checks.append(
                _check(
                    "supplier_cost",
                    "Supplier price",
                    "missing",
                    "Supplier cost is missing or zero; verify the quote.",
                )
            )
        else:
            checks.append(
                _check(
                    "supplier_cost",
                    "Supplier price",
                    "pass",
                    f"{_money(product_cost)} {offer.currency} per unit from {supplier.supplier_name if supplier else 'supplier'}.",
                )
            )
        shipping = float(offer.shipping_cost) if offer.shipping_cost is not None else None
        if shipping is None:
            checks.append(
                _check("delivery_cost", "Delivery cost", "missing", "Delivery cost not recorded.")
            )
        elif shipping == 0:
            checks.append(
                _check(
                    "delivery_cost",
                    "Delivery cost",
                    "pass",
                    "Delivery cost recorded as zero; confirm free shipping is real.",
                )
            )
        else:
            checks.append(
                _check(
                    "delivery_cost",
                    "Delivery cost",
                    "pass",
                    f"{_money(shipping)} {offer.currency} per unit.",
                )
            )

    # A stored margin without a supplier offer behind it is stale, not evidence.
    margin = (
        float(score.estimated_margin_pct)
        if score is not None and score.estimated_margin_pct is not None and offer is not None
        else None
    )
    if margin is None:
        checks.append(
            _check(
                "margin",
                "Contribution margin",
                "missing",
                "Margin needs both a market price and a supplier cost.",
            )
        )
    elif margin >= min_margin_pct:
        checks.append(
            _check(
                "margin",
                "Contribution margin",
                "pass",
                f"{margin:.1f}% after estimated fees, fulfilment and returns (target {min_margin_pct:.0f}%).",
            )
        )
    else:
        checks.append(
            _check(
                "margin",
                "Contribution margin",
                "fail",
                f"{margin:.1f}% is below the {min_margin_pct:.0f}% target.",
            )
        )

    competition = metric.competition_class if metric is not None else "unknown"
    if competition == "unknown":
        checks.append(
            _check(
                "competition",
                "Competition",
                "missing",
                "Fewer than two independent competition signals.",
            )
        )
    elif competition in ("low", "moderate"):
        checks.append(
            _check("competition", "Competition", "pass", f"Classified {competition}.")
        )
    else:
        checks.append(
            _check(
                "competition",
                "Competition",
                "fail",
                f"Classified {competition}; too crowded for a first catalogue entry.",
            )
        )

    coverage = float(score.coverage_pct) if score is not None else 0.0
    if score is None:
        checks.append(
            _check(
                "evidence",
                "Evidence coverage",
                "missing",
                "No opportunity score has been computed.",
            )
        )
    elif coverage >= MIN_EVIDENCE_COVERAGE_PCT:
        checks.append(
            _check(
                "evidence",
                "Evidence coverage",
                "pass",
                f"{coverage:.0f}% of weighted evidence available.",
            )
        )
    else:
        checks.append(
            _check(
                "evidence",
                "Evidence coverage",
                "missing",
                f"Only {coverage:.0f}% coverage; score is not ranked as an opportunity.",
            )
        )

    fail_count = sum(1 for check in checks if check["status"] == "fail")
    missing = [check for check in checks if check["status"] == "missing"]
    if fail_count:
        verdict = "not_recommended"
    elif missing:
        verdict = "investigate"
    else:
        verdict = "recommended"

    price = (
        float(metric.market_avg_price)
        if metric is not None and metric.market_avg_price is not None
        else None
    )
    product_cost = (
        float(offer.product_cost)
        if offer is not None and offer.product_cost is not None
        else None
    )
    shipping_cost = float(offer.shipping_cost or 0) if offer is not None else None
    profit = estimate_contribution_profit(price, product_cost, shipping_cost)
    calculated_margin = estimate_contribution_margin(price, product_cost, shipping_cost)

    if verdict == "recommended":
        summary = (
            f"Demand is rising and the estimated margin is {margin:.1f}% with "
            "supplier and delivery costs recorded."
        )
    elif verdict == "not_recommended":
        failed = "; ".join(check["detail"] for check in checks if check["status"] == "fail")
        summary = f"Do not add yet. {failed}"
    else:
        summary = (
            "Investigate first: "
            + "; ".join(f"{check['label'].lower()} ({check['detail']})" for check in missing)
            + "."
        )

    next_actions = [
        {
            "key": check["key"],
            "action": _action_for(check["key"]),
        }
        for check in [*missing, *[c for c in checks if c["status"] == "fail"]]
    ]

    return {
        "verdict": verdict,
        "label": VERDICT_LABELS[verdict],
        "summary": summary,
        "checks": checks,
        "missing_evidence": [check["key"] for check in missing],
        "next_actions": next_actions,
        "economics": {
            "currency": product.currency or "AUD",
            "market_price": _money(price),
            "product_cost": _money(product_cost),
            "delivery_cost": _money(shipping_cost),
            "landed_cost": (
                _money(float(product_cost) + float(shipping_cost or 0))
                if product_cost is not None
                else None
            ),
            "estimated_profit_per_unit": _money(profit),
            "estimated_margin_pct": (
                round(calculated_margin, 2) if calculated_margin is not None else None
            ),
            "supplier_name": supplier.supplier_name if supplier else None,
            "supplier_is_synthetic": bool(supplier.is_synthetic) if supplier else None,
        },
        "thresholds": {
            "min_margin_pct": min_margin_pct,
            "min_coverage_pct": MIN_EVIDENCE_COVERAGE_PCT,
        },
        "disclaimer": (
            "Estimated from available evidence. Supplier costs and delivery must be "
            "confirmed with the supplier; this is not a sales forecast."
        ),
        "generated_at": datetime.now(timezone.utc),
    }


def _action_for(key: str) -> str:
    return {
        "demand": "Record a search-interest observation or import a Google Trends CSV.",
        "supplier_cost": "Request a supplier quote and record the unit cost.",
        "delivery_cost": "Record the supplier's delivery cost per unit.",
        "margin": "Recheck the market price and supplier quote; margin needs both.",
        "competition": "Investigate listing saturation before committing.",
        "evidence": "Collect more observations so coverage clears 60%.",
    }.get(key, "Collect the missing evidence.")
