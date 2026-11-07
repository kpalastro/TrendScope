from datetime import date

from sqlalchemy import func, select

from app.core.config import settings
from app.models import OpportunityScore, Product, ProductMetric, TrendObservation
from app.services.catalog import get_product_row
from app.services.ingestion import get_source, run_mock_sync
from app.services.metrics import compute_product_metrics
from app.services.normalise import normalise_name
from app.services.scoring_service import compute_product_score, get_active_profile


def test_mock_sync_is_idempotent(db, seeded):
    source = get_source(db, "mock")
    first = run_mock_sync(db, source=source, product_limit=4, history_days=200)
    count_after_first = db.execute(select(func.count(TrendObservation.id))).scalar()

    second = run_mock_sync(db, source=source, product_limit=4, history_days=200)
    count_after_second = db.execute(select(func.count(TrendObservation.id))).scalar()

    assert first.status == second.status == "success"
    assert first.records_written > 0
    assert second.records_written == 0
    assert count_after_first == count_after_second


def test_sync_failure_is_recorded(db, seeded):
    source = get_source(db, "mock")
    original = settings.mock_product_limit

    def boom(*args, **kwargs):
        raise RuntimeError("provider exploded")

    import app.services.ingestion as ingestion

    monkeypatch_target = ingestion.build_mock_dataset
    ingestion.build_mock_dataset = boom
    try:
        try:
            run_mock_sync(db, source=source, product_limit=2)
        except RuntimeError:
            pass
        else:  # pragma: no cover
            raise AssertionError("expected the failure to propagate")
    finally:
        ingestion.build_mock_dataset = monkeypatch_target

    db.refresh(source)
    from app.models import IngestionRun

    run = db.execute(
        select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(1)
    ).scalar_one()
    assert run.status == "failed"
    assert "provider exploded" in (run.error_summary or "")
    assert source.sync_status == "error"
    assert source.consecutive_failures == 1
    settings.mock_product_limit = original


def test_missing_data_never_becomes_zero_growth(db, seeded):
    product = Product(
        name="No Data Product",
        normalised_name=normalise_name("No Data Product"),
        slug="no-data-product",
        country="AU",
        currency="AUD",
        status="active",
    )
    db.add(product)
    db.flush()

    metric = compute_product_metrics(db, product, date.today())
    profile = get_active_profile(db)
    score = compute_product_score(db, product, metric, profile, date.today())
    db.commit()

    assert metric.search_growth_7d_pct is None
    assert metric.search_growth_30d_pct is None
    assert metric.growth_reason_30d == "no_source"
    assert metric.trend_direction == "unknown"
    assert metric.data_coverage_pct == 0
    assert score.classification == "insufficient_data"
    assert score.coverage_pct == 0

    row = get_product_row(db, product.id)
    assert row is not None
    assert row.metric.growth_reason_30d == "no_source"


def test_metric_computation_produces_all_three_windows(db, seeded):
    source = get_source(db, "mock")
    run_mock_sync(db, source=source, product_limit=2, history_days=250)
    metric = db.execute(select(ProductMetric).limit(1)).scalar_one()
    assert metric.growth_reason_7d == "ok"
    assert metric.growth_reason_30d == "ok"
    assert metric.growth_reason_90d == "ok"
    assert metric.search_growth_90d_pct is not None
    assert metric.competition_class in {"low", "moderate", "high", "saturated", "unknown"}


def test_observations_are_append_only_and_deduped(db, seeded):
    source = get_source(db, "mock")
    run_mock_sync(db, source=source, product_limit=2, history_days=200)
    first = db.execute(select(func.count(TrendObservation.id))).scalar()
    run_mock_sync(db, source=source, product_limit=2, history_days=200)
    second = db.execute(select(func.count(TrendObservation.id))).scalar()
    assert first == second

    duplicates = db.execute(
        select(
            func.count(TrendObservation.id),
        )
        .group_by(
            TrendObservation.product_id,
            TrendObservation.source_id,
            TrendObservation.observation_date,
            TrendObservation.metric_name,
            TrendObservation.granularity,
            TrendObservation.country,
        )
        .having(func.count(TrendObservation.id) > 1)
    ).all()
    assert duplicates == []
