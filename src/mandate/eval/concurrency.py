"""S6: concurrency. Many agents in many tenants decide at once while rules are revoked.

For every check the oracle says what the answer must be:

* an agent with no rule, or asking for something its rule never covered: deny, always;
* an agent whose rule is never revoked: allow, always;
* an agent whose rule is revoked mid-run: allow if the check finished before the revoke began,
  deny if it began after the revoke finished, either answer in between; and never an allow
  after a deny was seen (revocation is permanent).

Any error, wrong answer or foreign decision counts. Run with ``python -m mandate.eval.concurrency``.
"""

from __future__ import annotations

import argparse
import os
import platform
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from mandate.api.tenancy import FalkorTenantBackend, Runtimes, TenantRuntime
from mandate.clock import SystemClock
from mandate.config import Settings
from mandate.eval.metrics import percentile
from mandate.graph.client import GraphClient
from mandate.ids import new_id
from mandate.logging import configure_logging
from mandate.models.domain import (
    Agent,
    AgentKind,
    Channel,
    CheckRequest,
    Principal,
    Result,
    Role,
)

READ_TEXT = "You may read my email."
DENY_TEXT = "Never delete any email."


@dataclass(frozen=True)
class Variant:
    name: str
    write_every: int  # every Nth operation is an utterance (10 = 10 percent, 2 = 50 percent)


VARIANTS = (Variant("v1_read_heavy", 10), Variant("v2_write_heavy", 2))


@dataclass
class AgentPlan:
    tenant_id: str
    agent: Agent
    has_rule: bool
    rule_id: str | None
    revoked_mid_run: bool


@dataclass
class Observation:
    action: str
    started: float
    finished: float
    result: Result | None
    error: str | None = None


@dataclass(frozen=True)
class RevocationLag:
    """How long a revoked rule could still allow, for one agent.

    A check that starts after the revoke's write finished must be denied (the oracle fails
    the run otherwise), so the write window bounds the lag. Within it, either answer is
    correct; ``allows_in_window`` counts the allows that started there and
    ``last_allow_ms`` is how long after the revoke began the latest of them started.
    """

    window_ms: float
    allows_in_window: int
    last_allow_ms: float | None


def revocation_lag(seen: list[Observation], window: tuple[float, float]) -> RevocationLag:
    began, finished = window
    late = [
        o.started
        for o in seen
        if o.action == "email.read" and o.result is Result.ALLOW and began <= o.started < finished
    ]
    return RevocationLag(
        window_ms=(finished - began) * 1000,
        allows_in_window=len(late),
        last_allow_ms=(max(late) - began) * 1000 if late else None,
    )


@dataclass
class VariantResult:
    variant: str
    tenants: int
    agents: int
    checks: int
    writes: int
    mismatches: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    cross_tenant: list[str] = field(default_factory=list)
    audit_gaps: list[str] = field(default_factory=list)
    latencies_ms: list[float] = field(default_factory=list)
    seconds: float = 0.0
    lags: list[RevocationLag] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not (self.mismatches or self.errors or self.cross_tenant or self.audit_gaps)


def _setup(
    runtimes: Runtimes, tenant_id: str, agents_per_tenant: int
) -> tuple[TenantRuntime, str, list[AgentPlan]]:
    runtime = runtimes.create(tenant_id, tenant_id)
    owner = runtime.store.create_principal(Principal(id=new_id("prn"), name="o", role=Role.OWNER))
    plans: list[AgentPlan] = []
    for index in range(agents_per_tenant):
        agent = runtime.store.create_agent(
            Agent(id=new_id("agt"), name=f"a{index}", kind=AgentKind.PRIMARY)
        )
        has_rule = index % 2 == 0
        rule_id = None
        if has_rule:
            said = runtime.service.ingest_utterance(
                principal_id=owner.id,
                text=READ_TEXT,
                channel=Channel.OWNER_DIRECT,
                agent_ids=[agent.id],
            )
            rule_id = said.instructions[0].instruction.id
        plans.append(AgentPlan(tenant_id, agent, has_rule, rule_id, has_rule and index % 4 == 0))
    return runtime, owner.id, plans


