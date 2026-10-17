"""Contract tests: console users and the audit trail behave the same in memory and in FalkorDB."""

from collections.abc import Iterator

import pytest
from fakes.memory_directory import MemoryDirectory

from mandate.errors import Conflict, NotFound
from mandate.graph.client import GraphClient
from mandate.graph.directory import FalkorDirectory
from mandate.ids import new_id
from mandate.models.accounts import (
    ActorKind,
    AuditEvent,
    Directory,
    Outcome,
    Session,
    User,
    UserRole,
)
from mandate.models.webhooks import Delivery, Webhook, WebhookEvent, WebhookKind

pytestmark = pytest.mark.integration

ACME = {"id": "acme", "name": "Acme", "created_at": 1, "nonce": "n"}


@pytest.fixture(params=["memory", "falkor"])
def directory(request: pytest.FixtureRequest) -> Iterator[Directory]:
    if request.param == "memory":
        yield MemoryDirectory()
        return
    client: GraphClient = request.getfixturevalue("graph_client")
    name = f"r_test_{new_id('act')[4:].lower()}"
    client.run(name, "w14_registry_create_tenant", ACME)
    try:
        yield FalkorDirectory(client, name)
    finally:
        client.delete_graph(name)


def user(email: str, **extra: object) -> User:
    base: dict[str, object] = {
        "id": new_id("usr"),
        "email": email,
        "name": email.split("@")[0],
        "role": UserRole.VIEWER,
        "created_at": 10,
        "updated_at": 10,
        "password_hash": "scrypt$x",
    }
    return User.model_validate(base | extra)


def session(user_id: str, token_hash: str, **extra: object) -> Session:
    base: dict[str, object] = {
        "id": new_id("ses"),
        "user_id": user_id,
        "token_hash": token_hash,
        "created_at": 100,
        "expires_at": 1_000,
        "last_seen_at": 100,
    }
    return Session.model_validate(base | extra)


def event(n: int, **extra: object) -> AuditEvent:
    base: dict[str, object] = {
        "id": new_id("aud", now_ms=1_000 + n),
        "at": 1_000 + n,
        "actor_kind": ActorKind.KEY,
        "actor_id": "admin",
        "actor_name": "API key admin",
        "action": "tenant.create",
        "method": "POST",
        "route": "/v1/tenants",
        "status": 201,
        "outcome": Outcome.SUCCESS,
    }
    return AuditEvent.model_validate(base | extra)


def test_users_round_trip(directory: Directory) -> None:
    dana = directory.create_user(user("dana@example.com", role=UserRole.ADMIN))
    ops = directory.create_user(user("ops@example.com", tenants=("acme", "demo")))
    with pytest.raises(Conflict):
        directory.create_user(user("dana@example.com"))
    assert directory.get_user(dana.id) == dana
    assert directory.get_user(ops.id).tenants == ("acme", "demo")
    assert directory.find_user_by_email("ops@example.com") == ops
    assert directory.find_user_by_email("nobody@example.com") is None
    assert {u.id for u in directory.list_users()} == {dana.id, ops.id}
    with pytest.raises(NotFound):
        directory.get_user(new_id("usr"))


def test_updates_passwords_sessions_and_logins(directory: Directory) -> None:
    ops = directory.create_user(user("ops@example.com"))
    changed = ops.model_copy(
        update={"name": "Ops", "role": UserRole.OPERATOR, "tenants": None, "disabled": True,
                "updated_at": 20}
    )  # fmt: skip
    updated = directory.update_user(User.model_validate(changed.model_dump()))
    assert (updated.name, updated.role, updated.tenants, updated.disabled) == (
        "Ops",
        UserRole.OPERATOR,
        None,
        True,
    )
    assert updated.password_hash == ops.password_hash and updated.updated_at == 20
    after = directory.set_password(ops.id, "scrypt$new", 30)
    assert (after.password_hash, after.updated_at) == ("scrypt$new", 30)
    directory.record_login(ops.id, 50)
    assert directory.get_user(ops.id).last_login_at == 50
    for missing in (
        lambda: directory.set_password(new_id("usr"), "x", 1),
        lambda: directory.create_session(session(new_id("usr"), "h"), 1),
        lambda: directory.update_user(user("ghost@example.com")),
    ):
        with pytest.raises(NotFound):
            missing()


