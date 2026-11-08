"""Meta Ad Library connector.

The Ad Library API is an official, free Meta API. It returns advertising
activity, **not** social engagement, sales or demand. This connector therefore
stores a metric of type ``advertising`` and never feeds it into the social or
demand score. A token is required and the operator is responsible for Meta's
platform terms.
"""

from __future__ import annotations

import json
import os
from datetime import date
from urllib.parse import quote_plus

import httpx

from app.connectors.base import ConnectorContext
from app.connectors.framework import (
    BaseConnector,
    ConnectorAuthError,
    ConnectorError,
    ConnectorNotConfigured,
    ConnectorRateLimitError,
    RawObservation,
    RawPayload,
)

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

    def fetch_data(self, ctx: ConnectorContext) -> RawPayload:
        token = os.environ.get("META_AD_LIBRARY_TOKEN")
        if not token:
            raise ConnectorNotConfigured(
                "Set META_AD_LIBRARY_TOKEN to run the Meta Ad Library connector."
            )

        country = str(ctx.config.get("geo") or "AU").upper()
        max_keywords = int(ctx.config.get("max_keywords_per_run") or 10)
        sample_limit = max(1, min(int(ctx.config.get("ads_per_keyword") or 100), 500))
        timeout = httpx.Timeout(ctx.timeout_seconds)
        records: list[RawObservation] = []
        warnings: list[str] = []
        requests = 0

        with httpx.Client(timeout=timeout, headers=self._headers()) as client:
            for product in ctx.products[:max_keywords]:
                terms = product.search_terms()
                term = terms[0] if terms else product.name
                try:
                    response = client.get(
                        GRAPH_URL,
                        params={
                            "access_token": token,
                            "ad_reached_countries": json.dumps([country]),
                            "ad_active_status": "ACTIVE",
                            "search_terms": term,
                            "fields": "id,page_name,ad_delivery_start_time",
                            "limit": sample_limit,
                        },
                    )
                    requests += 1
                    self._raise_for_status(response)
                    body = response.json()
                except ConnectorError as exc:
                    warnings.append(f"{product.name}: {exc}")
                    continue

                ads = body.get("data") or []
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
                        original_metric="active ads returned by Ad Library search",
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
                            "note": "Active advertising activity, not social engagement or sales.",
                        },
                    )
                )

        return RawPayload(
            records=records,
            source_url=PUBLIC_SEARCH_URL,
            request_count=requests,
            warnings=warnings,
            metadata={"country": country, "max_keywords": max_keywords},
        )

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code in (401, 403):
            raise ConnectorAuthError(
                f"Meta rejected the Ad Library token (HTTP {response.status_code})."
            )
        if response.status_code == 429:
            raise ConnectorRateLimitError("Meta Ad Library rate limit reached; retry later.")
        if response.status_code >= 400:
            raise ConnectorError(f"Meta Ad Library returned HTTP {response.status_code}.")
