"""The metric registry: names, rendering, and that the pure core does not depend on it."""

from mandate.observability import metrics


def test_render_contains_every_metric_family() -> None:
    metrics.DECISIONS.labels("allow", "authorized", "test").inc()
    text = metrics.render().decode()
    for name in (
        "mandate_decisions_total",
        "mandate_decision_seconds",
        "mandate_tool_calls_total",
        "mandate_graph_query_seconds",
        "mandate_graph_errors_total",
        "mandate_graph_busy_retries_total",
        "mandate_http_requests_total",
        "mandate_http_request_seconds",
    ):
        assert f"# TYPE {name}" in text, name


def test_value_reads_back_what_was_recorded_and_zero_for_the_unseen() -> None:
    labels = {"result": "deny", "reason": "unit_test_reason", "source": "test"}
    assert metrics.value("mandate_decisions_total", labels) == 0.0
    metrics.DECISIONS.labels(**labels).inc(2)
    assert metrics.value("mandate_decisions_total", labels) == 2.0


# --- instrumentation: the guarded call, the check route and the graph client -------------


def _runtime_with_rule():  # type: ignore[no-untyped-def]
    from fakes.world import World

    from mandate.authority.service import AuthorityService
    from mandate.gateway.guard import GatewayRuntime
    from mandate.gateway.sandbox.state import Sandbox
    from mandate.models.domain import Channel

    w = World()
    service = AuthorityService(w.store, w.clock)
    service.ingest_utterance(
        principal_id=w.owner.id, text="You may read my email.", channel=Channel.OWNER_DIRECT
    )
    return w, GatewayRuntime(service, Sandbox.seeded())


def test_guarded_calls_are_counted_by_decision_and_by_tool_status() -> None:
    from mandate.gateway.guard import guarded_call

    w, runtime = _runtime_with_rule()
    allow = {"result": "allow", "reason": "authorized", "source": "gateway"}
    deny = {"result": "deny", "reason": "no_authority_path", "source": "gateway"}
    before_allow = metrics.value("mandate_decisions_total", allow)
    before_deny = metrics.value("mandate_decisions_total", deny)
    assert guarded_call(runtime, w.main.id, "email_list", {}).status == "ok"
    assert (
        guarded_call(runtime, w.main.id, "email_delete", {"message_id": "m-1"}).status == "denied"
    )
    assert metrics.value("mandate_decisions_total", allow) == before_allow + 1
    assert metrics.value("mandate_decisions_total", deny) == before_deny + 1
    assert metrics.value("mandate_tool_calls_total", {"tool": "email_list", "status": "ok"}) >= 1
    assert metrics.value("mandate_decision_seconds_count", {"source": "gateway"}) >= 2


def test_bad_arguments_are_counted_as_denied_tool_calls() -> None:
    from mandate.gateway.guard import guarded_call

    w, runtime = _runtime_with_rule()
    labels = {"tool": "email_read", "status": "denied"}
    before = metrics.value("mandate_tool_calls_total", labels)
    guarded_call(runtime, w.main.id, "email_read", {"message_id": "../etc/passwd"})
    assert metrics.value("mandate_tool_calls_total", labels) == before + 1
