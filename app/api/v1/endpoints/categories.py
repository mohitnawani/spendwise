from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_user
from app.core.security import AuthenticatedUser
from app.db.models.category import Category
from app.db.models.expense import Expense
from app.db.session import get_db
from app.schemas.category import CategoryCreate, CategoryRead, CategoryUpdate

router = APIRouter(prefix="/categories", tags=["Categories"])


@router.post("", response_model=CategoryRead, status_code=status.HTTP_201_CREATED)
async def create_category(
    payload: CategoryCreate,
    current_user: AuthenticatedUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> Category:
    # Check if a category with the same name already exists for this owner
    existing = await db.scalar(
        select(Category).where(
            Category.owner_id == current_user.id,
            func.lower(Category.name) == payload.name.lower(),
        )
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Category '{payload.name}' already exists for this user",
        )

    category = Category(
        owner_id=current_user.id,
        name=payload.name,
    )
    db.add(category)
    try:
        await db.commit()
        await db.refresh(category)
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Category already exists",
        ) from e

    return category


@router.get("", response_model=list[CategoryRead])
async def list_categories(
    current_user: AuthenticatedUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> list[Category]:
    result = await db.scalars(
        select(Category)
        .where(Category.owner_id == current_user.id)
        .order_by(Category.name.asc())
    )
    return list(result.all())


@router.get("/{category_id}", response_model=CategoryRead)
async def get_category(
    category_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> Category:
    category = await db.scalar(
        select(Category).where(
            Category.id == category_id,
            Category.owner_id == current_user.id,
        )
    )
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )
    return category


@router.patch("/{category_id}", response_model=CategoryRead)
async def update_category(
    category_id: uuid.UUID,
    payload: CategoryUpdate,
    current_user: AuthenticatedUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> Category:
    category = await db.scalar(
        select(Category).where(
            Category.id == category_id,
            Category.owner_id == current_user.id,
        )
    )
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    # Check duplicate name for same user
    conflict = await db.scalar(
        select(Category).where(
            Category.owner_id == current_user.id,
            Category.id != category_id,
            func.lower(Category.name) == payload.name.lower(),
        )
    )
    if conflict:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Category '{payload.name}' already exists for this user",
        )

    category.name = payload.name
    try:
        await db.commit()
        await db.refresh(category)
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Category name conflict",
        ) from e

    return category


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    category = await db.scalar(
        select(Category).where(
            Category.id == category_id,
            Category.owner_id == current_user.id,
        )
    )
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    # Check if any expenses are attached to this category
    expense_count = await db.scalar(
        select(func.count(Expense.id)).where(Expense.category_id == category_id)
    )
    if expense_count and expense_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete category: it is still referenced by expenses",
        )

    await db.delete(category)
    await db.commit()