def test_sessions_live_expire_and_end(directory: Directory) -> None:
    dana = directory.create_user(user("dana@example.com"))
    ops = directory.create_user(user("ops@example.com"))
    laptop = directory.create_session(session(dana.id, "h1", user_agent="Firefox"), now=100)
    phone = directory.create_session(session(dana.id, "h2", last_seen_at=150), now=100)
    theirs = directory.create_session(session(ops.id, "h3"), now=100)
    assert laptop.user_agent == "Firefox" and phone.user_agent is None

    found = directory.session_by_token("h1", now=500)
    assert found is not None and found[0].id == dana.id and found[1] == laptop
    assert directory.session_by_token("h1", now=1_000) is None  # expired
    assert directory.session_by_token("nope", now=500) is None

    assert [s.id for s in directory.list_sessions(dana.id, now=500)] == [phone.id, laptop.id]
    directory.touch_session(laptop.id, 600)
    assert [s.id for s in directory.list_sessions(dana.id, now=700)] == [laptop.id, phone.id]

    assert directory.end_session(ops.id, laptop.id) is False  # not theirs
    assert directory.end_session(dana.id, phone.id) is True
    assert directory.end_session(dana.id, phone.id) is False
    assert directory.end_sessions(dana.id, keep=laptop.id) == 0
    assert directory.end_sessions(dana.id) == 1
    assert directory.list_sessions(dana.id, now=500) == []
    left = directory.session_by_token("h3", now=500)
    assert left is not None and left[1] == theirs  # someone else's is untouched

    # A new session clears out the user's expired ones.
    directory.create_session(session(ops.id, "h4", expires_at=5_000), now=2_000)
    assert directory.session_by_token("h3", now=999) is None
    assert [s.token_hash for s in directory.list_sessions(ops.id, now=2_000)] == ["h4"]


def test_the_audit_trail_filters_and_pages(directory: Directory) -> None:
    dana = directory.create_user(user("dana@example.com"))
    events = [
        event(1, tenant_id="acme", target="acme"),
        event(
            2,
            actor_kind=ActorKind.USER,
            actor_id=dana.id,
            actor_name="dana",
            action="rule.confirm",
            tenant_id="acme",
            target=new_id("ins"),
        ),  # fmt: skip
        event(3, tenant_id="globex", action="tenant.delete"),
        event(
            4,
            actor_kind=ActorKind.ANONYMOUS,
            actor_id=None,
            actor_name="x@example.com",
            action="auth.login",
            outcome=Outcome.DENIED,
            status=401,
        ),  # fmt: skip
    ]
    for e in events:
        directory.record_audit(e)

    def ids(**kw: object) -> list[str]:
        query = {"tenant_ids": None, "tenant_id": None, "actor_id": None, "action": None,
                 "before": None, "limit": 50} | kw  # fmt: skip
        return [e.id for e in directory.list_audit(**query)]  # type: ignore[arg-type]

    newest_first = [e.id for e in reversed(events)]
    assert ids() == newest_first
    assert directory.list_audit(tenant_ids=None, tenant_id=None, actor_id=None, action=None,
                                before=None, limit=50) == list(reversed(events))  # fmt: skip
    assert ids(limit=2) == newest_first[:2]
    assert ids(before=events[2].id) == [events[1].id, events[0].id]
    assert ids(tenant_id="acme") == [events[1].id, events[0].id]
    assert ids(tenant_ids=frozenset({"acme"})) == [events[1].id, events[0].id]
    assert ids(tenant_ids=frozenset()) == []
    assert ids(actor_id=dana.id) == [events[1].id]
    assert ids(action="auth.login") == [events[3].id]


