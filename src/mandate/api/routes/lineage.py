"""Blast radius, quarantine and replay for an instruction."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Request

from mandate.api.routes.authority import runtime_for
from mandate.api.security import require_caller
from mandate.lineage.blast_radius import blast_radius, quarantine
from mandate.lineage.reliance import rank_reliance
from mandate.lineage.replay import replay_without
from mandate.models.api import (
    BlastRadiusOut,
    ByPrincipal,
    QuarantineOut,
    RelianceOut,
    ReplayOut,
)
from mandate.models.domain import PrincipalId

router = APIRouter(
    prefix="/v1/tenants/{tenant_id}/instructions/{instruction_id}",
    tags=["lineage"],
    dependencies=[Depends(require_caller)],
)


@router.get("/blast-radius", response_model=BlastRadiusOut)
def get_blast_radius(tenant_id: str, instruction_id: str, request: Request) -> BlastRadiusOut:
    runtime = runtime_for(tenant_id, request)
    radius = blast_radius(runtime.store, instruction_id)
    return BlastRadiusOut.model_validate(asdict(radius))


@router.post("/quarantine", response_model=QuarantineOut)
def quarantine_instruction(
    tenant_id: str, instruction_id: str, body: ByPrincipal, request: Request
) -> QuarantineOut:
    runtime = runtime_for(tenant_id, request)
    runtime.service.require_owner(body.by)
    now = request.app.state.runtimes.clock.now_ms()
    ids = quarantine(runtime.store, instruction_id, at=now, by=body.by)
    return QuarantineOut(instruction_ids=ids, quarantined=True)


@router.delete("/quarantine", response_model=QuarantineOut)
def release_instruction(
    tenant_id: str, instruction_id: str, by: PrincipalId, request: Request
) -> QuarantineOut:
    runtime = runtime_for(tenant_id, request)
    runtime.service.require_owner(by)
    now = request.app.state.runtimes.clock.now_ms()
    ids = quarantine(runtime.store, instruction_id, value=False, at=now, by=by)
    return QuarantineOut(instruction_ids=ids, quarantined=False)


@router.post("/replay", response_model=ReplayOut)
def replay(tenant_id: str, instruction_id: str, request: Request) -> ReplayOut:
    runtime = runtime_for(tenant_id, request)
    result = replay_without(runtime.store, request.app.state.runtimes.clock, instruction_id)
    return ReplayOut.model_validate(asdict(result))


tenant_router = APIRouter(
    prefix="/v1/tenants/{tenant_id}", tags=["lineage"], dependencies=[Depends(require_caller)]
)


@tenant_router.get("/reliance", response_model=list[RelianceOut])
def reliance(tenant_id: str, request: Request, limit: int = 20) -> list[RelianceOut]:
    """The rules recorded decisions leaned on most, with review flags."""
    runtime = runtime_for(tenant_id, request)
    rows = rank_reliance(runtime.store, max(1, min(limit, 100)))
    return [
        RelianceOut(**{**asdict(row), "flags": list(row.flags), "needs_review": row.needs_review})
        for row in rows
    ]
