"""The audit trail: what is recorded, who it names, and who may read it."""

import csv
import io
from typing import Any

import pytest
from fakes.memory_backend import MemoryTenantBackend
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mandate.api import sessions
from mandate.api.app import create_app
from mandate.api.audit import ACTIONS, action_name
from mandate.clock import FixedClock
from mandate.config import Settings
from mandate.models.accounts import AuditEvent

KEY = "k" * 24
READER = "r" * 24
SCOPED = "s" * 24
H = {"X-Mandate-Key": KEY}
CONSOLE = {"X-Mandate-Client": "console"}
PASSWORD = "correct horse battery"
S1 = "You may read and archive my email, but confirm with me before deleting anything."


@pytest.fixture(autouse=True)
def cheap_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sessions, "SCRYPT_N", 2**10)


class Setup:
    def __init__(self) -> None:
        settings = Settings(  # type: ignore[call-arg]
            mandate_api_key=KEY,
            mandate_api_keys=f"reader:{READER}:viewer:*;acmeadmin:{SCOPED}:admin:acme",
            mandate_cookie_secure=False,
            _env_file=None,
        )
        self.backend = MemoryTenantBackend()
        self.app: FastAPI = create_app(settings, self.backend, FixedClock())
        self.c = TestClient(self.app, raise_server_exceptions=False)

    @property
    def events(self) -> list[AuditEvent]:
        return self.backend.directory.events  # type: ignore[attr-defined,no-any-return]

    def actions(self) -> list[str]:
        return [e.action for e in self.events]

    def post(self, path: str, body: dict[str, Any] | None = None, key: str = KEY) -> Any:
        return self.c.post(path, json=body or {}, headers={"X-Mandate-Key": key})

    def tenant(self, tenant_id: str = "acme") -> dict[str, str]:
        assert self.post("/v1/tenants", {"tenant_id": tenant_id, "name": "x"}).status_code == 201
        base = f"/v1/tenants/{tenant_id}"
        owner = self.post(f"{base}/principals", {"name": "Dana", "role": "owner"}).json()["id"]
        agent = self.post(f"{base}/agents", {"name": "main", "kind": "primary"}).json()["id"]
        return {"base": base, "owner": owner, "agent": agent}


def test_changes_are_recorded_with_who_what_and_how_it_ended() -> None:
    s = Setup()
    t = s.tenant()
    said = s.post(
        f"{t['base']}/utterances",
        {"principal_id": t["owner"], "text": S1, "channel": "owner_direct"},
    ).json()
    rule = next(i["instruction"]["id"] for i in said["instructions"] if i["needs_confirmation"])
    assert s.post(f"{t['base']}/instructions/{rule}/confirm", {"by": t["owner"]}).is_success
    assert s.post(f"{t['base']}/instructions/{rule}/confirm", {"by": t["owner"]}).status_code == 409

    assert s.actions() == [
        "tenant.create",
        "principal.create",
        "agent.create",
        "owner.say",
        "rule.confirm",
        "rule.confirm",
    ]
    ok, conflict = s.events[-2], s.events[-1]
    assert (ok.actor_kind, ok.actor_id, ok.actor_name) == ("key", "admin", "API key admin")
    assert ok.tenant_id == "acme" and ok.target == rule and ok.outcome == "success"
    assert ok.route == "/v1/tenants/{tenant_id}/instructions/{instruction_id}/confirm"
    assert ok.request_id and ok.request_id.startswith("req_")
    assert (conflict.status, conflict.outcome) == (409, "failed")


def test_reads_tool_calls_and_anonymous_requests_are_not_recorded() -> None:
    s = Setup()
    t = s.tenant()
    before = len(s.events)
    s.c.get("/v1/tenants", headers=H)
    s.post(f"{t['base']}/tool-calls", {"agent_id": t["agent"], "tool": "email_read", "args": {}})
    s.post(f"{t['base']}/check", {"agent_id": t["agent"], "action": "email.read", "resource": "x"})
    s.c.post("/v1/tenants", json={"tenant_id": "zz", "name": "x"})  # no key at all
    s.c.post("/v1/tenants", json={"tenant_id": "zz", "name": "x"}, headers={"X-Mandate-Key": "x"})
    assert len(s.events) == before


def test_a_refusal_is_recorded_as_denied() -> None:
    s = Setup()
    s.tenant()
    refused = s.post("/v1/tenants", {"tenant_id": "other", "name": "x"}, key=READER)
    assert refused.status_code == 403
    last = s.events[-1]
    assert (last.action, last.actor_id, last.outcome, last.status) == (
        "tenant.create",
        "reader",
        "denied",
        403,
    )


