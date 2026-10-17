"""Indexes and unique constraints for a tenant graph (docs/data-model.md section 9)."""

from __future__ import annotations

from mandate.errors import GraphQueryError
from mandate.graph.client import GraphClient

INDEXED_PROPERTIES: dict[str, tuple[str, ...]] = {
    "Principal": ("id",),
    "Agent": ("id",),
    "Utterance": ("id",),
    "Summary": ("id",),
    "Instruction": ("id", "status", "created_at"),
    "Scope": ("id", "action_type"),
    "Action": ("id",),
    "Decision": ("id", "at"),
    "RevokedToken": ("id",),
}
REGISTRY_PROPERTIES: dict[str, tuple[str, ...]] = {
    "Tenant": ("id",),
    "User": ("id", "email"),
    "Session": ("id", "token_hash"),
    "Webhook": ("id", "tenant_id"),
    "Delivery": ("id",),
    "AuditEvent": ("id", "tenant_id", "actor_id"),
}


def _already(error: GraphQueryError) -> bool:
    text = str(error).lower()
    return "already" in text


def ensure_schema(
    client: GraphClient,
    graph_name: str,
    properties_by_label: dict[str, tuple[str, ...]] | None = None,
) -> None:
    """Create indexes and unique ``id`` constraints. Safe to call repeatedly."""
    layout = properties_by_label or INDEXED_PROPERTIES
    for label, properties in layout.items():
        for prop in properties:
            try:
                client.run_admin_text(graph_name, f"CREATE INDEX FOR (n:{label}) ON (n.{prop})")
            except GraphQueryError as error:
                if not _already(error):
                    raise
    for label in layout:
        try:
            client.create_unique_constraint(graph_name, label, "id")
        except GraphQueryError as error:
            if not _already(error):
                raise
