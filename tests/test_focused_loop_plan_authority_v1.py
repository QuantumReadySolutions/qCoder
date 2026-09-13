"""Inert plan commitment and the separate, single-use execution authority."""

from __future__ import annotations

from typing import Any

import pytest

from qcoder.executors.aer_stabilizer_v1 import InvocationCounter
from qcoder.focused_loop.authority import (
    AttemptLedger,
    build_execution_authority,
    consume_attempt_identity,
    validate_execution_authority,
)
from qcoder.focused_loop.canonical import FocusedLoopError, digest_excluding
from qcoder.focused_loop.identities import (
    EXECUTION_AUTHORITY_SCHEMA_ID,
    EXECUTION_PLAN_SCHEMA_ID,
    EXECUTION_RECEIPT_SCHEMA_ID,
    FIXED_SHOTS,
    METHOD_MPS_EXACT,
    METHOD_STABILIZER,
    REGIME_ID,
    RESULT_PROTOCOL_SCHEMA_ID,
)
from qcoder.focused_loop.plan import (
    PLAN_DIGEST_FIELD,
    PLAN_STATE_INERT,
    build_execution_plan,
    plan_digest_of,
    validate_execution_plan,
)

OBJECTIVE_DIGEST = "1" * 64
CIRCUIT_DIGEST = "2" * 64
PROFILE_DIGEST = "3" * 64
NOW = 1_000.0
EXPIRES_AT = 2_000.0


def make_plan(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "objective_digest": OBJECTIVE_DIGEST,
        "circuit_digest": CIRCUIT_DIGEST,
        "circuit_path": "circuits/nested_bell.qasm",
        "profile_digest": PROFILE_DIGEST,
        "seed": 7,
    }
    kwargs.update(overrides)
    return build_execution_plan(**kwargs)


