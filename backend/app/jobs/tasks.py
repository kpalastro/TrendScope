from __future__ import annotations

from datetime import date, timedelta

from app.core.database import SessionLocal
from app.jobs.celery_app import celery_app
from app.services.ingestion import get_source, run_mock_sync
from app.services.metrics import compute_all_metrics
from app.services.reports import generate_weekly
from app.services.scoring_service import compute_all_scores


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
