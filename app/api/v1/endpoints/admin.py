from __future__ import annotations

import math

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import require_admin
from app.core.security import AuthenticatedUser
from app.db.models.category import Category
from app.db.models.expense import Expense
from app.db.session import get_db
from app.schemas.admin import AdminExpenseListResponse, AdminStats
from app.schemas.expense import ExpenseRead

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/expenses", response_model=AdminExpenseListResponse)
async def list_all_expenses(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    admin: AuthenticatedUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminExpenseListResponse:
    total = await db.scalar(select(func.count(Expense.id))) or 0

    query = (
        select(Expense)
        .options(selectinload(Expense.category))
        .order_by(Expense.spent_at.desc(), Expense.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [ExpenseRead.model_validate(e) for e in (await db.scalars(query)).all()]
    pages = math.ceil(total / page_size) if total > 0 else 1

    return AdminExpenseListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get("/stats", response_model=AdminStats)
async def get_service_stats(
    admin: AuthenticatedUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminStats:
    total_expenses = await db.scalar(select(func.count(Expense.id))) or 0
    total_categories = await db.scalar(select(func.count(Category.id))) or 0

    expense_users = select(Expense.owner_id).distinct()
    category_users = select(Category.owner_id).distinct()
    all_users_union = expense_users.union(category_users).subquery()
    total_users = (
        await db.scalar(select(func.count()).select_from(all_users_union)) or 0
    )

    return AdminStats(
        total_users_count=total_users,
        total_expenses_count=total_expenses,
        total_categories_count=total_categories,
    )
