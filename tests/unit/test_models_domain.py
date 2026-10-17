import pytest
from pydantic import ValidationError

from mandate.ids import new_id
from mandate.models.domain import (
    REASONS_FOR_RESULT,
    Action,
    Agent,
    CheckRequest,
    Constraints,
    Decision,
    Delegation,
    Effect,
    Instruction,
    LineageTrust,
    PathHop,
    Principal,
    Reason,
    Result,
    Scope,
    Utterance,
)

T = 1_760_500_000_000


def ins(**overrides: object) -> Instruction:
    data: dict[str, object] = {
        "id": new_id("ins"),
        "effect": "allow",
        "text_span": "read my email",
        "created_at": T,
        "lineage_trust": "trusted",
    }
    data.update(overrides)
    return Instruction.model_validate(data)


def test_effect_enum_rejected() -> None:
    with pytest.raises(ValidationError):
        ins(effect="maybe")


def test_id_prefix_checked() -> None:
    with pytest.raises(ValidationError):
        Principal(id=new_id("agt"), name="Dana", role="owner")  # type: ignore[arg-type]
    assert Principal(id=new_id("prn"), name="Dana", role="owner")  # type: ignore[arg-type]


def test_models_are_frozen_and_forbid_extra_fields() -> None:
    principal = Principal(id=new_id("prn"), name="Dana", role="owner")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        principal.name = "Other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        Principal.model_validate(
            {"id": new_id("prn"), "name": "Dana", "role": "owner", "admin": True}
        )


def test_constraints_unknown_key_rejected() -> None:
    with pytest.raises(ValidationError):
        Constraints.model_validate({"max_amount": 5, "currency": "usd"})


def test_constraints_json_roundtrip() -> None:
    constraints = Constraints(max_amount=500)
    assert Constraints.from_json(constraints.to_json()) == constraints
    assert Constraints.from_json("") == Constraints()
    assert Constraints().to_json() == "{}"


def test_constraints_negative_amount_rejected() -> None:
    with pytest.raises(ValidationError):
        Constraints(max_amount=-1)


def test_valid_to_after_valid_from() -> None:
    with pytest.raises(ValidationError):
        ins(valid_from=T + 10, valid_to=T + 10)
    assert ins(valid_from=T + 10, valid_to=T + 11)


def test_active_instruction_needs_activated_at() -> None:
    with pytest.raises(ValidationError):
        ins(status="active")
    assert ins(status="active", activated_at=T + 1, valid_from=T + 1)


def test_revoked_instruction_needs_revoked_at() -> None:
    with pytest.raises(ValidationError):
        ins(status="revoked", activated_at=T + 1)


def test_activation_cannot_precede_creation() -> None:
    with pytest.raises(ValidationError):
        ins(status="active", activated_at=T - 1)


def test_untrusted_lineage_cannot_be_activated() -> None:
    # The shape check accepts it so tampered data can be read and then ignored (AUTH-004);
    # activation of untrusted lineage is refused when writing (AUTH-006, store tests).
    tampered = ins(lineage_trust=LineageTrust.UNTRUSTED, status="active", activated_at=T + 1)
    assert tampered.lineage_trust is LineageTrust.UNTRUSTED
    assert ins(lineage_trust=LineageTrust.UNTRUSTED)  # pending is fine


def test_negative_timestamp_rejected() -> None:
    with pytest.raises(ValidationError):
        ins(created_at=-1)


def test_trusted_utterance_requires_owner_direct_channel() -> None:
    base = {"id": new_id("utt"), "text": "hi", "at": T}
    with pytest.raises(ValidationError):
        Utterance.model_validate({**base, "channel": "untrusted_content", "trust": "trusted"})
    assert Utterance.model_validate({**base, "channel": "owner_direct", "trust": "trusted"})
    assert Utterance.model_validate({**base, "channel": "owner_direct", "trust": "untrusted"})


