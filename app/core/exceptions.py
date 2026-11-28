from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import request_id_ctx_var

logger = logging.getLogger("spendwise.errors")

_STATUS_CODE_MAP: dict[int, str] = {
    status.HTTP_400_BAD_REQUEST: "BAD_REQUEST",
    status.HTTP_401_UNAUTHORIZED: "UNAUTHORIZED",
    status.HTTP_403_FORBIDDEN: "FORBIDDEN",
    status.HTTP_404_NOT_FOUND: "RESOURCE_NOT_FOUND",
    status.HTTP_405_METHOD_NOT_ALLOWED: "METHOD_NOT_ALLOWED",
    status.HTTP_409_CONFLICT: "CONFLICT",
    status.HTTP_422_UNPROCESSABLE_CONTENT: "VALIDATION_ERROR",
    status.HTTP_500_INTERNAL_SERVER_ERROR: "INTERNAL_SERVER_ERROR",
    status.HTTP_502_BAD_GATEWAY: "BAD_GATEWAY",
    status.HTTP_503_SERVICE_UNAVAILABLE: "SERVICE_UNAVAILABLE",
}


def _error_payload(
    code: str,
    message: str,
    request_id: str,
    details: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    error_body: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": request_id,
    }
    if details is not None:
        error_body["details"] = details
    return {"error": error_body}


def register_exception_handlers(app: FastAPI) -> None:
    """Register global exception handlers for consistent JSON error responses."""

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        req_id = getattr(request.state, "request_id", request_id_ctx_var.get())
        error_code = _STATUS_CODE_MAP.get(exc.status_code, f"HTTP_{exc.status_code}")
        message = str(exc.detail) if exc.detail else "Request failed"
        headers = dict(exc.headers) if exc.headers else {}
        headers["X-Request-ID"] = req_id
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(error_code, message, req_id),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        req_id = getattr(request.state, "request_id", request_id_ctx_var.get())
        details = [
            {
                "field": ".".join(str(loc) for loc in err.get("loc", ())),
                "message": err.get("msg", "Invalid value"),
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=_error_payload(
                "VALIDATION_ERROR",
                "Request validation failed",
                req_id,
                details=details,
            ),
            headers={"X-Request-ID": req_id},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        req_id = getattr(request.state, "request_id", request_id_ctx_var.get())
        logger.exception(
            "Unhandled server error on %s %s",
            request.method,
            request.url.path,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_payload(
                "INTERNAL_SERVER_ERROR",
                "An unexpected internal error occurred",
                req_id,
            ),
            headers={"X-Request-ID": req_id},
        )
