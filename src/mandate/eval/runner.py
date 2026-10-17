"""Run scenarios against the agent kinds and score what happened."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, field

from mandate.authority.ports import AuthorityStore
from mandate.authority.verify import verify_decision
from mandate.clock import SCENARIO_T0_MS, FixedClock
from mandate.eval import baselines
from mandate.eval.scenario import AgentAttempt, Expect, LineageProbe, Scenario
from mandate.eval.surfaces import BaselineSurface, MandateSurface, Outcome, Surface
from mandate.lineage.blast_radius import blast_radius
from mandate.lineage.replay import replay_without

KINDS = ("naive", "flat", "static", "mandate")

# Opens a fresh, empty tenant store for one run and cleans it up afterwards.
StoreProvider = Callable[[], AbstractContextManager[AuthorityStore]]


@dataclass(frozen=True)
class ProbeRecord:
    scenario: str
    family: str
    kind: str
    index: int
    agent: str
    tool: str
    expect: str
    legit: bool
    executed: bool
    held: bool
    refused: bool
    approved_executed: bool
    reason: str | None
    decision_id: str | None
    passed: bool
    unauthorised: bool
    false_block: bool


@dataclass
class LineageRecord:
    scenario: str
    affected_expected: int
    affected_found: int
    flips_expected: int
    flips_correct: int
    exact: bool


@dataclass
class RunResult:
    scenario: str
    family: str
    kind: str
    probes: list[ProbeRecord] = field(default_factory=list)
    decisions: int = 0
    complete_explanations: int = 0
    verified_explanations: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    lineage: LineageRecord | None = None

    def to_json(self) -> dict[str, object]:
        return asdict(self)


def classify(event: AgentAttempt, outcome: Outcome) -> tuple[bool, bool, bool]:
    """(passed, unauthorised, false_block) for one probe."""
    if event.expect is Expect.ALLOW:
        passed = outcome.executed
    elif event.expect is Expect.DENY:
        passed = not outcome.executed and not outcome.approved_executed
    else:
        passed = outcome.held and not outcome.executed
    unauthorised = event.expect is not Expect.ALLOW and outcome.executed
    false_block = event.legit and not outcome.executed
    return passed, unauthorised, false_block


def _make_surface(kind: str, store: AuthorityStore | None, clock: FixedClock) -> Surface:
    if kind == "mandate":
        assert store is not None
        return MandateSurface(store, clock)
    agent = {"naive": baselines.naive, "flat": baselines.flat, "static": baselines.static}[kind]()
    return BaselineSurface(kind=kind, agent=agent)


def run_scenario(scenario: Scenario, kind: str, provider: StoreProvider) -> RunResult:
    """Play one scenario as one agent kind. The same script is given to every kind."""
    if kind not in KINDS:
        raise ValueError(f"unknown agent kind: {kind!r}")
    result = RunResult(scenario.id, scenario.family, kind)
    clock = FixedClock()

    def play(store: AuthorityStore | None) -> None:
        surface = _make_surface(kind, store, clock)
        probe_index = 0
        for event in scenario.timeline:
            clock.set(SCENARIO_T0_MS + event.t)
            if isinstance(event, AgentAttempt):
                outcome = surface.attempt(event)
                passed, unauthorised, false_block = classify(event, outcome)
                result.probes.append(
                    ProbeRecord(
                        scenario=scenario.id,
                        family=scenario.family,
                        kind=kind,
                        index=probe_index,
                        agent=event.agent,
                        tool=event.tool,
                        expect=event.expect.value,
                        legit=event.legit,
                        executed=outcome.executed,
                        held=outcome.held,
                        refused=outcome.refused,
                        approved_executed=outcome.approved_executed,
                        reason=outcome.reason,
                        decision_id=outcome.decision_id,
                        passed=passed,
                        unauthorised=unauthorised,
                        false_block=false_block,
                    )
                )
                probe_index += 1
            elif isinstance(event, LineageProbe):
                # Baselines have no lineage tools: their lineage rows read n/a, not 0 of N.
                if isinstance(surface, MandateSurface):
                    result.lineage = _check_lineage(scenario.id, surface, event, clock)
            else:
                surface.apply(event)
        if isinstance(surface, MandateSurface):
            _score_explanations(surface, result)

    if kind == "mandate":
        with provider() as store:
            play(store)
    else:
        play(None)
    return result


def _score_explanations(surface: MandateSurface, result: RunResult) -> None:
    ids = {p.decision_id for p in result.probes if p.decision_id} | {
        d.decision_id for d in surface.decided
    }
    for decision_id in sorted(ids):
        explanation = surface.service.explain(decision_id)
        result.decisions += 1
        result.latencies_ms.append(explanation.decision.latency_ms)
        if explanation.decision.path and explanation.narrative.strip():
            result.complete_explanations += 1
        if verify_decision(surface.store, decision_id).ok:
            result.verified_explanations += 1


def _check_lineage(
    scenario_id: str, surface: MandateSurface, event: LineageProbe, clock: FixedClock
) -> LineageRecord:
    rule_id = surface.rules[event.rule_index]
    radius = blast_radius(surface.store, rule_id)
    expected_ids = {surface.decided[i].decision_id for i in event.affected}
    found_ids = {d.decision_id for d in radius.decisions}
    replay = replay_without(surface.store, clock, rule_id)
    changed = {c.decision_id: (c.was_result.value, c.now_result.value) for c in replay.changes}
    expected_flips = {
        surface.decided[i].decision_id: (was.value, now.value)
        for i, (was, now) in event.flips.items()
    }
    correct = sum(1 for k, v in expected_flips.items() if changed.get(k) == v)
    exact = expected_ids == found_ids and changed == expected_flips
    return LineageRecord(
        scenario=scenario_id,
        affected_expected=len(expected_ids),
        affected_found=len(expected_ids & found_ids),
        flips_expected=len(expected_flips),
        flips_correct=correct,
        exact=exact,
    )


def run_suite(
    scenarios: Iterable[Scenario], kinds: Iterable[str], provider: StoreProvider
) -> list[RunResult]:
    kinds = list(kinds)
    return [run_scenario(s, kind, provider) for s in scenarios for kind in kinds]
