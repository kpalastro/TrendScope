"""Authorised Google Trends connector (DataForSEO).

Google does not publish a general-purpose Trends API. DataForSEO is a
commercial provider with a documented Google Trends API and explicit terms; an
operator's own account and credentials are required. This connector never reads
the Google Trends website directly, never scrapes and never emulates a browser.

The API returns *relative search interest* (0-100), not search volume, sales or
units. Observations are labelled with the index unit and the provider's terms,
and they are stored per product and per date.

Docs: https://docs.dataforseo.com/v3/keywords_data/google_trends/overview/
Terms: https://dataforseo.com/terms-of-service
"""

from __future__ import annotations

import base64
import math
import os
import time
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import quote_plus

from app.connectors.base import ConnectorContext
from app.connectors.framework import (
    BaseConnector,
    ConnectorAuthError,
    ConnectorError,
    ConnectorNotConfigured,
    ConnectorRateLimitError,
    HealthResult,
    RawObservation,
    RawPayload,
)
from app.connectors.http import RetryPolicy, RetryingHttpClient

API_ROOT = "https://api.dataforseo.com/v3"
TRENDS_URL = f"{API_ROOT}/keywords_data/google_trends/explore/live"
USER_DATA_URL = f"{API_ROOT}/appendix/user_data"
TRENDS_PUBLIC_URL = "https://trends.google.com/trends/explore"
COUNTRY_LOCATION_CODES = {
    "AU": 2036,
    "NZ": 2554,
    "US": 2840,
    "GB": 2826,
    "CA": 2124,
}
GRANULARITY_BY_RANGE = {
    "past_7_days": "daily",
    "past_30_days": "daily",
    "past_90_days": "daily",
    "past_12_months": "weekly",
    "past_5_years": "monthly",
}


