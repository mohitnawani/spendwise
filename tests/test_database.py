import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    UniqueConstraint,
    delete,
    select,
)
from sqlalchemy.exc import IntegrityError

from app.db.models import Base, Category, Expense
from app.db.session import async_session_factory


def test_models_metadata_schema() -> None:
    """Verify table structures, columns, and constraints in SQLAlchemy metadata."""
    assert "categories" in Base.metadata.tables
    assert "expenses" in Base.metadata.tables

    # Verify categories schema
    cat_table = Base.metadata.tables["categories"]
    assert "id" in cat_table.c
    assert "owner_id" in cat_table.c
    assert "name" in cat_table.c
    assert "created_at" in cat_table.c

    cat_unique = [c for c in cat_table.constraints if isinstance(c, UniqueConstraint)]
    assert any(
        {"owner_id", "name"} == {col.name for col in c.columns} for c in cat_unique
    )

    # Verify expenses schema
    exp_table = Base.metadata.tables["expenses"]
    assert "id" in exp_table.c
    assert "owner_id" in exp_table.c
    assert "category_id" in exp_table.c
    assert "title" in exp_table.c
    assert "amount" in exp_table.c
    assert "currency" in exp_table.c
    assert "spent_at" in exp_table.c
    assert "notes" in exp_table.c
    assert "created_at" in exp_table.c
    assert "updated_at" in exp_table.c

    exp_fks = [c for c in exp_table.constraints if isinstance(c, ForeignKeyConstraint)]
    assert any(
        c.referred_table.name == "categories" and c.ondelete == "RESTRICT"
        for c in exp_fks
    )

    exp_checks = [c for c in exp_table.constraints if isinstance(c, CheckConstraint)]
    assert any("amount > 0" in str(c.sqltext) for c in exp_checks)


@pytest.mark.asyncio
async def test_database_persistence_and_constraints() -> None:
    """Test actual persistence, relationships, and constraints
    against the live database.
    """
    async with async_session_factory() as session:
        unique_owner = f"user_{uuid.uuid4().hex[:8]}"
        category = Category(
            owner_id=unique_owner,
            name="Groceries",
        )
        session.add(category)
        await session.commit()
        await session.refresh(category)

        assert category.id is not None
        assert category.created_at is not None
        cat_id = category.id

        # Create an expense linked to this category
        expense = Expense(
            owner_id=unique_owner,
            category_id=cat_id,
            title="Weekly vegetables",
            amount=Decimal("450.75"),
            currency="INR",
            spent_at=datetime.now(UTC),
            notes="Farmer market",
        )
        session.add(expense)
        await session.commit()
        await session.refresh(expense)

        assert expense.id is not None
        assert expense.amount == Decimal("450.75")
        assert expense.category_id == cat_id

        # Verify querying
        result = await session.execute(select(Expense).where(Expense.id == expense.id))
        fetched = result.scalar_one()
        assert fetched.title == "Weekly vegetables"

        # Verify unique category name per owner (same owner + same name must fail)
        duplicate_cat = Category(
            owner_id=unique_owner,
            name="Groceries",
        )
        session.add(duplicate_cat)
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

        # Verify positive amount check constraint (amount <= 0 must fail)
        invalid_expense = Expense(
            owner_id=unique_owner,
            category_id=cat_id,
            title="Negative expense",
            amount=Decimal("-10.00"),
            currency="INR",
            spent_at=datetime.now(UTC),
        )
        session.add(invalid_expense)
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

        # Clean up test records
        await session.execute(delete(Expense).where(Expense.owner_id == unique_owner))
        await session.execute(delete(Category).where(Category.owner_id == unique_owner))
        await session.commit()
