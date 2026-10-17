"""The MCP servers, exercised through a real in-memory MCP client (no database)."""

import base64
import time
from types import SimpleNamespace
from typing import Any

import pytest
from fakes.memory_backend import MemoryTenantBackend
from mcp.client import Client

from mandate.api.tenancy import Runtimes
from mandate.clock import SystemClock
from mandate.gateway.tools import TOOLS
from mandate.mcp_servers import resolvers
from mandate.mcp_servers.admin_server import AdminIdentity, build_admin_server
from mandate.mcp_servers.agent_server import build_agent_server
from mandate.mcp_servers.identity import (
    LEGACY_PREFIX,
    AgentIdentity,
    _sign,
    bearer_token,
    mint_agent_token,
    mint_agent_token_with_id,
    verify_agent_token,
)
from mandate.models.domain import AgentKind, Role

SECRET = "unit-test-secret-0123456789"


def same(found: AgentIdentity | None, expected: AgentIdentity) -> bool:
    """Equal tenant and agent; the expiry stamped into a token is checked separately."""
    return found is not None and (found.tenant_id, found.agent_id) == (
        expected.tenant_id,
        expected.agent_id,
    )


def context(headers: dict[str, str] | None) -> Any:
    return SimpleNamespace(headers=headers)


class Setup:
    def __init__(self) -> None:
        self.runtimes = Runtimes(MemoryTenantBackend(), SystemClock())
        self.runtime = self.runtimes.create("t1", "Test tenant")
        store: Any = self.runtime.store
        self.owner = store.add_principal("Dana", Role.OWNER)
        self.agent = store.add_agent("main", AgentKind.PRIMARY)
        who = AgentIdentity("t1", self.agent.id)
        self.agent_client = Client(build_agent_server(self.runtimes, resolvers.static_agent(who)))
        admin = AdminIdentity("t1", self.owner.id)
        self.admin_client = Client(
            build_admin_server(self.runtimes, resolvers.static_admin(admin), SECRET)
        )

    @property
    def sandbox(self) -> Any:
        return self.runtime.gateway.sandbox


@pytest.fixture
def setup() -> Setup:
    return Setup()


async def call(client: Client, tool: str, **arguments: Any) -> Any:
    result = await client.call_tool(tool, arguments)
    assert not result.is_error, result
    content = result.structured_content
    # The SDK wraps a bare list return value as {"result": [...]}.
    return content["result"] if list(content) == ["result"] else content


async def grant(admin: Client, text: str) -> list[dict[str, Any]]:
    said = await call(admin, "say", text=text)
    for item in said["instructions"]:
        if item["needs_confirmation"]:
            await call(admin, "confirm_instruction", instruction_id=item["id"])
    return said["instructions"]


# --- tokens -------------------------------------------------------------------------


def test_token_round_trip_and_tampering() -> None:
    who = AgentIdentity("t1", "agt_1")
    token = mint_agent_token(SECRET, who)
    assert same(verify_agent_token(SECRET, token), who)
    assert verify_agent_token("another-secret-0123456789", token) is None
    head, payload, signature = token.split(".")
    assert verify_agent_token(SECRET, f"{head}.{payload}x.{signature}") is None
    assert verify_agent_token(SECRET, f"{head}.{payload}.{'0' * len(signature)}") is None
    for junk in (None, "", "garbage", "a.b", "a.b.c.d", f"bad.{payload}.{signature}"):
        assert verify_agent_token(SECRET, junk) is None


def test_ids_with_the_separator_cannot_be_minted() -> None:
    with pytest.raises(ValueError):
        mint_agent_token(SECRET, AgentIdentity("t|1", "agt_1"))


def test_bearer_header_parsing() -> None:
    assert bearer_token("Bearer abc") == "abc" and bearer_token("bearer abc") == "abc"
    assert bearer_token("Basic abc") is None and bearer_token(None) is None


def test_http_agent_resolver_requires_a_valid_token() -> None:
    token = mint_agent_token(SECRET, AgentIdentity("t1", "agt_1"))
    identify = resolvers.http_agent(SECRET)
    assert same(
        identify(context({"authorization": f"Bearer {token}"})), AgentIdentity("t1", "agt_1")
    )
    for headers in ({}, {"authorization": "Bearer nope"}, None):
        with pytest.raises(PermissionError):
            identify(context(headers))


