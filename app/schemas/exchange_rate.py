from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class CurrencyConversionResponse(BaseModel):
    amount: Decimal = Field(..., gt=0, description="Original expense amount")
    from_currency: str = Field(
        ..., min_length=3, max_length=3, description="Source 3-letter currency code"
    )
    to_currency: str = Field(
        ..., min_length=3, max_length=3, description="Target 3-letter currency code"
    )
    rate: Decimal = Field(..., gt=0, description="Exchange rate applied")
    converted_amount: Decimal = Field(
        ..., gt=0, description="Calculated converted amount"
    )
    rate_date: date = Field(..., description="Date of the exchange rate")
