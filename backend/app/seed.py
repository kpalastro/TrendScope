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
        "cost_model": "synthetic",
        "monthly_cost": 0,
        "availability": "available",
        "usage_rights": "synthetic",
        "config": {"geo": "AU", "note": "Deterministic synthetic data for local demos."},
    },
    {
        "provider_key": "csv_import",
        "provider_name": "Manual CSV / spreadsheet import",
        "source_type": "manual_upload",
        "enabled": True,
        "is_synthetic": False,
        "cost_model": "manual",
        "monthly_cost": 0,
        "availability": "available",
        "usage_rights": "manual_research",
        "config": {"max_file_mb": 2, "required_columns": ["name"]},
    },
    {
        "provider_key": "google_trends",
        "provider_name": "Google Trends (manual / official alpha)",
        "source_type": "search_trend",
        "enabled": False,
        "is_synthetic": False,
        "cost_model": "free",
        "monthly_cost": 0,
        "availability": "manual_fallback",
        "availability_reason": (
            "Google Trends has no generally available public API. Export interest-over-time "
            "from the Trends UI and import it as CSV, or use the approved official alpha."
        ),
        "usage_rights": "manual_research",
        "docs_url": "https://developers.google.com/search/apis/trends",
        "terms_url": "https://policies.google.com/terms",
        "config": {"geo": "AU", "mode": "manual_csv"},
    },
    {
        "provider_key": "google_bigquery_trends",
        "provider_name": "Google Trends public BigQuery dataset",
        "source_type": "search_trend",
        "enabled": False,
        "is_synthetic": False,
        "cost_model": "free",
        "monthly_cost": 0,
        "availability": "requires_credentials",
        "availability_reason": (
            "Set GOOGLE_APPLICATION_CREDENTIALS and install the optional google-cloud-bigquery "
            "package. BigQuery public-data queries run in your own project."
        ),
        "usage_rights": "api_terms",
        "docs_url": "https://developers.google.com/search/apis/trends",
        "terms_url": "https://cloud.google.com/bigquery/public-data",
        "secret_ref": "GOOGLE_APPLICATION_CREDENTIALS",
        "rate_limit_per_min": 6,
        "config": {"geo": "AU", "max_terms_per_run": 250, "history_days": 35},
    },
    {
        "provider_key": "google_trends_dataforseo",
        "provider_name": "Google Trends via DataForSEO (authorised API)",
        "source_type": "search_trend",
        "enabled": False,
        "is_synthetic": False,
        "cost_model": "paid",
        "monthly_cost": 0,
        "availability": "requires_credentials",
        "availability_reason": (
            "Set DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD. DataForSEO provides a "
            "documented Google Trends API under its terms; verify current pricing."
        ),
        "usage_rights": "api_terms",
        "docs_url": "https://docs.dataforseo.com/v3/keywords_data/google_trends/overview/",
        "terms_url": "https://dataforseo.com/terms-of-service",
        "secret_ref": "DATAFORSEO_LOGIN,DATAFORSEO_PASSWORD",
        "rate_limit_per_min": 12,
        "config": {
            "geo": "AU",
            "location_code": 2036,
            "time_range": "past_12_months",
            "max_keywords_per_run": 10,
            "history_days": 365,
        },
    },
    {
        "provider_key": "ebay_au",
        "provider_name": "eBay Australia (Browse API)",
        "source_type": "marketplace",
        "enabled": False,
        "is_synthetic": False,
        "cost_model": "free",
        "monthly_cost": 0,
        "availability": "requires_credentials",
        "availability_reason": "Set EBAY_CLIENT_ID and EBAY_CLIENT_SECRET. Active listings only; no sold data.",
        "usage_rights": "api_terms",
        "docs_url": "https://developer.ebay.com/api-docs/buy/browse/overview.html",
        "terms_url": "https://developer.ebay.com/terms/api-license",
        "secret_ref": "EBAY_CLIENT_ID,EBAY_CLIENT_SECRET",
        "rate_limit_per_min": 30,
        "config": {
            "marketplace_id": "EBAY_AU",
            "covers_sold_data": False,
            "max_keywords_per_run": 10,
            "listings_per_keyword": 50,
            "max_pages_per_keyword": 1,
            "geo": "AU",
        },
    },
    {
        "provider_key": "meta_ad_library",
        "provider_name": "Meta Ad Library (official API)",
        "source_type": "advertising",
        "enabled": False,
        "is_synthetic": False,
        "cost_model": "free",
        "monthly_cost": 0,
        "availability": "requires_credentials",
        "availability_reason": "Set META_AD_LIBRARY_TOKEN. Advertising activity only, not social engagement.",
        "usage_rights": "api_terms",
        "docs_url": "https://www.facebook.com/ads/library/api/",
        "terms_url": "https://www.facebook.com/legal/terms",
        "secret_ref": "META_AD_LIBRARY_TOKEN",
        "rate_limit_per_min": 30,
        "config": {"geo": "AU", "max_keywords_per_run": 10, "ads_per_keyword": 100, "max_pages_per_keyword": 1},
    },
    {
        "provider_key": "amazon_public_research",
        "provider_name": "Amazon public research (manual)",
        "source_type": "marketplace",
        "enabled": False,
        "is_synthetic": False,
        "cost_model": "manual",
        "monthly_cost": 0,
        "availability": "manual_fallback",
        "availability_reason": (
            "Amazon Australia exposes no first-party product API to this account. "
            "Use manual research or CSV import; do not scrape protected pages."
        ),
        "usage_rights": "manual_research",
        "docs_url": "https://webservices.amazon.com/paapi5/documentation/",
        "terms_url": "https://www.amazon.com.au/gp/help/customer/display.html?nodeId=508088",
        "config": {"geo": "AU", "mode": "manual_research"},
    },
    {
        "provider_key": "tiktok",
        "provider_name": "TikTok Creative Center (manual research)",
        "source_type": "social",
        "enabled": False,
        "is_synthetic": False,
        "cost_model": "free",
        "monthly_cost": 0,
        "availability": "manual_fallback",
        "availability_reason": (
            "TikTok Creative Center has no permitted public API for Australia. "
            "Record social signals manually; do not scrape or bypass signing controls."
        ),
        "usage_rights": "manual_research",
        "docs_url": "https://ads.tiktok.com/business/creativecenter/",
        "terms_url": "https://www.tiktok.com/legal/page/row/terms-of-service/en",
        "config": {"geo": "AU", "mode": "manual_research"},
    },
    {
        "provider_key": "amazon_au",
        "provider_name": "Amazon Australia (legacy unavailable)",
        "source_type": "marketplace",
        "enabled": False,
        "is_synthetic": False,
        "cost_model": "free",
        "monthly_cost": 0,
        "availability": "unavailable",
        "availability_reason": (
            "No first-party product API for amazon.com.au; PA-API has no AU domain. "
            "Use the manual research source instead."
        ),
        "usage_rights": "unspecified",
        "config": {"available": False},
    },
    {
        "provider_key": "exploding_topics",
        "provider_name": "Exploding Topics (optional paid plugin)",
        "source_type": "trend_discovery",
        "enabled": False,
        "is_synthetic": False,
        "cost_model": "paid",
        "monthly_cost": 0,
        "availability": "requires_credentials",
        "availability_reason": "Optional paid provider; verify current subscription and API terms before enabling.",
        "usage_rights": "api_terms",
        "secret_ref": "EXPLODING_TOPICS_API_KEY",
        "config": {"mode": "csv_first", "cost_note": "API access requires a paid plan; verify pricing."},
    },
    {
        "provider_key": "cj_dropshipping",
        "provider_name": "CJ Dropshipping (optional supplier plugin)",
        "source_type": "supplier",
        "enabled": False,
        "is_synthetic": False,
        "cost_model": "free",
        "monthly_cost": 0,
        "availability": "requires_credentials",
        "availability_reason": "Optional free supplier API; access is revoked after 30 days without transactions.",
        "usage_rights": "api_terms",
        "secret_ref": "CJ_API_KEY",
        "config": {"note": "Supplier catalogue, authorised API only."},
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
    existing = {source.provider_key: source for source in db.execute(select(DataSource)).scalars()}
    created = 0
    metadata_fields = (
        "provider_name",
        "source_type",
        "is_synthetic",
        "cost_model",
        "monthly_cost",
        "cost_currency",
        "request_limit_month",
        "availability",
        "availability_reason",
        "usage_rights",
        "docs_url",
        "terms_url",
    )
    for definition in SOURCE_REGISTRY:
        source = existing.get(definition["provider_key"])
        if source is None:
            db.add(
                DataSource(
                    provider_key=definition["provider_key"],
                    provider_name=definition["provider_name"],
                    source_type=definition["source_type"],
                    enabled=definition.get("enabled", False),
                    is_synthetic=definition.get("is_synthetic", False),
                    config=definition.get("config", {}),
                    secret_ref=definition.get("secret_ref"),
                    cost_model=definition.get("cost_model", "free"),
                    monthly_cost=definition.get("monthly_cost", 0),
                    cost_currency=definition.get("cost_currency", "AUD"),
                    request_limit_month=definition.get("request_limit_month"),
                    availability=definition.get("availability", "available"),
                    availability_reason=definition.get("availability_reason"),
                    usage_rights=definition.get("usage_rights", "unspecified"),
                    docs_url=definition.get("docs_url"),
                    terms_url=definition.get("terms_url"),
                    rate_limit_per_min=definition.get("rate_limit_per_min", 60),
                )
            )
            created += 1
            continue
        # Descriptive metadata is seed-owned; operator choices (enabled,
        # config, rate limit and secret reference) are not overwritten. This
        # lets an existing Phase 1 database adopt the free-first registry on the
        # next seed without losing its local settings.
        for field in metadata_fields:
            if field in definition:
                setattr(source, field, definition[field])
        if source.secret_ref is None and definition.get("secret_ref"):
            source.secret_ref = definition["secret_ref"]
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
