"""Webhooks: where they may point, what they say, when they speak, and who may manage them."""

import hashlib
import hmac
import json
from typing import Any

import pytest
from fakes.memory_backend import MemoryTenantBackend
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mandate.api.app import create_app
from mandate.api.notify import Notifier, SendResult, check_url, mask_url, sign
from mandate.clock import FixedClock
from mandate.config import Settings
from mandate.errors import ValidationFailure

KEY = "k" * 24
VIEWER = "v" * 24
H = {"X-Mandate-Key": KEY}
S1 = "You may read and archive my email, but confirm with me before deleting anything."
PUBLIC = "https://console.example.com"
HOOK_URL = "https://93.184.216.34/hooks/abcd1234"  # a public address, so no DNS in tests


class FakeSender:
    def __init__(self, *answers: SendResult) -> None:
        self.answers = list(answers)
        self.posts: list[tuple[str, dict[str, Any], dict[str, str]]] = []

    def post(self, url: str, body: bytes, headers: dict[str, str]) -> SendResult:
        self.posts.append((url, json.loads(body), headers))
        self.last_body = body
        return self.answers.pop(0) if self.answers else SendResult(200, None)


class Setup:
    def __init__(self, sender: FakeSender | None = None) -> None:
        settings = Settings(  # type: ignore[call-arg]
            mandate_api_key=KEY,
            mandate_api_keys=f"viewer:{VIEWER}:viewer:*",
            mandate_public_url=PUBLIC,
            _env_file=None,
        )
        self.backend = MemoryTenantBackend()
        self.app: FastAPI = create_app(settings, self.backend, FixedClock())
        self.sender = sender or FakeSender()
        self.app.state.notifier = Notifier(
            self.app.state.runtimes,
            link_secret=self.app.state.link_secrets[0],
            public_url=PUBLIC,
            link_ttl_seconds=3600,
            sender=self.sender,
            sleep=lambda _s: None,
        )
        self.c = TestClient(self.app, raise_server_exceptions=False)
        assert self.post("/v1/tenants", {"tenant_id": "acme", "name": "Acme"}).status_code == 201
        self.owner = self.post("/principals", {"name": "Dana", "role": "owner"}).json()["id"]
        self.main = self.post("/agents", {"name": "assistant", "kind": "primary"}).json()["id"]
        said = self.post(
            "/utterances", {"principal_id": self.owner, "text": S1, "channel": "owner_direct"}
        ).json()
        for item in said["instructions"]:
            if item["needs_confirmation"]:
                self.post(f"/instructions/{item['instruction']['id']}/confirm", {"by": self.owner})

    @property
    def notifier(self) -> Notifier:
        return self.app.state.notifier  # type: ignore[no-any-return]

    def post(self, path: str, body: dict[str, Any], key: str = KEY) -> Any:
        url = path if path.startswith("/v1/") else f"/v1/tenants/acme{path}"
        return self.c.post(url, json=body, headers={"X-Mandate-Key": key})

    def hook(self, kind: str = "json", **extra: Any) -> dict[str, Any]:
        made = self.post("/webhooks", {"name": "Ops", "url": HOOK_URL, "kind": kind, **extra})
        assert made.status_code == 201, made.text
        return made.json()  # type: ignore[no-any-return]

    def hold(self, message_id: str = "m-1") -> str:
        held = self.post(
            "/tool-calls",
            {"agent_id": self.main, "tool": "email_delete", "args": {"message_id": message_id}},
        ).json()
        assert held["status"] == "confirmation_required"
        return str(held["approval_id"])


# --- where a webhook may point --------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://93.184.216.34/x",  # not https
        "ftp://93.184.216.34/x",
        "https://user:pw@93.184.216.34/x",  # credentials in the URL
        "https://127.0.0.1/x",
        "https://localhost/x",
        "https://10.1.2.3/x",
        "https://192.168.0.10/x",
        "https://169.254.169.254/latest/meta-data",  # the cloud metadata service
        "https://[::1]/x",
        "https:///nohost",
    ],
)
def test_a_webhook_cannot_point_inside_the_network(url: str) -> None:
    with pytest.raises(ValidationFailure):
        check_url(url, allow_private=False)