def tamper(plan: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """Force a field and recompute the self-digest, so only the field under test fails."""
    mutated = {
        key: dict(value) if isinstance(value, dict) else value for key, value in plan.items()
    }
    for key, value in overrides.items():
        if "." in key:
            outer, inner = key.split(".", 1)
            mutated[outer][inner] = value
        else:
            mutated[key] = value
    mutated[PLAN_DIGEST_FIELD] = digest_excluding(mutated, field=PLAN_DIGEST_FIELD)
    return mutated


def test_inert_plan_commit_produces_digest_and_never_executes() -> None:
    counter = InvocationCounter()
    plan = make_plan()
    assert plan["schema_id"] == EXECUTION_PLAN_SCHEMA_ID
    assert plan["regime_id"] == REGIME_ID
    assert plan["plan_state"] == PLAN_STATE_INERT
    assert plan["method_id"] == METHOD_STABILIZER
    assert plan["settings"] == {"shots": FIXED_SHOTS, "noise": "none", "seed": 7}
    assert plan["result_protocol_id"] == RESULT_PROTOCOL_SCHEMA_ID
    assert plan["expected_receipt_schema_id"] == EXECUTION_RECEIPT_SCHEMA_ID
    assert len(plan[PLAN_DIGEST_FIELD]) == 64
    assert counter.count == 0
    assert counter.requests == []


def test_plan_build_is_deterministic_and_roundtrips_through_validation() -> None:
    first = make_plan()
    second = make_plan()
    assert first == second
    assert validate_execution_plan(first) == first
    assert plan_digest_of(first) == first[PLAN_DIGEST_FIELD]


def test_plan_digest_changes_with_every_bound_identity() -> None:
    baseline = make_plan()[PLAN_DIGEST_FIELD]
    assert make_plan(objective_digest="4" * 64)[PLAN_DIGEST_FIELD] != baseline
    assert make_plan(circuit_digest="5" * 64)[PLAN_DIGEST_FIELD] != baseline
    assert make_plan(profile_digest="6" * 64)[PLAN_DIGEST_FIELD] != baseline
    assert make_plan(seed=None)[PLAN_DIGEST_FIELD] != baseline


@pytest.mark.parametrize(
    ("overrides", "category"),
    [
        ({"method_id": METHOD_MPS_EXACT}, "execution_plan_method_unsupported"),
        ({"method_id": "statevector"}, "execution_plan_method_unsupported"),
        ({"shots": 597}, "execution_plan_shots_unsupported"),
        ({"shots": 1024}, "execution_plan_shots_unsupported"),
        ({"shots": 0}, "execution_plan_shots_unsupported"),
        ({"noise": "depolarizing"}, "execution_plan_noise_unsupported"),
        ({"objective_digest": "not-a-digest"}, "execution_plan_objective_digest_invalid"),
        ({"circuit_digest": None}, "execution_plan_circuit_digest_invalid"),
        ({"profile_digest": "7" * 63}, "execution_plan_profile_digest_invalid"),
        ({"circuit_transport": "inline_qasm"}, "execution_plan_circuit_transport_unsupported"),
        ({"circuit_path": ""}, "execution_plan_circuit_path_invalid"),
        ({"result_protocol_id": "other.v1"}, "execution_plan_result_protocol_unsupported"),
        ({"expected_receipt_schema_id": "other.v1"}, "execution_plan_receipt_schema_unsupported"),
        ({"regime_id": "remote_qpu_v1"}, "execution_plan_regime_unsupported"),
        ({"max_wall_seconds": 0.0}, "execution_plan_limits_invalid"),
        ({"max_memory_bytes": 0}, "execution_plan_limits_invalid"),
        ({"seed": -1}, "execution_plan_seed_invalid"),
    ],
)
def test_plan_build_rejects_out_of_regime_values(
    overrides: dict[str, Any], category: str
) -> None:
    counter = InvocationCounter()
    with pytest.raises(FocusedLoopError) as excinfo:
        make_plan(**overrides)
    assert excinfo.value.category == category
    assert counter.count == 0


def test_plan_validation_rejects_unknown_and_missing_fields() -> None:
    plan = make_plan()
    with_extra = dict(plan)
    with_extra["escalation_hint"] = "please run it anyway"
    with pytest.raises(FocusedLoopError) as extra_error:
        validate_execution_plan(with_extra)
    assert extra_error.value.category == "execution_plan_schema_invalid"

    without_digest = {key: value for key, value in plan.items() if key != "profile_digest"}
    with pytest.raises(FocusedLoopError) as missing_error:
        validate_execution_plan(without_digest)
    assert missing_error.value.category == "execution_plan_schema_invalid"


def test_plan_validation_rejects_non_inert_state_and_tampered_digest() -> None:
    plan = make_plan()
    with pytest.raises(FocusedLoopError) as state_error:
        validate_execution_plan(tamper(plan, plan_state="authorized"))
    assert state_error.value.category == "execution_plan_state_not_inert"

    forged = dict(plan)
    forged[PLAN_DIGEST_FIELD] = "0" * 64
    with pytest.raises(FocusedLoopError) as digest_error:
        validate_execution_plan(forged)
    assert digest_error.value.category == "execution_plan_digest_mismatch"


def test_tampered_shots_are_rejected_even_with_a_recomputed_digest() -> None:
    plan = make_plan()
    with pytest.raises(FocusedLoopError) as excinfo:
        validate_execution_plan(tamper(plan, **{"settings.shots": 1024}))
    assert excinfo.value.category == "execution_plan_shots_unsupported"


def make_authority(plan: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "plan_digest": plan[PLAN_DIGEST_FIELD],
        "attempt_identity": "attempt-0001",
        "expires_at": EXPIRES_AT,
    }
    kwargs.update(overrides)
    return build_execution_authority(**kwargs)


def test_authority_is_a_separate_object_bound_to_one_plan_digest() -> None:
    plan = make_plan()
    authority = make_authority(plan)
    assert authority["schema_id"] == EXECUTION_AUTHORITY_SCHEMA_ID
    assert authority["schema_id"] != plan["schema_id"]
    assert authority["plan_digest"] == plan[PLAN_DIGEST_FIELD]
    assert authority["displayed_plan_digest"] == plan[PLAN_DIGEST_FIELD]
    assert authority["granted_by"] == "native_client_customer_action"
    assert authority["single_use"] is True
    validated = validate_execution_authority(
        authority, plan_digest=plan[PLAN_DIGEST_FIELD], now=NOW
    )
    assert validated == authority


def test_authority_rejects_a_digest_for_a_different_plan() -> None:
    plan = make_plan()
    other = make_plan(circuit_digest="9" * 64)
    authority = make_authority(other)
    with pytest.raises(FocusedLoopError) as excinfo:
        validate_execution_authority(authority, plan_digest=plan[PLAN_DIGEST_FIELD], now=NOW)
    assert excinfo.value.category == "execution_authority_plan_digest_mismatch"


def test_authority_rejects_a_stale_displayed_plan() -> None:
    plan = make_plan()
    stale = make_plan(seed=8)
    authority = build_execution_authority(
        plan_digest=plan[PLAN_DIGEST_FIELD],
        displayed_plan_digest=stale[PLAN_DIGEST_FIELD],
        attempt_identity="attempt-0002",
        expires_at=EXPIRES_AT,
    )
    with pytest.raises(FocusedLoopError) as excinfo:
        validate_execution_authority(authority, plan_digest=plan[PLAN_DIGEST_FIELD], now=NOW)
    assert excinfo.value.category == "execution_authority_displayed_plan_stale"


def test_authority_rejects_expiry_single_use_false_and_wrong_grantor() -> None:
    plan = make_plan()
    expired = make_authority(plan, expires_at=NOW - 1.0)
    with pytest.raises(FocusedLoopError) as expiry_error:
        validate_execution_authority(expired, plan_digest=plan[PLAN_DIGEST_FIELD], now=NOW)
    assert expiry_error.value.category == "execution_authority_expired"

    with pytest.raises(FocusedLoopError) as single_use_error:
        make_authority(plan, single_use=False)
    assert single_use_error.value.category == "execution_authority_not_single_use"

    with pytest.raises(FocusedLoopError) as grantor_error:
        make_authority(plan, granted_by="qcoder_inferred_intent")
    assert grantor_error.value.category == "execution_authority_granted_by_unsupported"


def test_authority_rejects_a_forged_self_digest() -> None:
    plan = make_plan()
    authority = dict(make_authority(plan))
    authority["attempt_identity"] = "attempt-swapped"
    with pytest.raises(FocusedLoopError) as excinfo:
        validate_execution_authority(authority, plan_digest=plan[PLAN_DIGEST_FIELD], now=NOW)
    assert excinfo.value.category == "execution_authority_digest_mismatch"


def test_attempt_ledger_permits_at_most_one_attempt_per_identity() -> None:
    ledger = AttemptLedger.empty()
    assert ledger.is_consumed("attempt-0001") is False
    spent = ledger.consume("attempt-0001")
    assert spent.is_consumed("attempt-0001") is True
    assert ledger.is_consumed("attempt-0001") is False
    with pytest.raises(FocusedLoopError) as excinfo:
        spent.consume("attempt-0001")
    assert excinfo.value.category == "execution_attempt_identity_already_consumed"
    assert spent.consume("attempt-0002").consumed == {"attempt-0001", "attempt-0002"}


def test_attempt_ledger_has_no_shared_module_state() -> None:
    first = AttemptLedger.empty().consume("attempt-a")
    second = AttemptLedger.empty()
    assert second.consumed == frozenset()
    assert first.consumed == frozenset({"attempt-a"})
    assert consume_attempt_identity(None, "attempt-a") == frozenset({"attempt-a"})
    with pytest.raises(FocusedLoopError):
        consume_attempt_identity(["attempt-a"], "attempt-a")


def test_ledger_rejects_unbounded_or_malformed_identities() -> None:
    with pytest.raises(FocusedLoopError) as excinfo:
        AttemptLedger.of("attempt-not-a-collection")
    assert excinfo.value.category == "execution_attempt_ledger_invalid"
    with pytest.raises(FocusedLoopError) as blank_error:
        AttemptLedger.empty().consume("")
    assert blank_error.value.category == "execution_authority_attempt_identity_invalid"
