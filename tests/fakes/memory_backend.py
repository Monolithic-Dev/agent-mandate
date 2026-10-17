"""An in-memory ``TenantBackend`` so the REST API can be tested without a database."""

from __future__ import annotations

from fakes.memory_directory import MemoryDirectory
from fakes.memory_store import InMemoryStore
from mandate.errors import NotFound, TenantExists
from mandate.graph.tenants import Tenant, tenant_graph_name


class MemoryTenantBackend:
    def __init__(self) -> None:
        self.tenants: dict[str, Tenant] = {}
        self.stores: dict[str, InMemoryStore] = {}
        self.up = True
        self.directory = MemoryDirectory()

    def create(self, tenant_id: str, name: str, now_ms: int) -> Tenant:
        tenant_graph_name(tenant_id)
        if tenant_id in self.tenants:
            raise TenantExists(f"tenant {tenant_id!r} already exists")
        tenant = Tenant(tenant_id, name, now_ms)
        self.tenants[tenant_id] = tenant
        self.stores[tenant_id] = InMemoryStore()
        return tenant

    def get(self, tenant_id: str) -> Tenant:
        tenant_graph_name(tenant_id)
        if tenant_id not in self.tenants:
            raise NotFound("no such tenant")
        return self.tenants[tenant_id]

    def list(self) -> list[Tenant]:
        return sorted(self.tenants.values(), key=lambda t: t.id)

    def drop(self, tenant_id: str) -> None:
        self.get(tenant_id)
        del self.tenants[tenant_id]
        del self.stores[tenant_id]

    def store_for(self, tenant_id: str) -> InMemoryStore:
        self.get(tenant_id)
        return self.stores[tenant_id]

    def stats(self, tenant_id: str) -> dict[str, int]:
        store = self.store_for(tenant_id)
        counts = {
            "Principal": len(store.principals),
            "Agent": len(store.agents),
            "Utterance": len(store.utterances),
            "Instruction": len(store.rules),
            "Decision": len(store.recorded),
        }
        return {label: n for label, n in counts.items() if n}

    def ping(self) -> bool:
        return self.up
