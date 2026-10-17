"""S5 and S6: the probe programs themselves must be able to fail."""

from typing import Any

from fakes.memory_backend import MemoryTenantBackend
from fakes.memory_store import InMemoryStore

from mandate.eval.concurrency import AgentPlan, Observation, judge, revocation_lag
from mandate.eval.isolation import run_isolation, summarise
from mandate.models.domain import Agent, AgentKind, Result

# --- S6 oracle ------------------------------------------------------------------------


def plan(*, has_rule: bool, revoked: bool = False) -> AgentPlan:
    agent = Agent(id="agt_" + "A" * 26, name="a", kind=AgentKind.PRIMARY)
    return AgentPlan("t", agent, has_rule, "ins_x" if has_rule else None, revoked)


def obs(action: str, result: Result, start: float, end: float) -> Observation:
    return Observation(action, start, end, result)


def test_oracle_accepts_the_correct_answers() -> None:
    steady = plan(has_rule=True)
    seen = [obs("email.read", Result.ALLOW, 0, 1), obs("email.delete", Result.DENY, 1, 2)]
    assert judge(steady, seen, None) == []
    assert judge(plan(has_rule=False), [obs("email.read", Result.DENY, 0, 1)], None) == []


def test_oracle_rejects_wrong_answers_and_errors() -> None:
    steady = plan(has_rule=True)
    assert judge(steady, [obs("email.read", Result.DENY, 0, 1)], None)
    assert judge(steady, [obs("email.delete", Result.ALLOW, 0, 1)], None)
    assert judge(plan(has_rule=False), [obs("email.read", Result.ALLOW, 0, 1)], None)
    assert judge(steady, [Observation("email.read", 0, 1, None, "boom")], None)


def test_oracle_timing_window_for_a_revoke() -> None:
    racing = plan(has_rule=True, revoked=True)
    window = (10.0, 12.0)
    ok = [
        obs("email.read", Result.ALLOW, 0, 5),  # finished before the revoke began
        obs("email.read", Result.ALLOW, 9, 11),  # overlaps: either answer is fine
        obs("email.read", Result.DENY, 10, 13),  # overlaps
        obs("email.read", Result.DENY, 13, 14),  # began after it finished
    ]
    assert judge(racing, ok, window) == []
    assert judge(racing, [obs("email.read", Result.DENY, 0, 5)], window)  # denied too early
    assert judge(racing, [obs("email.read", Result.ALLOW, 13, 14)], window)  # allowed too late
    undone = [obs("email.read", Result.DENY, 10, 11), obs("email.read", Result.ALLOW, 11, 11.5)]
    assert judge(racing, undone, window)  # an allow after a deny, inside the window


# --- S5 harness ----------------------------------------------------------------------


def test_isolation_probes_find_nothing_in_a_correct_backend() -> None:
    probes = run_isolation(MemoryTenantBackend, lambda tenant_id: None)
    assert len(probes) == 60
    assert summarise(probes).successes == 0, [p for p in probes if p.leaked]


class SharedStoreBackend(MemoryTenantBackend):
    """A deliberately broken backend: every tenant reads and writes one shared store."""

    def __init__(self) -> None:
        super().__init__()
        self.shared = InMemoryStore()

    def create(self, tenant_id: str, name: str, now_ms: int) -> Any:
        tenant = super().create(tenant_id, name, now_ms)
        self.stores[tenant_id] = self.shared
        return tenant


def test_isolation_probes_catch_a_backend_that_shares_data() -> None:
    probes = run_isolation(SharedStoreBackend, lambda tenant_id: None)
    assert summarise(probes).successes > 10


def test_revocation_lag_counts_only_allows_that_started_inside_the_window() -> None:
    allow, deny = Result.ALLOW, Result.DENY
    seen = [
        Observation("email.read", 0.5, 0.6, allow),  # before the revoke began
        Observation("email.read", 1.010, 1.020, allow),  # inside the window
        Observation("email.read", 1.030, 1.040, allow),  # inside, the latest
        Observation("email.delete", 1.035, 1.045, deny),  # not the revoked action
        Observation("email.read", 1.060, 1.070, deny),  # after the window
    ]
    lag = revocation_lag(seen, (1.0, 1.050))
    assert round(lag.window_ms) == 50 and lag.allows_in_window == 2
    assert lag.last_allow_ms is not None and round(lag.last_allow_ms) == 30
    assert revocation_lag(seen[-1:], (1.0, 1.050)).last_allow_ms is None
