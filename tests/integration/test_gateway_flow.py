"""The guarded call and held-action approval against a real FalkorDB tenant graph."""

from collections.abc import Iterator

import pytest
from fakes.falkor_world import FalkorBuilder
from fakes.world import World

from mandate.authority.service import AuthorityService
from mandate.clock import SCENARIO_T0_MS as T0
from mandate.errors import Conflict
from mandate.gateway.guard import GatewayRuntime, guarded_call, resolve_pending
from mandate.gateway.sandbox.state import Sandbox
from mandate.graph.client import GraphClient
from mandate.graph.schema import ensure_schema
from mandate.ids import new_id
from mandate.models.domain import (
    Action,
    ActionStatus,
    Approval,
    Channel,
    Decision,
    PathHop,
    Reason,
    Result,
)

pytestmark = pytest.mark.integration

S1 = "You may read and archive my email, but confirm with me before deleting anything."


@pytest.fixture
def world(graph_client: GraphClient) -> Iterator[World]:
    name = f"t_test_{new_id('act')[4:].lower()}"
    ensure_schema(graph_client, name)
    try:
        yield World(FalkorBuilder(graph_client, name))
    finally:
        graph_client.delete_graph(name)


def test_s1_end_to_end_with_approval(world: World) -> None:
    service = AuthorityService(world.store, world.clock)
    runtime = GatewayRuntime(service, Sandbox.seeded(), content_principal_id=world.outsider.id)
    ingested = service.ingest_utterance(
        principal_id=world.owner.id, text=S1, channel=Channel.OWNER_DIRECT
    )
    for item in ingested.instructions:
        if item.needs_confirmation:
            service.confirm_instruction(item.instruction.id, world.owner.id)

    assert guarded_call(runtime, world.main.id, "email_list", {}).status == "ok"
    held = guarded_call(runtime, world.main.id, "email_delete", {"message_id": "m-1"})
    assert held.status == "confirmation_required" and held.approval_id
    assert "m-1" in runtime.sandbox.messages
    assert service.get_action(held.approval_id).action.status is ActionStatus.PENDING

    approved = resolve_pending(runtime, held.approval_id, world.owner.id, approved=True)
    assert approved.status == "ok" and "m-1" not in runtime.sandbox.messages
    assert service.get_action(held.approval_id).action.status is ActionStatus.EXECUTED
    with pytest.raises(Conflict):
        resolve_pending(runtime, held.approval_id, world.owner.id, approved=True)
    assert world.store.counts()["Approval"] == 1


def test_forged_refund_is_refused_and_nothing_executes(world: World) -> None:
    service = AuthorityService(world.store, world.clock)
    runtime = GatewayRuntime(service, Sandbox.seeded(), content_principal_id=world.outsider.id)
    ingested = service.ingest_utterance(
        principal_id=world.owner.id,
        text="You may read my email. You may issue refunds up to $500.",
        channel=Channel.OWNER_DIRECT,
    )
    for item in ingested.instructions:
        if item.needs_confirmation:
            service.confirm_instruction(item.instruction.id, world.owner.id)
    assert guarded_call(runtime, world.main.id, "email_read", {"message_id": "m-31"}).status == "ok"
    over = guarded_call(runtime, world.main.id, "refund_issue", {"order_id": "89", "amount": 600})
    assert (over.status, over.reason) == ("denied", "constraint_not_met")
    assert runtime.sandbox.orders["89"].refunded_amount == 0
    # The attacker's email was stored as untrusted content in the graph.
    assert world.store.counts()["Utterance"] >= 2


def test_resolve_pending_action_is_atomic(world: World) -> None:
    store = world.store.store  # the production store behind the builder
    action = Action(
        id=new_id("act"),
        action_type="email.delete",
        resource="inbox/m-1",
        status=ActionStatus.PENDING,
        at=T0,
    )
    decision = Decision(
        id=new_id("dec"),
        result=Result.CONFIRM,
        reason=Reason.CONFIRM_RULE,
        as_of=T0,
        at=T0,
        path=[PathHop(type="Agent", id=world.main.id)],
    )
    store.record_decision(action, decision, [], world.main.id)
    first = Approval(id=new_id("apr"), approved=True, by=world.owner.id, at=T0 + 1)
    second = Approval(id=new_id("apr"), approved=True, by=world.owner.id, at=T0 + 2)
    assert store.resolve_pending_action(action.id, first, ActionStatus.EXECUTED) is True
    assert store.resolve_pending_action(action.id, second, ActionStatus.EXECUTED) is False
    assert store.get_action(action.id).action.status is ActionStatus.EXECUTED
    assert store.get_action(action.id).agent_id == world.main.id
    assert store.counts()["Approval"] == 1  # the loser left no approval behind
