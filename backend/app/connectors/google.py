"""Google search-interest connectors.

There is no generally available public Google Trends API. ``GoogleTrendsConnector``
therefore represents the permitted manual workflow (CSV export or the official
alpha, once granted). ``GoogleBigQueryTrendsConnector`` reads Google's public
BigQuery trends dataset under the operator's own Google Cloud project; it is
free to query within BigQuery's free tier and requires no marketplace
subscription.

Neither connector claims absolute search volume. The public dataset exposes
rank/score, which is relative search interest, not sales.
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any

from app.connectors.base import ConnectorContext
from app.connectors.framework import (
    BaseConnector,
    ConnectorError,
    ConnectorUnavailable,
    HealthResult,
    RawObservation,
    RawPayload,
)
from app.services.normalise import normalise_name

TRENDS_DATASET_URL = "https://console.cloud.google.com/marketplace/details/google/bigquery-public-data.google_trends"


class GoogleTrendsConnector(BaseConnector):
    provider_key = "google_trends"
    provider_name = "Google Trends (manual / official alpha)"
    source_type = "search_trend"
    cost_model = "free"
    default_availability = "manual_fallback"
    availability_reason = (
        "Google Trends has no generally available public API. Export interest-over-time "
        "from the Trends UI and import it as CSV, or use the approved official alpha when "
        "access is granted."
    )
    docs_url = "https://developers.google.com/search/apis/trends"
    terms_url = "https://policies.google.com/terms"
    usage_rights = "manual_research"

    def fetch_data(self, ctx: ConnectorContext) -> RawPayload:
        raise ConnectorUnavailable(self.availability_reason or "Google Trends API unavailable.")


class GoogleBigQueryTrendsConnector(BaseConnector):
    provider_key = "google_bigquery_trends"
    provider_name = "Google Trends public BigQuery dataset"
    source_type = "search_trend"
    cost_model = "free"
    default_availability = "available"
    requires_credentials = True
    credential_names = ("GOOGLE_APPLICATION_CREDENTIALS",)
    docs_url = "https://developers.google.com/search/apis/trends"
    terms_url = "https://cloud.google.com/bigquery/public-data"
    usage_rights = "api_terms"

    def fetch_data(self, ctx: ConnectorContext) -> RawPayload:
        try:
            from google.cloud import bigquery  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - depends on optional install
            raise ConnectorUnavailable(
                "The optional google-cloud-bigquery package is not installed. "
                "Install it from backend/requirements-optional.txt to use this connector."
            ) from exc

        source_url = TRENDS_DATASET_URL
        query = """
            SELECT country_code, term, rank, score, week
            FROM `bigquery-public-data.google_trends.international_top_rising_terms`
            WHERE country_code = @country
              AND week >= @since
            ORDER BY week DESC, rank ASC
            LIMIT @limit
        """
        country = str(ctx.config.get("geo") or "AU").upper()
        limit = int(ctx.config.get("max_terms_per_run") or 250)
        params = [
            bigquery.ScalarQueryParameter("country", "STRING", country),
            bigquery.ScalarQueryParameter("since", "DATE", ctx.since),
            bigquery.ScalarQueryParameter("limit", "INT64", max(1, min(limit, 1000))),
        ]
        try:
            client = bigquery.Client()
            job_config = bigquery.QueryJobConfig(query_parameters=params)
            rows = list(client.query(query, job_config=job_config).result())
        except Exception as exc:  # noqa: BLE001 - provider/SDK failures share one path
            raise ConnectorError(
                f"BigQuery trends query failed: {type(exc).__name__}: {exc}"[:1000]
            ) from exc

        products_by_term: dict[str, list[Any]] = {}
        for product in ctx.products:
            for term in product.search_terms():
                key = normalise_name(term)
                if key:
                    products_by_term.setdefault(key, []).append(product)

        records: list[RawObservation] = []
        seen: set[tuple[str, date]] = set()
        unmatched = 0
        for row in rows:
            term = str(getattr(row, "term", "") or "")
            week = _as_date(getattr(row, "week", None))
            if not term or week is None:
                continue
            matches = products_by_term.get(normalise_name(term), [])
            if not matches:
                unmatched += 1
                continue
            rank = getattr(row, "rank", None)
            if rank is None:
                continue
            for product in matches:
                key = (product.external_id, week)
                if key in seen:
                    continue
                seen.add(key)
                records.append(
                    RawObservation(
                        external_id=product.external_id,
                        observation_date=week,
                        period_start=week,
                        period_end=week + timedelta(days=6),
                        metric_name="search_trend_rank",
                        metric_type="search_interest",
                        metric_value=float(rank),
                        unit="rank",
                        granularity="weekly",
                        confidence=0.7,
                        original_metric="rank",
                        source_url=source_url,
                        verification_status="verified",
                        data_quality="high",
                        meta={
                            "provider": "google_bigquery_trends",
                            "term": term,
                            "country_code": country,
                            "score": getattr(row, "score", None),
                            "dataset": "bigquery-public-data.google_trends.international_top_rising_terms",
                            "note": "Relative search rank, not search volume or sales.",
                        },
                    )
                )

        return RawPayload(
            records=records,
            source_url=source_url,
            request_count=1,
            warnings=(
                [f"{unmatched} rising term(s) did not match a tracked keyword."]
                if unmatched
                else []
            ),
            metadata={"rows_returned": len(rows), "matched_products": len(seen)},
        )

    def probe(self, source: Any) -> HealthResult:
        if self.get_source_status(source).state == "requires_credentials":
            return HealthResult(
                status="unconfigured",
                ok=False,
                message="GOOGLE_APPLICATION_CREDENTIALS is not set.",
                live=True,
            )
        started = time.perf_counter()
        try:
            from google.cloud import bigquery  # type: ignore[import-not-found]
        except ImportError:
            return HealthResult(
                status="unavailable",
                ok=False,
                message=(
                    "google-cloud-bigquery is not installed; install the optional "
                    "requirements to use this connector."
                ),
                live=True,
            )
        try:
            client = bigquery.Client()
            # A dry run validates credentials and dataset access at no query cost.
            job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
            client.query(
                "SELECT 1 FROM `bigquery-public-data.google_trends."
                "international_top_rising_terms` LIMIT 1",
                job_config=job_config,
            )
            latency = int((time.perf_counter() - started) * 1000)
            return HealthResult(
                status="healthy",
                ok=True,
                message="BigQuery credentials and public trends dataset are reachable.",
                latency_ms=latency,
                details={"dataset": TRENDS_DATASET_URL, "dry_run": True},
                live=True,
            )
        except Exception as exc:  # noqa: BLE001 - health checks must not raise
            latency = int((time.perf_counter() - started) * 1000)
            return HealthResult(
                status="degraded",
                ok=False,
                message=f"BigQuery probe failed: {type(exc).__name__}: {exc}"[:500],
                latency_ms=latency,
                live=True,
            )


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value)
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None
