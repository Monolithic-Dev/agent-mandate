"""Tenant backends and per-tenant runtimes.

The API depends on the ``TenantBackend`` protocol, not on FalkorDB, so the whole REST
surface can be tested without a database. ``FalkorTenantBackend`` is the real one.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol

from mandate.authority.ports import AuthorityStore
from mandate.authority.service import AuthorityService
from mandate.clock import Clock
from mandate.errors import NotFound
from mandate.gateway.guard import GatewayRuntime
from mandate.gateway.sandbox.state import Sandbox
from mandate.graph.client import GraphClient
from mandate.graph.directory import FalkorDirectory
from mandate.graph.store import FalkorAuthorityStore
from mandate.graph.tenants import (
    Tenant,
    create_tenant,
    drop_tenant,
    get_tenant,
    list_tenants,
)
from mandate.ids import new_id
from mandate.models.accounts import Directory
from mandate.models.domain import Principal, Role

CONTENT_PRINCIPAL_NAME = "untrusted-content"


class TenantBackend(Protocol):
    directory: Directory  # console users and the audit trail, shared by every tenant

    def create(self, tenant_id: str, name: str, now_ms: int) -> Tenant: ...

    def get(self, tenant_id: str) -> Tenant: ...

    def list(self) -> list[Tenant]: ...

    def drop(self, tenant_id: str) -> None: ...

    def store_for(self, tenant_id: str) -> AuthorityStore: ...

    def stats(self, tenant_id: str) -> dict[str, int]: ...

    def ping(self) -> bool: ...


class FalkorTenantBackend:
    def __init__(self, client: GraphClient) -> None:
        self._client = client
        self.directory: Directory = FalkorDirectory(client)

    def create(self, tenant_id: str, name: str, now_ms: int) -> Tenant:
        return create_tenant(self._client, tenant_id, name, now_ms=now_ms)

    def get(self, tenant_id: str) -> Tenant:
        return get_tenant(self._client, tenant_id)

    def list(self) -> list[Tenant]:
        return list_tenants(self._client)

    def drop(self, tenant_id: str) -> None:
        drop_tenant(self._client, tenant_id)

    def store_for(self, tenant_id: str) -> AuthorityStore:
        return FalkorAuthorityStore(self._client, get_tenant(self._client, tenant_id).graph_name)

    def stats(self, tenant_id: str) -> dict[str, int]:
        store = FalkorAuthorityStore(self._client, get_tenant(self._client, tenant_id).graph_name)
        return store.counts()

    def ping(self) -> bool:
        return self._client.ping()


@dataclass
class TenantRuntime:
    tenant: Tenant
    store: AuthorityStore
    service: AuthorityService
    gateway: GatewayRuntime

    @property
    def content_principal_id(self) -> str | None:
        return self.gateway.content_principal_id


class Runtimes:
    """Builds and caches one runtime (service, sandbox, gateway) per tenant."""

    def __init__(self, backend: TenantBackend, clock: Clock) -> None:
        self._backend = backend
        self._clock = clock
        self._cache: dict[str, TenantRuntime] = {}
        self._lock = threading.Lock()

    @property
    def backend(self) -> TenantBackend:
        return self._backend

    @property
    def clock(self) -> Clock:
        return self._clock

    def _build(self, tenant: Tenant) -> TenantRuntime:
        store = self._backend.store_for(tenant.id)
        content = next(
            (
                p
                for p in store.list_principals()
                if p.name == CONTENT_PRINCIPAL_NAME and p.role is Role.EXTERNAL
            ),
            None,
        ) or store.create_principal(
            Principal(id=new_id("prn"), name=CONTENT_PRINCIPAL_NAME, role=Role.EXTERNAL)
        )
        service = AuthorityService(store, self._clock)
        gateway = GatewayRuntime(service, Sandbox.seeded(), content_principal_id=content.id)
        return TenantRuntime(tenant, store, service, gateway)

    def create(self, tenant_id: str, name: str) -> TenantRuntime:
        tenant = self._backend.create(tenant_id, name, self._clock.now_ms())
        runtime = self._build(tenant)
        with self._lock:
            self._cache[tenant_id] = runtime
        return runtime

    def get(self, tenant_id: str) -> TenantRuntime:
        with self._lock:
            cached = self._cache.get(tenant_id)
        if cached is not None:
            return cached
        runtime = self._build(self._backend.get(tenant_id))  # raises NotFound
        with self._lock:
            return self._cache.setdefault(tenant_id, runtime)

    def drop(self, tenant_id: str) -> None:
        self._backend.drop(tenant_id)
        self._backend.directory.delete_webhooks(tenant_id=tenant_id)
        with self._lock:
            self._cache.pop(tenant_id, None)

    def reset_sandbox(self, tenant_id: str) -> None:
        runtime = self.get(tenant_id)
        runtime.gateway.sandbox = Sandbox.seeded()

    def require(self, tenant_id: str) -> TenantRuntime:
        try:
            return self.get(tenant_id)
        except NotFound:
            with self._lock:
                self._cache.pop(tenant_id, None)
            raise
