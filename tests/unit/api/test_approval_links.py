"""Approval links: bound to one action, tenant and approver; expiring; first use wins."""

import base64
import time
from typing import Any

import pytest
from fakes.memory_backend import MemoryTenantBackend
from fastapi.testclient import TestClient

from mandate.api.app import create_app
from mandate.api.approval_links import link_secrets, mint_link, read_link
from mandate.clock import FixedClock
from mandate.config import Settings, token_secrets
from mandate.ids import new_id
from mandate.mcp_servers.identity import AgentIdentity, mint_agent_token

ADMIN = "a" * 24
READER = "r" * 24
H = {"X-Mandate-Key": ADMIN}
SETTINGS = Settings(  # type: ignore[call-arg]
    mandate_api_key=ADMIN,
    mandate_api_keys=f"reader:{READER}:viewer:*",  # type: ignore[arg-type]
    _env_file=None,
)
SECRET = "link-test-secret-0123456789"
S1 = "You may read and archive my email, but confirm with me before deleting anything."
ACT, PRN = new_id("act"), new_id("prn")


# --- the token ---------------------------------------------------------------------------


def test_round_trip_expiry_and_wrong_key() -> None:
    token, link = mint_link(SECRET, "acme", ACT, PRN, ttl_seconds=60, now=1_000.0)
    assert read_link([SECRET], token, now=1_059.0) == link
    assert (link.tenant_id, link.action_id, link.approver_id) == ("acme", ACT, PRN)
    assert read_link([SECRET], token, now=1_060.0) is None  # expired at the instant
    assert read_link(["another-secret-0123456789"], token, now=1_000.0) is None
    assert read_link(["another-secret-0123456789", SECRET], token, now=1_000.0) == link


@pytest.mark.parametrize("field", ["acme", ACT, PRN])
def test_every_bound_field_is_covered_by_the_signature(field: str) -> None:
    token, _ = mint_link(SECRET, "acme", ACT, PRN)
    head, payload, signature = token.split(".")
    raw = base64.urlsafe_b64decode(payload.encode()).decode()
    other = {"acme": "globex", ACT: new_id("act"), PRN: new_id("prn")}[field]
    swapped = base64.urlsafe_b64encode(raw.replace(field, other).encode()).decode()
    assert read_link([SECRET], f"{head}.{swapped}.{signature}") is None


def test_an_agent_token_is_never_a_link() -> None:
    keys = link_secrets([SECRET])
    assert keys != [SECRET]  # links have their own derived key
    agent = mint_agent_token(SECRET, AgentIdentity("acme", new_id("agt")))
    assert read_link(keys, agent) is None
    # Even a link-shaped token signed with the agent-token secret itself is refused.
    signed_with_agent_secret, _ = mint_link(SECRET, "acme", ACT, PRN)
    assert read_link(keys, signed_with_agent_secret) is None


@pytest.mark.parametrize("junk", [None, "", "apl1", "apl1.x.y", "apl1.a.b.c", "mnd3.a.b"])
def test_junk_is_refused(junk: str | None) -> None:
    assert read_link([SECRET], junk) is None


@pytest.mark.parametrize(
    ("tenant", "action", "approver", "ttl"),
    [
        ("a|b", ACT, PRN, 60),
        ("acme", "act_x", PRN, 60),
        ("acme", ACT, "agt_x", 60),
        ("acme", ACT, PRN, 0),
        ("acme", ACT, PRN, 86_401),
    ],
)
def test_bad_links_are_not_minted(tenant: str, action: str, approver: str, ttl: int) -> None:
    with pytest.raises(ValueError):
        mint_link(SECRET, tenant, action, approver, ttl_seconds=ttl)


# --- over HTTP ---------------------------------------------------------------------------


