from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    database_url: str = "postgresql+psycopg://perekup@db:5432/perekup"
    autoria_api_key: SecretStr = SecretStr("")
    listing_provider: Literal["mock", "autoria", "rst"] = "mock"
    import_interval_minutes: int = Field(1440, ge=5)
    min_comparable_listings: int = Field(5, ge=3)
    default_repair_cost: float = Field(500, ge=0, allow_inf_nan=False)
    default_additional_expenses: float = Field(350, ge=0, allow_inf_nan=False)
    inactive_after_days: int = Field(14, ge=1)
    import_on_startup: bool = True
    scheduler_enabled: bool = True
    autoria_request_delay_seconds: float = Field(2, ge=1)
    autoria_max_pages: int = Field(1, ge=1, le=20)
    autoria_page_size: int = Field(20, ge=1, le=100)
    autoria_search_params: dict = Field(
        default_factory=lambda: {"category_id": 1, "marka_id[0]": 24, "model_id[0]": 186}
    )

    @model_validator(mode="after")
    def validate_provider(self):
        if self.listing_provider == "autoria" and not self.autoria_api_key.get_secret_value():
            raise ValueError("Для LISTING_PROVIDER=autoria укажите AUTORIA_API_KEY в .env")
        if {"api_key", "page", "countpage"} & self.autoria_search_params.keys():
            raise ValueError("api_key, page и countpage задаются отдельно от AUTORIA_SEARCH_PARAMS")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
