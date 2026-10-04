"""One error shape for the whole API.

    { "error": { "code": "not_found", "message": "Project not found" } }

Raise ApiError (or one of the helpers below) from any endpoint. The handlers
registered here turn every failure, including validation errors and unexpected
exceptions, into that shape. See docs/api-contracts.md.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("subpay.api")

# Codes used when a framework-level HTTP error has no ApiError behind it.
_STATUS_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    503: "service_unavailable",
}


class ApiError(Exception):
    """An error that is safe to show to the user."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers


def unauthenticated(message: str = "Sign in to continue") -> ApiError:
    return ApiError(401, "unauthenticated", message, headers={"WWW-Authenticate": "Bearer"})


def forbidden(message: str = "You do not have permission to do that") -> ApiError:
    return ApiError(403, "forbidden", message)


def not_found(what: str = "Resource") -> ApiError:
    """Use for records that do not exist AND records in another organisation."""
    return ApiError(404, "not_found", f"{what} not found")


def conflict(message: str) -> ApiError:
    return ApiError(409, "conflict", message)


def service_unavailable(
    message: str = "Service temporarily unavailable. Try again shortly.",
) -> ApiError:
    return ApiError(503, "service_unavailable", message)


def validation_error(message: str, field: str | None = None) -> ApiError:
    details = [{"field": field, "message": message}] if field else None
    return ApiError(422, "validation_error", message, details=details)


def error_body(code: str, message: str, details: list[dict[str, Any]] | None = None) -> dict:
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return {"error": error}


def _field_name(loc: tuple[Any, ...]) -> str:
    """('body', 'name') -> 'name'; ('query', 'limit') -> 'limit'."""
    parts = [str(p) for p in loc if p not in ("body", "query", "path", "header", "cookie")]
    return ".".join(parts) or ".".join(str(p) for p in loc)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, exc.details),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": _field_name(tuple(err.get("loc", ()))), "message": err.get("msg", "Invalid")}
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=error_body("validation_error", "Request validation failed", details),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODES.get(exc.status_code, "error")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(code, message),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # Log the real cause; never send internals to the client.
        logger.exception("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=error_body("internal_error", "Something went wrong. Please try again."),
        )
