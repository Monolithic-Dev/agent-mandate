# Contributing

This is a personal project that is built to a written spec. Read [docs/README.md](docs/README.md) for the reading order and [docs/dev-setup.md](docs/dev-setup.md) to get a working environment.

## Workflow

1. Pick the next phase in [docs/phases/](docs/phases/) (or an issue).
2. Create a branch from `main`: `type/short-slug`, where `type` is `feat`, `fix`, `docs`, `test`, `chore` or `refactor`. Example: `feat/check-authority`.
3. Make small commits using [Conventional Commits](https://www.conventionalcommits.org/): `feat(authority): add precedence rules`.
4. Open a pull request to `main` using the template. CI must be green.
5. Squash or merge after review. Delete the branch.

Commits are authored by the person who wrote them, using their own git identity. Do not add co-author trailers or generated-by footers.

## Spec and code stay in sync

The documents in `docs/` are the contract. If code forces a change to a field name, endpoint, query or rule, change the doc **in the same pull request**. A reviewer should be able to read the doc and predict the code.

Names to keep identical across docs and code: node labels and properties ([docs/data-model.md](docs/data-model.md)), endpoint paths and MCP tool names ([docs/api-spec.md](docs/api-spec.md)), reason codes (data-model.md section 6), scenario ids ([docs/evaluation.md](docs/evaluation.md)).

## Quality bar

- Tests accompany behaviour. Use the named test cases in [docs/testing.md](docs/testing.md) where they exist.
- `ruff check .`, `ruff format --check .`, `mypy` and `pytest tests/unit` pass before you push.
- Anything touching input, shared state or an external call includes validation and failure handling in the same change, and fails closed.
- No secrets, API keys or real personal data in commits. `.env` is git-ignored; run the secrets scan (`pre-commit run gitleaks --all-files`) if unsure.
- Claims in the README or docs need evidence. See [docs/claims-ledger.md](docs/claims-ledger.md).

## Reporting problems

Use the issue templates. For security problems, see [SECURITY.md](SECURITY.md).
