"""Provider health evaluation and history.

A health check answers a different question from an ingestion run:

* a *configuration* check is local, free and safe to run at any time;
* a *live* check makes the cheapest authenticated provider call available.

Both are recorded in ``provider_health_checks`` and mirrored onto the source row
(``health_status``, ``last_health_check_at``, ``last_health_latency_ms``). The
history lets an operator see flapping providers and distinguishes "no
credentials" from "provider rejected the credentials".
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.framework import ConnectorError, ConnectorUnavailable, HealthResult
from app.connectors.registry import get_connector
from app.models import DataSource, IngestionRun, ProviderHealthCheck, utcnow


def evaluate(
    db: Session, source: DataSource, *, live: bool = False
) -> ProviderHealthCheck:
    """Run a health check, persist the result and update the source row."""
    connector = get_connector(source.provider_key)
    if connector is None:
        result = HealthResult(
            status="unavailable",
            ok=False,
            message="No connector plugin is installed for this provider.",
            details={"installed": False},
            live=False,
        )
    else:
        try:
            result = connector.health_check(source, live=live)
        except ConnectorUnavailable as exc:
            result = HealthResult(
                status="unavailable", ok=False, message=str(exc)[:500], live=live
            )
        except ConnectorError as exc:
            result = HealthResult(
                status="degraded",
                ok=False,
                message=str(exc)[:500],
                details={"error_type": type(exc).__name__},
                live=live,
            )
        except Exception as exc:  # noqa: BLE001 - health checks must not raise
            result = HealthResult(
                status="degraded",
                ok=False,
                message=f"{type(exc).__name__}: {exc}"[:500],
                live=live,
            )

    row = ProviderHealthCheck(
        source_id=source.id,
        checked_at=utcnow(),
        live=bool(result.live),
        status=result.status,
        ok=bool(result.ok),
        latency_ms=result.latency_ms,
        http_status=result.http_status,
        message=result.message,
        details=dict(result.details or {}),
    )
    db.add(row)
    source.health_status = result.status
    source.last_health_check_at = row.checked_at
    source.last_health_latency_ms = result.latency_ms
    db.commit()
    db.refresh(row)
    return row


def check_all(db: Session, *, live: bool = False) -> list[ProviderHealthCheck]:
    sources = db.execute(select(DataSource).order_by(DataSource.provider_key)).scalars().all()
    return [evaluate(db, source, live=live) for source in sources]


def recent_checks(
    db: Session, source_id: UUID, *, limit: int = 20
) -> list[ProviderHealthCheck]:
    return list(
        db.execute(
            select(ProviderHealthCheck)
            .where(ProviderHealthCheck.source_id == source_id)
            .order_by(ProviderHealthCheck.checked_at.desc())
            .limit(max(1, min(limit, 200)))
        )
        .scalars()
        .all()
    )


def summary(db: Session, source: DataSource) -> dict:
    """Rolling 24-hour health statistics plus the latest ingestion run."""
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    checks = db.execute(
        select(ProviderHealthCheck).where(
            ProviderHealthCheck.source_id == source.id,
            ProviderHealthCheck.checked_at >= since,
        )
    ).scalars().all()
    ok_count = sum(1 for check in checks if check.ok)
    latencies = [check.latency_ms for check in checks if check.latency_ms is not None]
    latest = db.execute(
        select(ProviderHealthCheck)
        .where(ProviderHealthCheck.source_id == source.id)
        .order_by(ProviderHealthCheck.checked_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    latest_run = db.execute(
        select(IngestionRun)
        .where(IngestionRun.source_id == source.id)
        .order_by(IngestionRun.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return {
        "source_id": source.id,
        "provider_key": source.provider_key,
        "provider_name": source.provider_name,
        "health_status": source.health_status,
        "last_health_check_at": source.last_health_check_at,
        "last_health_latency_ms": source.last_health_latency_ms,
        "last_sync_at": source.last_sync_at,
        "last_success_at": source.last_success_at,
        "sync_status": source.sync_status,
        "consecutive_failures": source.consecutive_failures,
        "checks_24h": len(checks),
        "ok_24h": ok_count,
        "success_rate_24h": round(ok_count / len(checks), 3) if checks else None,
        "avg_latency_ms_24h": round(sum(latencies) / len(latencies)) if latencies else None,
        "latest_check": check_payload(latest) if latest else None,
        "latest_run": run_payload(latest_run) if latest_run else None,
    }


def check_payload(row: ProviderHealthCheck) -> dict:
    return {
        "id": row.id,
        "source_id": row.source_id,
        "checked_at": row.checked_at,
        "live": row.live,
        "status": row.status,
        "ok": row.ok,
        "latency_ms": row.latency_ms,
        "http_status": row.http_status,
        "message": row.message,
        "details": row.details or {},
    }


def run_payload(row: IngestionRun) -> dict:
    return {
        "id": row.id,
        "job_name": row.job_name,
        "status": row.status,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "records_fetched": row.records_fetched,
        "records_written": row.records_written,
        "records_updated": row.records_updated,
        "records_rejected": row.records_rejected,
        "error_summary": row.error_summary,
    }


def overall(db: Session) -> dict:
    sources = db.execute(select(DataSource).order_by(DataSource.provider_key)).scalars().all()
    items = [summary(db, source) for source in sources]
    counts: dict[str, int] = {}
    for item in items:
        counts[item["health_status"]] = counts.get(item["health_status"], 0) + 1
    return {
        "data": items,
        "meta": {
            "counts": counts,
            "total": len(items),
            "generated_at": utcnow(),
            "note": (
                "Configuration checks are local. Live checks make one cheap "
                "authenticated provider call and may consume a small quota."
            ),
        },
    }
