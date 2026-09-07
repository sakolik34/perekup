import pytest


def test_pages_health_swagger_and_stats(client):
    for path in ["/", "/health", "/docs", "/openapi.json", "/listings/1", "/static/app.js"]:
        assert client.get(path).status_code == 200
    stats = client.get("/api/stats").json()
    assert stats["active"] == 41
    assert stats["new_today"] == 41
    assert stats["potential_deals"] > 0
    assert stats["last_updated"]


def test_filters_and_pagination(client):
    data = client.get("/api/listings?brand=Volkswagen&price_to=15000&sort=price&page_size=3").json()
    assert len(data["items"]) == 3
    assert all(x["brand"] == "Volkswagen" and x["price_usd"] <= 15000 for x in data["items"])
    assert [x["price_usd"] for x in data["items"]] == sorted(x["price_usd"] for x in data["items"])
    other = client.get(
        "/api/listings?brand=Volkswagen&price_to=15000&sort=price&page_size=3&page=2"
    ).json()
    assert not {x["id"] for x in data["items"]} & {x["id"] for x in other["items"]}


@pytest.mark.parametrize(
    "query",
    [
        "year_from=2016&year_to=2018",
        "mileage_max=140000",
        "location=Киев",
        "fuel_type=Дизель&transmission=Автомат",
        "discount_min=10&profit_min=1&risk_max=40",
        "model=Octavia",
    ],
)
def test_other_filters(client, query):
    response = client.get("/api/listings?" + query)
    assert response.status_code == 200
    assert 0 < response.json()["total"] < 41


@pytest.mark.parametrize(
    "query",
    [
        "year_from=2020&year_to=2010",
        "price_from=20&price_to=10",
        "risk_max=101",
        "page=0",
        "sort=SQL",
        "price_from=nan",
    ],
)
def test_invalid_filters(client, query):
    assert client.get("/api/listings?" + query).status_code == 422


def test_detail_calculation_and_import(client):
    detail = client.get("/api/listings/1").json()
    assert detail["price_history"] and detail["comparables"]
    response = client.post(
        "/api/listings/1/calculate", json={"repair_cost": 1000, "additional_expenses": 400}
    )
    assert response.status_code == 200
    result = response.json()
    assert (
        result["potential_profit"] == result["estimated_market_price"] - detail["price_usd"] - 1400
    )
    assert client.post("/api/import").status_code == 200
    assert client.get("/api/listings/1").json()["score"]["estimated_repair_cost"] == 1000


@pytest.mark.parametrize("cost", [-1, "NaN", "Infinity", 10000000000000, "1.234"])
def test_invalid_expenses(client, cost):
    assert (
        client.post(
            "/api/listings/1/calculate", json={"repair_cost": cost, "additional_expenses": 100}
        ).status_code
        == 422
    )


def test_missing_listing_and_cross_origin(client):
    assert client.get("/api/listings/99999").status_code == 404
    assert client.get("/listings/99999").status_code == 404
    assert (
        client.post("/api/import", headers={"Origin": "https://foreign.example"}).status_code == 403
    )
