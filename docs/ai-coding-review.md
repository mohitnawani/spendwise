# AI Coding Review — One Failure

## Context
In **Milestone 4 (Core Domain CRUD & Ownership Enforcement)**, we added integration tests in `tests/test_categories.py`, `tests/test_expenses.py`, and `tests/test_admin.py` using `pytest-asyncio` and `httpx.AsyncClient` against a real PostgreSQL container via SQLAlchemy's async engine (`asyncpg`).

## What the coding agent proposed
The initial `app/db/session.py` and `tests/conftest.py` setup created a single module-level `async_engine = create_async_engine(...)` with default connection pooling (`AsyncAdaptedQueuePool`) and ran `pytest` with `asyncio_default_fixture_loop_scope = "function"`. No test-teardown hook disposed of the database connection pool between test functions.

## Why it was wrong or suboptimal
Because `pytest-asyncio` with function-scoped loops creates and closes a fresh `asyncio` event loop for every test function, connections opened and returned to SQLAlchemy's global connection pool during Test 1 remained bound to Test 1's closed event loop. When Test 2 checked out a pooled connection—or when pool cleanup ran on an already-closed loop—`asyncpg` crashed with:

- `RuntimeError: Task ... got Future <Future pending> attached to a different loop`
- `RuntimeError: Event loop is closed`

While the first test passed in isolation, running the full suite caused cascading intermittent failures across `test_categories.py`, `test_database.py`, and `test_expenses.py`.

## How I detected it
Running the full test suite inside the Docker container (`docker exec spendwise-api pytest -vv`) after adding the Milestone 4 test files exposed 3 failures out of 22 tests with `Event loop is closed` and `attached to a different loop` tracebacks from `asyncpg/protocol/protocol.pyx`.

## What I changed
Added an `autouse=True` async fixture (`cleanup_db_connections`) in `tests/conftest.py` that calls `await engine.dispose()` in teardown at the end of every test while that test's event loop is still open:

```python
@pytest.fixture(autouse=True)
async def cleanup_db_connections() -> AsyncGenerator[None, None]:
    yield
    await engine.dispose()
```

Re-running `docker exec spendwise-api pytest -vv` confirmed all 22 tests passed cleanly with zero unawaited-coroutine warnings or loop-mismatch errors.

## Engineering lesson
Global stateful resources—especially async database connection pools—cannot safely outlive the event loop that created their sockets. When using function-scoped event loops in `pytest-asyncio`, always dispose of async engine pools before loop teardown (or use `NullPool` in test environments) and verify by running the entire test suite together, not just individual test files.
