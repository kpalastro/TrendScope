from __future__ import annotations

import csv
import io
import math
from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, File, Query, Response, UploadFile
from sqlalchemy import select

from app.api.deps import AdminUser, CurrentUser, DbSession, WriteUser
from app.connectors.csv_source import OBSERVATION_COLUMNS, CSVImportConnector
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
from app.schemas import (
    ObservationCorrect,
    ObservationCreate,
    ProductCreate,
    ProductPatch,
    SupplierOfferCreate,
    SupplierOfferPatch,
)
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
from app.services.presenters import (
    DISCLAIMER,
    as_float,
    keywords,
    money,
    product_sources,
    score_breakdown,
    trend_series,
)
from app.services.recommendations import build_recommendation, cheapest_offer
from app.services.scoring_service import compute_product_score, get_active_profile
from app.services.slugs import unique_external_id, unique_product_slug

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


def _recompute(db, product: Product, as_of: date | None = None) -> None:
    as_of = as_of or date.today()
    metric = compute_product_metrics(db, product, as_of)
    profile = get_active_profile(db)
    if profile is not None:
        compute_product_score(db, product, metric, profile, as_of)


def _recommendation(db, row) -> dict:
    offer, supplier = cheapest_offer(db, row.product.id)
    return build_recommendation(
        row.product, row.metric, row.score, offer, supplier
    )


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
            "recommendation": _recommendation(db, row),
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


def _manual_source(db) -> DataSource:
    source = db.execute(
        select(DataSource).where(DataSource.provider_key == "csv_import")
    ).scalar_one_or_none()
    if source is None:
        raise ApiError(
            503, "SOURCE_UNAVAILABLE", "The manual CSV / research source is not configured."
        )
    return source


def _observation_payload(observation: TrendObservation) -> dict:
    return {
        "id": observation.id,
        "product_id": observation.product_id,
        "source_id": observation.source_id,
        "metric_name": observation.metric_name,
        "metric_type": observation.metric_type,
        "value": as_float(observation.metric_value),
        "unit": observation.unit,
        "granularity": observation.granularity,
        "observation_date": observation.observation_date,
        "period_start": observation.period_start,
        "period_end": observation.period_end,
        "country": observation.country,
        "currency": observation.currency,
        "provider_name": observation.provider_name,
        "source_url": observation.source_url,
        "verification_status": observation.verification_status,
        "data_quality": observation.data_quality,
        "original_metric": observation.original_metric,
        "confidence": round(float(observation.confidence), 3),
        "is_synthetic": bool(observation.is_synthetic),
        "collected_at": observation.collected_at,
        "notes": (observation.meta or {}).get("notes"),
    }


def _product_lookup(db) -> tuple[dict[str, Product], dict[str, Product]]:
    """Map product names/slugs/external ids to products, and the reverse."""
    products = (
        db.execute(select(Product).where(Product.status == "active")).scalars().all()
    )
    by_key: dict[str, Product] = {}
    by_external: dict[str, Product] = {}
    for product in products:
        external = product.external_id or product.slug
        by_external[external] = product
        for key in (product.name, product.slug, external):
            if key:
                by_key[str(key).lower()] = product
    return by_key, by_external


@router.get("/import/observations/template")
def observation_template(user: CurrentUser) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(OBSERVATION_COLUMNS)
    writer.writerow(
        [
            "Silicone Kitchen Organisation Tray",
            "search_interest",
            "search_interest",
            "52",
            "index",
            date.today().isoformat(),
            "",
            "",
            "https://trends.google.com/trends/explore?geo=AU",
            "unverified",
            "medium",
            "Google Trends export, transcribed by hand",
        ]
    )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="trendscope-observations-template.csv"'
        },
    )


