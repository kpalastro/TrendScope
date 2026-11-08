"""Provider-key -> connector class registry.

Paid providers are optional plugins: adding one later means adding a class here
and a ``data_sources`` row. The scoring engine, observation schema and API do
not change.
"""

from __future__ import annotations

from app.connectors.amazon import AmazonPublicResearchConnector
from app.connectors.csv_source import CSVImportConnector
from app.connectors.dataforseo import DataForSEOTrendsConnector
from app.connectors.ebay import EbayMarketplaceConnector
from app.connectors.framework import BaseConnector
from app.connectors.google import GoogleBigQueryTrendsConnector, GoogleTrendsConnector
from app.connectors.meta import MetaAdLibraryConnector
from app.connectors.mock_connector import MockConnector
from app.connectors.tiktok import TikTokTrendsConnector

CONNECTOR_CLASSES: dict[str, type[BaseConnector]] = {
    "mock": MockConnector,
    "google_trends": GoogleTrendsConnector,
    "google_trends_dataforseo": DataForSEOTrendsConnector,
    "google_bigquery_trends": GoogleBigQueryTrendsConnector,
    "tiktok": TikTokTrendsConnector,
    "meta_ad_library": MetaAdLibraryConnector,
    "ebay_au": EbayMarketplaceConnector,
    "amazon_public_research": AmazonPublicResearchConnector,
    "csv_import": CSVImportConnector,
}


def get_connector(provider_key: str) -> BaseConnector | None:
    cls = CONNECTOR_CLASSES.get(provider_key)
    return cls() if cls is not None else None


def installed_provider_keys() -> set[str]:
    return set(CONNECTOR_CLASSES)
