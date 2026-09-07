import hashlib
import json
import logging
import re
import time
from urllib.parse import urljoin, urlparse

import httpx
from pydantic import ValidationError

from app.providers.base import ImportBatch, ListingData, ListingProvider, ProviderError

# В HTTP-логах иначе может оказаться api_key из query string.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class AutoRiaClient:
    BASE_URL = "https://developers.ria.com"

    def __init__(self, settings, transport=None, sleep=time.sleep):
        self.settings = settings
        self.transport = transport
        self.sleep = sleep

    def request(self, path, params=None, method="GET", body=None):
        query = {**(params or {}), "api_key": self.settings.autoria_api_key.get_secret_value()}
        with httpx.Client(
            base_url=self.BASE_URL, timeout=30, transport=self.transport, follow_redirects=False
        ) as client:
            for attempt in range(3):
                self.sleep(
                    self.settings.autoria_request_delay_seconds if attempt == 0 else 2**attempt
                )
                try:
                    response = client.request(method, path, params=query, json=body)
                except httpx.TransportError:
                    if attempt == 2:
                        raise ProviderError(
                            "AUTO.RIA недоступен: ошибка сети или тайм-аут."
                        ) from None
                    continue
                if response.status_code == 429:
                    raise ProviderError(
                        "AUTO.RIA: исчерпан лимит запросов (429). Импорт остановлен. Дождитесь восстановления квоты; автоматический повтор — не раньше следующего интервала."
                    )
                if response.status_code in (401, 403):
                    raise ProviderError("AUTO.RIA: проверьте API-ключ и доступ к методу (401/403).")
                if response.status_code >= 500 and attempt < 2:
                    continue
                if response.status_code != 200:
                    raise ProviderError(
                        f"AUTO.RIA вернул HTTP {response.status_code}; импорт отменён."
                    )
                try:
                    return response.json()
                except ValueError:
                    raise ProviderError("AUTO.RIA вернул ответ не в формате JSON.") from None
        raise ProviderError("AUTO.RIA временно недоступен.")


def normalize_fuel(value):
    first = (value or "").split(",")[0].strip()
    return {
        "Дизель": "Дизель",
        "Бензин": "Бензин",
        "Електро": "Электро",
        "Електрика": "Электро",
        "Газ / Бензин": "Газ / Бензин",
    }.get(first, first or None)


def normalize_info(raw, external_id):
    try:
        if not isinstance(raw, dict):
            raise ValueError()
        data = raw["autoData"]
        if str(data["autoId"]) != str(external_id):
            raise ValueError()
        fuel = data.get("fuelName", "") or ""
        engine = re.search(r"(\d+(?:[.,]\d+)?)\s*л", fuel)
        link = urljoin("https://auto.ria.com", raw["linkToView"])
        if urlparse(link).hostname != "auto.ria.com":
            raise ValueError()
        photo = (raw.get("photoData") or {}).get("seoLinkB")
        state = raw.get("stateData") or {}
        gearbox = data.get("gearboxName")
        gearbox = {"Ручна / Механіка": "Механика", "Ручна": "Механика", "Механіка": "Механика"}.get(
            gearbox, gearbox
        )
        vin = raw.get("VIN")
        if vin and not re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", vin):
            vin = None
        return ListingData(
            external_id=str(external_id),
            source="autoria",
            url=link,
            title=raw["title"],
            brand=raw["markName"],
            model=raw["modelName"],
            generation=data.get("generationName"),
            year=data["year"],
            price_usd=raw["USD"],
            mileage_km=round(float(data["raceInt"]) * 1000)
            if data.get("raceInt") is not None
            else None,
            city=raw.get("locationCityName"),
            region=state.get("regionName"),
            fuel_type=normalize_fuel(fuel),
            engine_volume=float(engine.group(1).replace(",", ".")) if engine else None,
            transmission=gearbox,
            drive_type=data.get("driveName"),
            description=data.get("description") or "",
            seller_type=(raw.get("dealer") or {}).get("type"),
            vin=vin,
            is_active=bool(data.get("active", True))
            and not data.get("isSold", False)
            and not data.get("fromArchive", False),
            photos=[photo] if photo else [],
        )
    except (KeyError, TypeError, ValueError, ValidationError):
        raise ProviderError(
            f"AUTO.RIA: неподдерживаемый формат карточки {external_id}; данные не сохранены."
        ) from None


class AutoRiaProvider(ListingProvider):
    source = "autoria"

    def __init__(self, settings, client=None):
        self.settings = settings
        self.client = client or AutoRiaClient(settings)

    def fetch(self):
        ids = []
        complete = False
        for page in range(self.settings.autoria_max_pages):
            result = self.client.request(
                "/auto/search",
                {
                    **self.settings.autoria_search_params,
                    "page": page,
                    "countpage": self.settings.autoria_page_size,
                },
            )
            try:
                search = result["result"]["search_result"]
                page_ids = search["ids"]
                total = int(search["count"])
                if (
                    not isinstance(page_ids, list)
                    or any(not str(i).isdigit() for i in page_ids)
                    or total < 0
                ):
                    raise ValueError()
            except (KeyError, TypeError, ValueError):
                raise ProviderError(
                    "AUTO.RIA: неподдерживаемый формат результата поиска."
                ) from None
            ids.extend(str(i) for i in page_ids)
            if len(set(ids)) >= total:
                complete = True
                break
            if not page_ids:
                break
        listings = [
            normalize_info(self.client.request("/auto/info", {"auto_id": i}), i)
            for i in dict.fromkeys(ids)
        ]
        scope = hashlib.sha256(
            json.dumps(self.settings.autoria_search_params, sort_keys=True).encode()
        ).hexdigest()
        warnings = (
            ()
            if complete
            else (
                "Загружена часть результатов. Исчезновение из выборки не означает снятие с продажи; автоматическое снятие отключено для этого импорта.",
            )
        )
        return ImportBatch(listings, complete=complete, scope=scope, warnings=warnings)
