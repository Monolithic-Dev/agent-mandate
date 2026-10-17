"""The live evaluation runner, with a model that does exactly what it is asked."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fakes.memory_store import InMemoryStore

from mandate.eval.live import (
    PHRASES,
    prompt_only_system,
    run_one,
    skip_reason,
    summarise,
    task_for,
)
from mandate.eval.scenario import SCENARIO_DIR, load_scenarios
from mandate.llm import Message, Reply, ToolCall


@contextmanager
def memory_provider() -> Iterator[InMemoryStore]:
    yield InMemoryStore()


class Obedient:
    """Calls every scripted attempt of a scenario in its first turn, then says it is done."""

    name = "obedient"

    def __init__(self, calls: list[tuple[str, dict[str, Any]]]) -> None:
        self.calls = calls
        self.turn = 0
        self.systems: list[str] = []

    def complete(
        self, system: str, messages: list[Message], tools: Any = None, *, max_tokens: int = 1024
    ) -> Reply:
        self.systems.append(system)
        self.turn += 1
        if self.turn == 1:
            made = tuple(ToolCall(str(i), tool, args) for i, (tool, args) in enumerate(self.calls))
            return Reply("", made, "tool_use", {"input": 100, "output": 20})
        return Reply("Done.", (), "end", {"input": 50, "output": 5})


def scenario(sid: str):  # type: ignore[no-untyped-def]
    return next(s for s in load_scenarios(SCENARIO_DIR) if s.id == sid)


def test_a_lost_rule_is_not_in_the_prompt_and_the_task_lists_each_attempt() -> None:
    s1 = scenario("S1_rule_lost_v1")
    prompt = prompt_only_system(s1)
    # Compaction dropped the only sentence, which said to confirm: nothing is left to remember.
    assert "confirm" not in prompt and "The person has told you" not in prompt
    task = task_for(s1)
    assert "Delete message m-1." in task and task.count("\n") == len(s1.attempts())
    assert all(a.tool in PHRASES for a in s1.attempts())


def test_an_obedient_model_deletes_without_the_gateway_and_is_held_with_it() -> None:
    s1 = scenario("S1_rule_lost_v1")
    calls = [(a.tool, a.args) for a in s1.attempts()]
    prompt_only = run_one(s1, "prompt-only", 0, Obedient(calls), memory_provider, max_steps=4)
    assert (prompt_only.unauthorised, prompt_only.non_allow) == (5, 5)
    assert prompt_only.legit_done == 3 and prompt_only.held_right == 0

    mandate = run_one(s1, "mandate", 0, Obedient(calls), memory_provider, max_steps=4)
    assert (mandate.unauthorised, mandate.non_allow) == (0, 5)
    assert (mandate.held_right, mandate.legit_done) == (5, 3)
    assert mandate.off_script_executed == 0 and mandate.tokens == {"input": 150, "output": 25}

    summary = summarise([prompt_only, mandate])
    assert summary["prompt-only"]["unauthorised"].format().startswith("5/5")
    assert summary["mandate"]["unauthorised"].format().startswith("0/5")


def test_a_call_the_scenario_never_scripted_is_counted_apart() -> None:
    s1 = scenario("S1_rule_lost_v1")
    stray = [("file_write", {"path": "notes.txt", "content": "x"})]
    run = run_one(s1, "prompt-only", 0, Obedient(stray), memory_provider, max_steps=4)
    assert run.off_script_executed == 1 and run.unauthorised == 0


def test_scenarios_that_cannot_be_one_task_are_skipped_with_a_reason() -> None:
    reasons = {s.id: skip_reason(s) for s in load_scenarios(SCENARIO_DIR)}
    assert reasons["S1_rule_lost_v1"] is None
    assert any(reason == "more than one agent" for reason in reasons.values())
    assert any(reason == "direct engine checks" for reason in reasons.values())
    assert any(reason == "events between attempts" for reason in reasons.values())
