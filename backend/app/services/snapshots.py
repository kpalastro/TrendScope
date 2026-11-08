"""Immutable provider snapshots and history retention.

``trend_observations`` answers "what do we currently believe?"; a snapshot
answers "what did the provider actually return during this run?". The two are
kept separate so a later provider correction updates the current view without
erasing the earlier evidence.

Snapshots are normalised records, not raw HTTP bodies: credentials, cursor
tokens and provider headers never reach the archive.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.connectors.base import ConnectorDataset
from app.core.config import settings
from app.models import DataSource, IngestionRun, ProviderSnapshot, utcnow


def _iso(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _observation(record: Any) -> dict:
    return {
        "external_id": record.external_id,
        "observation_date": _iso(record.observation_date),
        "period_start": _iso(record.period_start),
        "period_end": _iso(record.period_end),
        "metric_name": record.metric_name,
        "metric_type": record.metric_type,
        "metric_value": record.metric_value,
        "unit": record.unit,
        "granularity": record.granularity,
        "confidence": record.confidence,
        "source_url": record.source_url,
        "verification_status": record.verification_status,
        "data_quality": record.data_quality,
        "original_metric": record.original_metric,
        "meta": record.meta or {},
    }


def _listing(record: Any) -> dict:
    return {
        "external_id": record.external_id,
        "marketplace": record.marketplace,
        "listing_id": record.listing_id,
        "title": record.title,
        "seller_name": record.seller_name,
        "price": record.price,
        "rating": record.rating,
        "review_count": record.review_count,
        "listing_url": record.listing_url,
    }


def _product(record: Any) -> dict:
    return {
        "external_id": record.external_id,
        "name": record.name,
        "category_slug": record.category_slug,
        "brand": record.brand,
        "price": record.price,
        "is_synthetic": record.is_synthetic,
        "source_url": record.source_url,
    }


def build_payload(dataset: ConnectorDataset, *, max_records: int) -> tuple[dict, bool, int]:
    """Return (payload, truncated, total_record_count)."""
    observations = [_observation(item) for item in dataset.observations]
    listings = [_listing(item) for item in dataset.listings]
    products = [_product(item) for item in dataset.products]
    suppliers = [
        {
            "supplier_name": item.supplier_name,
            "platform_key": item.platform_key,
            "country": item.country,
            "rating": item.rating,
            "url": item.url,
        }
        for item in dataset.suppliers
    ]
    offers = [
        {
            "external_id": item.external_id,
            "supplier_name": item.supplier_name,
            "external_product_id": item.external_product_id,
            "product_cost": item.product_cost,
            "shipping_cost": item.shipping_cost,
            "minimum_order_quantity": item.minimum_order_quantity,
            "lead_time_days": item.lead_time_days,
            "availability": item.availability,
        }
        for item in dataset.offers
    ]
    total = len(observations) + len(listings) + len(products) + len(suppliers) + len(offers)
    truncated = max_records > 0 and total > max_records
    if truncated:
        # Keep the first N observations and no other record types; the counts
        # and attribution still describe the full run.
        observations = observations[:max_records]
        listings = []
        products = []
        suppliers = []
        offers = []
    payload = {
        "observations": observations,
        "listings": listings,
        "products": products,
        "suppliers": suppliers,
        "offers": offers,
        "metadata": dataset.metadata or {},
        "warnings": list(dataset.warnings),
        "request_count": dataset.request_count,
        "source_url": dataset.source_url,
        "truncated": truncated,
    }
    return payload, truncated, total


def store_snapshot(
    db: Session,
    source: DataSource,
    run: IngestionRun,
    dataset: ConnectorDataset,
    *,
    period_start: date,
    period_end: date,
) -> ProviderSnapshot:
    payload, truncated, total = build_payload(
        dataset, max_records=settings.snapshot_max_records
    )
    checksum = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    attribution = {
        "provider_key": source.provider_key,
        "provider_name": source.provider_name,
        "source_type": source.source_type,
        "usage_rights": source.usage_rights,
        "docs_url": source.docs_url,
        "terms_url": source.terms_url,
        "is_synthetic": bool(source.is_synthetic),
        "request_count": dataset.request_count,
        "source_url": dataset.source_url,
        "collected_at": utcnow().isoformat(),
        "retention_days": settings.snapshot_retention_days,
    }
    snapshot = ProviderSnapshot(
        source_id=source.id,
        ingestion_run_id=run.id,
        fetched_at=utcnow(),
        period_start=period_start,
        period_end=period_end,
        record_count=total,
        observation_count=len(dataset.observations),
        listing_count=len(dataset.listings),
        checksum=checksum,
        truncated=truncated,
        payload=payload,
        attribution=attribution,
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def prune_snapshots(db: Session, retention_days: int | None = None) -> int:
    """Delete snapshots older than the retention window. Returns rows removed."""
    days = retention_days or settings.snapshot_retention_days
    if days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = db.execute(
        delete(ProviderSnapshot).where(ProviderSnapshot.fetched_at < cutoff)
    )
    db.commit()
    return int(result.rowcount or 0)


def latest_snapshots(
    db: Session, source_id, *, limit: int = 20
) -> list[ProviderSnapshot]:
    return list(
        db.execute(
            select(ProviderSnapshot)
            .where(ProviderSnapshot.source_id == source_id)
            .order_by(ProviderSnapshot.fetched_at.desc())
            .limit(max(1, min(limit, 100)))
        )
        .scalars()
        .all()
    )