def _agent_worker(
    runtime: TenantRuntime,
    owner_id: str,
    plan: AgentPlan,
    operations: int,
    variant: Variant,
    start: threading.Barrier,
) -> tuple[list[Observation], int]:
    seen: list[Observation] = []
    writes = 0
    start.wait()
    for number in range(operations):
        if number % variant.write_every == variant.write_every - 1:
            # A write that never changes what this agent may do: a duplicate read grant for a
            # live agent, or a deny-delete otherwise (a revoked agent must not be re-granted).
            text = READ_TEXT if plan.has_rule and not plan.revoked_mid_run else DENY_TEXT
            try:
                runtime.service.ingest_utterance(
                    principal_id=owner_id,
                    text=text,
                    channel=Channel.OWNER_DIRECT,
                    agent_ids=[plan.agent.id],
                )
                writes += 1
            except Exception as error:  # noqa: BLE001 - every failure is a finding
                now = time.perf_counter()
                seen.append(Observation("write", now, now, None, repr(error)[:120]))
            continue
        action = "email.read" if number % 2 == 0 else "email.delete"
        began = time.perf_counter()
        try:
            checked = runtime.service.check(
                CheckRequest(agent_id=plan.agent.id, action_type=action, resource="inbox/m-1")
            )
            seen.append(Observation(action, began, time.perf_counter(), checked.decision.result))
        except Exception as error:  # noqa: BLE001 - every failure is a finding
            seen.append(Observation(action, began, time.perf_counter(), None, repr(error)[:120]))
    return seen, writes


def _revoker(
    runtime: TenantRuntime,
    owner_id: str,
    plans: list[AgentPlan],
    start: threading.Barrier,
    seed: int,
    window: dict[str, tuple[float, float]],
    failures: list[str],
) -> None:
    rng = random.Random(seed)
    start.wait()
    for plan in plans:
        if not plan.revoked_mid_run or plan.rule_id is None:
            continue
        time.sleep(rng.uniform(0.005, 0.12))
        began = time.perf_counter()
        try:
            runtime.service.revoke_instruction(plan.rule_id, owner_id)
        except Exception as error:  # noqa: BLE001 - every failure is a finding
            failures.append(f"{plan.agent.id}: revoke failed: {repr(error)[:120]}")
            continue
        window[plan.agent.id] = (began, time.perf_counter())


def judge(
    plan: AgentPlan, seen: list[Observation], window: tuple[float, float] | None
) -> list[str]:
    problems: list[str] = []
    denied_seen = False
    for obs in seen:
        label = f"{plan.agent.id} {obs.action}"
        if obs.error is not None:
            problems.append(f"{label}: error {obs.error}")
            continue
        assert obs.result is not None
        allowed = obs.result is Result.ALLOW
        if obs.action == "email.delete" or not plan.has_rule:
            if allowed:
                problems.append(f"{label}: allowed but must be denied")
        elif not plan.revoked_mid_run:
            if not allowed:
                problems.append(f"{label}: {obs.result.value} but must be allow")
        else:
            began, finished = window if window else (float("inf"), float("inf"))
            if obs.finished <= began and not allowed:
                problems.append(f"{label}: denied before the revoke began")
            if obs.started >= finished and allowed:
                problems.append(f"{label}: allowed after the revoke finished")
            if allowed and denied_seen:
                problems.append(f"{label}: allowed after an earlier deny (revocation undone)")
            denied_seen = denied_seen or not allowed
    return problems


def run_variant(
    client: GraphClient, variant: Variant, tenants: int, agents: int, operations: int
) -> VariantResult:
    runtimes = Runtimes(FalkorTenantBackend(client), SystemClock())
    stamp = new_id("act")[4:12].lower()
    tenant_ids = [f"s6{stamp}{n}" for n in range(tenants)]
    result = VariantResult(variant.name, tenants, tenants * agents, 0, 0)
    try:
        setups = [_setup(runtimes, tenant_id, agents) for tenant_id in tenant_ids]
        workers = tenants * agents + tenants
        start = threading.Barrier(workers + 1)
        windows: dict[str, tuple[float, float]] = {}
        revoke_failures: list[str] = []
        with ThreadPoolExecutor(workers) as pool:
            jobs = []
            for runtime, owner_id, plans in setups:
                for plan in plans:
                    job = pool.submit(
                        _agent_worker, runtime, owner_id, plan, operations, variant, start
                    )
                    jobs.append((plan, job))
            for index, (runtime, owner_id, plans) in enumerate(setups):
                pool.submit(
                    _revoker, runtime, owner_id, plans, start, index, windows, revoke_failures
                )
            start.wait()
            began = time.perf_counter()
            outcomes = [(plan, job.result()) for plan, job in jobs]
        result.seconds = time.perf_counter() - began

        expected_decisions: dict[str, int] = dict.fromkeys(tenant_ids, 0)
        for plan, (seen, writes) in outcomes:
            result.writes += writes
            result.checks += sum(o.action != "write" for o in seen)
            expected_decisions[plan.tenant_id] += sum(
                o.error is None and o.action != "write" for o in seen
            )
            result.mismatches += judge(plan, seen, windows.get(plan.agent.id))
            if plan.agent.id in windows:
                result.lags.append(revocation_lag(seen, windows[plan.agent.id]))
            result.latencies_ms += [
                (o.finished - o.started) * 1000 for o in seen if o.action != "write"
            ]
        result.mismatches += revoke_failures
        result.errors = [m for m in result.mismatches if ": error " in m or "revoke failed" in m]
        result.mismatches = [m for m in result.mismatches if m not in result.errors]

        for runtime, _, plans in setups:
            tenant_id = runtime.tenant.id
            own = {plan.agent.id for plan in plans}
            recorded = runtime.store.list_decisions(limit=100000)
            foreign = [d.agent_id for d in recorded if d.agent_id not in own]
            if foreign:
                result.cross_tenant.append(f"{tenant_id}: {len(foreign)} foreign decisions")
            if len(recorded) != expected_decisions[tenant_id]:
                result.audit_gaps.append(
                    f"{tenant_id}: {len(recorded)} decisions recorded, "
                    f"{expected_decisions[tenant_id]} expected"
                )
    finally:
        for tenant_id in tenant_ids:
            try:
                runtimes.drop(tenant_id)
            except Exception:  # noqa: BLE001 - already gone is fine
                pass
    return result


