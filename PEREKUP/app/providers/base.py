from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


class ProviderError(Exception):
    pass


class ListingData(BaseModel):
    external_id: str = Field(min_length=1, max_length=100)
    source: str = Field(max_length=30)
    url: str | None = None
    title: str = Field(min_length=1, max_length=250)
    brand: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=100)
    generation: str | None = None
    year: int = Field(ge=1900, le=2100)
    price_usd: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    mileage_km: int | None = Field(None, ge=0)
    city: str | None = None
    region: str | None = None
    fuel_type: str | None = None
    engine_volume: float | None = Field(None, ge=0, le=20)
    transmission: str | None = None
    drive_type: str | None = None
    description: str = ""
    seller_type: str | None = None
    vin: str | None = None
    is_active: bool = True
    photos: list[str] = Field(default_factory=list)

    @field_validator("url")
    @classmethod
    def safe_url(cls, value):
        if value and (urlparse(value).scheme != "https" or not urlparse(value).hostname):
            raise ValueError("Ссылка должна использовать HTTPS")
        return value

    @field_validator("photos")
    @classmethod
    def safe_photos(cls, values):
        for value in values:
            if value.startswith("/static/"):
                continue
            cls.safe_url(value)
        return list(dict.fromkeys(values))[:30]


@dataclass
class ImportBatch:
    listings: list[ListingData]
    complete: bool = True
    scope: str = "default"
    warnings: tuple[str, ...] = ()


class ListingProvider(ABC):
    source: str

    @abstractmethod
    def fetch(self) -> ImportBatch:
        """Возвращает выборку. complete=True только при полном обходе её границ."""
