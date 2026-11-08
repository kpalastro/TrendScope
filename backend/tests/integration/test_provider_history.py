from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.connectors.base import ConnectorContext, ConnectorDataset, ObservationPoint
from app.connectors.framework import ConnectorRateLimitError
from app.models import DataSource, IngestionRun, Product, TrendObservation
from app.services.ingestion import _insert_observations, get_source, run_connector_sync


def _sources(client, headers) -> dict:
    response = client.get("/api/v1/data-sources", headers=headers)
    assert response.status_code == 200, response.text
    return {item["provider_key"]: item for item in response.json()["data"]}


def test_health_overview_covers_every_source(client, auth_headers, synced):
    response = client.get("/api/v1/data-sources/health", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["meta"]["total"] == len(body["data"])
    assert body["meta"]["counts"]
    assert body["meta"]["note"]
    provider_keys = {item["provider_key"] for item in body["data"]}
    assert "mock" in provider_keys
    assert "ebay_au" in provider_keys


def test_configuration_health_check_is_recorded_and_exposed(
    client, auth_headers, synced, monkeypatch
):
    for name in (
        "EBAY_CLIENT_ID",
        "EBAY_CLIENT_SECRET",
        "META_AD_LIBRARY_TOKEN",
        "DATAFORSEO_LOGIN",
        "DATAFORSEO_PASSWORD",
        "GOOGLE_APPLICATION_CREDENTIALS",
    ):
        monkeypatch.delenv(name, raising=False)
    sources = _sources(client, auth_headers)

    def check(provider_key: str) -> dict:
        response = client.post(
            f"/api/v1/data-sources/{sources[provider_key]['id']}/health-check",
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        return response.json()

    healthy = check("mock")
    assert healthy["check"]["status"] == "healthy"
    assert healthy["check"]["ok"] is True
    assert healthy["check"]["live"] is False
    assert healthy["summary"]["checks_24h"] == 1
    assert healthy["summary"]["ok_24h"] == 1
    assert healthy["summary"]["success_rate_24h"] == 1.0

    manual = check("google_trends")
    assert manual["check"]["status"] == "manual"
    assert manual["check"]["ok"] is False
    assert manual["check"]["live"] is False

    unconfigured = check("ebay_au")
    assert unconfigured["check"]["status"] == "unconfigured"
    assert unconfigured["check"]["details"]["credential_names"] == [
        "EBAY_CLIENT_ID",
        "EBAY_CLIENT_SECRET",
    ]

    refreshed = _sources(client, auth_headers)
    assert refreshed["mock"]["health_status"] == "healthy"
    assert refreshed["mock"]["last_health_check_at"] is not None
    assert refreshed["google_trends"]["health_status"] == "manual"

    history = client.get(
        f"/api/v1/data-sources/{sources['mock']['id']}/health?limit=5",
        headers=auth_headers,
    )
    assert history.status_code == 200, history.text
    body = history.json()
    assert body["summary"]["health_status"] == "healthy"
    assert len(body["checks"]) == 1
    assert body["checks"][0]["live"] is False
    assert "EBAY_CLIENT_SECRET" not in str(body)


def test_health_check_requires_admin(client, seeded):
    source = get_source(seeded, "mock")
    response = client.post(f"/api/v1/data-sources/{source.id}/health-check")
    assert response.status_code in {401, 403}


def test_sync_creates_snapshot_and_run_reports_updates(client, auth_headers, synced):
    sources = _sources(client, auth_headers)
    mock = sources["mock"]

    runs = client.get(
        f"/api/v1/data-sources/{mock['id']}/runs?per_page=10", headers=auth_headers
    )
    assert runs.status_code == 200, runs.text
    run = runs.json()["data"][0]
    assert "records_updated" in run
    assert run["records_updated"] == 0

    listing = client.get(
        f"/api/v1/data-sources/{mock['id']}/snapshots", headers=auth_headers
    )
    assert listing.status_code == 200, listing.text
    snapshots = listing.json()["data"]
    assert snapshots
    snapshot = snapshots[0]
    assert snapshot["record_count"] > 0
    assert len(snapshot["checksum"]) == 64
    assert snapshot["truncated"] is False
    assert "payload" not in snapshot
    assert snapshot["attribution"]["provider_key"] == "mock"
    assert run["cursor"]["snapshot_id"] == snapshot["id"]

    detail = client.get(
        f"/api/v1/data-sources/{mock['id']}/snapshots/{snapshot['id']}",
        headers=auth_headers,
    )
    assert detail.status_code == 200, detail.text
    payload = detail.json()["snapshot"]["payload"]
    assert payload["observations"]
    assert payload["truncated"] is False
    assert "payload" in detail.json()["snapshot"]


def test_snapshot_detail_is_scoped_to_its_source(client, auth_headers, synced):
    sources = _sources(client, auth_headers)
    mock = sources["mock"]
    snapshot = client.get(
        f"/api/v1/data-sources/{mock['id']}/snapshots", headers=auth_headers
    ).json()["data"][0]

    response = client.get(
        f"/api/v1/data-sources/{sources['google_trends']['id']}/snapshots/{snapshot['id']}",
        headers=auth_headers,
    )
    assert response.status_code == 404


def test_changed_observation_value_increments_revision(client, auth_headers, synced):
    db = synced
    source = get_source(db, "mock")
    observation = db.execute(
        select(TrendObservation).order_by(TrendObservation.observation_date).limit(1)
    ).scalar_one()
    product = db.get(Product, observation.product_id)
    external_id = product.external_id or product.slug
    previous_value = float(observation.metric_value)

    run = IngestionRun(source_id=source.id, job_name="sync.revision-test", status="running")
    db.add(run)
    db.commit()

    point = ObservationPoint(
        external_id=external_id,
        observation_date=observation.observation_date,
        metric_name=observation.metric_name,
        metric_value=previous_value + 5,
        unit=observation.unit,
        granularity=observation.granularity,
        confidence=observation.confidence,
        metric_type=observation.metric_type,
        period_start=observation.period_start,
        period_end=observation.period_end,
        source_url=observation.source_url,
        verification_status=observation.verification_status,
        data_quality=observation.data_quality,
        original_metric=observation.original_metric,
        meta={"provider": "test"},
    )
    dataset = ConnectorDataset(observations=[point])

    added, updated, rejected = _insert_observations(
        db, source, run, dataset, {external_id: product}
    )
    db.commit()

    assert (added, updated, rejected) == (0, 1, 0)
    db.refresh(observation)
    assert float(observation.metric_value) == previous_value + 5
    assert observation.revision == 2
    assert observation.updated_at is not None
    previous = observation.meta["previous_values"]
    assert previous[-1]["value"] == previous_value
    assert previous[-1]["ingestion_run_id"] == str(run.id)

    # Re-sending the same value is a no-op, not another revision.
    added, updated, rejected = _insert_observations(
        db, source, run, dataset, {external_id: product}
    )
    db.commit()
    assert (added, updated, rejected) == (0, 0, 0)
    db.refresh(observation)
    assert observation.revision == 2

    response = client.get(
        f"/api/v1/products/{product.slug}/observations",
        params={"metric_type": observation.metric_type},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    rows = response.json()["observations"]
    assert rows, response.text
    row = next(
        (item for item in rows if item["id"] == observation.id),
        None,
    )
    assert row is not None, (
        f"missing {observation.id} among {len(rows)} rows; "
        f"first={rows[0]['id']} last={rows[-1]['id']} metric={observation.metric_type}"
    )
    assert row["revision"] == 2
    assert row["updated_at"] is not None
    assert row["attribution"]["revision"] == 2
    assert row["attribution"]["provider_name"] == observation.provider_name


def test_transient_connector_error_is_retried(db, seeded, monkeypatch):
    from app.connectors.framework import BaseConnector
    from app.connectors import registry

    class FlakyConnector(BaseConnector):
        provider_key = "flaky_test"
        provider_name = "Flaky test provider"
        source_type = "search_trend"
        cost_model = "free"
        default_availability = "available"
        calls = 0

        def fetch_data(self, ctx: ConnectorContext):
            raise AssertionError("fetch_data is not used by the overriding run")

        def run(self, ctx: ConnectorContext) -> ConnectorDataset:
            type(self).calls += 1
            if type(self).calls == 1:
                raise ConnectorRateLimitError("provider asked us to slow down")
            return ConnectorDataset(
                warnings=["recovered after retry"],
                request_count=1,
                metadata={"attempts": type(self).calls},
            )

    FlakyConnector.calls = 0
    monkeypatch.setitem(registry.CONNECTOR_CLASSES, "flaky_test", FlakyConnector)

    source = DataSource(
        provider_key="flaky_test",
        provider_name="Flaky test provider",
        source_type="search_trend",
        enabled=True,
        config={"retry_attempts": 3, "retry_backoff_seconds": 0},
    )
    db.add(source)
    db.commit()

    run = run_connector_sync(db, source, as_of=date.today())
    db.refresh(run)

    assert FlakyConnector.calls == 2
    assert run.status == "success"
    assert run.cursor["succeeded_after_attempt"] == 2
    assert run.cursor["retry_code"] == "RATE_LIMITED"
    assert run.error_count == 0
    assert source.consecutive_failures == 0
