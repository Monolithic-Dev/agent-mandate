"""A scenario run as a timeline the console can show, one entry per scripted event.

The run itself is the evaluation's (``run_scenario``): the same script, the same scoring.
This module only describes it: what each event was, in words, and for each agent attempt
what happened to it.
"""

from __future__ import annotations

from dataclasses import dataclass

from mandate.eval.runner import ProbeRecord, RunResult
from mandate.eval.scenario import (
    AgentAttempt,
    Compact,
    Decide,
    Delegate,
    Event,
    ExternalContent,
    Launder,
    LineageProbe,
    OwnerSay,
    RevokeDelegation,
    RevokeRule,
    Scenario,
)


@dataclass(frozen=True)
class TimelineEntry:
    seq: int
    t: int
    event: str
    text: str
    # Set for agent attempts only.
    agent: str | None = None
    tool: str | None = None
    expect: str | None = None
    status: str | None = None  # executed, held, approved, denied
    reason: str | None = None
    decision_id: str | None = None
    unauthorised: bool = False
    false_block: bool = False


def _quote(text: str, limit: int = 120) -> str:
    text = " ".join(text.split())
    return f'"{text if len(text) <= limit else text[: limit - 1] + "…"}"'


def describe(event: Event) -> str:
    """One plain sentence for a scripted event."""
    match event:
        case OwnerSay():
            return f"Owner says {_quote(event.text)}"
        case ExternalContent():
            return f"Untrusted content arrives ({event.source_ref}): {_quote(event.text)}"
        case Launder():
            origin = "untrusted content"
            if event.with_owner:
                origin += " and the owner's words"
            return f"Memory summarises {origin} into a remembered rule: {_quote(event.text)}"
        case Compact():
            return "Context compacted: earlier messages are replaced by a summary"
        case Delegate():
            return (
                f"Agent {event.from_agent} delegates {event.action_type} on "
                f"{event.resource_pattern} to agent {event.to_agent}"
            )
        case RevokeDelegation():
            return f"Owner revokes delegation #{event.index + 1}"
        case RevokeRule():
            return f"Owner revokes rule #{event.index + 1}"
        case AgentAttempt():
            args = ", ".join(f"{k}={v!r}" for k, v in event.args.items())
            return f"Agent {event.agent} calls {event.tool}({args})"
        case Decide():
            return f"Check: may agent {event.agent} {event.action_type} on {event.resource}?"
        case LineageProbe():
            return f"Lineage check on rule #{event.rule_index + 1}"
    raise ValueError(f"unknown event: {event!r}")


def _status(probe: ProbeRecord) -> str:
    if probe.executed:
        return "executed"
    if probe.approved_executed:
        return "approved"
    if probe.held:
        return "held"
    return "denied"


def build_timeline(scenario: Scenario, result: RunResult) -> list[TimelineEntry]:
    """Pair each scripted event with what happened to it in ``result``."""
    probes = iter(result.probes)
    entries: list[TimelineEntry] = []
    for seq, event in enumerate(scenario.timeline):
        if isinstance(event, AgentAttempt):
            probe = next(probes)
            entries.append(
                TimelineEntry(
                    seq=seq,
                    t=event.t,
                    event=event.event,
                    text=describe(event),
                    agent=event.agent,
                    tool=event.tool,
                    expect=event.expect.value,
                    status=_status(probe),
                    reason=probe.reason,
                    decision_id=probe.decision_id,
                    unauthorised=probe.unauthorised,
                    false_block=probe.false_block,
                )
            )
        else:
            entries.append(TimelineEntry(seq, event.t, event.event, describe(event)))
    return entries
