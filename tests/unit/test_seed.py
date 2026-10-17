"""The demo seed builds the story the demo tells, deterministically, on any backend."""

import pytest
from fakes.memory_backend import MemoryTenantBackend

from mandate.api.tenancy import Runtimes
from mandate.authority.verify import verify_decision
from mandate.clock import SystemClock
from mandate.errors import TenantExists
from mandate.lineage.blast_radius import blast_radius
from mandate.lineage.reliance import rank_reliance
from mandate.mcp_servers.identity import verify_agent_token
from mandate.models.domain import ActionStatus
from mandate.seed import DEMO_TENANT, seed_demo


@pytest.fixture
def runtimes() -> Runtimes:
    return Runtimes(MemoryTenantBackend(), SystemClock())


def test_seed_builds_the_story(runtimes: Runtimes) -> None:
    result = seed_demo(runtimes, token_secret="s" * 24)
    rt = runtimes.get(DEMO_TENANT)
    store = rt.store

    results = {d.decision.id: d.decision.result.value for d in store.list_decisions(limit=200)}
    assert len(result.decision_ids) >= 12
    assert {"allow", "deny", "confirm"} <= set(results.values())

    # A delete is waiting for the owner, another was approved and ran.
    pending = [a.action.id for a in store.list_actions(status=ActionStatus.PENDING, limit=50)]
    assert result.held_action_id in pending
    assert "m-5" not in rt.gateway.sandbox.messages  # approved delete took effect
    assert "m-6" in rt.gateway.sandbox.messages  # the held one did not

    # The injected email executed nothing.
    assert rt.gateway.sandbox.sent == []

    # The typo rule is the heavily relied-on one, and blast radius finds its refunds.
    radius = blast_radius(store, result.typo_rule_id)
    assert len(radius.decisions) >= 3
    top = rank_reliance(store, limit=10)
    assert result.typo_rule_id in {row.instruction_id for row in top}

    token = verify_agent_token(["s" * 24], result.agent_token)
    assert token is not None and token.agent_id == result.assistant_id


def test_every_seeded_explanation_verifies(runtimes: Runtimes) -> None:
    result = seed_demo(runtimes)
    store = runtimes.get(DEMO_TENANT).store
    assert result.decision_ids
    for decision_id in result.decision_ids:
        assert verify_decision(store, decision_id).ok, decision_id


def test_seeding_twice_needs_reset(runtimes: Runtimes) -> None:
    seed_demo(runtimes)
    with pytest.raises(TenantExists):
        seed_demo(runtimes)
    again = seed_demo(runtimes, reset=True)
    assert runtimes.get(DEMO_TENANT).store.list_decisions(limit=200)
    assert again.tenant_id == DEMO_TENANT


def test_reset_on_an_absent_tenant_just_seeds(runtimes: Runtimes) -> None:
    assert seed_demo(runtimes, "fresh", reset=True).tenant_id == "fresh"


def test_the_story_is_the_same_every_time(runtimes: Runtimes) -> None:
    def shape(tenant: str) -> list[tuple[str, str]]:
        seed_demo(runtimes, tenant)
        rows = runtimes.get(tenant).store.list_decisions(limit=200)
        # Many decisions share a millisecond, so compare what happened, not the order of ids.
        return sorted((r.action.action_type, r.decision.result.value) for r in rows)

    assert shape("one") == shape("two")
