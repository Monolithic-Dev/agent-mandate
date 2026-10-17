"""Scenario files: scripted timelines with hand-written expectations (docs/scenarios.md).

A scenario is data, not code. Expectations (``expect``, ``legit``) are written by hand from
the scenario's intent, never computed by the engine, so the engine cannot grade itself.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

SCENARIO_DIR = Path(__file__).parent / "scenarios"


class ScenarioError(ValueError):
    """A scenario file is malformed or inconsistent."""


class Expect(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    CONFIRM = "confirm"


class Reply(StrEnum):
    APPROVE = "approve"
    DECLINE = "decline"


class _Event(BaseModel):
    model_config = ConfigDict(extra="forbid")
    t: int = Field(ge=0, description="milliseconds after the scenario start")


class OwnerSay(_Event):
    event: Literal["owner_say"]
    text: str
    confirm: bool = True


class ExternalContent(_Event):
    event: Literal["external_content"]
    text: str
    source_ref: str = "email:m-31"


class Launder(_Event):
    """A memory step summarises earlier content and re-expresses it as a remembered rule.

    The summary draws on the last piece of external content, and also on the owner's last
    utterance when ``with_owner`` is set (a mixed origin). ``hops`` stacks summaries.
    """

    event: Literal["launder"]
    text: str
    hops: int = Field(default=1, ge=1, le=3)
    with_owner: bool = False


class Compact(_Event):
    event: Literal["compact"]


class Delegate(_Event):
    event: Literal["delegate"]
    from_agent: Literal["main", "sub"] = "main"
    to_agent: Literal["main", "sub"] = "sub"
    action_type: str
    resource_pattern: str = "*"
    valid_for_ms: int | None = Field(default=None, gt=0)
    expect_error: bool = False


class RevokeDelegation(_Event):
    event: Literal["revoke_delegation"]
    index: int = Field(ge=0, description="which delegation, in creation order")


class RevokeRule(_Event):
    event: Literal["revoke_rule"]
    index: int = Field(ge=0, description="which rule, in creation order")


class AgentAttempt(_Event):
    event: Literal["agent_attempt"]
    agent: Literal["main", "sub"] = "main"
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    expect: Expect
    legit: bool = False
    owner_reply: Reply | None = None

    @model_validator(mode="after")
    def _consistent(self) -> AgentAttempt:
        if self.legit and self.expect is not Expect.ALLOW:
            raise ValueError("a legitimate probe must expect allow")
        if self.owner_reply is not None and self.expect is not Expect.CONFIRM:
            raise ValueError("owner_reply only applies to a probe that expects confirm")
        return self


class Decide(_Event):
    """Ask the engine directly (no tool is run). Used by the lineage scenarios."""

    event: Literal["decide"]
    agent: Literal["main", "sub"] = "main"
    action_type: str
    resource: str
    args: dict[str, Any] = Field(default_factory=dict)
    expect: Expect


class LineageProbe(_Event):
    """Check blast radius and replay for a rule against hand-written expectations."""

    event: Literal["lineage_probe"]
    rule_index: int = Field(ge=0)
    affected: list[int] = Field(description="indexes of the decide events that used the rule")
    flips: dict[int, tuple[Expect, Expect]] = Field(default_factory=dict)


Event = Annotated[
    OwnerSay
    | ExternalContent
    | Launder
    | Compact
    | Delegate
    | RevokeDelegation
    | RevokeRule
    | AgentAttempt
    | Decide
    | LineageProbe,
    Field(discriminator="event"),
]


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^S\d+_[a-z0-9_]+_v\d+$")
    description: str
    timeline: list[Event]

    @property
    def family(self) -> str:
        return self.id.split("_", 1)[0]

    @model_validator(mode="after")
    def _ordered_and_consistent(self) -> Scenario:
        times = [event.t for event in self.timeline]
        if times != sorted(times):
            raise ValueError("timeline events must be in time order")
        revoked_at: dict[str, int] = {}
        delegations = [e for e in self.timeline if isinstance(e, Delegate) and not e.expect_error]
        for event in self.timeline:
            if isinstance(event, RevokeDelegation):
                if event.index >= len(delegations):
                    raise ValueError("revoke_delegation refers to a delegation that never exists")
                revoked_at[str(event.index)] = event.t
        for event in self.timeline:
            if isinstance(event, AgentAttempt) and event.agent == "sub" and event.legit:
                for index in range(len(delegations)):
                    when = revoked_at.get(str(index))
                    if when is not None and event.t >= when:
                        raise ValueError(
                            "a probe expecting allow comes after the delegation was revoked"
                        )
        return self

    def attempts(self) -> list[AgentAttempt]:
        return [e for e in self.timeline if isinstance(e, AgentAttempt)]


def load_scenario(path: Path) -> Scenario:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return Scenario.model_validate(data)
    except (ValidationError, yaml.YAMLError, OSError) as error:
        raise ScenarioError(f"{path.name}: {error}") from error


def load_scenarios(directory: Path = SCENARIO_DIR) -> list[Scenario]:
    paths = sorted(directory.glob("S*.yaml"))
    scenarios = [load_scenario(path) for path in paths]
    ids = [s.id for s in scenarios]
    if len(ids) != len(set(ids)):
        raise ScenarioError("duplicate scenario ids")
    for path, scenario in zip(paths, scenarios, strict=True):
        if path.stem != scenario.id:
            raise ScenarioError(f"{path.name}: file name must equal the scenario id")
    return scenarios
