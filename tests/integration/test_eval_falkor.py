"""The whole evaluation against a real FalkorDB, through the command line entry point."""

import json
from pathlib import Path

import pytest

from mandate.eval.__main__ import main

pytestmark = pytest.mark.integration


def test_full_suite_meets_the_gates_and_writes_a_report(
    graph_client: object, tmp_path: Path
) -> None:
    exit_code = main(["--out", str(tmp_path)])
    assert exit_code == 0

    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "All thresholds met." in report and "95% Wilson interval" in report

    metrics = json.loads((tmp_path / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["mandate"]["unauthorised"][0] == 0
    assert metrics["mandate"]["false_blocks"][0] == 0
    assert metrics["mandate"]["explained"][0] == metrics["mandate"]["explained"][1] > 0
    assert metrics["naive"]["unauthorised"][0] > 0
    assert set(metrics["flat"]["unauthorised_by_family"]) == {"S2", "S3", "S8", "S9"}

    runs = (tmp_path / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(runs) == 104  # 26 scenarios x 4 agent kinds


def test_a_failed_gate_gives_a_non_zero_exit(graph_client: object, tmp_path: Path) -> None:
    # Only S1: the flat baseline then shows no unauthorised action in S2, so the gate fails.
    assert main(["--kinds", "flat", "--families", "S1", "--out", str(tmp_path)]) == 1


def test_no_matching_scenarios_is_an_error(graph_client: object, tmp_path: Path) -> None:
    assert main(["--families", "S7", "--out", str(tmp_path)]) == 2
