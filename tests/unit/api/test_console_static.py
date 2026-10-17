"""The API serving the built console, for a one-container deployment."""

from pathlib import Path

import pytest
from fakes.memory_backend import MemoryTenantBackend
from fastapi.testclient import TestClient

from mandate.api.app import create_app
from mandate.clock import FixedClock
from mandate.config import Settings

KEY = "k" * 24


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><title>Agent Mandate</title><div id=root>", "utf-8"
    )
    (dist / "assets" / "app-abc123.js").write_text("console.log(1)", "utf-8")
    (tmp_path / "secret.txt").write_text("not for the web", "utf-8")
    settings = Settings(mandate_api_key=KEY, mandate_static_dir=dist, _env_file=None)  # type: ignore[call-arg]
    return TestClient(create_app(settings, MemoryTenantBackend(), FixedClock()))


def test_the_console_loads_and_unknown_paths_load_the_app_so_it_can_route(
    client: TestClient,
) -> None:
    home = client.get("/")
    assert home.status_code == 200 and "<div id=root>" in home.text
    assert home.headers["cache-control"] == "no-cache"
    assert (
        home.headers["x-frame-options"] == "DENY"
        and home.headers["x-content-type-options"] == "nosniff"
    )
    deep = client.get("/tenants/acme/decisions/dec_1")
    assert deep.status_code == 200 and "<div id=root>" in deep.text


def test_built_assets_are_served_and_cached_for_good(client: TestClient) -> None:
    asset = client.get("/assets/app-abc123.js")
    assert asset.status_code == 200 and asset.text == "console.log(1)"
    assert "immutable" in asset.headers["cache-control"]


def test_the_api_keeps_its_own_routes_and_its_own_404(client: TestClient) -> None:
    assert client.get("/healthz").json()["status"] == "ok"
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/v1/scenarios").status_code == 401  # still guarded
    missing = client.get("/v1/nothing-here", headers={"X-Mandate-Key": KEY})
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"


def test_a_path_cannot_climb_out_of_the_console_folder(client: TestClient) -> None:
    for path in ("/../secret.txt", "/assets/../../secret.txt", "/%2e%2e/secret.txt"):
        response = client.get(path)
        assert "not for the web" not in response.text


def test_without_a_static_dir_the_api_serves_no_console() -> None:
    settings = Settings(mandate_api_key=KEY, _env_file=None)  # type: ignore[call-arg]
    api = TestClient(create_app(settings, MemoryTenantBackend(), FixedClock()))
    assert api.get("/").status_code == 404


def test_a_static_dir_without_an_index_is_refused_at_start(tmp_path: Path) -> None:
    settings = Settings(mandate_api_key=KEY, mandate_static_dir=tmp_path, _env_file=None)  # type: ignore[call-arg]
    with pytest.raises(FileNotFoundError, match="index.html"):
        create_app(settings, MemoryTenantBackend(), FixedClock())
