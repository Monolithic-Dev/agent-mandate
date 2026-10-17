# AI assistance disclosure

The Graph Hacks rules (Rule 11) allow AI coding assistants if their use is disclosed, and (Rules 12 and 13) require participants to understand and be able to explain what they submit. This file is that disclosure. It must stay accurate; update it when the way the project is built changes.

## Tools used

| Tool | Used for |
|---|---|
| Claude Code (Anthropic), running Claude models | Most of the code, tests, Cypher queries, scenario files and documentation in this repository were written by the assistant under the owner's direction, in a plan, implement, test and review loop |
| GitHub Actions, ruff, mypy, import-linter, pytest, hypothesis | Automated checks the assistant's output must pass (these are tools, not AI) |

## How the assistant was used

- The owner chose the project, the scope and the constraints, and directed each feature (one branch and pull request per feature).
- The assistant researched prior art through web search, wrote the design documents and the code, ran the tests, and reported results.
- Every result in the README and the claims ledger comes from a command that can be re-run (`python -m mandate.eval`, `python scripts/mutation_test.py`, and the S5 and S6 programs); no number is typed by hand.
- Git history is authored under the owner's name by the owner's instruction. That is a choice about commit metadata; this file is where assistance is disclosed.

## What the owner has verified and can explain

To be completed by the owner, in their own words, before any submission. Rules 12 and 13 ask for meaningful participant contribution and understanding; a reviewer may ask. Work through [docs/judge-qa.md](./docs/judge-qa.md) and tick only what you can explain without help.

| Area | Owner can explain it | Notes |
|---|---|---|
| The graph data model | [ ] | |
| The authority rules (trust, precedence, delegation, revocation) | [ ] | |
| One Cypher query end to end | [ ] | |
| Why FalkorDB is necessary (the removal test) | [ ] | |
| The evaluation, its baselines and its limits | [ ] | |
| The MCP servers and why approval is a separate process | [ ] | |

## Limits of this disclosure

The assistant's output was checked mainly by automated tests and by reading results; it has not had an independent security review. See [SECURITY.md](./SECURITY.md) and the claims ledger for what is and is not claimed.
