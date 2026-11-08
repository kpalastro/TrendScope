"""Free-first connector framework.

Every provider is an independent plugin implementing the same lifecycle:

    fetch_data -> validate_data -> normalize_data -> ConnectorDataset

``get_source_status`` and ``get_last_sync`` expose availability without making a
network call. ``handle_errors`` maps provider failures to a small, secret-free
error shape that the ingestion run records.

The framework deliberately does not scrape, bypass authentication, solve
CAPTCHAs or work around provider controls. A provider with no permitted API is
represented as ``manual_fallback`` (CSV/manual research) rather than emulated.
"""

from __future__ import annotations

import math
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, ClassVar

from app.connectors.base import ConnectorContext, ConnectorDataset, ObservationPoint
from app.models import (
    AVAILABILITY_STATES,
    COST_MODELS,
    DATA_QUALITY_LEVELS,
    METRIC_TYPES,
    VERIFICATION_STATUSES,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ConnectorError(Exception):
    """Base class for provider failures. Messages must never contain secrets."""


class ConnectorUnavailable(ConnectorError):
    """The provider cannot be called in this environment; use the fallback."""


class ConnectorNotConfigured(ConnectorUnavailable):
    """Required credentials or configuration are missing."""


class ConnectorAuthError(ConnectorError):
    """The provider rejected the credentials."""


class ConnectorRateLimitError(ConnectorError):
    """The provider asked us to slow down; the error is retryable."""


class ConnectorValidationError(ConnectorError):
    def __init__(self, message: str, issues: list[dict] | None = None):
        super().__init__(message)
        self.issues = issues or []


@dataclass(frozen=True)
class RawObservation:
    external_id: str
    observation_date: date
    metric_name: str
    metric_value: Any
    unit: str
    metric_type: str | None = None
    granularity: str = "daily"
    confidence: float = 1.0
    period_start: date | None = None
    period_end: date | None = None
    source_url: str | None = None
    verification_status: str = "unverified"
    data_quality: str = "unknown"
    original_metric: str | None = None
    source_timestamp: datetime | None = None
    meta: dict = field(default_factory=dict)


@dataclass
class RawPayload:
    records: list[RawObservation] = field(default_factory=list)
    collected_at: datetime = field(default_factory=utcnow)
    source_url: str | None = None
    warnings: list[str] = field(default_factory=list)
    request_count: int = 0
    metadata: dict = field(default_factory=dict)


@dataclass
class ValidationResult:
    valid: list[RawObservation] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.valid) and not self.rejected


@dataclass(frozen=True)
class ConnectorStatus:
    provider_key: str
    installed: bool
    enabled: bool
    available: bool
    state: str
    configured: bool
    reason: str | None
    credential_names: tuple[str, ...] = ()
    docs_url: str | None = None
    terms_url: str | None = None
    cost_model: str = "free"
    last_sync_at: datetime | None = None


@dataclass(frozen=True)
class ConnectorErrorInfo:
    code: str
    message: str
    retryable: bool


@dataclass(frozen=True)
class HealthResult:
    """Outcome of a provider health check.

    ``live`` distinguishes a local configuration check from a real provider
    call. A live check may consume a small amount of provider quota; the
    connectors implement the cheapest authenticated endpoint they have.
    """

    status: str
    ok: bool
    message: str
    latency_ms: int | None = None
    http_status: int | None = None
    details: dict = field(default_factory=dict)
    live: bool = False


