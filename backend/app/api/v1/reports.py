from __future__ import annotations

import csv
import io
from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response
from sqlalchemy import select

from app.api.deps import AdminUser, CurrentUser, DbSession, WriteUser
from app.core.errors import ApiError
from app.models import ResearchReport
from app.schemas import ReportCreate
from app.services.catalog import list_payload, query_products
from app.services.reports import generate_weekly, report_csv

router = APIRouter(tags=["reports"])


def _report_payload(report: ResearchReport) -> dict:
    return {
        "id": report.id,
        "report_type": report.report_type,
        "country": report.country,
        "period_start": report.period_start,
        "period_end": report.period_end,
        "status": report.status,
        "summary": report.summary,
        "report_data": report.report_data or {},
        "sources": report.sources or [],
        "generated_at": report.generated_at,
        "error": report.error,
    }


@router.get("/reports")
def list_reports(
    user: CurrentUser,
    db: DbSession,
    type: str | None = None,
    country: str | None = None,
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
) -> dict:
    stmt = select(ResearchReport).order_by(ResearchReport.period_start.desc())
    if type:
        stmt = stmt.where(ResearchReport.report_type == type)
    if country:
        stmt = stmt.where(ResearchReport.country == country)
    if from_date:
        stmt = stmt.where(ResearchReport.period_start >= from_date)
    if to_date:
        stmt = stmt.where(ResearchReport.period_end <= to_date)
    reports = db.execute(stmt).scalars().all()
    return {"data": [_report_payload(report) for report in reports], "meta": {"total": len(reports)}}


@router.post("/reports", status_code=201)
def create_report(payload: ReportCreate, user: WriteUser, db: DbSession) -> dict:
    if payload.period_end < payload.period_start:
        raise ApiError(422, "VALIDATION_ERROR", "period_end must not precede period_start.")
    report = generate_weekly(
        db, payload.country.upper(), payload.period_start, payload.period_end
    )
    return _report_payload(report)


@router.get("/reports/{report_id}")
def get_report(report_id: UUID, user: CurrentUser, db: DbSession) -> dict:
    report = db.get(ResearchReport, report_id)
    if report is None:
        raise ApiError(404, "NOT_FOUND", "Report not found.")
    return _report_payload(report)


@router.get("/reports/{report_id}/download")
def download_report(
    report_id: UUID,
    user: CurrentUser,
    db: DbSession,
    format: Literal["csv", "json"] = "csv",
) -> Response:
    import json

    report = db.get(ResearchReport, report_id)
    if report is None:
        raise ApiError(404, "NOT_FOUND", "Report not found.")
    if format == "json":
        content = json.dumps(_report_payload(report), indent=2, default=str)
        media_type = "application/json"
        filename = f"trendscope-report-{report.period_start}.json"
    else:
        content = report_csv(report)
        media_type = "text/csv"
        filename = f"trendscope-report-{report.period_start}.csv"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/reports/{report_id}", status_code=204)
def delete_report(report_id: UUID, user: AdminUser, db: DbSession) -> Response:
    report = db.get(ResearchReport, report_id)
    if report is None:
        raise ApiError(404, "NOT_FOUND", "Report not found.")
    db.delete(report)
    db.commit()
    return Response(status_code=204)


@router.get("/exports/products")
def export_products(
    user: CurrentUser,
    db: DbSession,
    q: str | None = None,
    country: str | None = "AU",
    category_id: UUID | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
    min_growth_7d: float | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    min_margin: float | None = None,
    supplier_available: bool | None = None,
    trend_direction: str | None = None,
    competition: Annotated[list[str] | None, Query()] = None,
    synthetic: Literal["include", "exclude", "only"] = "include",
    sort: str | None = "-opportunity_score",
) -> Response:
    params = {
        "q": q,
        "country": country,
        "category_id": category_id,
        "status": "active",
        "min_score": min_score,
        "max_score": max_score,
        "min_growth_7d": min_growth_7d,
        "min_price": min_price,
        "max_price": max_price,
        "min_margin": min_margin,
        "supplier_available": supplier_available,
        "trend_direction": trend_direction,
        "competition": competition,
        "synthetic": synthetic,
        "sort": sort,
    }
    # query_products caps per_page at 100; walk the pages so an export is the
    # whole filtered catalogue rather than an arbitrary first page.
    rows = []
    page = 1
    while True:
        batch, total = query_products(db, params, page=page, per_page=100)
        rows.extend(batch)
        if not batch or len(rows) >= total or page >= 100:
            break
        page += 1
    payload = list_payload(db, rows)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "id",
            "name",
            "slug",
            "category",
            "brand",
            "opportunity_score",
            "classification",
            "growth_7d_pct",
            "growth_30d_pct",
            "growth_90d_pct",
            "competition_class",
            "trend_direction",
            "estimated_margin_pct",
            "price_min",
            "price_max",
            "price_avg",
            "coverage_pct",
            "confidence",
            "synthetic",
        ]
    )
    for item in payload:
        writer.writerow(
            [
                item["id"],
                item["name"],
                item["slug"],
                (item["category"] or {}).get("name"),
                item["brand"],
                item["opportunity_score"],
                item["classification"],
                item["growth"]["d7"]["pct"],
                item["growth"]["d30"]["pct"],
                item["growth"]["d90"]["pct"],
                item["competition_class"],
                item["trend_direction"],
                item["estimated_margin_pct"],
                item["price_range"]["min"],
                item["price_range"]["max"],
                item["price_range"]["market_avg"],
                item["data_quality"]["coverage_pct"],
                item["data_quality"]["confidence"],
                item["data_quality"]["synthetic"],
            ]
        )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="trendscope-products.csv"'},
    )
