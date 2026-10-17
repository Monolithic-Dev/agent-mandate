"""The sandbox operations. Each validates its input and reports failures as errors."""

from __future__ import annotations

import posixpath

from mandate.errors import NotFound, ValidationFailure
from mandate.gateway.sandbox.state import Message, Sandbox

MAX_REFUND = 100_000


def _message(box: Sandbox, message_id: str) -> Message:
    message = box.messages.get(message_id)
    if message is None:
        raise NotFound(f"no such message: {message_id!r}")
    return message


def folder_of(box: Sandbox, message_id: str) -> str:
    """The folder a message lives in, or ``inbox`` if it is unknown."""
    message = box.messages.get(message_id)
    return message.folder if message else "inbox"


def email_list(box: Sandbox, folder: str, limit: int) -> dict[str, object]:
    rows = [m for m in box.messages.values() if m.folder == folder][:limit]
    return {"messages": [{"id": m.id, "from": m.sender, "subject": m.subject} for m in rows]}


def email_read(box: Sandbox, message_id: str) -> dict[str, object]:
    m = _message(box, message_id)
    return {"id": m.id, "from": m.sender, "subject": m.subject, "body": m.body}


def email_archive(box: Sandbox, message_id: str) -> dict[str, object]:
    _message(box, message_id).folder = "archive"
    return {"status": "archived", "id": message_id}


def email_delete(box: Sandbox, message_id: str) -> dict[str, object]:
    _message(box, message_id)
    del box.messages[message_id]
    return {"status": "deleted", "id": message_id}


def email_send(box: Sandbox, to: str, subject: str, body: str) -> dict[str, object]:
    box.sent.append({"to": to, "subject": subject, "body": body})
    return {"status": "sent", "to": to}


def refund_issue(box: Sandbox, order_id: str, amount: int) -> dict[str, object]:
    order = box.orders.get(order_id)
    if order is None:
        raise NotFound(f"no such order: {order_id!r}")
    if amount <= 0 or amount > MAX_REFUND:
        raise ValidationFailure("refund amount is out of range")
    if order.refunded_amount + amount > order.amount:
        raise ValidationFailure("refund exceeds the order amount")
    order.refunded_amount += amount
    return {"status": "refunded", "order": order_id, "amount": amount}


def normalise_file_path(path: str) -> str:
    cleaned = posixpath.normpath(path.strip()).lstrip("/")
    if not cleaned or cleaned == "." or ".." in cleaned.split("/"):
        raise ValidationFailure("invalid file path")
    return cleaned


def file_read(box: Sandbox, path: str) -> dict[str, object]:
    key = normalise_file_path(path)
    if key not in box.files:
        raise NotFound(f"no such file: {key!r}")
    return {"path": key, "content": box.files[key]}


def file_write(box: Sandbox, path: str, content: str) -> dict[str, object]:
    key = normalise_file_path(path)
    box.files[key] = content
    return {"status": "written", "path": key}


def file_delete(box: Sandbox, path: str) -> dict[str, object]:
    key = normalise_file_path(path)
    if key not in box.files:
        raise NotFound(f"no such file: {key!r}")
    del box.files[key]
    return {"status": "deleted", "path": key}
