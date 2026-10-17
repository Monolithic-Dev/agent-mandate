"""The agent-facing MCP server: every tool goes through the guarded call.

The tool list is generated from ``TOOLS`` so it cannot drift from the gateway. The agent's
identity comes from ``identify`` (a signed token), never from a tool argument, and this
server has no approval or administration tools at all.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer

from mandate.api.tenancy import Runtimes, TenantRuntime
from mandate.errors import MandateError
from mandate.gateway.guard import guarded_call
from mandate.gateway.tools import TOOLS, ToolSpec
from mandate.mcp_servers.identity import AgentIdentity
from mandate.models.domain import CheckRequest

Identify = Callable[[Context[Any]], AgentIdentity]

INSTRUCTIONS = (
    "Every tool call is checked against rules the owner has stated. A call may run, be held "
    "for the owner's approval (status confirmation_required), or be denied with a reason. "
    "Do not retry a denied call with different wording; ask the owner instead."
)


def _signature(spec: ToolSpec) -> inspect.Signature:
    """A flat signature from the tool's argument model, so clients see real parameters."""
    parameters = [
        inspect.Parameter(
            name,
            inspect.Parameter.KEYWORD_ONLY,
            default=inspect.Parameter.empty if field.is_required() else field.default,
            annotation=Annotated[field.annotation, *field.metadata],
        )
        for name, field in spec.model.model_fields.items()
    ]
    parameters.append(
        inspect.Parameter("ctx", inspect.Parameter.KEYWORD_ONLY, annotation=Context[Any])
    )
    return inspect.Signature(parameters, return_annotation=dict[str, Any])


def build_agent_server(runtimes: Runtimes, identify: Identify) -> MCPServer:
    server = MCPServer("agent-mandate", instructions=INSTRUCTIONS)

    def caller(ctx: Context[Any]) -> tuple[AgentIdentity, TenantRuntime]:
        """Who is calling and their tenant's runtime, refusing a revoked token on every call."""
        who = identify(ctx)
        runtime = runtimes.require(who.tenant_id)
        if who.token_id is not None and runtime.service.token_revoked(who.token_id):
            raise PermissionError("this agent token has been revoked")
        return who, runtime

    def register(spec: ToolSpec) -> None:
        def run(**kwargs: Any) -> dict[str, Any]:
            who, runtime = caller(kwargs.pop("ctx"))
            return guarded_call(runtime.gateway, who.agent_id, spec.name, kwargs).to_dict()

        signature = _signature(spec)
        run.__signature__ = signature  # type: ignore[attr-defined]
        # The SDK finds the context parameter through annotations as well as the signature.
        run.__annotations__ = {n: p.annotation for n, p in signature.parameters.items()}
        run.__name__ = spec.name
        server.add_tool(run, name=spec.name, description=f"{spec.name} (needs {spec.action_type})")

    for spec in TOOLS.values():
        register(spec)

    @server.tool()
    def whoami(ctx: Context[Any]) -> dict[str, str]:
        """The tenant and agent this connection acts as."""
        who, _ = caller(ctx)
        return {"tenant_id": who.tenant_id, "agent_id": who.agent_id}

    @server.tool()
    def can_i(action_type: str, resource: str, ctx: Context[Any]) -> dict[str, Any]:
        """Ask whether an action would be allowed, held or denied, without running it."""
        who, runtime = caller(ctx)
        try:
            request = CheckRequest(
                agent_id=who.agent_id, action_type=action_type, resource=resource
            )
        except (ValueError, MandateError) as error:
            return {"result": "deny", "reason": "bad_arguments", "message": str(error)[:200]}
        # A question, not an action: nothing is recorded, so probing cannot fill the owner's
        # approval queue or inflate blast radius and reliance counts.
        decision = runtime.service.check(request, persist=False).decision
        return {"result": decision.result.value, "reason": decision.reason.value}

    return server
