from __future__ import annotations

import os
from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.deps import AdminUser, CurrentUser, DbSession, WriteUser
from app.connectors.framework import ConnectorError, ConnectorUnavailable
from app.connectors.registry import get_connector
from app.core.errors import ApiError
from app.models import DataSource, IngestionRun, ProviderSnapshot
from app.schemas import SourcePatch
from app.services import audit, provider_health
from app.services.ingestion import get_source, run_connector_sync, run_mock_sync
from app.services.snapshots import latest_snapshots

router = APIRouter(tags=["sources"])


def _configured(source: DataSource) -> bool:
    if source.is_synthetic:
        return True
    names = [name.strip() for name in (source.secret_ref or "").split(",") if name.strip()]
    return all(os.environ.get(name) for name in names)


def _money(value) -> str | None:
    if value is None:
        return None
    return f"{float(value):.2f}"


def _health(source: DataSource, connector_status: dict) -> str:
    if not source.enabled:
        return "disabled"
    if connector_status.get("state") == "unavailable" or source.availability == "unavailable":
        return "unavailable"
    if connector_status.get("state") == "manual_fallback":
        return "manual"
    if connector_status.get("state") == "requires_credentials" or not connector_status.get(
        "configured", False
    ):
        return "unconfigured"
    if source.sync_status == "error" or (source.consecutive_failures or 0) > 0:
        return "degraded"
    if source.last_success_at is not None or source.sync_status == "ok":
        return "healthy"
    return "idle"


