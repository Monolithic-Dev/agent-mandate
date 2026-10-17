# Submission checklist: Graph Hacks, Context for AI Agents

Status: v1.0 · 2026-10-07. Based on the hackathon rules as captured in the teammate's knowledge base on 2026-10-04. **Re-check the official site (https://www.wemakedevs.org/hackathons/falkordb) before submitting; rules, schedule and prizes may change.** Window: 2026-10-15 00:01 to 2026-10-18 23:59 IST.

## Before anything else

- [ ] The team reports that the organisers allow work done before Oct 15. Get that in writing and keep it with the submission: rule 8 says main coding and design work must begin after the event starts. This repository predates that; nothing in its history may be altered or re-dated to hide it.
- [ ] Decide which track or tracks to enter and name every one (Rule 5). Fit: Track 2 (Agent Memory and Coordination: procedural memory as standing instructions, shared state through delegation, per-tenant isolation, concurrency evidence from S6) and Track 1 (Agents That Act on Connected Data: typed tools through MCP, graph queries as tools, explainable actions).

## Required items

| # | Requirement | Where it lives | Status |
|---|---|---|---|
| 1 | Public source repository | GitHub repository | Repo exists; confirm it is public |
| 2 | README with setup instructions | `README.md` | Done; the quick start was verified from a clean clone on 2026-10-11 (build, seed, first admin, sign-in) |
| 3 | README includes the graph data model | `README.md`, `docs/data-model.md` | Done |
| 4 | The Cypher queries or graph algorithms relied on | `docs/query-catalog.md` (generated, checked in CI) | Done |
| 5 | Demo video | `docs/demo-script.md` (v2, for the finished console) | Script written; not recorded |
| 6 | Live deployment, or complete local setup plus the video | `docker-compose.prod.yml`, `render.yaml` (a free one-container Render Blueprint), `deploy/render/paid.render.yaml`, `docs/deployment.md` | Deployed free on Render at <https://agent-mandate-0ocw.onrender.com> (sleeps when idle; the first visit takes about a minute). Give judges a visitor (operator) account through `MANDATE_DEMO_EMAIL` and `MANDATE_DEMO_PASSWORD`, and put its credentials in the submission form, not in the repository |
| 7 | Track(s) entered | Submission form | Decide |
| 8 | AI assistant disclosure | `AI_USAGE.md` | Written; the team must complete the verification table |
| 9 | Data is public, synthetic or your own | README, `docs/security-privacy.md` | Synthetic only |
| 10 | Participants can explain the code, graph model, queries | `docs/judge-qa.md` | Owner to rehearse |

## Pre-submission checks

Clean-clone test passes; unit, integration, evaluation, isolation, concurrency and mutation jobs green on `main`; README numbers match the committed reports; claims ledger re-read (nothing from the "must not claim" list appears anywhere); secrets scan clean; demo runs offline from the seed script; video uploaded and playable; form saved well before the deadline.

## Also done

- MIT license (`LICENSE`); team name and members in the README. A blog post is drafted in `docs/blog-post.md`.
- A live-model evaluation (`python -m mandate.eval.live`) with its report under `docs/results/`; the claims ledger covers what it does and does not show.
