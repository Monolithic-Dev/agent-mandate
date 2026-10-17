"""Manage console users from the server's shell, for the first admin and for recovery.

    python -m mandate.users add dana@example.com --name Dana --role admin
    python -m mandate.users add ops@example.com --name Ops --role viewer --tenants demo,acme
    python -m mandate.users list
    python -m mandate.users reset-password dana@example.com
    python -m mandate.users disable ops@example.com      (and: enable)

The password is read from MANDATE_NEW_PASSWORD, else from standard input when it is not a
terminal (``--password-stdin`` style, for scripts), else asked for without echo. Every change
is written to the audit trail as done from the command line.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

from mandate.api.routes.auth import normalise_email
from mandate.api.sessions import hash_password
from mandate.clock import SystemClock
from mandate.config import get_settings
from mandate.errors import MandateError
from mandate.graph.client import GraphClient
from mandate.graph.directory import FalkorDirectory
from mandate.graph.tenants import tenant_graph_name
from mandate.ids import new_id
from mandate.logging import configure_logging
from mandate.models.accounts import (
    PASSWORD_MAX,
    PASSWORD_MIN,
    ActorKind,
    AuditEvent,
    Directory,
    Outcome,
    User,
    UserRole,
)


def read_password(confirm: bool) -> str:
    password = os.environ.get("MANDATE_NEW_PASSWORD")
    if password is None and not sys.stdin.isatty():
        password = sys.stdin.readline().rstrip("\r\n")
    if password is None:
        password = getpass.getpass("Password: ")
        if confirm and getpass.getpass("Again: ") != password:
            raise SystemExit("the passwords differ")
    if not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        raise SystemExit(f"a password needs {PASSWORD_MIN} to {PASSWORD_MAX} characters")
    return password


def audit(directory: Directory, action: str, user: User, at: int) -> None:
    directory.record_audit(
        AuditEvent(
            id=new_id("aud", now_ms=at),
            at=at,
            actor_kind=ActorKind.CLI,
            actor_name=f"command line ({getpass.getuser()})",
            action=action,
            method="CLI",
            route=f"mandate.users {action.split('.', 1)[1].replace('_', '-')}",
            target=user.id,
            status=0,
            outcome=Outcome.SUCCESS,
        )
    )


def run(args: argparse.Namespace, directory: Directory, now_ms: int) -> int:
    if args.command == "list":
        for u in directory.list_users():
            scope = "all tenants" if u.tenants is None else ",".join(u.tenants)
            state = "disabled" if u.disabled else "active"
            print(f"{u.id}  {u.email:<32} {u.role.value:<8} {state:<8} {scope}")
        return 0
    email = normalise_email(args.email)
    if args.command == "add":
        tenants = None
        if args.tenants:
            tenants = tuple(sorted({t.strip() for t in args.tenants.split(",") if t.strip()}))
            for tenant_id in tenants:
                tenant_graph_name(tenant_id)
        user = directory.create_user(
            User(
                id=new_id("usr", now_ms=now_ms),
                email=email,
                name=args.name or email.split("@")[0],
                role=UserRole(args.role),
                tenants=tenants,
                created_at=now_ms,
                updated_at=now_ms,
                password_hash=hash_password(read_password(confirm=True)),
            )
        )
        audit(directory, "user.create", user, now_ms)
        print(f"created {user.id} ({user.email}, {user.role.value})")
        return 0
    found = directory.find_user_by_email(email)
    if found is None:
        print(f"no user has the email {email}", file=sys.stderr)
        return 1
    user = found
    if args.command == "reset-password":
        user = directory.set_password(user.id, hash_password(read_password(True)), now_ms)
        directory.end_sessions(user.id)
        audit(directory, "user.password_reset", user, now_ms)
        print(f"password reset for {user.email}; their sessions have ended")
    else:
        disabled = args.command == "disable"
        changed = user.model_copy(update={"disabled": disabled, "updated_at": now_ms})
        user = directory.update_user(User.model_validate(changed.model_dump()))
        if disabled:
            directory.end_sessions(user.id)
        audit(directory, "user.update", user, now_ms)
        print(f"{user.email} is now {'disabled' if disabled else 'active'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mandate.users", description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add", help="create a user")
    add.add_argument("email")
    add.add_argument("--name")
    add.add_argument("--role", choices=[r.value for r in UserRole], default="viewer")
    add.add_argument("--tenants", help="comma list; omit for every tenant")
    commands.add_parser("list", help="list users")
    for name in ("reset-password", "disable", "enable"):
        commands.add_parser(name).add_argument("email")
    args = parser.parse_args(argv)

    configure_logging("WARNING")
    graph = GraphClient.from_settings(get_settings())
    if not graph.ping():
        print("FalkorDB is not reachable", file=sys.stderr)
        return 2
    try:
        return run(args, FalkorDirectory(graph), SystemClock().now_ms())
    except MandateError as error:
        print(error.message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
