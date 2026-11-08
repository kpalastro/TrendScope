from __future__ import annotations

import email.utils
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.connectors.http import (
    RetryPolicy,
    RetryingHttpClient,
    parse_retry_after,
)


def test_parse_retry_after_accepts_seconds_and_http_dates():
    assert parse_retry_after("3") == 3.0
    assert parse_retry_after(" 1.5 ") == 1.5
    assert parse_retry_after(None) is None
    assert parse_retry_after("") is None
    assert parse_retry_after("not-a-date") is None

    when = datetime.now(timezone.utc) + timedelta(seconds=30)
    parsed = parse_retry_after(email.utils.format_datetime(when, usegmt=True))
    assert parsed is not None
    assert 25 <= parsed <= 31


def test_delay_for_uses_bounded_exponential_backoff():
    policy = RetryPolicy(max_attempts=5, base_delay=0.5, max_delay=2.0, jitter=0.0)

    assert policy.delay_for(1) == 0.5
    assert policy.delay_for(2) == 1.0
    assert policy.delay_for(3) == 2.0
    assert policy.delay_for(4) == 2.0  # capped

    # Retry-After wins over the exponential delay, but is still capped.
    assert policy.delay_for(1, "9") == 2.0
    assert policy.delay_for(1, "0.25") == 0.25
    assert policy.delay_for(1, "invalid") == 0.5


def _client(handler, *, attempts: int = 3):
    sleeps: list[float] = []
    transport = httpx.MockTransport(handler)
    client = RetryingHttpClient(
        transport=transport,
        policy=RetryPolicy(max_attempts=attempts, base_delay=0.0, jitter=0.0),
        sleep=sleeps.append,
    )
    return client, sleeps


def test_retries_transient_status_and_honours_retry_after():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(503, headers={"Retry-After": "2"})
        return httpx.Response(200, json={"ok": True})

    client, sleeps = _client(handler)
    with client:
        response = client.get("https://provider.test/items")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert len(calls) == 3
    assert client.stats.attempts == 3
    assert client.stats.retries == 2
    assert client.stats.retry_after_seconds == 2.0
    assert sleeps == [2.0, 2.0]
    assert client.stats.as_dict()["retries"] == 2


def test_does_not_retry_client_errors():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(400, json={"error": "bad request"})

    client, sleeps = _client(handler)
    with client:
        response = client.get("https://provider.test/items")

    assert response.status_code == 400
    assert len(calls) == 1
    assert client.stats.retries == 0
    assert sleeps == []


def test_returns_last_response_when_retries_are_exhausted():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "1"})

    client, sleeps = _client(handler, attempts=2)
    with client:
        response = client.get("https://provider.test/items")

    assert response.status_code == 429
    assert len(calls) == 2
    assert client.stats.attempts == 2
    assert client.stats.retries == 1
    # The final attempt is returned, not retried.
    assert sleeps == [1.0]


def test_retries_transport_errors_then_succeeds():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("connection reset", request=request)
        return httpx.Response(200, json={"ok": True})

    client, _sleeps = _client(handler)
    with client:
        response = client.get("https://provider.test/items")

    assert response.status_code == 200
    assert len(calls) == 2
    assert client.stats.retries == 1


def test_transport_error_raises_after_final_attempt():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ReadTimeout("too slow", request=request)

    client, _sleeps = _client(handler, attempts=2)
    with client, pytest.raises(httpx.ReadTimeout):
        client.get("https://provider.test/items")

    assert len(calls) == 2
