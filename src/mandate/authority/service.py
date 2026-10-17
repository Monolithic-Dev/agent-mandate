"""The authority service: the application-level operations an owner or gateway performs.

Each method validates its input, enforces who may do what (only an owner can confirm,
revoke or delegate), and delegates persistence to the store port. It contains no I/O of
its own, so it runs against the in-memory fake or the FalkorDB store unchanged.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from pydantic import ValidationError

from mandate.authority.check import CheckResult, check_authority
from mandate.authority.explain import Explanation, explain
from mandate.authority.parser import parse_utterance
from mandate.authority.pdp import PolicyDecisionPoint
from mandate.authority.ports import AuthorityStore, StoredAction
from mandate.clock import Clock
from mandate.errors import Conflict, DelegationExceedsAuthority, NotOwner, ValidationFailure
from mandate.ids import new_id
from mandate.models.domain import (
    ActionStatus,
    ActivationKind,
    AgentKind,
    Approval,
    Channel,
    CheckRequest,
    Constraints,
    Delegation,
    Instruction,
    LineageTrust,
    Result,
    Role,
    TokenRevocation,
    Utterance,
)
from mandate.models.registry import ACTION_TYPES, action_type_covers
from mandate.models.trust import compute_trust
from mandate.models.validation import ensure_not_future


@dataclass(frozen=True)
class IngestedInstruction:
    instruction: Instruction
    action_type: str
    resource_pattern: str
    max_amount: int | None
    # True when the owner can still confirm it; False when it is active or can never be.
    needs_confirmation: bool
    # True when its origin is untrusted: it is stored for display but can never activate.
    inert: bool


@dataclass(frozen=True)
class IngestResult:
    utterance: Utterance
    instructions: list[IngestedInstruction] = field(default_factory=list)
    unparsed: list[str] = field(default_factory=list)


def _sample_resource(pattern: str) -> str:
    """A concrete resource that matches a glob, used to probe whether authority exists."""
    return re.sub(r"[*?]", "x", pattern).strip("/") or "x"


class AuthorityService:
    def __init__(
        self,
        store: AuthorityStore,
        clock: Clock,
        *,
        id_factory: Callable[[str], str] = new_id,
        pdp: PolicyDecisionPoint | None = None,
    ) -> None:
        self._store = store
        self._clock = clock
        self._new_id = id_factory
        self._pdp = pdp
        self._known_agents: set[str] = set()

    # --- instructions ---------------------------------------------------------------

    def ingest_utterance(
        self,
        *,
        principal_id: str,
        text: str,
        channel: Channel,
        agent_ids: Sequence[str] | None = None,
        source_ref: str | None = None,
        at: int | None = None,
    ) -> IngestResult:
        """Store something a principal said and propose rules parsed from it.

        Trust is computed here from the channel and the speaker's role; a client cannot
        claim it. Rules from untrusted content are stored inert for display only.
        """
        principal = self._store.get_principal(principal_id)
        now = self._clock.now_ms()
        stamp = ensure_not_future(at, now) if at is not None else now
        try:
            utterance = Utterance(
                id=self._new_id("utt"),
                text=text,
                channel=channel,
                trust=compute_trust(channel, principal.role),
                source_ref=source_ref,
                at=stamp,
            )
        except ValidationError as error:
            raise ValidationFailure(f"invalid utterance: {error.errors()[0]['msg']}") from error
        self._store.create_utterance(utterance, principal.id)

        targets = list(agent_ids) if agent_ids else self._primary_agent_ids()
        parsed = parse_utterance(text)
        ingested: list[IngestedInstruction] = []
        for item in parsed.instructions:
            # The utterance keeps when it was said; its rules take effect when they are
            # recorded. Activating at a client-supplied past time would let a later ingest
            # rewrite the answer to "was this allowed at T?" for a T already answered.
            instruction = self._store.create_instruction(
                source_id=utterance.id,
                effect=item.effect,
                action_type=item.action_type,
                agent_ids=targets,
                created_at=now,
                text_span=item.text_span,
                resource_pattern=item.resource_pattern,
                max_amount=item.constraints.max_amount,
                # "for the next 2 hours": the rule stops applying then, whatever happens.
                valid_to=now + item.valid_for_ms if item.valid_for_ms else None,
            )
            inert = instruction.lineage_trust is LineageTrust.UNTRUSTED
            if not inert and not item.requires_confirmation:
                instruction = self._store.activate_instruction(
                    instruction.id, now, by=principal.id, via=ActivationKind.AUTO
                )
                self._supersede_duplicates(instruction, now)
            ingested.append(
                IngestedInstruction(
                    instruction=instruction,
                    action_type=item.action_type,
                    resource_pattern=item.resource_pattern,
                    max_amount=item.constraints.max_amount,
                    needs_confirmation=not inert and instruction.activated_at is None,
                    inert=inert,
                )
            )
        return IngestResult(utterance, ingested, parsed.unparsed)

    def confirm_instruction(self, instruction_id: str, by_principal_id: str) -> Instruction:
        self._require_owner(by_principal_id)
        now = self._clock.now_ms()
        pending = self._store.get_instruction(instruction_id)
        if pending.valid_to is not None and now >= pending.valid_to:
            raise Conflict("this rule's time limit has already passed; say it again to renew it")
        instruction = self._store.activate_instruction(
            instruction_id, now, by=by_principal_id, via=ActivationKind.CONFIRMED
        )
        self._supersede_duplicates(instruction, now)
        return instruction

    def revoke_instruction(self, instruction_id: str, by_principal_id: str) -> Instruction:
        self._require_owner(by_principal_id)
        return self._store.revoke_instruction(
            instruction_id, self._clock.now_ms(), by=by_principal_id
        )

    # --- delegation -----------------------------------------------------------------

    def delegate(
        self,
        *,
        from_agent_id: str,
        to_agent_id: str,
        action_type: str,
        by_principal_id: str,
        resource_pattern: str = "*",
        max_amount: int | None = None,
        valid_to: int | None = None,
        via_instruction: str | None = None,
    ) -> Delegation:
        """Let one agent act within a narrower scope of another's authority."""
        self._require_owner(by_principal_id)
        self._store.get_agent(from_agent_id)
        self._store.get_agent(to_agent_id)
        now = self._clock.now_ms()
        try:
            delegation = Delegation(
                id=self._new_id("dlg"),
                from_agent=from_agent_id,
                to_agent=to_agent_id,
                action_type=action_type,
                resource_pattern=resource_pattern,
                constraints=Constraints(max_amount=max_amount),
                created_at=now,
                valid_from=now,
                valid_to=valid_to,
                via_instruction=via_instruction,
            )
        except ValidationError as error:
            raise ValidationFailure(f"invalid delegation: {error.errors()[0]['msg']}") from error
        if not self._delegator_holds_authority(delegation):
            raise DelegationExceedsAuthority(
                "the delegating agent holds no authority covering this scope"
            )
        return self._store.create_delegation(delegation)

    def revoke_delegation(self, delegation_id: str, by_principal_id: str) -> None:
        self._require_owner(by_principal_id)
        self._store.revoke_delegation(delegation_id, self._clock.now_ms())

    # --- held actions ---------------------------------------------------------------

    def resolve_action(
        self, action_id: str, by_principal_id: str, *, approved: bool
    ) -> StoredAction:
        """Approve or decline an action that was held for confirmation (owner only).

        The move out of ``pending`` and the approval record are one atomic write, so two
        concurrent resolutions cannot both succeed.
        """
        self._require_owner(by_principal_id)
        stored = self._store.get_action(action_id)
        if stored.action.status is not ActionStatus.PENDING:
            raise Conflict("this action is not waiting for approval")
        new_status = ActionStatus.EXECUTED if approved else ActionStatus.DENIED
        approval = Approval(
            id=self._new_id("apr"),
            approved=approved,
            by=by_principal_id,
            at=self._clock.now_ms(),
        )
        if not self._store.resolve_pending_action(action_id, approval, new_status):
            raise Conflict("this action was already resolved")
        return StoredAction(
            stored.action.model_copy(update={"status": new_status}),
            stored.agent_id,
            stored.decision_id,
        )

    def mark_action(self, action_id: str, status: ActionStatus) -> None:
        self._store.set_action_status(action_id, status)

    def get_action(self, action_id: str) -> StoredAction:
        return self._store.get_action(action_id)

    # --- agent tokens ---------------------------------------------------------------

    def revoke_token(
        self,
        token_id: str,
        by_principal_id: str,
        *,
        agent_id: str | None = None,
        expires_at_ms: int | None = None,
    ) -> TokenRevocation:
        """Revoke one agent token (owner only). Revoking it again returns the first record."""
        self._require_owner(by_principal_id)
        if agent_id is not None:
            self._store.get_agent(agent_id)  # NotFound for a token from another tenant
        return self._store.revoke_token(
            TokenRevocation(
                token_id=token_id,
                agent_id=agent_id,
                expires_at=expires_at_ms,
                revoked_at=self._clock.now_ms(),
                by=by_principal_id,
            )
        )

    def token_revoked(self, token_id: str) -> bool:
        return self._store.token_revoked(token_id)

    # --- checks and explanations ----------------------------------------------------

    def check(
        self, request: CheckRequest, *, persist: bool = True, request_id: str | None = None
    ) -> CheckResult:
        # An id that is not an agent of this tenant is an error, not a decision: nothing is
        # recorded, so a caller cannot write arbitrary (or another tenant's) ids into the log.
        if request.agent_id not in self._known_agents:
            self._store.get_agent(request.agent_id)
            self._known_agents.add(request.agent_id)  # agents are never deleted within a tenant
        return check_authority(
            self._store,
            self._store,
            request,
            clock=self._clock,
            pdp=self._pdp,
            persist=persist,
            request_id=request_id,
            id_factory=self._new_id,
        )

    def explain(self, decision_id: str) -> Explanation:
        return explain(self._store.get_decision(decision_id))

    # --- internals ------------------------------------------------------------------

    def require_owner(self, principal_id: str) -> None:
        """Raise `NotFound` for an unknown principal and `NotOwner` for a non-owner."""
        if self._store.get_principal(principal_id).role is not Role.OWNER:
            raise NotOwner("only an owner can do this")

    def _require_owner(self, principal_id: str) -> None:
        self.require_owner(principal_id)

    def _supersede_duplicates(self, instruction: Instruction, at: int) -> None:
        """A newly active rule replaces older active rules with the same effect and scope.

        Stating a limit twice ("up to 500", later "up to 5000") must leave one rule in force,
        and a later revocation or quarantine of the newer one must not silently revive the
        older through anything but the documented rules (AUTH-009).
        """
        records = self._store.list_instructions(status="active")
        mine = {r.agent_id for r in records if r.instruction.id == instruction.id}
        scope = next((r.scope for r in records if r.instruction.id == instruction.id), None)
        if scope is None:
            return
        older = {
            r.instruction.id
            for r in records
            if r.instruction.id != instruction.id
            and r.instruction.effect is instruction.effect
            and r.scope.action_type == scope.action_type
            and r.scope.resource_pattern == scope.resource_pattern
            and r.agent_id in mine
            and (r.instruction.activated_at or 0) <= at
        }
        for old_id in sorted(older):
            self._store.supersede(instruction.id, old_id, at)

    def _primary_agent_ids(self) -> list[str]:
        ids = [a.id for a in self._store.list_agents() if a.kind is AgentKind.PRIMARY]
        if not ids:
            raise ValidationFailure("there is no primary agent to apply rules to")
        return ids

    def _delegator_holds_authority(self, delegation: Delegation) -> bool:
        """Probe: does the delegator have allow or confirm for some action in this scope?"""
        resource = _sample_resource(delegation.resource_pattern)
        for action_type in ACTION_TYPES:
            if not action_type_covers(delegation.action_type, action_type):
                continue
            args = (
                {"amount": delegation.constraints.max_amount}
                if action_type == "refund.issue" and delegation.constraints.max_amount is not None
                else {}
            )
            request = CheckRequest(
                agent_id=delegation.from_agent,
                action_type=action_type,
                resource=resource,
                args=args,
                as_of=self._clock.now_ms(),
            )
            outcome = check_authority(
                self._store, None, request, clock=self._clock, pdp=self._pdp, persist=False
            )
            if outcome.decision.result in (Result.ALLOW, Result.CONFIRM):
                return True
        return False
