"""Command line: ``python -m mandate.eval`` runs the suite against a real FalkorDB.

Exit status is 1 if a gate in docs/evaluation.md fails.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from mandate.config import Settings
from mandate.eval.report import gate, summarise, write_report
from mandate.eval.runner import KINDS, run_suite
from mandate.eval.scenario import SCENARIO_DIR, load_scenarios
from mandate.graph.client import GraphClient
from mandate.graph.schema import ensure_schema
from mandate.graph.store import FalkorAuthorityStore
from mandate.ids import new_id
from mandate.logging import configure_logging


def falkor_provider(client: GraphClient):  # type: ignore[no-untyped-def]
    @contextmanager
    def provide() -> Iterator[FalkorAuthorityStore]:
        name = f"t_eval_{new_id('act')[4:].lower()}"
        ensure_schema(client, name)
        try:
            yield FalkorAuthorityStore(client, name)
        finally:
            client.delete_graph(name)

    return provide


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mandate.eval", description=__doc__)
    parser.add_argument("--kinds", nargs="+", choices=KINDS, default=list(KINDS))
    parser.add_argument("--families", nargs="+", help="scenario families to run, e.g. S1 S2")
    parser.add_argument("--scenarios", type=Path, default=SCENARIO_DIR)
    parser.add_argument("--out", type=Path, default=None, help="results directory")
    args = parser.parse_args(argv)
    configure_logging("WARNING")  # keep the report readable; decisions are in the graph

    client = GraphClient.from_settings(Settings())
    if not client.ping():
        print("FalkorDB is not reachable; start it with scripts/dev.ps1 up", file=sys.stderr)
        return 2

    scenarios = [
        s for s in load_scenarios(args.scenarios) if not args.families or s.family in args.families
    ]
    if not scenarios:
        print("no scenarios matched", file=sys.stderr)
        return 2
    results = run_suite(scenarios, args.kinds, falkor_provider(client))
    summaries = summarise(results)
    failures = gate(summaries)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out_dir = args.out or Path("eval") / "results" / stamp
    report = write_report(results, summaries, failures, out_dir)
    print(report.read_text(encoding="utf-8"))
    print(f"report written to {report}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