@router.post("/import/observations/csv", status_code=202)
async def import_observations_csv(
    user: WriteUser,
    db: DbSession,
    file: UploadFile = File(...),
) -> dict:
    """Import operator-supplied research observations (manual free fallback).

    Every row keeps its declared metric type, verification status and source URL;
    nothing is presented as a live measurement. Unknown products and invalid
    rows are rejected with their row number instead of being dropped.
    """
    source = _manual_source(db)
    raw = await file.read(MAX_CSV_BYTES + 1)
    if len(raw) > MAX_CSV_BYTES:
        raise ApiError(422, "BUSINESS_RULE_VIOLATION", "CSV file exceeds 2 MB.")
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ApiError(422, "VALIDATION_ERROR", "CSV must be UTF-8 encoded.") from exc

    try:
        reader = csv.DictReader(io.StringIO(content))
        raw_rows = list(reader)
    except csv.Error as exc:
        raise ApiError(422, "VALIDATION_ERROR", f"Could not read CSV: {exc}") from exc
    if not raw_rows:
        raise ApiError(422, "VALIDATION_ERROR", "CSV contains no data rows.")

    rows = [
        {(key or "").strip().lower(): (value or "").strip() for key, value in raw.items()}
        for raw in raw_rows
    ]
    by_key, by_external = _product_lookup(db)
    external_id_for = {
        key: (product.external_id or product.slug) for key, product in by_key.items()
    }
    connector = CSVImportConnector()
    records, errors = connector.observations_from_rows(
        rows, external_id_for=external_id_for
    )

    existing = {
        (
            item.product_id,
            item.observation_date,
            item.metric_name,
            item.granularity,
        )
        for item in db.execute(
            select(TrendObservation).where(TrendObservation.source_id == source.id)
        ).scalars()
    }
    created = 0
    skipped = 0
    touched: set = set()
    for record in records:
        product = by_external.get(record.external_id)
        if product is None:
            errors.append(
                {"row": None, "issue": f"unknown product: {record.external_id}"}
            )
            continue
        key = (
            product.id,
            record.observation_date,
            record.metric_name,
            record.granularity,
        )
        if key in existing:
            skipped += 1
            continue
        existing.add(key)
        db.add(
            TrendObservation(
                product_id=product.id,
                source_id=source.id,
                observation_date=record.observation_date,
                granularity=record.granularity,
                metric_name=record.metric_name,
                metric_type=record.metric_type or "other",
                metric_value=record.metric_value,
                unit=record.unit,
                country="AU",
                currency="AUD" if record.unit == "aud" else None,
                provider_name=source.provider_name,
                period_start=record.period_start or record.observation_date,
                period_end=record.period_end or record.observation_date,
                source_url=record.source_url,
                verification_status=record.verification_status,
                data_quality=record.data_quality,
                original_metric=record.original_metric,
                confidence=record.confidence,
                is_synthetic=False,
                source_timestamp=utcnow(),
                collected_at=utcnow(),
                meta=record.meta or {},
            )
        )
        touched.add(product.id)
        created += 1

    db.flush()
    for product_id in touched:
        product = db.get(Product, product_id)
        if product is not None:
            _recompute(db, product)
    if created:
        source.last_success_at = utcnow()
    db.commit()
    return {
        "created": created,
        "skipped": skipped,
        "rejected": len(errors),
        "errors": errors,
    }


@router.get("/{identifier}/observations")
def product_observations(
    identifier: str,
    user: CurrentUser,
    db: DbSession,
    metric_type: str | None = None,
    limit: int = 500,
) -> dict:
    row = _require_row(db, identifier)
    stmt = (
        select(TrendObservation)
        .where(TrendObservation.product_id == row.product.id)
        .order_by(TrendObservation.observation_date.desc(), TrendObservation.id.desc())
        .limit(max(1, min(limit, 2000)))
    )
    if metric_type:
        stmt = stmt.where(TrendObservation.metric_type == metric_type)
    observations = db.execute(stmt).scalars().all()
    return {
        "product_id": row.product.id,
        "observations": [_observation_payload(item) for item in observations],
    }


