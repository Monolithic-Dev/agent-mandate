from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from mandate.api.audit import note_created
from mandate.api.keys import Caller
from mandate.api.security import require_caller
from mandate.api.tenancy import Runtimes
from mandate.models.api import CreateTenant, TenantOut

router = APIRouter(prefix="/v1/tenants", tags=["tenants"], dependencies=[Depends(require_caller)])


def runtimes_of(request: Request) -> Runtimes:
    runtimes: Runtimes = request.app.state.runtimes
    return runtimes


@router.post("", status_code=201, response_model=TenantOut)
def create_tenant(body: CreateTenant, request: Request) -> TenantOut:
    runtime = runtimes_of(request).create(body.tenant_id, body.name)
    tenant = runtime.tenant
    note_created(request, tenant.id, tenant_id=tenant.id)
    return TenantOut(
        tenant_id=tenant.id,
        name=tenant.name,
        graph=tenant.graph_name,
        created_at=tenant.created_at,
        content_principal_id=runtime.content_principal_id,
    )


@router.get("", response_model=list[TenantOut])
def list_tenants(request: Request) -> list[TenantOut]:
    caller: Caller = request.state.caller
    return [
        TenantOut(tenant_id=t.id, name=t.name, graph=t.graph_name, created_at=t.created_at)
        for t in runtimes_of(request).backend.list()
        if caller.allows_tenant(t.id)  # a scoped caller only ever sees its own tenants
    ]


@router.delete("/{tenant_id}", status_code=204)
def delete_tenant(tenant_id: str, request: Request) -> Response:
    runtimes_of(request).drop(tenant_id)
    return Response(status_code=204)


@router.get("/{tenant_id}/stats")
def tenant_stats(tenant_id: str, request: Request) -> dict[str, int]:
    runtimes = runtimes_of(request)
    runtimes.require(tenant_id)
    return runtimes.backend.stats(tenant_id)
