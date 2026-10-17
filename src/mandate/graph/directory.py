"""Console users and audit events in the registry graph (the ``Directory`` port).

An audit event is linked to the user who performed it and to the tenant it concerns, so the
trail is a graph too: ``(:User)-[:PERFORMED]->(:AuditEvent)-[:CONCERNS]->(:Tenant)``. A
signed-in browser is ``(:User)-[:HAS_SESSION]->(:Session)``.
"""

from __future__ import annotations

import threading
from typing import Any

from mandate.errors import Conflict, NotFound
from mandate.graph.client import GraphClient
from mandate.graph.schema import REGISTRY_PROPERTIES, ensure_schema
from mandate.graph.tenants import REGISTRY_GRAPH
from mandate.models.accounts import AuditEvent, Session, User
from mandate.models.webhooks import Delivery, Webhook


def user_from_props(props: dict[str, Any]) -> User:
    return User(
        id=props["id"],
        email=props["email"],
        name=props["name"],
        role=props["role"],
        tenants=None if props.get("all_tenants", True) else tuple(props.get("tenants") or ()),
        disabled=bool(props.get("disabled", False)),
        created_at=props["created_at"],
        updated_at=props["updated_at"],
        last_login_at=props.get("last_login_at"),
        password_hash=props["password_hash"],
    )


def user_params(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role.value,
        "all_tenants": user.tenants is None,
        "tenants": list(user.tenants or ()),
        "disabled": user.disabled,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
        "password_hash": user.password_hash,
    }


def session_from_props(props: dict[str, Any]) -> Session:
    return Session.model_validate(
        {k: v for k, v in props.items() if k in Session.model_fields and v is not None}
    )


def webhook_from_props(props: dict[str, Any]) -> Webhook:
    data = {k: v for k, v in props.items() if k in Webhook.model_fields and v is not None}
    data["events"] = tuple(data.get("events") or ())
    return Webhook.model_validate(data)


def delivery_from_props(props: dict[str, Any]) -> Delivery:
    return Delivery.model_validate(
        {k: v for k, v in props.items() if k in Delivery.model_fields and v is not None}
    )


def audit_from_props(props: dict[str, Any]) -> AuditEvent:
    fields = AuditEvent.model_fields
    return AuditEvent.model_validate({k: v for k, v in props.items() if k in fields})


