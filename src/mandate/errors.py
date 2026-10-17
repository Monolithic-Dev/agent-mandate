"""Application errors.

Core code raises these; interfaces (REST, MCP) translate them into responses using
``code`` and ``http_status``. Codes match docs/api-spec.md section 1.
"""

from __future__ import annotations

from typing import Any


class MandateError(Exception):
    """Base class for all expected errors."""

    code: str = "internal_error"
    http_status: int = 500

    def __init__(self, message: str = "", *, details: dict[str, Any] | None = None) -> None:
        self.message = message or self.code
        self.details = details or {}
        super().__init__(self.message)

    def to_payload(self, request_id: str | None = None) -> dict[str, dict[str, Any]]:
        """Return the JSON error body defined in the API spec."""
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if request_id is not None:
            error["request_id"] = request_id
        if self.details:
            error["details"] = self.details
        return {"error": error}


class BadRequest(MandateError):
    code = "bad_request"
    http_status = 400


class Unauthorized(MandateError):
    code = "unauthorized"
    http_status = 401


class Forbidden(MandateError):
    code = "forbidden"
    http_status = 403


class NotFound(MandateError):
    code = "not_found"
    http_status = 404


class Conflict(MandateError):
    code = "conflict"
    http_status = 409


class TenantExists(Conflict):
    """A tenant with this id already exists."""


class AlreadyActive(Conflict):
    code = "already_active"


class UntrustedLineage(Conflict):
    """An instruction without a trusted origin cannot become authority."""

    code = "untrusted_lineage"


class ValidationFailure(MandateError):
    code = "validation_error"
    http_status = 422


class NotOwner(ValidationFailure):
    code = "not_owner"


class DelegationExceedsAuthority(ValidationFailure):
    code = "delegation_exceeds_authority"


class RateLimited(MandateError):
    code = "rate_limited"
    http_status = 429


class GraphUnavailable(MandateError):
    """The graph database cannot be reached. Callers must fail closed."""

    code = "graph_unavailable"
    http_status = 503


class GraphQueryError(MandateError):
    """The graph database rejected a query."""


class ConfigError(MandateError):
    code = "config_error"
