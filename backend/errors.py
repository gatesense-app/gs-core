"""
One error shape for the whole API:

    {"error": {"code": "not_found", "message": "Session not found"}}

Two things this buys us:
  - Clients (and the SPA) parse one shape instead of guessing between FastAPI's
    {"detail": ...} for HTTPException and something else for validation errors.
  - Unhandled exceptions never leak internals. A stack trace or a raw DB error
    can disclose schema, file paths, or query text; the client gets a generic
    500 while the real traceback goes to the server log.
"""

import logging
import traceback

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("gatesense.errors")

# Machine-readable codes for the statuses we actually raise.
_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
}


def _code_for(status: int) -> str:
    return _CODES.get(status, "error")


def error_body(status: int, message: str, code: str | None = None) -> dict:
    return {"error": {"code": code or _code_for(status), "message": message}}


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    # HTTPException detail is written by us, so it is safe to return as-is.
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(exc.status_code, detail),
        headers=getattr(exc, "headers", None),
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Summarize which fields failed without echoing the submitted values back.
    fields = []
    for err in exc.errors():
        loc = [str(p) for p in err.get("loc", []) if p not in ("body", "query", "path")]
        if loc:
            fields.append(".".join(loc))
    message = f"Invalid request: {', '.join(fields)}" if fields else "Invalid request"
    return JSONResponse(status_code=422, content=error_body(422, message))


async def unhandled_exception_handler(request: Request, exc: Exception):
    # Full detail server-side...
    log.error(
        "Unhandled error on %s %s: %s\n%s",
        request.method, request.url.path, exc,
        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    )
    # ...generic message to the client.
    return JSONResponse(
        status_code=500,
        content=error_body(500, "Something went wrong. Please try again."),
    )


def install(app) -> None:
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
