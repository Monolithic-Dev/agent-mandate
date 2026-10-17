"""Tenants: one FalkorDB graph per tenant, plus a small registry graph."""

from __future__ import annotations

import re
from dataclasses import dataclass

from mandate.errors import NotFound, TenantExists, ValidationFailure
from mandate.graph.client import GraphClient
from mandate.graph.schema import REGISTRY_PROPERTIES, ensure_schema
from mandate.ids import new_id

REGISTRY_GRAPH = "mandate_registry"
# No "__": a tenant graph must never contain REPLAY_MARKER, or sweep_replay_graphs would
# treat it as a leftover replay clone and delete it.
TENANT_ID_RE = re.compile(r"^(?!.*__)[a-z0-9_]{1,40}$")
REPLAY_MARKER = "__replay_"


@dataclass(frozen=True)
class Tenant:
    id: str
    name: str
    created_at: int

    @property
    def graph_name(self) -> str:
        return tenant_graph_name(self.id)


def tenant_graph_name(tenant_id: str) -> str:
    """The graph name for a tenant. Raises ``ValidationFailure`` for malformed ids."""
    if not TENANT_ID_RE.match(tenant_id):
        raise ValidationFailure("tenant id must be 1 to 40 characters of a-z, 0-9 and single _")
    return f"t_{tenant_id}"


def replay_graph_name(tenant_id: str, run_id: str) -> str:
    """Name of a temporary clone used for replay; always deleted after use."""
    suffix = re.sub(r"[^a-z0-9]", "", run_id.lower())[:30] or "run"
    return f"{tenant_graph_name(tenant_id)}{REPLAY_MARKER}{suffix}"


def create_tenant(client: GraphClient, tenant_id: str, name: str, *, now_ms: int) -> Tenant:
    graph = tenant_graph_name(tenant_id)
    if not name.strip() or len(name) > 80:
        raise ValidationFailure("tenant name must be 1 to 80 characters")
    ensure_schema(client, REGISTRY_GRAPH, REGISTRY_PROPERTIES)
    rows = client.run(
        REGISTRY_GRAPH,
        "w14_registry_create_tenant",
        {"id": tenant_id, "name": name.strip(), "created_at": now_ms, "nonce": new_id("act")},
    )
    if not rows or not rows[0]["created"]:
        raise TenantExists(f"tenant {tenant_id!r} already exists")
    ensure_schema(client, graph)
    return Tenant(tenant_id, name.strip(), now_ms)


def get_tenant(client: GraphClient, tenant_id: str) -> Tenant:
    tenant_graph_name(tenant_id)
    rows = client.run(REGISTRY_GRAPH, "q11_registry_get_tenant", {"id": tenant_id})
    if not rows:
        raise NotFound("no such tenant")
    row = rows[0]
    return Tenant(row["id"], row["name"], row["created_at"])


def list_tenants(client: GraphClient) -> list[Tenant]:
    if REGISTRY_GRAPH not in client.list_graphs():
        return []
    rows = client.run(REGISTRY_GRAPH, "q12_registry_list_tenants")
    return [Tenant(r["id"], r["name"], r["created_at"]) for r in rows]


def drop_tenant(client: GraphClient, tenant_id: str) -> None:
    """Delete a tenant's graph and registry entry. Unknown tenants raise ``NotFound``."""
    graph = tenant_graph_name(tenant_id)
    rows = client.run(REGISTRY_GRAPH, "w15_registry_delete_tenant", {"id": tenant_id})
    if not rows or rows[0]["deleted"] == 0:
        raise NotFound("no such tenant")
    client.delete_graph(graph)


def sweep_replay_graphs(client: GraphClient) -> list[str]:
    """Delete leftover replay clones (for example after a crash). Returns their names."""
    leftovers = [name for name in client.list_graphs() if REPLAY_MARKER in name]
    for name in leftovers:
        client.delete_graph(name)
    return leftovers
