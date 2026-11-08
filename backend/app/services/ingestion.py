"""Ingestion pipeline.

A run is: fetch a connector dataset -> upsert products, keywords, observations,
listings and supplier offers -> recompute metrics and scores -> close the run.

Upserts are keyed on the natural keys in the schema, so running the same sync
twice writes nothing new the second time. That is what makes the mock demo
reproducible and what the idempotency test asserts.
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.base import (
    ConnectorContext,
    ConnectorDataset,
    TrackedProduct,
    infer_metric_type,
)
from app.connectors.catalog import CATEGORIES
from app.connectors.framework import ConnectorError, ConnectorUnavailable
from app.connectors.mock import build_mock_dataset
from app.connectors.registry import get_connector
from app.core.config import settings
from app.models import (
    Category,
    DataSource,
    IngestionRun,
    MarketplaceListing,
    Product,
    ProductKeyword,
    Supplier,
    SupplierProduct,
    TrendObservation,
    utcnow,
)
from app.services.metrics import compute_all_metrics
from app.services.normalise import normalise_name
from app.services.scoring_service import compute_all_scores
from app.services.slugs import unique_product_slug
from app.services.snapshots import store_snapshot

CHUNK = 2000


def get_source(db: Session, provider_key: str) -> DataSource | None:
    return db.execute(
        select(DataSource).where(DataSource.provider_key == provider_key)
    ).scalar_one_or_none()


def _ensure_categories(db: Session) -> dict[str, Category]:
    existing = {c.slug: c for c in db.execute(select(Category)).scalars()}
    for slug, name in CATEGORIES:
        if slug not in existing:
            category = Category(name=name, slug=slug, path=slug, level=0)
            db.add(category)
            db.flush()
            existing[slug] = category
    return existing


def _unique_slug(db: Session, base: str, external_id: str) -> str:
    return unique_product_slug(db, base, external_id)


def _upsert_product(
    db: Session,
    source: DataSource,
    candidate,
    categories: dict[str, Category],
) -> tuple[Product, bool]:
    product = db.execute(
        select(Product).where(
            Product.source_id == source.id,
            Product.external_id == candidate.external_id,
        )
    ).scalar_one_or_none()

    category = categories.get(candidate.category_slug)
    created = False
    if product is None:
        product = Product(
            external_id=candidate.external_id,
            source_id=source.id,
            name=candidate.name,
            normalised_name=normalise_name(candidate.name),
            slug=_unique_slug(db, candidate.name, candidate.external_id),
            description=candidate.description,
            category_id=category.id if category else None,
            brand=candidate.brand,
            country="AU",
            currency="AUD",
            status="active",
            is_synthetic=bool(candidate.is_synthetic),
            first_seen_at=candidate.first_seen_at or utcnow(),
        )
        db.add(product)
        db.flush()
        created = True
    else:
        product.name = candidate.name
        product.normalised_name = normalise_name(candidate.name)
        product.description = candidate.description or product.description
        product.brand = candidate.brand or product.brand
        if category is not None:
            product.category_id = category.id
        product.is_synthetic = bool(candidate.is_synthetic)
        if candidate.first_seen_at and product.first_seen_at is None:
            product.first_seen_at = candidate.first_seen_at
    product.last_seen_at = utcnow()

    existing_keywords = set(
        db.execute(
            select(ProductKeyword.normalised_keyword).where(
                ProductKeyword.product_id == product.id,
                ProductKeyword.source_id == source.id,
            )
        ).scalars()
    )
    for keyword in candidate.keywords:
        normalised = normalise_name(keyword) or keyword.lower()
        if not normalised or normalised in existing_keywords:
            continue
        db.add(
            ProductKeyword(
                product_id=product.id,
                keyword=keyword,
                normalised_keyword=normalised,
                source_id=source.id,
            )
        )
        existing_keywords.add(normalised)
    return product, created


def _insert_observations(
    db: Session,
    source: DataSource,
    run: IngestionRun,
    dataset,
    product_map: dict[str, Product],
) -> tuple[int, int, int]:
    """Insert new observations and revise changed ones.

    Returns ``(added, updated, rejected)``. The natural key stays stable, so a
    repeated sync does not duplicate rows. When a provider corrects a value for
    the same key, the current row is updated, ``revision`` is incremented and
    the prior value is kept in ``metadata.previous_values`` (bounded). The
    immutable ``provider_snapshots`` archive retains the full earlier payload.
    """
    existing = {
        (
            row.product_id,
            row.observation_date,
            row.metric_name,
            row.granularity,
        ): row
        for row in db.execute(
            select(TrendObservation).where(TrendObservation.source_id == source.id)
        ).scalars()
    }
    added = 0
    updated = 0
    rejected = 0
    pending: list[TrendObservation] = []
    for point in dataset.observations:
        product = product_map.get(point.external_id)
        if product is None:
            rejected += 1
            continue
        key = (product.id, point.observation_date, point.metric_name, point.granularity)
        metric_type = point.metric_type or infer_metric_type(point.metric_name)
        verification = (
            "synthetic" if source.is_synthetic else point.verification_status
        )
        quality = "synthetic" if source.is_synthetic else point.data_quality
        row = existing.get(key)
        if row is not None:
            new_value = float(point.metric_value)
            old_value = float(row.metric_value)
            if abs(new_value - old_value) < 1e-9:
                continue
            previous = list((row.meta or {}).get("previous_values") or [])
            previous.append(
                {
                    "value": old_value,
                    "at": utcnow().isoformat(),
                    "ingestion_run_id": str(run.id),
                }
            )
            row.metric_value = new_value
            row.metric_type = metric_type
            row.unit = point.unit
            row.period_start = point.period_start or point.observation_date
            row.period_end = point.period_end or point.observation_date
            row.source_url = point.source_url
            row.verification_status = verification
            row.data_quality = quality
            row.original_metric = point.original_metric
            row.confidence = point.confidence
            row.source_timestamp = point.source_timestamp or utcnow()
            row.collected_at = utcnow()
            row.ingestion_run_id = run.id
            row.revision = int(row.revision or 1) + 1
            row.updated_at = utcnow()
            row.meta = {
                **(row.meta or {}),
                "previous_values": previous[-5:],
            }
            updated += 1
            continue
        pending.append(
            TrendObservation(
                product_id=product.id,
                source_id=source.id,
                ingestion_run_id=run.id,
                observation_date=point.observation_date,
                granularity=point.granularity,
                metric_name=point.metric_name,
                metric_type=metric_type,
                metric_value=point.metric_value,
                unit=point.unit,
                country="AU",
                currency="AUD" if point.unit == "aud" else None,
                provider_name=source.provider_name,
                period_start=point.period_start or point.observation_date,
                period_end=point.period_end or point.observation_date,
                source_url=point.source_url,
                verification_status=verification,
                data_quality=quality,
                original_metric=point.original_metric,
                confidence=point.confidence,
                is_synthetic=bool(source.is_synthetic),
                source_timestamp=point.source_timestamp or utcnow(),
                collected_at=utcnow(),
                revision=1,
                meta=point.meta or {},
            )
        )
        existing[key] = pending[-1]
        added += 1
        if len(pending) >= CHUNK:
            db.add_all(pending)
            db.flush()
            pending = []
    if pending:
        db.add_all(pending)
        db.flush()
    return added, updated, rejected


def _upsert_listings(
    db: Session, source: DataSource, dataset, product_map: dict[str, Product]
) -> tuple[int, int]:
    ids = [record.listing_id for record in dataset.listings]
    if not ids:
        return 0, 0

    existing = {
        (row.marketplace, row.external_listing_id): row
        for row in db.execute(
            select(MarketplaceListing).where(
                MarketplaceListing.source_id == source.id,
                MarketplaceListing.external_listing_id.in_(ids),
            )
        ).scalars()
    }
    written = 0
    rejected = 0
    for record in dataset.listings:
        product = product_map.get(record.external_id)
        if product is None:
            rejected += 1
            continue
        listing = existing.get((record.marketplace, record.listing_id))
        if listing is None:
            listing = MarketplaceListing(
                product_id=product.id,
                marketplace=record.marketplace,
                source_id=source.id,
                external_listing_id=record.listing_id,
                first_seen_at=utcnow(),
            )
            db.add(listing)
            existing[(record.marketplace, record.listing_id)] = listing
            written += 1
        listing.title = record.title
        listing.seller_name = record.seller_name
        listing.price = record.price
        listing.rating = record.rating
        listing.review_count = record.review_count
        listing.listing_url = record.listing_url or None
        listing.last_seen_at = utcnow()
    db.flush()
    return written, rejected


def _upsert_suppliers(
    db: Session, source: DataSource, dataset
) -> tuple[dict[str, Supplier], int]:
    existing = {
        (s.platform_key, s.supplier_name): s
        for s in db.execute(select(Supplier)).scalars()
    }
    written = 0
    for record in dataset.suppliers:
        supplier = existing.get((record.platform_key, record.supplier_name))
        if supplier is None:
            supplier = Supplier(
                supplier_name=record.supplier_name,
                platform_key=record.platform_key,
                source_id=source.id,
                is_synthetic=bool(source.is_synthetic),
            )
            db.add(supplier)
            existing[(record.platform_key, record.supplier_name)] = supplier
            written += 1
        supplier.country = record.country
        supplier.supplier_rating = record.rating
        supplier.supplier_url = record.url or None
    db.flush()
    return {name: supplier for (_key, name), supplier in existing.items()}, written


def _upsert_offers(
    db: Session,
    dataset,
    product_map: dict[str, Product],
    supplier_map: dict[str, Supplier],
) -> tuple[int, int]:
    if not dataset.offers:
        return 0, 0
    supplier_ids = [s.id for s in supplier_map.values()]
    external_ids = [record.external_product_id for record in dataset.offers]
    existing = {
        (row.supplier_id, row.external_product_id): row
        for row in db.execute(
            select(SupplierProduct).where(
                SupplierProduct.supplier_id.in_(supplier_ids),
                SupplierProduct.external_product_id.in_(external_ids),
            )
        ).scalars()
    }
    written = 0
    rejected = 0
    for record in dataset.offers:
        product = product_map.get(record.external_id)
        supplier = supplier_map.get(record.supplier_name)
        if product is None or supplier is None:
            rejected += 1
            continue
        offer = existing.get((supplier.id, record.external_product_id))
        if offer is None:
            offer = SupplierProduct(
                product_id=product.id,
                supplier_id=supplier.id,
                external_product_id=record.external_product_id,
            )
            db.add(offer)
            existing[(supplier.id, record.external_product_id)] = offer
            written += 1
        offer.product_cost = record.product_cost
        offer.shipping_cost = record.shipping_cost
        offer.minimum_order_quantity = record.minimum_order_quantity
        offer.lead_time_days = record.lead_time_days
        offer.availability = record.availability
        offer.currency = "AUD"
        offer.last_checked_at = utcnow()
    db.flush()
    return written, rejected


def _mark_failed(db: Session, run_id: UUID, source_id: UUID, exc: Exception) -> None:
    db.rollback()
    run = db.get(IngestionRun, run_id)
    source = db.get(DataSource, source_id)
    if isinstance(exc, ConnectorError):
        message = str(exc)[:1000]
    else:
        message = f"{type(exc).__name__}: {exc}"[:1000]
    if run is not None:
        run.status = "failed"
        run.finished_at = utcnow()
        run.error_count = (run.error_count or 0) + 1
        run.error_summary = message
    if source is not None:
        source.sync_status = "error"
        source.last_error = message
        source.consecutive_failures = (source.consecutive_failures or 0) + 1
    db.commit()


def _bump_usage(source: DataSource, request_count: int) -> None:
    """Track monthly provider usage for the cost-visibility page."""
    period = date.today().strftime("%Y-%m")
    if source.usage_period != period:
        source.usage_period = period
        source.requests_used_month = 0
    source.requests_used_month = (source.requests_used_month or 0) + max(
        0, int(request_count or 0)
    )


def _write_dataset(
    db: Session,
    source: DataSource,
    run: IngestionRun,
    dataset: ConnectorDataset,
    *,
    as_of: date,
    seed_product_map: dict[str, Product] | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
) -> dict[str, int]:
    """Upsert a normalised connector dataset and recompute derived snapshots."""
    categories = _ensure_categories(db)
    product_map: dict[str, Product] = dict(seed_product_map or {})
    created_products = 0
    rejected = 0
    for candidate in dataset.products:
        product, created = _upsert_product(db, source, candidate, categories)
        product_map[candidate.external_id] = product
        created_products += int(created)
    db.commit()

    observations_added, observations_updated, obs_rejected = _insert_observations(
        db, source, run, dataset, product_map
    )
    rejected += obs_rejected
    db.commit()

    snapshot = store_snapshot(
        db,
        source,
        run,
        dataset,
        period_start=period_start or as_of,
        period_end=period_end or as_of,
    )
    db.commit()

    listings_added, listing_rejected = _upsert_listings(db, source, dataset, product_map)
    rejected += listing_rejected
    supplier_map, suppliers_added = _upsert_suppliers(db, source, dataset)
    offers_added, offer_rejected = _upsert_offers(db, dataset, product_map, supplier_map)
    rejected += offer_rejected
    db.commit()

    compute_all_metrics(db, as_of)
    compute_all_scores(db, as_of)

    return {
        "created_products": created_products,
        "observations": observations_added,
        "observations_updated": observations_updated,
        "listings": listings_added,
        "suppliers": suppliers_added,
        "offers": offers_added,
        "rejected": rejected,
        "snapshot_id": str(snapshot.id),
        "snapshot_truncated": int(snapshot.truncated),
    }


def _finish_run(
    db: Session,
    run: IngestionRun,
    source: DataSource,
    counts: dict[str, int],
    *,
    request_count: int = 0,
    warnings: list[str] | None = None,
    extra_cursor: dict | None = None,
) -> None:
    run.status = "success"
    run.finished_at = utcnow()
    run.records_written = (
        counts["created_products"]
        + counts["observations"]
        + counts["listings"]
        + counts["suppliers"]
        + counts["offers"]
    )
    run.records_updated = counts.get("observations_updated", 0)
    run.records_rejected = counts["rejected"]
    run.error_count = 0
    run.error_summary = None
    cursor = dict(extra_cursor or {})
    if warnings:
        cursor["warnings"] = warnings[:20]
    if counts.get("snapshot_id"):
        cursor["snapshot_id"] = counts["snapshot_id"]
        cursor["snapshot_truncated"] = bool(counts.get("snapshot_truncated"))
    if cursor:
        run.cursor = cursor
    source.last_sync_at = utcnow()
    source.last_success_at = source.last_sync_at
    source.sync_status = "ok"
    source.last_error = None
    source.consecutive_failures = 0
    _bump_usage(source, request_count)
    db.commit()


def run_mock_sync(
    db: Session,
    source: DataSource | None = None,
    as_of: date | None = None,
    product_limit: int | None = None,
    history_days: int | None = None,
) -> IngestionRun:
    from app.core.config import settings

    as_of = as_of or date.today()
    source = source or get_source(db, "mock")
    if source is None:
        raise RuntimeError("Mock data source is not configured; run the seed first.")

    run = IngestionRun(source_id=source.id, job_name="sync.mock", status="running")
    db.add(run)
    db.commit()
    run_id, source_id = run.id, source.id

    try:
        history = max(1, history_days or settings.mock_history_days)
        dataset = build_mock_dataset(
            as_of=as_of,
            product_limit=product_limit or settings.mock_product_limit,
            history_days=history,
        )
        run.records_fetched = (
            len(dataset.products)
            + len(dataset.observations)
            + len(dataset.listings)
            + len(dataset.suppliers)
            + len(dataset.offers)
        )
        db.commit()

        counts = _write_dataset(
            db,
            source,
            run,
            dataset,
            as_of=as_of,
            period_start=as_of - timedelta(days=history - 1),
            period_end=as_of,
        )
        _finish_run(db, run, source, counts)
    except Exception as exc:  # noqa: BLE001 - the run record must capture any failure
        _mark_failed(db, run_id, source_id, exc)
        raise
    return run


def _tracked_products(
    db: Session, country: str = "AU", limit: int = 200
) -> tuple[TrackedProduct, ...]:
    products = (
        db.execute(
            select(Product)
            .where(Product.status == "active", Product.country == country)
            .order_by(Product.first_seen_at.desc())
            .limit(max(1, min(limit, 1000)))
        )
        .scalars()
        .all()
    )
    if not products:
        return ()
    keywords: dict = {}
    for product_id, keyword in db.execute(
        select(ProductKeyword.product_id, ProductKeyword.keyword).where(
            ProductKeyword.product_id.in_([product.id for product in products])
        )
    ).all():
        keywords.setdefault(product_id, []).append(keyword)
    return tuple(
        TrackedProduct(
            id=product.id,
            external_id=product.external_id or product.slug,
            name=product.name,
            keywords=tuple(keywords.get(product.id, ())),
        )
        for product in products
    )


def run_connector_sync(
    db: Session,
    source: DataSource,
    *,
    as_of: date | None = None,
) -> IngestionRun:
    """Run an installed connector plugin and record full provenance."""
    connector = get_connector(source.provider_key)
    if connector is None:
        raise RuntimeError(
            f"No connector plugin is installed for provider '{source.provider_key}'."
        )
    status = connector.get_source_status(source)
    if not status.available:
        raise ConnectorUnavailable(status.reason or "Source is not available.")

    as_of = as_of or date.today()
    run = IngestionRun(
        source_id=source.id,
        job_name=f"sync.{source.provider_key}",
        status="running",
    )
    db.add(run)
    db.commit()
    run_id, source_id = run.id, source.id

    try:
        try:
            history_days = int((source.config or {}).get("history_days") or 30)
        except (TypeError, ValueError):
            history_days = 30
        tracked = _tracked_products(
            db,
            country=str((source.config or {}).get("geo") or "AU"),
            limit=int((source.config or {}).get("max_tracked_products") or 200),
        )
        ctx = ConnectorContext(
            source=source,
            config=dict(source.config or {}),
            since=as_of - timedelta(days=max(1, min(history_days, 365))),
            until=as_of,
            products=tracked,
        )
        try:
            retry_attempts = int(
                (source.config or {}).get("retry_attempts")
                or settings.connector_retry_attempts
            )
        except (TypeError, ValueError):
            retry_attempts = settings.connector_retry_attempts
        retry_attempts = max(1, min(retry_attempts, 5))
        try:
            backoff = float(
                (source.config or {}).get("retry_backoff_seconds")
                or settings.connector_retry_backoff_seconds
            )
        except (TypeError, ValueError):
            backoff = settings.connector_retry_backoff_seconds
        backoff = max(0.0, min(backoff, 30.0))

        dataset = None
        retry_cursor: dict = {}
        for attempt in range(1, retry_attempts + 1):
            try:
                dataset = connector.run(ctx)
                if attempt > 1:
                    retry_cursor["succeeded_after_attempt"] = attempt
                break
            except ConnectorError as exc:
                info = connector.handle_errors(exc)
                if not info.retryable or attempt >= retry_attempts:
                    raise
                retry_cursor = {
                    "retry_attempts": attempt,
                    "retry_code": info.code,
                    "retry_message": info.message[:500],
                }
                db.rollback()
                time.sleep(backoff * (2 ** (attempt - 1)))
        if dataset is None:  # pragma: no cover - the loop raises instead
            raise ConnectorError("Connector returned no dataset.")
        run.records_fetched = (
            len(dataset.products)
            + len(dataset.observations)
            + len(dataset.listings)
            + len(dataset.suppliers)
            + len(dataset.offers)
        )
        db.commit()

        seed_map: dict[str, Product] = {}
        for tracked_product in tracked:
            product = db.get(Product, tracked_product.id)
            if product is not None:
                seed_map[tracked_product.external_id] = product

        counts = _write_dataset(
            db,
            source,
            run,
            dataset,
            as_of=as_of,
            seed_product_map=seed_map,
            period_start=ctx.since,
            period_end=ctx.until,
        )
        _finish_run(
            db,
            run,
            source,
            counts,
            request_count=dataset.request_count,
            warnings=dataset.warnings,
            extra_cursor=retry_cursor,
        )
    except Exception as exc:  # noqa: BLE001 - the run record must capture any failure
        _mark_failed(db, run_id, source_id, exc)
        raise
    return run


def latest_run(db: Session, source: DataSource | None = None) -> IngestionRun | None:
    query = select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(1)
    if source is not None:
        query = query.where(IngestionRun.source_id == source.id)
    return db.execute(query).scalar_one_or_none()
