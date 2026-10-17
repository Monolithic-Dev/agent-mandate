import re
import threading
import time

import pytest
from falkordb.node import Node
from redis.exceptions import ResponseError

from mandate.errors import GraphQueryError, GraphUnavailable, NotFound, ValidationFailure
from mandate.graph.client import (
    BUSY_RETRIES,
    QUERY_DIR,
    QUERY_NAME_RE,
    GraphClient,
    load_query,
    to_python,
    validate_graph_name,
)
from mandate.graph.mapping import (
    decision_from_props,
    delegation_from_props,
    instruction_from_props,
    scope_from_props,
)
from mandate.graph.tenants import REPLAY_MARKER, replay_graph_name, tenant_graph_name
from mandate.ids import new_id
from mandate.models.domain import Constraints, Decision, PathHop, Reason, Result

T = 1_760_500_000_000


@pytest.mark.parametrize(
    "name",
    [
        "",
        "q01",
        "Q01_x",
        "q01_UPPER",
        "q01_x; DROP",
        "../q01_x",
        "q01_x.cypher",
        "w1_short",
        "x01_a",
    ],
)
def test_load_query_rejects_bad_names(name: str) -> None:
    with pytest.raises(ValueError):
        load_query(name)


def test_load_query_unknown_name() -> None:
    with pytest.raises(ValueError):
        load_query("q99_does_not_exist")


def test_every_query_file_is_loadable_and_named_correctly() -> None:
    files = sorted(QUERY_DIR.glob("*.cypher"))
    assert len(files) >= 25
    for path in files:
        assert QUERY_NAME_RE.match(path.stem), path.name
        assert load_query(path.stem).strip()


def test_queries_use_parameters_not_inlined_values() -> None:
    # No query may embed a quoted id or number taken from user input; spot-check that the
    # only quoted literals are fixed vocabulary.
    allowed = {"pending", "active", "revoked", "superseded", "untrusted", "winner"}
    for path in QUERY_DIR.glob("*.cypher"):
        for literal in re.findall(r"'([^']*)'", path.read_text(encoding="utf-8")):
            assert literal in allowed, f"{path.name}: unexpected literal {literal!r}"


@pytest.mark.parametrize("name", ["t_acme", "mandate_registry", "t_acme__replay_abc123"])
def test_valid_graph_names(name: str) -> None:
    assert validate_graph_name(name) == name


@pytest.mark.parametrize(
    "name", ["", "T_acme", "t acme", "t-acme", "a" * 81, "t_acme;drop", "../x"]
)
def test_invalid_graph_names(name: str) -> None:
    with pytest.raises(ValueError):
        validate_graph_name(name)


def test_to_python_converts_nodes_and_nested_containers() -> None:
    node = Node(labels=["Agent"], properties={"id": "agt_1", "n": 2})
    assert to_python([node, {"x": [node]}, 5, "s", None]) == [
        {"id": "agt_1", "n": 2},
        {"x": [{"id": "agt_1", "n": 2}]},
        5,
        "s",
        None,
    ]


def test_tenant_graph_names() -> None:
    assert tenant_graph_name("acme") == "t_acme"
    for bad in ["", "Acme", "a b", "a" * 41, "acme'; DROP", "../acme", "acme-corp", "a__b"]:
        with pytest.raises(ValidationFailure):
            tenant_graph_name(bad)


def test_no_tenant_graph_can_look_like_a_replay_clone() -> None:
    # sweep_replay_graphs deletes every graph containing the marker.
    with pytest.raises(ValidationFailure):
        tenant_graph_name("acme__replay_x")
    assert REPLAY_MARKER not in tenant_graph_name("acme_replay_x")


def test_replay_graph_name_is_valid_and_marked() -> None:
    name = replay_graph_name("acme", new_id("act"))
    assert REPLAY_MARKER in name
    assert validate_graph_name(name) == name


def test_instruction_mapping_round_trip() -> None:
    props = {
        "id": new_id("ins"),
        "effect": "allow",
        "text_span": "read my email",
        "status": "active",
        "created_at": T,
        "activated_at": T,
        "valid_from": T,
        "quarantined": False,
        "lineage_trust": "trusted",
    }
    instruction = instruction_from_props(props)
    assert instruction.effect.value == "allow"
    assert instruction.revoked_at is None


def test_scope_mapping_parses_constraints() -> None:
    props = {
        "id": new_id("scp"),
        "action_type": "refund.issue",
        "resource_pattern": "*",
        "constraints": '{"max_amount":500}',
    }
    scope = scope_from_props(props)
    assert scope.constraints == Constraints(max_amount=500)
    props["constraints"] = ""
    assert scope_from_props(props).constraints == Constraints()


def test_delegation_mapping_adds_agents() -> None:
    a, b = new_id("agt"), new_id("agt")
    props = {
        "id": new_id("dlg"),
        "action_type": "email.read",
        "resource_pattern": "inbox/*",
        "constraints": "{}",
        "created_at": T,
        "valid_from": T,
    }
    delegation = delegation_from_props(props, a, b)
    assert (delegation.from_agent, delegation.to_agent) == (a, b)
    assert delegation.via_instruction is None


def test_decision_mapping_round_trip() -> None:
    decision = Decision(
        id=new_id("dec"),
        result=Result.DENY,
        reason=Reason.NO_AUTHORITY_PATH,
        as_of=T,
        at=T,
        path=[PathHop(type="Agent", id="agt_x"), PathHop(type="Note", id="n", note="why")],
        latency_ms=1.5,
    )
    props = {
        "id": decision.id,
        "result": "deny",
        "reason": "no_authority_path",
        "as_of": T,
        "at": T,
        "path_json": decision.path_json(),
        "ignored_json": decision.ignored_json(),
        "latency_ms": 1.5,
    }
    assert decision_from_props(props) == decision


