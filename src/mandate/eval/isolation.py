"""S5: tenant isolation. Can a caller acting in one tenant reach another tenant's data?

Every probe goes through the REST API, the way a real client would. A probe *leaks* if it
succeeds, or returns something that names a foreign object, where "not found" was the only
acceptable answer. Run with ``python -m mandate.eval.isolation``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi.testclient import TestClient

from mandate.api.app import create_app
from mandate.api.tenancy import FalkorTenantBackend, TenantBackend
from mandate.clock import SystemClock
from mandate.config import Settings
from mandate.eval.metrics import Rate
from mandate.graph.client import GraphClient
from mandate.logging import configure_logging

KEY = "isolation-probe-key-0123456789"
HEADERS = {"X-Mandate-Key": KEY}
RULE = "You may read my email, but confirm with me before deleting anything."
VARIANTS = (
    ("v1_distinct_rules", "acme", "globex", False),
    ("v2_identical_rules", "acme", "globex", True),
    ("v3_ids_differ_by_one_character", "acme", "acme_", True),
)


@dataclass(frozen=True)
class IsolationProbe:
    variant: str
    name: str
    leaked: bool
    detail: str


class Org:
    """One tenant seeded through the API: owner, agent, a rule, a decision, a held action."""

    def __init__(self, client: TestClient, tenant_id: str, rule_text: str) -> None:
        self.client = client
        self.id = tenant_id
        made = client.post(
            "/v1/tenants", json={"tenant_id": tenant_id, "name": tenant_id}, headers=HEADERS
        )
        assert made.status_code == 201, made.text
        self.owner = self.post("/principals", {"name": "owner", "role": "owner"}).json()["id"]
        self.agent = self.post("/agents", {"name": "main", "kind": "primary"}).json()["id"]
        said = self.post(
            "/utterances",
            {"principal_id": self.owner, "text": rule_text, "channel": "owner_direct"},
        ).json()
        self.instructions = [i["instruction"]["id"] for i in said["instructions"]]
        for item in said["instructions"]:
            if item["needs_confirmation"]:
                self.post(f"/instructions/{item['instruction']['id']}/confirm", {"by": self.owner})
        checked = self.post(
            "/check",
            {"agent_id": self.agent, "action_type": "email.read", "resource": "inbox/m-1"},
        ).json()
        self.decision = checked["decision_id"]
        held = self.post(
            "/tool-calls",
            {"agent_id": self.agent, "tool": "email_delete", "args": {"message_id": "m-1"}},
        ).json()
        self.action = held.get("approval_id", "")

    def post(self, suffix: str, body: dict[str, Any]) -> Any:
        return self.client.post(f"/v1/tenants/{self.id}{suffix}", json=body, headers=HEADERS)

    def get(self, suffix: str) -> Any:
        return self.client.get(f"/v1/tenants/{self.id}{suffix}", headers=HEADERS)

    @property
    def foreign_ids(self) -> set[str]:
        return {self.owner, self.agent, self.decision, self.action, *self.instructions}


def _is_not_found(response: Any) -> bool:
    return bool(response.status_code == 404)


def run_variant(
    client: TestClient, name: str, victim_id: str, attacker_id: str, same_rules: bool
) -> list[IsolationProbe]:
    victim = Org(client, victim_id, RULE)
    attacker = Org(client, attacker_id, RULE if same_rules else "Never delete any email.")
    probes: list[IsolationProbe] = []

    def record(label: str, leaked: bool, detail: str) -> None:
        probes.append(IsolationProbe(name, label, leaked, detail))

    def expect_not_found(label: str, response: Any) -> None:
        record(label, not _is_not_found(response), f"status {response.status_code}")

    ghost = "agt_" + "0" * 26
    expect_not_found(
        "check with the victim's agent id",
        attacker.post(
            "/check",
            {"agent_id": victim.agent, "action_type": "email.read", "resource": "inbox/m-1"},
        ),
    )
    ghost_response = attacker.post(
        "/check", {"agent_id": ghost, "action_type": "email.read", "resource": "inbox/m-1"}
    )
    foreign_response = attacker.post(
        "/check",
        {"agent_id": victim.agent, "action_type": "email.read", "resource": "inbox/m-1"},
    )
    record(
        "a foreign id is indistinguishable from a missing one",
        ghost_response.status_code != foreign_response.status_code
        or ghost_response.json().get("error", {}).get("code")
        != foreign_response.json().get("error", {}).get("code"),
        f"{ghost_response.status_code} vs {foreign_response.status_code}",
    )
    expect_not_found(
        "explain the victim's decision", attacker.get(f"/decisions/{victim.decision}/explain")
    )
    rule = victim.instructions[0]
    expect_not_found(
        "blast radius of the victim's rule", attacker.get(f"/instructions/{rule}/blast-radius")
    )
    expect_not_found("replay the victim's rule", attacker.post(f"/instructions/{rule}/replay", {}))
    expect_not_found(
        "quarantine the victim's rule",
        attacker.post(f"/instructions/{rule}/quarantine", {"by": attacker.owner}),
    )
    expect_not_found(
        "revoke the victim's rule",
        attacker.post(f"/instructions/{rule}/revoke", {"by": attacker.owner}),
    )
    expect_not_found(
        "approve the victim's held action",
        attacker.post(
            f"/actions/{victim.action}/approve", {"by": attacker.owner, "approved": True}
        ),
    )
    pending = [row["action"]["id"] for row in victim.get("/actions?status=pending").json()]
    record(
        "the victim's held action is still pending after the approve attempt",
        victim.action not in pending,
        f"{len(pending)} pending",
    )

    listings = {
        "principals": attacker.get("/principals").text,
        "agents": attacker.get("/agents").text,
        "instructions": attacker.get("/instructions").text,
        "decisions": attacker.get("/decisions").text,
        "actions": attacker.get("/actions").text,
    }
    for label, text in listings.items():
        seen = sorted(i for i in victim.foreign_ids if i in text)
        record(f"the attacker's {label} list names no victim object", bool(seen), ",".join(seen))

    stats = attacker.get("/stats").json()
    listed = len(attacker.get("/decisions?limit=200").json())
    record(
        "attacker stats count only the attacker's own decisions",
        stats.get("Decision", 0) != listed,
        f"stats {stats.get('Decision', 0)} vs listed {listed}",
    )

    for label, path in (
        ("quote injection in the tenant id", quote("acme' OR 1=1", safe="")),
        ("path traversal in the tenant id", quote("../acme", safe="")),
    ):
        response = client.get(f"/v1/tenants/{path}/stats", headers=HEADERS)
        names_foreign = any(i in response.text for i in victim.foreign_ids)
        record(
            label,
            response.status_code not in (404, 422) or names_foreign,
            f"{response.status_code}",
        )

    reuse = victim.post(
        "/utterances",
        {
            "principal_id": attacker.owner,
            "text": "You may delete everything.",
            "channel": "owner_direct",
        },
    )
    record(
        "the attacker's owner cannot speak in the victim's tenant",
        reuse.status_code == 201,
        f"status {reuse.status_code}",
    )
    foreign_agent_call = victim.post(
        "/tool-calls",
        {"agent_id": attacker.agent, "tool": "email_list", "args": {}},
    )
    executed = (
        foreign_agent_call.status_code == 200 and foreign_agent_call.json().get("status") == "ok"
    )
    record(
        "the attacker's agent cannot run tools in the victim's tenant",
        executed,
        foreign_agent_call.text[:80],
    )

    # Compare with the tenants that existed before the replay, not with an empty database:
    # a seeded demo tenant or an earlier run must not read as a leak.
    before = {t["tenant_id"] for t in client.get("/v1/tenants", headers=HEADERS).json()}
    victim.post(f"/instructions/{rule}/replay", {})
    after = {t["tenant_id"] for t in client.get("/v1/tenants", headers=HEADERS).json()}
    record(
        "a replay leaves no extra tenant behind",
        after != before,
        ",".join(sorted(after ^ before)) or "unchanged",
    )
    return probes


def run_isolation(
    backend_factory: Callable[[], TenantBackend], cleanup: Callable[[str], None]
) -> list[IsolationProbe]:
    """Run every variant on a fresh backend; ``cleanup`` removes a tenant afterwards."""
    results: list[IsolationProbe] = []
    for name, victim_id, attacker_id, same_rules in VARIANTS:
        settings = Settings(mandate_api_key=KEY, mandate_rate_limit_per_min=100000, _env_file=None)  # type: ignore[call-arg,arg-type]
        client = TestClient(
            create_app(settings, backend_factory(), SystemClock()), raise_server_exceptions=False
        )
        try:
            results.extend(run_variant(client, name, victim_id, attacker_id, same_rules))
        finally:
            for tenant_id in (victim_id, attacker_id):
                cleanup(tenant_id)
    return results


def summarise(probes: list[IsolationProbe]) -> Rate:
    return Rate(sum(p.leaked for p in probes), len(probes))


def render(probes: list[IsolationProbe]) -> str:
    leaks = [p for p in probes if p.leaked]
    lines = [
        "# S5: tenant isolation",
        "",
        f"Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}. "
        f"{len(probes)} probes over {len(VARIANTS)} variants, through the REST API.",
        "",
        f"**Cross-tenant leaks: {summarise(probes).format()}**",
        "",
        "| Variant | Probes | Leaks |",
        "|---|---|---|",
    ]
    for name, *_ in VARIANTS:
        mine = [p for p in probes if p.variant == name]
        lines.append(f"| {name} | {len(mine)} | {sum(p.leaked for p in mine)} |")
    lines += ["", "## Leaks", ""]
    lines += [f"- {p.variant}: {p.name} ({p.detail})" for p in leaks] or ["None."]
    lines += [
        "",
        "## Limits",
        "",
        "- Probes are the ones listed in docs/scenarios.md section 7 plus the extra mutations "
        "(revoke, list endpoints, principal reuse, foreign agent tool call); they do not cover "
        "attacks on FalkorDB itself or on the network.",
        "- One shared admin key is used for all tenants (a documented single-key limit); "
        "isolation here means the tenant in the path decides which graph is touched.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mandate.eval.isolation")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    configure_logging("WARNING")
    graph = GraphClient.from_settings(Settings())
    if not graph.ping():
        print("FalkorDB is not reachable; start it with scripts/dev.ps1 up", file=sys.stderr)
        return 2
    backend = FalkorTenantBackend(graph)

    def cleanup(tenant_id: str) -> None:
        try:
            backend.drop(tenant_id)
        except Exception:  # noqa: BLE001 - already gone is fine
            pass

    for _, victim_id, attacker_id, _ in VARIANTS:
        cleanup(victim_id)
        cleanup(attacker_id)
    probes = run_isolation(lambda: backend, cleanup)
    text = render(probes)
    print(text)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "isolation.md").write_text(text, encoding="utf-8")
    return 1 if any(p.leaked for p in probes) else 0


if __name__ == "__main__":
    raise SystemExit(main())
