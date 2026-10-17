"""Run an MCP server.

    python -m mandate.mcp_servers agent --token <agent token>                 (stdio)
    python -m mandate.mcp_servers admin --tenant T --owner prn_...            (stdio)
    python -m mandate.mcp_servers agent --http --port 8811
    python -m mandate.mcp_servers admin --http --port 8812

The admin key is MANDATE_API_KEY. Agent tokens are signed with MANDATE_TOKEN_SECRETS (newest
first, comma separated; defaults to a secret derived from the admin key) and expire after
MANDATE_TOKEN_TTL_SECONDS.
"""

from __future__ import annotations

import argparse
import sys

from mandate.api.tenancy import FalkorTenantBackend, Runtimes
from mandate.clock import SystemClock
from mandate.config import get_settings, token_secrets
from mandate.graph.client import GraphClient
from mandate.logging import configure_logging
from mandate.mcp_servers import resolvers
from mandate.mcp_servers.admin_server import AdminIdentity, build_admin_server
from mandate.mcp_servers.agent_server import build_agent_server
from mandate.mcp_servers.identity import verify_agent_token


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mandate.mcp_servers")
    parser.add_argument("profile", choices=["agent", "admin"])
    parser.add_argument("--http", action="store_true", help="serve streamable HTTP, not stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--token", help="agent token (stdio agent profile)")
    parser.add_argument("--tenant", help="tenant id (stdio admin profile)")
    parser.add_argument("--owner", help="owner principal id (stdio admin profile)")
    args = parser.parse_args(argv)

    settings = get_settings()
    secret = settings.require_api_key()
    secrets = token_secrets(settings)  # newest first; the first signs, all verify
    configure_logging(settings.mandate_log_level)  # logs go to stderr; stdout is the protocol
    runtimes = Runtimes(FalkorTenantBackend(GraphClient.from_settings(settings)), SystemClock())

    if args.profile == "agent":
        if args.http:
            identify = resolvers.http_agent(secrets)
        else:
            who = verify_agent_token(secrets, args.token)
            if who is None:
                print("a valid --token is required for the stdio agent profile", file=sys.stderr)
                return 2
            identify = resolvers.static_agent(who)
        server = build_agent_server(runtimes, identify)
    else:
        if args.http:
            admin_identify = resolvers.http_admin(secret)
        else:
            if not (args.tenant and args.owner):
                print(
                    "--tenant and --owner are required for the stdio admin profile", file=sys.stderr
                )
                return 2
            admin_identify = resolvers.static_admin(AdminIdentity(args.tenant, args.owner))
        server = build_admin_server(
            runtimes, admin_identify, secrets, settings.mandate_token_ttl_seconds
        )

    if args.http:
        server.run(
            "streamable-http",
            host=args.host,
            port=args.port or (8811 if args.profile == "agent" else 8812),
        )
    else:
        server.run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
