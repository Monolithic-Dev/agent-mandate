"""Prometheus metrics for the gateway, the API and the graph client.

One module owns every metric name so the dashboard, the alerts and the docs agree. The
decision engine itself (`mandate.authority`) does not import this: decisions are counted
where they leave the system (the guarded call and the API), never inside the pure core.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

REGISTRY = CollectorRegistry()

# Latency buckets in seconds: a decision is a few queries, so resolve the 5 to 500 ms range.
_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)

DECISIONS = Counter(
    "mandate_decisions_total",
    "Authority decisions returned, by outcome and reason.",
    ("result", "reason", "source"),
    registry=REGISTRY,
)
DECISION_SECONDS = Histogram(
    "mandate_decision_seconds",
    "Wall time of one authority check, including persistence.",
    ("source",),
    buckets=_BUCKETS,
    registry=REGISTRY,
)
TOOL_CALLS = Counter(
    "mandate_tool_calls_total",
    "Tool calls through the guarded call, by tool and status.",
    ("tool", "status"),
    registry=REGISTRY,
)
GRAPH_QUERY_SECONDS = Histogram(
    "mandate_graph_query_seconds",
    "Wall time of one graph query, by query name and read or write.",
    ("query", "mode"),
    buckets=_BUCKETS,
    registry=REGISTRY,
)
GRAPH_ERRORS = Counter(
    "mandate_graph_errors_total",
    "Graph failures, by kind (unavailable, rejected, overloaded).",
    ("kind",),
    registry=REGISTRY,
)
GRAPH_BUSY_RETRIES = Counter(
    "mandate_graph_busy_retries_total",
    "Queries the server refused as over capacity and the client retried.",
    registry=REGISTRY,
)
HTTP_REQUESTS = Counter(
    "mandate_http_requests_total",
    "HTTP requests, by method, route template and status code.",
    ("method", "route", "status"),
    registry=REGISTRY,
)
SIGN_INS = Counter(
    "mandate_sign_ins_total",
    "Console sign-in attempts, by outcome (success, denied, limited).",
    ("outcome",),
    registry=REGISTRY,
)
AUDIT_WRITE_FAILURES = Counter(
    "mandate_audit_write_failures_total",
    "Audit events that could not be written (the request itself had already completed).",
    registry=REGISTRY,
)
HTTP_SECONDS = Histogram(
    "mandate_http_request_seconds",
    "HTTP request wall time, by route template.",
    ("route",),
    buckets=_BUCKETS,
    registry=REGISTRY,
)


def render() -> bytes:
    """The Prometheus text exposition of every metric above."""
    return generate_latest(REGISTRY)


def value(name: str, labels: dict[str, str] | None = None) -> float:
    """Current value of one sample (0 when it has never been recorded). For tests."""
    return REGISTRY.get_sample_value(name, labels or {}) or 0.0
