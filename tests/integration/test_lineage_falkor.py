"""Blast radius, quarantine and replay against a real FalkorDB (AUTH-027)."""

from collections.abc import Iterator

import pytest
from fakes.falkor_world import FalkorBuilder
from fakes.world import World

from mandate.clock import SCENARIO_T0_MS as T0
from mandate.graph.client import GraphClient
from mandate.graph.schema import ensure_schema
from mandate.graph.tenants import REPLAY_MARKER
from mandate.ids import new_id
from mandate.lineage.blast_radius import blast_radius, quarantine
from mandate.lineage.replay import replay_without
from mandate.models.domain import Effect, Reason, Result

pytestmark = pytest.mark.integration

REFUNDS = [("80", 1200), ("81", 2500), ("82", 4800), ("83", 300)]


@pytest.fixture
def world(graph_client: GraphClient) -> Iterator[World]:
    name = f"t_test_{new_id('act')[4:].lower()}"
    ensure_schema(graph_client, name)
    try:
        yield World(FalkorBuilder(graph_client, name))
    finally:
        graph_client.delete_graph(name)


def s4(w: World):  # type: ignore[no-untyped-def]
    ok_said = w.store.say(w.owner, "limit 500", at=T0)
    ok = w.store.rule(ok_said, Effect.ALLOW, "refund.issue", agents=[w.main], at=T0, max_amount=500)
    bad_said = w.store.say(w.owner, "limit 5000", at=T0 + 100_000)
    mistake = w.store.rule(
        bad_said, Effect.ALLOW, "refund.issue", agents=[w.main], at=T0 + 100_000, max_amount=5000
    )
    w.store.supersede(mistake, ok, at=T0 + 100_000)
    ids = []
    for index, (order, amount) in enumerate(REFUNDS):
        checked = w.check(
            "refund.issue", f"order/{order}", {"amount": amount}, as_of=T0 + 101_000 + index
        )
        assert checked.decision.result is Result.ALLOW
        ids.append(checked.decision.id)
    return mistake, ids


def test_s4_blast_radius_and_replay(world: World) -> None:
    mistake, ids = s4(world)
    radius = blast_radius(world.store.store, mistake.id)
    assert [d.decision_id for d in radius.decisions] == ids

    result = replay_without(world.store.store, world.clock, mistake.id)
    assert result.evaluated == 4 and result.unchanged == 1
    assert {c.decision_id for c in result.changes} == set(ids[:3])
    assert all(c.now_reason is Reason.CONSTRAINT_NOT_MET for c in result.changes)


def test_auth027_live_graph_unchanged(world: World) -> None:
    mistake, _ids = s4(world)
    store = world.store.store
    before = store.counts()
    replay_without(store, world.clock, mistake.id)
    assert store.counts() == before
    assert not store.get_instruction(mistake.id).quarantined


def test_auth027_clone_deleted(world: World, graph_client: GraphClient) -> None:
    mistake, _ids = s4(world)
    store = world.store.store
    leftovers_before = [g for g in graph_client.list_graphs() if REPLAY_MARKER in g]
    replay_without(store, world.clock, mistake.id)
    assert [g for g in graph_client.list_graphs() if REPLAY_MARKER in g] == leftovers_before


def test_auth027_clone_deleted_even_when_the_replay_fails(
    world: World, graph_client: GraphClient
) -> None:
    mistake, _ids = s4(world)
    store = world.store.store
    leftovers_before = [g for g in graph_client.list_graphs() if REPLAY_MARKER in g]
    with pytest.raises(RuntimeError), store.clone_for_replay() as clone:
        clone.set_quarantined([mistake.id], True)
        raise RuntimeError("boom")
    assert [g for g in graph_client.list_graphs() if REPLAY_MARKER in g] == leftovers_before


def test_derived_rules_are_traced_and_quarantined_in_the_graph(world: World) -> None:
    said = world.store.say(world.owner, "allow deleting files", at=T0)
    root = world.store.rule(said, Effect.ALLOW, "file.delete", agents=[world.main], at=T0)
    summary = world.store.summarise(root.id, at=T0 + 1)
    child = world.store.rule(summary, Effect.ALLOW, "file.write", agents=[world.main], at=T0 + 2)
    store = world.store.store
    radius = blast_radius(store, root.id)
    assert radius.summaries == [summary.id] and radius.derived_instructions == [child.id]
    assert set(quarantine(store, root.id)) == {root.id, child.id}
    denied = world.check("file.write", "files/a", as_of=T0 + 10, persist=False).decision
    assert denied.result is Result.DENY
    quarantine(store, root.id, value=False)
    allowed = world.check("file.write", "files/a", as_of=T0 + 10, persist=False).decision
    assert allowed.result is Result.ALLOW