def test_public_https_is_fine_and_local_testing_can_opt_in() -> None:
    assert check_url(HOOK_URL, allow_private=False) == HOOK_URL
    assert check_url("http://127.0.0.1:9000/hook", allow_private=True)


def test_urls_are_masked_and_signatures_check_out() -> None:
    assert mask_url("https://hooks.slack.com/services/T0/B0/secretXYZ") == (
        "https://hooks.slack.com/…tXYZ"
    )
    body = b'{"a":1}'
    expected = hmac.new(b"s3cret", b"1700000000." + body, hashlib.sha256).hexdigest()
    assert sign("s3cret", "1700000000", body) == f"v1={expected}"


# --- what is said, and when ------------------------------------------------------------


def test_a_held_action_is_announced_once_signed_with_a_link_that_works() -> None:
    s = Setup()
    hook = s.hook()
    assert hook["secret"].startswith("whsec_") and hook["url"] == "https://93.184.216.34/…1234"
    action = s.hold()
    assert s.notifier.tick() == 1
    assert s.notifier.tick() == 0  # announced once

    (url, body, headers) = s.sender.posts[0]
    assert url == HOOK_URL and headers["X-Mandate-Event"] == "approval.requested"
    expected = sign(hook["secret"], headers["X-Mandate-Timestamp"], s.sender.last_body)
    assert headers["X-Mandate-Signature"] == expected
    assert (
        body["action"]["id"] == action
        and body["action"]["call"] == 'email_delete(message_id="m-1")'
    )
    assert body["agent"]["name"] == "assistant" and body["why_held"].startswith("Needs approval")
    assert body["console_url"] == f"{PUBLIC}/tenants/acme?tab=approvals"
    assert body["approve_url"].startswith(f"{PUBLIC}/approve#apl1.")

    token = body["approve_url"].split("#", 1)[1]
    seen = s.c.post("/v1/approval-links/inspect", json={"token": token})
    assert seen.status_code == 200 and seen.json()["action"]["id"] == action

    log = s.c.get(f"/v1/tenants/acme/webhooks/{hook['id']}/deliveries", headers=H).json()
    assert [(d["event"], d["ok"], d["attempts"], d["subject"]) for d in log] == [
        ("approval.requested", True, 1, action)
    ]
    listed = s.c.get("/v1/tenants/acme/webhooks", headers=H).json()
    assert listed[0]["last_ok"] is True and "secret" not in listed[0]


def test_slack_gets_a_message_with_an_approve_button() -> None:
    s = Setup()
    s.hook(kind="slack")
    s.hold()
    s.notifier.tick()
    (_, body, _) = s.sender.posts[0]
    assert "assistant wants to run `email_delete" in body["text"]
    buttons = body["blocks"][-1]["elements"]
    assert buttons[0]["text"]["text"] == "Review and approve"
    assert buttons[0]["url"].startswith(f"{PUBLIC}/approve#")


def test_what_was_already_waiting_is_not_announced_and_new_ones_are_in_order() -> None:
    s = Setup()
    s.hold("m-1")  # before the webhook existed
    s.hook()
    first = s.hold("m-2")
    s.app.state.runtimes.clock.advance(5)
    second = s.hold("m-3")
    assert s.notifier.tick() == 2
    assert [p[1]["action"]["id"] for p in s.sender.posts] == [first, second]