class BaseConnector(ABC):
    provider_key: ClassVar[str]
    provider_name: ClassVar[str]
    source_type: ClassVar[str]
    cost_model: ClassVar[str] = "free"
    default_availability: ClassVar[str] = "available"
    availability_reason: ClassVar[str | None] = None
    credential_names: ClassVar[tuple[str, ...]] = ()
    requires_credentials: ClassVar[bool] = False
    docs_url: ClassVar[str | None] = None
    terms_url: ClassVar[str | None] = None
    usage_rights: ClassVar[str] = "api_terms"

    def __init__(self) -> None:
        if self.cost_model not in COST_MODELS:
            raise ValueError(f"invalid cost model: {self.cost_model}")
        if self.default_availability not in AVAILABILITY_STATES:
            raise ValueError(f"invalid availability: {self.default_availability}")

    # -- lifecycle ---------------------------------------------------------

    def credentials_configured(self) -> bool:
        return all(os.environ.get(name) for name in self.credential_names)

    def get_source_status(self, source: Any) -> ConnectorStatus:
        configured = self.credentials_configured()
        reason = self.availability_reason
        state = self.default_availability

        if state == "manual_fallback":
            reason = reason or (
                "This provider has no permitted API for the chosen market. "
                "Use CSV import or manual research entry."
            )
        elif state == "unavailable":
            reason = reason or "This provider is not available for this market."
        elif self.requires_credentials and not configured:
            state = "requires_credentials"
            names = ", ".join(self.credential_names) or "credentials"
            reason = reason or f"Set {names} to enable this connector."
        elif source is not None and not getattr(source, "enabled", False):
            # Disabled is an operator choice, not a provider failure. The
            # connector is still available if credentials are present.
            state = "available"
            reason = "Source is disabled; enable it to run a sync."

        return ConnectorStatus(
            provider_key=self.provider_key,
            installed=True,
            enabled=bool(getattr(source, "enabled", False)),
            available=state == "available",
            state=state,
            configured=configured,
            reason=reason,
            credential_names=self.credential_names,
            docs_url=self.docs_url,
            terms_url=self.terms_url,
            cost_model=self.cost_model,
            last_sync_at=self.get_last_sync(source),
        )

    def get_last_sync(self, source: Any) -> datetime | None:
        return getattr(source, "last_sync_at", None) if source is not None else None

    def health_check(self, source: Any, *, live: bool = False) -> HealthResult:
        """Assess availability without a provider call unless ``live`` is set.

        A configuration check is always safe. A live check is delegated to
        ``probe``; connectors that cannot make a cheap authenticated call fall
        back to the configuration result rather than inventing a failure.
        """
        status = self.get_source_status(source)
        if status.state == "manual_fallback":
            return HealthResult(
                status="manual",
                ok=False,
                message=status.reason or "Manual fallback; no automated provider call.",
                details={"state": status.state, "configured": status.configured},
                live=False,
            )
        if status.state == "unavailable":
            return HealthResult(
                status="unavailable",
                ok=False,
                message=status.reason or "Provider unavailable.",
                details={"state": status.state},
                live=False,
            )
        if status.state == "requires_credentials":
            return HealthResult(
                status="unconfigured",
                ok=False,
                message=status.reason or "Credentials are not configured.",
                details={
                    "state": status.state,
                    "credential_names": list(status.credential_names),
                },
                live=False,
            )
        if live:
            return self.probe(source)
        return HealthResult(
            status="healthy",
            ok=True,
            message="Configured and available.",
            details={
                "state": status.state,
                "enabled": status.enabled,
                "configured": status.configured,
            },
            live=False,
        )

    def probe(self, source: Any) -> HealthResult:
        """Cheap authenticated provider call. Override where one exists."""
        return HealthResult(
            status="healthy",
            ok=True,
            message="No live probe is implemented; configuration check only.",
            details={"live_supported": False},
            live=False,
        )

    @abstractmethod
    def fetch_data(self, ctx: ConnectorContext) -> RawPayload:
        """Fetch provider records. No database writes happen here."""

    def validate_data(self, payload: RawPayload) -> ValidationResult:
        result = ValidationResult()
        today = date.today()
        for index, record in enumerate(payload.records, start=1):
            issues: list[str] = []
            if not (record.external_id or "").strip():
                issues.append("external_id is required")
            if not (record.metric_name or "").strip():
                issues.append("metric_name is required")
            try:
                value = float(record.metric_value)
            except (TypeError, ValueError):
                issues.append("metric_value is not numeric")
                value = 0.0
            else:
                if not math.isfinite(value):
                    issues.append("metric_value is not finite")
            if record.observation_date is None:
                issues.append("observation_date is required")
            elif record.observation_date > today:
                issues.append("observation_date is in the future")
            if record.metric_type and record.metric_type not in METRIC_TYPES:
                issues.append(f"unknown metric_type: {record.metric_type}")
            if record.verification_status not in VERIFICATION_STATUSES:
                issues.append(f"unknown verification_status: {record.verification_status}")
            if record.data_quality not in DATA_QUALITY_LEVELS:
                issues.append(f"unknown data_quality: {record.data_quality}")
            if issues:
                result.rejected.append(
                    {
                        "record": index,
                        "external_id": record.external_id,
                        "issues": issues,
                    }
                )
            else:
                result.valid.append(record)
        return result

    def normalize_data(self, payload: RawPayload) -> ConnectorDataset:
        dataset = ConnectorDataset(
            warnings=list(payload.warnings),
            request_count=payload.request_count,
            source_url=payload.source_url,
            metadata=dict(payload.metadata),
        )
        for record in payload.records:
            metric_type = record.metric_type or _infer_metric_type(record.metric_name)
            dataset.observations.append(
                ObservationPoint(
                    external_id=record.external_id,
                    observation_date=record.observation_date,
                    metric_name=record.metric_name,
                    metric_value=float(record.metric_value),
                    unit=record.unit,
                    granularity=record.granularity,
                    confidence=record.confidence,
                    meta=dict(record.meta or {}),
                    metric_type=metric_type,
                    period_start=record.period_start or record.observation_date,
                    period_end=record.period_end or record.observation_date,
                    source_url=record.source_url or payload.source_url,
                    verification_status=record.verification_status,
                    data_quality=record.data_quality,
                    original_metric=record.original_metric,
                    source_timestamp=record.source_timestamp or payload.collected_at,
                )
            )
        return dataset

    def handle_errors(self, exc: Exception) -> ConnectorErrorInfo:
        if isinstance(exc, ConnectorNotConfigured):
            return ConnectorErrorInfo("NOT_CONFIGURED", str(exc), False)
        if isinstance(exc, ConnectorUnavailable):
            return ConnectorErrorInfo("SOURCE_UNAVAILABLE", str(exc), False)
        if isinstance(exc, ConnectorAuthError):
            return ConnectorErrorInfo("AUTH_FAILED", str(exc), False)
        if isinstance(exc, ConnectorRateLimitError):
            return ConnectorErrorInfo("RATE_LIMITED", str(exc), True)
        if isinstance(exc, ConnectorValidationError):
            return ConnectorErrorInfo("VALIDATION_ERROR", str(exc), False)
        return ConnectorErrorInfo(
            "PROVIDER_ERROR", f"{type(exc).__name__}: {exc}"[:1000], True
        )

    def run(self, ctx: ConnectorContext) -> ConnectorDataset:
        payload = self.fetch_data(ctx)
        if not payload.records:
            # An empty but well-formed provider response is a valid no-op; the
            # run records the warning instead of inventing a failure.
            return ConnectorDataset(
                warnings=[
                    *payload.warnings,
                    f"{self.provider_name} returned no matching records.",
                ],
                request_count=payload.request_count,
                source_url=payload.source_url,
                metadata=dict(payload.metadata),
            )
        validation = self.validate_data(payload)
        if not validation.valid:
            detail = "; ".join(
                f"record {item.get('record')}: {', '.join(item.get('issues', []))}"
                for item in validation.rejected[:5]
            )
            raise ConnectorValidationError(
                f"{self.provider_name} returned no valid records. {detail}",
                validation.rejected,
            )
        dataset = self.normalize_data(
            RawPayload(
                records=validation.valid,
                collected_at=payload.collected_at,
                source_url=payload.source_url,
                warnings=[
                    *payload.warnings,
                    *[
                        f"rejected {len(validation.rejected)} record(s)"
                        for _ in [validation.rejected]
                        if validation.rejected
                    ],
                ],
                request_count=payload.request_count,
                metadata=payload.metadata,
            )
        )
        return dataset

    # -- shared helpers ----------------------------------------------------

    @staticmethod
    def _headers(**extra: str) -> dict[str, str]:
        return {"Accept": "application/json", "User-Agent": "TrendScope/1.0", **extra}


def _infer_metric_type(metric_name: str) -> str:
    from app.connectors.base import infer_metric_type

    return infer_metric_type(metric_name)