def test_in_falkordb_the_trail_is_linked_to_users_and_tenants(graph_client: GraphClient) -> None:
    name = f"r_test_{new_id('act')[4:].lower()}"
    graph_client.run(name, "w14_registry_create_tenant", ACME)
    try:
        directory = FalkorDirectory(graph_client, name)
        dana = directory.create_user(user("dana@example.com"))
        directory.record_audit(event(1, actor_kind=ActorKind.USER, actor_id=dana.id,
                                     tenant_id="acme"))  # fmt: skip
        directory.record_audit(event(2, tenant_id="nowhere"))  # neither a user nor a tenant
        rows = graph_client.run_admin_text(
            name,
            "MATCH (u:User)-[:PERFORMED]->(e:AuditEvent)-[:CONCERNS]->(t:Tenant) "
            "RETURN u.email AS email, t.id AS tenant, count(e) AS n",
        )
        assert rows == [{"email": "dana@example.com", "tenant": "acme", "n": 1}]
        loose = graph_client.run_admin_text(
            name, "MATCH (e:AuditEvent) WHERE NOT (e)--() RETURN count(e) AS n"
        )
        assert loose == [{"n": 1}]
    finally:
        graph_client.delete_graph(name)


# --- webhooks --------------------------------------------------------------------------


def webhook(tenant_id: str = "acme", **extra: object) -> Webhook:
    base: dict[str, object] = {
        "id": new_id("whk"),
        "tenant_id": tenant_id,
        "name": "Ops",
        "url": "https://93.184.216.34/hook",
        "kind": WebhookKind.JSON,
        "secret": "whsec_x",
        "created_at": 10,
    }
    return Webhook.model_validate(base | extra)


def delivery(webhook_id: str, at: int, **extra: object) -> Delivery:
    base: dict[str, object] = {
        "id": new_id("dlv", now_ms=at),
        "webhook_id": webhook_id,
        "event": WebhookEvent.APPROVAL_REQUESTED,
        "at": at,
        "ok": True,
        "attempts": 1,
        "status": 200,
        "duration_ms": 12.5,
    }
    return Delivery.model_validate(base | extra)


def test_webhooks_round_trip_and_their_deliveries_are_capped(directory: Directory) -> None:
    hook = directory.create_webhook(webhook(events=(WebhookEvent.APPROVAL_REQUESTED,)))
    off = directory.create_webhook(webhook(name="Off", enabled=False, created_at=20))
    assert directory.get_webhook(hook.id) == hook
    assert [w.id for w in directory.list_webhooks(tenant_id="acme")] == [hook.id, off.id]
    assert [w.id for w in directory.list_webhooks(enabled=True)] == [hook.id]
    assert directory.list_webhooks(tenant_id="other") == []

    renamed = directory.update_webhook(hook.model_copy(update={"name": "Pager", "enabled": False}))
    assert (renamed.name, renamed.enabled, renamed.url) == ("Pager", False, hook.url)
    directory.record_progress(hook.id, cursor="5|act_a", at=99, ok=False, failures=2)
    progressed = directory.get_webhook(hook.id)
    assert (progressed.cursor, progressed.last_delivery_at, progressed.last_ok) == (
        "5|act_a",
        99,
        False,
    )
    assert progressed.failures == 2

    for at in range(1, 6):
        failed = {"ok": False, "status": None, "error": "ConnectError"} if at == 3 else {}
        directory.record_delivery(delivery(hook.id, at, **failed), keep=3)
    kept = directory.list_deliveries(hook.id, limit=10)
    assert [d.at for d in kept] == [5, 4, 3]
    assert kept[2].status is None and kept[2].error == "ConnectError"
    assert [d.at for d in directory.list_deliveries(hook.id, limit=2)] == [5, 4]


def test_webhooks_are_deleted_one_by_one_or_by_tenant(directory: Directory) -> None:
    first, second = directory.create_webhook(webhook()), directory.create_webhook(webhook())
    directory.record_delivery(delivery(first.id, 1), keep=10)
    assert directory.delete_webhooks(webhook_id=first.id) == 1
    assert directory.list_deliveries(first.id, limit=10) == []
    with pytest.raises(NotFound):
        directory.get_webhook(first.id)
    assert directory.delete_webhooks(tenant_id="acme") == 1
    assert directory.list_webhooks() == [] and second.id
