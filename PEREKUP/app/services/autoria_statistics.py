from app.providers.autoria import AutoRiaClient
from app.providers.base import ProviderError


class AutoRiaStatisticsService:
    """Платный метод статистики; вызывается только явно, вне MVP-оценки."""

    def __init__(self, settings, client=None):
        self.client = client or AutoRiaClient(settings)

    def fetch(self, user_id: int, listing_id: str, period: int = 365):
        if user_id <= 0 or not listing_id.isdigit() or period <= 0:
            raise ValueError("Нужны корректные user_id, listing_id и период")
        data = self.client.request(
            "/auto/statistic-avarage-price/",
            {"user_id": user_id},
            method="POST",
            body={"langId": 4, "period": period, "params": {"omniId": listing_id}},
        )
        if not isinstance(data, dict):
            raise ProviderError("Неожиданный формат статистики AUTO.RIA")
        return data
