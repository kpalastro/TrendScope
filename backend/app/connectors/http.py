"""Retrying HTTP client shared by authorised provider connectors.

Provider APIs fail transiently: network resets, 429 rate limits and 5xx errors.
Retrying those is safe for the read-only calls this project makes. Retrying a
4xx client error or an auth failure is not: the request would fail identically
and may count against a quota. This module keeps that distinction in one place
so every connector behaves the same way.

The client never retries a request with a side effect beyond the read-only
provider queries used here. It never bypasses authentication, CAPTCHAs or
provider controls.
"""

from __future__ import annotations

import email.utils
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

import httpx

DEFAULT_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0
    jitter: float = 0.2
    retry_statuses: frozenset[int] = DEFAULT_RETRY_STATUSES

    def delay_for(self, attempt: int, retry_after: str | None = None) -> float:
        """Delay before the next attempt (attempt is 1-based)."""
        if retry_after:
            parsed = parse_retry_after(retry_after)
            if parsed is not None:
                return min(max(parsed, 0.0), self.max_delay)
        raw = self.base_delay * (2 ** max(0, attempt - 1))
        capped = min(raw, self.max_delay)
        if self.jitter:
            capped *= 1.0 + random.uniform(-self.jitter, self.jitter)
        return max(0.0, capped)


def parse_retry_after(value: str | None) -> float | None:
    """Parse Retry-After as seconds or an HTTP date. Invalid values are ignored."""
    if not value:
        return None
    text = value.strip()
    try:
        return float(text)
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (when - datetime.now(timezone.utc)).total_seconds()


@dataclass
class RetryStats:
    attempts: int = 0
    retries: int = 0
    retry_after_seconds: float | None = None
    delays: list[float] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "attempts": self.attempts,
            "retries": self.retries,
            "retry_after_seconds": self.retry_after_seconds,
            "delays": [round(value, 2) for value in self.delays],
        }


class RetryingHttpClient:
    """Thin httpx wrapper with bounded exponential backoff.

    ``transport`` and ``sleep`` are injectable so tests can assert retry
    behaviour without network access or real waiting.
    """

    def __init__(
        self,
        *,
        timeout: float | httpx.Timeout = 20.0,
        headers: dict[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
        policy: RetryPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.policy = policy or RetryPolicy()
        self.stats = RetryStats()
        self._sleep = sleep
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout), headers=headers, transport=transport
        )

    def __enter__(self) -> "RetryingHttpClient":
        self._client.__enter__()
        return self

    def __exit__(self, *exc_info) -> None:
        self._client.__exit__(*exc_info)

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        last_error: httpx.TransportError | None = None
        for attempt in range(1, self.policy.max_attempts + 1):
            self.stats.attempts += 1
            try:
                response = self._client.request(method, url, **kwargs)
            except httpx.TransportError as exc:
                last_error = exc
                if attempt >= self.policy.max_attempts:
                    raise
                self._wait(attempt, None)
                continue

            if (
                response.status_code in self.policy.retry_statuses
                and attempt < self.policy.max_attempts
            ):
                self._wait(attempt, response.headers.get("Retry-After"))
                continue
            return response

        # Defensive: the loop always returns or raises, but keep a typed exit.
        if last_error is not None:  # pragma: no cover - unreachable
            raise last_error
        raise RuntimeError("retry loop exited without a response")  # pragma: no cover

    def get(self, url: str, **kwargs) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def _wait(self, attempt: int, retry_after: str | None) -> None:
        delay = self.policy.delay_for(attempt, retry_after)
        self.stats.retries += 1
        self.stats.delays.append(delay)
        if retry_after:
            self.stats.retry_after_seconds = parse_retry_after(retry_after)
        self._sleep(delay)
