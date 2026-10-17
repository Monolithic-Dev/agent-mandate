"""A small test world: one tenant with an owner, an outsider and two agents."""

from __future__ import annotations

from typing import Any

from fakes.memory_store import InMemoryStore
from mandate.authority.check import CheckResult, check_authority
from mandate.models.domain import Agent, AgentKind, CheckRequest, Principal, Role


class World:
    """``store`` may be the in-memory fake (default) or a ``FalkorBuilder``."""

    def __init__(self, store: Any | None = None) -> None:
        self.store = store if store is not None else InMemoryStore()
        self.clock = self.store.clock
        self.owner: Principal = self.store.add_principal("Dana", Role.OWNER)
        self.outsider: Principal = self.store.add_principal("unknown-sender", Role.EXTERNAL)
        self.main: Agent = self.store.add_agent("main", AgentKind.PRIMARY)
        self.sub: Agent = self.store.add_agent("sub", AgentKind.SUB)

    def check(
        self,
        action_type: str,
        resource: str = "inbox/m-1",
        args: dict[str, Any] | None = None,
        *,
        agent: Agent | None = None,
        as_of: int | None = None,
        persist: bool = True,
    ) -> CheckResult:
        request = CheckRequest(
            agent_id=(agent or self.main).id,
            action_type=action_type,
            resource=resource,
            args=args or {},
            as_of=as_of,
        )
        return check_authority(self.store, self.store, request, clock=self.clock, persist=persist)
