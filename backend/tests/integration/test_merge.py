from __future__ import annotations

from datetime import date
from uuid import UUID

from app.models import Product


def _stored(seeded, product: dict) -> Product:
    seeded.expire_all()
    return seeded.get(Product, UUID(product["id"]))


def _create(client, headers, name: str, **extra) -> dict:
    payload = {"name": name, **extra}
    response = client.post("/api/v1/products", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_identifier_conflict_is_rejected(client, auth_headers, seeded):
    _create(client, auth_headers, "Manual Widget Alpha", identifiers={"gtin": "9350000000012"})
    response = client.post(
        "/api/v1/products",
        json={"name": "Manual Widget Beta", "identifiers": {"gtin": "9350000000012"}},
        headers=auth_headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


def test_invalid_identifier_is_rejected(client, auth_headers, seeded):
    response = client.post(
        "/api/v1/products",
        json={"name": "Manual Bad Identifier", "identifiers": {"isbn": "not-digits"}},
        headers=auth_headers,
    )
    assert response.status_code == 422

    unknown = client.post(
        "/api/v1/products",
        json={"name": "Manual Unknown Scheme", "identifiers": {"loyalty": "123"}},
        headers=auth_headers,
    )
    assert unknown.status_code == 422


def test_fuzzy_duplicate_enters_review_queue_and_merges(client, auth_headers, seeded):
    first = _create(client, auth_headers, "Silicone Kitchen Organisation Tray")
    second = _create(client, auth_headers, "Silicone Kitchen Organizer Tray")

    queue = client.get("/api/v1/products/matches", headers=auth_headers)
    assert queue.status_code == 200
    matches = queue.json()["data"]
    pair = [
        item
        for item in matches
        if {item["product_a"]["id"], item["product_b"]["id"]}
        == {first["id"], second["id"]}
    ]
    assert pair, matches
    assert pair[0]["method"] == "fuzzy"
    assert 0.72 <= pair[0]["similarity"] <= 1.0

    resolved = client.post(
        f"/api/v1/products/matches/{pair[0]['id']}/resolve",
        json={"action": "merge"},
        headers=auth_headers,
    )
    assert resolved.status_code == 200, resolved.text
    body = resolved.json()
    assert body["merge"]["target_id"] == first["id"]
    assert body["product"]["id"] == first["id"]

    survivor = client.get(f"/api/v1/products/{first['id']}", headers=auth_headers)
    assert survivor.status_code == 200
    merged_second = _stored(seeded, second)
    assert merged_second.status == "merged"
    assert str(merged_second.merged_into_product_id) == first["id"]


def test_rejecting_a_match_keeps_both_products(client, auth_headers, seeded):
    first = _create(client, auth_headers, "Bamboo Drawer Divider Small")
    second = _create(client, auth_headers, "Bamboo Drawer Divider Large")
    queue = client.get("/api/v1/products/matches", headers=auth_headers).json()["data"]
    pair = next(
        item
        for item in queue
        if {item["product_a"]["id"], item["product_b"]["id"]} == {first["id"], second["id"]}
    )
    resolved = client.post(
        f"/api/v1/products/matches/{pair['id']}/resolve",
        json={"action": "reject"},
        headers=auth_headers,
    )
    assert resolved.status_code == 200
    assert resolved.json()["match"]["status"] == "rejected"
    # Resolving twice is a conflict, not a silent second merge.
    again = client.post(
        f"/api/v1/products/matches/{pair['id']}/resolve",
        json={"action": "merge"},
        headers=auth_headers,
    )
    assert again.status_code == 409


def test_direct_merge_moves_history_to_survivor(client, auth_headers, seeded):
    source = _create(client, auth_headers, "Collapsible Water Bottle Blue", price="25.00")
    target = _create(client, auth_headers, "Collapsible Water Bottle Navy", price="27.00")

    # A metric the survivor does not already hold for the same natural key must
    # move, not be dropped.
    observation = client.post(
        f"/api/v1/products/{source['id']}/observations",
        json={
            "metric_name": "search_interest",
            "metric_type": "search_interest",
            "value": 52,
            "observation_date": date.today().isoformat(),
            "granularity": "daily",
        },
        headers=auth_headers,
    )
    assert observation.status_code == 201, observation.text

    response = client.post(
        f"/api/v1/products/{source['slug']}/merge",
        json={"into_product_id": target["id"]},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["merge"]["source_id"] == source["id"]
    assert body["merge"]["target_id"] == target["id"]
    assert body["merge"]["moved"]["observations"] >= 1
    # The source's price row shares the survivor's natural key, so it is dropped.
    assert body["merge"]["dropped"]["observations"] == 1

    merged_source = _stored(seeded, source)
    assert merged_source.status == "merged"
    assert str(merged_source.merged_into_product_id) == target["id"]

    survivor = client.get(f"/api/v1/products/{target['id']}", headers=auth_headers).json()
    assert survivor["id"] == target["id"]
    assert _stored(seeded, target).status == "active"
    observations = client.get(
        f"/api/v1/products/{target['id']}/observations", headers=auth_headers
    ).json()["observations"]
    moved = [item for item in observations if item["metric_name"] == "search_interest"]
    assert moved and moved[0]["value"] == 52


def test_merge_into_self_is_rejected(client, auth_headers, seeded):
    product = _create(client, auth_headers, "Merino Travel Sock")
    response = client.post(
        f"/api/v1/products/{product['id']}/merge",
        json={"into_product_id": product["id"]},
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_merge_queue_requires_admin(client, seeded):
    from app.core.security import hash_password
    from app.models import User

    seeded.add(
        User(
            email="analyst@trendscope.app",
            password_hash=hash_password("analyst123"),
            display_name="Analyst",
            role="analyst",
            is_active=True,
        )
    )
    seeded.commit()
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "analyst@trendscope.app", "password": "analyst123"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/api/v1/products/matches", headers=headers).status_code == 403


def test_merge_recomputes_survivor_with_source_date(client, auth_headers, seeded):
    today = date.today().isoformat()
    source = _create(client, auth_headers, "Reusable Produce Bag Set", price="18.00")
    target = _create(client, auth_headers, "Reusable Produce Bag Bundle", price="19.00")
    response = client.post(
        f"/api/v1/products/{source['id']}/merge",
        json={"into_product_id": target["id"]},
        headers=auth_headers,
    )
    assert response.status_code == 200
    metrics = client.get(
        f"/api/v1/products/{target['id']}/metrics", headers=auth_headers
    ).json()["metrics"]
    assert any(item["as_of_date"] == today for item in metrics)
