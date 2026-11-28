from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import request_id_ctx_var, setup_logging
from app.db.session import get_db

setup_logging()
logger = logging.getLogger("spendwise.access")

app = FastAPI(
    title=settings.APP_NAME,
    description="Expense tracking REST API powered by FastAPI and Keycloak",
    version="0.1.0",
)

register_exception_handlers(app)


@app.middleware("http")
async def request_id_and_logging_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Assign a Request ID, log method/path/status/duration, and attach X-Request-ID."""
    req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    token = request_id_ctx_var.set(req_id)
    request.state.request_id = req_id

    start_time = time.perf_counter()
    try:
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            "%s %s -> %d (%.2fms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        response.headers["X-Request-ID"] = req_id
        return response
    finally:
        request_id_ctx_var.reset(token)


# Include v1 API routes
app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    return {
        "status": "healthy",
        "application": settings.APP_NAME,
    }


@app.get("/ready", tags=["Health"])
async def readiness_check(
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    try:
        await db.execute(text("SELECT 1"))
        return {
            "status": "ready",
            "database": "connected",
        }
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from None


@app.get("/", tags=["Root"])
async def root() -> dict[str, str]:
    return {
        "message": f"Welcome to {settings.APP_NAME}",
        "docs": "/docs",
    }
