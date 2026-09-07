from app.providers.base import ListingProvider, ProviderError


class RstProvider(ListingProvider):
    source = "rst"

    def fetch(self):
        raise ProviderError(
            "RST пока не подключён. Способ получения данных и разрешение площадки нужно согласовать отдельно; парсинг и обход защиты не реализованы."
        )
