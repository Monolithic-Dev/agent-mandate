"""Mutation testing for the authority engine.

Breaks the decision logic one small edit at a time (flip a comparison, swap and/or, drop a
`not`, flip a boolean, shift an integer) and checks that the unit tests notice. A mutant the
tests do not catch is a gap in the tests, or an equivalent edit; survivors are listed so a
human can tell which.

    python scripts/mutation_test.py [--workers 4] [--out docs/results/<dir>] [--limit N]

Each worker mutates its own copy of the package (put first on PYTHONPATH), so the working tree
is never touched.
"""

from __future__ import annotations

import argparse
import ast
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "mandate"
TARGETS = [
    "authority/pdp.py",
    "authority/candidates.py",
    "authority/delegation.py",
    "authority/lineage.py",
    "authority/precedence.py",
    "authority/scope.py",
    "authority/check.py",
]
TESTS = [
    "tests/unit/spec",
    "tests/unit/test_authority_precedence.py",
    "tests/unit/test_authority_scope.py",
    "tests/unit/test_service.py",
]
TIMEOUT_SECONDS = 180

COMPARE_SWAPS: dict[type, type] = {
    ast.Lt: ast.LtE,
    ast.LtE: ast.Lt,
    ast.Gt: ast.GtE,
    ast.GtE: ast.Gt,
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
    ast.In: ast.NotIn,
    ast.NotIn: ast.In,
    ast.Is: ast.IsNot,
    ast.IsNot: ast.Is,
}


@dataclass(frozen=True)
class Mutant:
    file: str
    index: int
    line: int
    description: str


def _sites(tree: ast.AST) -> list[tuple[ast.AST, str]]:
    """Every mutable node with a label, in a stable traversal order."""
    found: list[tuple[ast.AST, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for i, op in enumerate(node.ops):
                if type(op) in COMPARE_SWAPS:
                    found.append(
                        (node, f"cmp{i}:{type(op).__name__}->{COMPARE_SWAPS[type(op)].__name__}")
                    )
        elif isinstance(node, ast.BoolOp):
            found.append((node, "and->or" if isinstance(node.op, ast.And) else "or->and"))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            found.append((node, "drop not"))
        elif isinstance(node, ast.Constant) and isinstance(node.value, bool):
            found.append((node, f"{node.value}->{not node.value}"))
        elif isinstance(node, ast.Constant) and type(node.value) is int and node.value >= 1:
            found.append((node, f"{node.value}->{node.value + 1}"))
    return found


def mutate(source: str, index: int) -> str:
    tree = ast.parse(source)
    sites = _sites(tree)
    node, label = sites[index]
    if label == "drop not":
        assert isinstance(node, ast.UnaryOp)
        operand = node.operand
        for parent in ast.walk(tree):
            for field, value in ast.iter_fields(parent):
                if value is node:
                    setattr(parent, field, operand)
                elif isinstance(value, list):
                    for i, item in enumerate(value):
                        if item is node:
                            value[i] = operand
    else:
        clone = copy.deepcopy(tree)
        target, _ = _sites(clone)[index]
        if isinstance(target, ast.Compare):
            position = int(label.split(":")[0][3:])
            target.ops[position] = COMPARE_SWAPS[type(target.ops[position])]()
        elif isinstance(target, ast.BoolOp):
            target.op = ast.Or() if isinstance(target.op, ast.And) else ast.And()
        elif isinstance(target, ast.Constant):
            target.value = (
                (not target.value) if isinstance(target.value, bool) else target.value + 1
            )
        tree = clone
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


def enumerate_mutants() -> list[Mutant]:
    mutants: list[Mutant] = []
    for relative in TARGETS:
        tree = ast.parse((PACKAGE / relative).read_text(encoding="utf-8"))
        for index, (node, label) in enumerate(_sites(tree)):
            mutants.append(Mutant(relative, index, getattr(node, "lineno", 0), label))
    return mutants


def run_worker_batch(worker: int, scratch: Path, batch: list[Mutant]) -> list[tuple[Mutant, str]]:
    copy_root = scratch / f"w{worker}"
    shutil.copytree(PACKAGE, copy_root / "mandate", ignore=shutil.ignore_patterns("__pycache__"))
    env = {**os.environ, "PYTHONPATH": str(copy_root), "PYTHONDONTWRITEBYTECODE": "1"}
    outcomes: list[tuple[Mutant, str]] = []
    originals: dict[str, str] = {}
    for mutant in batch:
        path = copy_root / "mandate" / mutant.file
        original = originals.setdefault(
            mutant.file, (PACKAGE / mutant.file).read_text(encoding="utf-8")
        )
        try:
            path.write_text(mutate(original, mutant.index), encoding="utf-8")
            command = [sys.executable, "-m", "pytest", *TESTS, "-x", "-q", "-p", "no:cacheprovider"]
            done = subprocess.run(
                command,
                cwd=ROOT,
                env=env,
                capture_output=True,
                timeout=TIMEOUT_SECONDS,
                check=False,
            )
            outcome = "survived" if done.returncode == 0 else "killed"
        except subprocess.TimeoutExpired:
            outcome = "killed"  # a mutant that hangs the suite is caught
        finally:
            path.write_text(original, encoding="utf-8")
        print(f"[{outcome:8}] {mutant.file}:{mutant.line} {mutant.description}", flush=True)
        outcomes.append((mutant, outcome))
    return outcomes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0, help="run only the first N mutants")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--min-score", type=float, default=0.0, help="fail below this percent")
    args = parser.parse_args()

    mutants = enumerate_mutants()
    if args.limit:
        mutants = mutants[: args.limit]
    print(f"{len(mutants)} mutants across {len(TARGETS)} files", flush=True)
    batches = [mutants[i :: args.workers] for i in range(args.workers)]
    with tempfile.TemporaryDirectory() as scratch, ThreadPoolExecutor(args.workers) as pool:
        futures = [
            pool.submit(run_worker_batch, i, Path(scratch), batch)
            for i, batch in enumerate(batches)
            if batch
        ]
        results = [pair for future in futures for pair in future.result()]

    survivors = sorted(
        (m for m, outcome in results if outcome == "survived"), key=lambda m: (m.file, m.line)
    )
    killed = len(results) - len(survivors)
    print(f"\nkilled {killed} of {len(results)} ({100 * killed / max(len(results), 1):.1f}%)")
    for m in survivors:
        print(f"  SURVIVOR {m.file}:{m.line} {m.description}")
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "mutation.json").write_text(
            json.dumps(
                {
                    "total": len(results),
                    "killed": killed,
                    "survivors": [m.__dict__ for m in survivors],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    score = 100 * killed / max(len(results), 1)
    if score < args.min_score:
        print(f"mutation score {score:.1f}% is below the required {args.min_score}%")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
