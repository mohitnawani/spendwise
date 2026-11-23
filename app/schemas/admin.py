from __future__ import annotations

from pydantic import BaseModel

from app.schemas.expense import ExpenseRead


class AdminExpenseListResponse(BaseModel):
    items: list[ExpenseRead]
    total: int
    page: int
    page_size: int
    pages: int


class AdminStats(BaseModel):
    total_users_count: int
    total_expenses_count: int
    total_categories_count: int