class Held:
    """A tenant with an email deletion held for the owner's approval."""

    def __init__(self) -> None:
        app = create_app(SETTINGS, MemoryTenantBackend(), FixedClock())
        self.c = TestClient(app, raise_server_exceptions=False)
        self.base = "/v1/tenants/acme"
        assert self.c.post("/v1/tenants", json={"tenant_id": "acme", "name": "Acme"}, headers=H)
        self.owner = self.post("/principals", {"name": "Dana", "role": "owner"}).json()["id"]
        self.outsider = self.post("/principals", {"name": "x", "role": "external"}).json()["id"]
        self.main = self.post("/agents", {"name": "main", "kind": "primary"}).json()["id"]
        said = self.post(
            "/utterances", {"principal_id": self.owner, "text": S1, "channel": "owner_direct"}
        ).json()
        for item in said["instructions"]:
            if item["needs_confirmation"]:
                rule = item["instruction"]["id"]
                assert self.post(f"/instructions/{rule}/confirm", {"by": self.owner}).is_success
        held = self.post(
            "/tool-calls",
            {"agent_id": self.main, "tool": "email_delete", "args": {"message_id": "m-1"}},
        ).json()
        assert held["status"] == "confirmation_required"
        self.action, self.decision = held["approval_id"], held["decision_id"]

    def post(self, path: str, body: dict[str, Any], headers: dict[str, str] = H) -> Any:
        return self.c.post(self.base + path, json=body, headers=headers)

    def link(self, **body: Any) -> dict[str, Any]:
        made = self.post(f"/actions/{self.action}/approval-link", {"by": self.owner, **body})
        assert made.status_code == 201, made.text
        return made.json()  # type: ignore[no-any-return]

    def public(self, path: str, body: dict[str, Any]) -> Any:
        return self.c.post(f"/v1/approval-links/{path}", json=body)  # no API key


def test_a_link_shows_the_action_then_approves_it_once() -> None:
    h = Held()
    made, second = h.link(), h.link()
    assert made["path"] == f"/approve#{made['token']}"
    assert made["expires_at"] - time.time() == pytest.approx(15 * 60, abs=5)

    seen = h.public("inspect", {"token": made["token"]})
    assert seen.status_code == 200, seen.text
    body = seen.json()
    assert body["action"]["id"] == h.action and body["action"]["args"]["tool"] == "email_delete"
    assert body["decision_id"] == h.decision and body["narrative"].startswith("Needs approval")
    assert body["approver"]["id"] == h.owner and body["agent"]["id"] == h.main
    assert body["pending"] is True

    done = h.public("resolve", {"token": made["token"], "approved": True})
    assert done.status_code == 200 and done.json()["status"] == "ok"
    again = h.public("resolve", {"token": made["token"], "approved": False})
    assert again.status_code == 409  # the first use wins
    other_link = h.public("resolve", {"token": second["token"], "approved": True})
    assert other_link.status_code == 409  # and so does any other link for the same action
    assert h.public("inspect", {"token": made["token"]}).json()["pending"] is False


def test_declining_through_a_link() -> None:
    h = Held()
    done = h.public("resolve", {"token": h.link()["token"], "approved": False})
    assert done.json() == {"status": "denied", "reason": "owner_declined", "approval_id": h.action}
    assert h.post(f"/actions/{h.action}/approval-link", {"by": h.owner}).status_code == 409


def test_bad_and_expired_links_get_one_answer() -> None:
    h = Held()
    keys = link_secrets(token_secrets(SETTINGS))
    expired, _ = mint_link(keys[0], "acme", h.action, h.owner, ttl_seconds=60, now=0.0)
    gone_tenant, _ = mint_link(keys[0], "nowhere", h.action, h.owner)
    for token in (expired, gone_tenant, "apl1.x.y", "nope"):
        for path, body in (("inspect", {}), ("resolve", {"approved": True})):
            response = h.public(path, {"token": token, **body})
            assert response.status_code == 401, (token, path, response.text)
            assert response.json()["error"]["message"].startswith("this approval link")


def test_a_link_for_someone_no_longer_owner_cannot_approve() -> None:
    h = Held()
    keys = link_secrets(token_secrets(SETTINGS))
    token, _ = mint_link(keys[0], "acme", h.action, h.outsider)  # as if minted by mistake
    assert h.public("resolve", {"token": token, "approved": True}).status_code == 422


def test_minting_needs_an_admin_key_an_owner_and_a_held_action() -> None:
    h = Held()
    viewer = {"X-Mandate-Key": READER}
    path = f"/actions/{h.action}/approval-link"
    assert h.post(path, {"by": h.owner}, viewer).status_code == 403
    assert h.c.post(h.base + path, json={"by": h.owner}).status_code == 401
    assert h.post(path, {"by": h.outsider}).status_code == 422
    assert h.post(path, {"by": h.owner, "ttl_seconds": 10}).status_code == 422
    unknown = f"/actions/{new_id('act')}/approval-link"
    assert h.post(unknown, {"by": h.owner}).status_code == 404
