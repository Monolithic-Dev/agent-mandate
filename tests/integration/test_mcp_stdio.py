"""The MCP servers as real processes over stdio, against a real FalkorDB."""

import os
import subprocess
import sys
from collections.abc import Iterator
from typing import Any

import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

from mandate.api.tenancy import FalkorTenantBackend, Runtimes
from mandate.clock import SystemClock
from mandate.config import Settings, token_secrets
from mandate.graph.client import GraphClient
from mandate.ids import new_id
from mandate.mcp_servers.identity import AgentIdentity, mint_agent_token
from mandate.models.domain import Agent, AgentKind, Channel, Principal, Role

pytestmark = pytest.mark.integration

SECRET = "integration-secret-0123456789"
# What the server process signs and verifies agent tokens with when only the admin key is set.
TOKEN_SECRET = token_secrets(Settings(mandate_api_key=SECRET, _env_file=None))[0]  # type: ignore[call-arg]


@pytest.fixture
def tenant(graph_client: GraphClient) -> Iterator[tuple[Runtimes, str, Any, Any]]:
    tenant_id = f"mcp{new_id('act')[4:14].lower()}"
    runtimes = Runtimes(FalkorTenantBackend(graph_client), SystemClock())
    runtime = runtimes.create(tenant_id, "MCP stdio test")
    owner = runtime.store.create_principal(
        Principal(id=new_id("prn"), name="Dana", role=Role.OWNER)
    )
    agent = runtime.store.create_agent(Agent(id=new_id("agt"), name="main", kind=AgentKind.PRIMARY))
    yield runtimes, tenant_id, owner, agent
    runtimes.drop(tenant_id)


def server_params(*args: str) -> StdioServerParameters:
    env = {**os.environ, "MANDATE_API_KEY": SECRET}
    env.pop("MANDATE_TOKEN_SECRETS", None)
    return StdioServerParameters(
        command=sys.executable, args=["-m", "mandate.mcp_servers", *args], env=env
    )


async def test_agent_process_enforces_the_owners_rules(
    tenant: tuple[Runtimes, str, Any, Any],
) -> None:
    runtimes, tenant_id, owner, agent = tenant
    service = runtimes.get(tenant_id).service
    token = mint_agent_token(TOKEN_SECRET, AgentIdentity(tenant_id, agent.id))

    async with Client(server_params("agent", "--token", token)) as client:
        who = (await client.call_tool("whoami", {})).structured_content
        assert who == {"tenant_id": tenant_id, "agent_id": agent.id}
        first = (await client.call_tool("email_list", {})).structured_content
        assert first["status"] == "denied"  # default deny, from the graph

        said = service.ingest_utterance(
            principal_id=owner.id,
            text="You may read my email, but never delete any email.",
            channel=Channel.OWNER_DIRECT,
        )
        for item in said.instructions:
            if item.needs_confirmation:
                service.confirm_instruction(item.instruction.id, owner.id)

        allowed = (await client.call_tool("email_list", {})).structured_content
        deleted = (await client.call_tool("email_delete", {"message_id": "m-1"})).structured_content
    assert allowed["status"] == "ok"
    assert deleted["status"] == "denied" and deleted["reason"] == "explicit_deny"


def test_agent_profile_refuses_to_start_without_a_valid_token() -> None:
    env = {**os.environ, "MANDATE_API_KEY": SECRET}
    env.pop("MANDATE_TOKEN_SECRETS", None)
    done = subprocess.run(
        [sys.executable, "-m", "mandate.mcp_servers", "agent", "--token", "forged"],
        env=env,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 2 and b"valid --token" in done.stderr
