"""TikTok trends connector.

TikTok Creative Center has no documented public API for Australia, and its
internal endpoints require signed headers and reject datacenter traffic. This
connector exists so the registry, UI and scoring engine can reason about the
source without pretending it works: it declares a manual fallback and never
scrapes.
"""

from __future__ import annotations

from app.connectors.base import ConnectorContext
from app.connectors.framework import BaseConnector, ConnectorUnavailable, RawPayload


class TikTokTrendsConnector(BaseConnector):
    provider_key = "tiktok"
    provider_name = "TikTok Creative Center (manual research)"
    source_type = "social"
    cost_model = "free"
    default_availability = "manual_fallback"
    availability_reason = (
        "TikTok Creative Center has no permitted public API for Australia. Record "
        "social signals manually or import a spreadsheet; do not scrape the site or "
        "bypass its signing controls."
    )
    docs_url = "https://ads.tiktok.com/business/creativecenter/"
    terms_url = "https://www.tiktok.com/legal/page/row/terms-of-service/en"
    usage_rights = "manual_research"

    def fetch_data(self, ctx: ConnectorContext) -> RawPayload:
        raise ConnectorUnavailable(self.availability_reason or "TikTok API unavailable.")
