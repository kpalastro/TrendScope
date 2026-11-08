"""eBay Australia Browse API connector.

The Browse API is an official, free developer API (application OAuth). It returns
**active listings only**. eBay's sold/completed feed was decommissioned and
Marketplace Insights is not open to new users, so this connector never claims
sales, units sold or sold price. All observations are labelled as active
marketplace listings/prices.
"""

from __future__ import annotations

import base64
import math
import os
from datetime import date
from typing import Any
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

TOKEN_URL = "https://api.ebay.com/identity/v2/oauth2/token"
BROWSE_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
SCOPE = "https://api.ebay.com/oauth/api_scope"
MARKETPLACE = "EBAY_AU"


class EbayMarketplaceConnector(BaseConnector):
    provider_key = "ebay_au"
    provider_name = "eBay Australia (Browse API)"
    source_type = "marketplace"
    cost_model = "free"
    default_availability = "available"
    requires_credentials = True
    credential_names = ("EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET")
    docs_url = "https://developer.ebay.com/api-docs/buy/browse/overview.html"
    terms_url = "https://developer.ebay.com/terms/api-license"
    usage_rights = "api_terms"

    def fetch_data(self, ctx: ConnectorContext) -> RawPayload:
        client_id = os.environ.get("EBAY_CLIENT_ID")
        client_secret = os.environ.get("EBAY_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise ConnectorNotConfigured(
                "Set EBAY_CLIENT_ID and EBAY_CLIENT_SECRET to run the eBay connector."
            )

        max_keywords = int(ctx.config.get("max_keywords_per_run") or 10)
        limit = max(1, min(int(ctx.config.get("listings_per_keyword") or 50), 200))
        timeout = httpx.Timeout(ctx.timeout_seconds)
        requests = 0
        records: list[RawObservation] = []
        warnings: list[str] = []

        with httpx.Client(timeout=timeout, headers=self._headers()) as client:
            token = self._token(client, client_id, client_secret)
            requests += 1
            for product in ctx.products[:max_keywords]:
                term = product.search_terms()[0] if product.search_terms() else product.name
                search_url = f"{BROWSE_URL}?q={quote_plus(term)}&limit={limit}"
                try:
                    response = client.get(
                        BROWSE_URL,
                        params={"q": term, "limit": limit},
                        headers={
                            "Authorization": f"Bearer {token}",
                            "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE,
                        },
                    )
                    requests += 1
                    self._raise_for_status(response)
                    body = response.json()
                except ConnectorError as exc:
                    warnings.append(f"{product.name}: {exc}")
                    continue

                total = body.get("total")
                items = body.get("itemSummaries") or []
                prices = [
                    float(item["price"]["value"])
                    for item in items
                    if isinstance(item.get("price"), dict)
                    and _finite_positive(item["price"].get("value"))
                ]
                if total is None:
                    total = len(items)
                today = date.today()
                records.append(
                    RawObservation(
                        external_id=product.external_id,
                        observation_date=today,
                        period_start=today,
                        period_end=today,
                        metric_name="marketplace_listing_count",
                        metric_type="marketplace_listing",
                        metric_value=float(total),
                        unit="count",
                        confidence=0.85,
                        original_metric="total active listings",
                        source_url=search_url,
                        verification_status="verified",
                        data_quality="medium",
                        meta={
                            "provider": "ebay_au",
                            "marketplace": "EBAY_AU",
                            "query": term,
                            "active_listings_only": True,
                            "sold_data": False,
                            "items_sampled": len(items),
                            "note": "Active listings, not sales.",
                        },
                    )
                )
                if prices:
                    records.append(
                        RawObservation(
                            external_id=product.external_id,
                            observation_date=today,
                            period_start=today,
                            period_end=today,
                            metric_name="marketplace_avg_price",
                            metric_type="marketplace_price",
                            metric_value=round(sum(prices) / len(prices), 2),
                            unit="aud",
                            confidence=0.8,
                            original_metric="mean of sampled active listing prices",
                            source_url=search_url,
                            verification_status="verified",
                            data_quality="medium",
                            meta={
                                "provider": "ebay_au",
                                "marketplace": "EBAY_AU",
                                "currency": "AUD",
                                "sample_size": len(prices),
                                "active_listings_only": True,
                            },
                        )
                    )
                else:
                    warnings.append(f"{product.name}: no priced active listings returned.")

        return RawPayload(
            records=records,
            source_url=BROWSE_URL,
            request_count=requests,
            warnings=warnings,
            metadata={"marketplace": MARKETPLACE, "max_keywords": max_keywords},
        )

    def _token(self, client: httpx.Client, client_id: str, client_secret: str) -> str:
        encoded = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        response = client.post(
            TOKEN_URL,
            headers={
                "Authorization": f"Basic {encoded}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials", "scope": SCOPE},
        )
        self._raise_for_status(response, auth=True)
        token = response.json().get("access_token")
        if not token:
            raise ConnectorAuthError("eBay token response did not include an access token.")
        return token

    @staticmethod
    def _raise_for_status(response: httpx.Response, auth: bool = False) -> None:
        if response.status_code in (401, 403):
            raise ConnectorAuthError(
                f"eBay rejected the credentials (HTTP {response.status_code})."
            )
        if response.status_code == 429:
            raise ConnectorRateLimitError("eBay rate limit reached; retry later.")
        if response.status_code >= 400:
            raise ConnectorError(f"eBay API returned HTTP {response.status_code}.")
        if auth and not response.is_success:
            raise ConnectorError(f"eBay token endpoint returned HTTP {response.status_code}.")


def _finite_positive(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0
