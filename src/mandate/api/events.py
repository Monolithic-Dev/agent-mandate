"""Live updates for the console, as server-sent events.

Writes reach the graph from several processes (the REST API, the MCP agent and admin
servers), so an in-process event bus would miss most of them. Instead each open stream
reads the tenant's ``ChangeMarker`` (one small query) about once a second and sends an
event when it differs from the last one:

* ``ready``: once, when the stream opens, with the current counts.
* ``decisions``: new decisions were recorded.
* ``approvals``: the set of held actions changed (``added`` lists the new ones).
* ``rules``: an instruction was added, confirmed, revoked, superseded or quarantined.
* ``unavailable``: the graph could not be read; the stream ends and the browser reconnects.

A stream lasts at most a few minutes and then ends; ``EventSource`` reconnects on its own
(``retry`` tells it how soon). A comment line keeps idle connections open through proxies.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from mandate.authority.ports import ChangeMarker
from mandate.errors import MandateError

RETRY_MS = 3000
HEARTBEAT_SECONDS = 15.0


def summary(marker: ChangeMarker) -> dict[str, Any]:
    return {
        "decisions": marker.decisions,
        "last_decision_at": marker.last_decision_at,
        "pending": list(marker.pending),
    }


def changes(old: ChangeMarker | None, new: ChangeMarker) -> list[tuple[str, dict[str, Any]]]:
    """The events that take a console from ``old`` to ``new`` (``ready`` on the first read)."""
    if old is None:
        return [("ready", summary(new))]
    found: list[tuple[str, dict[str, Any]]] = []
    if (new.decisions, new.last_decision_at) != (old.decisions, old.last_decision_at):
        found.append(
            (
                "decisions",
                {"decisions": new.decisions, "new": max(0, new.decisions - old.decisions)},
            )
        )
    if new.pending != old.pending:
        added = sorted(set(new.pending) - set(old.pending))
        found.append(("approvals", {"pending": list(new.pending), "added": added}))
    if new.rules != old.rules:
        found.append(("rules", {}))
    return found


def frame(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


async def stream(
    read_marker: Callable[[], Awaitable[ChangeMarker]],
    disconnected: Callable[[], Awaitable[bool]],
    *,
    poll_seconds: float,
    max_seconds: float,
    clock: Callable[[], float] = time.monotonic,
) -> AsyncIterator[str]:
    """Server-sent event frames until the client leaves, the graph fails or time runs out."""
    yield f"retry: {RETRY_MS}\n\n"
    started = last_sent = clock()
    previous: ChangeMarker | None = None
    while True:
        try:
            marker = await read_marker()
        except MandateError as error:
            yield frame("unavailable", {"code": error.code})
            return
        for event, data in changes(previous, marker):
            yield frame(event, data)
            last_sent = clock()
        previous = marker
        if clock() - last_sent >= HEARTBEAT_SECONDS:
            yield ": still here\n\n"
            last_sent = clock()
        if clock() - started >= max_seconds or await disconnected():
            return
        await asyncio.sleep(poll_seconds)
