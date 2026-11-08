from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import pytest

from app.connectors.base import ConnectorContext, TrackedProduct
from app.connectors.dataforseo import (
    DataForSEOTrendsConnector,
    _account_summary,
    _graph_points,
    _point_date,
    _point_value,
)
from app.connectors.framework import ConnectorNotConfigured
from app.connectors.http import RetryPolicy


def _context(*, external_id: str = "p1", name: str = "Yoga Mat") -> ConnectorContext:
    return ConnectorContext(
        source=None,
        config={"geo": "AU", "time_range": "past_12_months"},
        since=date(2025, 1, 1),
        until=date(2025, 1, 31),
        products=(TrackedProduct(id="p1", external_id=external_id, name=name),),
    )


def _trends_body() -> dict[str, Any]:
    return {
        "status_code": 20000,
        "status_message": "Ok.",
        "tasks": [
            {
                "status_code": 20000,
                "result": [
                    {
                        "items": [
                            {
                                "type": "google_trends_graph",
                                "data": [
                                    {
                                        "date_from": "2025-01-01",
                                        "date_to": "2025-01-07",
                                        "values": [42],
                                    },
                                    {
                                        "date_from": "2025-01-08",
                                        "date_to": "2025-01-14",
                                        "values": [55.5],
                                    },
                                ],
                            }
                        ]
                    }
                ],
            }
        ],
    }


def _connector(handler) -> DataForSEOTrendsConnector:
    return DataForSEOTrendsConnector(
        transport=httpx.MockTransport(handler),
        sleep=lambda _seconds: None,
        policy=RetryPolicy(max_attempts=2, base_delay=0.0, jitter=0.0),
    )


def test_response_helpers_extract_points_and_values():
    body = _trends_body()
    points = _graph_points(body)

    assert len(points) == 2
    assert _point_value(points[0]) == 42.0
    assert _point_value(points[1]) == 55.5
    assert _point_date(points[0]) == date(2025, 1, 1)

    assert _point_value({"values": ["not-a-number"]}) is None
    assert _point_value({"values": [-1]}) is None
    assert _point_value({}) is None
    assert _point_date({"timestamp": 1735689600}) == date(2025, 1, 1)
    assert _point_date({}) is None


def test_account_summary_is_secret_free():
    body = {
        "tasks": [
            {
                "result": [
                    {
                        "login": "operator@example.test",
                        "money": {"balance": 10},
                        "secret": "do-not-expose",
                    }
                ]
            }
        ]
    }
    summary = _account_summary(body)

    assert summary["login"] == "operator@example.test"
    assert summary["money"] == {"balance": 10}
    assert "secret" not in summary


def test_fetch_data_requires_credentials(monkeypatch):
    monkeypatch.delenv("DATAFORSEO_LOGIN", raising=False)
    monkeypatch.delenv("DATAFORSEO_PASSWORD", raising=False)

    with pytest.raises(ConnectorNotConfigured):
        _connector(lambda request: httpx.Response(500)).fetch_data(_context())


def test_fetch_data_maps_interest_points_to_provenance(monkeypatch):
    monkeypatch.setenv("DATAFORSEO_LOGIN", "login")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "password")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path.endswith("/keywords_data/google_trends/explore/live")
        assert request.headers["Authorization"].startswith("Basic ")
        return httpx.Response(200, json=_trends_body())

    payload = _connector(handler).fetch_data(_context())

    assert len(requests) == 1
    assert payload.request_count == 1
    assert payload.source_url == "https://trends.google.com/trends/explore"
    assert payload.metadata["provider"] == "google_trends_dataforseo"
    assert len(payload.records) == 2

    first = payload.records[0]
    assert first.external_id == "p1"
    assert first.observation_date == date(2025, 1, 1)
    assert first.metric_name == "google_trends_interest"
    assert first.metric_type == "search_interest"
    assert first.metric_value == 42.0
    assert first.unit == "index"
    assert first.granularity == "weekly"
    assert first.verification_status == "verified"
    assert first.data_quality == "high"
    assert "q=Yoga+Mat" in (first.source_url or "")
    assert first.meta["relative_index"] is True


def test_run_normalises_only_valid_points(monkeypatch):
    monkeypatch.setenv("DATAFORSEO_LOGIN", "login")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "password")
    connector = _connector(lambda request: httpx.Response(200, json=_trends_body()))

    dataset = connector.run(_context())

    assert len(dataset.observations) == 2
    assert dataset.observations[0].resolved_metric_type() == "search_interest"
    assert dataset.observations[0].metric_value == 42.0
    assert dataset.request_count == 1


def test_fetch_data_records_rate_limit_warning(monkeypatch):
    monkeypatch.setenv("DATAFORSEO_LOGIN", "login")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "password")

    payload = _connector(
        lambda request: httpx.Response(429, json={"status_message": "rate limited"})
    ).fetch_data(_context())

    assert payload.records == []
    assert payload.request_count == 1
    assert any("rate limit" in warning.lower() for warning in payload.warnings)


def test_probe_without_credentials_is_unconfigured(monkeypatch):
    monkeypatch.delenv("DATAFORSEO_LOGIN", raising=False)
    monkeypatch.delenv("DATAFORSEO_PASSWORD", raising=False)

    result = _connector(lambda request: httpx.Response(200)).probe(None)

    assert result.status == "unconfigured"
    assert result.ok is False
    assert result.live is True


def test_probe_reports_healthy_and_rejected_credentials(monkeypatch):
    monkeypatch.setenv("DATAFORSEO_LOGIN", "login")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "password")

    user_data = {
        "status_code": 20000,
        "tasks": [{"result": [{"login": "login", "money": {"balance": 5}}]}],
    }
    healthy = _connector(lambda request: httpx.Response(200, json=user_data)).probe(None)
    assert healthy.status == "healthy"
    assert healthy.ok is True
    assert healthy.live is True
    assert healthy.details["account"]["login"] == "login"

    rejected = _connector(lambda request: httpx.Response(401, json={})).probe(None)
    assert rejected.status == "degraded"
    assert rejected.ok is False
    assert rejected.http_status == 401
    assert "credentials" in (rejected.message or "").lower()
