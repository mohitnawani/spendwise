from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.category import CategoryRead


class ExpenseBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    amount: Decimal = Field(..., gt=0, decimal_places=2, max_digits=12)
    currency: str = Field(..., min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    category_id: uuid.UUID
    spent_at: datetime
    notes: str | None = Field(default=None)


class ExpenseCreate(ExpenseBase):
    pass


class ExpenseUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    amount: Decimal | None = Field(default=None, gt=0, decimal_places=2, max_digits=12)
    currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
    )
    category_id: uuid.UUID | None = None
    spent_at: datetime | None = None
    notes: str | None = None


class ExpenseRead(ExpenseBase):
    id: uuid.UUID
    owner_id: str
    created_at: datetime
    updated_at: datetime
    category: CategoryRead | None = None

    model_config = ConfigDict(from_attributes=True)


class ExpenseListResponse(BaseModel):
    items: list[ExpenseRead]
    total: int
    page: int
    page_size: int
    pages: int


class SpendingByCurrency(BaseModel):
    currency: str
    total_amount: Decimal
    count: int


class SpendingByCategory(BaseModel):
    category_id: uuid.UUID
    category_name: str
    currency: str
    total_amount: Decimal
    count: int


class ExpenseSummary(BaseModel):
    total_expenses_count: int
    by_currency: list[SpendingByCurrency]
    by_category: list[SpendingByCategory]
