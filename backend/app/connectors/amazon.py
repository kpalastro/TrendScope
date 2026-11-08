"""Amazon public-research connector.

There is no first-party Amazon Australia product/bestseller API available to a
research-only account. Amazon PA-API has no ``amazon.com.au`` domain and the
Creators API requires qualifying Associates sales. This connector therefore
declares a manual research path (public bestseller pages read by a human, CSV
import, or a licensed vendor later) and does not scrape.
"""

from __future__ import annotations

from app.connectors.base import ConnectorContext
from app.connectors.framework import BaseConnector, ConnectorUnavailable, RawPayload


class AmazonPublicResearchConnector(BaseConnector):
    provider_key = "amazon_public_research"
    provider_name = "Amazon public research (manual)"
    source_type = "marketplace"
    cost_model = "manual"
    default_availability = "manual_fallback"
    availability_reason = (
        "Amazon Australia exposes no first-party product API to this account. Use the "
        "manual research template or CSV import. Amazon bestseller pages must be read "
        "under Amazon's terms; this connector does not scrape them."
    )
    docs_url = "https://webservices.amazon.com/paapi5/documentation/"
    terms_url = "https://www.amazon.com.au/gp/help/customer/display.html?nodeId=508088"
    usage_rights = "manual_research"

    def fetch_data(self, ctx: ConnectorContext) -> RawPayload:
        raise ConnectorUnavailable(self.availability_reason or "Amazon API unavailable.")
