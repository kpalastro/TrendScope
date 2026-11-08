from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import select

from app.connectors.framework import ConnectorError
from app.connectors.registry import get_connector
from app.core.database import SessionLocal
from app.jobs.celery_app import celery_app
from app.models import DataSource
from app.services.ingestion import get_source, run_connector_sync, run_mock_sync
from app.services.metrics import compute_all_metrics
from app.services.provider_health import check_all
from app.services.reports import generate_weekly
from app.services.scoring_service import compute_all_scores
from app.services.snapshots import prune_snapshots


@celery_app.task(name="app.jobs.tasks.sync_mock", bind=True, max_retries=3, default_retry_delay=300)
def sync_mock(self, as_of: str | None = None):
    with SessionLocal() as db:
        source = get_source(db, "mock")
        if source is None:
            raise RuntimeError("Mock source missing; seed the database first.")
        try:
            run = run_mock_sync(db, source=source, as_of=date.fromisoformat(as_of) if as_of else None)
        except Exception as exc:  # noqa: BLE001 - retry transient failures
            raise self.retry(exc=exc)
        return {"run": str(run.id), "written": run.records_written}


@celery_app.task(name="app.jobs.tasks.sync_connector", bind=True, max_retries=3)
def sync_connector(self, source_id: str, as_of: str | None = None):
    """Sync one authorised connector with bounded retries for transient errors."""
    with SessionLocal() as db:
        try:
            source_uuid = UUID(source_id)
        except ValueError as exc:
            raise RuntimeError(f"Invalid data source id: {source_id}") from exc
        source = db.get(DataSource, source_uuid)
        if source is None:
            raise RuntimeError(f"Data source {source_id} not found.")
        try:
            run = run_connector_sync(
                db, source, as_of=date.fromisoformat(as_of) if as_of else None
            )
        except ConnectorError as exc:
            connector = get_connector(source.provider_key)
            info = connector.handle_errors(exc) if connector else None
            if info and info.retryable and self.request.retries < self.max_retries:
                countdown = min(60 * (2 ** self.request.retries), 600)
                raise self.retry(exc=exc, countdown=countdown)
            raise
        return {
            "run": str(run.id),
            "status": run.status,
            "written": run.records_written,
            "updated": run.records_updated,
        }


@celery_app.task(name="app.jobs.tasks.sync_enabled_connectors")
def sync_enabled_connectors(as_of: str | None = None):
    """Run every enabled, available non-synthetic connector sequentially."""
    target = date.fromisoformat(as_of) if as_of else None
    results: list[dict] = []
    with SessionLocal() as db:
        sources = (
            db.execute(
                select(DataSource)
                .where(DataSource.enabled.is_(True))
                .order_by(DataSource.provider_key)
            )
            .scalars()
            .all()
        )
        for source in sources:
            if source.provider_key in {"mock", "csv_import"} or source.is_synthetic:
                continue
            connector = get_connector(source.provider_key)
            if connector is None:
                continue
            if not connector.get_source_status(source).available:
                results.append(
                    {
                        "source": source.provider_key,
                        "status": "skipped",
                        "reason": "not available",
                    }
                )
                continue
            try:
                run = run_connector_sync(db, source, as_of=target)
                results.append(
                    {
                        "source": source.provider_key,
                        "status": run.status,
                        "written": run.records_written,
                        "updated": run.records_updated,
                    }
                )
            except Exception as exc:  # noqa: BLE001 - one source must not stop the rest
                results.append(
                    {
                        "source": source.provider_key,
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}"[:300],
                    }
                )
    return {"results": results}


@celery_app.task(name="app.jobs.tasks.check_provider_health")
def check_provider_health(live: bool = False):
    """Record a health check for every source (config-only by default)."""
    with SessionLocal() as db:
        checks = check_all(db, live=live)
        return {
            "checked": len(checks),
            "live": live,
            "failures": sum(1 for check in checks if not check.ok),
        }


@celery_app.task(name="app.jobs.tasks.prune_snapshots")
def prune_old_snapshots(retention_days: int | None = None):
    with SessionLocal() as db:
        return {"removed": prune_snapshots(db, retention_days)}


@celery_app.task(name="app.jobs.tasks.weekly_report")
def weekly_report(country: str = "AU"):
    end = date.today()
    start = end - timedelta(days=7)
    with SessionLocal() as db:
        report = generate_weekly(db, country, start, end)
        return {"report": str(report.id), "status": report.status}


@celery_app.task(name="app.jobs.tasks.recompute_scores")
def recompute_scores(as_of: str | None = None):
    target = date.fromisoformat(as_of) if as_of else date.today()
    with SessionLocal() as db:
        metrics = compute_all_metrics(db, target)
        scores = compute_all_scores(db, target)
        return {"metrics": metrics, "scores": scores}
