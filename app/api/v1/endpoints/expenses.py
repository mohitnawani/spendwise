from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import require_user
from app.core.security import AuthenticatedUser
from app.db.models.category import Category
from app.db.models.expense import Expense
from app.db.session import get_db
from app.schemas.expense import (
    ExpenseCreate,
    ExpenseListResponse,
    ExpenseRead,
    ExpenseSummary,
    ExpenseUpdate,
    SpendingByCategory,
    SpendingByCurrency,
)

router = APIRouter(prefix="/expenses", tags=["Expenses"])


@router.post("", response_model=ExpenseRead, status_code=status.HTTP_201_CREATED)
async def create_expense(
    payload: ExpenseCreate,
    current_user: AuthenticatedUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> Expense:
    # Verify that category exists and belongs to current user
    category = await db.scalar(
        select(Category).where(
            Category.id == payload.category_id,
            Category.owner_id == current_user.id,
        )
    )
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found or does not belong to the authenticated user",
        )

    expense = Expense(
        owner_id=current_user.id,
        category_id=payload.category_id,
        title=payload.title,
        amount=payload.amount,
        currency=payload.currency.upper(),
        spent_at=payload.spent_at,
        notes=payload.notes,
    )
    db.add(expense)
    await db.commit()
    await db.refresh(expense, ["category"])
    return expense


@router.get("/summary", response_model=ExpenseSummary)
async def get_expense_summary(
    current_user: AuthenticatedUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> ExpenseSummary:
    # Total count
    total_count = (
        await db.scalar(
            select(func.count(Expense.id)).where(Expense.owner_id == current_user.id)
        )
        or 0
    )

    # By currency
    currency_query = (
        select(
            Expense.currency,
            func.sum(Expense.amount).label("total_amount"),
            func.count(Expense.id).label("expense_count"),
        )
        .where(Expense.owner_id == current_user.id)
        .group_by(Expense.currency)
        .order_by(Expense.currency.asc())
    )
    currency_rows = (await db.execute(currency_query)).all()
    by_currency = [
        SpendingByCurrency(
            currency=row.currency,
            total_amount=row.total_amount,
            count=row.expense_count,
        )
        for row in currency_rows
    ]

    # By category
    category_query = (
        select(
            Category.id.label("category_id"),
            Category.name.label("category_name"),
            Expense.currency,
            func.sum(Expense.amount).label("total_amount"),
            func.count(Expense.id).label("expense_count"),
        )
        .join(Category, Expense.category_id == Category.id)
        .where(Expense.owner_id == current_user.id)
        .group_by(Category.id, Category.name, Expense.currency)
        .order_by(Category.name.asc(), Expense.currency.asc())
    )
    category_rows = (await db.execute(category_query)).all()
    by_category = [
        SpendingByCategory(
            category_id=row.category_id,
            category_name=row.category_name,
            currency=row.currency,
            total_amount=row.total_amount,
            count=row.expense_count,
        )
        for row in category_rows
    ]

    return ExpenseSummary(
        total_expenses_count=total_count,
        by_currency=by_currency,
        by_category=by_category,
    )


@router.get("", response_model=ExpenseListResponse)
async def list_expenses(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    category_id: uuid.UUID | None = Query(default=None),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
    current_user: AuthenticatedUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> ExpenseListResponse:
    base_conditions = [Expense.owner_id == current_user.id]

    if category_id:
        base_conditions.append(Expense.category_id == category_id)
    if currency:
        base_conditions.append(Expense.currency == currency.upper())
    if from_date:
        base_conditions.append(Expense.spent_at >= from_date)
    if to_date:
        base_conditions.append(Expense.spent_at <= to_date)

    # Total count
    total = await db.scalar(select(func.count(Expense.id)).where(*base_conditions)) or 0

    # Paginated query
    query = (
        select(Expense)
        .options(selectinload(Expense.category))
        .where(*base_conditions)
        .order_by(Expense.spent_at.desc(), Expense.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [ExpenseRead.model_validate(e) for e in (await db.scalars(query)).all()]
    pages = math.ceil(total / page_size) if total > 0 else 1

    return ExpenseListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get("/{expense_id}", response_model=ExpenseRead)
async def get_expense(
    expense_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> Expense:
    expense = await db.scalar(
        select(Expense)
        .options(selectinload(Expense.category))
        .where(
            Expense.id == expense_id,
            Expense.owner_id == current_user.id,
        )
    )
    if not expense:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Expense not found",
        )
    return expense


@router.patch("/{expense_id}", response_model=ExpenseRead)
async def update_expense(
    expense_id: uuid.UUID,
    payload: ExpenseUpdate,
    current_user: AuthenticatedUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> Expense:
    expense = await db.scalar(
        select(Expense)
        .options(selectinload(Expense.category))
        .where(
            Expense.id == expense_id,
            Expense.owner_id == current_user.id,
        )
    )
    if not expense:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Expense not found",
        )

    # If updating category, check ownership
    if payload.category_id is not None:
        cat = await db.scalar(
            select(Category).where(
                Category.id == payload.category_id,
                Category.owner_id == current_user.id,
            )
        )
        if not cat:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Category not found or does not belong to user",
            )
        expense.category_id = payload.category_id

    if payload.title is not None:
        expense.title = payload.title
    if payload.amount is not None:
        expense.amount = payload.amount
    if payload.currency is not None:
        expense.currency = payload.currency.upper()
    if payload.spent_at is not None:
        expense.spent_at = payload.spent_at
    if payload.notes is not None:
        expense.notes = payload.notes

    expense.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(expense, ["category"])
    return expense


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_expense(
    expense_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    expense = await db.scalar(
        select(Expense).where(
            Expense.id == expense_id,
            Expense.owner_id == current_user.id,
        )
    )
    if not expense:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Expense not found",
        )

    await db.delete(expense)
    await db.commit()
