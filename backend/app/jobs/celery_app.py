"""Celery application and schedules.

The schedule runs in Australia/Sydney so "02:00 daily" means the Sydney morning,
not UTC. Phase 1 syncs only the synthetic provider; real providers are gated
until credentials and terms are confirmed.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "trendscope",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.jobs.tasks"],
)

celery_app.conf.update(
    timezone="Australia/Sydney",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=1800,
    task_soft_time_limit=1500,
    broker_connection_retry_on_startup=True,
)

celery_app.conf.beat_schedule = {
    "mock-sync-daily": {
        "task": "app.jobs.tasks.sync_mock",
        "schedule": crontab(hour=2, minute=0),
    },
    "weekly-report-monday": {
        "task": "app.jobs.tasks.weekly_report",
        "schedule": crontab(hour=6, minute=0, day_of_week=1),
    },
    "recompute-scores-daily": {
        "task": "app.jobs.tasks.recompute_scores",
        "schedule": crontab(hour=3, minute=0),
    },
    "provider-health-daily": {
        "task": "app.jobs.tasks.check_provider_health",
        "schedule": crontab(hour=4, minute=0),
    },
    "connector-sync-daily": {
        "task": "app.jobs.tasks.sync_enabled_connectors",
        "schedule": crontab(hour=4, minute=30),
    },
    "snapshot-retention-weekly": {
        "task": "app.jobs.tasks.prune_snapshots",
        "schedule": crontab(hour=5, minute=0, day_of_week=0),
    },
}