def test_failures_are_retried_then_recorded_and_bad_requests_are_not_retried() -> None:
    s = Setup(FakeSender(SendResult(503, "HTTP 503"), SendResult(None, "ConnectError"),
                         SendResult(500, "HTTP 500"), SendResult(400, "HTTP 400")))  # fmt: skip
    hook = s.hook()
    s.hold("m-1")
    s.notifier.tick()
    s.hold("m-2")
    s.notifier.tick()
    log = s.c.get(f"/v1/tenants/acme/webhooks/{hook['id']}/deliveries", headers=H).json()
    assert [(d["ok"], d["attempts"], d["status"]) for d in log] == [
        (False, 1, 400),  # newest first: a 400 is not retried
        (False, 3, 500),
    ]
    listed = s.c.get("/v1/tenants/acme/webhooks", headers=H).json()[0]
    assert (listed["last_ok"], listed["failures"]) == (False, 2)


def test_a_disabled_webhook_is_quiet_and_re_enabling_does_not_replay() -> None:
    s = Setup()
    hook = s.hook()
    path = f"/v1/tenants/acme/webhooks/{hook['id']}"
    assert s.c.patch(path, json={"enabled": False}, headers=H).json()["enabled"] is False
    s.hold("m-1")
    assert s.notifier.tick() == 0
    s.c.patch(path, json={"enabled": True}, headers=H)
    assert s.notifier.tick() == 0  # m-1 was held while it was off
    s.hold("m-2")
    assert s.notifier.tick() == 1


def test_a_test_ping_is_sent_now() -> None:
    s = Setup()
    hook = s.hook(kind="slack")
    sent = s.post(f"/webhooks/{hook['id']}/test", {}).json()
    assert sent["event"] == "webhook.test" and sent["ok"] is True
    assert "this webhook works" in s.sender.posts[0][1]["text"]


# --- who may manage them ---------------------------------------------------------------


def test_only_admins_see_or_change_webhooks() -> None:
    s = Setup()
    hook = s.hook()
    assert (
        s.c.get("/v1/tenants/acme/webhooks", headers={"X-Mandate-Key": VIEWER}).status_code == 403
    )
    assert s.post(f"/webhooks/{hook['id']}/test", {}, key=VIEWER).status_code == 403
    bad = s.post("/webhooks", {"name": "x", "url": "https://10.0.0.1/x", "kind": "json"})
    assert bad.status_code == 422
    other = s.c.get("/v1/tenants/nope/webhooks", headers=H)
    assert other.status_code == 404


def test_deleting_a_webhook_or_its_tenant_removes_it() -> None:
    s = Setup()
    first, second = s.hook(), s.hook()
    assert s.c.delete(f"/v1/tenants/acme/webhooks/{first['id']}", headers=H).status_code == 204
    assert [h["id"] for h in s.c.get("/v1/tenants/acme/webhooks", headers=H).json()] == [
        second["id"]
    ]
    assert s.c.delete("/v1/tenants/acme", headers=H).status_code == 204
    assert s.backend.directory.list_webhooks() == []


def test_webhook_changes_are_audited() -> None:
    s = Setup()
    hook = s.hook()
    s.post(f"/webhooks/{hook['id']}/test", {})
    actions = [e.action for e in s.backend.directory.events]  # type: ignore[attr-defined]
    assert actions[-2:] == ["webhook.create", "webhook.test"]


def test_actions_held_in_the_same_millisecond_are_each_announced_once() -> None:
    # Ids made in one millisecond sort randomly, so the cursor cannot be "the newest id".
    s = Setup()
    s.hook()
    held = {s.hold(f"m-{n}") for n in range(6)}  # the fixed clock: all in one millisecond
    assert s.notifier.tick() == 6
    s.hold("m-6")
    assert s.notifier.tick() == 1
    assert s.notifier.tick() == 0
    announced = [p[1]["action"]["id"] for p in s.sender.posts]
    assert set(announced[:6]) == held and len(set(announced)) == 7


def test_the_cursor_round_trips() -> None:
    from mandate.api.notify import Cursor

    cursor = Cursor(1700, frozenset({"act_b", "act_a"}))
    assert str(cursor) == "1700|act_a,act_b"
    assert Cursor.parse(str(cursor)) == cursor
    assert Cursor.parse("") == Cursor() and Cursor.parse("garbage") == Cursor()
