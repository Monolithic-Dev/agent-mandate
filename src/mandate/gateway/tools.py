"""The tools agents may call, each mapped to an action type and a resource.

The map is the single place that says which authority a tool needs. Agents never choose
their own action type or resource: the gateway derives them from the validated arguments.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import ConfigDict, Field

from mandate.gateway.sandbox import actions
from mandate.gateway.sandbox.state import Sandbox
from mandate.models.nul_free import NulFreeModel

MessageId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")]
Address = Annotated[str, Field(pattern=r"^[^\s/@]+@[^\s/@]+$", max_length=200)]
FilePath = Annotated[str, Field(min_length=1, max_length=200)]


class _Args(NulFreeModel):
    # strict: a JSON true is not 1 and 100.0 is not 100; wrong types are refused, not coerced.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)


class EmailListArgs(_Args):
    folder: Annotated[str, Field(pattern=r"^[a-z]{1,20}$")] = "inbox"
    limit: Annotated[int, Field(ge=1, le=100)] = 20


class MessageArgs(_Args):
    message_id: MessageId


class EmailSendArgs(_Args):
    to: Address
    subject: Annotated[str, Field(max_length=200)]
    body: Annotated[str, Field(max_length=4000)]


class RefundArgs(_Args):
    order_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")]
    amount: Annotated[int, Field(ge=1, le=actions.MAX_REFUND)]


class PathArgs(_Args):
    path: FilePath


class FileWriteArgs(_Args):
    path: FilePath
    content: Annotated[str, Field(max_length=4000)]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    model: type[_Args]
    action_type: str
    resource: Callable[[Any, Sandbox], str]
    run: Callable[[Sandbox, Any], dict[str, object]]
    # Arguments that constrain authority (only ``amount`` today); everything else is ignored
    # by the engine.
    check_args: Callable[[Any], dict[str, Any]] = lambda args: {}


def _msg_resource(args: MessageArgs, box: Sandbox) -> str:
    return f"{actions.folder_of(box, args.message_id)}/{args.message_id}"


def _safe_segment(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._@-]", "_", value)


TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in [
        ToolSpec(
            "email_list",
            EmailListArgs,
            "email.read",
            lambda a, b: f"{a.folder}/list",
            lambda box, a: actions.email_list(box, a.folder, a.limit),
        ),
        ToolSpec(
            "email_read",
            MessageArgs,
            "email.read",
            _msg_resource,
            lambda box, a: actions.email_read(box, a.message_id),
        ),
        ToolSpec(
            "email_archive",
            MessageArgs,
            "email.archive",
            _msg_resource,
            lambda box, a: actions.email_archive(box, a.message_id),
        ),
        ToolSpec(
            "email_delete",
            MessageArgs,
            "email.delete",
            _msg_resource,
            lambda box, a: actions.email_delete(box, a.message_id),
        ),
        ToolSpec(
            "email_send",
            EmailSendArgs,
            "email.send",
            lambda a, b: f"outbox/{_safe_segment(a.to)}",
            lambda box, a: actions.email_send(box, a.to, a.subject, a.body),
        ),
        ToolSpec(
            "refund_issue",
            RefundArgs,
            "refund.issue",
            lambda a, b: f"order/{a.order_id}",
            lambda box, a: actions.refund_issue(box, a.order_id, a.amount),
            lambda a: {"amount": a.amount},
        ),
        ToolSpec(
            "file_read",
            PathArgs,
            "file.read",
            lambda a, b: f"files/{actions.normalise_file_path(a.path)}",
            lambda box, a: actions.file_read(box, a.path),
        ),
        ToolSpec(
            "file_write",
            FileWriteArgs,
            "file.write",
            lambda a, b: f"files/{actions.normalise_file_path(a.path)}",
            lambda box, a: actions.file_write(box, a.path, a.content),
        ),
        ToolSpec(
            "file_delete",
            PathArgs,
            "file.delete",
            lambda a, b: f"files/{actions.normalise_file_path(a.path)}",
            lambda box, a: actions.file_delete(box, a.path),
        ),
    ]
}
