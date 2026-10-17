"""Reading the audit trail: a page at a time, or as a CSV file for a spreadsheet or a SIEM.

Admins only. An admin limited to some tenants sees only the events about those tenants.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from mandate.api.keys import Caller
from mandate.api.routes.auth import directory_of
from mandate.api.security import require_caller
from mandate.errors import NotFound, ValidationFailure
from mandate.ids import is_valid_id
from mandate.models.accounts import AuditEvent
from mandate.models.api import AuditPage

router = APIRouter(prefix="/v1/audit", tags=["audit"], dependencies=[Depends(require_caller)])

EXPORT_MAX = 10_000
EXPORT_PAGE = 500
CSV_COLUMNS = (
    "id", "time_utc", "at", "actor_kind", "actor_id", "actor_name", "action", "outcome",
    "status", "method", "route", "tenant_id", "target", "request_id",
)  # fmt: skip


def _page(
    request: Request,
    *,
    tenant_id: str | None,
    actor_id: str | None,
    action: str | None,
    before: str | None,
    limit: int,
) -> list[AuditEvent]:
    caller: Caller = request.state.caller
    if tenant_id is not None and not caller.allows_tenant(tenant_id):
        raise NotFound("no such tenant")
    if before is not None and not is_valid_id(before, "aud"):
        raise ValidationFailure("before: must be an audit event id")
    return directory_of(request).list_audit(
        tenant_ids=caller.tenants,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action=action,
        before=before,
        limit=limit,
    )


@router.get("", response_model=AuditPage)
def list_events(
    request: Request,
    tenant_id: str | None = None,
    actor_id: str | None = None,
    action: str | None = None,
    before: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> AuditPage:
    events = _page(
        request,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action=action,
        before=before,
        limit=limit + 1,  # one more than asked says whether there is a next page
    )
    more = len(events) > limit
    events = events[:limit]
    return AuditPage(events=events, next=events[-1].id if more and events else None)


def _cell(value: object) -> str:
    """A spreadsheet must not run a cell as a formula (CSV injection)."""
    text = "" if value is None else str(value)
    return f"'{text}" if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@router.get("/export")
def export_events(
    request: Request,
    tenant_id: str | None = None,
    actor_id: str | None = None,
    action: str | None = None,
) -> Response:
    """Up to the newest 10,000 matching events, newest first."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    before: str | None = None
    written = 0
    while written < EXPORT_MAX:
        rows = _page(
            request,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action=action,
            before=before,
            limit=min(EXPORT_PAGE, EXPORT_MAX - written),
        )
        for e in rows:
            when = datetime.fromtimestamp(e.at / 1000, tz=UTC).isoformat(timespec="seconds")
            values = e.model_dump(mode="json") | {"time_utc": when}
            writer.writerow([_cell(values.get(column)) for column in CSV_COLUMNS])
        written += len(rows)
        if len(rows) < EXPORT_PAGE:
            break
        before = rows[-1].id
    return Response(
        buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="mandate-audit.csv"'},
    )
