from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.models import Category, Product, ProductMetric

router = APIRouter(tags=["competition"])


@router.get("/competition/summary")
def competition_summary(
    user: CurrentUser,
    db: DbSession,
    category_id: UUID | None = None,
    country: str = "AU",
) -> dict:
    latest = (
        select(func.max(ProductMetric.as_of_date))
        .where(ProductMetric.product_id == Product.id)
        .correlate(Product)
        .scalar_subquery()
    )
    conditions = [Product.status == "active", Product.country == country]
    if category_id:
        conditions.append(Product.category_id == category_id)

    rows = db.execute(
        select(
            ProductMetric.competition_class,
            ProductMetric.competition_index,
            ProductMetric.market_price_p25,
            ProductMetric.market_price_p75,
            Category.name,
        )
        .select_from(Product)
        .join(
            ProductMetric,
            (ProductMetric.product_id == Product.id)
            & (ProductMetric.as_of_date == latest),
        )
        .outerjoin(Category, Category.id == Product.category_id)
        .where(*conditions)
    ).all()

    classes = {"low": 0, "moderate": 0, "high": 0, "saturated": 0, "unknown": 0}
    indices = []
    p25s = []
    p75s = []
    by_category: dict[str, dict] = {}
    for row in rows:
        classes[row.competition_class] = classes.get(row.competition_class, 0) + 1
        if row.competition_index is not None:
            indices.append(float(row.competition_index))
        if row.market_price_p25 is not None:
            p25s.append(float(row.market_price_p25))
        if row.market_price_p75 is not None:
            p75s.append(float(row.market_price_p75))
        name = row.name or "Uncategorised"
        bucket = by_category.setdefault(name, {"product_count": 0, "indices": []})
        bucket["product_count"] += 1
        if row.competition_index is not None:
            bucket["indices"].append(float(row.competition_index))

    return {
        "country": country,
        "category_id": category_id,
        "product_count": len(rows),
        "average_index": round(sum(indices) / len(indices), 2) if indices else None,
        "classes": classes,
        "price_band": {
            "p25": f"{sum(p25s) / len(p25s):.2f}" if p25s else None,
            "p75": f"{sum(p75s) / len(p75s):.2f}" if p75s else None,
            "currency": "AUD",
        },
        "by_category": [
            {
                "category": name,
                "product_count": bucket["product_count"],
                "average_index": (
                    round(sum(bucket["indices"]) / len(bucket["indices"]), 2)
                    if bucket["indices"]
                    else None
                ),
            }
            for name, bucket in sorted(by_category.items())
        ],
        "caveats": [
            "Competition is estimated from active listings, price dispersion and review concentration.",
            "It is not a measure of sales.",
        ],
    }
