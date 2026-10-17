"""S5 and S6 against a real FalkorDB (small sizes; the full run is `python -m mandate.eval.*`)."""

import pytest

from mandate.api.tenancy import FalkorTenantBackend
from mandate.eval.concurrency import VARIANTS, run_variant
from mandate.eval.isolation import run_isolation, summarise
from mandate.graph.client import GraphClient

pytestmark = pytest.mark.integration


def test_isolation_has_no_leaks(graph_client: GraphClient) -> None:
    backend = FalkorTenantBackend(graph_client)

    def cleanup(tenant_id: str) -> None:
        try:
            backend.drop(tenant_id)
        except Exception:  # noqa: BLE001
            pass

    for tenant_id in ("acme", "globex", "acme_"):
        cleanup(tenant_id)
    probes = run_isolation(lambda: backend, cleanup)
    assert summarise(probes).successes == 0, [p for p in probes if p.leaked]


@pytest.mark.parametrize("variant", VARIANTS, ids=lambda v: v.name)
def test_concurrent_checks_match_the_oracle(graph_client: GraphClient, variant) -> None:  # type: ignore[no-untyped-def]
    result = run_variant(graph_client, variant, tenants=2, agents=4, operations=10)
    assert result.clean, (result.mismatches, result.errors, result.cross_tenant)
    assert result.checks > 0


def test_concurrency_stays_correct_when_the_server_queue_is_tiny(graph_client: GraphClient) -> None:
    """Regression: with the server queue at 4, unprotected clients got rejected queries."""
    execute = graph_client._db.connection.execute_command  # type: ignore[attr-defined]
    original = execute("GRAPH.CONFIG", "GET", "MAX_QUEUED_QUERIES")[1]
    execute("GRAPH.CONFIG", "SET", "MAX_QUEUED_QUERIES", 4)
    try:
        result = run_variant(graph_client, VARIANTS[1], tenants=3, agents=6, operations=12)
    finally:
        execute("GRAPH.CONFIG", "SET", "MAX_QUEUED_QUERIES", int(original))
    assert result.clean, (result.mismatches, result.errors, result.audit_gaps)
