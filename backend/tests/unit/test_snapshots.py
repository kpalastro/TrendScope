from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.connectors.base import (
    ConnectorDataset,
    ListingRecord,
    ObservationPoint,
    ProductCandidate,
    SupplierOfferRecord,
    SupplierRecord,
)
from app.core.config import settings
from app.models import DataSource, IngestionRun, ProviderSnapshot
from app.services.snapshots import (
    build_payload,
    latest_snapshots,
    prune_snapshots,
    store_snapshot,
)


def _dataset(observations: int = 2, listings: int = 1) -> ConnectorDataset:
    return ConnectorDataset(
        products=[
            ProductCandidate(
                external_id="p1",
                name="Yoga Mat",
                category_slug="fitness",
                brand="Acme",
                price=39.95,
                description="A mat",
                is_synthetic=False,
                source_url="https://provider.test/p1",
            )
        ],
        observations=[
            ObservationPoint(
                external_id="p1",
                observation_date=date(2025, 1, index + 1),
                metric_name="search_interest",
                metric_value=float(40 + index),
                unit="index",
                granularity="daily",
                metric_type="search_interest",
                period_start=date(2025, 1, index + 1),
                period_end=date(2025, 1, index + 1),
                source_url="https://provider.test/trends",
                verification_status="verified",
                data_quality="high",
                original_metric="interest",
                meta={"term": "yoga mat"},
            )
            for index in range(observations)
        ],
        listings=[
            ListingRecord(
                external_id="p1",
                marketplace="EBAY_AU",
                listing_id=f"L{index}",
                title="Yoga mat listing",
                seller_name="Seller",
                price=29.9,
                rating=4.8,
                review_count=12,
                listing_url="https://ebay.test/listing",
            )
            for index in range(listings)
        ],
        suppliers=[
            SupplierRecord(
                supplier_name="Supplier One",
                platform_key="manual",
                country="AU",
                rating=4.5,
                url="https://supplier.test",
            )
        ],
        offers=[
            SupplierOfferRecord(
                external_id="p1",
                supplier_name="Supplier One",
                external_product_id="offer-1",
                product_cost=10.0,
                shipping_cost=2.0,
                minimum_order_quantity=10,
                lead_time_days=7,
                availability="in_stock",
            )
        ],
        warnings=["one record was sampled"],
        request_count=3,
        source_url="https://provider.test",
        metadata={"window": "30d"},
    )


def _source_and_run(db) -> tuple[DataSource, IngestionRun]:
    source = db.query(DataSource).filter(DataSource.provider_key == "mock").one()
    run = IngestionRun(source_id=source.id, job_name="sync.mock", status="running")
    db.add(run)
    db.commit()
    return source, run


def test_build_payload_serialises_connector_records():
    payload, truncated, total = build_payload(_dataset(), max_records=5000)

    assert truncated is False
    assert total == 2 + 1 + 1 + 1 + 1
    assert payload["truncated"] is False
    assert payload["request_count"] == 3
    assert payload["metadata"] == {"window": "30d"}
    assert payload["warnings"] == ["one record was sampled"]
    assert payload["observations"][0]["observation_date"] == "2025-01-01"
    assert payload["observations"][0]["meta"] == {"term": "yoga mat"}
    assert payload["listings"][0]["listing_id"] == "L0"
    assert payload["offers"][0]["product_cost"] == 10.0


def test_build_payload_truncates_to_bound():
    payload, truncated, total = build_payload(_dataset(observations=5), max_records=2)

    assert truncated is True
    assert total == 5 + 1 + 1 + 1 + 1
    assert len(payload["observations"]) == 2
    assert payload["listings"] == []
    assert payload["products"] == []
    assert payload["suppliers"] == []
    assert payload["offers"] == []


def test_store_snapshot_archives_payload_and_attribution(db, seeded):
    source, run = _source_and_run(db)
    snapshot = store_snapshot(
        db,
        source,
        run,
        _dataset(),
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 30),
    )
    db.commit()

    assert snapshot.id is not None
    assert snapshot.source_id == source.id
    assert snapshot.ingestion_run_id == run.id
    assert snapshot.record_count == 6
    assert snapshot.observation_count == 2
    assert snapshot.listing_count == 1
    assert snapshot.truncated is False
    assert len(snapshot.checksum) == 64
    assert snapshot.attribution["provider_key"] == "mock"
    assert snapshot.attribution["is_synthetic"] is True
    assert snapshot.attribution["request_count"] == 3
    assert snapshot.period_start == date(2025, 1, 1)
    assert snapshot.payload["observations"][0]["metric_value"] == 40.0


def test_checksum_is_stable_for_the_same_dataset(db, seeded):
    source, run = _source_and_run(db)
    first = store_snapshot(
        db, source, run, _dataset(), period_start=date(2025, 1, 1), period_end=date(2025, 1, 30)
    )
    second = store_snapshot(
        db, source, run, _dataset(), period_start=date(2025, 1, 1), period_end=date(2025, 1, 30)
    )
    db.commit()

    assert first.checksum == second.checksum
    assert first.id != second.id


def test_snapshot_respects_configured_max_records(db, seeded, monkeypatch):
    monkeypatch.setattr(settings, "snapshot_max_records", 1)
    source, run = _source_and_run(db)
    snapshot = store_snapshot(
        db, source, run, _dataset(), period_start=date(2025, 1, 1), period_end=date(2025, 1, 30)
    )
    db.commit()

    assert snapshot.truncated is True
    assert len(snapshot.payload["observations"]) == 1
    assert snapshot.record_count == 6


def test_prune_snapshots_removes_only_rows_past_retention(db, seeded):
    source, run = _source_and_run(db)
    old = store_snapshot(
        db, source, run, _dataset(), period_start=date(2025, 1, 1), period_end=date(2025, 1, 30)
    )
    recent = store_snapshot(
        db, source, run, _dataset(), period_start=date(2025, 1, 1), period_end=date(2025, 1, 30)
    )
    old.fetched_at = datetime.now(timezone.utc) - timedelta(days=90)
    db.commit()

    removed = prune_snapshots(db, retention_days=30)

    remaining = db.query(ProviderSnapshot).all()
    assert removed == 1
    assert [row.id for row in remaining] == [recent.id]
    assert db.get(ProviderSnapshot, old.id) is None


def test_prune_snapshots_is_disabled_when_retention_is_zero(db, seeded):
    source, run = _source_and_run(db)
    store_snapshot(
        db, source, run, _dataset(), period_start=date(2025, 1, 1), period_end=date(2025, 1, 30)
    )
    db.commit()

    assert prune_snapshots(db, retention_days=0) == 0
    assert len(latest_snapshots(db, source.id)) == 1
