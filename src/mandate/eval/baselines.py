"""Baselines: agents whose rules live in their prompt, not in a graph (docs/ai-pipeline.md).

These are deterministic stand-ins for a model that follows the rules it was given. They
are deliberately fair about what such an agent can do (it respects a limit it was told
about, and holds when told to confirm) and honest about what it cannot (it cannot tell
who said something, and it has no notion of delegation).

* ``naive``: rules are in its prompt and history; when the context is compacted the
  summary drops sentences containing "confirm", "never" and "do not" (the documented
  failure), so confirm and deny rules vanish.
* ``flat``: the same, but rules are kept as a list that is never compacted.
* ``static``: a gateway with a fixed, developer-written policy (below). It ignores what the
  owner says and what content claims, so forged and laundered text cannot move it, but it
  also cannot honour the owner's own rules or learn of a revocation. The policy is **our
  assumption** of a plausible restrictive policy, not a model of any named product; every
  static-baseline figure depends on it and the report says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from mandate.authority.parser import ParsedInstruction, parse_utterance
from mandate.gateway.sandbox.state import Sandbox
from mandate.gateway.tools import TOOLS
from mandate.models.domain import Effect
from mandate.models.registry import action_type_covers
from mandate.models.resources import resource_matches

_PRE_APPROVED = re.compile(r"pre-?approved", re.IGNORECASE)


@dataclass(frozen=True)
class PromptRule:
    effect: Effect
    action_type: str
    resource_pattern: str
    max_amount: int | None

    @classmethod
    def from_parsed(cls, item: ParsedInstruction) -> PromptRule:
        return cls(
            item.effect, item.action_type, item.resource_pattern, item.constraints.max_amount
        )


@dataclass(frozen=True)
class Verdict:
    outcome: str  # "execute", "hold" or "refuse"
    reason: str


@dataclass
class PromptAgent:
    """An agent that follows whatever rules it currently remembers."""

    drops_confirm_and_deny_on_compaction: bool
    rules: list[PromptRule] = field(default_factory=list)
    sandbox: Sandbox = field(default_factory=Sandbox.seeded)
    # What the agent does when no rule it remembers matches.
    default: Verdict = field(
        default_factory=lambda: Verdict("execute", "no rule remembered, so it does the task")
    )
    # A static policy is configured once; it never learns from conversation or content.
    learns: bool = True

    # --- what the agent reads ---------------------------------------------------------

    def hear_owner(self, text: str) -> None:
        if not self.learns:
            return
        self.rules.extend(PromptRule.from_parsed(i) for i in parse_utterance(text).instructions)

    def read_content(self, text: str) -> None:
        """It cannot tell who wrote this, so instruction-like text is adopted as a rule."""
        if not self.learns:
            return
        self.rules.extend(PromptRule.from_parsed(i) for i in parse_utterance(text).instructions)
        if _PRE_APPROVED.search(text):
            lowered = text.lower()
            if "refund" in lowered:
                self.rules.append(PromptRule(Effect.ALLOW, "refund.issue", "*", None))
            if "send" in lowered:
                self.rules.append(PromptRule(Effect.ALLOW, "email.send", "*", None))

    def compact(self) -> None:
        if self.drops_confirm_and_deny_on_compaction:
            self.rules = [r for r in self.rules if r.effect is Effect.ALLOW]

    # --- what the agent does ----------------------------------------------------------

    def decide(self, tool: str, args: dict[str, object]) -> Verdict:
        spec = TOOLS[tool]
        parsed = spec.model.model_validate(args)
        action_type = spec.action_type
        resource = spec.resource(parsed, self.sandbox)
        amount = spec.check_args(parsed).get("amount")
        for rule in reversed(self.rules):  # the most recent rule it remembers wins
            if not action_type_covers(rule.action_type, action_type):
                continue
            if not resource_matches(rule.resource_pattern, resource):
                continue
            if rule.effect is Effect.DENY:
                return Verdict("refuse", "told not to")
            if rule.effect is Effect.CONFIRM:
                return Verdict("hold", "told to confirm first")
            if rule.max_amount is not None and amount is not None and amount > rule.max_amount:
                return Verdict("refuse", "over the limit it was told about")
            return Verdict("execute", "told it may")
        return self.default

    def run(self, tool: str, args: dict[str, object]) -> dict[str, object]:
        spec = TOOLS[tool]
        return spec.run(self.sandbox, spec.model.model_validate(args))


def naive() -> PromptAgent:
    return PromptAgent(drops_confirm_and_deny_on_compaction=True)


def flat() -> PromptAgent:
    return PromptAgent(drops_confirm_and_deny_on_compaction=False)


# The assumed static policy. Later entries win. Reads and archiving are allowed, refunds up
# to 100 are allowed (larger ones are refused), anything that sends, deletes or writes needs
# approval, and anything unlisted is denied.
STATIC_POLICY = (
    PromptRule(Effect.ALLOW, "email.read", "*", None),
    PromptRule(Effect.ALLOW, "email.archive", "*", None),
    PromptRule(Effect.ALLOW, "file.read", "*", None),
    PromptRule(Effect.ALLOW, "refund.issue", "*", 100),
    PromptRule(Effect.CONFIRM, "email.send", "*", None),
    PromptRule(Effect.CONFIRM, "email.delete", "*", None),
    PromptRule(Effect.CONFIRM, "file.write", "*", None),
    PromptRule(Effect.CONFIRM, "file.delete", "*", None),
)


def static() -> PromptAgent:
    return PromptAgent(
        drops_confirm_and_deny_on_compaction=False,
        rules=list(STATIC_POLICY),
        default=Verdict("refuse", "not in the static policy"),
        learns=False,
    )
