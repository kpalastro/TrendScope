def _first_product(client, headers):
    return client.get("/api/v1/products?per_page=1", headers=headers).json()["data"][0]


def test_watchlist_create_list_and_conflict(client, auth_headers, synced):
    product = _first_product(client, auth_headers)
    created = client.post(
        "/api/v1/watchlist",
        json={"product_id": product["id"], "status": "researching", "notes": "Check margins"},
        headers=auth_headers,
    )
    assert created.status_code == 201
    entry = created.json()
    assert entry["status"] == "researching"
    assert entry["product"]["id"] == product["id"]
    assert entry["product"]["opportunity_score"] is not None

    duplicate = client.post(
        "/api/v1/watchlist", json={"product_id": product["id"]}, headers=auth_headers
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "CONFLICT"

    listing = client.get("/api/v1/watchlist", headers=auth_headers).json()
    assert listing["meta"]["total"] == 1


def test_watchlist_update_and_delete(client, auth_headers, synced):
    product = _first_product(client, auth_headers)
    entry = client.post(
        "/api/v1/watchlist",
        json={"product_id": product["id"], "notes": "Check margins", "priority": 3},
        headers=auth_headers,
    ).json()
    updated = client.patch(
        f"/api/v1/watchlist/{entry['id']}",
        json={"status": "shortlisted", "priority": 2},
        headers=auth_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "shortlisted"
    assert updated.json()["priority"] == 2

    cleared = client.patch(
        f"/api/v1/watchlist/{entry['id']}",
        json={"notes": None, "priority": None},
        headers=auth_headers,
    )
    assert cleared.status_code == 200
    assert cleared.json()["notes"] is None
    assert cleared.json()["priority"] is None

    invalid = client.patch(
        f"/api/v1/watchlist/{entry['id']}", json={"status": "nonsense"}, headers=auth_headers
    )
    assert invalid.status_code == 422

    removed = client.delete(f"/api/v1/watchlist/{entry['id']}", headers=auth_headers)
    assert removed.status_code == 204
    assert client.get("/api/v1/watchlist", headers=auth_headers).json()["meta"]["total"] == 0


def test_watchlist_export_is_csv(client, auth_headers, synced):
    product = _first_product(client, auth_headers)
    client.post("/api/v1/watchlist", json={"product_id": product["id"]}, headers=auth_headers)
    response = client.get("/api/v1/watchlist/export", headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "opportunity_score" in response.text
    assert product["name"].split()[0] in response.text


def test_watchlist_compare(client, auth_headers, synced):
    products = client.get("/api/v1/products?per_page=3", headers=auth_headers).json()["data"]
    response = client.post(
        "/api/v1/watchlist/compare",
        json={"product_ids": [products[0]["id"], products[1]["id"]]},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert len(response.json()["data"]) == 2

    too_few = client.post(
        "/api/v1/watchlist/compare",
        json={"product_ids": [products[0]["id"]]},
        headers=auth_headers,
    )
    assert too_few.status_code == 422
