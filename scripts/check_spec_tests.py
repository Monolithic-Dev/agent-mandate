"""Fail if a rule in docs/spec/authority-semantics.md has no test.

A rule has a test when some test function name contains its id in lower case without the
hyphen (``AUTH-012`` -> ``auth012``). Rules in PENDING are exempt until their phase.
Run from the repository root: ``python scripts/check_spec_tests.py``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs" / "spec" / "authority-semantics.md"
TESTS = ROOT / "tests"

# Rule ids whose tests arrive in a later phase (see the conformance map in the spec).
PENDING: set[str] = set()


def spec_rule_ids() -> list[str]:
    text = SPEC.read_text(encoding="utf-8")
    return sorted(set(re.findall(r"^\| (AUTH-\d{3}) \|", text, flags=re.MULTILINE)))


def test_names() -> str:
    names: list[str] = []
    for path in TESTS.rglob("test_*.py"):
        names.extend(re.findall(r"^def (test_\w+)", path.read_text(encoding="utf-8"), re.M))
    return "\n".join(names).lower()


def main() -> int:
    names = test_names()
    missing = [
        rule
        for rule in spec_rule_ids()
        if rule not in PENDING and rule.lower().replace("-", "") not in names
    ]
    if missing:
        print("Rules without a test:", ", ".join(missing))
        return 1
    print(f"All {len(spec_rule_ids()) - len(PENDING)} non-pending rules have a test.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
