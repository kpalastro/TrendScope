from datetime import date


def test_dashboard_summary_and_widgets(client, auth_headers, synced):
    response = client.get("/api/v1/dashboard", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    summary = body["summary"]
    assert summary["products_monitored"] == 8
    assert summary["average_opportunity_score"] is not None
    assert any(source["provider_key"] == "mock" for source in summary["data_sources"])
    assert len(body["widgets"]) == 8
    keys = {widget["key"] for widget in body["widgets"]}
    assert {"weekly_trending", "monthly_trending", "emerging", "best_margins"} <= keys
    for widget in body["widgets"]:
        assert widget["note"]
        assert len(widget["items"]) <= 10


def test_unknown_widget_is_404(client, auth_headers, synced):
    response = client.get("/api/v1/dashboard/widgets/nope", headers=auth_headers)
    assert response.status_code == 404


def test_weekly_report_generation_and_download(client, auth_headers, synced):
    today = date.today().isoformat()
    response = client.post(
        "/api/v1/reports",
        json={
            "type": "weekly_trends",
            "country": "AU",
            "period_start": today,
            "period_end": today,
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    report = response.json()
    assert report["status"] == "ready"
    assert report["summary"]
    assert "top_growth" in report["report_data"]
    assert report["report_data"]["limitations"]
    assert report["report_data"]["disclaimer"]

    listing = client.get("/api/v1/reports", headers=auth_headers).json()
    assert listing["meta"]["total"] == 1

    csv_response = client.get(
        f"/api/v1/reports/{report['id']}/download?format=csv", headers=auth_headers
    )
    assert csv_response.status_code == 200
    assert "top_growth" in csv_response.text
    assert "disclaimer" in csv_response.text

    xlsx_response = client.get(
        f"/api/v1/reports/{report['id']}/download?format=xlsx", headers=auth_headers
    )
    assert xlsx_response.status_code == 200
    assert xlsx_response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    from io import BytesIO

    from openpyxl import load_workbook

    workbook = load_workbook(BytesIO(xlsx_response.content))
    assert workbook.sheetnames == ["Summary", "Products", "Sources", "Limitations"]
    assert workbook["Summary"]["A1"].value == "Field"


def test_report_rejects_inverted_period(client, auth_headers, synced):
    response = client.post(
        "/api/v1/reports",
        json={
            "type": "weekly_trends",
            "country": "AU",
            "period_start": "2026-11-08",
            "period_end": "2026-11-01",
        },
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_exports_products_csv(client, auth_headers, synced):
    response = client.get("/api/v1/exports/products", headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    header = response.text.splitlines()[0]
    assert "opportunity_score" in header
    assert "coverage_pct" in header
    assert len(response.text.splitlines()) > 1


def test_competition_summary(client, auth_headers, synced):
    response = client.get("/api/v1/competition/summary", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["product_count"] == 8
    assert sum(body["classes"].values()) == 8
    assert body["caveats"]
