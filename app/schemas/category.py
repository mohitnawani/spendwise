from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CategoryBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Category name")


class CategoryCreate(CategoryBase):
    pass


class CategoryUpdate(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Updated category name",
    )


class CategoryRead(CategoryBase):
    id: uuid.UUID
    owner_id: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
