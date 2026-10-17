"""Live console events: the marker diff, the stream's lifecycle, and the endpoint."""

import json
from typing import Any

from fakes.memory_backend import MemoryTenantBackend
from fastapi.testclient import TestClient

from mandate.api import events
from mandate.api.app import create_app
from mandate.authority.ports import ChangeMarker, rules_digest
from mandate.clock import FixedClock
from mandate.config import Settings
from mandate.errors import GraphUnavailable

ADMIN = "a" * 24
READER = "r" * 24
H = {"X-Mandate-Key": ADMIN}
BASE = ChangeMarker(decisions=2, last_decision_at=10, pending=("act_a",), rules="r1")


def parse(text: str) -> list[tuple[str, dict[str, Any]]]:
    found = []
    for block in text.split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in lines:
            found.append((lines["event"], json.loads(lines["data"])))
    return found


def test_the_first_read_is_ready_then_only_differences() -> None:
    assert events.changes(None, BASE) == [
        ("ready", {"decisions": 2, "last_decision_at": 10, "pending": ["act_a"]})
    ]
    assert events.changes(BASE, BASE) == []
    later = ChangeMarker(decisions=3, last_decision_at=11, pending=("act_b",), rules="r2")
    assert events.changes(BASE, later) == [
        ("decisions", {"decisions": 3, "new": 1}),
        ("approvals", {"pending": ["act_b"], "added": ["act_b"]}),
        ("rules", {}),
    ]
    resolved = ChangeMarker(decisions=2, last_decision_at=10, pending=(), rules="r1")
    assert events.changes(BASE, resolved) == [("approvals", {"pending": [], "added": []})]


def test_rules_digest_ignores_order_and_sees_state() -> None:
    a, b = ["ins_1", "active", False, "trusted"], ["ins_2", "pending", False, "trusted"]
    assert rules_digest([a, b]) == rules_digest([b, a])
    assert rules_digest([a, b]) != rules_digest([a, ["ins_2", "active", False, "trusted"]])
    assert rules_digest([[None, None, None, None]]) == rules_digest([])  # OPTIONAL MATCH nulls


async def collect(markers: list[Any], *, max_seconds: float = 100.0) -> str:
    """Run the stream over a scripted sequence of markers (or errors), with a fake clock."""
    now = [0.0]
    script = iter(markers)

    async def read() -> ChangeMarker:
        now[0] += 1.0
        item = next(script)
        if isinstance(item, Exception):
            raise item
        return item  # type: ignore[no-any-return]

    async def gone() -> bool:
        return False

    body = events.stream(read, gone, poll_seconds=0, max_seconds=max_seconds, clock=lambda: now[0])
    return "".join([chunk async for chunk in body])


async def test_a_stream_sends_changes_and_ends_when_the_graph_fails() -> None:
    pending = ChangeMarker(decisions=2, last_decision_at=10, pending=("act_a", "act_b"), rules="r1")
    text = await collect([BASE, BASE, pending, GraphUnavailable("down")])
    assert text.startswith(f"retry: {events.RETRY_MS}\n\n")
    assert [event for event, _ in parse(text)] == ["ready", "approvals", "unavailable"]
    assert parse(text)[1][1]["added"] == ["act_b"]
    assert parse(text)[2][1] == {"code": "graph_unavailable"}


async def test_a_quiet_stream_sends_heartbeats_and_ends_on_time() -> None:
    text = await collect([BASE] * 40, max_seconds=35)
    assert [event for event, _ in parse(text)] == ["ready"]
    assert text.count(": still here") == 2  # every 15 seconds of silence


def make_client() -> TestClient:
    settings = Settings(  # type: ignore[call-arg]
        mandate_api_key=ADMIN,
        mandate_api_keys=f"reader:{READER}:viewer:*",  # type: ignore[arg-type]
        _env_file=None,
    )
    app = create_app(settings, MemoryTenantBackend(), FixedClock())
    app.state.event_max_seconds = 0  # one read, then the stream ends
    return TestClient(app, raise_server_exceptions=False)


def test_the_endpoint_streams_ready_for_a_viewer_and_404s_a_stranger() -> None:
    c = make_client()
    assert c.post("/v1/tenants", json={"tenant_id": "acme", "name": "Acme"}, headers=H).is_success
    response = c.get("/v1/tenants/acme/events", headers={"X-Mandate-Key": READER})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert parse(response.text) == [
        ("ready", {"decisions": 0, "last_decision_at": None, "pending": []})
    ]
    assert c.get("/v1/tenants/nowhere/events", headers=H).status_code == 404
    assert c.get("/v1/tenants/acme/events").status_code == 401
