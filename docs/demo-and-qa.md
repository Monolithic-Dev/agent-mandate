# Demo Preparation and Tough Questions

Status: v1.0 · Last updated 2026-10-06. Complements the demo script in [roadmap.md](./roadmap.md) section 5 and the UI flows in [ux-flows.md](./ux-flows.md). Use this before any demo, review or interview.

## 1. Demo preparation checklist

Day before:
- [ ] `docker compose up -d --build` from a clean clone works using only the README.
- [ ] `python -m mandate.seed --reset` and the reset button restore the demo state.
- [ ] Stub mode scenarios S1 to S4 run end to end; the footer shows `Naive 5 · Mandate 0` for S1.
- [ ] Latest evaluation report is committed in `docs/results/` and matches the Eval page.
- [ ] A recorded fallback video exists locally and plays offline.
- [ ] No API key visible on screen; `.env` closed; terminal history clear.
- [ ] Browser zoom 110 to 125 percent, dark theme off for projectors, notifications silenced.

Five minutes before:
- [ ] `/healthz` returns ok; demo page loads in under 3 seconds.
- [ ] Reset the demo state once; run S1 once to warm up.
- [ ] Have the explanation page for one decision open in a second tab.

If something breaks live: say what you expected, switch to the recorded video, and continue. Do not debug on stage.

## 2. Recording the demo video

1. Follow the 3-minute script in [roadmap.md](./roadmap.md) section 5.
2. Record at 1080p, system audio off, voice-over after.
3. Show numbers only from the committed report.
4. End on the evaluation table, including the false-block row.

## 3. Tough questions and honest answers

| Question | Answer |
|---|---|
| "Isn't this just role-based access control?" | Partly, and we say so. What goes beyond it is authority that requires provenance back to a trusted human utterance (with `mixed` trust to defeat laundering), as-of queries, blast radius and replay on a cloned graph, one graph per tenant, and an evaluation that reports false blocks. If those do not matter in the measurements, a simpler store would do. |
| "Why not Postgres?" | A relational store can model the chains. The graph earns its place through lineage closure, `GRAPH.COPY` for replay, per-tenant graphs and, optionally, max-flow. We do not claim the graph is the only way; see ADR-002. |
| "Others already do delegation gateways. What is new?" | We do not claim novelty of mechanism. We credit mandatum, the Agent Passport System, Charon, CaMeL, MAP-Graph and others ([prior-art.md](./prior-art.md)). The contribution is a small, open, measured combination with the baseline comparison. |
| "Your baseline is rigged." | Three kinds are compared: `naive` (rules in prompt with compaction), `flat` (rules in prompt, never compacted, provenance-blind) and `mandate`. `flat` passes S1, and we report that. The stub compaction reproduces a documented failure deterministically, and live runs are reported separately. |
| "Do the stubs prove anything about real models?" | They prove properties of the gateway under controlled inputs. Live runs on a small sample show how a real model behaves; both are reported and labelled. |
| "Does it stop prompt injection?" | No. It limits what an injected instruction can authorise. The model can still be manipulated in what it says or reads. |
| "What about false blocks?" | They are a headline metric. The report lists every legitimate probe that was blocked or held, with the reason. |
| "What if the admin key leaks?" | Out of scope for v1 (single local admin key). The production plan is per-tenant OAuth, short-lived agent tokens and an external append-only audit log. |
| "Can the agent grant itself authority?" | The agent profile exposes no authority tools, identity comes from a token, and untrusted text cannot become authority. There are tests for each. |
| "Is replay trustworthy?" | Replay clones the graph and re-evaluates recorded actions at their original times with the suspect rule excluded; the result is compared with a hand-written oracle in S4. It does not replay model behaviour, only authority decisions. |
| "Why a graph database for something this small?" | The demo is small by design; the questions (derivation closure, as-of, clones, tenant isolation) are graph-shaped, and the measurements show whether that matters. |
| "Was this built for a hackathon?" | It is a personal project. Whether it is submitted anywhere depends on the organisers' rules; the history has not been altered. |
| "What would you do next?" | Real adapters with a privacy review, signed instruction records, an external audit log, per-tenant OAuth, a policy editor ([roadmap.md](./roadmap.md) section 6). |

## 4. Interview framing (two minutes)

1. **Problem:** agents keep rules in memory; memory gets summarised; planted text can look like orders; logs cannot say who authorised an action.
2. **Idea:** rules and authority live in a graph and are enforced at the tool boundary; instructions without a path back to the owner carry no authority.
3. **Evidence:** the scenario suite and baselines, including false blocks.
4. **Trade-offs and limits:** not first, not an injection defence, synthetic data.
5. **What I learned:** designing a gateway, graph modelling, evaluation design, honest reporting.
