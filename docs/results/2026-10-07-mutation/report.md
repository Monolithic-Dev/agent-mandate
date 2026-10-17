# Mutation testing of the authority engine

Run 2026-10-07 with `python scripts/mutation_test.py`. It makes one small edit at a time to the
decision logic (flip a comparison, swap `and`/`or`, drop a `not`, flip a boolean, add one to an
integer) in seven files under `src/mandate/authority/`, and runs the unit tests against each edit.
A mutant is **killed** if any test fails. Test set: `tests/unit/spec`, precedence, scope and service tests.

| Run | Mutants | Killed | Score |
|---|---|---|---|
| Before (existing tests) | 112 | 84 | 75.0% |
| After boundary, path and lineage tests | 112 | 107 | 95.5% |

The first run exposed real gaps: the explanation path contents, the delegation-depth and
lineage-depth limits, malformed delegation chains, the supersession boundary and a zero amount
against a limit. `tests/unit/spec/test_auth_boundaries.py` closes them.

## Survivors (5), judged not worth a test

| Where | Edit | Why it survives |
|---|---|---|
| `check.py` `persist` default | `True` to `False` | Every caller passes it explicitly; the default is never exercised. |
| `check.py` latency | `* 1000` to `* 1001` | Latency is a measurement; no rule depends on its exact value. |
| `check.py` log rounding | `round(x, 3)` to `round(x, 4)` | Log formatting only. |
| `precedence.py` allow rank | `2` to `3` | Order is unchanged (deny < confirm < allow), so behaviour is identical. |
| `pdp.py` `trace and ...` | `and` to `or` | Only differs when a winning rule has no lineage trace, which the store never returns. |

## Limits

- The operators are simple; a higher score here does not prove the rules are right, only that the tests would notice these edits.
- Equivalent mutants cannot be told apart automatically; the table above is a manual judgement.
- Only the decision engine is mutated, not the store, gateway or API.
