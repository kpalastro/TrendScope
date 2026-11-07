from __future__ import annotations

import math
from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, File, Query, Response, UploadFile
from sqlalchemy import select

from app.api.deps import AdminUser, CurrentUser, DbSession, WriteUser
from app.core.errors import ApiError
from app.models import (
    Category,
    DataSource,
    MarketplaceListing,
    OpportunityScore,
    Product,
    ProductKeyword,
    ProductMetric,
    Supplier,
    SupplierProduct,
    TrendObservation,
    utcnow,
)
from app.schemas import ProductCreate, ProductPatch
from app.services import importing
from app.services.catalog import (
    get_product_row,
    list_payload,
    pagination_meta,
    query_products,
    summary_payload,
)
from app.services.competition import competition_index, price_dispersion_component, review_concentration_component
from app.services.metrics import compute_product_metrics
from app.services.normalise import normalise_name, slugify
from app.services.slugs import unique_external_id, unique_product_slug
from app.services.presenters import (
    DISCLAIMER,
    as_float,
    keywords,
    money,
    product_sources,
    score_breakdown,
    trend_series,
)
from app.services.scoring_service import compute_product_score, get_active_profile

router = APIRouter(prefix="/products", tags=["products"])

MAX_CSV_BYTES = 2 * 1024 * 1024


