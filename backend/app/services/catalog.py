"""Explorer query layer and single-product loading."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, case, exists, func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    Category,
    OpportunityScore,
    Product,
    ProductKeyword,
    ProductMetric,
    ScoringProfile,
    SupplierProduct,
    WatchlistEntry,
)
from app.services.presenters import product_summary


@dataclass
class ProductRow:
    product: Product
    category: Category | None
    metric: ProductMetric | None
    score: OpportunityScore | None
    supplier_available: bool


def _latest_metric_date():
    return (
        select(func.max(ProductMetric.as_of_date))
        .where(ProductMetric.product_id == Product.id)
        .correlate(Product)
        .scalar_subquery()
    )


def _latest_score_id():
    """Id of the newest score row for the product.

    Selecting on ``max(calculated_on)`` alone fans out when two scoring profiles
    have a row for the same day (for example immediately after a profile switch),
    duplicating the product in every read. ``calculated_at`` breaks the tie in
    favour of the most recently computed row.
    """
    return (
        select(OpportunityScore.id)
        .where(OpportunityScore.product_id == Product.id)
        .order_by(
            OpportunityScore.calculated_on.desc(),
            OpportunityScore.calculated_at.desc(),
        )
        .limit(1)
        .correlate(Product)
        .scalar_subquery()
    )


def _supplier_exists():
    return (
        select(SupplierProduct.id)
        .where(SupplierProduct.product_id == Product.id)
        .exists()
    )


def _base_select():
    return (
        select(
            Product,
            Category,
            ProductMetric,
            OpportunityScore,
            _supplier_exists().label("supplier_available"),
        )
        .select_from(Product)
        .outerjoin(Category, Category.id == Product.category_id)
        .outerjoin(
            ProductMetric,
            and_(
                ProductMetric.product_id == Product.id,
                ProductMetric.as_of_date == _latest_metric_date(),
            ),
        )
        .outerjoin(
            OpportunityScore,
            and_(
                OpportunityScore.product_id == Product.id,
                OpportunityScore.id == _latest_score_id(),
            ),
        )
    )


def _apply_filters(stmt, params: dict[str, Any]):
    status = params.get("status") or "active"
    if status:
        stmt = stmt.where(Product.status == status)
    country = params.get("country")
    if country:
        stmt = stmt.where(Product.country == country)
    if q := (params.get("q") or "").strip():
        term = f"%{q.lower()}%"
        keyword_exists = exists(
            select(ProductKeyword.id).where(
                ProductKeyword.product_id == Product.id,
                func.lower(ProductKeyword.keyword).like(term),
            )
        )
        stmt = stmt.where(
            or_(
                func.lower(Product.name).like(term),
                func.lower(func.coalesce(Product.brand, "")).like(term),
                keyword_exists,
            )
        )
    if category_id := params.get("category_id"):
        stmt = stmt.where(Product.category_id == category_id)
    if path := params.get("category_path"):
        stmt = stmt.where(
            or_(Category.path == path, Category.path.like(f"{path}/%"), Category.slug == path)
        )
    if (min_score := params.get("min_score")) is not None:
        stmt = stmt.where(OpportunityScore.score >= min_score)
    if (max_score := params.get("max_score")) is not None:
        stmt = stmt.where(OpportunityScore.score <= max_score)
    if (min_growth_7d := params.get("min_growth_7d")) is not None:
        stmt = stmt.where(ProductMetric.search_growth_7d_pct >= min_growth_7d)
    if (min_growth_30d := params.get("min_growth_30d")) is not None:
        stmt = stmt.where(ProductMetric.search_growth_30d_pct >= min_growth_30d)
    if direction := params.get("trend_direction"):
        stmt = stmt.where(ProductMetric.trend_direction == direction)
    competition = params.get("competition")
    if competition:
        values = competition if isinstance(competition, (list, tuple, set)) else [competition]
        stmt = stmt.where(ProductMetric.competition_class.in_(list(values)))
    if (min_price := params.get("min_price")) is not None:
        stmt = stmt.where(ProductMetric.market_avg_price >= min_price)
    if (max_price := params.get("max_price")) is not None:
        stmt = stmt.where(ProductMetric.market_avg_price <= max_price)
    if (min_margin := params.get("min_margin")) is not None:
        stmt = stmt.where(OpportunityScore.estimated_margin_pct >= min_margin)
    if params.get("supplier_available") is True:
        stmt = stmt.where(_supplier_exists())
    elif params.get("supplier_available") is False:
        stmt = stmt.where(~_supplier_exists())
    synthetic = params.get("synthetic") or "include"
    if synthetic == "exclude":
        stmt = stmt.where(Product.is_synthetic.is_(False))
    elif synthetic == "only":
        stmt = stmt.where(Product.is_synthetic.is_(True))
    return stmt


SORTS = {
    "-opportunity_score": lambda: OpportunityScore.score,
    "-growth_7d": lambda: ProductMetric.search_growth_7d_pct,
    "-growth_30d": lambda: ProductMetric.search_growth_30d_pct,
    "-growth_90d": lambda: ProductMetric.search_growth_90d_pct,
    "growth_7d": lambda: ProductMetric.search_growth_7d_pct,
    "growth_30d": lambda: ProductMetric.search_growth_30d_pct,
    "growth_90d": lambda: ProductMetric.search_growth_90d_pct,
    "-seasonality": lambda: ProductMetric.seasonality_index,
    "-marketplace_popularity": lambda: ProductMetric.market_listing_count,
    "competition_index": lambda: ProductMetric.competition_index,
    "-estimated_margin": lambda: OpportunityScore.estimated_margin_pct,
    "-first_seen_at": lambda: Product.first_seen_at,
    "name": lambda: Product.name,
}

DESCENDING = {
    "-opportunity_score",
    "-growth_7d",
    "-growth_30d",
    "-growth_90d",
    "-seasonality",
    "-marketplace_popularity",
    "-estimated_margin",
    "-first_seen_at",
}


def _apply_sort(stmt, sort: str | None):
    key = sort if sort in SORTS else "-opportunity_score"
    column = SORTS[key]()
    nulls_last = case((column.is_(None), 1), else_=0)
    if key in DESCENDING:
        return stmt.order_by(nulls_last, column.desc())
    return stmt.order_by(nulls_last, column.asc())


def query_products(
    db: Session, params: dict[str, Any], page: int = 1, per_page: int = 25
) -> tuple[list[ProductRow], int]:
    page = max(1, page)
    per_page = max(1, min(per_page, 100))

    count_stmt = _apply_filters(
        select(func.count(func.distinct(Product.id)))
        .select_from(Product)
        .outerjoin(Category, Category.id == Product.category_id)
        .outerjoin(
            ProductMetric,
            and_(
                ProductMetric.product_id == Product.id,
                ProductMetric.as_of_date == _latest_metric_date(),
            ),
        )
        .outerjoin(
            OpportunityScore,
            and_(
                OpportunityScore.product_id == Product.id,
                OpportunityScore.id == _latest_score_id(),
            ),
        ),
        params,
    )
    total = int(db.execute(count_stmt).scalar() or 0)

    stmt = _apply_sort(_apply_filters(_base_select(), params), params.get("sort"))
    rows = db.execute(stmt.offset((page - 1) * per_page).limit(per_page)).all()
    return [
        ProductRow(
            product=row[0],
            category=row[1],
            metric=row[2],
            score=row[3],
            supplier_available=bool(row[4]),
        )
        for row in rows
    ], total


def get_product_row(db: Session, identifier: str | UUID) -> ProductRow | None:
    stmt = _base_select()
    if isinstance(identifier, UUID):
        stmt = stmt.where(Product.id == identifier)
    else:
        try:
            parsed = UUID(str(identifier))
        except (ValueError, AttributeError):
            stmt = stmt.where(Product.slug == str(identifier))
        else:
            stmt = stmt.where(or_(Product.id == parsed, Product.slug == str(identifier)))
    row = db.execute(stmt.limit(1)).first()
    if row is None:
        return None
    return ProductRow(
        product=row[0],
        category=row[1],
        metric=row[2],
        score=row[3],
        supplier_available=bool(row[4]),
    )


def profile_for_score(db: Session, score: OpportunityScore | None) -> ScoringProfile | None:
    if score is None:
        return None
    return db.get(ScoringProfile, score.scoring_profile_id)


def summary_payload(db: Session, row: ProductRow) -> dict:
    return product_summary(
        db,
        row.product,
        row.category,
        row.metric,
        row.score,
        profile_for_score(db, row.score),
        supplier_available=row.supplier_available,
    )


def list_payload(db: Session, rows: list[ProductRow]) -> list[dict]:
    profiles: dict = {}
    payload = []
    for row in rows:
        profile = None
        if row.score is not None:
            profile = profiles.get(row.score.scoring_profile_id)
            if profile is None:
                profile = profile_for_score(db, row.score)
                profiles[row.score.scoring_profile_id] = profile
        payload.append(
            product_summary(
                db,
                row.product,
                row.category,
                row.metric,
                row.score,
                profile,
                supplier_available=row.supplier_available,
            )
        )
    return payload


def top_rows(db: Session, sort: str, limit: int = 10, conditions=None) -> list[ProductRow]:
    """Top-N rows for a dashboard widget; widgets are read models, not new data."""
    stmt = _apply_sort(_base_select(), sort).where(Product.status == "active")
    for condition in conditions or []:
        stmt = stmt.where(condition)
    rows = db.execute(stmt.limit(max(1, min(limit, 50)))).all()
    return [
        ProductRow(
            product=row[0],
            category=row[1],
            metric=row[2],
            score=row[3],
            supplier_available=bool(row[4]),
        )
        for row in rows
    ]


def pagination_meta(
    page: int, per_page: int, total: int, filters: dict[str, Any]
) -> dict:
    pages = (total + per_page - 1) // per_page if per_page else 0
    return {
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": pages,
        "generated_at": datetime.now(timezone.utc),
        "filters_applied": filters,
    }


def category_counts(db: Session) -> dict:
    rows = db.execute(
        select(Product.category_id, func.count(Product.id))
        .where(Product.status == "active")
        .group_by(Product.category_id)
    ).all()
    return {row[0]: int(row[1]) for row in rows}


def watchlist_entry(db: Session, user_id, product_id) -> WatchlistEntry | None:
    return db.execute(
        select(WatchlistEntry).where(
            WatchlistEntry.user_id == user_id,
            WatchlistEntry.product_id == product_id,
        )
    ).scalar_one_or_none()