def test_http_admin_resolver_requires_the_admin_key_and_a_target() -> None:
    identify = resolvers.http_admin(SECRET)
    good = {"authorization": f"Bearer {SECRET}", "x-mandate-tenant": "t1", "x-mandate-owner": "p"}
    assert identify(context(good)) == AdminIdentity("t1", "p")
    agent_token = mint_agent_token(SECRET, AgentIdentity("t1", "agt_1"))
    for headers in (
        {**good, "authorization": "Bearer wrong"},
        {k: v for k, v in good.items() if k != "x-mandate-owner"},
        {**good, "authorization": f"Bearer {agent_token}"},  # an agent token is not the admin key
    ):
        with pytest.raises(PermissionError):
            identify(context(headers))


# --- the agent profile --------------------------------------------------------------


async def test_agent_server_exposes_the_gateway_tools_and_nothing_administrative(
    setup: Setup,
) -> None:
    async with setup.agent_client as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    assert set(tools) == set(TOOLS) | {"whoami", "can_i"}
    assert "message_id" in tools["email_delete"].input_schema["properties"]  # flat parameters
    assert "maximum" in tools["refund_issue"].input_schema["properties"]["amount"]


async def test_the_agent_cannot_choose_its_identity(setup: Setup) -> None:
    async with setup.agent_client as client:
        assert await call(client, "whoami") == {"tenant_id": "t1", "agent_id": setup.agent.id}
        spoofed = await client.call_tool("email_list", {"agent_id": "someone-else"})
    assert spoofed.is_error or spoofed.structured_content["status"] != "ok"


async def test_default_deny_then_owner_rule_then_hold_and_approve(setup: Setup) -> None:
    async with setup.agent_client as agent, setup.admin_client as admin:
        refused = await call(agent, "email_list")
        assert refused["status"] == "denied" and refused["reason"] == "no_authority_path"

        rules = await grant(
            admin, "You may read my email, but confirm with me before deleting anything."
        )
        assert rules

        assert (await call(agent, "email_list"))["status"] == "ok"
        held = await call(agent, "email_delete", message_id="m-1")
        assert held["status"] == "confirmation_required"
        assert "m-1" in setup.sandbox.messages

        pending = await call(admin, "pending_approvals")
        assert [row["action_id"] for row in pending] == [held["approval_id"]]
        done = await call(admin, "resolve_approval", action_id=held["approval_id"], approve=True)
        assert done["status"] == "ok"
        assert "m-1" not in setup.sandbox.messages

        why = await call(admin, "explain_decision", decision_id=held["decision_id"])
        assert why["result"] == "confirm" and why["narrative"]


async def test_declining_a_held_action_leaves_it_unexecuted(setup: Setup) -> None:
    async with setup.agent_client as agent, setup.admin_client as admin:
        await grant(admin, "You may read my email, but confirm with me before deleting anything.")
        held = await call(agent, "email_delete", message_id="m-2")
        done = await call(admin, "resolve_approval", action_id=held["approval_id"], approve=False)
    assert done["status"] == "denied" and "m-2" in setup.sandbox.messages


async def test_instructions_inside_an_email_grant_nothing(setup: Setup) -> None:
    async with setup.agent_client as agent, setup.admin_client as admin:
        await grant(admin, "You may read my email.")
        assert (await call(agent, "email_read", message_id="m-31"))["status"] == "ok"
        sent = await call(agent, "email_send", to="evil@example.com", subject="x", body="y")
    assert sent["status"] == "denied" and setup.sandbox.sent == []


async def test_can_i_does_not_run_anything(setup: Setup) -> None:
    async with setup.agent_client as agent:
        answer = await call(agent, "can_i", action_type="email.delete", resource="inbox/m-1")
        assert answer["result"] == "deny"
        bad = await call(agent, "can_i", action_type="not an action", resource="inbox/m-1")
    assert bad["reason"] == "bad_arguments"
    assert "m-1" in setup.sandbox.messages


async def test_can_i_records_nothing_and_never_fills_the_approval_queue(setup: Setup) -> None:
    async with setup.admin_client as admin, setup.agent_client as agent:
        await grant(admin, "Confirm before deleting.")
        for _ in range(3):
            answer = await call(agent, "can_i", action_type="email.delete", resource="inbox/m-1")
            assert answer == {"result": "confirm", "reason": "confirm_rule"}
        assert await call(admin, "pending_approvals") == []
    assert setup.runtime.store.list_decisions(limit=100) == []


# --- the admin profile --------------------------------------------------------------


