"""Weekly research report generation and CSV exports."""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Category,
    DataSource,
    OpportunityScore,
    Product,
    ProductMetric,
    ResearchReport,
    TrendObservation,
    WatchlistEntry,
)
from app.services.catalog import top_rows
from app.services.presenters import DISCLAIMER, public_score

LIMITATIONS = [
    "amazon_au unavailable: no first-party product API for the Australian marketplace",
    "tiktok unavailable: Creative Center is not accessible from Australia",
    "marketplace data covers active listings only, not sales",
]

MISSING_REPORT_REASONS = {
    "no_source": "no observation source",
    "insufficient_current_data": "current window too thin",
    "insufficient_baseline": "baseline window too thin",
    "zero_baseline": "baseline average is zero",
    "stale_data": "latest observation is stale",
}


def _row_item(row) -> dict:
    metric = row.metric
    score = row.score
    return {
        "product_id": str(row.product.id),
        "name": row.product.name,
        "slug": row.product.slug,
        "category": row.category.name if row.category else None,
        "opportunity_score": public_score(score),
        "classification": score.classification if score else None,
        "growth_7d_pct": (
            float(metric.search_growth_7d_pct)
            if metric and metric.search_growth_7d_pct is not None
            else None
        ),
        "growth_30d_pct": (
            float(metric.search_growth_30d_pct)
            if metric and metric.search_growth_30d_pct is not None
            else None
        ),
        "growth_reason_30d": metric.growth_reason_30d if metric else "no_source",
        "competition_class": metric.competition_class if metric else "unknown",
        "trend_direction": metric.trend_direction if metric else "unknown",
        "estimated_margin_pct": (
            float(score.estimated_margin_pct)
            if score and score.estimated_margin_pct is not None
            else None
        ),
        "is_synthetic": bool(row.product.is_synthetic),
    }


def generate_weekly(
    db: Session,
    country: str,
    period_start: date,
    period_end: date,
) -> ResearchReport:
    now = datetime.now(timezone.utc)
    report = db.execute(
        select(ResearchReport).where(
            ResearchReport.report_type == "weekly_trends",
            ResearchReport.country == country,
            ResearchReport.period_start == period_start,
        )
    ).scalar_one_or_none()
    if report is None:
        report = ResearchReport(
            report_type="weekly_trends",
            country=country,
            period_start=period_start,
            period_end=period_end,
        )
        db.add(report)

    try:
        growth_rows = top_rows(
            db,
            "-growth_7d",
            limit=10,
            conditions=[
                ProductMetric.search_growth_7d_pct.is_not(None),
                Product.country == country,
            ],
        )
        opportunity_rows = top_rows(
            db,
            "-opportunity_score",
            limit=10,
            conditions=[
                OpportunityScore.classification.in_(("excellent", "strong")),
                Product.country == country,
            ],
        )
        emerging_rows = top_rows(
            db,
            "-growth_7d",
            limit=10,
            conditions=[
                Product.country == country,
                Product.first_seen_at >= datetime.combine(
                    period_end - timedelta(days=30), datetime.min.time(), timezone.utc
                ),
                ProductMetric.search_growth_7d_pct > 0,
            ],
        )

        new_products = int(
            db.execute(
                select(func.count(Product.id)).where(
                    Product.status == "active",
                    Product.country == country,
                    Product.first_seen_at
                    >= datetime.combine(period_start, datetime.min.time(), timezone.utc),
                )
            ).scalar()
            or 0
        )

        category_rows = db.execute(
            select(Category.name, func.count(Product.id))
            .join(Product, Product.category_id == Category.id)
            .where(Product.status == "active", Product.country == country)
            .group_by(Category.name)
            .order_by(func.count(Product.id).desc())
        ).all()

        watchlist_rows = db.execute(
            select(WatchlistEntry.status, func.count(WatchlistEntry.id))
            .group_by(WatchlistEntry.status)
        ).all()

        sources = []
        for source in db.execute(select(DataSource).order_by(DataSource.provider_key)).scalars():
            latest = db.execute(
                select(func.max(TrendObservation.observation_date)).where(
                    TrendObservation.source_id == source.id
                )
            ).scalar()
            sources.append(
                {
                    "provider_key": source.provider_key,
                    "provider_name": source.provider_name,
                    "collection_date": latest.isoformat() if latest else None,
                    "is_synthetic": bool(source.is_synthetic),
                    "sync_status": source.sync_status,
                }
            )

        latest_metric = (
            select(func.max(ProductMetric.as_of_date))
            .where(
                ProductMetric.product_id == Product.id,
                ProductMetric.as_of_date <= period_end,
            )
            .correlate(Product)
            .scalar_subquery()
        )
        missing = db.execute(
            select(ProductMetric.growth_reason_30d, func.count(ProductMetric.id))
            .select_from(Product)
            .join(
                ProductMetric,
                (ProductMetric.product_id == Product.id)
                & (ProductMetric.as_of_date == latest_metric),
            )
            .where(Product.status == "active", Product.country == country)
            .group_by(ProductMetric.growth_reason_30d)
        ).all()
        missing_counts = {
            reason: int(count)
            for reason, count in missing
            if reason and reason != "ok"
        }

        report.report_data = {
            "period": {"start": period_start.isoformat(), "end": period_end.isoformat()},
            "generated_at": now.isoformat(),
            "top_growth": [_row_item(row) for row in growth_rows],
            "top_opportunities": [_row_item(row) for row in opportunity_rows],
            "emerging": [_row_item(row) for row in emerging_rows],
            "new_products": new_products,
            "categories": [
                {"name": name, "product_count": int(count)}
                for name, count in category_rows
            ],
            "watchlist": {status: int(count) for status, count in watchlist_rows},
            "growth_unavailable": missing_counts,
            "sources": sources,
            "limitations": LIMITATIONS,
            "disclaimer": DISCLAIMER,
        }
        report.summary = (
            f"{len(growth_rows)} products with measurable 7-day growth, "
            f"{new_products} newly discovered and {len(opportunity_rows)} high-opportunity "
            f"products. {sum(missing_counts.values())} products had no usable 30-day "
            "growth comparison; those are excluded rather than shown as 0%."
        )
        report.sources = sources
        report.status = "ready"
        report.generated_at = now
        report.error = None
    except Exception as exc:  # noqa: BLE001 - persisted for operator visibility
        report.status = "failed"
        report.error = f"{type(exc).__name__}: {exc}"[:1000]
    db.commit()
    return report


def report_csv(report: ResearchReport) -> str:
    data = report.report_data or {}
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "section",
            "name",
            "category",
            "opportunity_score",
            "classification",
            "growth_7d_pct",
            "growth_30d_pct",
            "growth_reason_30d",
            "competition_class",
            "trend_direction",
            "estimated_margin_pct",
            "synthetic",
        ]
    )
    for section in ("top_growth", "top_opportunities", "emerging"):
        for item in data.get(section, []):
            writer.writerow(
                [
                    section,
                    item.get("name"),
                    item.get("category"),
                    item.get("opportunity_score"),
                    item.get("classification"),
                    item.get("growth_7d_pct"),
                    item.get("growth_30d_pct"),
                    item.get("growth_reason_30d"),
                    item.get("competition_class"),
                    item.get("trend_direction"),
                    item.get("estimated_margin_pct"),
                    item.get("is_synthetic"),
                ]
            )
    writer.writerow([])
    writer.writerow(["disclaimer", DISCLAIMER])
    return buffer.getvalue()
