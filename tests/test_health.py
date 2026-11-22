from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.db.session import get_db
from app.main import app


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "application" in data


@pytest.mark.asyncio
async def test_root(client: AsyncClient) -> None:
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert data["docs"] == "/docs"


@pytest.mark.asyncio
async def test_ready_success(client: AsyncClient) -> None:
    async def override_get_db() -> AsyncGenerator[AsyncMock, None]:
        mock_session = AsyncMock()
        mock_session.execute.return_value = None
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = await client.get("/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ready", "database": "connected"}
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_ready_database_unavailable(client: AsyncClient) -> None:
    async def override_get_db() -> AsyncGenerator[AsyncMock, None]:
        mock_session = AsyncMock()
        mock_session.execute.side_effect = ConnectionRefusedError("Database down")
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = await client.get("/ready")
        assert response.status_code == 503
        assert response.json() == {"detail": "Database unavailable"}
    finally:
        app.dependency_overrides.pop(get_db, None)