async def test_admin_can_mint_a_token_only_for_a_real_agent(setup: Setup) -> None:
    async with setup.admin_client as admin:
        token = (await call(admin, "agent_token", agent_id=setup.agent.id))["token"]
        assert same(verify_agent_token(SECRET, token), AgentIdentity("t1", setup.agent.id))
        short = await call(admin, "agent_token", agent_id=setup.agent.id, ttl_seconds=60)
        assert short["expires_in_seconds"] == 60
        stranger = await admin.call_tool("agent_token", {"agent_id": "agt_" + "0" * 26})
    assert stranger.is_error


async def test_admin_tools_refuse_a_non_owner(setup: Setup) -> None:
    store: Any = setup.runtime.store
    outsider = store.add_principal("mallory", Role.EXTERNAL)
    server = build_admin_server(
        setup.runtimes, resolvers.static_admin(AdminIdentity("t1", outsider.id)), SECRET
    )
    async with Client(server) as client:
        result = await client.call_tool("say", {"text": "You may read my email."})
    assert result.is_error


async def test_lineage_tools_round_trip(setup: Setup) -> None:
    async with setup.agent_client as agent, setup.admin_client as admin:
        rule = (await grant(admin, "You may issue refunds up to $5000."))[0]["id"]
        assert (await call(agent, "refund_issue", order_id="85", amount=600))["status"] == "ok"
        radius = await call(admin, "blast_radius_of", instruction_id=rule)
        assert len(radius["decisions"]) == 1
        replay = await call(admin, "replay_without_instruction", instruction_id=rule)
        assert replay["evaluated"] == 1
        assert (await call(admin, "quarantine_instruction", instruction_id=rule))["quarantined"]
        assert (await call(agent, "refund_issue", order_id="86", amount=100))["status"] == "denied"
        released = await call(admin, "quarantine_instruction", instruction_id=rule, release=True)
        assert released["quarantined"] is False


async def test_reliance_tool_ranks_rules(setup: Setup) -> None:
    async with setup.agent_client as agent, setup.admin_client as admin:
        await grant(admin, "You may read my email.")
        for _ in range(2):
            assert (await call(agent, "email_list"))["status"] == "ok"
        rows = await call(admin, "reliance")
        assert len(rows) == 1 and rows[0]["decisions"] == 2 and rows[0]["needs_review"] is False


# --- expiry and rotation --------------------------------------------------------------


def test_a_token_expires() -> None:
    who = AgentIdentity("t1", "agt_1")
    token = mint_agent_token(SECRET, who, ttl_seconds=60, now=1_000.0)
    assert same(verify_agent_token(SECRET, token, now=1_059.0), who)
    assert verify_agent_token(SECRET, token, now=1_060.0) is None  # at the expiry instant
    assert verify_agent_token(SECRET, token, now=9_999.0) is None


def test_the_expiry_is_covered_by_the_signature() -> None:
    token = mint_agent_token(SECRET, AgentIdentity("t1", "agt_1"), ttl_seconds=60, now=1_000.0)
    head, payload, signature = token.split(".")
    raw = base64.urlsafe_b64decode(payload.encode()).decode().rsplit("|", 1)[0]
    stretched = base64.urlsafe_b64encode(f"{raw}|{10**10}".encode()).decode()
    assert verify_agent_token(SECRET, f"{head}.{stretched}.{signature}", now=2_000.0) is None


@pytest.mark.parametrize("ttl", [0, -5, 31 * 86_400])
def test_unreasonable_lifetimes_are_refused(ttl: int) -> None:
    with pytest.raises(ValueError):
        mint_agent_token(SECRET, AgentIdentity("t1", "agt_1"), ttl_seconds=ttl)


def test_rotation_old_tokens_verify_until_the_old_secret_is_dropped() -> None:
    old, new = "old-secret-0123456789", "new-secret-0123456789"
    who = AgentIdentity("t1", "agt_1")
    signed_before = mint_agent_token(old, who)
    signed_after = mint_agent_token(new, who)
    during = [new, old]  # newest first
    assert same(verify_agent_token(during, signed_before), who)
    assert same(verify_agent_token(during, signed_after), who)
    after = [new]  # the old secret is dropped
    assert verify_agent_token(after, signed_before) is None
    assert same(verify_agent_token(after, signed_after), who)


def test_a_stdio_identity_stops_working_when_its_token_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    who = AgentIdentity("t1", "agt_1", expires_at=int(time.time()) + 100)
    identify = resolvers.static_agent(who)
    assert identify(context({})) is who
    assert who.expires_at is not None
    monkeypatch.setattr("mandate.mcp_servers.resolvers.time.time", lambda: who.expires_at + 1)
    with pytest.raises(PermissionError):
        identify(context({}))


