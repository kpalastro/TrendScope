from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.errors import ApiError
from app.models import OpportunityScore, Product, ProductMetric, TrendObservation
from app.services.catalog import list_payload, query_products, top_rows
from app.services.growth import seasonality_index

router = APIRouter(tags=["discovery"])


def _synthetic_condition(mode: str):
    if mode == "exclude":
        return Product.is_synthetic.is_(False)
    if mode == "only":
        return Product.is_synthetic.is_(True)
    return None


def _payload(db, rows, note: str, **meta) -> dict:
    return {
        "data": list_payload(db, rows) if rows else [],
        "meta": {
            "generated_at": datetime.now(timezone.utc),
            "note": note,
            **meta,
        },
    }


@router.get("/trending")
def trending(
    user: CurrentUser,
    db: DbSession,
    window: int = 7,
    direction: Literal["rising", "declining"] = "rising",
    limit: int = 20,
    synthetic: Literal["include", "exclude", "only"] = "include",
) -> dict:
    if window not in (7, 30, 90):
        raise ApiError(422, "VALIDATION_ERROR", "window must be 7, 30 or 90")
    column = getattr(ProductMetric, f"search_growth_{window}d_pct")
    conditions = [column.is_not(None)]
    if direction == "rising":
        conditions.append(column > 0)
        sort = f"-growth_{window}d"
    else:
        conditions.append(column < 0)
        sort = f"growth_{window}d"
    extra = _synthetic_condition(synthetic)
    if extra is not None:
        conditions.append(extra)
    rows = top_rows(db, sort, limit=limit, conditions=conditions)
    return _payload(
        db,
        rows,
        f"Ranked by {window}-day search growth, {direction}. Growth is relative search "
        "interest, not sales.",
        window=window,
        direction=direction,
    )


@router.get("/emerging")
def emerging(
    user: CurrentUser,
    db: DbSession,
    since_days: int = 30,
    limit: int = 20,
    synthetic: Literal["include", "exclude", "only"] = "include",
) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, min(since_days, 365)))
    conditions = [
        Product.first_seen_at >= cutoff,
        ProductMetric.search_growth_7d_pct.is_not(None),
        ProductMetric.search_growth_7d_pct > 0,
    ]
    extra = _synthetic_condition(synthetic)
    if extra is not None:
        conditions.append(extra)
    rows = top_rows(db, "-growth_7d", limit=limit, conditions=conditions)
    return _payload(
        db,
        rows,
        "Both conditions must hold: discovered within the window and rising over 7 days. "
        "A new product without growth is new, not emerging.",
        since_days=since_days,
    )


@router.get("/opportunities")
def opportunities(
    user: CurrentUser,
    db: DbSession,
    min_score: float | None = None,
    min_coverage: float = 60.0,
    limit: int = 20,
    synthetic: Literal["include", "exclude", "only"] = "include",
) -> dict:
    conditions = [
        OpportunityScore.score.is_not(None),
        OpportunityScore.coverage_pct >= min_coverage,
    ]
    if min_score is not None:
        conditions.append(OpportunityScore.score >= min_score)
    extra = _synthetic_condition(synthetic)
    if extra is not None:
        conditions.append(extra)
    rows = top_rows(db, "-opportunity_score", limit=limit, conditions=conditions)
    return _payload(
        db,
        rows,
        f"Coverage-gated at {min_coverage:.0f}%: low-coverage products are excluded rather than "
        "presented as opportunities.",
        min_coverage=min_coverage,
    )


def _seasonal_rows(db, horizon_days: int, limit: int, synthetic: str):
    """Rank active rows by the seasonality index for the requested horizon.

    ``product_metrics.seasonality_index`` is stored for the default 90-day
    window, so a 45-day request must be recomputed from the raw series rather
    than returning the 90-day ranking with a different label.
    """
    rows = []
    page = 1
    while True:
        batch, total = query_products(
            db,
            {"sort": "-seasonality", "synthetic": synthetic, "status": "active"},
            page=page,
            per_page=100,
        )
        rows.extend(batch)
        if not batch or len(rows) >= total or page >= 20:
            break
        page += 1
    if not rows:
        return []

    product_ids = [row.product.id for row in rows]
    observations = db.execute(
        select(
            TrendObservation.product_id,
            TrendObservation.observation_date,
            TrendObservation.metric_value,
        ).where(
            TrendObservation.product_id.in_(product_ids),
            TrendObservation.metric_name == "search_interest",
        )
    ).all()
    series: dict = {}
    for product_id, day, value in observations:
        series.setdefault(product_id, {})[day] = float(value)

    today = date.today()
    ranked: list[tuple[float, object]] = []
    for row in rows:
        index = seasonality_index(series.get(row.product.id, {}), today, horizon_days)
        if index is not None and index > 1.0:
            ranked.append((index, row))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [row for _, row in ranked[: max(1, min(limit, 50))]]


@router.get("/seasonal")
def seasonal(
    user: CurrentUser,
    db: DbSession,
    horizon_days: int = 90,
    limit: int = 20,
    synthetic: Literal["include", "exclude", "only"] = "include",
) -> dict:
    if horizon_days not in (45, 90):
        raise ApiError(422, "VALIDATION_ERROR", "horizon_days must be 45 or 90")
    rows = _seasonal_rows(db, horizon_days, limit, synthetic)
    return _payload(
        db,
        rows,
        "Seasonality index above 1.0 means the upcoming window is expected to run above the "
        "annual average. Requires at least 12 months of history.",
        horizon_days=horizon_days,
    )
