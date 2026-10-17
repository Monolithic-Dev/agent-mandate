"""Fixtures for tests that need a running FalkorDB.

Locally the tests skip when the database is unreachable. In CI set REQUIRE_FALKORDB=1 so a
missing database is a failure, not a silent skip.
"""

import os
from collections.abc import Iterator

import pytest

from mandate.config import Settings
from mandate.graph.client import GraphClient
from mandate.graph.schema import ensure_schema
from mandate.ids import new_id

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def graph_client() -> GraphClient:
    client = GraphClient.from_settings(Settings())
    if not client.ping():
        message = "FalkorDB is not reachable (start it with scripts/dev.ps1 up)"
        if os.environ.get("REQUIRE_FALKORDB"):
            pytest.fail(message)
        pytest.skip(message)
    return client


@pytest.fixture
def tenant_graph(graph_client: GraphClient) -> Iterator[str]:
    name = f"t_test_{new_id('act')[4:].lower()}"
    ensure_schema(graph_client, name)
    yield name
    graph_client.delete_graph(name)
