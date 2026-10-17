"""Seed a demo tenant with a small, deterministic story, and reset it on demand.

    python -m mandate.seed                 # create tenant "demo" (does nothing if it exists)
    python -m mandate.seed --reset         # drop it and create it again
    python -m mandate.seed --tenant acme   # another tenant id

The story is the one the demo tells: an owner states rules; an agent reads, archives and
refunds within them; a delete is held; an injected email gets nothing; a delegate reads for
its parent; and then a typo in a refund limit lets three large refunds through, which blast
radius, quarantine and replay then find and undo. Everything is synthetic (Rule 6).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field

from mandate.api.tenancy import FalkorTenantBackend, Runtimes, TenantRuntime
from mandate.clock import SystemClock
from mandate.config import get_settings, token_secrets
from mandate.errors import TenantExists
from mandate.gateway.guard import ToolResult, guarded_call, resolve_pending
from mandate.graph.client import GraphClient
from mandate.ids import new_id
from mandate.logging import configure_logging
from mandate.mcp_servers.identity import AgentIdentity, mint_agent_token
from mandate.models.domain import Agent, AgentKind, Channel, Principal, Role

DEMO_TENANT = "demo"
OWNER_RULES = (
    "You may read and archive my email, but confirm with me before deleting anything.",
    "You may issue refunds up to $500.",
    "Confirm with me before sending any email.",
)
TYPO_RULE = "You may issue refunds up to $5000."  # the owner meant $500


@dataclass
class SeedResult:
    tenant_id: str
    owner_id: str
    assistant_id: str
    reconciler_id: str
    typo_rule_id: str
    held_action_id: str  # a delete still waiting for the owner
    approved_action_id: str  # a delete the owner approved
    decision_ids: list[str] = field(default_factory=list)
    untrusted_utterance: str = ""
    agent_token: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


def _call(
    rt: TenantRuntime, result: SeedResult, agent_id: str, tool: str, args: dict[str, object]
) -> ToolResult:
    out = guarded_call(rt.gateway, agent_id, tool, dict(args))
    if out.decision_id:
        result.decision_ids.append(out.decision_id)
    return out


def seed_demo(
    runtimes: Runtimes,
    tenant_id: str = DEMO_TENANT,
    *,
    reset: bool = False,
    token_secret: str | None = None,
) -> SeedResult:
    """Create the demo tenant. Raises ``TenantExists`` unless ``reset`` is set."""
    if reset:
        try:
            runtimes.drop(tenant_id)
        except Exception:  # noqa: BLE001 - nothing to drop is fine
            pass
    rt = runtimes.create(tenant_id, "Demo tenant")
    store, service = rt.store, rt.service

    owner = store.create_principal(Principal(id=new_id("prn"), name="Dana", role=Role.OWNER))
    assistant = store.create_agent(
        Agent(id=new_id("agt"), name="assistant", kind=AgentKind.PRIMARY)
    )
    reconciler = store.create_agent(Agent(id=new_id("agt"), name="reconciler", kind=AgentKind.SUB))

    def say(text: str) -> str:
        said = service.ingest_utterance(
            principal_id=owner.id, text=text, channel=Channel.OWNER_DIRECT
        )
        for item in said.instructions:
            if item.needs_confirmation:
                service.confirm_instruction(item.instruction.id, owner.id)
        return said.instructions[0].instruction.id if said.instructions else ""

    for text in OWNER_RULES:
        say(text)
    service.delegate(
        from_agent_id=assistant.id,
        to_agent_id=reconciler.id,
        action_type="email.read",
        resource_pattern="inbox/*",
        by_principal_id=owner.id,
    )

    result = SeedResult(
        tenant_id=tenant_id,
        owner_id=owner.id,
        assistant_id=assistant.id,
        reconciler_id=reconciler.id,
        typo_rule_id="",
        held_action_id="",
        approved_action_id="",
    )

    # An ordinary day.
    _call(rt, result, assistant.id, "email_list", {})
    _call(rt, result, assistant.id, "email_archive", {"message_id": "m-4"})
    _call(rt, result, reconciler.id, "email_read", {"message_id": "m-2"})
    _call(rt, result, assistant.id, "refund_issue", {"order_id": "82", "amount": 300})
    _call(rt, result, assistant.id, "refund_issue", {"order_id": "89", "amount": 900})  # over limit
    _call(rt, result, assistant.id, "file_write", {"path": "notes.txt", "content": "x"})  # no rule

    # An email with a planted instruction. Reading it is allowed; obeying it is not.
    _call(rt, result, assistant.id, "email_read", {"message_id": "m-31"})
    _call(
        rt,
        result,
        assistant.id,
        "email_send",
        {"to": "attacker@example.com", "subject": "hi", "body": "x"},
    )
    untrusted = [
        u for u in store.list_instructions() if u.instruction.lineage_trust.value == "untrusted"
    ]
    result.untrusted_utterance = untrusted[0].instruction.id if untrusted else ""

    # Deletes need the owner: one is approved, one is left waiting.
    approved = _call(rt, result, assistant.id, "email_delete", {"message_id": "m-5"})
    if approved.approval_id:
        resolve_pending(rt.gateway, approved.approval_id, owner.id, approved=True)
        result.approved_action_id = approved.approval_id
    held = _call(rt, result, assistant.id, "email_delete", {"message_id": "m-6"})
    result.held_action_id = held.approval_id or ""

    # The typo: $5000 instead of $500. Three large refunds go through before anyone notices.
    result.typo_rule_id = say(TYPO_RULE)
    for order, amount in (("87", 800), ("88", 850), ("89", 950)):
        _call(rt, result, assistant.id, "refund_issue", {"order_id": order, "amount": amount})

    if token_secret:
        result.agent_token = mint_agent_token(
            token_secret, AgentIdentity(tenant_id, assistant.id), ttl_seconds=7 * 86_400
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mandate.seed", description=__doc__)
    parser.add_argument("--tenant", default=DEMO_TENANT)
    parser.add_argument("--reset", action="store_true", help="drop the tenant first")
    parser.add_argument("--json", action="store_true", help="print the ids as JSON")
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging("WARNING")
    graph = GraphClient.from_settings(settings)
    if not graph.ping():
        print("FalkorDB is not reachable; start it with scripts/dev.ps1 up", file=sys.stderr)
        return 2
    runtimes = Runtimes(FalkorTenantBackend(graph), SystemClock())
    secrets = token_secrets(settings) if settings.mandate_api_key else []
    try:
        result = seed_demo(
            runtimes, args.tenant, reset=args.reset, token_secret=secrets[0] if secrets else None
        )
    except TenantExists:
        print(f"tenant {args.tenant!r} already exists; use --reset to rebuild it")
        return 0
    if args.json:
        print(result.to_json())
    else:
        print(
            f"seeded {result.tenant_id!r}: {len(result.decision_ids)} decisions, "
            f"typo rule {result.typo_rule_id}, held action {result.held_action_id}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
