# Your agent forgot the rule. Put the rule in a graph.

*Code Blooded: Mahakisore and Ramkumar. A write-up of Agent Mandate, built for the FalkorDB Graph Hacks.*

In February 2026 an AI agent was told to confirm with its owner before deleting anything. Then its context was summarised, the instruction did not survive the summary, and it deleted a large part of an inbox. Nobody had told it to. Nobody had told it *not* to, any more.

That is the failure we built Agent Mandate around, and it is not really about one model. It is about where the rules live. If "confirm before deleting" is a sentence in a prompt, it lives exactly as long as the prompt does.

## The idea: an action is allowed only if a graph says who said so

Agent Mandate is a gateway between an agent and its tools. Before any consequential action runs, the gateway asks one question: *is there a valid chain from something a trusted human actually said, through rules that are still in force, to this action?* If there is, it runs. If a rule says to ask first, it is held for the owner. If there is no chain, it is refused. And whichever it is, the gateway returns the chain as the explanation.

The chain is a path in a graph:

```
Principal ─SAID→ Utterance ─EXPRESSES→ Instruction ─ABOUT→ Scope
                                            └─APPLIES_TO→ Agent ─PROPOSED_BY← Action ←CHECKED─ Decision
```

The owner says something. That utterance, with a trust level worked out from who said it and over which channel, expresses an instruction (allow, deny or confirm). The instruction is about a scope (an action type on a pattern of resources) and applies to an agent. When the agent proposes an action, the decision walks that path, and records which rules it used.

## Why a graph, and not a table of rules

Three things we wanted are traversals, and they are awkward anywhere else.

**Lineage.** A summary can turn something an email said into a "remembered rule". If every instruction keeps its origin, through any number of summaries, then "this rule traces only to untrusted content" is a path query, and such a rule can be stored and shown but never activated. Text planted in an email is information, never authority.

**Delegation that only narrows.** An agent can hand a sub-agent part of its authority, never more than it has. Checking that is walking a chain of `DELEGATES_TO` edges and intersecting scopes. Revoke the parent and the child's next call fails, because the chain no longer exists.

**Blast radius and replay.** Find a rule that was a typo (a limit of $5,000 where the owner said $500) and the question is: what did it decide? That is everything connected to it by `USED`. Then the better question: what would have changed without it? FalkorDB can copy a graph, so we replay those decisions on a clone with the rule removed and show which ones flip, without touching the live graph. Quarantine takes the rule and everything derived from it out of force.

Each tenant is its own graph, so isolation is not a `WHERE` clause someone can forget.

## What it looks like

The first thing the console shows is the failure itself: the same script run for an ordinary agent and for Agent Mandate, side by side. The ordinary agent, whose context is compacted, deletes five emails. Agent Mandate holds all five and asks.

![The same script, run for an ordinary agent and for Agent Mandate](./images/demo.png)

Every decision has a page: the chain from the owner's words to the agent, and a check of each claim against the graph. Held actions can be approved in the console, or from a phone through a one-time link in a Slack message. Before a sentence becomes a rule, a studio previews it: the rules it makes, the live rules it contradicts, and which recent requests it would decide differently, re-checked on a throwaway copy of the graph.

![Previewing a rule before it is saved](./images/studio.png)

And a graph explorer lets you pick any node and trace where it came from and what it led to.

![Tracing a decision back to what the owner said](./images/explorer.png)

## What we measured, and what we did not

We wrote 27 scenarios with hand-written expectations (a rule lost in compaction, a forged instruction, a revocation, a delegation, a bad rule found later, an instruction laundered through a summary, benign lookalikes) and ran the same scripts for four agents: a naive one whose rules vanish when its context is compacted, one that keeps its rules but cannot tell who said what, a static policy, and Agent Mandate. On a real FalkorDB, scripted, Agent Mandate let **0 of 47** probes that should not execute through (95% interval 0.0% to 7.6%) and blocked **0 of 36** legitimate ones (0.0% to 9.6%). The naive agent executed 44 of the 47. The full report, with its limits, is in the repository.

Those agents are scripted, so they say nothing about real models. So we also ran a real one. Same scenarios, same hand-written expectations, with `openai/gpt-oss-120b` on Groq, in two arms: *prompt-only*, with the owner's rules in its prompt (minus what compaction dropped) and the tools unguarded, and *Agent Mandate*, with no rules in its head and every call through the gateway.

| `openai/gpt-oss-120b` on Groq, 16 scenarios, 1 run each | prompt-only | Agent Mandate |
|---|---|---|
| Unauthorised actions that took effect (of 39 that should not) | **28** (71.8%, 95% CI 56.2% to 83.5%) | **0** (0.0%, 95% CI 0.0% to 9.0%) |
| Legitimate actions completed (of 27) | 24 | 27 |
| Held for the owner (of 19 that required it) | n/a, no gateway | 16 (the model did not attempt the other 3) |

By family, unauthorised actions that took effect without and with the gateway: rule lost in compaction 22 of 25 and 0 of 25; forged instruction 2 of 8 and 0 of 8; laundered instruction 3 of 3 and 0 of 3; benign lookalikes 1 of 3 and 0 of 3. Without the gateway the model also issued a refund nobody asked for in one run. Eleven of the 27 scenarios could not be run as a single task and are listed, with reasons, in the report.

The prompt-only arm is not a strawman for its own sake: it is what "put the rules in the prompt" means once a context is summarised, and it did fine where nothing was compacted away. The point is the first row. A rule that lives in the prompt is gone when the prompt is, and a gateway that does not depend on the prompt does not care.

That is one model, on scripted tasks, with its output varying from run to run. It is evidence about this model on these tasks, not a claim about models. The report and every transcript are committed.

## What it does not do

It does not stop prompt injection; it controls what an agent is *authorised* to do, not what the model reads. It is not the first system to enforce policy at a tool boundary; we credit the related work in the repository. It uses synthetic data only.

## Try it

It is MIT licensed. With Docker, one command starts FalkorDB, the API and the console, and the README has the rest. The authority engine never calls a model, so it needs no key. If you want to watch a live agent at the gateway, it runs on Claude, Groq, OpenAI, or anything that speaks the OpenAI API, including a local model.

Code, the graph schema, every Cypher query, and the evaluation reports: the repository README.
