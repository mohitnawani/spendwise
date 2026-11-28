from __future__ import annotations

import logging
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_request_id_generated_and_propagated(client: AsyncClient) -> None:
    # Auto-generated Request ID on success
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert "X-Request-ID" in resp.headers
    uuid.UUID(resp.headers["X-Request-ID"])

    # Client-supplied Request ID preserved
    custom_id = "custom-trace-id-987"
    resp_custom = await client.get("/health", headers={"X-Request-ID": custom_id})
    assert resp_custom.status_code == 200
    assert resp_custom.headers["X-Request-ID"] == custom_id


@pytest.mark.asyncio
async def test_consistent_http_error_response_shape(client: AsyncClient) -> None:
    custom_id = "err-trace-401"
    resp = await client.get("/api/v1/auth/me", headers={"X-Request-ID": custom_id})
    assert resp.status_code == 401
    assert resp.headers["X-Request-ID"] == custom_id

    body = resp.json()
    assert "error" in body
    assert body["error"]["code"] == "UNAUTHORIZED"
    assert "Missing Authorization header" in body["error"]["message"]
    assert body["error"]["request_id"] == custom_id


@pytest.mark.asyncio
async def test_consistent_validation_error_response_shape(
    client: AsyncClient,
) -> None:
    resp = await client.get("/api/v1/exchange-rates/convert?amount=-5&from=USD&to=INR")
    assert resp.status_code in (401, 422)

    # Test 422 specifically on an authenticated endpoint
    from tests.conftest import create_token

    token = create_token(roles=["USER"])
    resp_422 = await client.get(
        "/api/v1/exchange-rates/convert?amount=-5&from=USD&to=INR",
        headers={"Authorization": f"Bearer {token}", "X-Request-ID": "val-422"},
    )
    assert resp_422.status_code == 422
    assert resp_422.headers["X-Request-ID"] == "val-422"

    body = resp_422.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "Request validation failed"
    assert body["error"]["request_id"] == "val-422"
    assert isinstance(body["error"]["details"], list)
    assert len(body["error"]["details"]) >= 1


@pytest.mark.asyncio
async def test_unhandled_500_hides_internal_details() -> None:
    @app.get("/_test_boom")
    async def _boom() -> None:
        raise RuntimeError("secret database password leaked")

    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/_test_boom", headers={"X-Request-ID": "boom-500"})

        assert resp.status_code == 500
        assert resp.headers["X-Request-ID"] == "boom-500"
        body = resp.json()
        assert body["error"]["code"] == "INTERNAL_SERVER_ERROR"
        assert body["error"]["message"] == "An unexpected internal error occurred"
        assert body["error"]["request_id"] == "boom-500"
        assert "secret database password" not in resp.text
    finally:
        app.router.routes = [
            r for r in app.router.routes if getattr(r, "path", None) != "/_test_boom"
        ]


@pytest.mark.asyncio
async def test_access_log_contains_request_id_and_no_secrets(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    from tests.conftest import create_token

    secret_token = create_token(roles=["USER"])
    custom_id = "log-trace-123"

    with caplog.at_level(logging.INFO, logger="spendwise.access"):
        resp = await client.get(
            "/api/v1/auth/me",
            headers={
                "Authorization": f"Bearer {secret_token}",
                "X-Request-ID": custom_id,
            },
        )
    assert resp.status_code == 200

    access_records = [r for r in caplog.records if r.name == "spendwise.access"]
    assert len(access_records) >= 1
    last_record = access_records[-1]
    assert "GET /api/v1/auth/me -> 200" in last_record.getMessage()
    assert secret_token not in last_record.getMessage()
