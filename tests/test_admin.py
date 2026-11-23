from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import create_token


@pytest.mark.asyncio
async def test_admin_endpoints_access_control(client: AsyncClient) -> None:
    admin_id = f"admin_{uuid.uuid4().hex[:6]}"
    user_id = f"user_{uuid.uuid4().hex[:6]}"

    admin_token = create_token(sub=admin_id, roles=["ADMIN", "USER"])
    user_token = create_token(sub=user_id, roles=["USER"])

    headers_admin = {"Authorization": f"Bearer {admin_token}"}
    headers_user = {"Authorization": f"Bearer {user_token}"}

    # 1. Unauthenticated request to /admin -> 401
    resp_unauth = await client.get("/api/v1/admin/stats")
    assert resp_unauth.status_code == 401

    # 2. Normal USER request to /admin -> 403 Forbidden
    resp_forbidden_stats = await client.get(
        "/api/v1/admin/stats",
        headers=headers_user,
    )
    assert resp_forbidden_stats.status_code == 403

    resp_forbidden_exp = await client.get(
        "/api/v1/admin/expenses",
        headers=headers_user,
    )
    assert resp_forbidden_exp.status_code == 403

    # 3. Create sample category and expense as normal user
    cat_resp = await client.post(
        "/api/v1/categories",
        json={"name": "Admin Test Cat"},
        headers=headers_user,
    )
    cat_id = cat_resp.json()["id"]

    await client.post(
        "/api/v1/expenses",
        json={
            "title": "Test Admin Expense",
            "amount": "99.99",
            "currency": "USD",
            "category_id": cat_id,
            "spent_at": "2026-01-15T12:00:00Z",
        },
        headers=headers_user,
    )

    # 4. Admin CAN access /admin/stats -> 200
    resp_stats = await client.get("/api/v1/admin/stats", headers=headers_admin)
    assert resp_stats.status_code == 200
    stats = resp_stats.json()
    assert stats["total_users_count"] >= 1
    assert stats["total_expenses_count"] >= 1
    assert stats["total_categories_count"] >= 1

    # 5. Admin CAN access /admin/expenses -> 200 (sees expenses across all users)
    resp_exp = await client.get(
        "/api/v1/admin/expenses?page=1&page_size=10",
        headers=headers_admin,
    )
    assert resp_exp.status_code == 200
    data = resp_exp.json()
    assert data["total"] >= 1
    assert any(item["title"] == "Test Admin Expense" for item in data["items"])
