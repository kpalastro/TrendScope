from __future__ import annotations

import os
from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import AdminUser, CurrentUser, DbSession, WriteUser
from app.core.errors import ApiError
from app.models import DataSource, IngestionRun
from app.schemas import SourcePatch
from app.services.ingestion import get_source, run_mock_sync

router = APIRouter(tags=["sources"])


def _configured(source: DataSource) -> bool:
    if source.is_synthetic:
        return True
    names = [name.strip() for name in (source.secret_ref or "").split(",") if name.strip()]
    return all(os.environ.get(name) for name in names)


def _source_payload(source: DataSource) -> dict:
    return {
        "id": source.id,
        "provider_key": source.provider_key,
        "provider_name": source.provider_name,
        "source_type": source.source_type,
        "enabled": source.enabled,
        "configured": _configured(source),
        "is_synthetic": source.is_synthetic,
        "config": source.config or {},
        "secret_ref": [name.strip() for name in (source.secret_ref or "").split(",") if name.strip()],
        "rate_limit_per_min": source.rate_limit_per_min,
        "sync_status": source.sync_status,
        "last_sync_at": source.last_sync_at,
        "last_error": source.last_error,
        "consecutive_failures": source.consecutive_failures,
    }


def _run_payload(run: IngestionRun) -> dict:
    return {
        "id": run.id,
        "source_id": run.source_id,
        "job_name": run.job_name,
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "records_fetched": run.records_fetched,
        "records_written": run.records_written,
        "records_rejected": run.records_rejected,
        "error_count": run.error_count,
        "error_summary": run.error_summary,
    }


def _job_payload(run: IngestionRun) -> dict:
    status = {
        "running": "running",
        "success": "succeeded",
        "failed": "failed",
    }.get(run.status, run.status)
    return {
        "id": str(run.id),
        "type": run.job_name,
        "status": status,
        "progress": {
            "processed": run.records_fetched,
            "total": run.records_fetched,
            "written": run.records_written,
            "rejected": run.records_rejected,
        },
        "result_url": f"/api/v1/data-sources/{run.source_id}/runs",
        "error": run.error_summary,
        "created_at": run.started_at,
        "poll_url": f"/api/v1/jobs/{run.id}",
    }


@router.get("/data-sources")
def list_sources(user: CurrentUser, db: DbSession) -> dict:
    sources = db.execute(select(DataSource).order_by(DataSource.provider_key)).scalars().all()
    return {"data": [_source_payload(source) for source in sources]}


@router.patch("/data-sources/{source_id}")
def patch_source(
    source_id: UUID, payload: SourcePatch, user: AdminUser, db: DbSession
) -> dict:
    source = db.get(DataSource, source_id)
    if source is None:
        raise ApiError(404, "NOT_FOUND", "Data source not found.")
    if payload.enabled is not None:
        source.enabled = payload.enabled
    if payload.config is not None:
        source.config = payload.config
    if payload.rate_limit_per_min is not None:
        source.rate_limit_per_min = payload.rate_limit_per_min
    db.commit()
    return _source_payload(source)


@router.post("/data-sources/{source_id}/sync", status_code=202)
def sync_source(source_id: UUID, user: WriteUser, db: DbSession) -> dict:
    source = db.get(DataSource, source_id)
    if source is None:
        raise ApiError(404, "NOT_FOUND", "Data source not found.")
    if not source.enabled:
        raise ApiError(503, "SOURCE_UNAVAILABLE", "This source is disabled.")
    if source.provider_key != "mock":
        raise ApiError(
            501,
            "NOT_IMPLEMENTED",
            "Only the mock provider is enabled in Phase 1. Configure it in a later phase.",
        )
    running = db.execute(
        select(IngestionRun)
        .where(IngestionRun.source_id == source.id, IngestionRun.status == "running")
        .limit(1)
    ).scalar_one_or_none()
    if running is not None:
        raise ApiError(409, "CONFLICT", "A run for this source is already in progress.")

    try:
        run = run_mock_sync(db, source=source)
    except Exception as exc:  # noqa: BLE001 - provider failure surfaces in the job
        db.rollback()
        raise ApiError(502, "PROVIDER_ERROR", f"Sync failed: {type(exc).__name__}") from exc
    return {"job": _job_payload(run), "run": _run_payload(run)}


@router.get("/data-sources/{source_id}/runs")
def source_runs(
    source_id: UUID, user: CurrentUser, db: DbSession, page: int = 1, per_page: int = 25
) -> dict:
    if db.get(DataSource, source_id) is None:
        raise ApiError(404, "NOT_FOUND", "Data source not found.")
    page = max(1, page)
    per_page = max(1, min(per_page, 100))
    rows = db.execute(
        select(IngestionRun)
        .where(IngestionRun.source_id == source_id)
        .order_by(IngestionRun.started_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    ).scalars().all()
    return {
        "data": [_run_payload(run) for run in rows],
        "meta": {"page": page, "per_page": per_page},
    }


@router.get("/sync/status")
def sync_status(user: CurrentUser, db: DbSession) -> dict:
    sources = db.execute(select(DataSource).order_by(DataSource.provider_key)).scalars().all()
    data = []
    for source in sources:
        latest = db.execute(
            select(IngestionRun)
            .where(IngestionRun.source_id == source.id)
            .order_by(IngestionRun.started_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        data.append(
            {
                **_source_payload(source),
                "latest_run": _run_payload(latest) if latest else None,
            }
        )
    return {"data": data}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, user: CurrentUser, db: DbSession) -> dict:
    try:
        run = db.get(IngestionRun, UUID(job_id))
    except ValueError as exc:
        raise ApiError(404, "NOT_FOUND", "Job not found.") from exc
    if run is None:
        raise ApiError(404, "NOT_FOUND", "Job not found.")
    return {"job": _job_payload(run)}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, user: WriteUser, db: DbSession) -> dict:
    return {
        "job": {
            "id": job_id,
            "status": "cancelled",
            "note": "Phase 1 runs are synchronous; nothing remained to cancel.",
        }
    }
