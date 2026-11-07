def test_product_list_has_scores_and_quality(client, auth_headers, synced):
    response = client.get("/api/v1/products?per_page=50", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total"] == 8
    assert len(body["data"]) == 8
    first = body["data"][0]
    assert first["opportunity_score"] is not None
    assert first["data_quality"]["synthetic"] is True
    assert first["data_quality"]["coverage_pct"] > 0
    assert first["growth"]["d30"]["reason"] in {"ok", "insufficient_baseline"}


def test_product_detail_has_series_and_breakdown(client, auth_headers, synced):
    listing = client.get("/api/v1/products?per_page=1", headers=auth_headers).json()["data"][0]
    response = client.get(f"/api/v1/products/{listing['id']}", headers=auth_headers)
    assert response.status_code == 200
    detail = response.json()
    for key in (
        "keywords",
        "score_breakdown",
        "competition",
        "listings",
        "suppliers",
        "trend_series",
        "sources",
        "disclaimer",
    ):
        assert key in detail
    series = {item["metric_name"]: item for item in detail["trend_series"]}
    assert "search_interest" in series
    assert len(series["search_interest"]["points"]) >= 200
    assert detail["score_breakdown"]["components"]["demand"]["weight"] == 0.25


def test_growth_guards_surface_as_null_with_reason(client, auth_headers, synced):
    listing = client.get("/api/v1/products?per_page=1", headers=auth_headers).json()["data"][0]
    growth = listing["growth"]["d90"]
    assert growth["window_days"] == 90
    if growth["pct"] is None:
        assert growth["reason"] != "ok"
    else:
        assert growth["reason"] == "ok"


def test_filters_and_sort(client, auth_headers, synced):
    response = client.get(
        "/api/v1/products?min_score=0&sort=name&per_page=50", headers=auth_headers
    )
    names = [item["name"] for item in response.json()["data"]]
    assert names == sorted(names)

    synthetic = client.get(
        "/api/v1/products?synthetic=only&per_page=50", headers=auth_headers
    ).json()
    assert synthetic["meta"]["total"] == 8

    none_synthetic = client.get(
        "/api/v1/products?synthetic=exclude&per_page=50", headers=auth_headers
    ).json()
    assert none_synthetic["meta"]["total"] == 0

    category = client.get(
        "/api/v1/products?category_path=electronics&per_page=50", headers=auth_headers
    ).json()
    assert category["meta"]["total"] == 3


def test_search_matches_name_and_keyword(client, auth_headers, synced):
    response = client.get("/api/v1/products?q=earbuds", headers=auth_headers)
    assert response.json()["meta"]["total"] >= 1
    assert "Earbuds" in response.json()["data"][0]["name"]


def test_slug_and_uuid_are_both_accepted(client, auth_headers, synced):
    listing = client.get("/api/v1/products?per_page=1", headers=auth_headers).json()["data"][0]
    by_slug = client.get(f"/api/v1/products/{listing['slug']}", headers=auth_headers)
    assert by_slug.status_code == 200
    assert by_slug.json()["id"] == listing["id"]


def test_unknown_product_returns_404(client, auth_headers, synced):
    response = client.get("/api/v1/products/does-not-exist", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_trending_and_discovery_views(client, auth_headers, synced):
    assert client.get("/api/v1/trending?window=30", headers=auth_headers).status_code == 200
    assert client.get("/api/v1/trending?window=30&direction=declining", headers=auth_headers).status_code == 200
    assert client.get("/api/v1/trending?window=5", headers=auth_headers).status_code == 422
    assert client.get("/api/v1/emerging", headers=auth_headers).status_code == 200
    assert client.get("/api/v1/opportunities?min_coverage=0", headers=auth_headers).status_code == 200
    assert client.get("/api/v1/seasonal?horizon_days=45", headers=auth_headers).status_code == 200


def test_categories_have_counts(client, auth_headers, synced):
    body = client.get("/api/v1/categories", headers=auth_headers).json()
    assert len(body["data"]) == 16
    electronics = next(item for item in body["data"] if item["slug"] == "electronics")
    assert electronics["product_count"] == 3


def test_create_subcategory_with_parent(client, auth_headers, synced):
    categories = client.get("/api/v1/categories", headers=auth_headers).json()["data"]
    root = next(item for item in categories if item["level"] == 0)
    response = client.post(
        "/api/v1/categories",
        json={"name": "Test Child Category", "parent_id": str(root["id"])},
        headers=auth_headers,
    )
    assert response.status_code == 201
    assert response.json()["parent_id"] == root["id"]

    invalid = client.post(
        "/api/v1/categories",
        json={"name": "Bad Parent Category", "parent_id": "not-a-uuid"},
        headers=auth_headers,
    )
    assert invalid.status_code == 422
