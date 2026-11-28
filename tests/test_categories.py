from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import create_token


@pytest.mark.asyncio
async def test_category_crud_and_ownership(client: AsyncClient) -> None:
    user_a = f"user_a_{uuid.uuid4().hex[:6]}"
    user_b = f"user_b_{uuid.uuid4().hex[:6]}"

    token_a = create_token(sub=user_a, roles=["USER"])
    token_b = create_token(sub=user_b, roles=["USER"])

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 1. User A creates a category
    resp = await client.post(
        "/api/v1/categories",
        json={"name": "Groceries"},
        headers=headers_a,
    )
    assert resp.status_code == 201
    cat_a = resp.json()
    assert cat_a["name"] == "Groceries"
    assert cat_a["owner_id"] == user_a
    cat_a_id = cat_a["id"]

    # 2. Reject blank category name (Pydantic validation: 422)
    resp_blank = await client.post(
        "/api/v1/categories",
        json={"name": ""},
        headers=headers_a,
    )
    assert resp_blank.status_code == 422

    # 3. Duplicate category for same owner -> 409 Conflict
    resp_dup = await client.post(
        "/api/v1/categories",
        json={"name": "Groceries"},
        headers=headers_a,
    )
    assert resp_dup.status_code == 409

    # 4. User B CAN create a category with the same name (scoped per owner)
    resp_b = await client.post(
        "/api/v1/categories",
        json={"name": "Groceries"},
        headers=headers_b,
    )
    assert resp_b.status_code == 201
    assert resp_b.json()["owner_id"] == user_b

    # 5. List categories: User A sees only their own categories
    resp_list = await client.get("/api/v1/categories", headers=headers_a)
    assert resp_list.status_code == 200
    items = resp_list.json()
    assert any(c["id"] == cat_a_id for c in items)
    assert all(c["owner_id"] == user_a for c in items)

    # 6. IDOR Check: User B CANNOT read User A's category (returns 404)
    resp_get_b = await client.get(
        f"/api/v1/categories/{cat_a_id}",
        headers=headers_b,
    )
    assert resp_get_b.status_code == 404

    # 7. IDOR Check: User B CANNOT update User A's category (returns 404)
    resp_update_b = await client.patch(
        f"/api/v1/categories/{cat_a_id}",
        json={"name": "Hacked Name"},
        headers=headers_b,
    )
    assert resp_update_b.status_code == 404

    # 8. User A updates their own category
    resp_update_a = await client.patch(
        f"/api/v1/categories/{cat_a_id}",
        json={"name": "Food & Groceries"},
        headers=headers_a,
    )
    assert resp_update_a.status_code == 200
    assert resp_update_a.json()["name"] == "Food & Groceries"

    # 9. IDOR Check: User B CANNOT delete User A's category (returns 404)
    resp_del_b = await client.delete(
        f"/api/v1/categories/{cat_a_id}",
        headers=headers_b,
    )
    assert resp_del_b.status_code == 404

    # 10. User A deletes their own category (when unused) -> 204
    resp_del_a = await client.delete(
        f"/api/v1/categories/{cat_a_id}",
        headers=headers_a,
    )
    assert resp_del_a.status_code == 204


@pytest.mark.asyncio
async def test_category_delete_conflict_when_referenced(
    client: AsyncClient,
) -> None:
    user_id = f"user_{uuid.uuid4().hex[:6]}"
    token = create_token(sub=user_id, roles=["USER"])
    headers = {"Authorization": f"Bearer {token}"}

    # Create category
    cat_resp = await client.post(
        "/api/v1/categories",
        json={"name": "Utilities"},
        headers=headers,
    )
    cat_id = cat_resp.json()["id"]

    # Create expense referencing this category
    exp_resp = await client.post(
        "/api/v1/expenses",
        json={
            "title": "Electricity Bill",
            "amount": "120.00",
            "currency": "USD",
            "category_id": cat_id,
            "spent_at": "2026-01-15T10:00:00Z",
        },
        headers=headers,
    )
    assert exp_resp.status_code == 201
    exp_id = exp_resp.json()["id"]

    # Attempting to delete category still referenced by expense must fail with 409
    del_cat_resp = await client.delete(
        f"/api/v1/categories/{cat_id}",
        headers=headers,
    )
    assert del_cat_resp.status_code == 409
    assert "still referenced by expenses" in del_cat_resp.json()["error"]["message"]

    # Delete the referencing expense first
    del_exp_resp = await client.delete(
        f"/api/v1/expenses/{exp_id}",
        headers=headers,
    )
    assert del_exp_resp.status_code == 204

    # Now category deletion succeeds
    del_cat_again = await client.delete(
        f"/api/v1/categories/{cat_id}",
        headers=headers,
    )
    assert del_cat_again.status_code == 204