def test_scope_validates_action_type_and_pattern() -> None:
    sid = new_id("scp")
    assert Scope(id=sid, action_type="email.*")
    assert Scope(id=sid, action_type="*", resource_pattern="inbox/*")
    with pytest.raises(ValidationError):
        Scope(id=sid, action_type="email.fly")
    with pytest.raises(ValidationError):
        Scope(id=sid, action_type="email.read", resource_pattern="../secret")
    with pytest.raises(ValidationError):
        Scope(id=sid, action_type="email.read", resource_pattern="  ")


def test_action_requires_registry_type_and_safe_resource() -> None:
    aid = new_id("act")
    assert Action(id=aid, action_type="email.delete", resource="inbox/m-1", at=T)
    with pytest.raises(ValidationError):
        Action(id=aid, action_type="email.*", resource="inbox/m-1", at=T)
    with pytest.raises(ValidationError):
        Action(id=aid, action_type="email.delete", resource="inbox/../x", at=T)


def test_delegation_rules() -> None:
    a, b = new_id("agt"), new_id("agt")
    base = {
        "id": new_id("dlg"),
        "from_agent": a,
        "to_agent": b,
        "action_type": "email.read",
        "created_at": T,
        "valid_from": T,
    }
    assert Delegation.model_validate(base)
    with pytest.raises(ValidationError):
        Delegation.model_validate({**base, "to_agent": a})
    with pytest.raises(ValidationError):
        Delegation.model_validate({**base, "valid_to": T})
    with pytest.raises(ValidationError):
        Delegation.model_validate({**base, "action_type": "nope"})


def test_check_request_validates_action_and_resource() -> None:
    agent = new_id("agt")
    assert CheckRequest(agent_id=agent, action_type="email.read", resource="inbox/m-1")
    with pytest.raises(ValidationError):
        CheckRequest(agent_id=agent, action_type="email.read", resource="")
    with pytest.raises(ValidationError):
        CheckRequest(agent_id=agent, action_type="bogus", resource="x")


def test_agent_kind_enum() -> None:
    assert Agent(id=new_id("agt"), name="main", kind="primary")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Agent(id=new_id("agt"), name="main", kind="boss")  # type: ignore[arg-type]


def decision(result: Result, reason: Reason) -> Decision:
    return Decision(
        id=new_id("dec"),
        result=result,
        reason=reason,
        as_of=T,
        at=T,
        path=[PathHop(type="Agent", id="agt_x")],
    )


@pytest.mark.parametrize(
    ("result", "reason"),
    [(res, rsn) for res, reasons in REASONS_FOR_RESULT.items() for rsn in reasons],
)
def test_valid_result_reason_pairs(result: Result, reason: Reason) -> None:
    assert decision(result, reason)


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        (Result.ALLOW, Reason.EXPLICIT_DENY),
        (Result.DENY, Reason.AUTHORIZED),
        (Result.CONFIRM, Reason.NO_AUTHORITY_PATH),
        (Result.ALLOW, Reason.CHECK_ERROR),
    ],
)
def test_invalid_result_reason_pairs(result: Result, reason: Reason) -> None:
    with pytest.raises(ValidationError):
        decision(result, reason)


def test_every_reason_is_used_by_exactly_one_result() -> None:
    seen = [reason for reasons in REASONS_FOR_RESULT.values() for reason in reasons]
    assert sorted(seen) == sorted(Reason)


def test_decision_requires_a_path() -> None:
    with pytest.raises(ValidationError):
        Decision(
            id=new_id("dec"),
            result=Result.DENY,
            reason=Reason.NO_AUTHORITY_PATH,
            as_of=T,
            at=T,
            path=[],
        )


def test_decision_json_helpers() -> None:
    d = decision(Result.DENY, Reason.NO_AUTHORITY_PATH)
    assert d.path_json() == '[{"type":"Agent","id":"agt_x","note":""}]'
    assert d.ignored_json() == "[]"


def test_effect_values_match_spec() -> None:
    assert {e.value for e in Effect} == {"allow", "deny", "confirm"}
