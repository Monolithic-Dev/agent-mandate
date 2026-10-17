"""Previewing a sentence before it becomes authority: rules, conflicts, and what would change."""

from typing import Any

from fakes.memory_backend import MemoryTenantBackend
from fastapi.testclient import TestClient

from mandate.api.app import create_app
from mandate.clock import FixedClock
from mandate.config import Settings

KEY = "k" * 24
VIEWER = "v" * 24
OPERATOR = "o" * 24
S1 = "You may read and archive my email, but confirm with me before deleting anything."


class Tenant:
    def __init__(self) -> None:
        settings = Settings(  # type: ignore[call-arg]
            mandate_api_key=KEY,
            mandate_api_keys=f"viewer:{VIEWER}:viewer:*;runner:{OPERATOR}:operator:*",
            _env_file=None,
        )
        self.backend = MemoryTenantBackend()
        self.c = TestClient(
            create_app(settings, self.backend, FixedClock()), raise_server_exceptions=False
        )
        assert self.post("/v1/tenants", {"tenant_id": "acme", "name": "Acme"}).status_code == 201
        self.owner = self.post("/principals", {"name": "Dana", "role": "owner"}).json()["id"]
        self.other = self.post("/principals", {"name": "x", "role": "external"}).json()["id"]
        self.main = self.post("/agents", {"name": "main", "kind": "primary"}).json()["id"]
        said = self.post(
            "/utterances", {"principal_id": self.owner, "text": S1, "channel": "owner_direct"}
        ).json()
        for item in said["instructions"]:
            if item["needs_confirmation"]:
                rule = item["instruction"]["id"]
                self.post(f"/instructions/{rule}/confirm", {"by": self.owner})
        # Recent requests the preview can re-check: a read, a refund nobody allowed (twice,
        # so it is re-checked once), and a refund of 900.
        self.check("email.read", "inbox/m-1")
        for amount, order in ((300, 1), (300, 1), (900, 2)):
            self.check("refund.issue", f"order/{order}", args={"amount": amount})

    def post(self, path: str, body: dict[str, Any], key: str = KEY) -> Any:
        url = path if path.startswith("/v1/") else f"/v1/tenants/acme{path}"
        return self.c.post(url, json=body, headers={"X-Mandate-Key": key})

    def check(self, action: str, resource: str, **extra: Any) -> None:
        body = {"agent_id": self.main, "action_type": action, "resource": resource, **extra}
        assert self.post("/check", body).status_code == 200

    def preview(self, text: str, key: str = KEY, **extra: Any) -> Any:
        return self.post(
            "/utterances/preview", {"principal_id": self.owner, "text": text, **extra}, key
        )

    def rule_count(self) -> int:
        rows = self.c.get("/v1/tenants/acme/instructions", headers={"X-Mandate-Key": KEY}).json()
        return len({row["instruction"]["id"] for row in rows})


def test_a_new_allowance_shows_what_it_would_let_through() -> None:
    t = Tenant()
    rules_before = t.rule_count()
    body = t.preview("You may issue refunds up to $500.").json()
    (rule,) = body["rules"]
    assert (rule["effect"], rule["action_type"], rule["max_amount"]) == (
        "allow",
        "refund.issue",
        500,
    )
    assert rule["needs_confirmation"] is True and rule["valid_to"] is None
    assert body["conflicts"] == [] and body["unparsed"] == []
    assert body["agent_ids"] == [t.main]
    # Two distinct refund requests are re-checked; only the one within the limit flips.
    assert body["evaluated"] == 2
    flipped, reason_only = body["changes"]
    assert (flipped["resource"], flipped["amount"]) == ("order/1", 300)
    assert (flipped["was_result"], flipped["now_result"]) == ("deny", "allow")
    assert flipped["result_changed"] is True
    # 900 is still refused, but now because it is over the limit rather than for want of a rule.
    assert (reason_only["amount"], reason_only["now_result"]) == (900, "deny")
    assert reason_only["result_changed"] is False
    assert reason_only["was_reason"] != reason_only["now_reason"]
    assert t.rule_count() == rules_before  # nothing live was written


def test_a_contradiction_is_flagged_and_its_effect_shown() -> None:
    t = Tenant()
    body = t.preview("Never read my email.").json()
    (conflict,) = body["conflicts"]
    assert (conflict["kind"], conflict["effect"], conflict["action_type"]) == (
        "contradicts",
        "allow",
        "email.read",
    )
    (change,) = body["changes"]
    assert (change["action_type"], change["was_result"], change["now_result"]) == (
        "email.read",
        "allow",
        "deny",
    )


def test_saying_the_same_rule_again_is_a_duplicate_and_changes_nothing() -> None:
    t = Tenant()
    body = t.preview("You may read my email.").json()
    assert [c["kind"] for c in body["conflicts"]] == ["duplicates"]
    assert body["changes"] == [] and body["evaluated"] == 1


def test_a_time_limit_is_shown() -> None:
    t = Tenant()
    (rule,) = t.preview("You may issue refunds up to $50 for the next 2 hours.").json()["rules"]
    assert rule["valid_for_ms"] == 7_200_000 and rule["valid_to"] is not None


def test_what_is_not_understood_is_reported_and_nothing_is_checked() -> None:
    t = Tenant()
    body = t.preview("Be careful with my inbox.").json()
    assert body["rules"] == [] and body["unparsed"] == ["Be careful with my inbox"]
    assert body["evaluated"] == 0


def test_only_the_owner_can_be_previewed_and_only_by_an_operator_or_admin() -> None:
    t = Tenant()
    other = t.post("/utterances/preview", {"principal_id": t.other, "text": "You may read email."})
    assert other.status_code == 422
    assert t.preview("You may read my email.", key=VIEWER).status_code == 403
    assert t.preview("You may read my email.", key=OPERATOR).status_code == 200


def test_a_preview_is_not_audited() -> None:
    t = Tenant()
    before = len(t.backend.directory.events)  # type: ignore[attr-defined]
    t.preview("You may read my email.")
    assert len(t.backend.directory.events) == before  # type: ignore[attr-defined]


def test_the_activity_overview_counts_the_recorded_decisions() -> None:
    t = Tenant()
    body = t.c.get("/v1/tenants/acme/activity?hours=24", headers={"X-Mandate-Key": VIEWER}).json()
    assert body["total"] == 4 and body["results"] == {"allow": 1, "confirm": 0, "deny": 3}
    assert len(body["buckets"]) == 24 and body["bucket_ms"] == 3_600_000
    assert {c["key"] for c in body["actions"]} == {"email.read", "refund.issue"}
    assert body["latency_p95_ms"] is not None
    bad = t.c.get("/v1/tenants/acme/activity?hours=999", headers={"X-Mandate-Key": KEY})
    assert bad.status_code == 422
