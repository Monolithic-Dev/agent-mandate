# Judge Q&A and walkthrough

Status: v1.0 · 2026-10-07. Questions a reviewer is likely to ask, with answers grounded in this repository. Rules 12 and 13 of the hackathon require participants to understand and explain the work: read the code named under each answer until you can say it without this page. If an answer here is wrong or out of date, fix the page.

## The thirty-second version

Agents keep rules like "confirm before deleting" in memory, and memory gets summarised, so the rule is lost. Text planted in an email can look like an order from the owner. Agent Mandate puts the rules in a graph outside the agent. Every tool call goes through a gateway that asks the graph one question: is there an unrevoked chain from something a trusted human actually said to this action? The answer is `allow`, `confirm` or `deny`, and the chain is the explanation.

## The graph model in plain words

- A **Principal** (a person) says an **Utterance**. Its **trust** comes from the channel and the person's role: the owner typing directly is trusted; an email body is not.
- An **Instruction** (a rule: allow, deny or confirm some action on some resource) is **expressed by** an Utterance, or by a **Summary** that was **derived from** utterances or other instructions.
- An Instruction **applies to** Agents. A **Delegation** passes some of one agent's authority to another and can only narrow it.
- A **Decision** records each check: it **checked** an **Action** and **used** certain Instructions.
- Code: `docs/data-model.md`, `src/mandate/models/domain.py`, `src/mandate/graph/queries/`.

## Questions

**Why does this need a graph? Could Postgres do it?**
Three things are naturally graph questions: (1) *lineage*: does a rule's origin, through any number of summaries and derived rules, reach a trusted utterance? (variable-length upward traversal, `q04_*`); (2) *delegation chains*: every path from a delegating agent to this one, each narrowing the scope (`q02_delegation_chains`); (3) *blast radius*: everything downstream of a mistaken rule, in both directions (`q05_blast_radius_step`, `lineage/blast_radius.py`). Recursive SQL can express them; the point is they are the product's core queries, not decoration. **Removal test (Rule 3):** replace the store with the in-memory fake used in tests and the decision logic still runs, which is deliberate (ports and adapters) and is what lets us test the rules. What does not survive is multi-tenant isolation by graph, `GRAPH.COPY` replay on a clone, and the lineage queries at database speed. Be ready to say this plainly; do not claim the graph is the only way to compute the answer.

**Isn't this just RBAC or another MCP gateway?**
Gateways enforce policy a developer wrote. Here the policy comes from what the owner said, every allow carries a path back to that utterance, rules from untrusted content are stored but inert, and the same graph answers "as of when?" and "what if that rule had never existed?". Related work is credited in `docs/prior-art.md` (MAP-Graph, CaMeL, Agent Passport System, Charon, Progent, mcp-policy-gateway, Microsoft Agent Governance Toolkit and others). We do not claim to be first.

**How does it stop prompt injection?**
It does not stop a model reading injected text. It stops injected text from conferring authority: the email is recorded as untrusted content, a rule parsed from it is created inert and cannot be activated (the store refuses), and a summary that mixes trusted and untrusted sources is `mixed`, which can only ask for confirmation. Scenarios S2 and S3 in `src/mandate/eval/scenarios/`.

**What if the model or the parser gets the owner's sentence wrong?**
The default parser is deterministic and conservative (40 labelled sentences, `tests/data/parser_cases.csv`); anything it does not recognise is reported as unparsed, not guessed. Rules that raise limits or allow destructive actions need the owner's confirmation. A mistaken rule is handled by blast radius, quarantine and replay.

**What happens if the database is down or a write fails?**
Fail closed. A failed check is a deny with `error_kind`; if the decision cannot be written to the audit log the action is refused. Under overload the client queues and retries rejected queries (`graph/client.py`); S6 found this and the fix is regression-tested.

**How do you know it works?**
`python -m mandate.eval`: 26 scripted scenarios on a real FalkorDB, Agent Mandate against three baselines (naive, flat, static policy), Wilson confidence intervals, false blocks reported. 0 of 47 unauthorised actions executed, 0 of 36 legitimate actions blocked (95% CI up to 9.6%). S5: 0 leaks in 60 isolation probes. S6: 0 wrong answers in 1,400 concurrent checks. Mutation testing: 107 of 112 deliberate faults in the decision engine caught. Limits: scripted agents, synthetic data, no live-model result yet, and the naive baseline is a documented failure reproduced, not a measurement of any product. See `docs/claims-ledger.md` for the exact wording allowed.

**What is the weakest part?**
Say it before they do: the evaluation uses scripted agents (live-model runs are planned and will be labelled); write-heavy p95 latency under 50 simultaneous clients is 1.4 to 2.8 seconds, above our 100 ms target; authentication is a shared admin key plus signed agent tokens, not a full identity system; no external security review.

**Why separate agent and admin MCP servers?**
So an agent has no path to approval. Approval tools exist only in a second process the agent is never given. Agent identity is a signed token, never an argument.

**Which parts did you write and which did the AI write?**
Answer honestly from `AI_USAGE.md`. The assistant wrote most of the code under direction; you must be able to explain it. If you cannot yet, say what you are still learning and show the part you do understand.

## Walkthrough to rehearse (10 minutes)

1. Open `docs/data-model.md` and draw the nodes and edges on paper without looking.
2. Read `src/mandate/authority/pdp.py` (about 180 lines): candidates, then trust, then precedence, then the result. Explain deny > confirm > allow and "most recent wins".
3. Read `lineage.py` and `q04_lineage_instruction.cypher`: how an instruction's origin is found.
4. Run `python -m mandate.eval` and open the report; explain one scenario from each family (S1 to S4).
5. Run the MCP admin and agent servers (README), say a rule, watch a call be held, approve it, open the explanation.
6. Read `docs/spec/authority-semantics.md` rules AUTH-001 to AUTH-010 and match each to a test in `tests/unit/spec/`.
