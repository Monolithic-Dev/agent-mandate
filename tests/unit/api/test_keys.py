"""Scoped API keys: roles, tenant allow-lists, and the table that decides who may do what."""

from typing import Any

import pytest
from fakes.memory_backend import MemoryTenantBackend
from fastapi.testclient import TestClient

from mandate.api.app import create_app
from mandate.api.keys import ApiKey, Role, build_keyring, find_key, required_role
from mandate.clock import FixedClock
from mandate.config import Settings
from mandate.errors import ConfigError

ADMIN = "a" * 24
READER = "r" * 24
RUNNER = "o" * 24
ACME_ADMIN = "c" * 24
EXTRA = (
    f"reader:{READER}:viewer:acme;runner:{RUNNER}:operator:acme,globex;"
    f"acmeadmin:{ACME_ADMIN}:admin:acme"
)


def client(**overrides: Any) -> TestClient:
    settings = Settings(mandate_api_key=ADMIN, mandate_api_keys=EXTRA, _env_file=None, **overrides)  # type: ignore[call-arg,arg-type]
    app = create_app(settings, MemoryTenantBackend(), FixedClock())
    return TestClient(app, raise_server_exceptions=False)


def h(secret: str) -> dict[str, str]:
    return {"X-Mandate-Key": secret}


# --- parsing and the table -----------------------------------------------------------


def test_keyring_always_has_the_admin_key() -> None:
    ring = build_keyring(ADMIN, None)
    assert [(k.id, k.role, k.all_tenants) for k in ring] == [("admin", Role.ADMIN, True)]


def test_keyring_parses_scoped_keys() -> None:
    ring = {k.id: k for k in build_keyring(ADMIN, EXTRA)}
    assert ring["reader"].role is Role.VIEWER and ring["reader"].tenants == frozenset({"acme"})
    assert ring["runner"].tenants == frozenset({"acme", "globex"})
    assert ring["acmeadmin"].allows_tenant("acme") and not ring["acmeadmin"].allows_tenant("x")


@pytest.mark.parametrize(
    "spec",
    [
        "onlytwo:parts",
        f"x:{READER}:boss:acme",  # unknown role
        "x:short:viewer:acme",  # secret too short
        f":{READER}:viewer:acme",  # no id
        f"x:{READER}:viewer:,",  # empty tenant list
        f"admin:{READER}:viewer:acme",  # duplicate id
        f"x:{ADMIN}:viewer:acme",  # duplicate secret
    ],
)
def test_bad_key_specs_are_rejected(spec: str) -> None:
    with pytest.raises(ConfigError):
        build_keyring(ADMIN, spec)


def test_find_key_matches_exactly() -> None:
    ring = build_keyring(ADMIN, EXTRA)
    found = find_key(READER, ring)
    assert found is not None and found.id == "reader"
    for bad in (None, "", READER + "x", READER[:-1], "nope"):
        assert find_key(bad, ring) is None


@pytest.mark.parametrize(
    ("method", "path", "role"),
    [
        ("GET", "/v1/tenants/{tenant_id}/decisions", Role.VIEWER),
        ("HEAD", "/v1/tenants", Role.VIEWER),
        ("POST", "/v1/tenants/{tenant_id}/tool-calls", Role.OPERATOR),
        ("POST", "/v1/tenants/{tenant_id}/check", Role.OPERATOR),
        ("POST", "/v1/tenants/{tenant_id}/utterances", Role.ADMIN),
        ("POST", "/v1/tenants/{tenant_id}/actions/{action_id}/approve", Role.ADMIN),
        ("POST", "/v1/tenants/{tenant_id}/instructions/{instruction_id}/quarantine", Role.ADMIN),
        ("DELETE", "/v1/tenants/{tenant_id}", Role.ADMIN),
        ("PUT", "/anything/new", Role.ADMIN),  # unknown shapes default to the strictest role
    ],
)
def test_required_role_table(method: str, path: str, role: Role) -> None:
    assert required_role(method, path) is role


# --- over HTTP -----------------------------------------------------------------------


def seed(c: TestClient) -> None:
    for tenant in ("acme", "globex", "initech"):
        made = c.post("/v1/tenants", json={"tenant_id": tenant, "name": tenant}, headers=h(ADMIN))
        assert made.status_code == 201


