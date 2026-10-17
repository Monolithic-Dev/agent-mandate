import pytest
from pydantic import ValidationError

from mandate.errors import NotFound, ValidationFailure
from mandate.gateway.sandbox import actions
from mandate.gateway.sandbox.state import INJECTION_TEXT, Sandbox
from mandate.gateway.tools import TOOLS


@pytest.fixture
def box() -> Sandbox:
    return Sandbox.seeded()


# --- sandbox -----------------------------------------------------------------------


def test_seed_contents(box: Sandbox) -> None:
    assert len(box.messages) == 21
    assert box.messages["m-31"].body == INJECTION_TEXT
    assert set(box.orders) == {str(n) for n in range(80, 90)}
    assert "notes.txt" in box.files


def test_email_list_filters_by_folder_and_limit(box: Sandbox) -> None:
    assert len(actions.email_list(box, "inbox", 5)["messages"]) == 5  # type: ignore[arg-type]
    assert actions.email_list(box, "archive", 5)["messages"] == []


def test_archive_moves_and_read_returns_body(box: Sandbox) -> None:
    actions.email_archive(box, "m-3")
    assert actions.folder_of(box, "m-3") == "archive"
    assert actions.email_read(box, "m-3")["body"] == box.messages["m-3"].body
    assert actions.folder_of(box, "m-999") == "inbox"


def test_delete_removes_and_unknown_messages_are_errors(box: Sandbox) -> None:
    actions.email_delete(box, "m-1")
    assert "m-1" not in box.messages
    with pytest.raises(NotFound):
        actions.email_delete(box, "m-1")
    with pytest.raises(NotFound):
        actions.email_read(box, "m-999")


def test_send_records_the_message(box: Sandbox) -> None:
    actions.email_send(box, "a@b.com", "hi", "body")
    assert box.sent == [{"to": "a@b.com", "subject": "hi", "body": "body"}]


def test_refund_rules(box: Sandbox) -> None:
    assert actions.refund_issue(box, "80", 60)["status"] == "refunded"
    with pytest.raises(ValidationFailure):
        actions.refund_issue(box, "80", 60)  # exceeds the order amount (100)
    with pytest.raises(ValidationFailure):
        actions.refund_issue(box, "81", 0)
    with pytest.raises(NotFound):
        actions.refund_issue(box, "999", 1)
    assert box.orders["80"].refunded_amount == 60


def test_file_operations_and_traversal_is_rejected(box: Sandbox) -> None:
    actions.file_write(box, "/new/file.txt", "x")
    assert actions.file_read(box, "new/file.txt")["content"] == "x"
    actions.file_delete(box, "new/file.txt")
    with pytest.raises(NotFound):
        actions.file_read(box, "new/file.txt")
    for bad in ["../secret", "a/../../b", "", "   ", "."]:
        with pytest.raises(ValidationFailure):
            actions.normalise_file_path(bad)


# --- tools -------------------------------------------------------------------------


def test_every_tool_maps_to_a_registry_action() -> None:
    from mandate.models.registry import ACTION_TYPES

    assert {spec.action_type for spec in TOOLS.values()} <= set(ACTION_TYPES)
    assert set(TOOLS) == {
        "email_list",
        "email_read",
        "email_archive",
        "email_delete",
        "email_send",
        "refund_issue",
        "file_read",
        "file_write",
        "file_delete",
    }


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("email_read", {}),
        ("email_read", {"message_id": "a/b"}),
        ("email_read", {"message_id": "m-1", "extra": 1}),
        ("email_send", {"to": "no-at-sign", "subject": "s", "body": "b"}),
        ("email_send", {"to": "a/b@c.com", "subject": "s", "body": "b"}),
        ("refund_issue", {"order_id": "80", "amount": 0}),
        ("refund_issue", {"order_id": "80", "amount": "abc"}),
        ("refund_issue", {"order_id": "80", "amount": 10**9}),
        ("email_list", {"folder": "IN BOX"}),
        ("email_list", {"limit": 0}),
        ("file_write", {"path": "a", "content": "x" * 4001}),
    ],
)
def test_bad_arguments_are_rejected(tool: str, args: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        TOOLS[tool].model.model_validate(args)


def test_resources_are_derived_from_arguments(box: Sandbox) -> None:
    def resource(tool: str, **args: object) -> str:
        spec = TOOLS[tool]
        return spec.resource(spec.model.model_validate(args), box)

    assert resource("email_read", message_id="m-1") == "inbox/m-1"
    actions.email_archive(box, "m-1")
    assert resource("email_read", message_id="m-1") == "archive/m-1"
    assert resource("email_list") == "inbox/list"
    assert resource("email_send", to="a@b.com", subject="s", body="b") == "outbox/a@b.com"
    assert resource("refund_issue", order_id="80", amount=5) == "order/80"
    assert resource("file_read", path="/notes.txt") == "files/notes.txt"
    with pytest.raises(ValidationFailure):
        resource("file_read", path="../x")


def test_only_refunds_carry_an_authority_amount() -> None:
    refund = TOOLS["refund_issue"]
    args = refund.model.model_validate({"order_id": "80", "amount": 25})
    assert refund.check_args(args) == {"amount": 25}
    delete = TOOLS["email_delete"]
    assert delete.check_args(delete.model.model_validate({"message_id": "m-1"})) == {}
