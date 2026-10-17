"""python -m mandate.users: the first admin, and recovery from the server's shell."""

import argparse

import pytest
from fakes.memory_directory import MemoryDirectory

from mandate.api import sessions
from mandate.api.sessions import verify_password
from mandate.models.accounts import Session
from mandate.users import run

PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sessions, "SCRYPT_N", 2**10)
    monkeypatch.setenv("MANDATE_NEW_PASSWORD", PASSWORD)


def args(command: str, **extra: object) -> argparse.Namespace:
    return argparse.Namespace(command=command, **extra)


def test_add_list_reset_disable_enable(capsys: pytest.CaptureFixture[str]) -> None:
    d = MemoryDirectory()
    add = args("add", email="Dana@Example.com", name=None, role="admin", tenants="acme, demo")
    assert run(add, d, 1_000) == 0
    user = d.users[next(iter(d.users))]
    assert (user.email, user.name, user.tenants) == ("dana@example.com", "dana", ("acme", "demo"))
    assert verify_password(PASSWORD, user.password_hash)

    assert run(args("list"), d, 1_000) == 0
    assert "dana@example.com" in capsys.readouterr().out

    d.sessions["ses_1"] = Session(
        id="ses_1", user_id=user.id, token_hash="h", created_at=1, expires_at=9_999,
        last_seen_at=1,
    )  # fmt: skip
    assert run(args("reset-password", email="dana@example.com"), d, 2_000) == 0
    assert d.sessions == {}  # a reset signs them out everywhere
    assert run(args("disable", email="dana@example.com"), d, 3_000) == 0
    assert d.users[user.id].disabled
    assert run(args("enable", email="dana@example.com"), d, 4_000) == 0
    assert not d.users[user.id].disabled
    assert run(args("disable", email="nobody@example.com"), d, 5_000) == 1

    trail = [(e.action, e.actor_kind, e.method) for e in d.events]
    assert trail == [
        ("user.create", "cli", "CLI"),
        ("user.password_reset", "cli", "CLI"),
        ("user.update", "cli", "CLI"),
        ("user.update", "cli", "CLI"),
    ]


def test_a_short_password_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANDATE_NEW_PASSWORD", "short")
    add = args("add", email="x@example.com", name="x", role="viewer", tenants=None)
    with pytest.raises(SystemExit):
        run(add, MemoryDirectory(), 1_000)
