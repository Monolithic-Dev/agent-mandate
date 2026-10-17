"""An in-memory ``Directory``, held to the graph's behaviour by tests/integration contract tests."""

from __future__ import annotations

from mandate.errors import Conflict, NotFound
from mandate.models.accounts import AuditEvent, Session, User
from mandate.models.webhooks import Delivery, Webhook


class MemoryDirectory:
    def __init__(self) -> None:
        self.users: dict[str, User] = {}
        self.events: list[AuditEvent] = []
        self.sessions: dict[str, Session] = {}
        self.webhooks: dict[str, Webhook] = {}
        self.deliveries: list[Delivery] = []
        self.tenant_ids: set[str] | None = None  # None: every tenant exists

    def create_user(self, user: User) -> User:
        if any(u.email == user.email for u in self.users.values()):
            raise Conflict("a user with this email already exists")
        self.users[user.id] = user
        return user

    def get_user(self, user_id: str) -> User:
        if user_id not in self.users:
            raise NotFound("no such user")
        return self.users[user_id]

    def find_user_by_email(self, email: str) -> User | None:
        return next((u for u in self.users.values() if u.email == email), None)

    def list_users(self) -> list[User]:
        return sorted(self.users.values(), key=lambda u: (u.created_at, u.id))

    def update_user(self, user: User) -> User:
        current = self.get_user(user.id)
        updated = current.model_copy(
            update={
                "name": user.name,
                "role": user.role,
                "tenants": user.tenants,
                "disabled": user.disabled,
                "updated_at": user.updated_at,
            }
        )
        self.users[user.id] = updated
        return updated

    def set_password(self, user_id: str, password_hash: str, at: int) -> User:
        current = self.get_user(user_id)
        updated = current.model_copy(update={"password_hash": password_hash, "updated_at": at})
        self.users[user_id] = updated
        return updated

    def create_session(self, session: Session, now: int) -> Session:
        self.get_user(session.user_id)
        for sid, s in list(self.sessions.items()):
            if s.user_id == session.user_id and s.expires_at <= now:
                del self.sessions[sid]
        self.sessions[session.id] = session
        return session

    def session_by_token(self, token_hash: str, now: int) -> tuple[User, Session] | None:
        for s in self.sessions.values():
            if s.token_hash == token_hash and s.expires_at > now:
                return self.users[s.user_id], s
        return None

    def touch_session(self, session_id: str, at: int) -> None:
        if session_id in self.sessions:
            current = self.sessions[session_id]
            self.sessions[session_id] = current.model_copy(update={"last_seen_at": at})

    def list_sessions(self, user_id: str, now: int) -> list[Session]:
        live = [s for s in self.sessions.values() if s.user_id == user_id and s.expires_at > now]
        return sorted(live, key=lambda s: (s.last_seen_at, s.id), reverse=True)

    def end_session(self, user_id: str, session_id: str) -> bool:
        session = self.sessions.get(session_id)
        if session is None or session.user_id != user_id:
            return False
        del self.sessions[session_id]
        return True

    def end_sessions(self, user_id: str, keep: str | None = None) -> int:
        ended = [sid for sid, s in self.sessions.items() if s.user_id == user_id and sid != keep]
        for sid in ended:
            del self.sessions[sid]
        return len(ended)

    def record_login(self, user_id: str, at: int) -> None:
        if user_id in self.users:
            self.users[user_id] = self.users[user_id].model_copy(update={"last_login_at": at})

    def record_audit(self, event: AuditEvent) -> None:
        self.events.append(event)

    def create_webhook(self, webhook: Webhook) -> Webhook:
        if self.tenant_ids is not None and webhook.tenant_id not in self.tenant_ids:
            raise NotFound("no such tenant")
        self.webhooks[webhook.id] = webhook
        return webhook

    def list_webhooks(
        self, *, tenant_id: str | None = None, enabled: bool | None = None
    ) -> list[Webhook]:
        rows = [
            w
            for w in self.webhooks.values()
            if (tenant_id is None or w.tenant_id == tenant_id)
            and (enabled is None or w.enabled == enabled)
        ]
        return sorted(rows, key=lambda w: (w.created_at, w.id))

    def get_webhook(self, webhook_id: str) -> Webhook:
        if webhook_id not in self.webhooks:
            raise NotFound("no such webhook")
        return self.webhooks[webhook_id]

    def update_webhook(self, webhook: Webhook) -> Webhook:
        current = self.get_webhook(webhook.id)
        updated = current.model_copy(
            update={"name": webhook.name, "events": webhook.events, "enabled": webhook.enabled}
        )
        self.webhooks[webhook.id] = updated
        return updated

    def record_progress(
        self, webhook_id: str, *, cursor: str, at: int | None, ok: bool | None, failures: int
    ) -> None:
        if webhook_id in self.webhooks:
            self.webhooks[webhook_id] = self.webhooks[webhook_id].model_copy(
                update={
                    "cursor": cursor,
                    "last_delivery_at": at,
                    "last_ok": ok,
                    "failures": failures,
                }
            )

    def delete_webhooks(
        self, *, webhook_id: str | None = None, tenant_id: str | None = None
    ) -> int:
        doomed = {
            w.id
            for w in self.webhooks.values()
            if (webhook_id is not None and w.id == webhook_id)
            or (tenant_id is not None and w.tenant_id == tenant_id)
        }
        for wid in doomed:
            del self.webhooks[wid]
        self.deliveries = [d for d in self.deliveries if d.webhook_id not in doomed]
        return len(doomed)

    def record_delivery(self, delivery: Delivery, keep: int) -> None:
        self.deliveries.append(delivery)
        mine = sorted(
            (d for d in self.deliveries if d.webhook_id == delivery.webhook_id),
            key=lambda d: (d.at, d.id),
            reverse=True,
        )
        dropped = {d.id for d in mine[keep:]}
        self.deliveries = [d for d in self.deliveries if d.id not in dropped]

    def list_deliveries(self, webhook_id: str, limit: int) -> list[Delivery]:
        mine = [d for d in self.deliveries if d.webhook_id == webhook_id]
        return sorted(mine, key=lambda d: (d.at, d.id), reverse=True)[:limit]

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
        rows = [
            e
            for e in self.events
            if (tenant_ids is None or e.tenant_id in tenant_ids)
            and (tenant_id is None or e.tenant_id == tenant_id)
            and (actor_id is None or e.actor_id == actor_id)
            and (action is None or e.action == action)
            and (before is None or e.id < before)
        ]
        return sorted(rows, key=lambda e: e.id, reverse=True)[:limit]
