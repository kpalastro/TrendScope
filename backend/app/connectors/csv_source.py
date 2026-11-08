"""CSV import connector.

CSV is the universal free fallback. Product import already has its own upload
endpoint; this connector also normalises observation rows so operator-supplied
research (Google Trends exports, marketplace screenshots transcribed by hand,
supplier quotes) enters the same append-only history with full provenance.

It never fetches from a network and never claims a CSV row is a live observation.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any, Iterable

from app.connectors.base import ConnectorContext
from app.connectors.framework import (
    BaseConnector,
    ConnectorUnavailable,
    RawObservation,
    RawPayload,
    ValidationResult,
)
from app.models import DATA_QUALITY_LEVELS, METRIC_TYPES, VERIFICATION_STATUSES

OBSERVATION_COLUMNS = [
    "product",
    "metric_name",
    "metric_type",
    "value",
    "unit",
    "observation_date",
    "period_start",
    "period_end",
    "source_url",
    "verification_status",
    "data_quality",
    "notes",
]


class CSVImportConnector(BaseConnector):
    provider_key = "csv_import"
    provider_name = "Manual CSV / spreadsheet import"
    source_type = "manual_upload"
    cost_model = "manual"
    default_availability = "available"
    docs_url = None
    terms_url = None
    usage_rights = "manual_research"

    def fetch_data(self, ctx: ConnectorContext) -> RawPayload:
        raise ConnectorUnavailable(
            "CSV import is an upload workflow. Use POST /products/import/csv for "
            "products or POST /products/import/observations/csv for research observations."
        )

    def validate_data(self, payload: RawPayload) -> ValidationResult:
        return super().validate_data(payload)

    def observations_from_rows(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        external_id_for: dict[str, str],
        country: str = "AU",
        source_url: str | None = None,
    ) -> tuple[list[RawObservation], list[dict]]:
        """Convert manual-research rows to observations.

        ``rows`` are keyed by the column names in ``OBSERVATION_COLUMNS``.
        ``external_id_for`` maps a normalised product name/slug to the product's
        connector external id. Unmatched products produce a row-level error.
        """
        records: list[RawObservation] = []
        errors: list[dict] = []
        for index, row in enumerate(rows, start=2):
            product_key = str(row.get("product") or "").strip()
            external_id = external_id_for.get(product_key.lower())
            if not external_id:
                errors.append({"row": index, "issue": f"unknown product: {product_key or '(blank)'}"})
                continue
            try:
                value = float(str(row.get("value") or "").replace(",", ""))
            except ValueError:
                errors.append({"row": index, "issue": "value is not a number"})
                continue
            if not math.isfinite(value):
                errors.append({"row": index, "issue": "value is not finite"})
                continue
            try:
                observation_date = date.fromisoformat(str(row.get("observation_date") or ""))
            except ValueError:
                errors.append({"row": index, "issue": "observation_date must be YYYY-MM-DD"})
                continue
            if observation_date > date.today():
                errors.append({"row": index, "issue": "observation_date is in the future"})
                continue
            metric_name = str(row.get("metric_name") or "").strip()
            if not metric_name:
                errors.append({"row": index, "issue": "metric_name is required"})
                continue
            metric_type = str(row.get("metric_type") or "").strip() or None
            if metric_type and metric_type not in METRIC_TYPES:
                errors.append({"row": index, "issue": f"unknown metric_type: {metric_type}"})
                continue
            verification = str(row.get("verification_status") or "unverified").strip()
            if verification not in VERIFICATION_STATUSES:
                errors.append({"row": index, "issue": f"unknown verification_status: {verification}"})
                continue
            quality = str(row.get("data_quality") or "unknown").strip()
            if quality not in DATA_QUALITY_LEVELS:
                errors.append({"row": index, "issue": f"unknown data_quality: {quality}"})
                continue
            records.append(
                RawObservation(
                    external_id=external_id,
                    observation_date=observation_date,
                    period_start=_date(row.get("period_start")) or observation_date,
                    period_end=_date(row.get("period_end")) or observation_date,
                    metric_name=metric_name[:60],
                    metric_type=metric_type,
                    metric_value=value,
                    unit=str(row.get("unit") or "").strip() or "index",
                    granularity="daily",
                    confidence=0.8 if verification == "verified" else 0.6,
                    source_url=str(row.get("source_url") or "").strip() or source_url,
                    verification_status=verification,
                    data_quality=quality,
                    original_metric=metric_name,
                    meta={
                        "origin": "csv_observation_import",
                        "country": country,
                        "notes": str(row.get("notes") or "").strip()[:1000] or None,
                    },
                )
            )
        return records, errors


def _date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None
