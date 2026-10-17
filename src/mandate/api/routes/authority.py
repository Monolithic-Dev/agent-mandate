"""Principals, agents, utterances, instructions, delegations, checks and explanations."""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError

from mandate.api.audit import note_created
from mandate.api.errors import request_id_of
from mandate.api.routes.tenants import runtimes_of
from mandate.api.security import require_caller
from mandate.api.tenancy import TenantRuntime
from mandate.authority.verify import verify_decision
from mandate.errors import GraphUnavailable, ValidationFailure
from mandate.ids import new_id
from mandate.lineage.whatif import preview_utterance
from mandate.models.api import (
    ByPrincipal,
    CheckIn,
    CheckOut,
    CheckResultOut,
    CreateAgent,
    CreatePrincipal,
    DelegationIn,
    DelegationOut,
    ExplainOut,
    IngestedInstructionOut,
    InstructionView,
    PreviewIn,
    UtteranceIn,
    UtteranceOut,
    VerifyOut,
)
from mandate.models.domain import Agent, CheckRequest, Instruction, Principal, Result
from mandate.observability import metrics

router = APIRouter(
    prefix="/v1/tenants/{tenant_id}", tags=["authority"], dependencies=[Depends(require_caller)]
)


def runtime_for(tenant_id: str, request: Request) -> TenantRuntime:
    return runtimes_of(request).require(tenant_id)


# --- principals and agents ---------------------------------------------------------


@router.post("/principals", status_code=201, response_model=Principal)
def create_principal(tenant_id: str, body: CreatePrincipal, request: Request) -> Principal:
    runtime = runtime_for(tenant_id, request)
    principal = runtime.store.create_principal(
        Principal(id=new_id("prn"), name=body.name, role=body.role)
    )
    note_created(request, principal.id)
    return principal


@router.get("/principals", response_model=list[Principal])
def list_principals(tenant_id: str, request: Request) -> list[Principal]:
    return runtime_for(tenant_id, request).store.list_principals()


@router.post("/agents", status_code=201, response_model=Agent)
def create_agent(tenant_id: str, body: CreateAgent, request: Request) -> Agent:
    runtime = runtime_for(tenant_id, request)
    agent = runtime.store.create_agent(Agent(id=new_id("agt"), name=body.name, kind=body.kind))
    note_created(request, agent.id)
    return agent


@router.get("/agents", response_model=list[Agent])
def list_agents(tenant_id: str, request: Request) -> list[Agent]:
    return runtime_for(tenant_id, request).store.list_agents()


# --- utterances and instructions ---------------------------------------------------


@router.post("/utterances/preview")
def preview(tenant_id: str, body: PreviewIn, request: Request) -> dict[str, Any]:
    """What saying this would do: the rules, what it conflicts with, and which recent
    requests would be decided differently. Read-only (a throwaway copy of the graph)."""
    runtime = runtime_for(tenant_id, request)
    result = preview_utterance(
        runtime.store,
        runtimes_of(request).clock,
        principal_id=body.principal_id,
        text=body.text,
        agent_ids=body.agent_ids,
    )
    return asdict(result)


@router.post("/utterances", status_code=201, response_model=UtteranceOut)
def ingest_utterance(
    tenant_id: str, body: UtteranceIn, request: Request, extract: str | None = None
) -> UtteranceOut:
    if extract is not None:
        # The optional model-based extractor arrives with the agents phase.
        raise ValidationFailure("model-based extraction is not available yet")
    runtime = runtime_for(tenant_id, request)
    result = runtime.service.ingest_utterance(
        principal_id=body.principal_id,
        text=body.text,
        channel=body.channel,
        agent_ids=body.agent_ids,
        source_ref=body.source_ref,
        at=body.at,
    )
    note_created(request, result.utterance.id)
    return UtteranceOut(
        utterance_id=result.utterance.id,
        channel=result.utterance.channel,
        trust=result.utterance.trust.value,
        at=result.utterance.at,
        instructions=[
            IngestedInstructionOut(
                instruction=item.instruction,
                action_type=item.action_type,
                resource_pattern=item.resource_pattern,
                max_amount=item.max_amount,
                needs_confirmation=item.needs_confirmation,
                inert=item.inert,
            )
            for item in result.instructions
        ],
        unparsed=result.unparsed,
    )


@router.get("/instructions", response_model=list[InstructionView])
def list_instructions(
    tenant_id: str, request: Request, status: str | None = None, agent_id: str | None = None
) -> list[InstructionView]:
    runtime = runtime_for(tenant_id, request)
    records = runtime.store.list_instructions(status=status, agent_id=agent_id)
    return [
        InstructionView(instruction=r.instruction, scope=r.scope, agent_id=r.agent_id)
        for r in records
    ]


