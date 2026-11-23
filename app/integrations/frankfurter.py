from __future__ import annotations

import json
import logging
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import httpx
from fastapi import HTTPException, status

from app.core.config import settings
from app.schemas.exchange_rate import CurrencyConversionResponse

logger = logging.getLogger(__name__)


async def convert_currency(
    amount: Decimal,
    from_currency: str,
    to_currency: str,
    client: httpx.AsyncClient | None = None,
) -> CurrencyConversionResponse:
    from_curr = from_currency.upper().strip()
    to_curr = to_currency.upper().strip()

    # 1. Shortcut for identical currencies (no external network call needed)
    if from_curr == to_curr:
        return CurrencyConversionResponse(
            amount=amount,
            from_currency=from_curr,
            to_currency=to_curr,
            rate=Decimal("1.00"),
            converted_amount=amount,
            rate_date=date.today(),
        )

    # 2. Configure explicit timeouts
    timeout = httpx.Timeout(
        connect=2.0,
        read=settings.EXTERNAL_API_TIMEOUT_SECONDS,
        write=settings.EXTERNAL_API_TIMEOUT_SECONDS,
        pool=settings.EXTERNAL_API_TIMEOUT_SECONDS,
    )
    url = f"{settings.FRANKFURTER_BASE_URL.rstrip('/')}/v1/latest"
    params = {"base": from_curr, "symbols": to_curr}

    async def _fetch(http_client: httpx.AsyncClient) -> httpx.Response:
        return await http_client.get(url, params=params)

    # 3. Perform request with error mapping
    try:
        if client is not None:
            response = await _fetch(client)
        else:
            async with httpx.AsyncClient(timeout=timeout) as async_client:
                response = await _fetch(async_client)
    except httpx.TimeoutException as exc:
        logger.warning(
            "Frankfurter API timeout for %s -> %s: %s", from_curr, to_curr, exc
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Currency exchange service timed out",
        ) from exc
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError) as exc:
        logger.warning(
            "Frankfurter API connection failure for %s -> %s: %s",
            from_curr,
            to_curr,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to connect to upstream currency service",
        ) from exc
    except httpx.HTTPError as exc:
        logger.warning(
            "Frankfurter HTTP error for %s -> %s: %s", from_curr, to_curr, exc
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Upstream currency service error",
        ) from exc

    # 4. Handle HTTP status codes from upstream
    if response.status_code == 404:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported currency pair",
        )

    if response.status_code != 200:
        logger.warning(
            "Frankfurter returned non-200 status %d: %s",
            response.status_code,
            response.text,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Upstream currency service error",
        )

    # 5. Parse and validate upstream payload
    try:
        data = response.json()
        rates = data.get("rates")
        if not isinstance(rates, dict) or to_curr not in rates:
            raise ValueError(f"Missing rate for {to_curr} in upstream response")

        rate_val = Decimal(str(rates[to_curr]))
        rate_date = date.fromisoformat(data["date"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        logger.warning(
            "Malformed Frankfurter response for %s -> %s: %s",
            from_curr,
            to_curr,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Malformed response from upstream currency service",
        ) from exc

    converted_amount = (amount * rate_val).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    return CurrencyConversionResponse(
        amount=amount,
        from_currency=from_curr,
        to_currency=to_curr,
        rate=rate_val,
        converted_amount=converted_amount,
        rate_date=rate_date,
    )
