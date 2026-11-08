"""eBay Australia Browse API connector.

The Browse API is an official, free developer API (application OAuth). It returns
**active listings only**. eBay's sold/completed feed was decommissioned and
Marketplace Insights is not open to new users, so this connector never claims
sales, units sold or sold price. All observations are labelled as active
marketplace listings/prices.

Requests go through the shared retrying client: 429 and 5xx responses are
retried with exponential backoff and ``Retry-After`` is honoured. The OAuth
token is cached for its advertised lifetime so pagination and repeated syncs do
not mint a new token for every request.
"""

from __future__ import annotations

import base64
import math
import os
import threading
import time
from datetime import date
from typing import Any
from urllib.parse import quote_plus

from app.connectors.base import ConnectorContext, ListingRecord
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

TOKEN_URL = "https://api.ebay.com/identity/v2/oauth2/token"
BROWSE_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
SCOPE = "https://api.ebay.com/oauth/api_scope"
MARKETPLACE = "EBAY_AU"

_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_TOKEN_LOCK = threading.Lock()


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
        client_id = os.environ.get("EBAY_CLIENT_ID")
        client_secret = os.environ.get("EBAY_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise ConnectorNotConfigured(
                "Set EBAY_CLIENT_ID and EBAY_CLIENT_SECRET to run the eBay connector."
            )

        max_keywords = max(1, min(int(ctx.config.get("max_keywords_per_run") or 10), 50))
        limit = max(1, min(int(ctx.config.get("listings_per_keyword") or 50), 200))
        max_pages = max(1, min(int(ctx.config.get("max_pages_per_keyword") or 1), 5))
        marketplace = str(ctx.config.get("marketplace_id") or MARKETPLACE)
        requests = 0
        records: list[RawObservation] = []
        listings: list[ListingRecord] = []
        warnings: list[str] = []
        seen_listings: set[str] = set()
        sampled = 0
        non_aud = 0

        with self._client(ctx.timeout_seconds) as client:
            retry_stats = client.stats
            token = self._token(client, client_id, client_secret)
            requests += 1
            for product in ctx.products[:max_keywords]:
                term = product.search_terms()[0] if product.search_terms() else product.name
                search_url = (
                    f"{BROWSE_URL}?q={quote_plus(term)}&limit={limit}"
                    f"&marketplace={quote_plus(marketplace)}"
                )
                total: int | None = None
                items: list[dict] = []
                pages_read = 0
                offset = 0
                while pages_read < max_pages:
                    response = client.get(
                        BROWSE_URL,
                        params={"q": term, "limit": limit, "offset": offset},
                        headers={
                            "Authorization": f"Bearer {token}",
                            "X-EBAY-C-MARKETPLACE-ID": marketplace,
                        },
                    )
                    requests += 1
                    try:
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
                    page_items = body.get("itemSummaries") or []
                    items.extend(page_items)
                    pages_read += 1
                    if isinstance(body.get("total"), int):
                        total = body["total"]
                    offset += len(page_items)
                    if (
                        not page_items
                        or len(page_items) < limit
                        or (isinstance(total, int) and offset >= total)
                    ):
                        break

                prices: list[float] = []
                for item in items:
                    price = item.get("price") if isinstance(item, dict) else None
                    if not isinstance(price, dict):
                        continue
                    if str(price.get("currency") or "").upper() != "AUD":
                        non_aud += 1
                        continue
                    value = price.get("value")
                    if not _finite_positive(value):
                        continue
                    prices.append(float(value))
                    listing_id = str(item.get("itemId") or "").strip()
                    if not listing_id or listing_id in seen_listings:
                        continue
                    seen_listings.add(listing_id)
                    seller = item.get("seller") if isinstance(item.get("seller"), dict) else {}
                    listings.append(
                        ListingRecord(
                            external_id=product.external_id,
                            marketplace=marketplace,
                            listing_id=listing_id,
                            title=str(item.get("title") or "")[:300],
                            seller_name=str(seller.get("username") or "")[:200],
                            price=float(value),
                            # eBay Browse does not expose product review data.
                            # Seller feedback is not a product rating, so it is
                            # deliberately not mapped into these fields.
                            rating=0.0,
                            review_count=0,
                            listing_url=str(item.get("itemWebUrl") or ""),
                        )
                    )
                    sampled += 1

                if total is None:
                    total = len(items)
                today = date.today()
                if total is not None:
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
                                "marketplace": marketplace,
                                "query": term,
                                "active_listings_only": True,
                                "sold_data": False,
                                "items_sampled": len(items),
                                "pages_read": pages_read,
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
                            original_metric="mean of sampled active listing prices (AUD)",
                            source_url=search_url,
                            verification_status="verified",
                            data_quality="medium",
                            meta={
                                "provider": "ebay_au",
                                "marketplace": marketplace,
                                "currency": "AUD",
                                "sample_size": len(prices),
                                "pages_read": pages_read,
                                "active_listings_only": True,
                                "sold_data": False,
                            },
                        )
                    )
                else:
                    warnings.append(f"{product.name}: no priced AUD active listings returned.")

        return RawPayload(
            records=records,
            source_url=BROWSE_URL,
            request_count=requests,
            warnings=warnings,
            listings=listings,
            metadata={
                "marketplace": marketplace,
                "max_keywords": max_keywords,
                "listings_per_keyword": limit,
                "max_pages_per_keyword": max_pages,
                "listing_records": sampled,
                "non_aud_listings_skipped": non_aud,
                "retry": retry_stats.as_dict(),
                "sold_data": False,
            },
        )

    def probe(self, source: Any) -> HealthResult:
        client_id = os.environ.get("EBAY_CLIENT_ID")
        client_secret = os.environ.get("EBAY_CLIENT_SECRET")
        if not client_id or not client_secret:
            return HealthResult(
                status="unconfigured",
                ok=False,
                message="EBAY_CLIENT_ID and EBAY_CLIENT_SECRET are not set.",
                live=True,
            )
        started = time.perf_counter()
        try:
            with self._client(10.0) as client:
                self._token(client, client_id, client_secret, force=True)
            latency = int((time.perf_counter() - started) * 1000)
            return HealthResult(
                status="healthy",
                ok=True,
                message="eBay OAuth token issued; Browse API credentials are valid.",
                latency_ms=latency,
                details={"marketplace": MARKETPLACE, "scope": SCOPE, "sold_data": False},
                live=True,
            )
        except ConnectorAuthError as exc:
            latency = int((time.perf_counter() - started) * 1000)
            return HealthResult(
                status="degraded",
                ok=False,
                message=str(exc)[:500],
                latency_ms=latency,
                live=True,
            )
        except Exception as exc:  # noqa: BLE001 - health checks must not raise
            latency = int((time.perf_counter() - started) * 1000)
            return HealthResult(
                status="degraded",
                ok=False,
                message=f"eBay probe failed: {type(exc).__name__}: {exc}"[:500],
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

    def _token(
        self,
        client: RetryingHttpClient,
        client_id: str,
        client_secret: str,
        *,
        force: bool = False,
    ) -> str:
        now = time.time()
        with _TOKEN_LOCK:
            cached = _TOKEN_CACHE.get(client_id)
            if cached and not force and cached[1] > now + 60:
                return cached[0]

        encoded = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        response = client.post(
            TOKEN_URL,
            headers={
                "Authorization": f"Basic {encoded}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials", "scope": SCOPE},
        )
        self._raise_for_status(response)
        try:
            body = response.json()
        except ValueError as exc:
            raise ConnectorAuthError("eBay token response was not JSON.") from exc
        token = body.get("access_token")
        if not token:
            raise ConnectorAuthError("eBay token response did not include an access token.")
        expires_in = float(body.get("expires_in") or 7200)
        with _TOKEN_LOCK:
            _TOKEN_CACHE[client_id] = (str(token), now + max(60.0, expires_in))
        return str(token)

    @staticmethod
    def _raise_for_status(response: Any) -> None:
        if response.status_code in (401, 403):
            raise ConnectorAuthError(
                f"eBay rejected the credentials (HTTP {response.status_code})."
            )
        if response.status_code == 429:
            raise ConnectorRateLimitError("eBay rate limit reached; retry later.")
        if response.status_code >= 400:
            raise ConnectorError(f"eBay API returned HTTP {response.status_code}.")


def _finite_positive(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0
