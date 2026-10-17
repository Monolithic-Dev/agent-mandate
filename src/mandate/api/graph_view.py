"""A tenant's graph as Cytoscape elements, with an optional decision path highlighted.

Display only: captions and classes are derived from stored properties, and nothing here
feeds a decision. Classes carry state (result, status, trust) so the UI can style it,
always alongside a text caption so colour is never the only signal.
"""

from __future__ import annotations

from typing import Any

from mandate.authority.ports import GraphEdge, GraphNode, GraphSnapshot
from mandate.models.api import GraphElement, GraphOut

# Properties copied to the element per label (never decision paths or raw arguments).
_FIELDS: dict[str, tuple[str, ...]] = {
    "Principal": ("name", "role"),
    "Agent": ("name", "kind"),
    "Utterance": ("text", "channel", "trust", "at"),
    "Summary": ("text", "at"),
    "Instruction": (
        "effect",
        "status",
        "text_span",
        "lineage_trust",
        "quarantined",
        "activated_at",
        "revoked_at",
    ),
    "Scope": ("action_type", "resource_pattern"),
    "Action": ("action_type", "resource", "status", "at"),
    "Decision": ("result", "reason", "at", "as_of"),
    "Approval": ("approved", "by", "at"),
}

_CAPTION_LIMIT = 48


def _short(text: Any) -> str:
    value = " ".join(str(text).split())
    return value if len(value) <= _CAPTION_LIMIT else value[: _CAPTION_LIMIT - 1] + "…"


def caption(node: GraphNode) -> str:
    p = node.props
    match node.label:
        case "Principal":
            return f"{p.get('name', node.id)} ({p.get('role', '?')})"
        case "Agent":
            return f"{p.get('name', node.id)} ({p.get('kind', '?')})"
        case "Utterance" | "Summary":
            return _short(p.get("text", node.id))
        case "Instruction":
            return f"{p.get('effect', '?')}: {_short(p.get('text_span', ''))}"
        case "Scope":
            return f"{p.get('action_type', '?')} on {p.get('resource_pattern', '?')}"
        case "Action":
            return f"{p.get('action_type', '?')} {p.get('resource', '')}".strip()
        case "Decision":
            return f"{str(p.get('result', '?')).upper()}: {p.get('reason', '')}"
        case "Approval":
            return "approved" if p.get("approved") else "declined"
    return node.id


def _node_classes(node: GraphNode) -> list[str]:
    p = node.props
    classes = [node.label.lower()]
    if node.label == "Instruction":
        classes += [str(p.get("status", "")), str(p.get("lineage_trust", ""))]
        if p.get("quarantined"):
            classes.append("quarantined")
    elif node.label == "Utterance":
        classes.append(str(p.get("trust", "")))
    elif node.label == "Decision":
        classes.append(str(p.get("result", "")))
    elif node.label == "Action":
        classes.append(str(p.get("status", "")))
    return [c for c in classes if c]


def _edge_id(edge: GraphEdge) -> str:
    # A delegation's edge carries the delegation id, which decision paths cite.
    if edge.type == "DELEGATES_TO" and edge.props.get("id"):
        return str(edge.props["id"])
    return f"{edge.source}>{edge.type}>{edge.target}"


def to_elements(snapshot: GraphSnapshot, highlight: set[str] | None = None) -> GraphOut:
    """Cytoscape elements; nodes and edges whose ids are in ``highlight`` are marked."""
    marked = highlight or set()
    untrusted = {
        n.id
        for n in snapshot.nodes
        if (n.label == "Utterance" and n.props.get("trust") == "untrusted")
        or (n.label == "Instruction" and n.props.get("lineage_trust") == "untrusted")
    }
    elements: list[GraphElement] = []
    for node in snapshot.nodes:
        classes = _node_classes(node) + (["highlight"] if node.id in marked else [])
        data = {"id": node.id, "label": node.label, "caption": caption(node)}
        data.update({k: node.props[k] for k in _FIELDS.get(node.label, ()) if k in node.props})
        elements.append(GraphElement(group="nodes", data=data, classes=" ".join(classes)))
    for edge in snapshot.edges:
        edge_id = _edge_id(edge)
        classes = [edge.type.lower()]
        if edge.source in untrusted:
            classes.append("untrusted")
        if edge.type == "DELEGATES_TO" and edge.props.get("revoked_at") is not None:
            classes.append("revoked")
        if edge_id in marked or (edge.source in marked and edge.target in marked):
            classes.append("highlight")
        data = {"id": edge_id, "source": edge.source, "target": edge.target, "label": edge.type}
        if edge.type == "USED" and edge.props.get("role"):
            data["role"] = edge.props["role"]
        elements.append(GraphElement(group="edges", data=data, classes=" ".join(classes)))
    present = {n.id for n in snapshot.nodes} | {_edge_id(e) for e in snapshot.edges}
    return GraphOut(
        elements=elements,
        truncated=snapshot.truncated,
        highlight=sorted(marked & present),
    )
