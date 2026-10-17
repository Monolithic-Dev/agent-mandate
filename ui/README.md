# Web console

React, Vite, TypeScript and Cytoscape.js, with Radix primitives (dialogs, tooltips, tabs, menus), Motion for animation, Sonner toasts, a cmdk command palette and Lucide icons. It tells the story in [docs/ux-flows.md](../docs/ux-flows.md): a scenario run side by side, why a decision was made, rules and their state, a rule's blast radius and replay, and the evaluation.

| Page | What it shows |
|---|---|
| `/` Demo | Pick a scenario, run it for a baseline and Agent Mandate side by side, watch the unauthorised-actions counter. Reset the seeded demo tenant. |
| `/tenants`, `/tenants/:tid` | Tenants as a searchable grid; a tenant's summary tiles and tabs for what is waiting for the owner's approval (approve, decline, or make a single-use approval link), a tenant's rules (confirm, revoke), decision log, activity, graph and (admins) alerts. |
| `/tenants/:tid/decisions/:did` | The explanation, the chain from the owner's words to the agent, the verification against the graph, the path on the graph. |
| `/tenants/:tid/instructions/:iid` | A rule's blast radius, a replay without it (on a throwaway copy), quarantine and release. |
| `/eval` | The latest evaluation from `MANDATE_RESULTS_DIR`. |
| `/approve#<token>` | One held action from an approval link: who asked, what, why it is held; approve or decline. The link is the credential; the token stays in the URL fragment, so it never reaches a server log. |

## Run it

With FalkorDB and the API running (see the main README):

```
cd ui
npm install
npm run dev        # http://localhost:5173
```

The dev server proxies `/v1` to the API (`MANDATE_API_URL`, default `http://127.0.0.1:8000`) and adds the API key to each request there, so there is nothing to sign in to. It reads `MANDATE_UI_KEY`, or else `MANDATE_API_KEY`, from the repository's `.env` or the environment. The key never reaches the browser: do not give it a `VITE_` prefix, which would compile it into the bundle. Set `MANDATE_UI_AUTH=login` to send no key and sign in as a user instead, as in production.

In Docker, `docker-compose.prod.yml` runs the console as an unprivileged nginx on port 8080 that serves the build and proxies `/v1` to the API. By default it adds no key: people sign in. Create the first admin on the server with `python -m mandate.users add you@example.com --role admin`; admins then invite others from **Users**. Setting `MANDATE_UI_KEY` instead signs everyone in with that key's role (only on localhost).

**Rule studio** (`/tenants/<id>/studio`, from the tenant page): type a rule in the owner's words and, before saving, see the rules it makes (with time limits and which need confirmation), what it did not understand, the live rules it overlaps, and which recent requests would be decided differently; then save it, or save and confirm as the owner. Beside it, try any action as a dry run and see the decision and its chain without recording anything.

**Graph explorer** (a tenant's Graph tab): search for a node by what it says (press <kbd>/</kbd>), hide kinds of node, and pick a node to see its properties and neighbours. **Trace lineage** fades everything except what the node came from (the people, sayings and rules behind it) and what it led to (actions and decisions); walking a trace does not pull in an agent's unrelated rules. The picked node and the trace are in the address (`?tab=graph&node=<id>&trace=1`), so a view can be shared as a link. Every answer is also in the table view and the inspector, so none of it needs the canvas.

**Phones.** Under 860px the sidebar becomes a menu drawer, and the approvals, decisions, rules and users tables become labelled cards (a table opts in with `className="stack"` and a `data-label` on each cell), so Approve and Decline are never off-screen. A browser test fails if any page scrolls sideways at 390px.

**Activity** (a tenant tab): decisions over the last day or week as a stacked bar per hour (or six hours) by outcome, with a hover tooltip, a legend with counts and a table view; the outcome colours are validated for colour-blind separation in both themes. Beside it, the most common reasons, actions and agents, and check latency (median and p95). **Alerts** (a tenant tab, admins): Slack and JSON webhooks that tell the owner, with a one-time approval link, the moment an action is held.

**Signed in, the console has:** an account menu (change password, where you are signed in, sign out everywhere); **Users** (admins with every tenant: invite, role and tenant access, reset a password, sign someone out, disable); **Audit log** (admins: every change as a sentence, filters, CSV export). Viewers see everything in their tenants with the changing actions disabled and a note saying why.

## Check it

```
npm run lint       # TypeScript, strict
npm test           # vitest: components and the API client
npm run build
E2E_BASE_URL=http://localhost:5173 npm run e2e   # Playwright smoke tests against a running stack
```

`e2e/a11y.spec.ts` audits every page with [axe](https://github.com/dequelabs/axe-core) against WCAG 2.2 AA in the light and dark themes (and the sign-in page and the phone menu), and a violation fails the run with the rule, the element and how to fix it. `e2e/screenshots.spec.ts` regenerates the README's images from a running, seeded stack (`README_SHOTS=../docs/images npx playwright test screenshots`) and is skipped otherwise.

The smoke tests use an installed Chrome or Edge (`E2E_CHANNEL`, default `msedge` on Windows and `chrome` elsewhere), so no browser download is needed. They run in CI against the production stack.

## Design

- **Shell.** A collapsible sidebar, breadcrumbs in the top bar, and a command palette on <kbd>Ctrl</kbd>/<kbd>⌘</kbd>+<kbd>K</kbd> for pages, tenants, the demo reset and the theme. The approval page stands alone, without the console around it, because the owner opening it is not an operator.
- **Theme.** Light, dark or the system's; the choice is remembered in the browser. Colours are tokens in `src/styles.css`, with text contrast of at least 4.5:1 in both themes. Fonts (Inter, JetBrains Mono) are bundled, so the console makes no third-party requests.
- **Feedback.** Changes that run something (approve, decline, revoke, quarantine) ask first in an accessible dialog; outcomes appear as toasts; loading shows skeletons and empty lists say what will appear there.
- **Motion.** Page transitions, entering and leaving rows, the sliding nav and tab indicators, numbers that pop when they change, animated bars and a playback progress bar. All of it stops when the system asks for reduced motion.

## Notes

- An approval link works on any page that can reach the API's `/v1/approval-links` routes, which need no key. The console still proxies every other `/v1` call with its own key, so if owners open links on the console, the console must be reachable by them: put it behind your login, or serve the `/approve` page alone.
- A tenant page updates itself while it is open (a **live** badge by the title): new decisions, actions waiting for approval and rule changes appear without a reload, from `GET /v1/tenants/:tid/events`. A new held action also raises a toast.
- Runs are deterministic and return their whole timeline at once; the page reveals it one event at a time (all at once when the system asks for reduced motion). There is no live-model mode yet.
- Every graph has a table alternative, every result has an icon and a word, and new events are announced in a live region.
- Pages that draw the graph load Cytoscape on demand, so the demo page loads without it.
