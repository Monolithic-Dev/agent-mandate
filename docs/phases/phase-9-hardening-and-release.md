# Phase 9: Hardening and Release

## Header

- **Goal (done means):** edge cases are tested, the security threats are covered by tests, live-model results are collected and honestly reported, the README quotes only measured numbers, a demo video exists, and `v0.1.0` is tagged.
- **Preconditions:** Phase 7 complete; Phase 8 complete or documented as skipped.
- **Implements:** [../edge-cases.md](../edge-cases.md) (all); [../security-privacy.md](../security-privacy.md) section 5; [../testing.md](../testing.md) sections 4 to 6; [../evaluation.md](../evaluation.md) sections 6 and 7; [../roadmap.md](../roadmap.md) section 5.

## Task breakdown

1. **Branch** `chore/hardening-release`.
2. **Edge-case sweep.** For each row of [../edge-cases.md](../edge-cases.md), confirm a test exists; write the missing ones. Specifically add: `test_same_ms_opposite_effects_deny_wins`, `test_later_narrow_allow_after_broad_deny_both_orders`, `test_delegation_cycle_terminates`, `test_resource_traversal_rejected`, `test_negative_and_future_timestamps_rejected`, `test_graph_down_returns_deny_and_503`, `test_graph_copy_failure_after_retries_returns_503`, `test_revoked_rule_derived_rules_remain_until_quarantined`, `test_unknown_agent_or_principal_404`, `test_foreign_tenant_id_returns_same_404_as_missing`.
3. **Security pass.** Implement any remaining item in security-privacy.md section 5 that lacks a test; add a `gitleaks` CI stage (enable the placeholder from Phase 1); run `pip-audit` and `npm audit` and record findings in `docs/security-notes.md` (fix or justify each).
4. **Dependency and image pinning.** Pin the FalkorDB image tag and Python/Node dependency versions; update [../deployment.md](../deployment.md).
5. **Coverage.** Run `coverage run -m pytest` and meet the targets in testing.md section 4 (`authority` 95, `lineage` 90, overall 85); add tests where the report shows gaps in decision logic (not to inflate numbers elsewhere).
6. **Live runs.** With `ANTHROPIC_API_KEY` set: run S1, S2, S3, S4 and S5 (5 scenarios) × 3 repetitions for `naive`, `flat`, `mandate` in `live` mode (`python -m mandate.eval.runner --suite live --mode live --repeats 3`). Record counts, spread and total cost. Report live results in a **separate table** from stub results. Do not cherry-pick: include every run.
7. **Results.** Copy one dated `report.md` (stub) and one live `report.md` to `docs/results/<date>/`; commit them. The README table is generated from these by `scripts/render_results.py` so numbers cannot drift.
8. **README.** Write `README.md` (root): one-line pitch, the problem, what it does, architecture picture (Mermaid), run instructions (`docker compose`, seeding, demo script), results table with the dated link, limitations and non-goals, prior-art credits, docs index. Use only measured numbers; no "first", "unique" or "provably forgotten".
9. **Demo video.** Record the 3-minute script from [../roadmap.md](../roadmap.md) section 5 using `scripts/demo.ps1`; store the link in the README; keep the file locally as the fallback.
10. **Release.** Update the PRD status and change log; update docs where reality differed from the spec (the spec must match the code); `git tag v0.1.0`; create a GitHub release with the results link.
10b. **OWASP mapping and external numbers.** Look up the current OWASP list for agentic applications from its primary source (do not copy it from memory), map each item to the controls and tests here (`docs/owasp-mapping.md`), and mark items not addressed. If Phase 8b ran, add its report to `docs/results/` and quote it per claim C10 only. Compute Wilson intervals for every rate in the README table.
11. **Name check.** Search GitHub and the web for conflicts with "Agent Mandate" and decide whether to keep or rename before announcing publicly (PRD open question 1).
12. **Hackathon decision (if still relevant).** Re-read the Graph Hacks rules and the organisers' answer (if any) about existing projects; follow it exactly. Do not alter history or dates to change the apparent build timeline.

## Real-world engineering concerns

- **Reproducibility of results:** each `report.md` records the git SHA, model id, mode and date.
- **Honesty:** include false blocks and failed variants; label the stub compaction as a deterministic reproduction.
- **Operational readiness:** run the manual QA checklist from [../testing.md](../testing.md) section 6 on a clean clone (`git clone`, `.env` from the example, `docker compose up`).
- **Secrets:** run the secrets scan on the whole history before making the repository public.

## Definition of done

- [ ] A fresh clone on a clean machine reaches the working demo by following only the README.
- [ ] CI is green with lint, types, unit, integration, eval (stub thresholds), UI build and secrets scan.
- [ ] Coverage targets met.
- [ ] Stub and live reports committed under `docs/results/` and referenced from the README.
- [ ] README numbers match the committed reports (script-generated).
- [ ] Demo video recorded and linked.
- [ ] Security notes list every audit finding with a decision.
- [ ] `v0.1.0` tagged and released; docs match the code.

## Risks and blockers

| Risk | Mitigation |
|---|---|
| Live runs show Mandate false blocks or naive behaving | Report as is; adjust wording and scenarios, not the data |
| API cost higher than expected | The live set is small and capped; stop and report partial results if needed |
| Docs drift from code | Update docs in the same pull requests; final read-through against the code |
| Name conflict discovered late | Rename is a search-and-replace plus a package alias; decide in task 11 |

## Time budget

10 percent, about 10 hours. **Cut first if long:** the `pip-audit`/`npm audit` notes, extra live repetitions (minimum 1 each), the coverage push beyond the `authority` package.

## Handoff

Project is releasable. Next steps are in [../roadmap.md](../roadmap.md) section 6. Tag: `v0.1.0`.
