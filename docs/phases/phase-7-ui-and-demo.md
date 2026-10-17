# Phase 7: UI and Demo

## Header

- **Goal (done means):** the five pages and six flows in the UX spec work against the real API; the split-screen scenario run tells the S1 story in under a minute; every decision's path is highlighted on the graph; the whole demo can be run from one command.
- **Preconditions:** Phase 6 complete (all endpoints exist).
- **Implements:** [../ux-flows.md](../ux-flows.md) (all sections); [../api-spec.md](../api-spec.md) graph view, runs and eval endpoints; [../roadmap.md](../roadmap.md) section 5 (demo script).

## Task breakdown

1. **Branch** `feat/ui`.
2. **Scaffold** `ui/` with Vite React TypeScript: `npm create vite@latest ui -- --template react-ts`; add `cytoscape`, `react-router-dom`, `vitest`, `@testing-library/react`, `@playwright/test`. Configure the dev proxy in `vite.config.ts`: `/v1` → `http://localhost:8000`, with the API key read from `VITE_MANDATE_KEY` (local use only; documented as not for hosted deployments).
3. **`src/types.ts`** mirroring api-spec.md response shapes (`Decision`, `Instruction`, `BlastRadius`, `ReplayResult`, `GraphElements`, `RunEvent`, `EvalReport`). **`src/api.ts`**: typed fetch wrapper (adds the key header, parses the error format into a thrown `ApiError` with `code` and `request_id`), plus `subscribeRunEvents(runId, onEvent)` using `EventSource` (falls back to polling every 1 s on error).
4. **Components (`src/components/`):**
   - `GraphView.tsx`: Cytoscape instance; props `elements`, `highlightPath`, `onNodeClick`; shapes and colours per ux-flows.md section 4; dashed edges for untrusted lineage; a **"Show as table"** toggle rendering the same data as an accessible table; skeleton while loading; message when truncated at 500 nodes.
   - `DecisionPanel.tsx`: result badge with icon and text, reason, narrative, path list; keyboard focusable.
   - `SplitRun.tsx`: two columns (naive, mandate) with timeline chips (`owner said`, `context compacted`, `call`, `EXECUTED`, `CONFIRM`, `DENIED`), a live region (`aria-live="polite"`) announcing new events, and the footer counter `Unauthorised actions: Naive n · Mandate m`.
   - `RulesList.tsx`: rules with status chips; **Confirm** disabled with tooltip for untrusted lineage; **Revoke** with confirm dialog.
   - `BlastRadius.tsx` and `ReplayDiff.tsx`: highlight on the graph; table of decisions; Replay and Quarantine buttons with loading and error states.
   - `MetricsTable.tsx` and `LatencyChart.tsx` (simple SVG bars; no chart library needed).
5. **Pages (`src/pages/`):** `Demo.tsx` (scenario picker, mode toggle stub/live, Run, Reset), `Tenant.tsx`, `Decision.tsx`, `Instruction.tsx`, `Eval.tsx`; routes in `App.tsx`.
6. **Seed and reset for the demo:** `scripts/demo.ps1` and `scripts/demo.sh` run `docker compose up -d --build`, `python scripts/wait_for_falkordb.py`, `python scripts/seed.py --reset`, then print the UI URL. Add `POST /v1/demo/reset` (admin only, resets seeded tenants and sandbox state in about one second).
7. **Styling:** CSS variables for light and dark themes; contrast at least 4.5:1; focus rings visible; no colour-only meaning.
8. **Docker:** `ui/Dockerfile` (node build, nginx serving `dist/`, proxying `/v1` to `api`); add the `ui` service to `docker-compose.yml`.
9. **Tests:**
    - vitest: `GraphView renders nodes and highlights path`, `GraphView table toggle lists the same nodes`, `DecisionPanel shows icon and text for each result`, `SplitRun counter updates from events`, `RulesList disables confirm for untrusted`, `api.ts maps error body to ApiError`.
    - Playwright smoke (`ui/e2e/demo.spec.ts`): `demo page runs S1 and ends with 5 vs 0`, `clicking a decision highlights a path ending at the owner utterance`, `forged instruction shows greyed with disabled confirm`.
    - Manual: run the QA checklist in [../testing.md](../testing.md) section 6.

## Real-world engineering concerns

- **Error states:** every request has loading, empty and error UI; errors show the `request_id`.
- **SSE reliability:** reconnect with backoff; fallback to polling; events carry a sequence number so duplicates are ignored.
- **Performance:** cap graph elements at 500; use `layout: 'cose'` only under 150 nodes, otherwise a breadth-first layout.
- **Security:** the key lives in an env var for local use; no secrets in the bundle for hosted use (a hosted demo uses a read-only demo key and a separate proxy).
- **Accessibility:** keyboard navigation for all actions, table alternative for graphs, live regions for events.

## Definition of done

- [ ] `scripts/demo.ps1` brings the whole stack up and the demo page loads in under 3 seconds.
- [ ] Running S1 split-screen shows naive deleting five and Mandate holding the first, ending `5 vs 0`.
- [ ] Clicking any decision highlights a path from the owner utterance to the agent and scope.
- [ ] The forged rule appears greyed with disabled confirm; the denied refund shows the ignored-rule chip.
- [ ] Blast radius and replay views show the S4 oracle results.
- [ ] Eval page matches the latest `report.md`.
- [ ] vitest and Playwright smoke pass; `npm run build` and `npm run lint` pass in CI (stage enabled).
- [ ] Reset button restores demo state in under 2 seconds.

## Risks and blockers

| Risk | Mitigation |
|---|---|
| Graph UI consumes the schedule | Stick to Cytoscape defaults and the six flows; defer polish |
| SSE blocked by a proxy | Polling fallback is already specified |
| CORS or proxy problems | Single dev proxy in Vite; nginx proxy in Docker |
| Demo flakiness | Reset button, deterministic stub mode, recorded fallback video (Phase 9) |

## Time budget

14 percent, about 14 hours. **Cut first if long:** `LatencyChart`, dark theme, the Tenant page's decision log filters.

## Handoff

Phase 8 (if the gate passes) and Phase 9 can assume: a complete, demoable product. Tag: `phase-7-complete`.
