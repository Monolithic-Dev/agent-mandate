"""Lineage trust (AUTH-003). Breadth-first, bounded, cycle-safe."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from mandate.authority.ports import AuthorityReader, LineageNode
from mandate.models.domain import LineageTrust, Trust

MAX_LINEAGE_DEPTH = 6


@dataclass(frozen=True)
class LineageResult:
    trust: LineageTrust
    utterances: tuple[LineageNode, ...]
    # Nodes from the instruction up to the first trusted utterance (or the first utterance
    # when none is trusted), instruction first. Used to build explanation paths.
    trace: tuple[LineageNode, ...]


def classify(utterances: tuple[LineageNode, ...]) -> LineageTrust:
    """Trust of a set of origin utterances (AUTH-003)."""
    if not utterances:
        return LineageTrust.UNTRUSTED
    trusted = [u for u in utterances if u.trust is Trust.TRUSTED]
    if len(trusted) == len(utterances):
        return LineageTrust.TRUSTED
    if trusted:
        return LineageTrust.MIXED
    return LineageTrust.UNTRUSTED


def compute_lineage(
    reader: AuthorityReader, instruction_id: str, *, max_depth: int = MAX_LINEAGE_DEPTH
) -> LineageResult:
    """Walk upward from an instruction through EXPRESSES and DERIVED_FROM to utterances."""
    root = LineageNode(instruction_id, "Instruction")
    parents: dict[str, LineageNode | None] = {instruction_id: None}
    utterances: list[LineageNode] = []
    queue: deque[tuple[LineageNode, int]] = deque([(root, 0)])

    while queue:
        node, depth = queue.popleft()
        if node.label == "Utterance":
            utterances.append(node)
            continue
        if depth >= max_depth:
            continue
        for source in reader.lineage_sources(node.id):
            if source.id in parents:
                continue
            parents[source.id] = node
            queue.append((source, depth + 1))

    unique = tuple(utterances)
    trusted_first = next((u for u in unique if u.trust is Trust.TRUSTED), None)
    target = trusted_first or (unique[0] if unique else None)
    trace: list[LineageNode] = []
    cursor: LineageNode | None = target
    while cursor is not None:
        trace.append(cursor)
        cursor = parents[cursor.id]
    trace.reverse()
    return LineageResult(trust=classify(unique), utterances=unique, trace=tuple(trace))