def test_sign_ins_are_recorded_whether_or_not_they_succeed() -> None:
    s = Setup()
    made = s.post(
        "/v1/users",
        {"email": "dana@example.com", "name": "Dana", "role": "admin", "password": PASSWORD},
    ).json()
    for password in ("wrong password", PASSWORD):
        s.c.post(
            "/v1/auth/login",
            json={"email": "dana@example.com", "password": password},
            headers=CONSOLE,
        )
    s.c.post("/v1/auth/logout", headers=CONSOLE)
    create, failed, success, logout = s.events[-4:]
    assert create.action == "user.create" and create.target == made["id"]
    assert (failed.action, failed.actor_kind, failed.actor_name, failed.outcome) == (
        "auth.login",
        "anonymous",
        "dana@example.com",
        "denied",
    )
    assert (success.actor_kind, success.actor_id, success.outcome) == (
        "user",
        made["id"],
        "success",
    )
    assert (logout.action, logout.actor_id) == ("auth.logout", made["id"])


def test_an_approval_link_is_recorded_as_the_owner_who_used_it() -> None:
    s = Setup()
    t = s.tenant()
    said = s.post(
        f"{t['base']}/utterances",
        {"principal_id": t["owner"], "text": S1, "channel": "owner_direct"},
    ).json()
    for item in said["instructions"]:
        if item["needs_confirmation"]:
            rule = item["instruction"]["id"]
            s.post(f"{t['base']}/instructions/{rule}/confirm", {"by": t["owner"]})
    held = s.post(
        f"{t['base']}/tool-calls",
        {"agent_id": t["agent"], "tool": "email_delete", "args": {"message_id": "m-1"}},
    ).json()
    link = s.post(f"{t['base']}/actions/{held['approval_id']}/approval-link", {"by": t["owner"]})
    token = link.json()["token"]
    s.c.post("/v1/approval-links/inspect", json={"token": token})
    s.c.post("/v1/approval-links/resolve", json={"token": token, "approved": True})
    used = s.events[-1]
    assert s.actions()[-2:] == ["approval_link.create", "action.resolve_by_link"]
    assert (used.actor_kind, used.actor_id, used.actor_name) == ("link", t["owner"], "Dana")
    assert (used.tenant_id, used.target) == ("acme", held["approval_id"])


def test_the_trail_pages_newest_first_and_filters() -> None:
    s = Setup()
    for n in range(5):
        s.tenant(f"t{n}")
    first = s.c.get("/v1/audit?limit=4", headers=H).json()
    assert len(first["events"]) == 4 and first["next"] == first["events"][-1]["id"]
    ids = [e["id"] for e in first["events"]]
    assert ids == sorted(ids, reverse=True)
    rest = s.c.get(f"/v1/audit?limit=200&before={first['next']}", headers=H).json()
    assert rest["next"] is None and len(first["events"]) + len(rest["events"]) == len(s.events)
    only = s.c.get("/v1/audit?tenant_id=t2&action=agent.create", headers=H).json()["events"]
    assert [(e["tenant_id"], e["action"]) for e in only] == [("t2", "agent.create")]
    assert s.c.get("/v1/audit?before=nonsense", headers=H).status_code == 422


def test_an_admin_of_some_tenants_reads_only_their_events() -> None:
    s = Setup()
    s.tenant("acme")
    s.tenant("globex")
    seen = s.c.get("/v1/audit?limit=200", headers={"X-Mandate-Key": SCOPED}).json()["events"]
    assert seen and {e["tenant_id"] for e in seen} == {"acme"}
    other = s.c.get("/v1/audit?tenant_id=globex", headers={"X-Mandate-Key": SCOPED})
    assert other.status_code == 404
    assert s.c.get("/v1/audit", headers={"X-Mandate-Key": READER}).status_code == 403


def test_the_export_is_csv_and_cannot_run_formulas() -> None:
    s = Setup()
    s.tenant()
    s.post("/v1/users", {"email": "x@example.com", "name": "=HYPERLINK(1)", "role": "viewer",
                         "password": PASSWORD})  # fmt: skip
    s.c.post(
        "/v1/auth/login",
        json={"email": "x@example.com", "password": PASSWORD},
        headers=CONSOLE,
    )
    exported = s.c.get("/v1/audit/export", headers=H)
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(exported.text)))
    assert len(rows) == len(s.events)
    assert rows[0]["actor_name"] == "'=HYPERLINK(1)" and rows[0]["time_utc"].endswith("+00:00")


def test_every_mutating_route_has_an_action_name() -> None:
    s = Setup()
    unnamed = []
    for route in s.app.routes:
        methods = getattr(route, "methods", set()) - {"GET", "HEAD", "OPTIONS"}
        path = getattr(route, "path", "")
        for method in methods:
            name = action_name(method, path)
            if " " in name and not path.endswith(("/tool-calls", "/check", "/inspect", "/preview")):
                unnamed.append((method, path))
    assert unnamed == []
    assert len(set(ACTIONS.values())) == len(ACTIONS)
