"""The owner-facing MCP server: say rules, approve held actions, inspect and undo.

Run it separately from the agent server. An agent is only ever given the agent server's
address and token, so it has no path to these tools and cannot approve its own actions.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from mcp.server.mcpserver import Context, MCPServer

from mandate.api.tenancy import Runtimes
from mandate.authority.verify import verify_decision
from mandate.gateway.guard import resolve_pending
from mandate.lineage.blast_radius import blast_radius, quarantine
from mandate.lineage.reliance import rank_reliance
from mandate.lineage.replay import replay_without
from mandate.mcp_servers.identity import (
    DEFAULT_TTL_SECONDS,
    AgentIdentity,
    mint_agent_token_with_id,
    revoke_token,
)
from mandate.models.domain import ActionStatus, Channel


@dataclass(frozen=True)
class AdminIdentity:
    tenant_id: str
    owner_id: str


IdentifyAdmin = Callable[[Context[Any]], AdminIdentity]


def build_admin_server(
    runtimes: Runtimes,
    identify: IdentifyAdmin,
    token_secret: str | Sequence[str],
    token_ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> MCPServer:
    """``token_secret`` is one secret or a ring, newest first: the first signs, all verify."""
    ring = [token_secret] if isinstance(token_secret, str) else list(token_secret)
    server = MCPServer(
        "agent-mandate-admin",
        instructions="Owner tools. Everything here acts as the owner of one tenant.",
    )

    def runtime_and_owner(ctx: Context[Any]) -> tuple[Any, str]:
        who = identify(ctx)
        runtime = runtimes.require(who.tenant_id)
        runtime.service.require_owner(who.owner_id)
        return runtime, who.owner_id

    @server.tool()
    def say(text: str, ctx: Context[Any]) -> dict[str, Any]:
        """State a rule or preference as the owner, e.g. 'Never delete any email.'"""
        runtime, owner = runtime_and_owner(ctx)
        result = runtime.service.ingest_utterance(
            principal_id=owner, text=text, channel=Channel.OWNER_DIRECT
        )
        return {
            "utterance_id": result.utterance.id,
            "instructions": [
                {
                    "id": item.instruction.id,
                    "action_type": item.action_type,
                    "effect": item.instruction.effect.value,
                    "needs_confirmation": item.needs_confirmation,
                }
                for item in result.instructions
            ],
            "unparsed": result.unparsed,
        }

    @server.tool()
    def confirm_instruction(instruction_id: str, ctx: Context[Any]) -> dict[str, Any]:
        """Activate a proposed rule."""
        runtime, owner = runtime_and_owner(ctx)
        done = runtime.service.confirm_instruction(instruction_id, owner)
        return {"id": done.id, "status": done.status.value}

    @server.tool()
    def revoke_instruction(instruction_id: str, ctx: Context[Any]) -> dict[str, Any]:
        """Revoke a rule; it stops applying from the next check."""
        runtime, owner = runtime_and_owner(ctx)
        done = runtime.service.revoke_instruction(instruction_id, owner)
        return {"id": done.id, "status": done.status.value}

    @server.tool()
    def pending_approvals(ctx: Context[Any]) -> list[dict[str, Any]]:
        """Actions held for the owner's approval."""
        runtime, _ = runtime_and_owner(ctx)
        rows = runtime.store.list_actions(status=ActionStatus.PENDING, limit=50)
        return [
            {
                "action_id": row.action.id,
                "agent_id": row.agent_id,
                "action_type": row.action.action_type,
                "resource": row.action.resource,
                "decision_id": row.decision_id,
            }
            for row in rows
        ]

    @server.tool()
    def resolve_approval(action_id: str, approve: bool, ctx: Context[Any]) -> dict[str, Any]:
        """Approve (runs the held action) or decline it."""
        runtime, owner = runtime_and_owner(ctx)
        return resolve_pending(runtime.gateway, action_id, owner, approved=approve).to_dict()

    @server.tool()
    def explain_decision(decision_id: str, ctx: Context[Any]) -> dict[str, Any]:
        """Why an action was allowed, held or denied, with the chain that decided it."""
        runtime, _ = runtime_and_owner(ctx)
        explanation = runtime.service.explain(decision_id)
        return {
            "narrative": explanation.narrative,
            "result": explanation.decision.result.value,
            "path": [hop.model_dump() for hop in explanation.decision.path],
        }

    @server.tool()
    def verify_explanation(decision_id: str, ctx: Context[Any]) -> dict[str, Any]:
        """Re-check every claim in a decision's stored explanation against the graph."""
        runtime, _ = runtime_and_owner(ctx)
        result = verify_decision(runtime.store, decision_id)
        return {
            "decision_id": result.decision_id,
            "ok": result.ok,
            "failures": [{"name": c.name, "detail": c.detail} for c in result.failures],
            "checks": len(result.checks),
        }

    @server.tool()
    def blast_radius_of(instruction_id: str, ctx: Context[Any]) -> dict[str, Any]:
        """Every instruction and decision that depended on this rule."""
        runtime, _ = runtime_and_owner(ctx)
        return asdict(blast_radius(runtime.store, instruction_id))

    @server.tool()
    def quarantine_instruction(
        instruction_id: str, ctx: Context[Any], release: bool = False
    ) -> dict[str, Any]:
        """Stop a mistaken rule and everything derived from it (or release it again)."""
        runtime, owner = runtime_and_owner(ctx)
        now = runtimes.clock.now_ms()
        ids = quarantine(runtime.store, instruction_id, value=not release, at=now, by=owner)
        return {"instruction_ids": ids, "quarantined": not release}

    @server.tool()
    def replay_without_instruction(instruction_id: str, ctx: Context[Any]) -> dict[str, Any]:
        """Re-decide past actions as if this rule had never existed (on a throwaway copy)."""
        runtime, _ = runtime_and_owner(ctx)
        return asdict(replay_without(runtime.store, runtimes.clock, instruction_id))

    @server.tool()
    def reliance(ctx: Context[Any], limit: int = 10) -> list[dict[str, Any]]:
        """Which rules the recorded decisions leaned on most, and which are shaky."""
        runtime, _ = runtime_and_owner(ctx)
        rows = rank_reliance(runtime.store, max(1, min(limit, 50)))
        return [{**asdict(row), "needs_review": row.needs_review} for row in rows]

    @server.tool()
    def agent_token(
        agent_id: str, ctx: Context[Any], ttl_seconds: int | None = None
    ) -> dict[str, Any]:
        """A signed, expiring token that lets one agent connect to the agent server as itself."""
        who = identify(ctx)
        runtime, _ = runtime_and_owner(ctx)
        runtime.store.get_agent(agent_id)  # raises NotFound for a stranger
        ttl = token_ttl_seconds if ttl_seconds is None else ttl_seconds
        token, minted = mint_agent_token_with_id(
            ring[0], AgentIdentity(who.tenant_id, agent_id), ttl_seconds=ttl
        )
        return {
            "token": token,
            "token_id": minted.token_id,
            "expires_at": minted.expires_at,
            "expires_in_seconds": ttl,
        }

    @server.tool()
    def revoke_agent_token(
        ctx: Context[Any], token_id: str | None = None, token: str | None = None
    ) -> dict[str, Any]:
        """Revoke one agent token before it expires, by its id or by the token itself.

        Other tokens for the same agent keep working; the revoked one is refused from its
        next call.
        """
        who = identify(ctx)
        runtime, owner = runtime_and_owner(ctx)
        return revoke_token(runtime.service, who.tenant_id, owner, token_id, token, ring)

    return server
