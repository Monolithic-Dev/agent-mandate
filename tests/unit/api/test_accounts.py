"""Console users: sign-in, sessions, roles, cross-site protection, and managing users."""

from typing import Any

import pytest
from fakes.memory_backend import MemoryTenantBackend
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mandate.api import sessions
from mandate.api.app import create_app
from mandate.api.sessions import SESSION_COOKIE, hash_password, token_hash, verify_password
from mandate.clock import FixedClock
from mandate.config import Settings

KEY = "k" * 24
H = {"X-Mandate-Key": KEY}
CONSOLE = {"X-Mandate-Client": "console"}
PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def cheap_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sessions, "SCRYPT_N", 2**10)


def make_app(**overrides: Any) -> FastAPI:
    settings = Settings(  # type: ignore[call-arg]
        mandate_api_key=KEY, mandate_cookie_secure=False, _env_file=None, **overrides
    )
    return create_app(settings, MemoryTenantBackend(), FixedClock())


def browser(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def add_user(app: FastAPI, email: str, role: str = "admin", **extra: Any) -> dict[str, Any]:
    body = {"email": email, "name": email.split("@")[0], "role": role, "password": PASSWORD}
    made = browser(app).post("/v1/users", json={**body, **extra}, headers=H)
    assert made.status_code == 201, made.text
    return made.json()  # type: ignore[no-any-return]


def signed_in(app: FastAPI, email: str, password: str = PASSWORD) -> TestClient:
    client = browser(app)
    done = client.post(
        "/v1/auth/login", json={"email": email, "password": password}, headers=CONSOLE
    )
    assert done.status_code == 200, done.text
    return client


def tenant(app: FastAPI, tenant_id: str = "acme") -> None:
    made = browser(app).post("/v1/tenants", json={"tenant_id": tenant_id, "name": "x"}, headers=H)
    assert made.status_code == 201, made.text


# --- passwords and session tokens ------------------------------------------------------


def test_password_hashes_verify_and_are_salted() -> None:
    first, second = hash_password(PASSWORD), hash_password(PASSWORD)
    assert first != second and first.startswith("scrypt$")
    assert verify_password(PASSWORD, first) and verify_password(PASSWORD, second)
    assert not verify_password("wrong password!", first)
    for broken in ("", "scrypt$1$2", "bcrypt$x$y$z$a$b", "scrypt$x$8$1$aa$bb"):
        assert not verify_password(PASSWORD, broken)


def directory(app: FastAPI) -> Any:
    return app.state.runtimes.backend.directory


def advance(app: FastAPI, seconds: int) -> None:
    app.state.runtimes.clock.advance(seconds * 1000)


def test_only_a_hash_of_the_session_token_is_stored() -> None:
    app = make_app()
    add_user(app, "dana@example.com")
    client = signed_in(app, "dana@example.com")
    token = client.cookies[SESSION_COOKIE]
    (session,) = directory(app).sessions.values()
    assert token.startswith("mst_") and token not in str(session.model_dump())
    assert session.token_hash == token_hash(token)


def test_signing_out_ends_the_session_on_the_server() -> None:
    app = make_app()
    add_user(app, "dana@example.com")
    client = signed_in(app, "dana@example.com")
    stolen = client.cookies[SESSION_COOKIE]
    assert client.post("/v1/auth/logout", headers=CONSOLE).status_code == 204
    replay = browser(app)
    replay.cookies.set(SESSION_COOKIE, stolen)
    assert replay.get("/v1/auth/me").status_code == 401  # a copied cookie is worthless now
    assert directory(app).sessions == {}


def test_a_session_expires_and_idles_out() -> None:
    app = make_app(mandate_session_ttl_seconds=3600, mandate_session_idle_seconds=600)
    add_user(app, "dana@example.com")
    client = signed_in(app, "dana@example.com")
    for _ in range(5):  # active every 9 minutes: never idle, but the hour still runs out
        advance(app, 9 * 60)
        assert client.get("/v1/auth/me").status_code == 200
    advance(app, 16 * 60)
    assert client.get("/v1/auth/me").status_code == 401  # 61 minutes after sign-in
    idle = signed_in(app, "dana@example.com")
    advance(app, 601)
    assert idle.get("/v1/auth/me").status_code == 401


def test_garbage_cookies_are_refused_without_a_lookup() -> None:
    app = make_app()
    for junk in ("", "x", "mst_short", "mst_" + "a" * 200, "ses1.usr_1.0.0.9.n.sig"):
        client = browser(app)
        client.cookies.set(SESSION_COOKIE, junk)
        assert client.get("/v1/auth/me").status_code == 401


def test_people_see_their_sessions_and_end_one() -> None:
    app = make_app()
    add_user(app, "dana@example.com")
    laptop = signed_in(app, "dana@example.com")
    phone = browser(app)
    phone.headers["user-agent"] = "Mozilla/5.0 (iPhone)"
    phone.post(
        "/v1/auth/login",
        json={"email": "dana@example.com", "password": PASSWORD},
        headers=CONSOLE,
    )
    advance(app, 120)
    laptop.get("/v1/auth/me")  # seen more recently than the phone
    sessions = laptop.get("/v1/auth/sessions").json()
    assert [s["current"] for s in sessions] == [True, False]
    assert sessions[1]["user_agent"] == "Mozilla/5.0 (iPhone)"
    gone = laptop.delete(f"/v1/auth/sessions/{sessions[1]['id']}", headers=CONSOLE)
    assert gone.status_code == 204
    assert phone.get("/v1/auth/me").status_code == 401
    assert laptop.get("/v1/auth/me").status_code == 200
    again = laptop.delete(f"/v1/auth/sessions/{sessions[1]['id']}", headers=CONSOLE)
    assert again.status_code == 404


def test_nobody_ends_someone_elses_session() -> None:
    app = make_app()
    add_user(app, "dana@example.com")
    add_user(app, "ops@example.com", role="viewer")
    dana = signed_in(app, "dana@example.com")
    ops = signed_in(app, "ops@example.com")
    theirs = dana.get("/v1/auth/sessions").json()[0]["id"]
    assert ops.delete(f"/v1/auth/sessions/{theirs}", headers=CONSOLE).status_code == 404
    assert dana.get("/v1/auth/me").status_code == 200


# --- signing in ------------------------------------------------------------------------


def test_sign_in_sets_a_strict_http_only_cookie_and_me_answers() -> None:
    app = make_app()
    user = add_user(app, "Dana@Example.com")
    assert user["email"] == "dana@example.com"  # emails are compared lower-case
    client = browser(app)
    done = client.post(
        "/v1/auth/login", json={"email": "DANA@example.com", "password": PASSWORD}, headers=CONSOLE
    )
    assert done.status_code == 200, done.text
    cookie = done.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "max-age=43200" in cookie
    me = client.get("/v1/auth/me").json()
    assert me["kind"] == "user" and me["id"] == user["id"] and me["role"] == "admin"
    assert client.get("/v1/users").json()[0]["last_login_at"] is not None


def test_the_cookie_is_secure_by_default() -> None:
    settings = Settings(mandate_api_key=KEY, _env_file=None)  # type: ignore[call-arg]
    app = create_app(settings, MemoryTenantBackend(), FixedClock())
    add_user(app, "dana@example.com")
    done = browser(app).post(
        "/v1/auth/login", json={"email": "dana@example.com", "password": PASSWORD}, headers=CONSOLE
    )
    assert "secure" in done.headers["set-cookie"].lower()


def test_a_wrong_password_and_an_unknown_email_look_the_same() -> None:
    app = make_app()
    add_user(app, "dana@example.com")
    answers = []
    for email in ("dana@example.com", "nobody@example.com"):
        r = browser(app).post(
            "/v1/auth/login", json={"email": email, "password": "not the password"}, headers=CONSOLE
        )
        answers.append((r.status_code, r.json()["error"]["message"], "set-cookie" in r.headers))
    assert answers[0] == answers[1] == (401, "the email or password is incorrect", False)


def test_sign_in_needs_the_console_header() -> None:
    app = make_app()
    add_user(app, "dana@example.com")
    r = browser(app).post(
        "/v1/auth/login", json={"email": "dana@example.com", "password": PASSWORD}
    )
    assert r.status_code == 403


def test_sign_in_attempts_are_limited_per_email() -> None:
    app = make_app()
    add_user(app, "dana@example.com")
    client = browser(app)
    wrong = {"email": "dana@example.com", "password": "not the password"}
    codes = [
        client.post("/v1/auth/login", json=wrong, headers=CONSOLE).status_code for _ in range(10)
    ]
    assert set(codes) == {401}
    right = {"email": "dana@example.com", "password": PASSWORD}
    assert client.post("/v1/auth/login", json=right, headers=CONSOLE).status_code == 429
    other = {"email": "other@example.com", "password": "x"}
    assert client.post("/v1/auth/login", json=other, headers=CONSOLE).status_code == 401


def test_a_disabled_user_cannot_sign_in_and_their_sessions_end() -> None:
    app = make_app()
    user = add_user(app, "ops@example.com", role="viewer")
    client = signed_in(app, "ops@example.com")
    off = browser(app).patch(f"/v1/users/{user['id']}", json={"disabled": True}, headers=H)
    assert off.status_code == 200 and off.json()["disabled"] is True
    assert client.get("/v1/auth/me").status_code == 401
    r = browser(app).post(
        "/v1/auth/login", json={"email": "ops@example.com", "password": PASSWORD}, headers=CONSOLE
    )
    assert r.status_code == 401


def test_sign_out_clears_the_cookie() -> None:
    app = make_app()
    add_user(app, "dana@example.com")
    client = signed_in(app, "dana@example.com")
    assert client.post("/v1/auth/logout", headers=CONSOLE).status_code == 204
    assert client.get("/v1/auth/me").status_code == 401
    assert browser(app).post("/v1/auth/logout").status_code == 204  # already signed out: fine


# --- what a session may do -------------------------------------------------------------


def test_a_cookie_write_without_the_console_header_is_refused() -> None:
    app = make_app()
    add_user(app, "dana@example.com")
    client = signed_in(app, "dana@example.com")
    body = {"tenant_id": "acme", "name": "Acme"}
    assert client.post("/v1/tenants", json=body).status_code == 403  # a forged cross-site post
    assert client.post("/v1/tenants", json=body, headers=CONSOLE).status_code == 201


def test_roles_apply_to_users_as_they_do_to_keys() -> None:
    app = make_app()
    tenant(app)
    add_user(app, "viewer@example.com", role="viewer")
    viewer = signed_in(app, "viewer@example.com")
    assert viewer.get("/v1/tenants").status_code == 200
    owner = {"name": "Dana", "role": "owner"}
    refused = viewer.post("/v1/tenants/acme/principals", json=owner, headers=CONSOLE)
    assert refused.status_code == 403 and "viewer" in refused.json()["error"]["message"]
    assert viewer.get("/v1/users").status_code == 403
    assert viewer.get("/v1/audit").status_code == 403


def test_a_user_limited_to_tenants_sees_only_those() -> None:
    app = make_app()
    tenant(app, "acme")
    tenant(app, "globex")
    add_user(app, "acme@example.com", role="admin", tenants=["acme"])
    client = signed_in(app, "acme@example.com")
    assert [t["tenant_id"] for t in client.get("/v1/tenants").json()] == ["acme"]
    assert client.get("/v1/tenants/globex/principals").status_code == 404
    assert client.get("/v1/tenants/acme/principals").status_code == 200
    assert client.get("/v1/auth/me").json()["tenants"] == ["acme"]
    assert client.get("/v1/users").status_code == 403  # managing users needs every tenant


def test_an_api_key_wins_over_a_cookie() -> None:
    app = make_app()
    add_user(app, "viewer@example.com", role="viewer")
    client = signed_in(app, "viewer@example.com")
    me = client.get("/v1/auth/me", headers=H).json()
    assert me == {
        "kind": "key",
        "id": "admin",
        "name": "API key admin",
        "email": None,
        "role": "admin",
        "tenants": None,
    }
    assert client.get("/v1/auth/me", headers={"X-Mandate-Key": "x" * 24}).status_code == 401


# --- passwords and sessions ------------------------------------------------------------


def test_changing_a_password_ends_other_sessions_but_not_this_one() -> None:
    app = make_app()
    add_user(app, "dana@example.com")
    here, elsewhere = signed_in(app, "dana@example.com"), signed_in(app, "dana@example.com")
    new = "a whole new passphrase"
    wrong = here.post(
        "/v1/auth/password",
        json={"current_password": "nope", "new_password": new},
        headers=CONSOLE,
    )
    assert wrong.status_code == 400
    done = here.post(
        "/v1/auth/password",
        json={"current_password": PASSWORD, "new_password": new},
        headers=CONSOLE,
    )
    assert done.status_code == 200, done.text
    assert here.get("/v1/auth/me").status_code == 200
    assert elsewhere.get("/v1/auth/me").status_code == 401
    signed_in(app, "dana@example.com", new)


def test_a_new_password_must_be_long_enough() -> None:
    app = make_app()
    add_user(app, "dana@example.com")
    client = signed_in(app, "dana@example.com")
    short = {"current_password": PASSWORD, "new_password": "short"}
    assert client.post("/v1/auth/password", json=short, headers=CONSOLE).status_code == 422


def test_sign_out_everywhere() -> None:
    app = make_app()
    add_user(app, "dana@example.com")
    here, elsewhere = signed_in(app, "dana@example.com"), signed_in(app, "dana@example.com")
    assert here.post("/v1/auth/sessions/end", headers=CONSOLE).status_code == 204
    assert here.get("/v1/auth/me").status_code == 401
    assert elsewhere.get("/v1/auth/me").status_code == 401


def test_an_api_key_has_no_password_to_change() -> None:
    app = make_app()
    body = {"current_password": PASSWORD, "new_password": "a whole new passphrase"}
    assert browser(app).post("/v1/auth/password", json=body, headers=H).status_code == 400


# --- managing users --------------------------------------------------------------------


def test_admins_manage_users() -> None:
    app = make_app()
    user = add_user(app, "ops@example.com", role="viewer")
    client = browser(app)
    duplicate = {"email": "OPS@example.com", "name": "x", "role": "viewer", "password": PASSWORD}
    assert client.post("/v1/users", json=duplicate, headers=H).status_code == 409
    changed = client.patch(
        f"/v1/users/{user['id']}", json={"role": "operator", "tenants": ["acme"]}, headers=H
    ).json()
    assert changed["role"] == "operator" and changed["tenants"] == ["acme"]
    everywhere = client.patch(f"/v1/users/{user['id']}", json={"tenants": None}, headers=H)
    assert everywhere.json()["tenants"] is None
    assert client.patch("/v1/users/usr_x", json={"name": "x"}, headers=H).status_code == 404
    bad = client.patch(f"/v1/users/{user['id']}", json={"tenants": ["Not Valid"]}, headers=H)
    assert bad.status_code == 422
    assert "password_hash" not in str(client.get("/v1/users", headers=H).json())


def test_a_reset_password_ends_the_users_sessions() -> None:
    app = make_app()
    user = add_user(app, "ops@example.com", role="viewer")
    session = signed_in(app, "ops@example.com")
    reset = {"password": "a reset passphrase"}
    done = browser(app).post(f"/v1/users/{user['id']}/password", json=reset, headers=H)
    assert done.status_code == 200
    assert session.get("/v1/auth/me").status_code == 401
    signed_in(app, "ops@example.com", "a reset passphrase")
    again = signed_in(app, "ops@example.com", "a reset passphrase")
    assert browser(app).post(f"/v1/users/{user['id']}/sessions/end", headers=H).status_code == 200
    assert again.get("/v1/auth/me").status_code == 401


def test_nobody_can_change_their_own_role_or_status() -> None:
    app = make_app()
    me = add_user(app, "dana@example.com")
    client = signed_in(app, "dana@example.com")
    for change in ({"role": "viewer"}, {"disabled": True}, {"tenants": ["acme"]}):
        r = client.patch(f"/v1/users/{me['id']}", json=change, headers=CONSOLE)
        assert r.status_code == 400, change
    renamed = client.patch(f"/v1/users/{me['id']}", json={"name": "Dana B"}, headers=CONSOLE)
    assert renamed.status_code == 200 and renamed.json()["name"] == "Dana B"
