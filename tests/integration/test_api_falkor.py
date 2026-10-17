"""The REST API against a real FalkorDB: the owner workflow, isolation and tenant lifecycle."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from mandate.api.app import create_app
from mandate.api.tenancy import FalkorTenantBackend
from mandate.clock import SystemClock
from mandate.config import Settings
from mandate.graph.client import GraphClient
from mandate.ids import new_id

pytestmark = pytest.mark.integration

KEY = "k" * 24
HEADERS = {"X-Mandate-Key": KEY}
S1 = "You may read and archive my email, but confirm with me before deleting anything."


@pytest.fixture
def client(graph_client: GraphClient) -> Iterator[TestClient]:
    settings = Settings(mandate_api_key=KEY, _env_file=None)  # type: ignore[call-arg]
    app = create_app(settings, FalkorTenantBackend(graph_client), SystemClock())
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def tenant_id(client: TestClient) -> Iterator[str]:
    ident = f"api_{new_id('act')[4:].lower()}"
    yield ident
    client.delete(f"/v1/tenants/{ident}", headers=HEADERS)


def setup_tenant(client: TestClient, tenant_id: str) -> dict[str, str]:
    base = f"/v1/tenants/{tenant_id}"
    created = client.post(
        "/v1/tenants", json={"tenant_id": tenant_id, "name": "T"}, headers=HEADERS
    )
    assert created.status_code == 201, created.text
    owner = client.post(
        f"{base}/principals", json={"name": "Dana", "role": "owner"}, headers=HEADERS
    )
    main = client.post(f"{base}/agents", json={"name": "main", "kind": "primary"}, headers=HEADERS)
    return {"base": base, "owner": owner.json()["id"], "main": main.json()["id"]}


def test_s1_workflow_through_the_api(client: TestClient, tenant_id: str) -> None:
    t = setup_tenant(client, tenant_id)
    said = client.post(
        f"{t['base']}/utterances",
        json={"principal_id": t["owner"], "text": S1, "channel": "owner_direct"},
        headers=HEADERS,
    )
    assert said.status_code == 201, said.text
    for item in said.json()["instructions"]:
        if item["needs_confirmation"]:
            ok = client.post(
                f"{t['base']}/instructions/{item['instruction']['id']}/confirm",
                json={"by": t["owner"]},
                headers=HEADERS,
            )
            assert ok.status_code == 200, ok.text

    def tool(name: str, **args: object) -> dict[str, object]:
        response = client.post(
            f"{t['base']}/tool-calls",
            json={"agent_id": t["main"], "tool": name, "args": args},
            headers=HEADERS,
        )
        assert response.status_code == 200, response.text
        return response.json()  # type: ignore[no-any-return]

    assert tool("email_list")["status"] == "ok"
    held = tool("email_delete", message_id="m-1")
    assert held["status"] == "confirmation_required"
    pending = client.get(f"{t['base']}/actions?status=pending", headers=HEADERS).json()
    assert [(row["action"]["id"], row["decision_id"]) for row in pending] == [
        (held["approval_id"], held["decision_id"])
    ]
    approved = client.post(
        f"{t['base']}/actions/{held['approval_id']}/approve",
        json={"by": t["owner"], "approved": True},
        headers=HEADERS,
    )
    assert approved.json()["status"] == "ok"

    explained = client.get(
        f"{t['base']}/decisions/{held['decision_id']}/explain", headers=HEADERS
    ).json()
    assert explained["narrative"].startswith("Needs approval")
    stats = client.get(f"{t['base']}/stats", headers=HEADERS).json()
    assert stats["Approval"] == 1 and stats["Decision"] >= 2


def test_tenant_lifecycle_and_isolation(client: TestClient, tenant_id: str) -> None:
    first = setup_tenant(client, tenant_id)
    second_id = f"{tenant_id}_b"
    try:
        second = setup_tenant(client, second_id)
        duplicate = client.post(
            "/v1/tenants", json={"tenant_id": tenant_id, "name": "x"}, headers=HEADERS
        )
        assert duplicate.status_code == 409
        said = client.post(
            f"{first['base']}/utterances",
            json={
                "principal_id": first["owner"],
                "text": "You may read my email.",
                "channel": "owner_direct",
            },
            headers=HEADERS,
        )
        assert said.status_code == 201
        own = client.post(
            f"{first['base']}/check",
            json={"agent_id": first["main"], "action_type": "email.read", "resource": "inbox/m-1"},
            headers=HEADERS,
        )
        assert own.json()["result"] == "allow"
        # The first tenant's agent id means nothing in the second tenant's graph.
        foreign = client.post(
            f"{second['base']}/check",
            json={"agent_id": first["main"], "action_type": "email.read", "resource": "inbox/m-1"},
            headers=HEADERS,
        )
        assert foreign.status_code == 404  # an unknown agent is an error, nothing is recorded
        assert (
            client.get(
                f"{second['base']}/decisions/{own.json()['decision_id']}/explain", headers=HEADERS
            ).status_code
            == 404
        )
    finally:
        client.delete(f"/v1/tenants/{second_id}", headers=HEADERS)


def test_bad_tenant_ids_never_reach_the_database(client: TestClient) -> None:
    for bad in ("Acme", "x'; MATCH (n) DETACH DELETE n //", "a" * 41):
        response = client.post("/v1/tenants", json={"tenant_id": bad, "name": "x"}, headers=HEADERS)
        assert response.status_code == 422, bad


def test_health_reports_the_database(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok", "graph": "up"}


def test_console_run_and_graph_on_a_real_database(client: TestClient) -> None:
    run = client.post(
        "/v1/runs", json={"scenario_id": "S2_forged_v1", "kinds": ["mandate"]}, headers=HEADERS
    )
    assert run.status_code == 201, run.text
    body = run.json()
    tenant = body["tenant_id"]
    try:
        (mandate,) = body["runs"]
        assert mandate["unauthorised"] == 0
        decided = next(e for e in mandate["timeline"] if e["decision_id"])
        graph = client.get(
            f"/v1/tenants/{tenant}/graph",
            params={"highlight": decided["decision_id"]},
            headers=HEADERS,
        )
        assert graph.status_code == 200, graph.text
        elements = graph.json()["elements"]
        labels = {e["data"]["label"] for e in elements if e["group"] == "nodes"}
        assert {"Principal", "Agent", "Utterance", "Instruction", "Decision"} <= labels
        untrusted = [e for e in elements if "untrusted" in e["classes"].split()]
        assert untrusted  # the forged email and the rule drawn from it
        assert decided["decision_id"] in graph.json()["highlight"]
    finally:
        client.delete(f"/v1/tenants/{tenant}", headers=HEADERS)


def test_demo_reset_on_a_real_database(client: TestClient) -> None:
    reset = client.post("/v1/demo/reset", headers=HEADERS)
    try:
        assert reset.status_code == 200, reset.text
        assert reset.json()["held_action_id"].startswith("act_")
    finally:
        client.delete("/v1/tenants/demo", headers=HEADERS)


def test_approval_link_and_token_revocation_on_falkordb(client: TestClient, tenant_id: str) -> None:
    t = setup_tenant(client, tenant_id)
    said = client.post(
        f"{t['base']}/utterances",
        json={"principal_id": t["owner"], "text": S1, "channel": "owner_direct"},
        headers=HEADERS,
    ).json()
    for item in said["instructions"]:
        if item["needs_confirmation"]:
            rule = item["instruction"]["id"]
            client.post(
                f"{t['base']}/instructions/{rule}/confirm", json={"by": t["owner"]}, headers=HEADERS
            )
    held = client.post(
        f"{t['base']}/tool-calls",
        json={"agent_id": t["main"], "tool": "email_delete", "args": {"message_id": "m-1"}},
        headers=HEADERS,
    ).json()
    link = client.post(
        f"{t['base']}/actions/{held['approval_id']}/approval-link",
        json={"by": t["owner"]},
        headers=HEADERS,
    ).json()
    seen = client.post("/v1/approval-links/inspect", json={"token": link["token"]}).json()
    assert seen["pending"] and seen["decision_id"] == held["decision_id"]
    body = {"token": link["token"], "approved": True}
    assert client.post("/v1/approval-links/resolve", json=body).json()["status"] == "ok"
    assert client.post("/v1/approval-links/resolve", json=body).status_code == 409

    minted = client.post(
        f"{t['base']}/agents/{t['main']}/tokens", json={"by": t["owner"]}, headers=HEADERS
    ).json()
    revoked = client.post(
        f"{t['base']}/token-revocations",
        json={"by": t["owner"], "token": minted["token"]},
        headers=HEADERS,
    ).json()
    assert revoked["agent_id"] == t["main"] and revoked["token_id"] == minted["token_id"]
    listed = client.get(f"{t['base']}/token-revocations", headers=HEADERS).json()
    assert [row["token_id"] for row in listed] == [minted["token_id"]]
    graph = client.get(f"{t['base']}/graph", headers=HEADERS).json()
    assert all(e["data"]["label"] != "RevokedToken" for e in graph["elements"])


def test_preview_runs_on_a_throwaway_copy_of_the_graph(
    client: TestClient, tenant_id: str, graph_client: GraphClient
) -> None:
    t = setup_tenant(client, tenant_id)
    checked = client.post(
        f"{t['base']}/check",
        json={"agent_id": t["main"], "action_type": "refund.issue", "resource": "order/1",
              "args": {"amount": 300}},
        headers=HEADERS,
    )  # fmt: skip
    assert checked.json()["result"] == "deny"
    graphs_before = set(graph_client.list_graphs())
    body = client.post(
        f"{t['base']}/utterances/preview",
        json={"principal_id": t["owner"], "text": "You may issue refunds up to $500 for an hour."},
        headers=HEADERS,
    ).json()
    (change,) = body["changes"]
    assert (change["was_result"], change["now_result"]) == ("deny", "allow")
    assert body["rules"][0]["valid_for_ms"] == 3_600_000
    # Nothing live changed, and the copy is gone.
    rules = client.get(f"{t['base']}/instructions", headers=HEADERS).json()
    assert rules == []
    assert set(graph_client.list_graphs()) == graphs_before


def test_activity_is_read_from_the_graph(client: TestClient, tenant_id: str) -> None:
    t = setup_tenant(client, tenant_id)
    for amount in (10, 20):
        client.post(
            f"{t['base']}/check",
            json={"agent_id": t["main"], "action_type": "refund.issue", "resource": "order/1",
                  "args": {"amount": amount}},
            headers=HEADERS,
        )  # fmt: skip
    body = client.get(f"{t['base']}/activity?hours=1", headers=HEADERS).json()
    assert body["total"] == 2 and body["results"]["deny"] == 2
    assert body["actions"] == [{"key": "refund.issue", "count": 2}]
    assert body["agents"] == [{"key": t["main"], "count": 2}]