@router.post("/{identifier}/observations", status_code=201)
def create_product_observation(
    identifier: str,
    payload: ObservationCreate,
    user: WriteUser,
    db: DbSession,
) -> dict:
    row = _require_row(db, identifier)
    source = _manual_source(db)
    country = (payload.country or row.product.country or "AU").upper()
    existing = db.execute(
        select(TrendObservation).where(
            TrendObservation.product_id == row.product.id,
            TrendObservation.source_id == source.id,
            TrendObservation.observation_date == payload.observation_date,
            TrendObservation.metric_name == payload.metric_name,
            TrendObservation.granularity == payload.granularity,
            TrendObservation.country == country,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ApiError(
            409,
            "CONFLICT",
            "An observation already exists for this metric, date, granularity and country. "
            f"Correct observation {existing.id} instead of adding a duplicate.",
        )
    observation = TrendObservation(
        product_id=row.product.id,
        source_id=source.id,
        observation_date=payload.observation_date,
        granularity=payload.granularity,
        metric_name=payload.metric_name,
        metric_type=payload.metric_type,
        metric_value=payload.value,
        unit=payload.unit,
        country=country,
        currency=payload.currency or (row.product.currency if payload.metric_type == "marketplace_price" else None),
        provider_name=payload.provider_name,
        period_start=payload.period_start or payload.observation_date,
        period_end=payload.period_end or payload.observation_date,
        source_url=payload.source_url,
        verification_status=payload.verification_status,
        data_quality=payload.data_quality,
        original_metric=payload.original_metric or payload.metric_name,
        confidence=payload.confidence,
        is_synthetic=False,
        source_timestamp=utcnow(),
        collected_at=utcnow(),
        meta={"origin": "manual_entry", "notes": payload.notes},
    )
    db.add(observation)
    db.flush()
    _recompute(db, row.product)
    source.last_success_at = utcnow()
    db.commit()
    fresh = _require_row(db, row.product.id)
    return {
        "observation": _observation_payload(observation),
        "recommendation": _recommendation(db, fresh),
    }


@router.patch("/{identifier}/observations/{observation_id}")
def correct_product_observation(
    identifier: str,
    observation_id: int,
    payload: ObservationCorrect,
    user: WriteUser,
    db: DbSession,
) -> dict:
    row = _require_row(db, identifier)
    observation = db.get(TrendObservation, observation_id)
    if observation is None or observation.product_id != row.product.id:
        raise ApiError(404, "NOT_FOUND", "Observation not found for this product.")
    source = db.get(DataSource, observation.source_id)
    if source is None or source.provider_key != "csv_import":
        raise ApiError(
            409,
            "BUSINESS_RULE_VIOLATION",
            "Only operator-entered observations can be corrected; connector history is append-only.",
        )
    changes = {
        key: value
        for key, value in payload.model_dump(exclude_none=True).items()
        if key in {"value", "verification_status", "data_quality", "source_url", "notes", "reason"}
    }
    if not changes:
        raise ApiError(422, "VALIDATION_ERROR", "No correction fields were supplied.")
    meta = dict(observation.meta or {})
    corrections = list(meta.get("corrections") or [])
    corrections.append(
        {
            "at": utcnow().isoformat(),
            "previous_value": as_float(observation.metric_value),
            "previous_verification": observation.verification_status,
            **{key: str(value) for key, value in changes.items()},
        }
    )
    meta["corrections"] = corrections
    observation.meta = meta
    if payload.value is not None:
        observation.metric_value = payload.value
    if payload.verification_status is not None:
        observation.verification_status = payload.verification_status
    if payload.data_quality is not None:
        observation.data_quality = payload.data_quality
    if payload.source_url is not None:
        observation.source_url = payload.source_url
    if payload.notes is not None:
        meta["notes"] = payload.notes
    observation.collected_at = utcnow()
    db.flush()
    _recompute(db, row.product)
    db.commit()
    fresh = _require_row(db, row.product.id)
    return {
        "observation": _observation_payload(observation),
        "recommendation": _recommendation(db, fresh),
    }


@router.post("/{identifier}/suppliers", status_code=201)
def add_product_supplier(
    identifier: str,
    payload: SupplierOfferCreate,
    user: WriteUser,
    db: DbSession,
) -> dict:
    """Record a supplier quote — the evidence the recommendation workflow needs."""
    row = _require_row(db, identifier)
    source = _manual_source(db)
    supplier = db.execute(
        select(Supplier).where(
            Supplier.platform_key == payload.platform_key,
            Supplier.supplier_name == payload.supplier_name,
        )
    ).scalar_one_or_none()
    created_supplier = False
    if supplier is None:
        supplier = Supplier(
            supplier_name=payload.supplier_name,
            platform_key=payload.platform_key,
            source_id=source.id,
            is_synthetic=False,
        )
        db.add(supplier)
        db.flush()
        created_supplier = True
    supplier.supplier_url = payload.supplier_url or supplier.supplier_url
    supplier.country = (payload.country or supplier.country or "").upper() or None
    if payload.supplier_rating is not None:
        supplier.supplier_rating = payload.supplier_rating
    supplier.source_id = source.id

    external_id = payload.external_product_id or f"manual-{row.product.slug}"
    offer = db.execute(
        select(SupplierProduct).where(
            SupplierProduct.supplier_id == supplier.id,
            SupplierProduct.external_product_id == external_id,
        )
    ).scalar_one_or_none()
    created = False
    if offer is None:
        offer = SupplierProduct(
            product_id=row.product.id,
            supplier_id=supplier.id,
            external_product_id=external_id,
        )
        db.add(offer)
        created = True
    offer.supplier_url = payload.supplier_url or offer.supplier_url
    offer.product_cost = payload.product_cost
    offer.shipping_cost = payload.shipping_cost
    offer.currency = payload.currency.upper()
    offer.minimum_order_quantity = payload.minimum_order_quantity
    offer.lead_time_days = payload.lead_time_days
    offer.availability = payload.availability
    offer.last_checked_at = utcnow()
    db.flush()
    _recompute(db, row.product)
    source.last_success_at = utcnow()
    db.commit()
    fresh = _require_row(db, row.product.id)
    return {
        "created": created,
        "supplier_created": created_supplier,
        "suppliers": _suppliers(db, row.product.id),
        "recommendation": _recommendation(db, fresh),
    }


@router.patch("/{identifier}/suppliers/{offer_id}")
def patch_product_supplier(
    identifier: str,
    offer_id: UUID,
    payload: SupplierOfferPatch,
    user: WriteUser,
    db: DbSession,
) -> dict:
    row = _require_row(db, identifier)
    offer = db.get(SupplierProduct, offer_id)
    if offer is None or offer.product_id != row.product.id:
        raise ApiError(404, "NOT_FOUND", "Supplier offer not found for this product.")
    supplier = db.get(Supplier, offer.supplier_id)
    if supplier is None:
        raise ApiError(404, "NOT_FOUND", "Supplier not found.")

    if payload.supplier_name is not None and payload.supplier_name != supplier.supplier_name:
        clash = db.execute(
            select(Supplier.id).where(
                Supplier.platform_key == supplier.platform_key,
                Supplier.supplier_name == payload.supplier_name,
            )
        ).first()
        if clash is not None:
            raise ApiError(409, "CONFLICT", "A supplier with this name already exists.")
        supplier.supplier_name = payload.supplier_name

    for field in ("supplier_url", "country", "supplier_rating"):
        value = getattr(payload, field)
        if value is not None:
            setattr(supplier, field, value.upper() if field == "country" else value)
    for field in (
        "product_cost",
        "shipping_cost",
        "currency",
        "minimum_order_quantity",
        "lead_time_days",
        "availability",
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(offer, field, value.upper() if field == "currency" else value)
    offer.last_checked_at = utcnow()
    db.flush()
    _recompute(db, row.product)
    db.commit()
    fresh = _require_row(db, row.product.id)
    return {
        "suppliers": _suppliers(db, row.product.id),
        "recommendation": _recommendation(db, fresh),
    }


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
