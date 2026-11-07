"""Idempotent seed data: categories, scoring profile, admin user, source registry."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.catalog import CATEGORIES
from app.core.config import settings
from app.core.security import hash_password
from app.models import Category, DataSource, ScoringProfile, User
from app.services.scoring import DEFAULT_THRESHOLDS, DEFAULT_WEIGHTS

SOURCE_REGISTRY = [
    {
        "provider_key": "mock",
        "provider_name": "Mock demo provider",
        "source_type": "synthetic_demo",
        "enabled": True,
        "is_synthetic": True,
        "config": {"geo": "AU", "note": "Deterministic synthetic data for local demos."},
    },
    {
        "provider_key": "csv_import",
        "provider_name": "Manual CSV import",
        "source_type": "manual_upload",
        "enabled": True,
        "is_synthetic": False,
        "config": {"max_file_mb": 2, "required_columns": ["name"]},
    },
    {
        "provider_key": "google_trends",
        "provider_name": "Google Trends (DataForSEO)",
        "source_type": "search_trend",
        "enabled": False,
        "config": {"geo": "AU", "max_keywords_per_run": 200},
        "secret_ref": "DATAFORSEO_LOGIN,DATAFORSEO_PASSWORD",
    },
    {
        "provider_key": "ebay_au",
        "provider_name": "eBay Australia (Browse API)",
        "source_type": "marketplace",
        "enabled": False,
        "config": {"marketplace_id": "EBAY_AU", "covers_sold_data": False},
        "secret_ref": "EBAY_CLIENT_ID,EBAY_CLIENT_SECRET",
    },
    {
        "provider_key": "exploding_topics",
        "provider_name": "Exploding Topics",
        "source_type": "trend_discovery",
        "enabled": False,
        "config": {"mode": "csv_first"},
        "secret_ref": "EXPLODING_TOPICS_API_KEY",
    },
    {
        "provider_key": "amazon_au",
        "provider_name": "Amazon Australia",
        "source_type": "marketplace",
        "enabled": False,
        "config": {
            "available": False,
            "reason": "No first-party product API for amazon.com.au; PA-API has no AU domain.",
        },
    },
    {
        "provider_key": "tiktok",
        "provider_name": "TikTok Creative Center",
        "source_type": "social",
        "enabled": False,
        "config": {"available": False, "reason": "Creative Center is not accessible from Australia."},
    },
    {
        "provider_key": "cj_dropshipping",
        "provider_name": "CJ Dropshipping",
        "source_type": "supplier",
        "enabled": False,
        "config": {"note": "API access is revoked after 30 days without transactions."},
        "secret_ref": "CJ_API_KEY",
    },
]


def seed_categories(db: Session) -> int:
    existing = {category.slug for category in db.execute(select(Category)).scalars()}
    created = 0
    for slug, name in CATEGORIES:
        if slug in existing:
            continue
        db.add(Category(name=name, slug=slug, path=slug, level=0))
        created += 1
    db.flush()
    return created


def seed_sources(db: Session) -> int:
    existing = {source.provider_key for source in db.execute(select(DataSource)).scalars()}
    created = 0
    for definition in SOURCE_REGISTRY:
        if definition["provider_key"] in existing:
            continue
        db.add(
            DataSource(
                provider_key=definition["provider_key"],
                provider_name=definition["provider_name"],
                source_type=definition["source_type"],
                enabled=definition.get("enabled", False),
                is_synthetic=definition.get("is_synthetic", False),
                config=definition.get("config", {}),
                secret_ref=definition.get("secret_ref"),
            )
        )
        created += 1
    db.flush()
    return created


def seed_admin(db: Session) -> User:
    email = settings.admin_email.lower()
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None:
        user = User(
            email=email,
            password_hash=hash_password(settings.admin_password),
            display_name="TrendScope Admin",
            role="admin",
            is_active=True,
        )
        db.add(user)
        db.flush()
    return user


def seed_scoring_profile(db: Session) -> ScoringProfile:
    profile = db.execute(
        select(ScoringProfile).where(
            ScoringProfile.country == "AU", ScoringProfile.is_default.is_(True)
        )
    ).scalar_one_or_none()
    if profile is None:
        profile = ScoringProfile(
            name="Default AU",
            country="AU",
            version=1,
            weights=DEFAULT_WEIGHTS,
            thresholds=DEFAULT_THRESHOLDS,
            is_active=True,
            is_default=True,
        )
        db.add(profile)
        db.flush()
    return profile


def seed_all(db: Session) -> dict:
    created = {
        "categories": seed_categories(db),
        "sources": seed_sources(db),
    }
    seed_admin(db)
    seed_scoring_profile(db)
    db.commit()
    return created


def init_database(db: Session, demo: bool = False) -> dict:
    from app.services.ingestion import get_source, run_mock_sync

    created = seed_all(db)
    if demo and settings.seed_demo:
        source = get_source(db, "mock")
        if source is not None and source.last_sync_at is None:
            run = run_mock_sync(db, source=source)
            created["demo_run"] = str(run.id)
    return created
