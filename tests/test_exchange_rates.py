from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import AsyncClient

from tests.conftest import create_token


@pytest.mark.asyncio
async def test_convert_missing_token_returns_401(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/exchange-rates/convert?amount=100&from=USD&to=INR")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_convert_validation_errors_returns_422(client: AsyncClient) -> None:
    token = create_token(roles=["USER"])
    headers = {"Authorization": f"Bearer {token}"}

    # Negative amount
    resp = await client.get(
        "/api/v1/exchange-rates/convert?amount=-50&from=USD&to=INR",
        headers=headers,
    )
    assert resp.status_code == 422

    # Zero amount
    resp = await client.get(
        "/api/v1/exchange-rates/convert?amount=0&from=USD&to=INR",
        headers=headers,
    )
    assert resp.status_code == 422

    # Invalid currency code (lowercase or not 3 chars)
    resp = await client.get(
        "/api/v1/exchange-rates/convert?amount=100&from=us&to=INR",
        headers=headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_convert_identical_currencies_shortcut(client: AsyncClient) -> None:
    token = create_token(roles=["USER"])
    headers = {"Authorization": f"Bearer {token}"}

    with patch("app.integrations.frankfurter.httpx.AsyncClient") as mock_client_cls:
        resp = await client.get(
            "/api/v1/exchange-rates/convert?amount=100.00&from=USD&to=USD",
            headers=headers,
        )
        assert resp.status_code == 200
        mock_client_cls.assert_not_called()

        data = resp.json()
        assert data["amount"] == "100.00"
        assert data["from_currency"] == "USD"
        assert data["to_currency"] == "USD"
        assert data["rate"] == "1.00" or data["rate"] == "1.0" or data["rate"] == "1"
        assert data["converted_amount"] == "100.00"
        assert "rate_date" in data


@pytest.mark.asyncio
async def test_convert_success_happy_path(client: AsyncClient) -> None:
    token = create_token(roles=["USER"])
    headers = {"Authorization": f"Bearer {token}"}

    fake_response = httpx.Response(
        status_code=200,
        json={
            "amount": 1.0,
            "base": "USD",
            "date": "2026-01-15",
            "rates": {"INR": 83.12},
        },
        request=httpx.Request("GET", "https://api.frankfurter.dev/v1/latest"),
    )

    with patch("app.integrations.frankfurter.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = fake_response

        resp = await client.get(
            "/api/v1/exchange-rates/convert?amount=100.00&from=USD&to=INR",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["amount"] == "100.00"
        assert data["from_currency"] == "USD"
        assert data["to_currency"] == "INR"
        assert data["rate"] == "83.12"
        assert data["converted_amount"] == "8312.00"
        assert data["rate_date"] == "2026-01-15"


@pytest.mark.asyncio
async def test_convert_upstream_timeout_returns_503(client: AsyncClient) -> None:
    token = create_token(roles=["USER"])
    headers = {"Authorization": f"Bearer {token}"}

    with patch("app.integrations.frankfurter.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client.get.side_effect = httpx.ReadTimeout(
            "Timeout connecting to Frankfurter"
        )

        resp = await client.get(
            "/api/v1/exchange-rates/convert?amount=100.00&from=USD&to=INR",
            headers=headers,
        )
        assert resp.status_code == 503
        assert resp.json()["error"]["message"] == "Currency exchange service timed out"


@pytest.mark.asyncio
async def test_convert_upstream_connection_failure_returns_502(
    client: AsyncClient,
) -> None:
    token = create_token(roles=["USER"])
    headers = {"Authorization": f"Bearer {token}"}

    with patch("app.integrations.frankfurter.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")

        resp = await client.get(
            "/api/v1/exchange-rates/convert?amount=100.00&from=USD&to=INR",
            headers=headers,
        )
        assert resp.status_code == 502
        assert (
            resp.json()["error"]["message"]
            == "Unable to connect to upstream currency service"
        )


@pytest.mark.asyncio
async def test_convert_unsupported_currency_pair_returns_400(
    client: AsyncClient,
) -> None:
    token = create_token(roles=["USER"])
    headers = {"Authorization": f"Bearer {token}"}

    fake_response = httpx.Response(
        status_code=404,
        json={"message": "not found"},
        request=httpx.Request("GET", "https://api.frankfurter.dev/v1/latest"),
    )

    with patch("app.integrations.frankfurter.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = fake_response

        resp = await client.get(
            "/api/v1/exchange-rates/convert?amount=100.00&from=XYZ&to=ABC",
            headers=headers,
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["message"] == "Unsupported currency pair"


@pytest.mark.asyncio
async def test_convert_upstream_server_error_returns_502(
    client: AsyncClient,
) -> None:
    token = create_token(roles=["USER"])
    headers = {"Authorization": f"Bearer {token}"}

    fake_response = httpx.Response(
        status_code=500,
        text="Internal Server Error",
        request=httpx.Request("GET", "https://api.frankfurter.dev/v1/latest"),
    )

    with patch("app.integrations.frankfurter.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = fake_response

        resp = await client.get(
            "/api/v1/exchange-rates/convert?amount=100.00&from=USD&to=EUR",
            headers=headers,
        )
        assert resp.status_code == 502
        assert resp.json()["error"]["message"] == "Upstream currency service error"


@pytest.mark.asyncio
async def test_convert_malformed_upstream_payload_returns_502(
    client: AsyncClient,
) -> None:
    token = create_token(roles=["USER"])
    headers = {"Authorization": f"Bearer {token}"}

    # Missing target currency in rates dict
    fake_response = httpx.Response(
        status_code=200,
        json={"amount": 1.0, "base": "USD", "date": "2026-01-15", "rates": {}},
        request=httpx.Request("GET", "https://api.frankfurter.dev/v1/latest"),
    )

    with patch("app.integrations.frankfurter.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = fake_response

        resp = await client.get(
            "/api/v1/exchange-rates/convert?amount=100.00&from=USD&to=EUR",
            headers=headers,
        )
        assert resp.status_code == 502
        assert (
            resp.json()["error"]["message"]
            == "Malformed response from upstream currency service"
        )
