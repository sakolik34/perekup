from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ListingFilters(BaseModel):
    q: str | None = Field(None, max_length=120)
    brand: str | None = Field(None, max_length=100)
    model: str | None = Field(None, max_length=100)
    year_from: int | None = Field(None, ge=1900, le=2100)
    year_to: int | None = Field(None, ge=1900, le=2100)
    price_from: float | None = Field(None, ge=0, allow_inf_nan=False)
    price_to: float | None = Field(None, ge=0, allow_inf_nan=False)
    mileage_max: int | None = Field(None, ge=0)
    location: str | None = Field(None, max_length=100)
    fuel_type: str | None = Field(None, max_length=100)
    transmission: str | None = Field(None, max_length=100)
    discount_min: float | None = Field(None, ge=0, le=100, allow_inf_nan=False)
    profit_min: float | None = Field(None, allow_inf_nan=False)
    risk_max: float | None = Field(None, ge=0, le=100, allow_inf_nan=False)
    sort: Literal["profit", "price", "date", "score"] = "score"
    page: int = Field(1, ge=1)
    page_size: int = Field(12, ge=1, le=100)

    @model_validator(mode="after")
    def ranges(self):
        for name in ("year", "price"):
            low, high = getattr(self, f"{name}_from"), getattr(self, f"{name}_to")
            if low is not None and high is not None and low > high:
                raise ValueError("Нижняя граница должна быть не больше верхней")
        return self


class CalculateRequest(BaseModel):
    repair_cost: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    additional_expenses: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
