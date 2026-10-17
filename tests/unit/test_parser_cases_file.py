"""Checks the labelled parser cases file is well formed.

The parser itself is implemented in Phase 3; this keeps the data honest until then.
"""

import csv
from pathlib import Path

CASES = Path(__file__).resolve().parents[1] / "data" / "parser_cases.csv"
EFFECTS = {"allow", "deny", "confirm"}
ACTIONS = {
    "email.read",
    "email.archive",
    "email.delete",
    "email.send",
    "refund.issue",
    "file.read",
    "file.write",
    "file.delete",
}


def _rows() -> list[dict[str, str]]:
    with CASES.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_counts() -> None:
    rows = _rows()
    assert len(rows) == 40
    assert sum(r["should_parse"] == "true" for r in rows) == 30
    assert sum(r["should_parse"] == "false" for r in rows) == 10


def test_ids_unique() -> None:
    ids = [r["id"] for r in _rows()]
    assert len(ids) == len(set(ids))


def test_expected_format() -> None:
    for row in _rows():
        if row["should_parse"] == "false":
            assert row["expected"] == "", row["id"]
            continue
        for part in row["expected"].split(";"):
            effect, action, pattern, max_amount = part.split("|")
            assert effect in EFFECTS, row["id"]
            assert action in ACTIONS, row["id"]
            assert pattern, row["id"]
            assert max_amount == "" or max_amount.isdigit(), row["id"]
            if max_amount:
                assert action == "refund.issue", row["id"]
