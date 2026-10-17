import pytest

from mandate import errors


def test_payload_shape() -> None:
    payload = errors.NotFound("no such tenant").to_payload("req_1")
    assert payload == {
        "error": {"code": "not_found", "message": "no such tenant", "request_id": "req_1"}
    }


def test_default_message_is_code() -> None:
    assert errors.Conflict().message == "conflict"


def test_details_included_when_present() -> None:
    payload = errors.ValidationFailure("bad", details={"field": "effect"}).to_payload()
    assert payload["error"]["details"] == {"field": "effect"}
    assert "request_id" not in payload["error"]


@pytest.mark.parametrize(
    ("error", "code", "status"),
    [
        (errors.BadRequest, "bad_request", 400),
        (errors.Unauthorized, "unauthorized", 401),
        (errors.NotFound, "not_found", 404),
        (errors.Conflict, "conflict", 409),
        (errors.TenantExists, "conflict", 409),
        (errors.AlreadyActive, "already_active", 409),
        (errors.UntrustedLineage, "untrusted_lineage", 409),
        (errors.ValidationFailure, "validation_error", 422),
        (errors.NotOwner, "not_owner", 422),
        (errors.DelegationExceedsAuthority, "delegation_exceeds_authority", 422),
        (errors.RateLimited, "rate_limited", 429),
        (errors.GraphUnavailable, "graph_unavailable", 503),
        (errors.GraphQueryError, "internal_error", 500),
    ],
)
def test_codes_and_statuses_match_api_spec(
    error: type[errors.MandateError], code: str, status: int
) -> None:
    instance = error()
    assert instance.code == code
    assert instance.http_status == status
    assert isinstance(instance, errors.MandateError)