def _price(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(str(value).replace("$", "").replace(",", ""))
    except ValueError as exc:
        raise ApiError(422, "VALIDATION_ERROR", "price must be a number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ApiError(422, "VALIDATION_ERROR", "price must be greater than zero")
    return parsed


def _require_row(db, identifier) -> "ProductRow":  # noqa: F821
    row = get_product_row(db, identifier)
    if row is None:
        raise ApiError(404, "NOT_FOUND", "Product not found.")
    return row


def _listings(db, product_id) -> list[dict]:
    rows = db.execute(
        select(MarketplaceListing)
        .where(MarketplaceListing.product_id == product_id)
        .order_by(MarketplaceListing.price)
    ).scalars()
    return [
        {
            "id": listing.id,
            "marketplace": listing.marketplace,
            "title": listing.title,
            "seller_name": listing.seller_name,
            "price": money(listing.price),
            "currency": listing.currency,
            "rating": as_float(listing.rating),
            "review_count": listing.review_count,
            "is_active": listing.is_active,
        }
        for listing in rows
    ]


def _suppliers(db, product_id) -> list[dict]:
    rows = db.execute(
        select(SupplierProduct, Supplier)
        .join(Supplier, Supplier.id == SupplierProduct.supplier_id)
        .where(SupplierProduct.product_id == product_id)
        .order_by(SupplierProduct.product_cost + SupplierProduct.shipping_cost)
    ).all()
    return [
        {
            "id": offer.id,
            "supplier_id": supplier.id,
            "supplier_name": supplier.supplier_name,
            "country": supplier.country,
            "supplier_rating": as_float(supplier.supplier_rating),
            "product_cost": money(offer.product_cost),
            "shipping_cost": money(offer.shipping_cost),
            "currency": offer.currency,
            "minimum_order_quantity": offer.minimum_order_quantity,
            "lead_time_days": offer.lead_time_days,
            "availability": offer.availability,
            "is_synthetic": bool(supplier.is_synthetic),
        }
        for offer, supplier in rows
    ]


def _competition(db, row) -> dict | None:
    metric = row.metric
    if metric is None:
        return None
    listings = db.execute(
        select(MarketplaceListing).where(
            MarketplaceListing.product_id == row.product.id,
            MarketplaceListing.is_active.is_(True),
        )
    ).scalars().all()
    prices = [float(item.price) for item in listings if item.price]
    reviews = [int(item.review_count) for item in listings if item.review_count]
    index, coverage, detail = competition_index(
        metric.market_listing_count, prices, reviews
    )
    unavailable = ["advertising_saturation", "amazon_au_sales"]
    if not prices:
        unavailable.append("price_dispersion")
    if not reviews:
        unavailable.append("review_concentration")
    return {
        "product_id": row.product.id,
        "index": as_float(index),
        "classification": metric.competition_class,
        "coverage": round(float(coverage), 2),
        "evidence": {
            "active_listing_count": {
                "value": metric.market_listing_count,
                "source": "mock",
                "status": "synthetic" if row.product.is_synthetic else "observed",
            },
            "price_dispersion_cv": price_dispersion_component(prices),
            "review_concentration": review_concentration_component(reviews),
            "components": detail,
        },
        "unavailable": unavailable,
        "caveats": [
            "Based on active marketplace listings, not sales.",
            "Competition needs at least two independent signals; below that it is unknown.",
        ],
        "classified_at": metric.as_of_date,
    }


def detail_payload(db, row) -> dict:
    from app.services.catalog import profile_for_score

    payload = summary_payload(db, row)
    scores = db.execute(
        select(OpportunityScore)
        .where(OpportunityScore.product_id == row.product.id)
        .order_by(OpportunityScore.calculated_on.desc())
        .limit(12)
    ).scalars().all()
    profile = profile_for_score(db, row.score) if row.score is not None else None
    payload.update(
        {
            "description": row.product.description,
            "keywords": keywords(db, row.product.id),
            "model": row.product.model,
            "attributes": row.product.attributes or {},
            "score_breakdown": (
                score_breakdown(row.score, profile) if row.score is not None else None
            ),
            "competition": _competition(db, row),
            "listings": _listings(db, row.product.id),
            "suppliers": _suppliers(db, row.product.id),
            "trend_series": trend_series(db, row.product.id),
            "recent_scores": [
                score_breakdown(score, profile_for_score(db, score)) for score in scores
            ],
            "sources": product_sources(db, row.product.id),
            "disclaimer": DISCLAIMER,
        }
    )
    return payload


@router.get("/import/csv/template")
def csv_template(user: CurrentUser) -> Response:
    return Response(
        content=importing.template_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="trendscope-products-template.csv"'},
    )


@router.post("/import/csv", status_code=202)
async def import_csv(
    user: WriteUser,
    db: DbSession,
    file: UploadFile = File(...),
) -> dict:
    source = db.execute(
        select(DataSource).where(DataSource.provider_key == "csv_import")
    ).scalar_one_or_none()
    if source is None:
        raise ApiError(503, "SOURCE_UNAVAILABLE", "The CSV import source is not configured.")
    raw = await file.read(MAX_CSV_BYTES + 1)
    if len(raw) > MAX_CSV_BYTES:
        raise ApiError(422, "BUSINESS_RULE_VIOLATION", "CSV file exceeds 2 MB.")
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ApiError(422, "VALIDATION_ERROR", "CSV must be UTF-8 encoded.") from exc
    result = importing.import_csv(db, source, content)
    return {
        "job": {
            "id": f"import-{utcnow().strftime('%Y%m%d%H%M%S')}",
            "type": "import.csv",
            "status": "succeeded",
            "progress": {"processed": result.total, "total": result.total},
            "result_url": "/api/v1/products",
            "error": None,
            "created_at": utcnow(),
            "poll_url": "/api/v1/products",
        },
        "created": result.created,
        "updated": result.updated,
        "rejected": result.rejected,
        "errors": result.errors,
    }


@router.get("")
def list_products(
    user: CurrentUser,
    db: DbSession,
    q: str | None = None,
    country: str | None = "AU",
    category_id: UUID | None = None,
    category_path: str | None = None,
    status: str | None = "active",
    min_score: float | None = None,
    max_score: float | None = None,
    min_growth_7d: float | None = None,
    min_growth_30d: float | None = None,
    trend_direction: str | None = None,
    competition: Annotated[list[str] | None, Query()] = None,
    min_price: float | None = None,
    max_price: float | None = None,
    min_margin: float | None = None,
    supplier_available: bool | None = None,
    synthetic: Literal["include", "exclude", "only"] = "include",
    sort: str | None = "-opportunity_score",
    page: int = 1,
    per_page: int = 25,
) -> dict:
    params = {
        "q": q,
        "country": country,
        "category_id": category_id,
        "category_path": category_path,
        "status": status,
        "min_score": min_score,
        "max_score": max_score,
        "min_growth_7d": min_growth_7d,
        "min_growth_30d": min_growth_30d,
        "trend_direction": trend_direction,
        "competition": competition,
        "min_price": min_price,
        "max_price": max_price,
        "min_margin": min_margin,
        "supplier_available": supplier_available,
        "synthetic": synthetic,
        "sort": sort,
    }
    page = max(1, page)
    per_page = max(1, min(per_page, 100))
    rows, total = query_products(db, params, page=page, per_page=per_page)
    applied = {key: value for key, value in params.items() if value not in (None, "", [])}
    return {
        "data": list_payload(db, rows),
        "meta": pagination_meta(page, per_page, total, applied),
    }


@router.post("", status_code=201)
def create_product(payload: ProductCreate, user: WriteUser, db: DbSession) -> dict:
    source = db.execute(
        select(DataSource).where(DataSource.provider_key == "csv_import")
    ).scalar_one_or_none()
    if source is None:
        raise ApiError(503, "SOURCE_UNAVAILABLE", "The manual product source is not configured.")
    category = db.get(Category, payload.category_id) if payload.category_id else None
    if payload.category_id and category is None:
        raise ApiError(422, "VALIDATION_ERROR", "Unknown category_id.")
    normalised = normalise_name(payload.name)
    candidates = (
        db.execute(select(Product).where(Product.normalised_name == normalised)).scalars().all()
    )
    if any(item.status == "active" for item in candidates):
        raise ApiError(409, "CONFLICT", "A product with this name already exists.")
    # An archived row still owns (source_id, external_id) and the product's raw
    # history. Re-activate it instead of inserting a duplicate that would violate
    # the unique constraint.
    archived = next((item for item in candidates if item.status == "archived"), None)

    price = _price(payload.price)
    if archived is not None:
        product = archived
        product.name = payload.name
        product.normalised_name = normalised
        product.description = payload.description
        product.category_id = category.id if category else None
        product.brand = payload.brand
        product.status = "active"
        product.is_manual = True
        product.last_seen_at = utcnow()
        product.updated_at = utcnow()
    else:
        product = Product(
            external_id=unique_external_id(db, source.id, f"manual-{slugify(payload.name)}"),
            source_id=source.id,
            name=payload.name,
            normalised_name=normalised,
            slug=unique_product_slug(db, payload.name, payload.name),
            description=payload.description,
            category_id=category.id if category else None,
            brand=payload.brand,
            country="AU",
            currency="AUD",
            status="active",
            is_manual=True,
            first_seen_at=utcnow(),
            last_seen_at=utcnow(),
        )
        db.add(product)
        db.flush()

    seen_keywords: set[str] = set()
    for keyword in payload.keywords:
        normalised_keyword = (normalise_name(keyword) or keyword.lower())[:200]
        if not normalised_keyword or normalised_keyword in seen_keywords:
            continue
        seen_keywords.add(normalised_keyword)
        exists = db.execute(
            select(ProductKeyword.id).where(
                ProductKeyword.product_id == product.id,
                ProductKeyword.normalised_keyword == normalised_keyword,
                ProductKeyword.source_id == source.id,
            )
        ).first()
        if exists is None:
            db.add(
                ProductKeyword(
                    product_id=product.id,
                    keyword=keyword[:200],
                    normalised_keyword=normalised_keyword,
                    source_id=source.id,
                )
            )
    if price is not None:
        today = date.today()
        observation = db.execute(
            select(TrendObservation).where(
                TrendObservation.product_id == product.id,
                TrendObservation.source_id == source.id,
                TrendObservation.observation_date == today,
                TrendObservation.metric_name == "marketplace_avg_price",
                TrendObservation.granularity == "daily",
                TrendObservation.country == "AU",
            )
        ).scalar_one_or_none()
        if observation is None:
            db.add(
                TrendObservation(
                    product_id=product.id,
                    source_id=source.id,
                    observation_date=today,
                    granularity="daily",
                    metric_name="marketplace_avg_price",
                    metric_value=price,
                    unit="aud",
                    country="AU",
                    currency="AUD",
                    is_synthetic=False,
                    meta={"origin": "manual_entry"},
                )
            )
    # The session does not autoflush, so the new observation must reach the
    # database before metrics are computed from it.
    db.flush()
    metric = compute_product_metrics(db, product, date.today())
    profile = get_active_profile(db)
    if profile is not None:
        compute_product_score(db, product, metric, profile, date.today())
    db.commit()
    row = _require_row(db, product.id)
    return detail_payload(db, row)


@router.get("/{identifier}")
def get_product(identifier: str, user: CurrentUser, db: DbSession) -> dict:
    return detail_payload(db, _require_row(db, identifier))


@router.patch("/{identifier}")
def patch_product(identifier: str, payload: ProductPatch, user: WriteUser, db: DbSession) -> dict:
    row = _require_row(db, identifier)
    product = row.product
    if payload.name is not None:
        product.name = payload.name
        product.normalised_name = normalise_name(payload.name)
    if payload.category_id is not None:
        category = db.get(Category, payload.category_id)
        if category is None:
            raise ApiError(422, "VALIDATION_ERROR", "Unknown category_id.")
        product.category_id = category.id
    if payload.brand is not None:
        product.brand = payload.brand
    if payload.description is not None:
        product.description = payload.description
    if payload.status is not None:
        product.status = payload.status
    product.updated_at = utcnow()
    db.commit()
    return detail_payload(db, _require_row(db, product.id))


@router.delete("/{identifier}", status_code=204)
def archive_product(identifier: str, user: AdminUser, db: DbSession) -> Response:
    product = _require_row(db, identifier).product
    product.status = "archived"
    product.updated_at = utcnow()
    db.commit()
    return Response(status_code=204)


@router.get("/{identifier}/trends")
def product_trends(
    identifier: str,
    user: CurrentUser,
    db: DbSession,
    metric: str | None = None,
    limit: int = 365,
) -> dict:
    row = _require_row(db, identifier)
    series = trend_series(db, row.product.id, limit_days=max(1, min(limit, 2000)))
    if metric:
        series = [item for item in series if item["metric_name"] == metric]
    return {"product_id": row.product.id, "series": series}


def _metric_payload(metric: ProductMetric) -> dict:
    return {
        "as_of_date": metric.as_of_date,
        "search_index_avg_7d": as_float(metric.search_index_avg_7d),
        "search_index_avg_30d": as_float(metric.search_index_avg_30d),
        "search_index_avg_90d": as_float(metric.search_index_avg_90d),
        "search_growth_7d_pct": as_float(metric.search_growth_7d_pct),
        "search_growth_30d_pct": as_float(metric.search_growth_30d_pct),
        "search_growth_90d_pct": as_float(metric.search_growth_90d_pct),
        "growth_reasons": {
            "d7": metric.growth_reason_7d,
            "d30": metric.growth_reason_30d,
            "d90": metric.growth_reason_90d,
        },
        "market_listing_count": metric.market_listing_count,
        "market_avg_price": money(metric.market_avg_price),
        "market_price_p25": money(metric.market_price_p25),
        "market_price_p75": money(metric.market_price_p75),
        "review_velocity_30d": as_float(metric.review_velocity_30d),
        "competition_index": as_float(metric.competition_index),
        "competition_class": metric.competition_class,
        "competition_coverage": as_float(metric.competition_coverage),
        "seasonality_index": as_float(metric.seasonality_index),
        "trend_direction": metric.trend_direction,
        "data_coverage_pct": round(float(metric.data_coverage_pct), 2),
        "confidence": round(float(metric.confidence), 3),
        "synthetic_share": round(float(metric.synthetic_share), 3),
        "computed_at": metric.computed_at,
    }


@router.get("/{identifier}/metrics")
def product_metrics(identifier: str, user: CurrentUser, db: DbSession, limit: int = 90) -> dict:
    row = _require_row(db, identifier)
    rows = db.execute(
        select(ProductMetric)
        .where(ProductMetric.product_id == row.product.id)
        .order_by(ProductMetric.as_of_date.desc())
        .limit(max(1, min(limit, 365)))
    ).scalars().all()
    return {"product_id": row.product.id, "metrics": [_metric_payload(m) for m in rows]}


@router.get("/{identifier}/score")
def product_score(
    identifier: str, user: CurrentUser, db: DbSession, history: bool = False
) -> dict:
    from app.services.catalog import profile_for_score

    row = _require_row(db, identifier)
    if row.score is None:
        return {"product_id": row.product.id, "score": None, "reason": "insufficient_data"}
    profile = profile_for_score(db, row.score)
    payload = {"product_id": row.product.id, "score": score_breakdown(row.score, profile)}
    if history:
        rows = db.execute(
            select(OpportunityScore)
            .where(OpportunityScore.product_id == row.product.id)
            .order_by(OpportunityScore.calculated_on.desc())
            .limit(90)
        ).scalars()
        payload["history"] = [
            score_breakdown(item, profile_for_score(db, item)) for item in rows
        ]
    return payload


@router.get("/{identifier}/listings")
def product_listings(identifier: str, user: CurrentUser, db: DbSession) -> dict:
    row = _require_row(db, identifier)
    return {"product_id": row.product.id, "listings": _listings(db, row.product.id)}


@router.get("/{identifier}/competition")
def product_competition(identifier: str, user: CurrentUser, db: DbSession) -> dict:
    row = _require_row(db, identifier)
    return _competition(db, row) or {
        "product_id": row.product.id,
        "index": None,
        "classification": "unknown",
        "coverage": 0.0,
        "evidence": {},
        "unavailable": ["all"],
        "caveats": ["No metrics computed for this product yet."],
        "classified_at": None,
    }


@router.get("/{identifier}/suppliers")
def product_suppliers(identifier: str, user: CurrentUser, db: DbSession) -> dict:
    row = _require_row(db, identifier)
    return {"product_id": row.product.id, "suppliers": _suppliers(db, row.product.id)}
