from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import DbSession
from app.core.config import settings

router = APIRouter(tags=["health"])

VERSION = "1.0.0-phase1"


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "trendscope-api", "version": VERSION}


@router.get("/health/ready")
def ready(db: DbSession) -> dict:
    checks = {"database": "ok", "redis": "skipped"}

    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - readiness must report, not raise
        checks["database"] = f"error: {type(exc).__name__}"
        return {"status": "degraded", "checks": checks, "version": VERSION}

    if settings.celery_enabled:
        try:
            import redis

            client = redis.Redis.from_url(settings.redis_url, socket_timeout=0.5)
            client.ping()
            checks["redis"] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks["redis"] = f"error: {type(exc).__name__}"
            return {"status": "degraded", "checks": checks, "version": VERSION}

    return {"status": "ok", "checks": checks, "version": VERSION}
