import csv
import io
from datetime import date, timedelta

from app.connectors.csv_source import OBSERVATION_COLUMNS
from app.connectors.registry import get_connector


def _first_product(client, headers) -> dict:
    response = client.get("/api/v1/products?per_page=1", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"][0]


def _source_map(client, headers) -> dict:
    response = client.get("/api/v1/data-sources", headers=headers)
    assert response.status_code == 200, response.text
    return {item["provider_key"]: item for item in response.json()["data"]}


def test_sources_expose_cost_usage_and_availability(client, auth_headers, synced):
    sources = _source_map(client, auth_headers)

    for key in (
        "mock",
        "csv_import",
        "google_trends",
        "google_bigquery_trends",
        "ebay_au",
        "meta_ad_library",
        "amazon_public_research",
        "tiktok",
    ):
        assert key in sources
        item = sources[key]
        assert item["cost_model"] in {"free", "paid", "manual", "synthetic"}
        assert item["usage_rights"]
        assert item["estimated_monthly_spend"] is not None
        assert item["health"]

    assert sources["google_trends"]["availability"] == "manual_fallback"
    assert sources["google_trends"]["connector"]["installed"] is True
    assert sources["google_trends"]["connector"]["available"] is False
    assert sources["ebay_au"]["connector"]["state"] == "requires_credentials"
    assert sources["exploding_topics"]["cost_model"] == "paid"
    assert sources["exploding_topics"]["enabled"] is False
    assert sources["exploding_topics"]["connector"]["installed"] is False


def test_unconfigured_connector_is_not_synced(client, auth_headers, synced):
    sources = _source_map(client, auth_headers)
    response = client.post(
        f"/api/v1/data-sources/{sources['ebay_au']['id']}/sync", headers=auth_headers
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SOURCE_UNAVAILABLE"


def test_manual_observation_keeps_full_provenance(client, auth_headers, synced):
    product = _first_product(client, auth_headers)
    day = (date.today() - timedelta(days=5)).isoformat()
    payload = {
        "metric_name": "google_trends_manual_index",
        "metric_type": "search_interest",
        "value": 64.5,
        "unit": "index",
        "observation_date": day,
        "provider_name": "Manual Google Trends research",
        "source_url": "https://trends.google.com/trends/explore?geo=AU",
        "verification_status": "unverified",
        "data_quality": "medium",
        "notes": "Transcribed from a Google Trends screenshot",
    }
    response = client.post(
        f"/api/v1/products/{product['slug']}/observations",
        json=payload,
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    observation = body["observation"]
    assert observation["metric_type"] == "search_interest"
    assert observation["provider_name"] == payload["provider_name"]
    assert observation["source_url"] == payload["source_url"]
    assert observation["verification_status"] == "unverified"
    assert observation["data_quality"] == "medium"
    assert observation["value"] == 64.5
    assert observation["notes"] == payload["notes"]
    assert body["recommendation"]["verdict"] in {
        "recommended",
        "investigate",
        "not_recommended",
    }

    listed = client.get(
        f"/api/v1/products/{product['slug']}/observations?metric_type=search_interest",
        headers=auth_headers,
    ).json()["observations"]
    assert any(item["id"] == observation["id"] for item in listed)


def test_duplicate_manual_observation_is_rejected(client, auth_headers, synced):
    product = _first_product(client, auth_headers)
    payload = {
        "metric_name": "manual_duplicate_check",
        "metric_type": "other",
        "value": 1.0,
        "observation_date": (date.today() - timedelta(days=2)).isoformat(),
    }
    url = f"/api/v1/products/{product['slug']}/observations"
    first = client.post(url, json=payload, headers=auth_headers)
    assert first.status_code == 201, first.text
    second = client.post(url, json=payload, headers=auth_headers)
    assert second.status_code == 409


def test_manual_supplier_unlocks_the_margin_check(client, auth_headers, synced):
    product = _first_product(client, auth_headers)
    response = client.post(
        f"/api/v1/products/{product['slug']}/suppliers",
        json={
            "supplier_name": "Shenzhen Test Supply",
            "country": "CN",
            "supplier_rating": 4.6,
            "product_cost": "11.50",
            "shipping_cost": "3.20",
            "currency": "AUD",
            "minimum_order_quantity": 10,
            "lead_time_days": 14,
            "availability": "in_stock",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["created"] is True
    assert body["recommendation"]["checks"]
    assert any(
        item["supplier_name"] == "Shenzhen Test Supply" for item in body["suppliers"]
    )

    detail = client.get(f"/api/v1/products/{product['slug']}", headers=auth_headers)
    assert detail.status_code == 200
    recommendation = detail.json()["recommendation"]
    assert recommendation["verdict"] in {
        "recommended",
        "investigate",
        "not_recommended",
    }
    supplier_check = next(
        item for item in recommendation["checks"] if item["key"] == "supplier_cost"
    )
    assert supplier_check["status"] == "pass"
    delivery_check = next(
        item for item in recommendation["checks"] if item["key"] == "delivery_cost"
    )
    assert delivery_check["status"] == "pass"


def test_supplier_patch_recomputes_the_recommendation(client, auth_headers, synced):
    created_product = client.post(
        "/api/v1/products",
        json={"name": "Manual Margin Test Product", "price": "40.00"},
        headers=auth_headers,
    )
    assert created_product.status_code == 201, created_product.text
    slug = created_product.json()["slug"]

    created = client.post(
        f"/api/v1/products/{slug}/suppliers",
        json={
            "supplier_name": "Margin Test Supply",
            "product_cost": "30.00",
            "shipping_cost": "5.00",
            "currency": "AUD",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    margin = next(
        item for item in created.json()["recommendation"]["checks"] if item["key"] == "margin"
    )
    assert margin["status"] == "fail"

    offer = next(
        item
        for item in created.json()["suppliers"]
        if item["supplier_name"] == "Margin Test Supply"
    )
    response = client.patch(
        f"/api/v1/products/{slug}/suppliers/{offer['id']}",
        json={"product_cost": "5.00"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    margin = next(
        item
        for item in response.json()["recommendation"]["checks"]
        if item["key"] == "margin"
    )
    assert margin["status"] == "pass"


def test_recommendations_endpoint_separates_evidence_from_verdict(
    client, auth_headers, synced
):
    response = client.get(
        "/api/v1/opportunities/recommendations?limit=5", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["meta"]["counts"]
    assert body["data"]
    for item in body["data"]:
        assert item["product"]["name"]
        recommendation = item["recommendation"]
        assert recommendation["verdict"] in {
            "recommended",
            "investigate",
            "not_recommended",
        }
        for check in recommendation["checks"]:
            assert check["key"]
            assert check["status"] in {"pass", "fail", "missing"}
        assert "not a recommendation" in body["meta"]["note"]


def test_observation_csv_template_and_import(client, auth_headers, synced):
    template = client.get(
        "/api/v1/products/import/observations/template", headers=auth_headers
    )
    assert template.status_code == 200
    header = template.text.splitlines()[0].split(",")
    assert header == OBSERVATION_COLUMNS

    product = _first_product(client, auth_headers)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(OBSERVATION_COLUMNS)
    writer.writerow(
        [
            product["name"],
            "social_mentions_manual",
            "social_engagement",
            "1250",
            "mentions",
            (date.today() - timedelta(days=3)).isoformat(),
            "",
            "",
            "https://example.com/manual-research",
            "estimated",
            "low",
            "Counted from a manual platform review",
        ]
    )
    response = client.post(
        "/api/v1/products/import/observations/csv",
        files={"file": ("observations.csv", buffer.getvalue(), "text/csv")},
        headers=auth_headers,
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["created"] == 1
    assert body["rejected"] == 0

    observations = client.get(
        f"/api/v1/products/{product['slug']}/observations?metric_type=social_engagement",
        headers=auth_headers,
    ).json()["observations"]
    imported = next(
        item for item in observations if item["metric_name"] == "social_mentions_manual"
    )
    assert imported["metric_type"] == "social_engagement"
    assert imported["verification_status"] == "estimated"
    assert imported["data_quality"] == "low"

    detail = client.get(f"/api/v1/products/{product['slug']}", headers=auth_headers)
    assert detail.status_code == 200

    # A second upload of the same row is skipped, not duplicated.
    again = client.post(
        "/api/v1/products/import/observations/csv",
        files={"file": ("observations.csv", buffer.getvalue(), "text/csv")},
        headers=auth_headers,
    )
    assert again.json()["skipped"] == 1


def test_csv_observation_import_reports_unknown_products(client, auth_headers, synced):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(OBSERVATION_COLUMNS)
    writer.writerow(
        [
            "Product That Does Not Exist",
            "search_interest",
            "search_interest",
            "50",
            "index",
            date.today().isoformat(),
        ]
    )
    response = client.post(
        "/api/v1/products/import/observations/csv",
        files={"file": ("observations.csv", buffer.getvalue(), "text/csv")},
        headers=auth_headers,
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["created"] == 0
    assert body["rejected"] == 1
    assert "unknown product" in body["errors"][0]["issue"]


def test_connector_status_is_derived_without_network_calls():
    ebay = get_connector("ebay_au")
    status = ebay.get_source_status(None)
    assert status.state == "requires_credentials"
    assert status.available is False
    assert status.credential_names == ("EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET")

    google = get_connector("google_trends")
    google_status = google.get_source_status(None)
    assert google_status.state == "manual_fallback"
    assert google_status.cost_model == "free"

    assert get_connector("exploding_topics") is None
