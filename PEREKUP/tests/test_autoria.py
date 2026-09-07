import httpx
import pytest
from pydantic import SecretStr

from app.providers.autoria import AutoRiaClient, AutoRiaProvider, normalize_info
from app.providers.base import ProviderError
from app.services.autoria_statistics import AutoRiaStatisticsService


@pytest.fixture
def info():
    # Минимальная обезличенная структура официального примера auto/info.
    return {
        "title": "BMW 3 Series",
        "markName": "BMW",
        "modelName": "3 Series",
        "USD": 32999,
        "linkToView": "/auto_bmw_3_series_36756951.html",
        "locationCityName": "Одеса",
        "stateData": {"regionName": "Одеська"},
        "photoData": {
            "seoLinkB": "https://cdn2.riastatic.com/photosnew/auto/photo/bmw_3-series__556104182b.jpg"
        },
        "autoData": {
            "autoId": 36756951,
            "year": 2019,
            "raceInt": 140,
            "fuelName": "Дизель, 2 л.",
            "gearboxName": "Автомат",
            "driveName": "Повний",
            "generationName": "G20",
            "active": True,
            "isSold": False,
            "description": "Тест",
        },
        "VIN": "WBA5V710xKFxxxx23",
    }


def test_documented_field_mapping(info):
    result = normalize_info(info, "36756951")
    assert result.mileage_km == 140000
    assert result.engine_volume == 2
    assert result.fuel_type == "Дизель"
    assert result.vin is None
    assert result.region == "Одеська"
    assert result.url == "https://auto.ria.com/auto_bmw_3_series_36756951.html"


def test_missing_optional_fields(info):
    info.pop("photoData")
    info.pop("VIN")
    info["autoData"].pop("raceInt")
    result = normalize_info(info, "36756951")
    assert result.photos == [] and result.mileage_km is None


@pytest.mark.parametrize("mutation", ["id", "price", "url", "schema"])
def test_invalid_card_rejected(info, mutation):
    if mutation == "id":
        info["autoData"]["autoId"] = 1
    if mutation == "price":
        info["USD"] = 0
    if mutation == "url":
        info["linkToView"] = "javascript:alert(1)"
    if mutation == "schema":
        info.pop("autoData")
    with pytest.raises(ProviderError):
        normalize_info(info, "36756951")


def test_search_request_and_complete_batch(settings, info):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path == "/auto/search":
            assert request.url.params["page"] == "0"
            return httpx.Response(
                200, json={"result": {"search_result": {"ids": ["36756951"], "count": 1}}}
            )
        return httpx.Response(200, json=info)

    settings.autoria_api_key = SecretStr("test-secret")
    client = AutoRiaClient(settings, transport=httpx.MockTransport(handler), sleep=lambda _: None)
    batch = AutoRiaProvider(settings, client).fetch()
    assert batch.complete and len(batch.listings) == 1
    assert len(calls) == 2
    assert calls[1].url.params["auto_id"] == "36756951"
    assert calls[0].url.params["api_key"] == "test-secret"


def test_partial_search_is_not_complete(settings, info):
    def handler(request):
        if request.url.path == "/auto/search":
            return httpx.Response(
                200, json={"result": {"search_result": {"ids": ["36756951"], "count": 100}}}
            )
        return httpx.Response(200, json=info)

    batch = AutoRiaProvider(
        settings, AutoRiaClient(settings, httpx.MockTransport(handler), lambda _: None)
    ).fetch()
    assert not batch.complete and batch.warnings


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_api_errors_are_safe_and_bounded(settings, status, caplog):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"api_key": "secret-value"})

    settings.autoria_api_key = SecretStr("secret-value")
    with pytest.raises(ProviderError) as exc:
        AutoRiaClient(settings, httpx.MockTransport(handler), lambda _: None).request(
            "/auto/search"
        )
    assert len(calls) == (3 if status == 500 else 1)
    assert "secret-value" not in str(exc.value)
    assert "secret-value" not in caplog.text


def test_network_and_json_errors(settings):
    def handler(request):
        raise httpx.ConnectError("secret URL", request=request)

    with pytest.raises(ProviderError):
        AutoRiaClient(settings, httpx.MockTransport(handler), lambda _: None).request(
            "/auto/search"
        )
    with pytest.raises(ProviderError):
        AutoRiaClient(
            settings,
            httpx.MockTransport(lambda r: httpx.Response(200, text="not json")),
            lambda _: None,
        ).request("/auto/search")


def test_documented_statistics_request(settings):
    import json

    def handler(request):
        assert request.method == "POST"
        assert request.url.path == "/auto/statistic-avarage-price/"
        assert request.url.params["user_id"] == "123"
        assert json.loads(request.content) == {
            "langId": 4,
            "period": 365,
            "params": {"omniId": "36756951"},
        }
        return httpx.Response(200, json={"data": []})

    service = AutoRiaStatisticsService(
        settings, AutoRiaClient(settings, httpx.MockTransport(handler), lambda _: None)
    )
    assert service.fetch(123, "36756951") == {"data": []}