class DataForSEOTrendsConnector(BaseConnector):
    provider_key = "google_trends_dataforseo"
    provider_name = "Google Trends via DataForSEO (authorised API)"
    source_type = "search_trend"
    cost_model = "paid"
    default_availability = "available"
    requires_credentials = True
    credential_names = ("DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD")
    docs_url = "https://docs.dataforseo.com/v3/keywords_data/google_trends/overview/"
    terms_url = "https://dataforseo.com/terms-of-service"
    usage_rights = "api_terms"

    def __init__(
        self,
        transport: Any = None,
        sleep: Any = None,
        policy: RetryPolicy | None = None,
    ) -> None:
        super().__init__()
        self._transport = transport
        self._sleep = sleep
        self._policy = policy or RetryPolicy()

    # -- lifecycle ---------------------------------------------------------

    def fetch_data(self, ctx: ConnectorContext) -> RawPayload:
        login = os.environ.get("DATAFORSEO_LOGIN")
        password = os.environ.get("DATAFORSEO_PASSWORD")
        if not login or not password:
            raise ConnectorNotConfigured(
                "Set DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD to use the authorised "
                "Google Trends connector."
            )

        geo = str(ctx.config.get("geo") or "AU").upper()
        location_code = int(
            ctx.config.get("location_code") or COUNTRY_LOCATION_CODES.get(geo, 2036)
        )
        language_code = str(ctx.config.get("language_code") or "en")
        time_range = str(ctx.config.get("time_range") or "past_12_months")
        granularity = GRANULARITY_BY_RANGE.get(time_range, "weekly")
        max_keywords = max(1, min(int(ctx.config.get("max_keywords_per_run") or 10), 50))

        records: list[RawObservation] = []
        warnings: list[str] = []
        requests = 0
        seen: set[tuple[str, date]] = set()

        with self._client(ctx.timeout_seconds) as client:
            retry_stats = client.stats
            for product in ctx.products[:max_keywords]:
                terms = product.search_terms()
                term = terms[0] if terms else product.name
                payload = [
                    {
                        "keywords": [term],
                        "location_code": location_code,
                        "language_code": language_code,
                        "time_range": time_range,
                        "type": "web",
                    }
                ]
                try:
                    response = client.post(TRENDS_URL, json=payload)
                    requests += 1
                    body = self._parse_response(response)
                except ConnectorError as exc:
                    warnings.append(f"{product.name}: {exc}")
                    continue

                points = _graph_points(body)
                if not points:
                    warnings.append(
                        f"{product.name}: DataForSEO returned no interest-over-time points."
                    )
                    continue
                source_url = (
                    f"{TRENDS_PUBLIC_URL}?date={quote_plus(time_range)}"
                    f"&geo={quote_plus(geo)}&q={quote_plus(term)}"
                )
                for point in points:
                    day = _point_date(point)
                    value = _point_value(point)
                    if day is None or value is None:
                        continue
                    key = (product.external_id, day)
                    if key in seen:
                        continue
                    seen.add(key)
                    period_end = _as_date(point.get("date_to")) or day
                    records.append(
                        RawObservation(
                            external_id=product.external_id,
                            observation_date=day,
                            period_start=day,
                            period_end=period_end,
                            metric_name="google_trends_interest",
                            metric_type="search_interest",
                            metric_value=value,
                            unit="index",
                            granularity=granularity,
                            confidence=0.85,
                            original_metric="Google Trends interest over time (0-100)",
                            source_url=source_url,
                            verification_status="verified",
                            data_quality="high",
                            source_timestamp=datetime.now(timezone.utc),
                            meta={
                                "provider": "google_trends_dataforseo",
                                "query": term,
                                "geo": geo,
                                "location_code": location_code,
                                "time_range": time_range,
                                "relative_index": True,
                                "note": (
                                    "Relative search interest (0-100), not search volume "
                                    "or sales. Sourced through DataForSEO's documented API."
                                ),
                            },
                        )
                    )

        return RawPayload(
            records=records,
            source_url=TRENDS_PUBLIC_URL,
            request_count=requests,
            warnings=warnings,
            metadata={
                "provider": "google_trends_dataforseo",
                "geo": geo,
                "time_range": time_range,
                "retry": retry_stats.as_dict(),
            },
        )

    def probe(self, source: Any) -> HealthResult:
        login = os.environ.get("DATAFORSEO_LOGIN")
        password = os.environ.get("DATAFORSEO_PASSWORD")
        if not login or not password:
            return HealthResult(
                status="unconfigured",
                ok=False,
                message="DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD are not set.",
                live=True,
            )
        started = time.perf_counter()
        try:
            with self._client(10.0) as client:
                response = client.get(USER_DATA_URL)
            latency = int((time.perf_counter() - started) * 1000)
            if response.status_code in (401, 403):
                return HealthResult(
                    status="degraded",
                    ok=False,
                    message="DataForSEO rejected the credentials.",
                    latency_ms=latency,
                    http_status=response.status_code,
                    live=True,
                )
            if response.status_code >= 400:
                return HealthResult(
                    status="degraded",
                    ok=False,
                    message=f"DataForSEO returned HTTP {response.status_code}.",
                    latency_ms=latency,
                    http_status=response.status_code,
                    live=True,
                )
            body = response.json()
            if int(body.get("status_code") or 0) != 20000:
                return HealthResult(
                    status="degraded",
                    ok=False,
                    message=str(body.get("status_message") or "DataForSEO rejected the check.")[
                        :500
                    ],
                    latency_ms=latency,
                    http_status=response.status_code,
                    live=True,
                )
            return HealthResult(
                status="healthy",
                ok=True,
                message="Authenticated with DataForSEO; API account reachable.",
                latency_ms=latency,
                http_status=response.status_code,
                details={"account": _account_summary(body)},
                live=True,
            )
        except Exception as exc:  # noqa: BLE001 - health checks must not raise
            latency = int((time.perf_counter() - started) * 1000)
            return HealthResult(
                status="degraded",
                ok=False,
                message=f"DataForSEO probe failed: {type(exc).__name__}: {exc}"[:500],
                latency_ms=latency,
                live=True,
            )

    # -- helpers -----------------------------------------------------------

    def _client(self, timeout_seconds: float) -> RetryingHttpClient:
        login = os.environ.get("DATAFORSEO_LOGIN") or ""
        password = os.environ.get("DATAFORSEO_PASSWORD") or ""
        encoded = base64.b64encode(f"{login}:{password}".encode()).decode()
        kwargs = {
            "timeout": timeout_seconds,
            "headers": self._headers(
                Authorization=f"Basic {encoded}", **{"Content-Type": "application/json"}
            ),
            "transport": self._transport,
            "policy": self._policy,
        }
        if self._sleep is not None:
            kwargs["sleep"] = self._sleep
        return RetryingHttpClient(**kwargs)

    @staticmethod
    def _parse_response(response: Any) -> dict:
        if response.status_code in (401, 403):
            raise ConnectorAuthError(
                f"DataForSEO rejected the credentials (HTTP {response.status_code})."
            )
        if response.status_code == 429:
            raise ConnectorRateLimitError(
                "DataForSEO rate limit reached; the sync will retry later."
            )
        if response.status_code >= 400:
            raise ConnectorError(
                f"DataForSEO API returned HTTP {response.status_code}."
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise ConnectorError("DataForSEO returned a non-JSON response.") from exc
        code = int(body.get("status_code") or 0)
        if code == 20000:
            return body
        message = str(body.get("status_message") or "DataForSEO request failed.")[:500]
        if code in (40100, 40101, 40102):
            raise ConnectorAuthError(message)
        if code in (40200, 40201, 40202):
            raise ConnectorAuthError(f"DataForSEO account/payment issue: {message}")
        if code in (42900, 42901):
            raise ConnectorRateLimitError(message)
        raise ConnectorError(f"DataForSEO error {code}: {message}")


def _graph_points(body: dict) -> list[dict]:
    """Return the interest-over-time points from a DataForSEO response."""
    points: list[dict] = []
    for task in body.get("tasks") or []:
        if int(task.get("status_code") or 0) not in (20000, 0):
            continue
        for result in task.get("result") or []:
            for item in result.get("items") or []:
                data = item.get("data")
                if isinstance(data, list) and data:
                    for point in data:
                        if isinstance(point, dict):
                            points.append(point)
    return points


def _point_value(point: dict) -> float | None:
    values = point.get("values")
    raw: Any = None
    if isinstance(values, list) and values:
        raw = values[0]
    elif "value" in point:
        raw = point.get("value")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return value


def _point_date(point: dict) -> date | None:
    day = _as_date(point.get("date_from"))
    if day is not None:
        return day
    timestamp = point.get("timestamp")
    if timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(float(timestamp), tz=timezone.utc).date()
    except (TypeError, ValueError, OSError):
        return None


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _account_summary(body: dict) -> dict:
    tasks = body.get("tasks") or []
    if not tasks or not isinstance(tasks[0], dict):
        return {}
    result = tasks[0].get("result")
    if isinstance(result, list) and result and isinstance(result[0], dict):
        return {
            key: result[0].get(key)
            for key in ("login", "money", "rate_limits", "timezone")
            if key in result[0]
        }
    return {}
