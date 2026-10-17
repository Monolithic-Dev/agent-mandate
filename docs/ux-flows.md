# UX Flows

Status: v1.0 · Last updated 2026-10-06 · Implements [PRD.md](./PRD.md) section 6.5 and the demo in [roadmap.md](./roadmap.md). The UI exists to make the authority path and the before/after difference visible. It is a React + Vite + TypeScript app using Cytoscape.js.

## 1. Pages

| Route | Page | Purpose |
|---|---|---|
| `/` | Demo | Pick a scenario, run it split-screen, watch decisions appear |
| `/tenants/:tid` | Tenant | Rules list, agents, delegations, decision log, graph |
| `/decisions/:did` | Decision | The explanation path for one decision |
| `/instructions/:iid` | Instruction | Lineage, blast radius, replay diff |
| `/eval` | Eval | Latest metrics table and the false-block list |

## 2. Core flows

### Flow A: Run a scenario split-screen (the hero flow)
1. User opens `/`, picks scenario `S1 Rule lost in summarisation`, mode `stub`.
2. Two panels start: **Naive agent** (left, red accent) and **Agent Mandate** (right, green accent), fed by `GET /v1/runs/{id}/events` (SSE).
3. A shared timeline shows events in order: owner states the rule, context compacted (a visible "summary replaced 12 messages" chip), user asks to clean the inbox.
4. Left: tool calls `email_delete ×5` appear, each marked **EXECUTED** in red.
5. Right: the first `email_delete` shows **CONFIRM** with the rule that triggered it; the agent stops and asks. The owner's scripted reply appears and the action completes or is declined.
6. A footer counter shows `Unauthorised actions: Naive 5 · Mandate 0`.

### Flow B: Why was this allowed or blocked?
1. Click any decision chip → `/decisions/:did`.
2. The graph highlights the path from the owner's utterance through the instruction and scope to the agent. A sentence under the graph reads the narrative (template-generated).
3. For a denial, the panel lists what was found and why it did not count (for example "ignored: instruction from untrusted email, lineage untrusted").

### Flow C: Forged instruction
1. Run S2. The untrusted email appears on the timeline with an **UNTRUSTED** badge.
2. The extracted rule shows as a greyed node with a dashed outline in the graph; its confirm button is disabled with the tooltip "no human origin".
3. The agent's refund attempt shows **DENIED** with the ignored-instruction chip.

### Flow D: Revoke
1. In the rules list, press **Revoke** on a delegation. The edge turns dashed grey.
2. Re-run the next agent step: **DENIED, authority revoked**, path shows the revoked edge in red.

### Flow E: Blast radius and replay
1. Open a mistaken instruction → **Blast radius**. Affected summaries, derived rules, delegations and decisions are highlighted in red on the graph; a table lists the four decisions.
2. Press **Replay without this rule**. A diff table appears: decision, was, now, reason; unchanged decisions are collapsed.
3. Press **Quarantine** to apply.

### Flow F: Evaluation
`/eval` shows a table per metric by agent kind (naive, flat, mandate), the false-block list, and the concurrency chart (latency p50 and p95).

## 3. Key screens and states

| Screen | States |
|---|---|
| Demo | idle, running, finished; per panel: waiting, call proposed, executed, held, denied, error |
| Graph view | loading, empty (no rules yet), focus mode (depth 1 to 3), highlight mode (path), truncated (over 500 nodes) |
| Decision panel | allow (green), confirm (amber), deny (red); each with an icon and a text label so colour is not the only signal |
| Rules list | pending, active, revoked, superseded, quarantined, untrusted |

## 4. Visual language

- Node shapes by label (Principal circle, Utterance rounded rectangle, Instruction hexagon, Scope tag, Agent diamond, Action square, Decision star).
- Edge labels are the relationship names. Trusted lineage edges are solid; untrusted are dashed.
- Result colours: allow green, confirm amber, deny red, quarantined purple. Always paired with text.
- Dark and light themes via CSS variables.

## 5. Accessibility

- Full keyboard navigation; focus ring visible; graph nodes reachable through a table view alternative (every graph has a "show as table" toggle).
- Colour is never the only indicator; each result has an icon and a word.
- Contrast ratio at least 4.5:1 for text.
- Live regions announce new decisions in the demo panels.

## 6. What makes the 3-minute demo feel polished

- One click starts the scenario; no setup visible.
- The compaction chip and the **EXECUTED** versus **CONFIRM** contrast are readable from across a room.
- The footer counter ends at `5 vs 0`.
- Pre-seeded tenants; a reset button restores state in one second.
- Loading states never show an empty graph for more than 300 ms (skeleton).
- A recorded fallback video exists.

## 7. Assumptions
- Desktop-first (1280 px and up). A basic responsive layout stacks the two panels on narrow screens.