def _source_payload(source: DataSource) -> dict:
    connector = get_connector(source.provider_key)
    if connector is not None:
        status = connector.get_source_status(source)
        connector_payload = {
            "installed": True,
            "state": status.state,
            "available": status.available,
            "configured": status.configured,
            "reason": status.reason,
            "credential_names": list(status.credential_names),
            "docs_url": status.docs_url,
            "terms_url": status.terms_url,
            "cost_model": status.cost_model,
        }
        configured = status.configured
    else:
        connector_payload = {
            "installed": False,
            "state": "not_installed",
            "available": False,
            "configured": _configured(source),
            "reason": "No connector plugin is installed. Add one later without changing the schema or scoring engine.",
            "credential_names": [
                name.strip()
                for name in (source.secret_ref or "").split(",")
                if name.strip()
            ],
            "docs_url": source.docs_url,
            "terms_url": source.terms_url,
            "cost_model": source.cost_model,
        }
        configured = _configured(source)

    return {
        "id": source.id,
        "provider_key": source.provider_key,
        "provider_name": source.provider_name,
        "source_type": source.source_type,
        "enabled": source.enabled,
        "configured": configured,
        "is_synthetic": source.is_synthetic,
        "config": source.config or {},
        "secret_ref": [name.strip() for name in (source.secret_ref or "").split(",") if name.strip()],
        "rate_limit_per_min": source.rate_limit_per_min,
        "sync_status": source.sync_status,
        "last_sync_at": source.last_sync_at,
        "last_success_at": source.last_success_at,
        "last_error": source.last_error,
        "consecutive_failures": source.consecutive_failures,
        "health_status": source.health_status,
        "last_health_check_at": source.last_health_check_at,
        "last_health_latency_ms": source.last_health_latency_ms,
        "cost_model": source.cost_model,
        "monthly_cost": _money(source.monthly_cost),
        "cost_currency": source.cost_currency,
        "estimated_monthly_spend": _money(source.monthly_cost),
        "request_limit_month": source.request_limit_month,
        "requests_used_month": source.requests_used_month or 0,
        "usage_period": source.usage_period,
        "availability": source.availability,
        "availability_reason": source.availability_reason,
        "usage_rights": source.usage_rights,
        "docs_url": source.docs_url,
        "terms_url": source.terms_url,
        "health": _health(source, connector_payload),
        "connector": connector_payload,
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
        "records_updated": run.records_updated,
        "records_rejected": run.records_rejected,
        "error_count": run.error_count,
        "error_summary": run.error_summary,
        "cursor": run.cursor or {},
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


def _snapshot_payload(snapshot: ProviderSnapshot, *, include_payload: bool = False) -> dict:
    payload = {
        "id": snapshot.id,
        "source_id": snapshot.source_id,
        "ingestion_run_id": snapshot.ingestion_run_id,
        "fetched_at": snapshot.fetched_at,
        "period_start": snapshot.period_start,
        "period_end": snapshot.period_end,
        "record_count": snapshot.record_count,
        "observation_count": snapshot.observation_count,
        "listing_count": snapshot.listing_count,
        "checksum": snapshot.checksum,
        "truncated": snapshot.truncated,
        "attribution": snapshot.attribution or {},
    }
    if include_payload:
        payload["payload"] = snapshot.payload or {}
    return payload


@router.get("/data-sources/health")
def health_overview(user: CurrentUser, db: DbSession) -> dict:
    """Latest health for every source plus 24-hour check statistics."""
    return provider_health.overall(db)


@router.get("/data-sources/{source_id}/health")
def source_health(
    source_id: UUID,
    user: CurrentUser,
    db: DbSession,
    limit: int = 20,
) -> dict:
    source = db.get(DataSource, source_id)
    if source is None:
        raise ApiError(404, "NOT_FOUND", "Data source not found.")
    checks = provider_health.recent_checks(db, source.id, limit=limit)
    return {
        "summary": provider_health.summary(db, source),
        "checks": [provider_health.check_payload(item) for item in checks],
    }


@router.post("/data-sources/{source_id}/health-check")
def run_health_check(
    source_id: UUID,
    request: Request,
    user: AdminUser,
    db: DbSession,
    live: bool = False,
) -> dict:
    """Record a health check.

    ``live=false`` is a free local configuration check. ``live=true`` makes the
    cheapest authenticated provider call the connector supports and may consume
    a small amount of provider quota.
    """
    source = db.get(DataSource, source_id)
    if source is None:
        raise ApiError(404, "NOT_FOUND", "Data source not found.")
    check = provider_health.evaluate(db, source, live=live)
    audit.record(
        db,
        action="data_source.health_check",
        entity_type="data_source",
        entity_id=source.id,
        user=user,
        request=request,
        changes={
            "live": check.live,
            "status": check.status,
            "ok": check.ok,
            "latency_ms": check.latency_ms,
        },
    )
    return {
        "check": provider_health.check_payload(check),
        "summary": provider_health.summary(db, source),
    }


@router.get("/data-sources/{source_id}/snapshots")
def source_snapshots(
    source_id: UUID,
    user: CurrentUser,
    db: DbSession,
    limit: int = 20,
) -> dict:
    source = db.get(DataSource, source_id)
    if source is None:
        raise ApiError(404, "NOT_FOUND", "Data source not found.")
    rows = latest_snapshots(db, source.id, limit=limit)
    return {
        "data": [_snapshot_payload(row) for row in rows],
        "meta": {"count": len(rows), "limit": max(1, min(limit, 100))},
    }


@router.get("/data-sources/{source_id}/snapshots/{snapshot_id}")
def source_snapshot_detail(
    source_id: UUID,
    snapshot_id: UUID,
    user: CurrentUser,
    db: DbSession,
) -> dict:
    snapshot = db.get(ProviderSnapshot, snapshot_id)
    if snapshot is None or snapshot.source_id != source_id:
        raise ApiError(404, "NOT_FOUND", "Snapshot not found.")
    return {"snapshot": _snapshot_payload(snapshot, include_payload=True)}


@router.patch("/data-sources/{source_id}")
def patch_source(
    source_id: UUID,
    payload: SourcePatch,
    request: Request,
    user: AdminUser,
    db: DbSession,
) -> dict:
    source = db.get(DataSource, source_id)
    if source is None:
        raise ApiError(404, "NOT_FOUND", "Data source not found.")
    before = {"enabled": source.enabled, "cost_model": source.cost_model}
    if payload.enabled is not None:
        source.enabled = payload.enabled
    if payload.config is not None:
        source.config = payload.config
    if payload.rate_limit_per_min is not None:
        source.rate_limit_per_min = payload.rate_limit_per_min
    if payload.cost_model is not None:
        source.cost_model = payload.cost_model
    if payload.monthly_cost is not None:
        source.monthly_cost = payload.monthly_cost
    if payload.cost_currency is not None:
        source.cost_currency = payload.cost_currency.upper()
    if payload.request_limit_month is not None:
        source.request_limit_month = payload.request_limit_month
    if payload.usage_rights is not None:
        source.usage_rights = payload.usage_rights
    if payload.docs_url is not None:
        source.docs_url = payload.docs_url
    if payload.terms_url is not None:
        source.terms_url = payload.terms_url
    db.commit()
    audit.record(
        db,
        action="data_source.update",
        entity_type="data_source",
        entity_id=source.id,
        user=user,
        request=request,
        changes={
            "before": before,
            "after": {"enabled": source.enabled, "cost_model": source.cost_model},
        },
    )
    return _source_payload(source)


@router.post("/data-sources/{source_id}/test-connection")
def test_connection(source_id: UUID, user: AdminUser, db: DbSession) -> dict:
    source = db.get(DataSource, source_id)
    if source is None:
        raise ApiError(404, "NOT_FOUND", "Data source not found.")
    connector = get_connector(source.provider_key)
    if connector is None:
        raise ApiError(
            501,
            "NOT_IMPLEMENTED",
            "No connector plugin is installed for this provider.",
        )
    status = connector.get_source_status(source)
    return {
        "source_id": source.id,
        "provider_key": source.provider_key,
        "installed": True,
        "enabled": status.enabled,
        "configured": status.configured,
        "available": status.available,
        "state": status.state,
        "reason": status.reason,
        "checked_at": None,
        "note": "Credential and configuration check only; no provider call was made.",
    }


@router.post("/data-sources/{source_id}/sync", status_code=202)
def sync_source(
    source_id: UUID, request: Request, user: WriteUser, db: DbSession
) -> dict:
    source = db.get(DataSource, source_id)
    if source is None:
        raise ApiError(404, "NOT_FOUND", "Data source not found.")
    if not source.enabled:
        raise ApiError(503, "SOURCE_UNAVAILABLE", "This source is disabled.")

    connector = get_connector(source.provider_key)
    if connector is None:
        raise ApiError(
            501,
            "NOT_IMPLEMENTED",
            "No connector plugin is installed for this provider. Add a connector plugin "
            "or use CSV/manual research.",
        )
    status = connector.get_source_status(source)
    if not status.available:
        raise ApiError(
            503,
            "SOURCE_UNAVAILABLE",
            status.reason or "This source is not available.",
        )
    if source.provider_key == "csv_import":
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "CSV import is an upload workflow. Use POST /products/import/csv or "
            "POST /products/import/observations/csv.",
        )

    running = db.execute(
        select(IngestionRun)
        .where(IngestionRun.source_id == source.id, IngestionRun.status == "running")
        .limit(1)
    ).scalar_one_or_none()
    if running is not None:
        raise ApiError(409, "CONFLICT", "A run for this source is already in progress.")

    try:
        if source.provider_key == "mock":
            run = run_mock_sync(db, source=source)
        else:
            run = run_connector_sync(db, source)
    except ConnectorUnavailable as exc:
        db.rollback()
        raise ApiError(503, "SOURCE_UNAVAILABLE", str(exc)) from exc
    except ConnectorError as exc:
        db.rollback()
        raise ApiError(502, "PROVIDER_ERROR", str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - provider failure surfaces in the job
        db.rollback()
        raise ApiError(502, "PROVIDER_ERROR", f"Sync failed: {type(exc).__name__}") from exc
    audit.record(
        db,
        action="data_source.sync",
        entity_type="data_source",
        entity_id=source.id,
        user=user,
        request=request,
        changes={
            "run_id": str(run.id),
            "records_fetched": run.records_fetched,
            "records_written": run.records_written,
        },
    )
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
