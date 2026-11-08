from __future__ import annotations

from datetime import date, datetime, timezone
from io import BytesIO
from types import SimpleNamespace

from openpyxl import load_workbook

from app.services.reports import csv_safe, report_csv, report_xlsx


def _report(**overrides):
    data = {
        "period": {"start": "2026-11-01", "end": "2026-11-08"},
        "top_growth": [
            {
                "name": "=HYPERLINK(\"http://evil\")",
                "category": "home-kitchen",
                "opportunity_score": 78,
                "classification": "strong",
                "growth_7d_pct": 12.5,
                "growth_30d_pct": 20.0,
                "growth_reason_30d": "ok",
                "competition_class": "moderate",
                "trend_direction": "rising",
                "estimated_margin_pct": 25.0,
                "is_synthetic": False,
            }
        ],
        "top_opportunities": [],
        "emerging": [],
        "new_products": 2,
        "sources": [
            {
                "provider_key": "mock",
                "provider_name": "Demo",
                "collection_date": "2026-11-08",
                "is_synthetic": True,
                "sync_status": "ok",
            }
        ],
        "limitations": ["listings are not sales"],
        "disclaimer": "Estimate only.",
    }
    data.update(overrides.pop("report_data", {}))
    return SimpleNamespace(
        report_type="weekly_trends",
        country="AU",
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 8),
        status="ready",
        generated_at=datetime(2026, 11, 8, tzinfo=timezone.utc),
        summary="Summary text",
        report_data=data,
        **overrides,
    )


def test_csv_safe_neutralises_formula_prefixes():
    assert csv_safe("=SUM(A1:A2)") == "'=SUM(A1:A2)"
    assert csv_safe("+61 400") == "'+61 400"
    assert csv_safe("@handle") == "'@handle"
    assert csv_safe(-12.5) == -12.5
    assert csv_safe(None) is None
    assert csv_safe("Silicone Tray") == "Silicone Tray"


def test_report_csv_escapes_formula_injection():
    text = report_csv(_report())
    assert "'=HYPERLINK" in text
    assert "disclaimer" in text


def test_report_xlsx_has_expected_sheets_and_rows():
    payload = report_xlsx(_report())
    workbook = load_workbook(BytesIO(payload))
    assert workbook.sheetnames == ["Summary", "Products", "Sources", "Limitations"]

    products = workbook["Products"]
    rows = list(products.values)
    assert rows[0][:3] == ("section", "name", "category")
    assert rows[1][1] == '=HYPERLINK("http://evil")'
    assert products.freeze_panes == "A2"

    summary = dict(workbook["Summary"].values)
    assert summary["Country"] == "AU"
    assert summary["New products"] == 2
