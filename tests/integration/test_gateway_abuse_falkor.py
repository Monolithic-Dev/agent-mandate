"""The injection corpus against a real FalkorDB: hostile text must stay data in the graph."""

import json
from pathlib import Path

import pytest

from mandate.api.tenancy import FalkorTenantBackend, Runtimes
from mandate.clock import SystemClock
from mandate.graph.client import GraphClient
from mandate.ids import new_id
from mandate.models.domain import Agent, AgentKind, Channel, Principal, Role

pytestmark = pytest.mark.integration

CORPUS = json.loads(
    (Path(__file__).parent.parent / "data" / "abuse_strings.json").read_text(encoding="utf-8")
)


def test_hostile_text_stays_data_in_the_graph(graph_client: GraphClient) -> None:
    tenant_id = f"abuse{new_id('act')[4:12].lower()}"
    runtimes = Runtimes(FalkorTenantBackend(graph_client), SystemClock())
    runtime = runtimes.create(tenant_id, "abuse")
    try:
        owner = runtime.store.create_principal(
            Principal(id=new_id("prn"), name="Dana", role=Role.OWNER)
        )
        agent = runtime.store.create_agent(
            Agent(id=new_id("agt"), name="main", kind=AgentKind.PRIMARY)
        )
        before = runtime.store.counts()
        texts = [t for t in CORPUS if t.strip() and "\x00" not in t]  # NUL is refused at the edge
        for text in texts:
            runtime.service.ingest_utterance(
                principal_id=owner.id, text=text, channel=Channel.OWNER_DIRECT
            )
            runtime.service.ingest_utterance(
                principal_id=runtime.content_principal_id or owner.id,
                text=text,
                channel=Channel.UNTRUSTED_CONTENT,
            )
        after = runtime.store.counts()
        # Exactly the utterances we added, and nothing deleted or invented by injected Cypher.
        assert after["Utterance"] == before.get("Utterance", 0) + 2 * len(texts)
        assert after["Principal"] == before["Principal"] == 2  # owner + untrusted-content
        assert after["Agent"] == before["Agent"] == 1
        assert set(after) - set(before) <= {"Utterance", "Instruction", "Scope"}
        # The graph still answers, and nothing injected gained authority.
        records = runtime.store.list_instructions()
        assert all(
            r.instruction.lineage_trust.value != "untrusted" or r.instruction.activated_at is None
            for r in records
        )
        assert runtime.store.get_agent(agent.id).id == agent.id
    finally:
        runtimes.drop(tenant_id)
