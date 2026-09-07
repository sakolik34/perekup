import json
from pathlib import Path

from app.providers.mock import MockProvider

ROOT = Path(__file__).resolve().parents[1]


def test_demo_photos_match_models_and_exist():
    batch = MockProvider().fetch()
    credits = {
        item["file"] for item in json.loads((ROOT / "app/static/cars/credits.json").read_text())
    }
    by_brand = {}
    for item in batch.listings:
        by_brand.setdefault(item.brand, set()).update(item.photos)
        for url in item.photos:
            assert url in credits
            assert (ROOT / "app" / url.lstrip("/")).is_file()
    assert len(by_brand) == 5
    for brand, photos in by_brand.items():
        assert photos
        for other, other_photos in by_brand.items():
            if other != brand:
                assert not photos & other_photos


def test_search_title_and_literal_wildcards(client):
    response = client.get("/api/listings", params={"q": "gOlF"})
    assert response.status_code == 200
    assert response.json()["total"] == 10
    assert all("Golf" in row["title"] for row in response.json()["items"])
    assert client.get("/api/listings", params={"q": "%"}).json()["total"] == 0
    assert client.get("/api/listings", params={"q": "_"}).json()["total"] == 0
    assert client.get("/api/listings", params={"q": "x" * 121}).status_code == 422


def test_deal_preset_matches_dashboard(client):
    stats = client.get("/api/stats").json()
    listing = client.get("/api/listings?discount_min=10&profit_min=0.01&risk_max=40").json()
    assert listing["total"] == stats["potential_deals"]
    assert stats["models_by_brand"]["Volkswagen"] == ["Golf"]
    assert stats["models_by_brand"]["Mazda"] == ["MX-5"]


def test_guide_and_download(client):
    guide = client.get("/guide")
    assert guide.status_code == 200
    assert "GitHub" in guide.text
    assert "Firzafp" in guide.text
    assert "CC BY-SA 4.0" in guide.text
    assert client.get("/guide/github.md").status_code == 200
    for item in json.loads((ROOT / "app/static/cars/credits.json").read_text()):
        response = client.get(item["file"])
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/")
