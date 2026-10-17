"""The two ways a scenario is played: through the gateway, or by an agent that trusts its prompt."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from mandate.authority.parser import parse_utterance
from mandate.authority.ports import AuthorityStore
from mandate.authority.service import AuthorityService
from mandate.clock import FixedClock
from mandate.errors import DelegationExceedsAuthority, MandateError
from mandate.eval import baselines
from mandate.eval.scenario import (
    AgentAttempt,
    Compact,
    Decide,
    Delegate,
    Event,
    ExternalContent,
    Launder,
    OwnerSay,
    Reply,
    RevokeDelegation,
    RevokeRule,
)
from mandate.gateway.guard import GatewayRuntime, guarded_call, resolve_pending
from mandate.gateway.sandbox.state import Sandbox
from mandate.ids import new_id
from mandate.models.domain import (
    Agent,
    AgentKind,
    Channel,
    CheckRequest,
    Principal,
    Role,
    Summary,
)


@dataclass(frozen=True)
class Outcome:
    """What happened when an agent tried something."""

    executed: bool  # took effect with no owner approval
    held: bool  # stopped and asked
    refused: bool
    approved_executed: bool = False  # took effect only after the owner approved a hold
    reason: str | None = None
    decision_id: str | None = None


@dataclass(frozen=True)
class Decided:
    """The result of asking the engine directly (a ``decide`` event)."""

    result: str
    reason: str
    decision_id: str


class Surface(Protocol):
    kind: str

    def apply(self, event: Event) -> None: ...

    def attempt(self, event: AgentAttempt) -> Outcome: ...


@dataclass
class BaselineSurface:
    """Plays a scenario with an agent that keeps its rules in its prompt."""

    kind: str
    agent: baselines.PromptAgent
    decided: list[Decided] = field(default_factory=list)

    def apply(self, event: Event) -> None:
        if isinstance(event, OwnerSay):
            self.agent.hear_owner(event.text)
        elif isinstance(event, ExternalContent):
            self.agent.read_content(event.text)
        elif isinstance(event, Launder):
            # It cannot tell where its memory of this came from, so it adopts it as a rule.
            self.agent.read_content(event.text)
        elif isinstance(event, Compact):
            self.agent.compact()
        # Delegation, revocation and direct engine checks mean nothing to a prompt-only agent.
        elif isinstance(event, Delegate | RevokeDelegation | RevokeRule | Decide):
            return

    def attempt(self, event: AgentAttempt) -> Outcome:
        verdict = self.agent.decide(event.tool, event.args)
        if verdict.outcome == "refuse":
            return Outcome(False, False, True, reason=verdict.reason)
        if verdict.outcome == "hold":
            if event.owner_reply is Reply.APPROVE:
                if not self._run(event):
                    return Outcome(False, True, False, reason="the tool failed")
                return Outcome(False, True, False, approved_executed=True, reason=verdict.reason)
            return Outcome(False, True, False, reason=verdict.reason)
        if not self._run(event):
            return Outcome(False, False, True, reason="the tool failed")
        return Outcome(True, False, False, reason=verdict.reason)

    def _run(self, event: AgentAttempt) -> bool:
        """Run the tool; a tool that raises did not take effect."""
        try:
            self.agent.run(event.tool, event.args)
        except MandateError:
            return False
        return True


class MandateSurface:
    """Plays a scenario through the real gateway, service and store."""

    kind = "mandate"

    def __init__(self, store: AuthorityStore, clock: FixedClock) -> None:
        self.store = store
        self.clock = clock
        self.owner = store.create_principal(
            Principal(id=new_id("prn"), name="Dana", role=Role.OWNER)
        )
        self.outsider = store.create_principal(
            Principal(id=new_id("prn"), name="unknown-sender", role=Role.EXTERNAL)
        )
        self.agents = {
            "main": store.create_agent(
                Agent(id=new_id("agt"), name="main", kind=AgentKind.PRIMARY)
            ),
            "sub": store.create_agent(Agent(id=new_id("agt"), name="sub", kind=AgentKind.SUB)),
        }
        self.service = AuthorityService(store, clock)
        self.runtime = GatewayRuntime(
            self.service, Sandbox.seeded(), content_principal_id=self.outsider.id
        )
        self.rules: list[str] = []
        self.last_owner_utterance: str | None = None
        self.last_external_utterance: str | None = None
        self.delegations: list[str] = []
        self.decided: list[Decided] = []

    def apply(self, event: Event) -> None:
        if isinstance(event, OwnerSay):
            result = self.service.ingest_utterance(
                principal_id=self.owner.id, text=event.text, channel=Channel.OWNER_DIRECT
            )
            self.last_owner_utterance = result.utterance.id
            for item in result.instructions:
                self.rules.append(item.instruction.id)
                if event.confirm and item.needs_confirmation:
                    self.service.confirm_instruction(item.instruction.id, self.owner.id)
        elif isinstance(event, ExternalContent):
            result = self.service.ingest_utterance(
                principal_id=self.outsider.id,
                text=event.text,
                channel=Channel.UNTRUSTED_CONTENT,
                source_ref=event.source_ref,
            )
            self.last_external_utterance = result.utterance.id
            self.rules.extend(i.instruction.id for i in result.instructions)
        elif isinstance(event, Launder):
            self._launder(event)
        elif isinstance(event, Delegate):
            self._delegate(event)
        elif isinstance(event, RevokeDelegation):
            self.service.revoke_delegation(self.delegations[event.index], self.owner.id)
        elif isinstance(event, RevokeRule):
            self.service.revoke_instruction(self.rules[event.index], self.owner.id)
        elif isinstance(event, Decide):
            self._decide(event)
        # Compaction means nothing to the gateway: its rules are not in anyone's context.

    def _launder(self, event: Launder) -> None:
        """Summarise earlier content (and maybe the owner) and re-express it as a rule.

        This is the memory step of an agent, done below the service so that nothing here
        goes through the owner: the store decides what lineage the new rule has, and
        refuses to activate one that traces only to untrusted content.
        """
        assert self.last_external_utterance is not None, "launder needs earlier external content"
        sources = [self.last_external_utterance]
        if event.with_owner:
            assert self.last_owner_utterance is not None, "with_owner needs an earlier owner_say"
            sources.append(self.last_owner_utterance)
        now = self.clock.now_ms()
        for _ in range(event.hops):
            summary = self.store.create_summary(
                Summary(id=new_id("sum"), text="summary of earlier content", at=now), sources
            )
            sources = [summary.id]
        for item in parse_utterance(event.text).instructions:
            instruction = self.store.create_instruction(
                source_id=sources[0],
                effect=item.effect,
                action_type=item.action_type,
                agent_ids=[self.agents["main"].id],
                created_at=now,
                text_span=item.text_span,
                resource_pattern=item.resource_pattern,
                max_amount=item.constraints.max_amount,
            )
            self.rules.append(instruction.id)
            try:
                self.store.activate_instruction(instruction.id, now)
            except MandateError:
                pass  # refused: its lineage reaches no trusted utterance

    def _delegate(self, event: Delegate) -> None:
        valid_to = self.clock.now_ms() + event.valid_for_ms if event.valid_for_ms else None
        try:
            delegation = self.service.delegate(
                from_agent_id=self.agents[event.from_agent].id,
                to_agent_id=self.agents[event.to_agent].id,
                action_type=event.action_type,
                resource_pattern=event.resource_pattern,
                valid_to=valid_to,
                by_principal_id=self.owner.id,
            )
        except DelegationExceedsAuthority:
            if not event.expect_error:
                raise
            return
        if event.expect_error:
            raise AssertionError("the delegation was expected to be refused")
        self.delegations.append(delegation.id)

    def _decide(self, event: Decide) -> None:
        checked = self.service.check(
            CheckRequest(
                agent_id=self.agents[event.agent].id,
                action_type=event.action_type,
                resource=event.resource,
                args=event.args,
                as_of=self.clock.now_ms(),
            )
        )
        if checked.decision.result.value != event.expect.value:
            raise AssertionError(
                f"decide event at t={event.t} expected {event.expect.value} "
                f"but the engine said {checked.decision.result.value} ("
                f"{checked.decision.reason.value}); the scenario or the engine is wrong"
            )
        self.decided.append(
            Decided(
                checked.decision.result.value, checked.decision.reason.value, checked.decision.id
            )
        )

    def attempt(self, event: AgentAttempt) -> Outcome:
        result = guarded_call(self.runtime, self.agents[event.agent].id, event.tool, event.args)
        if result.status == "ok":
            return Outcome(True, False, False, decision_id=result.decision_id)
        if result.status == "confirmation_required":
            assert result.approval_id is not None
            held = Outcome(False, True, False, reason=result.reason, decision_id=result.decision_id)
            if event.owner_reply is None:
                return held
            approved = event.owner_reply is Reply.APPROVE
            resolved = resolve_pending(
                self.runtime, result.approval_id, self.owner.id, approved=approved
            )
            return Outcome(
                False,
                True,
                False,
                approved_executed=approved and resolved.status == "ok",
                reason=result.reason,
                decision_id=result.decision_id,
            )
        return Outcome(False, False, True, reason=result.reason, decision_id=result.decision_id)

    def explain_all(self) -> list[Any]:
        """Explanations for every decision the surface produced (for completeness checks)."""
        return [self.service.explain(d.decision_id) for d in self.decided]
