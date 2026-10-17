"""The console endpoints: graph, scenarios, runs, latest evaluation, demo reset."""

import json
from pathlib import Path
from typing import Any

from fakes.memory_backend import MemoryTenantBackend
from fastapi.testclient import TestClient

from mandate.api.app import create_app
from mandate.clock import FixedClock
from mandate.config import Settings

ADMIN = "a" * 24
READER = "r" * 24
H = {"X-Mandate-Key": ADMIN}
S1 = "You may read and archive my email, but confirm with me before deleting anything."


def client(results: Path | None = None) -> TestClient:
    settings = Settings(  # type: ignore[call-arg]
        mandate_api_key=ADMIN,
        mandate_api_keys=f"reader:{READER}:viewer:*",
        mandate_results_dir=results or Path("no-such-results-dir"),
        _env_file=None,
    )
    app = create_app(settings, MemoryTenantBackend(), FixedClock())
    return TestClient(app, raise_server_exceptions=False)


def tenant_with_a_decision(c: TestClient) -> tuple[str, str]:
    assert c.post("/v1/tenants", json={"tenant_id": "acme", "name": "Acme"}, headers=H).is_success
    base = "/v1/tenants/acme"
    owner = c.post(f"{base}/principals", json={"name": "Dana", "role": "owner"}, headers=H).json()
    agent = c.post(f"{base}/agents", json={"name": "main", "kind": "primary"}, headers=H).json()
    said = c.post(
        f"{base}/utterances",
        json={"principal_id": owner["id"], "text": S1, "channel": "owner_direct"},
        headers=H,
    ).json()
    for item in said["instructions"]:
        if item["needs_confirmation"]:
            c.post(
                f"{base}/instructions/{item['instruction']['id']}/confirm",
                json={"by": owner["id"]},
                headers=H,
            )
    checked = c.post(
        f"{base}/check",
        json={"agent_id": agent["id"], "action_type": "email.delete", "resource": "inbox/m-1"},
        headers=H,
    ).json()
    return base, checked["decision_id"]


def by_label(elements: list[dict[str, Any]], label: str) -> list[dict[str, Any]]:
    return [e for e in elements if e["group"] == "nodes" and e["data"]["label"] == label]


# --- graph ---------------------------------------------------------------------------


def test_graph_draws_the_tenant_and_highlights_a_decision_path() -> None:
    c = client()
    base, decision_id = tenant_with_a_decision(c)

    plain = c.get(f"{base}/graph", headers=H).json()
    elements = plain["elements"]
    assert not plain["truncated"] and plain["highlight"] == []
    assert len(by_label(elements, "Instruction")) == 3
    assert by_label(elements, "Utterance")[0]["classes"].split() == ["utterance", "trusted"]
    edge_types = {e["data"]["label"] for e in elements if e["group"] == "edges"}
    assert {"SAID", "EXPRESSES", "ABOUT", "APPLIES_TO", "CHECKED", "USED"} <= edge_types

    lit = c.get(f"{base}/graph", params={"highlight": decision_id}, headers=H).json()
    marked = {e["data"]["id"] for e in lit["elements"] if "highlight" in e["classes"].split()}
    principal = by_label(lit["elements"], "Principal")
    owner = next(p for p in principal if p["data"]["role"] == "owner")
    assert decision_id in marked and owner["data"]["id"] in marked
    assert by_label(lit["elements"], "Decision")[0]["data"]["caption"].startswith("CONFIRM")


def test_graph_limit_truncates_and_an_unknown_decision_is_not_found() -> None:
    c = client()
    base, _ = tenant_with_a_decision(c)
    cut = c.get(f"{base}/graph", params={"limit": 2}, headers=H).json()
    assert cut["truncated"] and len([e for e in cut["elements"] if e["group"] == "nodes"]) == 2
    missing = c.get(f"{base}/graph", params={"highlight": "dec_" + "0" * 26}, headers=H)
    assert missing.status_code == 404


# --- scenarios and runs --------------------------------------------------------------


def test_scenarios_are_listed() -> None:
    listed = client().get("/v1/scenarios", headers=H).json()
    s1 = next(s for s in listed if s["id"] == "S1_rule_lost_v1")
    assert s1["family"] == "S1" and s1["attempts"] > 0 and len(listed) >= 26


def test_a_run_shows_the_gap_and_its_decisions_can_be_explained() -> None:
    c = client()
    response = c.post("/v1/runs", json={"scenario_id": "S1_rule_lost_v1"}, headers=H)
    assert response.status_code == 201, response.text
    run = response.json()
    naive, mandate = (next(r for r in run["runs"] if r["kind"] == k) for k in ("naive", "mandate"))
    assert naive["unauthorised"] > 0 and mandate["unauthorised"] == 0
    assert any(e["event"] == "compact" for e in mandate["timeline"])
    assert run["tenant_id"].startswith("run_")

    decided = [e for e in mandate["timeline"] if e["decision_id"]]
    assert decided and all(
        e["status"] in {"executed", "held", "approved", "denied"} for e in decided
    )
    first = decided[0]["decision_id"]
    explained = c.get(f"/v1/tenants/{run['tenant_id']}/decisions/{first}/explain", headers=H)
    assert explained.status_code == 200
    assert all(e["decision_id"] is None for e in naive["timeline"])  # baselines decide nothing


def test_run_rejects_unknown_scenarios_and_kinds() -> None:
    c = client()
    assert c.post("/v1/runs", json={"scenario_id": "S0_nope_v1"}, headers=H).status_code == 404
    bad = c.post("/v1/runs", json={"scenario_id": "S1_rule_lost_v1", "kinds": ["x"]}, headers=H)
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "validation_error"


def test_a_viewer_can_read_but_not_run_or_reset() -> None:
    c = client()
    reader = {"X-Mandate-Key": READER}
    assert c.get("/v1/scenarios", headers=reader).status_code == 200
    assert (
        c.post("/v1/runs", json={"scenario_id": "S1_rule_lost_v1"}, headers=reader).status_code
        == 403
    )
    assert c.post("/v1/demo/reset", headers=reader).status_code == 403


# --- evaluation and demo -------------------------------------------------------------


def test_latest_evaluation_is_the_newest_folder(tmp_path: Path) -> None:
    for name, runs in (("2026-10-01-old", 1), ("2026-10-09-new", 2)):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "metrics.json").write_text(json.dumps({"mandate": {"runs": runs}}))
        (folder / "report.md").write_text(f"# report {name}")
    (tmp_path / "2026-10-10-mutation").mkdir()  # no metrics.json: not an evaluation
    latest = client(tmp_path).get("/v1/eval/latest", headers=H).json()
    assert latest["name"] == "2026-10-09-new" and latest["metrics"]["mandate"]["runs"] == 2
    assert latest["report"] == "# report 2026-10-09-new"


def test_latest_evaluation_is_not_found_without_results(tmp_path: Path) -> None:
    assert client(tmp_path).get("/v1/eval/latest", headers=H).status_code == 404


def test_demo_reset_seeds_the_demo_tenant_again() -> None:
    c = client()
    first = c.post("/v1/demo/reset", headers=H)
    assert first.status_code == 200, first.text
    again = c.post("/v1/demo/reset", headers=H).json()
    assert again["tenant_id"] == "demo" and again["typo_rule_id"].startswith("ins_")
    assert again["typo_rule_id"] != first.json()["typo_rule_id"]  # a fresh tenant
    assert "agent_token" not in again
    stats = c.get("/v1/tenants/demo/stats", headers=H)
    assert stats.status_code == 200
