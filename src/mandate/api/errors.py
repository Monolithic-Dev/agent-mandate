"""Error handling: every failure becomes the documented JSON error body."""

from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from mandate.errors import MandateError
from mandate.logging import get_logger
from mandate.observability import metrics

log = get_logger(__name__)

MAX_BODY_BYTES = 64 * 1024
REQUEST_ID_HEADER = "X-Request-Id"


def request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _body(code: str, message: str, request: Request, details: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    rid = request_id_of(request)
    if rid:
        error["request_id"] = rid
    if details:
        error["details"] = details
    return {"error": error}


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request id, rejects oversized bodies, and records request metrics."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.request_id = f"req_{uuid.uuid4().hex[:20]}"
        began = time.perf_counter()
        declared = request.headers.get("content-length")
        too_large = declared is not None and declared.isdigit() and int(declared) > MAX_BODY_BYTES
        if too_large:
            response: Response = JSONResponse(
                _body("payload_too_large", "request body is too large", request), status_code=413
            )
        else:
            response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request.state.request_id
        # The route template (not the raw path) keeps label cardinality bounded: ids in the
        # path would otherwise create a new series per tenant, instruction and decision.
        route = getattr(request.scope.get("route"), "path", "unmatched")
        metrics.HTTP_REQUESTS.labels(request.method, route, str(response.status_code)).inc()
        metrics.HTTP_SECONDS.labels(route).observe(time.perf_counter() - began)
        return response


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(MandateError)
    async def mandate_error(request: Request, error: MandateError) -> JSONResponse:
        if error.http_status >= 500:
            log.error("request_failed", code=error.code, path=request.url.path)
        return JSONResponse(
            _body(error.code, error.message, request, error.details), status_code=error.http_status
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        first = error.errors()[0] if error.errors() else {"msg": "invalid request", "loc": ()}
        location = ".".join(str(part) for part in first["loc"] if part != "body")
        message = f"{location}: {first['msg']}" if location else str(first["msg"])
        return JSONResponse(_body("validation_error", message, request), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
        codes = {404: "not_found", 405: "bad_request"}
        code = codes.get(error.status_code, "bad_request")
        return JSONResponse(_body(code, str(error.detail), request), status_code=error.status_code)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, error: Exception) -> JSONResponse:
        log.exception("unhandled_error", path=request.url.path)
        # Never leak internals; the request id lets the operator find the log line.
        return JSONResponse(
            _body("internal_error", "an unexpected error occurred", request), status_code=500
        )