def render(results: list[VariantResult], sha: str) -> str:
    lines = [
        "# S6: concurrency",
        "",
        f"Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} at git `{sha}`. "
        f"Machine: {platform.platform()}, {os.cpu_count()} logical CPUs; FalkorDB in a local "
        "container; the load generator and the API code run in this one Python process "
        "(threads), so latency includes contention for the interpreter.",
        "",
        "| Variant | Tenants x agents | Checks | Writes | Wrong answers | Errors | Cross-tenant | "
        "Audit gaps | p50 ms | p95 ms | Checks/s |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        p50, p95 = percentile(r.latencies_ms, 0.5), percentile(r.latencies_ms, 0.95)
        rate = r.checks / r.seconds if r.seconds else 0
        lines.append(
            f"| {r.variant} | {r.tenants} x {r.agents // r.tenants} | {r.checks} | {r.writes} | "
            f"{len(r.mismatches)} | {len(r.errors)} | {len(r.cross_tenant)} | "
            f"{len(r.audit_gaps)} | "
            f"{p50:.1f} | {p95:.1f} | {rate:.0f} |"
        )
    lines += [
        "",
        "## Revocation lag",
        "",
        "Per revoked rule: the revoke's write window (a check that starts after it must be "
        "denied, and is), and the allows that started inside it, where either answer is correct.",
        "",
        "| Variant | Revokes | Window p50 ms | Window max ms | Allows inside a window | "
        "Latest allow after revoke began, ms |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        windows = [lag.window_ms for lag in r.lags]
        lates = [lag.last_allow_ms for lag in r.lags if lag.last_allow_ms is not None]
        p50 = percentile(windows, 0.5)
        lines.append(
            f"| {r.variant} | {len(r.lags)} | "
            f"{f'{p50:.1f}' if p50 is not None else 'n/a'} | "
            f"{f'{max(windows):.1f}' if windows else 'n/a'} | "
            f"{sum(lag.allows_in_window for lag in r.lags)} | "
            f"{f'{max(lates):.1f}' if lates else 'none'} |"
        )
    lines += ["", "## Problems", ""]
    problems = [
        f"- {r.variant}: {text}"
        for r in results
        for text in (*r.mismatches, *r.errors, *r.cross_tenant, *r.audit_gaps)
    ]
    lines += problems[:40] or ["None."]
    lines += [
        "",
        "## Limits",
        "",
        "- The oracle is deterministic (what each agent's rules allow) plus a timing window for "
        "revokes; it does not cover multi-step races between several writers to one rule.",
        "- One process with threads, one database node. Not a throughput benchmark. All workers "
        "start together (a closed loop of 50 clients), so latency is mostly queueing: "
        "p50 is roughly 50 clients divided by checks per second.",
        "- An unscored warm-up run precedes the measured ones; without it the first variant's "
        "p95 was about 2 seconds (connection and query-plan cold start).",
        "- Writes are duplicate grants and deny rules that cannot change an agent's answer; "
        "write conflicts that should change answers are covered by the unit and contract tests.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mandate.eval.concurrency")
    parser.add_argument("--tenants", type=int, default=5)
    parser.add_argument("--agents", type=int, default=10)
    parser.add_argument("--operations", type=int, default=20)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    configure_logging("ERROR")
    client = GraphClient.from_settings(Settings())
    if not client.ping():
        print("FalkorDB is not reachable; start it with scripts/dev.ps1 up", file=sys.stderr)
        return 2
    # One small unscored pass first: the cold start (connections, query plans) added about
    # two seconds to the first variant's p95 and is not what this program measures.
    run_variant(client, VARIANTS[0], args.tenants, args.agents, 2)
    results = [
        run_variant(client, variant, args.tenants, args.agents, args.operations)
        for variant in VARIANTS
    ]
    from mandate.eval.report import _git_sha

    text = render(results, _git_sha())
    print(text)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "concurrency.md").write_text(text, encoding="utf-8")
    return 0 if all(r.clean for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
