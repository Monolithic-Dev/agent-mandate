"""Convert graph property dictionaries to domain models (and back where needed)."""

from __future__ import annotations

import json
from typing import Any

from mandate.models.domain import (
    Action,
    Constraints,
    Decision,
    Delegation,
    IgnoredInstruction,
    Instruction,
    PathHop,
    Scope,
)


def instruction_from_props(props: dict[str, Any]) -> Instruction:
    return Instruction.model_validate(props)


def scope_from_props(props: dict[str, Any]) -> Scope:
    data = dict(props)
    data["constraints"] = Constraints.from_json(data.get("constraints") or "{}")
    return Scope.model_validate(data)


def delegation_from_props(props: dict[str, Any], from_agent: str, to_agent: str) -> Delegation:
    data = dict(props)
    data["constraints"] = Constraints.from_json(data.get("constraints") or "{}")
    data["from_agent"] = from_agent
    data["to_agent"] = to_agent
    return Delegation.model_validate(data)


def action_from_props(props: dict[str, Any]) -> Action:
    data = dict(props)
    data["args"] = json.loads(data.get("args") or "{}")
    return Action.model_validate(data)


def decision_from_props(props: dict[str, Any]) -> Decision:
    data = dict(props)
    data["path"] = [PathHop.model_validate(hop) for hop in json.loads(data.pop("path_json"))]
    data["ignored"] = [
        IgnoredInstruction.model_validate(item)
        for item in json.loads(data.pop("ignored_json", "[]") or "[]")
    ]
    return Decision.model_validate(data)
