# Phase 8b: External Validation on AgentDojo (Optional, Gated)

## Header

- **Goal (done means):** a defence that wraps an AgentDojo agent pipeline with the authority engine is run on a defined subset of one task suite, and benign utility, utility under attack and attack success rate are reported against no defence and AgentDojo's simple tool-filter baseline, with confidence intervals and honest limits.
- **Preconditions:** Phases 1 to 7 complete; Phase 8 complete or skipped. The gate below passes.
- **Implements:** [../engineering-review.md](../engineering-review.md) sections 5 (change 2) and 7; [../decisions.md](../decisions.md) ADR-013; [../claims-ledger.md](../claims-ledger.md) C10.

## Go/no-go gate

All must be true; otherwise skip this phase (record "skipped: <reason>" in the risk register):

- [ ] The core evaluation (Phase 5) passes its thresholds and the lineage tools (Phase 6) work.
- [ ] `pip install agentdojo` works under Python 3.12 and a one-task smoke run completes with no defence (confirms the harness, an API key and budget).
- [ ] A budget for model calls is set in writing (estimate: tasks × injections × 3 conditions × tool-call turns; write the number down before running).
- [ ] The AgentDojo version is pinned and its pipeline-element interface has been read in the installed version (names below are placeholders until then).
- [ ] At least 8 hours remain in the effort budget.

## What is and is not being claimed

AgentDojo tasks are single-turn, so the "standing instruction" is the user's task text. To use the engine, scopes must be derived from that text (tool names and argument constraints). This tests the engine **plus a scope-synthesis step**, and it overlaps with how other systems generate per-task policies. The claim to test: *an authority graph seeded from the user's request, in which untrusted tool output carries no authority, blocks injected actions at acceptable utility cost.* No claim is made about multi-turn standing instructions from this run.

## Task breakdown

1. **Branch** `feat/agentdojo-validation`. Add an optional extra `bench = ["agentdojo"]` to `pyproject.toml`; the main install must not depend on it.
2. **Generalise action types for external tools.** Allow scope `action_type` values of the form `tool.<name>` in addition to the registry (data-model.md section 5), validated by a regex `^tool\.[a-z0-9_]{1,64}$`; resource is derived from a chosen argument (for example a recipient or file id) by a per-suite mapping table `eval/agentdojo/tool_map.yaml`. Update [../data-model.md](../data-model.md) and [../spec/authority-semantics.md](../spec/authority-semantics.md) (no rule change; AUTH-011 already covers matching) in the same pull request.
3. **Scope synthesis `eval/agentdojo/scope_synthesis.py`.** Input: the user task text and the suite's tool list. Output: candidate instructions (allow, on `tool.<name>` with optional argument constraints). Two modes, both reported: (a) **oracle scopes** derived from the task's ground-truth tool calls (upper bound on the engine alone) and (b) **LLM-synthesised scopes** from the task text only (the realistic case). Validation: only tools in the suite's list; no wildcards beyond `tool.*` for read-only tools if a flag allows it (default off); each rule's `text_span` must be a substring of the task text for mode (b).
4. **Defence element `eval/agentdojo/mandate_defense.py`.** Implements AgentDojo's pipeline element interface (verify the exact base class in the pinned version): at run start it creates a fresh tenant, records the user task as an `owner_direct` utterance, installs the synthesised instructions (owner-confirmed automatically in this harness, and labelled as such), records each tool result as an `untrusted_content` utterance, and before each tool call runs `check_authority`. `allow` passes the call through; `confirm` and `deny` return a short refusal message to the agent. Fail closed on any error. Record every decision.
5. **Runner `eval/agentdojo/run.py`.** Parameters: suite (start with one, for example `workspace`), user-task subset (for example 10 tasks chosen by a fixed seed and listed in the report), injection tasks (for example 3), attack (the default `important_instructions` or the pinned version's equivalent), model id, conditions: `none`, `tool_filter` (AgentDojo's baseline), `mandate-oracle`, `mandate-synth`. Output JSONL per run and a summary.
6. **Metrics `eval/agentdojo/metrics.py`.** Benign utility (no attack), utility under attack, attack success rate; each with n and a **Wilson interval**; plus decisions per run, false blocks (benign tasks that failed because of a hold or deny), and mean added latency. Write `docs/results/<date>/agentdojo.md`.
7. **Tests:** `test_tool_map_covers_suite_tools`, `test_scope_synthesis_rejects_unknown_tools`, `test_oracle_scopes_allow_ground_truth_calls`, `test_injected_tool_call_denied_when_not_in_scope`, `test_untrusted_tool_result_cannot_activate_instruction`, `test_defence_fails_closed_on_error`, `test_wilson_interval_known_values`.
8. **Report honestly:** list tasks where the defence blocked a legitimate step; give the cost; state that the subset is small and chosen by fixed seed; do not compare to published numbers from other papers (different models, subsets and attacks).

## Real-world engineering concerns

- **Cost and time:** every condition multiplies model calls; cap turns per run; run sequentially with resume (skip completed run ids); log spend.
- **Non-determinism:** temperature 0 where the provider allows; report repeat variance with at least 2 repeats if budget permits.
- **Isolation:** one tenant per run, dropped afterwards; no shared state between conditions.
- **Dependency risk:** the benchmark package may change; pin the version and record it in every report.

## Definition of done

- [ ] A smoke run completes for all four conditions on one task.
- [ ] The full subset run completes and `docs/results/<date>/agentdojo.md` exists with n, intervals, costs, versions, seeds and the list of blocked benign steps.
- [ ] The README or claims ledger quotes only numbers from that file, and describes the claim as in "What is and is not being claimed".
- [ ] If the gate failed: the phase is annotated "skipped: <reason>" here and in the roadmap.

## Risks and blockers

| Risk | Mitigation |
|---|---|
| Scope synthesis is weak, so utility drops | Report oracle and synthesised modes separately; the oracle mode isolates the engine |
| Pipeline interface differs from placeholders | Read the pinned version first; adapt the one defence file |
| Budget exceeded | Smaller subset; fewer injections; stop and report partial results |
| Results look like a re-implementation of existing policy generators | Say so; the contribution is provenance and replay, not scope synthesis |

## Time budget

Optional; about 8 hours, taken from Phase 9's slack, not from earlier phases. **Cut first if long:** repeats, the second injection task, the LLM-synthesised mode (keep oracle mode).

## Handoff

Phase 9 can assume the AgentDojo result exists (or is documented as skipped). Tag: `phase-8b-complete` or `phase-8b-skipped`.
