"""Agent tokens over REST: mint for a real agent, revoke one by id or by the token itself."""

from typing import Any

from fakes.memory_backend import MemoryTenantBackend
from fastapi.testclient import TestClient

from mandate.api.app import create_app
from mandate.clock import FixedClock
from mandate.config import Settings, token_secrets
from mandate.mcp_servers.identity import AgentIdentity, mint_agent_token, verify_agent_token

ADMIN = "a" * 24
READER = "r" * 24
H = {"X-Mandate-Key": ADMIN}
SETTINGS = Settings(  # type: ignore[call-arg,arg-type]
    mandate_api_key=ADMIN, mandate_api_keys=f"reader:{READER}:viewer:*", _env_file=None
)


class Tenant:
    def __init__(self, c: TestClient, tenant_id: str = "acme") -> None:
        self.c = c
        self.base = f"/v1/tenants/{tenant_id}"
        made = c.post("/v1/tenants", json={"tenant_id": tenant_id, "name": tenant_id}, headers=H)
        assert made.status_code == 201
        self.owner = self.post("/principals", {"name": "Dana", "role": "owner"}).json()["id"]
        self.outsider = self.post("/principals", {"name": "x", "role": "external"}).json()["id"]
        self.main = self.post("/agents", {"name": "main", "kind": "primary"}).json()["id"]

    def post(self, path: str, body: dict[str, Any], headers: dict[str, str] = H) -> Any:
        return self.c.post(self.base + path, json=body, headers=headers)

    def get(self, path: str, headers: dict[str, str] = H) -> Any:
        return self.c.get(self.base + path, headers=headers)

    def mint(self, **body: Any) -> dict[str, Any]:
        minted = self.post(f"/agents/{self.main}/tokens", {"by": self.owner, **body})
        assert minted.status_code == 201, minted.text
        return minted.json()


def make_client() -> TestClient:
    app = create_app(SETTINGS, MemoryTenantBackend(), FixedClock())
    return TestClient(app, raise_server_exceptions=False)


def test_mint_then_revoke_by_id() -> None:
    c = make_client()
    t = Tenant(c)
    body = t.mint(ttl_seconds=600)
    who = verify_agent_token(token_secrets(SETTINGS), body["token"])
    assert who is not None
    assert (who.tenant_id, who.agent_id, who.token_id) == ("acme", t.main, body["token_id"])
    assert body["expires_at"] == who.expires_at

    revoked = t.post("/token-revocations", {"by": t.owner, "token_id": body["token_id"]})
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["token_id"] == body["token_id"] and revoked.json()["agent_id"] is None
    listed = t.get("/token-revocations").json()
    assert [row["token_id"] for row in listed] == [body["token_id"]]
    runtime = c.app.state.runtimes.require("acme")  # type: ignore[attr-defined]
    assert runtime.service.token_revoked(body["token_id"])


def test_revoke_by_the_token_records_its_agent_and_expiry() -> None:
    t = Tenant(make_client())
    minted = t.mint()
    revoked = t.post("/token-revocations", {"by": t.owner, "token": minted["token"]}).json()
    assert revoked["agent_id"] == t.main
    assert revoked["expires_at"] == minted["expires_at"] * 1000


def test_revocation_refusals() -> None:
    c = make_client()
    t, other = Tenant(c), Tenant(c, "globex")
    token = t.mint()["token"]
    foreign = other.post(f"/agents/{other.main}/tokens", {"by": other.owner}).json()["token"]
    stranger = mint_agent_token("some-other-secret-0123456789", AgentIdentity("acme", t.main))
    for body, status in (
        ({"by": t.owner, "token": foreign}, 400),  # another tenant's token
        ({"by": t.owner, "token": stranger}, 400),  # not signed by this server
        ({"by": t.owner, "token": "mnd3.x.y"}, 400),
        ({"by": t.owner}, 400),  # nothing named
        ({"by": t.outsider, "token": token}, 422),  # only the owner revokes
        ({"by": t.owner, "token_id": "tok_nope"}, 422),
    ):
        response = t.post("/token-revocations", body)
        assert response.status_code == status, (body, response.text)


def test_mint_refusals_and_roles() -> None:
    t = Tenant(make_client())
    unknown = "agt_" + "0" * 26
    assert t.post(f"/agents/{unknown}/tokens", {"by": t.owner}).status_code == 404
    assert t.post(f"/agents/{t.main}/tokens", {"by": t.outsider}).status_code == 422
    too_long = t.post(f"/agents/{t.main}/tokens", {"by": t.owner, "ttl_seconds": 10**9})
    assert too_long.status_code == 422

    viewer = {"X-Mandate-Key": READER}
    assert t.post(f"/agents/{t.main}/tokens", {"by": t.owner}, viewer).status_code == 403
    assert t.post("/token-revocations", {"by": t.owner}, viewer).status_code == 403
    assert t.get("/token-revocations", viewer).json() == []