def test_viewer_can_read_its_tenant_but_not_write_or_see_others() -> None:
    c = client()
    seed(c)
    assert c.get("/v1/tenants/acme/stats", headers=h(READER)).status_code == 200
    assert c.get("/v1/tenants/globex/stats", headers=h(READER)).status_code == 404
    write = c.post(
        "/v1/tenants/acme/principals", json={"name": "x", "role": "owner"}, headers=h(READER)
    )
    assert write.status_code == 403 and write.json()["error"]["code"] == "forbidden"
    check = c.post(
        "/v1/tenants/acme/check",
        json={"agent_id": "agt_" + "0" * 26, "action_type": "email.read", "resource": "inbox/a"},
        headers=h(READER),
    )
    assert check.status_code == 403  # a viewer cannot even ask for decisions to be recorded


def test_a_foreign_tenant_looks_exactly_like_a_missing_one() -> None:
    c = client()
    seed(c)
    foreign = c.get("/v1/tenants/globex/stats", headers=h(READER))
    missing = c.get("/v1/tenants/nowhere/stats", headers=h(READER))
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["error"]["code"] == missing.json()["error"]["code"]


def test_scoped_keys_only_list_their_tenants_and_cannot_create_tenants() -> None:
    c = client()
    seed(c)
    runner = {t["tenant_id"] for t in c.get("/v1/tenants", headers=h(RUNNER)).json()}
    assert runner == {"acme", "globex"}
    everything = {t["tenant_id"] for t in c.get("/v1/tenants", headers=h(ADMIN)).json()}
    assert everything == {"acme", "globex", "initech"}
    made = c.post("/v1/tenants", json={"tenant_id": "new", "name": "n"}, headers=h(ACME_ADMIN))
    assert made.status_code == 403


def test_operator_runs_tools_but_cannot_change_rules_or_approve() -> None:
    c = client()
    seed(c)
    owner = c.post(
        "/v1/tenants/acme/principals", json={"name": "d", "role": "owner"}, headers=h(ADMIN)
    ).json()["id"]
    agent = c.post(
        "/v1/tenants/acme/agents", json={"name": "m", "kind": "primary"}, headers=h(ADMIN)
    ).json()["id"]
    call = c.post(
        "/v1/tenants/acme/tool-calls",
        json={"agent_id": agent, "tool": "email_list", "args": {}},
        headers=h(RUNNER),
    )
    assert call.status_code == 200 and call.json()["status"] == "denied"  # default deny
    say = c.post(
        "/v1/tenants/acme/utterances",
        json={"principal_id": owner, "text": "You may read my email.", "channel": "owner_direct"},
        headers=h(RUNNER),
    )
    assert say.status_code == 403
    approve = c.post(
        "/v1/tenants/acme/actions/act_x/approve",
        json={"by": owner, "approved": True},
        headers=h(RUNNER),
    )
    assert approve.status_code == 403


def test_tenant_admin_manages_only_its_own_tenant() -> None:
    c = client()
    seed(c)
    ok = c.post(
        "/v1/tenants/acme/principals", json={"name": "d", "role": "owner"}, headers=h(ACME_ADMIN)
    )
    assert ok.status_code == 201
    other = c.post(
        "/v1/tenants/globex/principals", json={"name": "d", "role": "owner"}, headers=h(ACME_ADMIN)
    )
    assert other.status_code == 404
    assert c.delete("/v1/tenants/globex", headers=h(ACME_ADMIN)).status_code == 404


def test_each_key_has_its_own_rate_limit_bucket() -> None:
    c = client(mandate_rate_limit_per_min=2)
    codes = [c.get("/v1/tenants", headers=h(READER)).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    assert c.get("/v1/tenants", headers=h(RUNNER)).status_code == 200  # another key, own bucket


def test_metrics_follow_the_same_rules() -> None:
    c = client()
    assert c.get("/metrics").status_code == 401
    assert c.get("/metrics", headers=h(READER)).status_code == 200


def test_api_key_is_frozen() -> None:
    key = ApiKey("k", "s" * 16, Role.VIEWER, None)
    with pytest.raises(AttributeError):
        key.role = Role.ADMIN  # type: ignore[misc]
