"""Meta Ad Library connector.

The Ad Library API is an official, free Meta API. It returns advertising
activity, **not** social engagement, sales or demand. This connector therefore
stores a metric of type ``advertising`` and never feeds it into the social or
demand score. A token is required and the operator is responsible for Meta's
platform terms.

Requests use the shared retrying client (429/5xx with backoff) and follow the
cursor Meta returns, up to a bounded number of pages.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date
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

GRAPH_URL = "https://graph.facebook.com/v20.0/ads_archive"
PUBLIC_SEARCH_URL = "https://www.facebook.com/ads/library/"


class MetaAdLibraryConnector(BaseConnector):
    provider_key = "meta_ad_library"
    provider_name = "Meta Ad Library (official API)"
    source_type = "advertising"
    cost_model = "free"
    default_availability = "available"
    requires_credentials = True
    credential_names = ("META_AD_LIBRARY_TOKEN",)
    docs_url = "https://www.facebook.com/ads/library/api/"
    terms_url = "https://www.facebook.com/legal/terms"
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

    def fetch_data(self, ctx: ConnectorContext) -> RawPayload:
        token = os.environ.get("META_AD_LIBRARY_TOKEN")
        if not token:
            raise ConnectorNotConfigured(
                "Set META_AD_LIBRARY_TOKEN to run the Meta Ad Library connector."
            )

        country = str(ctx.config.get("geo") or "AU").upper()
        max_keywords = max(1, min(int(ctx.config.get("max_keywords_per_run") or 10), 50))
        sample_limit = max(1, min(int(ctx.config.get("ads_per_keyword") or 100), 500))
        max_pages = max(1, min(int(ctx.config.get("max_pages_per_keyword") or 1), 5))
        records: list[RawObservation] = []
        warnings: list[str] = []
        requests = 0

        with self._client(ctx.timeout_seconds) as client:
            retry_stats = client.stats
            for product in ctx.products[:max_keywords]:
                terms = product.search_terms()
                term = terms[0] if terms else product.name
                ads: list[dict] = []
                pages_read = 0
                next_url: str | None = GRAPH_URL
                params: dict[str, Any] | None = {
                    "access_token": token,
                    "ad_reached_countries": json.dumps([country]),
                    "ad_active_status": "ACTIVE",
                    "search_terms": term,
                    "fields": "id,page_name,ad_delivery_start_time",
                    "limit": sample_limit,
                }
                while next_url and pages_read < max_pages:
                    try:
                        response = client.get(next_url, params=params)
                        requests += 1
                        self._raise_for_status(response)
                        body = response.json()
                    except ConnectorError as exc:
                        if pages_read == 0:
                            warnings.append(f"{product.name}: {exc}")
                        else:
                            warnings.append(
                                f"{product.name}: stopped after page {pages_read}: {exc}"
                            )
                        break
                    page_ads = body.get("data") or []
                    ads.extend(item for item in page_ads if isinstance(item, dict))
                    pages_read += 1
                    next_url = (body.get("paging") or {}).get("next")
                    # The next cursor already carries the token and filters.
                    params = None
                    if not page_ads:
                        break

                today = date.today()
                records.append(
                    RawObservation(
                        external_id=product.external_id,
                        observation_date=today,
                        period_start=today,
                        period_end=today,
                        metric_name="meta_active_ads",
                        metric_type="advertising",
                        metric_value=float(len(ads)),
                        unit="count",
                        confidence=0.7,
                        original_metric="active ads sampled from Ad Library search",
                        source_url=(
                            f"{PUBLIC_SEARCH_URL}?active_status=active&ad_type=all"
                            f"&country={country}&q={quote_plus(term)}"
                        ),
                        verification_status="verified",
                        data_quality="medium",
                        meta={
                            "provider": "meta_ad_library",
                            "country": country,
                            "query": term,
                            "sample_limit": sample_limit,
                            "pages_read": pages_read,
                            "sampled": True,
                            "note": (
                                "Active advertising activity sampled from the Ad Library, "
                                "not total demand, social engagement or sales."
                            ),
                        },
                    )
                )

        return RawPayload(
            records=records,
            source_url=PUBLIC_SEARCH_URL,
            request_count=requests,
            warnings=warnings,
            metadata={
                "country": country,
                "max_keywords": max_keywords,
                "max_pages_per_keyword": max_pages,
                "retry": retry_stats.as_dict(),
            },
        )

    def probe(self, source: Any) -> HealthResult:
        token = os.environ.get("META_AD_LIBRARY_TOKEN")
        if not token:
            return HealthResult(
                status="unconfigured",
                ok=False,
                message="META_AD_LIBRARY_TOKEN is not set.",
                live=True,
            )
        started = time.perf_counter()
        try:
            with self._client(10.0) as client:
                response = client.get(
                    GRAPH_URL,
                    params={
                        "access_token": token,
                        "ad_reached_countries": json.dumps(["AU"]),
                        "ad_active_status": "ACTIVE",
                        "search_terms": "test",
                        "fields": "id",
                        "limit": 1,
                    },
                )
            latency = int((time.perf_counter() - started) * 1000)
            if response.status_code >= 400:
                return HealthResult(
                    status="degraded",
                    ok=False,
                    message=self._error_message(response),
                    latency_ms=latency,
                    http_status=response.status_code,
                    live=True,
                )
            return HealthResult(
                status="healthy",
                ok=True,
                message="Meta Ad Library responded to an authenticated query.",
                latency_ms=latency,
                http_status=response.status_code,
                details={"advertising_only": True},
                live=True,
            )
        except Exception as exc:  # noqa: BLE001 - health checks must not raise
            latency = int((time.perf_counter() - started) * 1000)
            return HealthResult(
                status="degraded",
                ok=False,
                message=f"Meta probe failed: {type(exc).__name__}: {exc}"[:500],
                latency_ms=latency,
                live=True,
            )

    # -- internals ---------------------------------------------------------

    def _client(self, timeout_seconds: float) -> RetryingHttpClient:
        kwargs = {
            "timeout": timeout_seconds,
            "headers": self._headers(),
            "transport": self._transport,
            "policy": self._policy,
        }
        if self._sleep is not None:
            kwargs["sleep"] = self._sleep
        return RetryingHttpClient(**kwargs)

    @staticmethod
    def _raise_for_status(response: Any) -> None:
        if response.status_code in (401, 403):
            raise ConnectorAuthError(
                f"Meta rejected the Ad Library token (HTTP {response.status_code})."
            )
        if response.status_code == 429:
            raise ConnectorRateLimitError("Meta Ad Library rate limit reached; retry later.")
        if response.status_code >= 400:
            raise ConnectorError(f"Meta Ad Library returned HTTP {response.status_code}.")

    @staticmethod
    def _error_message(response: Any) -> str:
        try:
            body = response.json()
        except ValueError:
            return f"Meta Ad Library returned HTTP {response.status_code}."
        error = body.get("error") if isinstance(body, dict) else None
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])[:500]
        return f"Meta Ad Library returned HTTP {response.status_code}."
