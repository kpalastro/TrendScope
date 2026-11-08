from __future__ import annotations

from app.core.security import hash_password
from app.models import User


def _login(client, email: str, password: str) -> dict:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _viewer(db) -> User:
    user = User(
        email="viewer@trendscope.app",
        password_hash=hash_password("viewer123"),
        display_name="Viewer",
        role="viewer",
        is_active=True,
    )
    db.add(user)
    db.commit()
    return user


def test_calculate_requires_auth(client, seeded):
    assert client.post("/api/v1/profit/calculate", json={}).status_code == 401


def test_calculate_returns_decimal_strings(client, auth_headers, seeded):
    response = client.post(
        "/api/v1/profit/calculate",
        json={"supplier_price": "12.40", "selling_price_inc_gst": "69.95"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["outputs"]["profit_per_order"] == "22.77"
    assert body["outputs"]["selling_price_ex_gst"] == "63.59"
    assert body["assumptions_version"]
    assert body["warnings"]
    assert "Estimate only" in body["disclaimer"]


def test_calculate_rejects_invalid_input(client, auth_headers, seeded):
    response = client.post(
        "/api/v1/profit/calculate",
        json={"selling_price_inc_gst": "0"},
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_assumptions_payload(client, auth_headers, seeded):
    response = client.get("/api/v1/profit/assumptions", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["assumptions_version"]
    assert body["defaults"]["gst_rate_pct"] == 10.0
    assert any("GST" in note for note in body["notes"])


def test_scenario_crud_recalculates_on_patch(client, auth_headers, seeded):
    created = client.post(
        "/api/v1/profit/scenarios",
        json={"name": "Tray base case", "inputs": {"supplier_price": "12.40"}},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    scenario = created.json()
    assert scenario["outputs"]["profit_per_order"] == "22.77"
    assert scenario["currency"] == "AUD"

    listing = client.get("/api/v1/profit/scenarios", headers=auth_headers)
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()["data"]] == [scenario["id"]]

    patched = client.patch(
        f"/api/v1/profit/scenarios/{scenario['id']}",
        json={"name": "Tray premium", "inputs": {"supplier_price": "12.40", "selling_price_inc_gst": "79.95"}},
        headers=auth_headers,
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["name"] == "Tray premium"
    assert body["outputs"]["selling_price_ex_gst"] == "72.68"

    deleted = client.delete(
        f"/api/v1/profit/scenarios/{scenario['id']}", headers=auth_headers
    )
    assert deleted.status_code == 204
    assert client.get("/api/v1/profit/scenarios", headers=auth_headers).json()["data"] == []


def test_viewer_cannot_save_scenario_but_can_calculate(client, auth_headers, seeded):
    _viewer(seeded)
    viewer_headers = _login(client, "viewer@trendscope.app", "viewer123")

    assert (
        client.post(
            "/api/v1/profit/calculate", json={}, headers=viewer_headers
        ).status_code
        == 200
    )
    response = client.post(
        "/api/v1/profit/scenarios",
        json={"name": "Nope"},
        headers=viewer_headers,
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_scenario_rejects_unknown_product(client, auth_headers, seeded):
    response = client.post(
        "/api/v1/profit/scenarios",
        json={
            "name": "Ghost",
            "product_id": "00000000-0000-0000-0000-000000000000",
        },
        headers=auth_headers,
    )
    assert response.status_code == 404