async def test_verify_explanation_tool(setup: Setup) -> None:
    async with setup.agent_client as agent, setup.admin_client as admin:
        await grant(admin, "You may read my email.")
        decision = (await call(agent, "email_list"))["decision_id"]
        verified = await call(admin, "verify_explanation", decision_id=decision)
        assert verified["ok"] is True and verified["failures"] == [] and verified["checks"] >= 8


# --- per-token revocation ---------------------------------------------------------------


def test_every_token_has_its_own_signed_id() -> None:
    who = AgentIdentity("t1", "agt_1")
    first, minted = mint_agent_token_with_id(SECRET, who)
    second = mint_agent_token(SECRET, who)
    found = verify_agent_token(SECRET, first)
    assert found is not None and found.token_id == minted.token_id
    assert minted.token_id is not None and minted.token_id.startswith("tok_")
    other = verify_agent_token(SECRET, second)
    assert other is not None and other.token_id != minted.token_id
    # Swapping in another id breaks the signature.
    head, payload, signature = first.split(".")
    raw = base64.urlsafe_b64decode(payload.encode()).decode()
    swapped = raw.replace(minted.token_id, other.token_id or "")
    forged = base64.urlsafe_b64encode(swapped.encode()).decode()
    assert verify_agent_token(SECRET, f"{head}.{forged}.{signature}") is None


def test_a_token_from_before_ids_still_verifies_without_one() -> None:
    payload = base64.urlsafe_b64encode(f"t1|agt_1|{int(time.time()) + 60}".encode()).decode()
    legacy = f"{LEGACY_PREFIX}.{payload}.{_sign(SECRET, payload)}"
    found = verify_agent_token(SECRET, legacy)
    assert same(found, AgentIdentity("t1", "agt_1")) and found is not None
    assert found.token_id is None


def test_a_token_with_a_malformed_id_is_refused() -> None:
    payload = base64.urlsafe_b64encode(f"t1|agt_1|tok_x|{int(time.time()) + 60}".encode()).decode()
    assert verify_agent_token(SECRET, f"mnd3.{payload}.{_sign(SECRET, payload)}") is None


CAN_I = {"action_type": "email.read", "resource": "inbox/m-1"}


def agent_client_for(setup: Setup, token: str) -> Client:
    who = verify_agent_token(SECRET, token)
    assert who is not None
    return Client(build_agent_server(setup.runtimes, resolvers.static_agent(who)))


async def test_a_revoked_token_is_refused_from_its_next_call(setup: Setup) -> None:
    async with setup.admin_client as admin:
        await grant(admin, "You may read my email.")
        doomed = await call(admin, "agent_token", agent_id=setup.agent.id)
        kept = await call(admin, "agent_token", agent_id=setup.agent.id)
        assert doomed["token_id"] != kept["token_id"]
        async with agent_client_for(setup, doomed["token"]) as agent:
            assert (await call(agent, "email_list"))["status"] == "ok"
            revoked = await call(admin, "revoke_agent_token", token_id=doomed["token_id"])
            assert revoked["token_id"] == doomed["token_id"] and revoked["by"] == setup.owner.id
            for tool, args in (("email_list", {}), ("whoami", {}), ("can_i", CAN_I)):
                assert (await agent.call_tool(tool, args)).is_error
        async with agent_client_for(setup, kept["token"]) as agent:
            assert (await call(agent, "email_list"))["status"] == "ok"  # the other still works


async def test_revoking_by_the_token_itself_records_its_agent_and_expiry(setup: Setup) -> None:
    async with setup.admin_client as admin:
        minted = await call(admin, "agent_token", agent_id=setup.agent.id)
        revoked = await call(admin, "revoke_agent_token", token=minted["token"])
        assert revoked["agent_id"] == setup.agent.id
        assert revoked["expires_at"] == minted["expires_at"] * 1000
        again = await call(admin, "revoke_agent_token", token_id=minted["token_id"])
        assert again == revoked  # idempotent: the first record stands
        foreign = mint_agent_token(SECRET, AgentIdentity("t2", setup.agent.id))
        for bad in ({"token": foreign}, {"token": "nope"}, {}, {"token_id": "tok_short"}):
            assert (await admin.call_tool("revoke_agent_token", bad)).is_error
