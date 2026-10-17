"""The demo seed on a real FalkorDB: every decision it leaves behind verifies."""

import pytest

from mandate.api.tenancy import FalkorTenantBackend, Runtimes
from mandate.authority.verify import verify_decision
from mandate.clock import SystemClock
from mandate.graph.client import GraphClient
from mandate.ids import new_id
from mandate.seed import seed_demo

pytestmark = pytest.mark.integration


def test_seed_and_reset_on_a_real_graph(graph_client: GraphClient) -> None:
    tenant = f"seed{new_id('act')[4:12].lower()}"
    runtimes = Runtimes(FalkorTenantBackend(graph_client), SystemClock())
    try:
        first = seed_demo(runtimes, tenant)
        again = seed_demo(runtimes, tenant, reset=True)
        assert again.owner_id != first.owner_id  # a genuinely fresh graph
        store = runtimes.get(tenant).store
        assert len(store.list_decisions(limit=200)) == len(again.decision_ids)
        for decision_id in again.decision_ids:
            assert verify_decision(store, decision_id).ok, decision_id
    finally:
        runtimes.drop(tenant)
