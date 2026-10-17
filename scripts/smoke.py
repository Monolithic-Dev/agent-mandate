"""Smoke test for a running deployment: python scripts/smoke.py <base-url> <api-key>.

Checks that the service is ready, that authentication and tenant scoping behave, that a
seeded demo tenant makes sensible decisions, and that metrics are exposed. Standard library
only, so it runs anywhere. Exits 1 on the first failed check.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from typing import Any


def call(base: str, path: str, key: str | None = None, body: Any = None) -> tuple[int, Any]:
    request = urllib.request.Request(base + path, method="POST" if body is not None else "GET")
    if key:
        request.add_header("X-Mandate-Key", key)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        request.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(request, data=data, timeout=10) as response:  # noqa: S310
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as error:
        raw, status = error.read(), error.code
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw.decode(errors="replace")


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    base, key = argv[1].rstrip("/"), argv[2]
    failures = 0

    def check(name: str, ok: bool, detail: object = "") -> None:
        nonlocal failures
        print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  ({detail})"))
        failures += 0 if ok else 1

    status, body = call(base, "/readyz")
    check("readyz is ready", status == 200 and body.get("status") == "ready", (status, body))
    status, _ = call(base, "/v1/tenants")
    check("no key is refused", status == 401, status)
    status, _ = call(base, "/v1/tenants", "wrong-key-wrong-key-1234")
    check("a wrong key is refused", status == 401, status)
    status, tenants = call(base, "/v1/tenants", key)
    check("the key lists tenants", status == 200 and isinstance(tenants, list), status)
    demo = next((t for t in tenants if t["tenant_id"] == "demo"), None) if status == 200 else None
    check("the demo tenant is seeded (run mandate.seed)", demo is not None)
    if demo is not None:
        status, rows = call(base, "/v1/tenants/demo/decisions?limit=200", key)
        results = {row["decision"]["result"] for row in rows} if status == 200 else set()
        check(
            "the demo has allow, deny and confirm decisions",
            {"allow", "deny", "confirm"} <= results,
        )
        status, ranked = call(base, "/v1/tenants/demo/reliance", key)
        check("reliance ranks the rules", status == 200 and len(ranked) > 0, status)
        if status == 200 and rows:
            decision_id = rows[0]["decision"]["id"]
            status, verified = call(base, f"/v1/tenants/demo/decisions/{decision_id}/verify", key)
            check("a stored explanation verifies", status == 200 and verified["ok"], verified)
    status, text = call(base, "/metrics", key)
    check("metrics are exposed", status == 200 and "mandate_decisions_total" in str(text), status)
    status, _ = call(base, "/metrics")
    check("metrics need a key", status == 401, status)
    print("PASS" if not failures else f"{failures} check(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
