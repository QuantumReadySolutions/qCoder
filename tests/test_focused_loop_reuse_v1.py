"""Currentness and reuse decided from exact identities, never from narrative."""

from __future__ import annotations

from typing import Any

import pytest

from qcoder.executors.aer_stabilizer_v1 import InvocationCounter
from qcoder.focused_loop.authority import AttemptLedger
from qcoder.focused_loop.canonical import FocusedLoopError
from qcoder.focused_loop.identities import RESULT_PROTOCOL_SCHEMA_ID
from qcoder.focused_loop.plan import PLAN_DIGEST_FIELD, build_execution_plan
from qcoder.focused_loop.reuse import (
    ACTION_REQUIRE_NEW_EXECUTION,
    ACTION_REUSE_EXISTING_RESULT,
    CURRENTNESS_STALE,
    CURRENTNESS_SUPERSEDED,
    CURRENTNESS_UNKNOWN,
    build_reuse_identity,
    decide_result_reuse,
    refuse_duplicate_execution_attempt,
    require_new_execution,
    reuse_identity_digest,
)

OBJECTIVE_DIGEST = "1" * 64
CIRCUIT_DIGEST = "2" * 64
PROFILE_DIGEST = "3" * 64
MANIFEST_DIGEST = "4" * 64
RECEIPT_DIGEST = "5" * 64
ATTEMPT_IDENTITY = "attempt-reuse-0001"
RUNTIME_VERSIONS = {"python": "3.14.3", "qiskit": "2.4.1", "qiskit_aer": "0.17.0"}


def make_plan(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "objective_digest": OBJECTIVE_DIGEST,
        "circuit_digest": CIRCUIT_DIGEST,
        "circuit_path": "circuits/nested_bell.qasm",
        "profile_digest": PROFILE_DIGEST,
        "seed": 3,
    }
    kwargs.update(overrides)
    return build_execution_plan(**kwargs)


def make_identity(plan: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "objective_digest": plan["objective_digest"],
        "circuit_digest": plan["circuit_digest"],
        "plan_digest": plan[PLAN_DIGEST_FIELD],
        "profile_digest": plan["profile_digest"],
        "runtime_versions": RUNTIME_VERSIONS,
    }
    kwargs.update(overrides)
    return build_reuse_identity(**kwargs)


def make_accepted(identity: dict[str, Any], *, currentness: str = "current") -> dict[str, Any]:
    return {
        "identity": identity,
        "currentness": currentness,
        "result_manifest_digest": MANIFEST_DIGEST,
        "receipt_digest": RECEIPT_DIGEST,
        "attempt_identity": ATTEMPT_IDENTITY,
    }


def test_an_equivalent_current_request_reuses_without_any_execution_attempt() -> None:
    counter = InvocationCounter()
    plan = make_plan()
    identity = make_identity(plan)
    decision = decide_result_reuse(
        request_identity=make_identity(plan), accepted_result=make_accepted(identity)
    )
    assert decision["action"] == ACTION_REUSE_EXISTING_RESULT
    assert decision["new_execution_attempts_required"] == 0
    assert decision["result_manifest_digest"] == MANIFEST_DIGEST
    assert decision["receipt_digest"] == RECEIPT_DIGEST
    assert decision["evidence_basis"] == "exact_identity_match"
    assert decision["identity_digest"] == reuse_identity_digest(identity)
    assert counter.count == 0


def test_the_identity_tuple_is_exactly_the_bound_digests() -> None:
    plan = make_plan()
    identity = make_identity(plan)
    assert set(identity) == {
        "objective_digest",
        "circuit_digest",
        "plan_digest",
        "result_protocol_id",
        "profile_digest",
        "runtime_versions",
    }
    assert identity["result_protocol_id"] == RESULT_PROTOCOL_SCHEMA_ID


@pytest.mark.parametrize(
    ("overrides", "category"),
    [
        ({"objective_digest": "9" * 64}, "reuse_objective_digest_mismatch"),
        ({"circuit_digest": "9" * 64}, "reuse_circuit_digest_mismatch"),
        ({"profile_digest": "9" * 64}, "reuse_profile_digest_mismatch"),
        (
            {"runtime_versions": {**RUNTIME_VERSIONS, "qiskit": "2.3.0"}},
            "reuse_runtime_version_mismatch",
        ),
    ],
)
def test_a_cross_revision_identity_rejects_rather_than_reuses(
    overrides: dict[str, Any], category: str
) -> None:
    counter = InvocationCounter()
    plan = make_plan()
    accepted = make_accepted(make_identity(plan))
    with pytest.raises(FocusedLoopError) as excinfo:
        decide_result_reuse(
            request_identity=make_identity(plan, **overrides), accepted_result=accepted
        )
    assert excinfo.value.category == category
    assert counter.count == 0