def test_not_found_error_is_a_mandate_error() -> None:
    assert NotFound("x").http_status == 404


# --- backpressure and the busy retry -------------------------------------------------


class _FakeResult:
    header: list[str] = []
    result_set: list[list[object]] = []


class _ScriptedGraph:
    """Raises the scripted errors first, then succeeds; records peak concurrency."""

    def __init__(self, errors: list[Exception], pause: float = 0.0) -> None:
        self.errors = errors
        self.calls = 0
        self.read_only_calls = 0
        self.pause = pause
        self.active = 0
        self.peak = 0
        self.lock = threading.Lock()

    def ro_query(self, query: str, params: dict[str, object]) -> _FakeResult:
        self.read_only_calls += 1
        return self.query(query, params)

    def query(self, query: str, params: dict[str, object]) -> _FakeResult:
        with self.lock:
            self.calls += 1
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            if self.pause:
                time.sleep(self.pause)
            if self.errors:
                raise self.errors.pop(0)
            return _FakeResult()
        finally:
            with self.lock:
                self.active -= 1


def _client_with(graph: _ScriptedGraph, max_in_flight: int = 16) -> GraphClient:
    client = GraphClient(object(), max_in_flight)  # type: ignore[arg-type]
    client._graph = lambda name: graph  # type: ignore[method-assign,assignment]
    return client


def test_a_busy_rejection_is_retried_and_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mandate.graph.client.time.sleep", lambda s: None)
    busy = ResponseError("Max pending queries exceeded")
    graph = _ScriptedGraph([busy, busy])
    assert _client_with(graph).run_admin_text("g", "RETURN 1") == []
    assert graph.calls == 3


def test_a_persistent_busy_rejection_becomes_graph_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("mandate.graph.client.time.sleep", lambda s: None)
    graph = _ScriptedGraph([ResponseError("Max pending queries exceeded")] * 50)
    with pytest.raises(GraphUnavailable):
        _client_with(graph).run_admin_text("g", "RETURN 1")
    assert graph.calls == BUSY_RETRIES + 1


def test_other_query_errors_are_not_retried() -> None:
    graph = _ScriptedGraph([ResponseError("Invalid input")])
    with pytest.raises(GraphQueryError):
        _client_with(graph).run_admin_text("g", "RETURN 1")
    assert graph.calls == 1


def test_in_flight_queries_never_exceed_the_limit() -> None:
    graph = _ScriptedGraph([], pause=0.01)
    client = _client_with(graph, max_in_flight=3)
    threads = [
        threading.Thread(target=client.run_admin_text, args=("g", "RETURN 1")) for _ in range(20)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert graph.calls == 20 and graph.peak <= 3


def test_named_reads_use_read_only_calls_and_writes_do_not() -> None:
    graph = _ScriptedGraph([])
    client = _client_with(graph)
    client.run("g", "q05_agents_exist", {"ids": ["a"]})
    assert (graph.calls, graph.read_only_calls) == (1, 1)
    client.run("g", "w02_create_agent", {})
    assert (graph.calls, graph.read_only_calls) == (2, 1)
    client.run_admin_text("g", "RETURN 1")
    assert (graph.calls, graph.read_only_calls) == (3, 1)


def test_a_read_of_a_graph_that_does_not_exist_returns_no_rows() -> None:
    graph = _ScriptedGraph([ResponseError("Invalid graph operation on empty key")])
    assert _client_with(graph).run("g", "q09_tenant_counts") == []
    # A write to the same condition is still an error, not silently ignored.
    graph = _ScriptedGraph([ResponseError("Invalid graph operation on empty key")])
    with pytest.raises(GraphQueryError):
        _client_with(graph).run("g", "w02_create_agent", {})


def test_graph_client_records_latency_retries_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from mandate.observability import metrics

    monkeypatch.setattr("mandate.graph.client.time.sleep", lambda s: None)
    busy = metrics.value("mandate_graph_busy_retries_total")
    overloaded = metrics.value("mandate_graph_errors_total", {"kind": "overloaded"})
    rejected = metrics.value("mandate_graph_errors_total", {"kind": "rejected"})
    seen = metrics.value(
        "mandate_graph_query_seconds_count", {"query": "q05_agents_exist", "mode": "read"}
    )

    _client_with(_ScriptedGraph([ResponseError("Max pending queries exceeded")])).run(
        "g", "q05_agents_exist", {"ids": []}
    )
    assert metrics.value("mandate_graph_busy_retries_total") == busy + 1
    assert (
        metrics.value(
            "mandate_graph_query_seconds_count", {"query": "q05_agents_exist", "mode": "read"}
        )
        == seen + 1
    )

    with pytest.raises(GraphUnavailable):
        _client_with(
            _ScriptedGraph([ResponseError("Max pending queries exceeded")] * 50)
        ).run_admin_text("g", "RETURN 1")
    assert metrics.value("mandate_graph_errors_total", {"kind": "overloaded"}) == overloaded + 1

    with pytest.raises(GraphQueryError):
        _client_with(_ScriptedGraph([ResponseError("Invalid input")])).run_admin_text("g", "x")
    assert metrics.value("mandate_graph_errors_total", {"kind": "rejected"}) == rejected + 1
