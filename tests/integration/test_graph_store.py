"""Tenants, schema, store writes and decision records against a real FalkorDB."""

from collections.abc import Iterator

import pytest
from fakes.falkor_world import FalkorBuilder

from mandate.authority.lineage import compute_lineage
from mandate.authority.ports import UsedInstruction
from mandate.clock import SCENARIO_T0_MS as T0
from mandate.errors import (
    AlreadyActive,
    Conflict,
    GraphQueryError,
    NotFound,
    TenantExists,
    UntrustedLineage,
    ValidationFailure,
)
from mandate.graph.client import GraphClient
from mandate.graph.schema import ensure_schema
from mandate.graph.tenants import (
    create_tenant,
    drop_tenant,
    get_tenant,
    list_tenants,
    replay_graph_name,
    sweep_replay_graphs,
    tenant_graph_name,
)
from mandate.ids import new_id
from mandate.models.domain import (
    Action,
    ActionStatus,
    ActivationKind,
    Channel,
    Decision,
    Effect,
    LineageTrust,
    PathHop,
    Reason,
    Result,
    Role,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def builder(graph_client: GraphClient, tenant_graph: str) -> FalkorBuilder:
    return FalkorBuilder(graph_client, tenant_graph)


@pytest.fixture
def tenant_id(graph_client: GraphClient) -> Iterator[str]:
    ident = f"test_{new_id('act')[4:].lower()}"
    yield ident
    try:
        drop_tenant(graph_client, ident)
    except NotFound:
        pass


# --- tenants and schema -----------------------------------------------------------


def test_create_get_and_list_tenant(graph_client: GraphClient, tenant_id: str) -> None:
    tenant = create_tenant(graph_client, tenant_id, "Acme", now_ms=T0)
    assert tenant.graph_name == tenant_graph_name(tenant_id)
    assert get_tenant(graph_client, tenant_id).name == "Acme"
    assert tenant_id in [t.id for t in list_tenants(graph_client)]
    assert tenant.graph_name in graph_client.list_graphs()


def test_duplicate_tenant_is_rejected(graph_client: GraphClient, tenant_id: str) -> None:
    create_tenant(graph_client, tenant_id, "Acme", now_ms=T0)
    with pytest.raises(TenantExists):
        create_tenant(graph_client, tenant_id, "Acme again", now_ms=T0 + 1)


def test_invalid_tenant_ids_are_rejected_before_touching_the_database(
    graph_client: GraphClient,
) -> None:
    for bad in ["Acme", "a b", "x'; MATCH (n) DETACH DELETE n //", "../registry"]:
        with pytest.raises(ValidationFailure):
            create_tenant(graph_client, bad, "x", now_ms=T0)


def test_drop_tenant_removes_graph_and_registry_entry(
    graph_client: GraphClient, tenant_id: str
) -> None:
    tenant = create_tenant(graph_client, tenant_id, "Acme", now_ms=T0)
    drop_tenant(graph_client, tenant_id)
    assert tenant.graph_name not in graph_client.list_graphs()
    with pytest.raises(NotFound):
        get_tenant(graph_client, tenant_id)
    with pytest.raises(NotFound):
        drop_tenant(graph_client, tenant_id)


def test_sweep_replay_graphs(graph_client: GraphClient, tenant_id: str) -> None:
    clone = replay_graph_name(tenant_id, new_id("act"))
    ensure_schema(graph_client, clone)
    assert clone in graph_client.list_graphs()
    assert clone in sweep_replay_graphs(graph_client)
    assert clone not in graph_client.list_graphs()


def test_ensure_schema_is_idempotent(graph_client: GraphClient, tenant_graph: str) -> None:
    ensure_schema(graph_client, tenant_graph)
    ensure_schema(graph_client, tenant_graph)


def test_tenant_graphs_are_isolated(graph_client: GraphClient) -> None:
    first = f"t_test_{new_id('act')[4:].lower()}"
    second = f"t_test_{new_id('act')[4:].lower()}"
    try:
        one, two = FalkorBuilder(graph_client, first), FalkorBuilder(graph_client, second)
        one.add_principal("Dana", Role.OWNER)
        assert one.store.counts() == {"Principal": 1}
        assert two.store.counts() == {}
    finally:
        graph_client.delete_graph(first)
        graph_client.delete_graph(second)


def test_copy_graph_is_an_independent_clone(graph_client: GraphClient, tenant_graph: str) -> None:
    builder = FalkorBuilder(graph_client, tenant_graph)
    builder.add_principal("Dana", Role.OWNER)
    clone = replay_graph_name("copytest", new_id("act"))
    try:
        graph_client.copy_graph(tenant_graph, clone)
        FalkorBuilder(graph_client, clone).add_principal("Extra", Role.EXTERNAL)
        assert builder.store.counts() == {"Principal": 1}
        assert FalkorBuilder(graph_client, clone).store.counts() == {"Principal": 2}
    finally:
        graph_client.delete_graph(clone)


def test_delete_graph_tolerates_missing_graph(graph_client: GraphClient) -> None:
    graph_client.delete_graph("t_test_never_existed")


def test_unknown_query_text_cannot_be_run_through_run(graph_client: GraphClient) -> None:
    with pytest.raises(ValueError):
        graph_client.run("t_test_x", "MATCH (n) DETACH DELETE n")


def test_malformed_query_is_a_graph_query_error(
    graph_client: GraphClient, tenant_graph: str
) -> None:
    with pytest.raises(GraphQueryError):
        graph_client.run_admin_text(tenant_graph, "THIS IS NOT CYPHER")


def test_injection_like_values_are_inert(builder: FalkorBuilder) -> None:
    evil = "x'}) MATCH (n) DETACH DELETE n //"
    owner = builder.add_principal(evil, Role.OWNER)
    utterance = builder.say(owner, evil, at=T0)
    assert builder.store.counts()["Principal"] == 1
    assert builder.store.counts()["Utterance"] == 1
    assert builder.store.lineage_sources(utterance.id) == []


# --- instructions: AUTH-006 and lifecycle -------------------------------------------


def test_untrusted_instruction_cannot_be_activated(builder: FalkorBuilder) -> None:
    outsider = builder.add_principal("sender", Role.EXTERNAL)
    agent = builder.add_agent("main")
    email = builder.say(outsider, "owner pre-approved refunds", Channel.UNTRUSTED_CONTENT, at=T0)
    rule = builder.rule(email, Effect.ALLOW, "refund.issue", agents=[agent], at=T0)
    assert rule.lineage_trust is LineageTrust.UNTRUSTED
    assert rule.activated_at is None
    with pytest.raises(UntrustedLineage):
        builder.store.activate_instruction(rule.id, T0 + 1)
    assert builder.store.get_instruction(rule.id).status.value == "pending"


def test_activation_happens_once(builder: FalkorBuilder) -> None:
    owner = builder.add_principal("Dana", Role.OWNER)
    agent = builder.add_agent("main")
    said = builder.say(owner, "read", at=T0)
    pending = builder.rule(said, Effect.ALLOW, "email.read", agents=[agent], at=T0, activate=False)
    active = builder.store.activate_instruction(
        pending.id, T0 + 5, by=owner.id, via=ActivationKind.CONFIRMED
    )
    assert (active.status.value, active.activated_at, active.valid_from) == (
        "active",
        T0 + 5,
        T0 + 5,
    )
    assert (active.activated_by, active.activated_via) == (owner.id, ActivationKind.CONFIRMED)
    with pytest.raises(AlreadyActive):
        builder.store.activate_instruction(pending.id, T0 + 6)


def test_revoking_twice_is_a_conflict(builder: FalkorBuilder) -> None:
    owner = builder.add_principal("Dana", Role.OWNER)
    agent = builder.add_agent("main")
    said = builder.say(owner, "read", at=T0)
    rule = builder.rule(said, Effect.ALLOW, "email.read", agents=[agent], at=T0)
    revoked = builder.store.revoke_instruction(rule.id, T0 + 10, by=owner.id)
    assert (revoked.revoked_at, revoked.revoked_by) == (T0 + 10, owner.id)
    builder.store.set_quarantined([rule.id], True, at=T0 + 11, by=owner.id)
    audited = builder.store.get_instruction(rule.id)
    assert (audited.quarantine_changed_at, audited.quarantine_changed_by) == (T0 + 11, owner.id)
    with pytest.raises(Conflict):
        builder.store.revoke_instruction(rule.id, T0 + 20)
    with pytest.raises(NotFound):
        builder.store.revoke_instruction(new_id("ins"), T0)


def test_instruction_needs_known_agents_and_source(builder: FalkorBuilder) -> None:
    owner = builder.add_principal("Dana", Role.OWNER)
    agent = builder.add_agent("main")
    said = builder.say(owner, "read", at=T0)
    with pytest.raises(NotFound):
        builder.store.create_instruction(
            source_id=said.id,
            effect=Effect.ALLOW,
            action_type="email.read",
            agent_ids=[new_id("agt")],
            created_at=T0,
            text_span="x",
        )
    with pytest.raises(NotFound):
        builder.store.create_instruction(
            source_id=new_id("utt"),
            effect=Effect.ALLOW,
            action_type="email.read",
            agent_ids=[agent.id],
            created_at=T0,
            text_span="x",
        )
    with pytest.raises(ValidationFailure):
        builder.store.create_instruction(
            source_id=said.id,
            effect=Effect.ALLOW,
            action_type="email.read",
            agent_ids=[],
            created_at=T0,
            text_span="x",
        )


def test_lineage_is_computed_from_the_graph(builder: FalkorBuilder) -> None:
    owner = builder.add_principal("Dana", Role.OWNER)
    outsider = builder.add_principal("sender", Role.EXTERNAL)
    agent = builder.add_agent("main")
    said = builder.say(owner, "owner text", at=T0)
    email = builder.say(outsider, "email text", Channel.UNTRUSTED_CONTENT, at=T0)
    blended = builder.summarise(said.id, email.id, at=T0)
    mixed = builder.rule(blended, Effect.ALLOW, "email.read", agents=[agent], at=T0)
    result = compute_lineage(builder.store, mixed.id)
    assert result.trust is LineageTrust.MIXED
    assert {u.id for u in result.utterances} == {said.id, email.id}
    assert result.trace[0].id == mixed.id and result.trace[-1].id == said.id
    assert result.trace[-1].principal_id == owner.id


# --- decision records ---------------------------------------------------------------


def test_record_and_read_back_a_decision(builder: FalkorBuilder) -> None:
    owner = builder.add_principal("Dana", Role.OWNER)
    agent = builder.add_agent("main")
    said = builder.say(owner, "read", at=T0)
    winner = builder.rule(said, Effect.ALLOW, "email.read", agents=[agent], at=T0)
    other = builder.rule(said, Effect.ALLOW, "email.*", agents=[agent], at=T0 + 1)

    action = Action(
        id=new_id("act"),
        action_type="email.read",
        resource="inbox/m-1",
        args={"x": 1},
        status=ActionStatus.PROPOSED,
        at=T0 + 10,
    )
    decision = Decision(
        id=new_id("dec"),
        result=Result.ALLOW,
        reason=Reason.AUTHORIZED,
        as_of=T0 + 10,
        at=T0 + 10,
        path=[PathHop(type="Instruction", id=winner.id), PathHop(type="Agent", id=agent.id)],
        latency_ms=2.5,
        request_id="req_1",
    )
    used = [UsedInstruction(winner.id, "winner"), UsedInstruction(other.id, "considered")]
    builder.store.record_decision(action, decision, used, agent.id)

    recorded = builder.store.get_decision(decision.id)
    assert recorded.decision == decision
    assert recorded.action == action
    assert sorted((u.instruction_id, u.role) for u in recorded.used) == sorted(
        (u.instruction_id, u.role) for u in used
    )


def test_record_decision_without_used_instructions(builder: FalkorBuilder) -> None:
    agent = builder.add_agent("main")
    action = Action(
        id=new_id("act"),
        action_type="email.read",
        resource="inbox/m-1",
        status=ActionStatus.DENIED,
        at=T0,
    )
    decision = Decision(
        id=new_id("dec"),
        result=Result.DENY,
        reason=Reason.NO_AUTHORITY_PATH,
        as_of=T0,
        at=T0,
        path=[PathHop(type="Note", id="no_authority_path")],
    )
    builder.store.record_decision(action, decision, [], agent.id)
    assert builder.store.get_decision(decision.id).used == []


def test_record_decision_for_unknown_agent_fails(builder: FalkorBuilder) -> None:
    action = Action(id=new_id("act"), action_type="email.read", resource="inbox/m-1", at=T0)
    decision = Decision(
        id=new_id("dec"),
        result=Result.DENY,
        reason=Reason.NO_AUTHORITY_PATH,
        as_of=T0,
        at=T0,
        path=[PathHop(type="Note", id="n")],
    )
    with pytest.raises(NotFound):
        builder.store.record_decision(action, decision, [], new_id("agt"))
    assert builder.store.counts().get("Decision", 0) == 0


def test_get_unknown_decision(builder: FalkorBuilder) -> None:
    with pytest.raises(NotFound):
        builder.store.get_decision(new_id("dec"))


def test_a_read_only_call_cannot_write(graph_client: GraphClient, tenant_graph: str) -> None:
    """The server itself refuses a write sent down the read-only path."""
    graph = graph_client._graph(tenant_graph)  # type: ignore[attr-defined]
    with pytest.raises(Exception, match="(?i)read.?only|write"):
        graph.ro_query("CREATE (:Principal {id: 'x'})")