class FalkorDirectory:
    def __init__(self, client: GraphClient, graph_name: str = REGISTRY_GRAPH) -> None:
        self._client = client
        self._graph = graph_name  # another name only for tests, never the real registry
        self._schema_ready = False
        self._lock = threading.Lock()

    def _write(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if not self._schema_ready:
            with self._lock:
                if not self._schema_ready:
                    ensure_schema(self._client, self._graph, REGISTRY_PROPERTIES)
                    self._schema_ready = True
        return self._client.run(self._graph, query, params)

    def _read(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return self._client.run(self._graph, query, params)

    # --- users -----------------------------------------------------------------------

    def create_user(self, user: User) -> User:
        rows = self._write("w19_create_user", user_params(user))
        if not rows or not rows[0]["created"]:
            raise Conflict("a user with this email already exists")
        return user

    def get_user(self, user_id: str) -> User:
        rows = self._read("q24_user_by_id", {"id": user_id})
        if not rows:
            raise NotFound("no such user")
        return user_from_props(rows[0]["u"])

    def find_user_by_email(self, email: str) -> User | None:
        rows = self._read("q25_user_by_email", {"email": email})
        return user_from_props(rows[0]["u"]) if rows else None

    def list_users(self) -> list[User]:
        return [user_from_props(row["u"]) for row in self._read("q26_users_list")]

    def update_user(self, user: User) -> User:
        rows = self._write("w20_update_user", user_params(user))
        if not rows:
            raise NotFound("no such user")
        return user_from_props(rows[0]["u"])

    def set_password(self, user_id: str, password_hash: str, at: int) -> User:
        rows = self._write(
            "w21_set_password", {"id": user_id, "password_hash": password_hash, "at": at}
        )
        if not rows:
            raise NotFound("no such user")
        return user_from_props(rows[0]["u"])

    def record_login(self, user_id: str, at: int) -> None:
        self._write("w22_record_login", {"id": user_id, "at": at})

    # --- sessions --------------------------------------------------------------------

    def create_session(self, session: Session, now: int) -> Session:
        self._write("w25_prune_sessions", {"user_id": session.user_id, "now": now})
        rows = self._write("w24_create_session", session.model_dump())
        if not rows:
            raise NotFound("no such user")
        return session_from_props(rows[0]["s"])

    def session_by_token(self, token_hash: str, now: int) -> tuple[User, Session] | None:
        rows = self._read("q28_session_by_token", {"token_hash": token_hash, "now": now})
        if not rows:
            return None
        return user_from_props(rows[0]["u"]), session_from_props(rows[0]["s"])

    def touch_session(self, session_id: str, at: int) -> None:
        self._write("w26_touch_session", {"id": session_id, "at": at})

    def list_sessions(self, user_id: str, now: int) -> list[Session]:
        rows = self._read("q29_user_sessions", {"user_id": user_id, "now": now})
        return [session_from_props(row["s"]) for row in rows]

    def end_session(self, user_id: str, session_id: str) -> bool:
        rows = self._write("w27_end_session", {"user_id": user_id, "id": session_id})
        return bool(rows and rows[0]["ended"])

    def end_sessions(self, user_id: str, keep: str | None = None) -> int:
        rows = self._write("w28_end_sessions", {"user_id": user_id, "keep": keep})
        return int(rows[0]["ended"]) if rows else 0

    # --- webhooks --------------------------------------------------------------------

    def create_webhook(self, webhook: Webhook) -> Webhook:
        params = webhook.model_dump(mode="json")
        params["events"] = list(params["events"])
        rows = self._write("w29_create_webhook", params)
        if not rows:
            raise NotFound("no such tenant")
        return webhook_from_props(rows[0]["w"])

    def list_webhooks(
        self, *, tenant_id: str | None = None, enabled: bool | None = None
    ) -> list[Webhook]:
        rows = self._read("q30_webhooks_list", {"tenant_id": tenant_id, "enabled": enabled})
        return [webhook_from_props(row["w"]) for row in rows]

    def get_webhook(self, webhook_id: str) -> Webhook:
        rows = self._read("q31_webhook_by_id", {"id": webhook_id})
        if not rows:
            raise NotFound("no such webhook")
        return webhook_from_props(rows[0]["w"])

    def update_webhook(self, webhook: Webhook) -> Webhook:
        rows = self._write(
            "w30_update_webhook",
            {
                "id": webhook.id,
                "name": webhook.name,
                "events": [e.value for e in webhook.events],
                "enabled": webhook.enabled,
            },
        )
        if not rows:
            raise NotFound("no such webhook")
        return webhook_from_props(rows[0]["w"])

    def record_progress(
        self, webhook_id: str, *, cursor: str, at: int | None, ok: bool | None, failures: int
    ) -> None:
        self._write(
            "w31_webhook_progress",
            {
                "id": webhook_id,
                "cursor": cursor,
                "last_delivery_at": at,
                "last_ok": ok,
                "failures": failures,
            },
        )

    def delete_webhooks(
        self, *, webhook_id: str | None = None, tenant_id: str | None = None
    ) -> int:
        params = {"id": webhook_id, "tenant_id": tenant_id}
        self._write("w32_delete_webhook_deliveries", params)
        rows = self._write("w33_delete_webhooks", params)
        return int(rows[0]["deleted"]) if rows else 0

    def record_delivery(self, delivery: Delivery, keep: int) -> None:
        self._write("w34_record_delivery", delivery.model_dump(mode="json"))
        self._write("w35_prune_deliveries", {"webhook_id": delivery.webhook_id, "keep": keep})

    def list_deliveries(self, webhook_id: str, limit: int) -> list[Delivery]:
        rows = self._read("q32_deliveries_list", {"webhook_id": webhook_id, "limit": limit})
        return [delivery_from_props(row["d"]) for row in rows]

    # --- audit -----------------------------------------------------------------------

    def record_audit(self, event: AuditEvent) -> None:
        self._write("w23_record_audit", event.model_dump(mode="json"))

    def list_audit(
        self,
        *,
        tenant_ids: frozenset[str] | None,
        tenant_id: str | None,
        actor_id: str | None,
        action: str | None,
        before: str | None,
        limit: int,
    ) -> list[AuditEvent]:
        rows = self._read(
            "q27_audit_list",
            {
                "tenant_ids": sorted(tenant_ids) if tenant_ids is not None else None,
                "tenant_id": tenant_id,
                "actor_id": actor_id,
                "action": action,
                "before": before,
                "limit": limit,
            },
        )
        return [audit_from_props(row["e"]) for row in rows]
