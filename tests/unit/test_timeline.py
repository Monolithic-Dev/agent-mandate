"""Every scripted event in every scenario can be described for the console."""

from mandate.eval.scenario import AgentAttempt, load_scenarios
from mandate.eval.timeline import describe


def test_every_event_in_every_scenario_has_a_sentence() -> None:
    for scenario in load_scenarios():
        for event in scenario.timeline:
            text = describe(event)
            assert text and "\n" not in text, (scenario.id, event)
            if isinstance(event, AgentAttempt):
                assert event.tool in text
