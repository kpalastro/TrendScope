def test_unauthenticated_request_returns_error_envelope(client):
    response = client.get("/api/v1/products")
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "UNAUTHENTICATED"
    assert body["error"]["request_id"]
    assert response.headers["X-Request-Id"]


def test_login_rejects_bad_password(client, seeded):
    response = client.post(
        "/api/v1/auth/login", json={"email": "admin@trendscope.app", "password": "nope"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_login_and_me(client, seeded):
    response = client.post(
        "/api/v1/auth/login", json={"email": "admin@trendscope.app", "password": "admin123"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    assert body["user"]["role"] == "admin"
    assert "admin" in body["user"]["permissions"]

    me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == "admin@trendscope.app"


def test_invalid_token_rejected(client, seeded):
    response = client.get("/api/v1/products", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_health_is_public(client):
    assert client.get("/health").json()["status"] == "ok"
    ready = client.get("/api/v1/health/ready").json()
    assert ready["checks"]["database"] == "ok"
