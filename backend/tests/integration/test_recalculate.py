from __future__ import annotations

from datetime import date, timedelta


def test_recalculate_all_products(client, auth_headers, synced):
    response = client.post(
        "/api/v1/scores/recalculate", json={"all": True}, headers=auth_headers
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["products"] >= 8
    assert body["job"]["type"] == "scores.recalculate"
    assert body["job"]["status"] == "succeeded"
    assert body["as_of_date"] == date.today().isoformat()


def test_recalculate_single_product(client, auth_headers, synced):
    products = client.get("/api/v1/products", headers=auth_headers).json()["data"]
    product_id = products[0]["id"]
    response = client.post(
        "/api/v1/scores/recalculate",
        json={"product_id": product_id},
        headers=auth_headers,
    )
    assert response.status_code == 202
    assert response.json()["products"] == 1

    score = client.get(f"/api/v1/products/{product_id}/score", headers=auth_headers)
    assert score.status_code == 200


def test_recalculate_past_date(client, auth_headers, synced):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    response = client.post(
        "/api/v1/scores/recalculate",
        json={"all": True, "as_of_date": yesterday},
        headers=auth_headers,
    )
    assert response.status_code == 202
    assert response.json()["as_of_date"] == yesterday


def test_recalculate_requires_exactly_one_scope(client, auth_headers, synced):
    neither = client.post("/api/v1/scores/recalculate", json={}, headers=auth_headers)
    assert neither.status_code == 422

    products = client.get("/api/v1/products", headers=auth_headers).json()["data"]
    both = client.post(
        "/api/v1/scores/recalculate",
        json={"all": True, "product_id": products[0]["id"]},
        headers=auth_headers,
    )
    assert both.status_code == 422


def test_recalculate_rejects_future_date_and_unknown_product(client, auth_headers, synced):
    future = (date.today() + timedelta(days=1)).isoformat()
    response = client.post(
        "/api/v1/scores/recalculate",
        json={"all": True, "as_of_date": future},
        headers=auth_headers,
    )
    assert response.status_code == 422

    unknown = client.post(
        "/api/v1/scores/recalculate",
        json={"product_id": "00000000-0000-0000-0000-000000000000"},
        headers=auth_headers,
    )
    assert unknown.status_code == 404


def test_recalculate_requires_admin(client, seeded):
    from app.core.security import hash_password
    from app.models import User

    seeded.add(
        User(
            email="analyst2@trendscope.app",
            password_hash=hash_password("analyst123"),
            display_name="Analyst",
            role="analyst",
            is_active=True,
        )
    )
    seeded.commit()
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "analyst2@trendscope.app", "password": "analyst123"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    response = client.post(
        "/api/v1/scores/recalculate", json={"all": True}, headers=headers
    )
    assert response.status_code == 403
