from __future__ import annotations

from app.api.v1.auth import REFRESH_COOKIE_PATH
from app.core.config import settings

COOKIE = "trendscope_refresh"


def _login(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": settings.admin_email, "password": settings.admin_password},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_login_sets_httponly_refresh_cookie(client, seeded):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": settings.admin_email, "password": settings.admin_password},
    )
    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie", "")
    assert COOKIE in set_cookie
    assert "HttpOnly" in set_cookie
    # The cookie must cover the browser-visible auth route through the Next.js
    # rewrite (/api/backend/auth), not only the backend's own prefix.
    assert f"Path={REFRESH_COOKIE_PATH}" in set_cookie
    assert REFRESH_COOKIE_PATH == "/"

    cookie = client.cookies.get(COOKIE)
    assert cookie
    # The refresh token lives only in the cookie, never in the JSON body.
    assert response.json()["access_token"] != cookie


def test_refresh_rotates_the_cookie(client, seeded):
    _login(client)
    first = client.cookies.get(COOKIE)

    response = client.post("/api/v1/auth/refresh")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["access_token"]
    assert body["user"]["email"] == settings.admin_email

    second = client.cookies.get(COOKIE)
    assert second and second != first

    refreshed = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert refreshed.status_code == 200


def test_reusing_a_rotated_token_revokes_the_family(client, seeded):
    _login(client)
    first = client.cookies.get(COOKIE)
    assert client.post("/api/v1/auth/refresh").status_code == 200
    current = client.cookies.get(COOKIE)
    assert current and current != first

    # Replay the already-rotated token.
    client.cookies.set(COOKIE, first, path=REFRESH_COOKIE_PATH)
    replay = client.post("/api/v1/auth/refresh")
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "UNAUTHENTICATED"

    # The legitimate successor is revoked too: the family is considered stolen.
    client.cookies.set(COOKIE, current, path=REFRESH_COOKIE_PATH)
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_logout_revokes_and_clears_cookie(client, seeded):
    _login(client)
    raw = client.cookies.get(COOKIE)
    assert raw

    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 204
    assert not client.cookies.get(COOKIE)

    client.cookies.set(COOKIE, raw, path=REFRESH_COOKIE_PATH)
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_refresh_without_cookie_is_unauthorised(client, seeded):
    response = client.post("/api/v1/auth/refresh")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
