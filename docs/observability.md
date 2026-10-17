# Observability

Status: v1.0 · 2026-10-07. What the running system exposes so a problem can be found without a debugger. Adapted from the teammate's design (`friend/19_OBSERVABILITY.md`), trimmed to what exists.

## Endpoints

| Path | Auth | Meaning |
|---|---|---|
| `/healthz` | none | The process is up; reports the graph as `up` or `down` (503 when down) |
| `/readyz` | none | Ready only if the graph answers a real read (a ping and a tenant listing). 503 otherwise. Use this for container and load-balancer checks |
| `/metrics` | `X-Mandate-Key` | Prometheus text format |

Every response carries `X-Request-Id`; the same id is on the log lines for that request and in error bodies.

## Metrics

All defined in `src/mandate/observability/metrics.py` (the only place metric names live).

| Metric | Labels | Use |
|---|---|---|
| `mandate_decisions_total` | `result`, `reason`, `source` (`api` or `gateway`) | Rate of allow, confirm and deny; a rise in `check_error` means the graph is failing and the system is failing closed |
| `mandate_decision_seconds` | `source` | Decision latency including persistence |
| `mandate_tool_calls_total` | `tool`, `status` | Tool calls by `ok`, `denied`, `confirmation_required`, `error` |
| `mandate_graph_query_seconds` | `query`, `mode` | Latency per named query; find the slow one |
| `mandate_graph_errors_total` | `kind` (`unavailable`, `rejected`, `overloaded`) | `overloaded` means the server's queue was full and retries gave up |
| `mandate_graph_busy_retries_total` | none | Queries retried after "Max pending queries exceeded"; a steady rise means more clients than the server queue allows |
| `mandate_http_requests_total` | `method`, `route`, `status` | Route is the template, not the raw path, so ids never become label values |
| `mandate_http_request_seconds` | `route` | Request latency |

The authority engine itself (`mandate.authority`) does not import the metrics module (import-linter enforces it); decisions are counted where they leave the system.

## Scraping

```yaml
scrape_configs:
  - job_name: agent-mandate
    metrics_path: /metrics
    authorization: { type: Bearer, credentials: unused }   # replace with a header as below
    http_headers:
      X-Mandate-Key: { values: ["<your MANDATE_API_KEY>"] }
    static_configs: [{ targets: ["localhost:8000"] }]
```

(`http_headers` needs a recent Prometheus. Otherwise put a reverse proxy in front that adds the header, and do not expose `/metrics` publicly.)

## Alerts worth having

- `rate(mandate_graph_errors_total{kind="overloaded"}[5m]) > 0`: the database is saturated.
- `rate(mandate_decisions_total{reason="check_error"}[5m]) > 0`: checks are failing closed.
- `histogram_quantile(0.95, rate(mandate_decision_seconds_bucket[5m])) > 0.5`: slow decisions. For reference, S6 measured p95 about 0.2 s read-heavy and 1.4 to 2.8 s write-heavy under 50 simultaneous clients.
- `/readyz` failing for more than a minute.

## Logs

JSON to stdout via structlog; keys named `key`, `token`, `secret` or `password` are redacted. Decisions log `agent_id`, `action_type`, `result`, `reason`, `latency_ms` and `error_kind`; raw email bodies and utterance text are not logged.

## Not built yet

OpenTelemetry traces, per-tenant metrics (deliberately omitted: unbounded label cardinality), a dashboard, and `GRAPH.SLOWLOG` capture.
