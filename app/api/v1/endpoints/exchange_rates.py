from decimal import Decimal

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import require_user
from app.core.security import AuthenticatedUser
from app.integrations.frankfurter import convert_currency
from app.schemas.exchange_rate import CurrencyConversionResponse

router = APIRouter(prefix="/exchange-rates", tags=["Exchange Rates"])


@router.get("/convert", response_model=CurrencyConversionResponse)
async def get_currency_conversion(
    amount: Decimal = Query(
        ..., gt=0, decimal_places=2, max_digits=12, description="Amount to convert"
    ),
    from_currency: str = Query(
        ..., alias="from", min_length=3, max_length=3, pattern=r"^[A-Z]{3}$"
    ),
    to_currency: str = Query(
        ..., alias="to", min_length=3, max_length=3, pattern=r"^[A-Z]{3}$"
    ),
    user: AuthenticatedUser = Depends(require_user),
) -> CurrencyConversionResponse:
    return await convert_currency(
        amount=amount,
        from_currency=from_currency.upper(),
        to_currency=to_currency.upper(),
    )
