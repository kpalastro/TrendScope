def _upload(client, headers, content, filename="products.csv"):
    return client.post(
        "/api/v1/products/import/csv",
        headers=headers,
        files={"file": (filename, content, "text/csv")},
    )


VALID = (
    "name,category,brand,price,keywords,description\n"
    "Ceramic Pour Over Set,home-kitchen,Brew Co,49.95,coffee;pour over;ceramic,Brew kit\n"
    "Bad Category Row,not-a-category,Acme,10.00,x,broken\n"
    "Bad Price Row,electronics,Acme,not-a-price,x,broken\n"
)


def test_template_download(client, auth_headers):
    response = client.get("/api/v1/products/import/csv/template", headers=auth_headers)
    assert response.status_code == 200
    assert response.text.splitlines()[0].startswith("name,category,brand,price")


def test_import_creates_valid_rows_and_reports_rejections(client, auth_headers, seeded):
    response = _upload(client, auth_headers, VALID)
    assert response.status_code == 202
    body = response.json()
    assert body["created"] == 1
    assert body["rejected"] == 2
    issues = {item["row"]: item["issue"] for item in body["errors"]}
    assert "unknown category" in issues[3]
    assert "price" in issues[4]

    found = client.get("/api/v1/products?q=pour over", headers=auth_headers).json()
    assert found["meta"]["total"] == 1
    product = found["data"][0]
    assert product["data_quality"]["synthetic"] is False
    assert product["price_range"]["market_avg"] == "49.95"
    # No search history exists, so growth is null with a reason, never 0%.
    assert product["growth"]["d30"]["pct"] is None
    assert product["growth"]["d30"]["reason"] == "no_source"


def test_reimport_updates_instead_of_duplicating(client, auth_headers, seeded):
    _upload(client, auth_headers, VALID)
    again = _upload(client, auth_headers, VALID)
    body = again.json()
    assert body["created"] == 0
    assert body["updated"] == 1
    total = client.get("/api/v1/products?q=pour over", headers=auth_headers).json()["meta"]["total"]
    assert total == 1


def test_missing_name_column_rejected(client, auth_headers, seeded):
    response = _upload(client, auth_headers, "category,brand\npets,Acme\n")
    assert response.status_code == 202
    assert response.json()["rejected"] == 1
    assert "name" in response.json()["errors"][0]["issue"]


def test_manual_product_creation(client, auth_headers, seeded):
    categories = client.get("/api/v1/categories", headers=auth_headers).json()["data"]
    category = next(item for item in categories if item["slug"] == "pets")
    response = client.post(
        "/api/v1/products",
        json={
            "name": "Manual Pet Test Item",
            "category_id": category["id"],
            "brand": "Test Brand",
            "price": "29.95",
            "keywords": ["pet", "test"],
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    detail = response.json()
    assert detail["category"]["slug"] == "pets"
    assert detail["data_quality"]["synthetic"] is False
    # A price with no demand/marketplace evidence cannot produce a score; the
    # API shows null rather than a misleading 0.
    assert detail["opportunity_score"] is None
    assert detail["score_breakdown"]["score"] is None
    assert detail["score_breakdown"]["score_raw"] is None
    assert detail["classification"] == "insufficient_data"

    duplicate = client.post(
        "/api/v1/products", json={"name": "Manual Pet Test Item"}, headers=auth_headers
    )
    assert duplicate.status_code == 409


def test_manual_product_deduplicates_keywords(client, auth_headers, seeded):
    response = client.post(
        "/api/v1/products",
        json={
            "name": "Keyword Dedupe Test Item",
            "keywords": ["pet", "Pet", " pet ", "PET"],
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    keywords = response.json()["keywords"]
    assert len(keywords) == 1


def test_manual_product_reactivates_archived_row(client, auth_headers, seeded):
    created = client.post(
        "/api/v1/products", json={"name": "Archived Manual Item"}, headers=auth_headers
    )
    assert created.status_code == 201
    product_id = created.json()["id"]
    assert client.delete(f"/api/v1/products/{product_id}", headers=auth_headers).status_code == 204

    again = client.post(
        "/api/v1/products", json={"name": "Archived Manual Item"}, headers=auth_headers
    )
    assert again.status_code == 201
    detail = again.json()
    assert detail["id"] == product_id
    # Archived products are excluded from the catalogue; the reactivated row is back.
    found = client.get(
        "/api/v1/products?q=Archived Manual Item", headers=auth_headers
    ).json()
    assert found["meta"]["total"] == 1
    assert found["data"][0]["id"] == product_id


def test_import_reactivates_archived_product(client, auth_headers, seeded):
    _upload(client, auth_headers, VALID)
    product = client.get("/api/v1/products?q=pour over", headers=auth_headers).json()["data"][0]
    assert client.delete(f"/api/v1/products/{product['id']}", headers=auth_headers).status_code == 204

    again = _upload(client, auth_headers, VALID)
    assert again.status_code == 202
    body = again.json()
    assert body["created"] == 0
    assert body["updated"] == 1

    restored = client.get(f"/api/v1/products/{product['id']}", headers=auth_headers)
    assert restored.status_code == 200
    assert restored.json()["id"] == product["id"]
    found = client.get("/api/v1/products?q=pour over", headers=auth_headers).json()
    assert found["meta"]["total"] == 1


def test_reimport_keeps_first_price_observation(client, auth_headers, seeded):
    first = (
        "name,category,brand,price,keywords,description\n"
        "Price History Item,electronics,Acme,10.00,price,first\n"
    )
    second = first.replace("10.00", "20.00")
    _upload(client, auth_headers, first)
    _upload(client, auth_headers, second)

    product = client.get("/api/v1/products?q=Price History Item", headers=auth_headers).json()["data"][0]
    assert product["price_range"]["market_avg"] == "10.00"


def test_import_rejects_non_finite_price(client, auth_headers, seeded):
    response = _upload(client, auth_headers, "name,category,price\nNaN Item,electronics,nan\n")
    assert response.status_code == 202
    assert response.json()["rejected"] == 1
    assert "price" in response.json()["errors"][0]["issue"]


def test_import_deduplicates_keywords(client, auth_headers, seeded):
    response = _upload(
        client,
        auth_headers,
        "name,category,price,keywords\nDup Keyword Item,electronics,10,pet;pet;Pet\n",
    )
    assert response.status_code == 202
    assert response.json()["created"] == 1
    product = client.get("/api/v1/products?q=Dup Keyword Item", headers=auth_headers).json()["data"][0]
    detail = client.get(f"/api/v1/products/{product['id']}", headers=auth_headers).json()
    assert len(detail["keywords"]) == 1


def test_product_export_honours_price_filter(client, auth_headers, seeded):
    for name, price in (
        ("Cheap Export Item", "10.00"),
        ("Expensive Export Item", "500.00"),
    ):
        response = client.post(
            "/api/v1/products", json={"name": name, "price": price}, headers=auth_headers
        )
        assert response.status_code == 201

    export = client.get("/api/v1/exports/products?max_price=100", headers=auth_headers)
    assert export.status_code == 200
    assert "Cheap Export Item" in export.text
    assert "Expensive Export Item" not in export.text