@router.post("/instructions/{instruction_id}/confirm", response_model=Instruction)
def confirm_instruction(
    tenant_id: str, instruction_id: str, body: ByPrincipal, request: Request
) -> Instruction:
    runtime = runtime_for(tenant_id, request)
    return runtime.service.confirm_instruction(instruction_id, body.by)


@router.post("/instructions/{instruction_id}/revoke", response_model=Instruction)
def revoke_instruction(
    tenant_id: str, instruction_id: str, body: ByPrincipal, request: Request
) -> Instruction:
    runtime = runtime_for(tenant_id, request)
    return runtime.service.revoke_instruction(instruction_id, body.by)


# --- delegations -------------------------------------------------------------------


@router.post("/delegations", status_code=201, response_model=DelegationOut)
def create_delegation(tenant_id: str, body: DelegationIn, request: Request) -> DelegationOut:
    runtime = runtime_for(tenant_id, request)
    delegation = runtime.service.delegate(
        from_agent_id=body.from_agent,
        to_agent_id=body.to_agent,
        action_type=body.action_type,
        by_principal_id=body.by,
        resource_pattern=body.resource_pattern,
        max_amount=body.max_amount,
        valid_to=body.valid_to,
        via_instruction=body.via_instruction,
    )
    note_created(request, delegation.id)
    return DelegationOut(id=delegation.id, created_at=delegation.created_at)


@router.post("/delegations/{delegation_id}/revoke", status_code=200)
def revoke_delegation(
    tenant_id: str, delegation_id: str, body: ByPrincipal, request: Request
) -> dict[str, str]:
    runtime = runtime_for(tenant_id, request)
    runtime.service.revoke_delegation(delegation_id, body.by)
    return {"status": "revoked", "id": delegation_id}


# --- check and explain -------------------------------------------------------------


@router.post("/check", response_model=CheckOut)
def check(tenant_id: str, body: CheckIn, request: Request) -> CheckOut:
    runtime = runtime_for(tenant_id, request)
    try:
        check_request = CheckRequest(
            agent_id=body.agent_id,
            action_type=body.action_type,
            resource=body.resource,
            args=body.args,
            as_of=body.as_of,
        )
    except ValidationError as error:
        raise ValidationFailure(error.errors()[0]["msg"]) from error
    recorded = not body.dry_run and body.as_of is None
    began = time.perf_counter()
    checked = runtime.service.check(
        check_request, persist=recorded, request_id=request_id_of(request)
    )
    if checked.error_kind == "graph_unavailable":
        raise GraphUnavailable("the graph database is unreachable")
    decision = checked.decision
    metrics.DECISION_SECONDS.labels("api").observe(time.perf_counter() - began)
    metrics.DECISIONS.labels(decision.result.value, decision.reason.value, "api").inc()
    return CheckOut(
        decision_id=decision.id if recorded else None,
        result=decision.result,
        reason=decision.reason,
        action_id=checked.action.id if recorded else None,
        recorded=recorded,
        approval_required=decision.result is Result.CONFIRM,
        path=decision.path,
        ignored=decision.ignored,
        latency_ms=decision.latency_ms,
    )


@router.get("/decisions/{decision_id}/explain", response_model=ExplainOut)
def explain(tenant_id: str, decision_id: str, request: Request) -> ExplainOut:
    explanation = runtime_for(tenant_id, request).service.explain(decision_id)
    return ExplainOut(
        decision=explanation.decision,
        action=explanation.action,
        used=[{"id": i, "role": role} for i, role in explanation.used],
        narrative=explanation.narrative,
    )


@router.get("/decisions/{decision_id}/verify", response_model=VerifyOut)
def verify(tenant_id: str, decision_id: str, request: Request) -> VerifyOut:
    """Re-check every claim in the stored explanation against the graph."""
    result = verify_decision(runtime_for(tenant_id, request).store, decision_id)
    return VerifyOut(
        decision_id=result.decision_id,
        ok=result.ok,
        checks=[CheckResultOut(name=c.name, ok=c.ok, detail=c.detail) for c in result.checks],
    )


@router.get("/decisions")
def list_decisions(
    tenant_id: str, request: Request, agent_id: str | None = None, limit: int = 50
) -> list[dict[str, object]]:
    runtime = runtime_for(tenant_id, request)
    bounded = max(1, min(limit, 200))
    return [
        {
            "decision": row.decision.model_dump(mode="json"),
            "action": row.action.model_dump(mode="json"),
            "agent_id": row.agent_id,
        }
        for row in runtime.store.list_decisions(agent_id=agent_id, limit=bounded)
    ]
