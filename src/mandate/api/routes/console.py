"""What the web console needs beyond the core API: the graph, scenario runs, the latest
evaluation and a demo reset (docs/ux-flows.md)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from mandate.api import events
from mandate.api.graph_view import to_elements
from mandate.api.routes.tenants import runtimes_of
from mandate.api.security import require_caller
from mandate.authority.ports import AuthorityStore
from mandate.errors import NotFound, ValidationFailure
from mandate.eval.runner import KINDS, run_scenario
from mandate.eval.scenario import Scenario, load_scenarios
from mandate.eval.timeline import build_timeline
from mandate.ids import new_id
from mandate.lineage.activity import MAX_ROWS, summarise, window
from mandate.models.api import (
    EvalOut,
    GraphOut,
    RunIn,
    RunKindOut,
    RunOut,
    ScenarioOut,
    TimelineEntryOut,
)
from mandate.seed import seed_demo

MAX_GRAPH_NODES = 2000

tenant_router = APIRouter(
    prefix="/v1/tenants/{tenant_id}", tags=["console"], dependencies=[Depends(require_caller)]
)
router = APIRouter(prefix="/v1", tags=["console"], dependencies=[Depends(require_caller)])


@lru_cache(maxsize=1)
def _scenarios() -> dict[str, Scenario]:
    return {s.id: s for s in load_scenarios()}


@tenant_router.get("/events")
def live_events(tenant_id: str, request: Request) -> StreamingResponse:
    """Server-sent events when the tenant's decisions, held actions or rules change."""
    store = runtimes_of(request).require(tenant_id).store  # 404 before the stream opens
    state = request.app.state
    body = events.stream(
        lambda: run_in_threadpool(store.change_marker),
        request.is_disconnected,
        poll_seconds=state.event_poll_seconds,
        max_seconds=state.event_max_seconds,
    )
    return StreamingResponse(
        body,
        media_type="text/event-stream",
        # No caching, and tell nginx-style proxies not to buffer the stream.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@tenant_router.get("/activity")
def activity(tenant_id: str, request: Request, hours: int = 24) -> dict[str, Any]:
    """Decisions over the last ``hours`` (1 to 168): per bucket by result, the most common
    reasons, actions and agents, and how long checks took."""
    if not 1 <= hours <= 168:
        raise ValidationFailure("hours: must be 1 to 168")
    runtimes = runtimes_of(request)
    runtime = runtimes.require(tenant_id)
    now = runtimes.clock.now_ms()
    since, _until, _size = window(now, hours)
    rows = runtime.store.decision_activity(since, MAX_ROWS + 1)
    result = summarise(rows[:MAX_ROWS], now=now, hours=hours, truncated=len(rows) > MAX_ROWS)
    return asdict(result)


@tenant_router.get("/graph", response_model=GraphOut)
def graph(
    tenant_id: str, request: Request, limit: int = 500, highlight: str | None = None
) -> GraphOut:
    """The tenant's graph as Cytoscape elements; ``highlight`` marks a decision's path."""
    runtime = runtimes_of(request).require(tenant_id)
    marked: set[str] = set()
    if highlight:
        recorded = runtime.store.get_decision(highlight)  # NotFound for a stranger
        marked = {highlight, recorded.action.id, recorded.agent_id}
        marked |= {hop.id for hop in recorded.decision.path if hop.type != "Note"}
    snapshot = runtime.store.graph_snapshot(max(1, min(limit, MAX_GRAPH_NODES)))
    return to_elements(snapshot, marked)


@router.get("/scenarios", response_model=list[ScenarioOut])
def scenarios() -> list[ScenarioOut]:
    return [
        ScenarioOut(
            id=s.id,
            family=s.family,
            description=s.description,
            events=len(s.timeline),
            attempts=len(s.attempts()),
        )
        for s in _scenarios().values()
    ]


@contextmanager
def _no_store() -> Iterator[AuthorityStore]:
    raise RuntimeError("baselines keep no store")
    yield  # pragma: no cover


@router.post("/runs", status_code=201, response_model=RunOut)
def create_run(body: RunIn, request: Request) -> RunOut:
    """Play one scenario for each requested agent kind, as the evaluation does.

    Agent Mandate plays in a fresh tenant that is kept, so every decision in the run can
    be explained, verified and drawn. Baselines play in memory. The run is deterministic
    and fast, so the whole timeline is returned at once; the console paces it for display.
    """
    scenario = _scenarios().get(body.scenario_id)
    if scenario is None:
        raise NotFound("no such scenario")
    unknown = sorted(set(body.kinds) - set(KINDS))
    if unknown:
        raise ValidationFailure(f"unknown agent kinds: {unknown}; use {list(KINDS)}")

    tenant_id: str | None = None
    runs: list[RunKindOut] = []
    for kind in dict.fromkeys(body.kinds):
        if kind == "mandate":
            tenant_id = f"run_{new_id('act')[4:16].lower()}"
            store = runtimes_of(request).create(tenant_id, f"Run of {scenario.id}").store

            @contextmanager
            def provide(store: AuthorityStore = store) -> Iterator[AuthorityStore]:
                yield store

            result = run_scenario(scenario, kind, provide)
        else:
            result = run_scenario(scenario, kind, _no_store)
        timeline = [TimelineEntryOut(**asdict(e)) for e in build_timeline(scenario, result)]
        runs.append(
            RunKindOut(
                kind=kind,
                timeline=timeline,
                unauthorised=sum(p.unauthorised for p in result.probes),
                false_blocks=sum(p.false_block for p in result.probes),
                held=sum(p.held for p in result.probes),
                attempts=len(result.probes),
            )
        )
    return RunOut(
        scenario_id=scenario.id,
        description=scenario.description,
        tenant_id=tenant_id,
        runs=runs,
    )


@router.get("/eval/latest", response_model=EvalOut)
def latest_eval(request: Request) -> EvalOut:
    """The newest evaluation under the results folder (folders are named by date)."""
    directory: Path = request.app.state.results_dir
    found = sorted(directory.glob("*/metrics.json"), key=lambda p: p.parent.name)
    if not found:
        raise NotFound("no evaluation results; run python -m mandate.eval")
    metrics_path = found[-1]

    metrics: dict[str, Any] = json.loads(metrics_path.read_text(encoding="utf-8"))
    report_path = metrics_path.parent / "report.md"
    report = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    return EvalOut(name=metrics_path.parent.name, metrics=metrics, report=report)


@router.post("/demo/reset")
def reset_demo(request: Request) -> dict[str, Any]:
    """Drop and re-seed the demo tenant (``python -m mandate.seed --reset``)."""
    result = asdict(seed_demo(runtimes_of(request), reset=True))
    result.pop("agent_token", None)
    return result
