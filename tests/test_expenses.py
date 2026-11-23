from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import create_token


@pytest.mark.asyncio
async def test_expense_crud_and_cross_user_isolation(client: AsyncClient) -> None:
    user_a = f"user_a_{uuid.uuid4().hex[:6]}"
    user_b = f"user_b_{uuid.uuid4().hex[:6]}"

    token_a = create_token(sub=user_a, roles=["USER"])
    token_b = create_token(sub=user_b, roles=["USER"])

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 1. Create categories for User A and User B
    cat_a_resp = await client.post(
        "/api/v1/categories",
        json={"name": "Travel"},
        headers=headers_a,
    )
    cat_a_id = cat_a_resp.json()["id"]

    cat_b_resp = await client.post(
        "/api/v1/categories",
        json={"name": "Travel B"},
        headers=headers_b,
    )
    cat_b_id = cat_b_resp.json()["id"]

    # 2. Reject negative or zero amount (Pydantic validation: 422)
    resp_negative = await client.post(
        "/api/v1/expenses",
        json={
            "title": "Invalid Amount",
            "amount": "-50.00",
            "currency": "USD",
            "category_id": cat_a_id,
            "spent_at": "2026-01-15T12:00:00Z",
        },
        headers=headers_a,
    )
    assert resp_negative.status_code == 422

    # 3. Reject invalid currency code (Pydantic validation: 422)
    resp_currency = await client.post(
        "/api/v1/expenses",
        json={
            "title": "Invalid Currency",
            "amount": "50.00",
            "currency": "US",
            "category_id": cat_a_id,
            "spent_at": "2026-01-15T12:00:00Z",
        },
        headers=headers_a,
    )
    assert resp_currency.status_code == 422

    # 4. Reject attaching someone else's category:
    # User A attempts to use User B's category -> 404
    resp_wrong_cat = await client.post(
        "/api/v1/expenses",
        json={
            "title": "Cross User Category",
            "amount": "100.00",
            "currency": "USD",
            "category_id": cat_b_id,
            "spent_at": "2026-01-15T12:00:00Z",
        },
        headers=headers_a,
    )
    assert resp_wrong_cat.status_code == 404

    # 5. User A creates a valid expense
    exp_resp = await client.post(
        "/api/v1/expenses",
        json={
            "title": "Flight ticket",
            "amount": "350.00",
            "currency": "USD",
            "category_id": cat_a_id,
            "spent_at": "2026-01-10T08:30:00Z",
            "notes": "Business trip",
        },
        headers=headers_a,
    )
    assert exp_resp.status_code == 201
    exp_data = exp_resp.json()
    exp_id = exp_data["id"]
    assert exp_data["owner_id"] == user_a
    assert exp_data["amount"] == "350.00"

    # 6. IDOR Check: User B CANNOT read User A's expense -> 404
    resp_get_b = await client.get(
        f"/api/v1/expenses/{exp_id}",
        headers=headers_b,
    )
    assert resp_get_b.status_code == 404

    # 7. IDOR Check: User B CANNOT patch User A's expense -> 404
    resp_patch_b = await client.patch(
        f"/api/v1/expenses/{exp_id}",
        json={"title": "Hacked Title"},
        headers=headers_b,
    )
    assert resp_patch_b.status_code == 404

    # 8. IDOR Check: User B CANNOT delete User A's expense -> 404
    resp_del_b = await client.delete(
        f"/api/v1/expenses/{exp_id}",
        headers=headers_b,
    )
    assert resp_del_b.status_code == 404

    # 9. User A updates their own expense
    resp_patch_a = await client.patch(
        f"/api/v1/expenses/{exp_id}",
        json={"amount": "380.00", "notes": "Upgraded seat"},
        headers=headers_a,
    )
    assert resp_patch_a.status_code == 200
    assert resp_patch_a.json()["amount"] == "380.00"
    assert resp_patch_a.json()["notes"] == "Upgraded seat"

    # 10. User A deletes their own expense -> 204
    resp_del_a = await client.delete(
        f"/api/v1/expenses/{exp_id}",
        headers=headers_a,
    )
    assert resp_del_a.status_code == 204


@pytest.mark.asyncio
async def test_expense_filters_and_pagination(client: AsyncClient) -> None:
    user_id = f"user_filter_{uuid.uuid4().hex[:6]}"
    token = create_token(sub=user_id, roles=["USER"])
    headers = {"Authorization": f"Bearer {token}"}

    # Create 2 categories
    cat1_id = (
        await client.post(
            "/api/v1/categories",
            json={"name": "Food"},
            headers=headers,
        )
    ).json()["id"]
    cat2_id = (
        await client.post(
            "/api/v1/categories",
            json={"name": "Transport"},
            headers=headers,
        )
    ).json()["id"]

    # Create 3 expenses
    await client.post(
        "/api/v1/expenses",
        json={
            "title": "Dinner",
            "amount": "50.00",
            "currency": "EUR",
            "category_id": cat1_id,
            "spent_at": "2026-01-05T19:00:00Z",
        },
        headers=headers,
    )
    await client.post(
        "/api/v1/expenses",
        json={
            "title": "Lunch",
            "amount": "25.00",
            "currency": "EUR",
            "category_id": cat1_id,
            "spent_at": "2026-01-10T13:00:00Z",
        },
        headers=headers,
    )
    await client.post(
        "/api/v1/expenses",
        json={
            "title": "Taxi",
            "amount": "30.00",
            "currency": "USD",
            "category_id": cat2_id,
            "spent_at": "2026-01-20T08:00:00Z",
        },
        headers=headers,
    )

    # Filter by currency=EUR -> 2 items
    resp_eur = await client.get("/api/v1/expenses?currency=EUR", headers=headers)
    assert resp_eur.status_code == 200
    assert resp_eur.json()["total"] == 2

    # Filter by category_id=cat2_id -> 1 item
    resp_cat = await client.get(
        f"/api/v1/expenses?category_id={cat2_id}",
        headers=headers,
    )
    assert resp_cat.status_code == 200
    assert resp_cat.json()["total"] == 1

    # Filter by date range (2026-01-01 to 2026-01-08) -> 1 item (Dinner)
    resp_date = await client.get(
        "/api/v1/expenses?from_date=2026-01-01T00:00:00Z&to_date=2026-01-08T00:00:00Z",
        headers=headers,
    )
    assert resp_date.status_code == 200
    assert resp_date.json()["total"] == 1
    assert resp_date.json()["items"][0]["title"] == "Dinner"

    # Pagination test: page=1, page_size=2 -> items: 2, total: 3, pages: 2
    resp_page1 = await client.get(
        "/api/v1/expenses?page=1&page_size=2",
        headers=headers,
    )
    assert resp_page1.status_code == 200
    p1_data = resp_page1.json()
    assert len(p1_data["items"]) == 2
    assert p1_data["total"] == 3
    assert p1_data["pages"] == 2

    # Verify Summary endpoint
    resp_summary = await client.get("/api/v1/expenses/summary", headers=headers)
    assert resp_summary.status_code == 200
    summary_data = resp_summary.json()
    assert summary_data["total_expenses_count"] == 3
    # Check currency breakdown
    currencies = {c["currency"]: c["total_amount"] for c in summary_data["by_currency"]}
    assert currencies["EUR"] == "75.00"
    assert currencies["USD"] == "30.00"
