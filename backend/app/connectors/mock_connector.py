"""Mock connector marker.

The deterministic generator builds a full ``ConnectorDataset`` (products,
observations, listings, suppliers, offers), so ingestion special-cases it in
``run_mock_sync`` rather than going through the raw-record normaliser. The class
still participates in status reporting and the plugin registry.
"""

from __future__ import annotations

from app.connectors.base import ConnectorContext
from app.connectors.framework import BaseConnector, ConnectorUnavailable, RawPayload


class MockConnector(BaseConnector):
    provider_key = "mock"
    provider_name = "Mock demo provider"
    source_type = "synthetic_demo"
    cost_model = "synthetic"
    default_availability = "available"
    usage_rights = "synthetic"

    def fetch_data(self, ctx: ConnectorContext) -> RawPayload:
        raise ConnectorUnavailable(
            "The mock provider is generated deterministically by run_mock_sync."
        )