def test_a_different_plan_digest_rejects_rather_than_reuses() -> None:
    plan = make_plan()
    other_plan = make_plan(seed=4)
    accepted = make_accepted(make_identity(plan))
    with pytest.raises(FocusedLoopError) as excinfo:
        decide_result_reuse(
            request_identity=make_identity(other_plan, circuit_digest=CIRCUIT_DIGEST),
            accepted_result=accepted,
        )
    assert excinfo.value.category == "reuse_plan_digest_mismatch"


@pytest.mark.parametrize(
    "currentness", [CURRENTNESS_STALE, CURRENTNESS_SUPERSEDED, CURRENTNESS_UNKNOWN]
)
def test_a_non_current_accepted_result_is_never_reused(currentness: str) -> None:
    plan = make_plan()
    identity = make_identity(plan)
    with pytest.raises(FocusedLoopError) as excinfo:
        decide_result_reuse(
            request_identity=identity,
            accepted_result=make_accepted(identity, currentness=currentness),
        )
    assert excinfo.value.category == "reuse_accepted_result_not_current"


def test_an_unsupported_result_protocol_is_refused() -> None:
    plan = make_plan()
    with pytest.raises(FocusedLoopError) as excinfo:
        make_identity(plan, result_protocol_id="qcoder.result_protocol.other.v1")
    assert excinfo.value.category == "reuse_result_protocol_unsupported"


def test_reuse_never_accepts_narrative_or_filename_evidence() -> None:
    plan = make_plan()
    identity = make_identity(plan)
    narrative = dict(make_accepted(identity))
    narrative["chat_transcript_hint"] = "we ran this exact circuit last Tuesday"
    with pytest.raises(FocusedLoopError) as excinfo:
        decide_result_reuse(request_identity=identity, accepted_result=narrative)
    assert excinfo.value.category == "reuse_accepted_result_invalid"

    incomplete = dict(make_accepted(identity))
    del incomplete["attempt_identity"]
    with pytest.raises(FocusedLoopError) as missing_error:
        decide_result_reuse(request_identity=identity, accepted_result=incomplete)
    assert missing_error.value.category == "reuse_accepted_result_invalid"


def test_an_identity_with_unknown_fields_is_refused() -> None:
    plan = make_plan()
    identity = dict(make_identity(plan))
    identity["filename"] = "nested_bell.qasm"
    with pytest.raises(FocusedLoopError) as excinfo:
        decide_result_reuse(
            request_identity=identity, accepted_result=make_accepted(make_identity(plan))
        )
    assert excinfo.value.category == "reuse_identity_invalid"


def test_require_new_execution_is_the_explicit_non_reuse_decision() -> None:
    decision = require_new_execution(reason="no_accepted_current_result_for_this_identity")
    assert decision["action"] == ACTION_REQUIRE_NEW_EXECUTION
    assert decision["new_execution_attempts_required"] == 1
    assert decision["evidence_basis"] == "no_exact_identity_match"


def test_duplicate_prevention_refuses_a_second_execution_for_one_attempt() -> None:
    ledger = AttemptLedger.empty().consume(ATTEMPT_IDENTITY)
    assert refuse_duplicate_execution_attempt(
        attempt_identity="attempt-reuse-0002", consumed=ledger
    ) == "attempt-reuse-0002"
    with pytest.raises(FocusedLoopError) as excinfo:
        refuse_duplicate_execution_attempt(attempt_identity=ATTEMPT_IDENTITY, consumed=ledger)
    assert excinfo.value.category == "execution_attempt_identity_already_consumed"
    with pytest.raises(FocusedLoopError):
        refuse_duplicate_execution_attempt(
            attempt_identity=ATTEMPT_IDENTITY, consumed=[ATTEMPT_IDENTITY]
        )
    assert (
        refuse_duplicate_execution_attempt(attempt_identity=ATTEMPT_IDENTITY, consumed=None)
        == ATTEMPT_IDENTITY
    )
