"""Join proof between the sibling receipt and the REAL strict result manifest v3.

Nothing in this file edits, patches, or relaxes ``current_loop_result_manifest``. Every
manifest below is validated by the accepted v3 normalizer exactly as it ships.
"""

from __future__ import annotations

from typing import Any

import pytest

from qcoder.current_loop_result_manifest import (
    STRICT_RESULT_MANIFEST_SCHEMA_ID,
    STRICT_RESULT_MANIFEST_SCHEMA_VERSION,
)
from qcoder.focused_loop.authority import build_execution_authority
from qcoder.focused_loop.canonical import FocusedLoopError, canonical_digest
from qcoder.focused_loop.identities import FIXED_SHOTS
from qcoder.focused_loop.manifest_adapter import (
    MANIFEST_LIMITATION_VERIFICATION_SCOPE,
    MANIFEST_NON_CLAIM_INDEPENDENT_VERIFICATION,
    bind_receipt_to_result_manifest,
    build_strict_result_manifest_payload,
    circuit_artifact_revisions,
    join_receipt_to_strict_result_manifest,
    normalize_through_strict_manifest_v3,
)
from qcoder.focused_loop.plan import PLAN_DIGEST_FIELD, build_execution_plan
from qcoder.focused_loop.receipt import (
    RECEIPT_DIGEST_FIELD,
    STATUS_COMPLETED,
    STATUS_TIMEOUT,
    build_execution_receipt,
    censored_timing,
    observed_timing,
    unmeasured_resource_observation,
)

OBJECTIVE_DIGEST = "1" * 64
CIRCUIT_DIGEST = "2" * 64
PROFILE_DIGEST = "3" * 64
OTHER_CIRCUIT_DIGEST = "7" * 64
ATTEMPT_IDENTITY = "attempt-join-0001"
REVISION_ID = "rev-circuit-1"
OTHER_REVISION_ID = "rev-circuit-other"
PLANNED_VERSIONS = {"python": "3.14.3", "qiskit": "2.4.1", "qiskit_aer": "0.17.0"}
BACKEND = "aer_simulator_stabilizer"
INTERFACE = "qiskit_aer.AerSimulator.run"
CONFIGURATION_REFERENCE = "qcoder.focused_loop.local_aer_stabilizer_clifford_memory_binding_v1"

#: 598 shots across four distinct 12-bit outcome keys, well inside v3's 1024 outcome cap.
COUNTS = {
    "000000000000": 150,
    "000000000011": 150,
    "000000001100": 150,
    "000000001111": 148,
}
BIT_ORDER = [f"c[{index}]" for index in range(12)]
REGISTER_ORDER = ["c"]


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


def make_authority(plan: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "plan_digest": plan[PLAN_DIGEST_FIELD],
        "attempt_identity": ATTEMPT_IDENTITY,
        "expires_at": 2_000.0,
    }
    kwargs.update(overrides)
    return build_execution_authority(**kwargs)


def make_receipt(
    plan: dict[str, Any], authority: dict[str, Any], **overrides: Any
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "plan_digest": plan[PLAN_DIGEST_FIELD],
        "authority_digest": authority["authority_digest"],
        "attempt_identity": authority["attempt_identity"],
        "actual_method": plan["method_id"],
        "actual_settings": dict(plan["settings"]),
        "actual_profile_digest": plan["profile_digest"],
        "runtime_versions": PLANNED_VERSIONS,
        "timing": observed_timing(started_at=0.0, ended_at=0.25),
        "resource_observation": unmeasured_resource_observation(),
        "status": STATUS_COMPLETED,
        "deviation": {"detected": False, "fields": []},
        "plan_match_verified_in_process": True,
        "result_manifest_digest": canonical_digest({"provisional_counts": COUNTS}),
    }
    kwargs.update(overrides)
    return build_execution_receipt(**kwargs)


def make_payload(receipt: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "receipt": receipt,
        "counts": COUNTS,
        "circuit_artifact_revision_id": REVISION_ID,
        "circuit_digest": CIRCUIT_DIGEST,
        "backend_or_sampler": BACKEND,
        "interface": INTERFACE,
        "execution_configuration_reference": CONFIGURATION_REFERENCE,
        "bit_order": BIT_ORDER,
        "register_order": REGISTER_ORDER,
    }
    kwargs.update(overrides)
    return build_strict_result_manifest_payload(**kwargs)


def make_revisions(*, include_other: bool = False) -> dict[str, Any]:
    revisions = circuit_artifact_revisions(
        artifact_revision_id=REVISION_ID, circuit_digest=CIRCUIT_DIGEST
    )
    if include_other:
        revisions[OTHER_REVISION_ID] = {
            "logical_role": "circuit_qasm",
            "content_digest": OTHER_CIRCUIT_DIGEST,
        }
    return revisions


def bound_case() -> tuple[dict[str, Any], ...]:
    """Build the fully bound plan, authority, payload, manifest, and receipt."""
    plan = make_plan()
    authority = make_authority(plan)
    provisional = make_receipt(plan, authority)
    payload = make_payload(provisional)
    revisions = make_revisions()
    manifest = normalize_through_strict_manifest_v3(payload, artifact_revisions=revisions)
    receipt = bind_receipt_to_result_manifest(
        receipt=provisional, manifest_digest=manifest["manifest_digest"]
    )
    return plan, authority, provisional, payload, revisions, manifest, receipt


def test_the_real_v3_validator_accepts_the_projected_manifest() -> None:
    _plan, _authority, _provisional, _payload, _revisions, manifest, _receipt = bound_case()
    assert manifest["schema_id"] == STRICT_RESULT_MANIFEST_SCHEMA_ID
    assert manifest["schema_version"] == STRICT_RESULT_MANIFEST_SCHEMA_VERSION
    assert manifest["manifestation"] == "exact_result"
    assert manifest["observed_shots"] == FIXED_SHOTS
    assert manifest["requested_shots"] == FIXED_SHOTS
    assert sum(manifest["counts"].values()) == FIXED_SHOTS
    assert len(manifest["counts"]) == 4
    assert all(len(key) == 12 for key in manifest["counts"])
    assert manifest["execution_method"] == {
        "kind": "sampled_shots",
        "interface": INTERFACE,
        "backend_or_sampler": BACKEND,
    }
    assert manifest["circuit_lineage"]["status"] == "exact"
    assert manifest["bit_register_ordering"]["status"] == "known"
    assert len(manifest["manifest_digest"]) == 64


def test_the_join_binds_one_plan_one_authority_one_receipt_and_one_manifest() -> None:
    plan, authority, _provisional, payload, revisions, manifest, receipt = bound_case()
    join = join_receipt_to_strict_result_manifest(
        plan=plan,
        authority=authority,
        receipt=receipt,
        manifest_payload=payload,
        artifact_revisions=revisions,
        planned_runtime_versions=PLANNED_VERSIONS,
    )
    assert join["manifest_digest"] == manifest["manifest_digest"]
    assert join["outcome_digest"] == manifest["outcome_digest"]
    assert join["plan_digest"] == plan[PLAN_DIGEST_FIELD]
    assert join["authority_digest"] == authority["authority_digest"]
    assert join["attempt_identity"] == ATTEMPT_IDENTITY
    assert join["receipt_digest"] == receipt[RECEIPT_DIGEST_FIELD]
    assert join["deviation"] == {"detected": False, "fields": []}
    assert "result_manifest_digest" in join["joins_verified"]
    assert "method_settings_profile_versions" in join["joins_verified"]


def test_v3_client_reported_non_verification_is_not_a_contradiction() -> None:
    """v3 requires ``qcoder_independently_verified_execution=false``.

    That flag lives inside v3's *client-reported* execution observation block and says
    only that this manifest asserts no independent qCoder verification of the client's
    execution report. The sibling receipt's ``plan_match_verified_in_process=true`` is a
    different and stronger statement: the executor itself verified, in process, that the
    artifact it loaded and the settings it applied matched the frozen plan. Both are
    true at once, and v3 is used exactly as accepted rather than reinterpreted.
    """
    plan, authority, _provisional, payload, revisions, manifest, receipt = bound_case()
    assert manifest["execution_observation"] == {
        "status": "client_reported_completed",
        "external_execution_attempt_count": 1,
        "dependency_installation_performed": False,
        "environment_mutated": False,
        "qcoder_independently_verified_execution": False,
    }
    assert receipt["plan_match_verified_in_process"] is True
    assert MANIFEST_LIMITATION_VERIFICATION_SCOPE in manifest["limitations"]
    assert MANIFEST_NON_CLAIM_INDEPENDENT_VERIFICATION in manifest["non_claims"]

    join = join_receipt_to_strict_result_manifest(
        plan=plan,
        authority=authority,
        receipt=receipt,
        manifest_payload=payload,
        artifact_revisions=revisions,
        planned_runtime_versions=PLANNED_VERSIONS,
    )
    assert join["independent_verification_claimed"] is False
    assert join["plan_match_verified_in_process"] is True


def test_join_fails_when_the_manifest_attempt_identity_differs() -> None:
    plan, authority, _provisional, payload, revisions, _manifest, receipt = bound_case()
    forged = dict(payload)
    forged["execution_attempt_id"] = "attempt-somebody-elses"
    with pytest.raises(FocusedLoopError) as excinfo:
        join_receipt_to_strict_result_manifest(
            plan=plan,
            authority=authority,
            receipt=receipt,
            manifest_payload=forged,
            artifact_revisions=revisions,
            planned_runtime_versions=PLANNED_VERSIONS,
        )
    assert excinfo.value.category == "manifest_join_execution_attempt_id_mismatch"


def test_join_fails_when_the_receipt_is_not_bound_to_the_real_manifest_digest() -> None:
    plan, authority, provisional, payload, revisions, _manifest, _receipt = bound_case()
    with pytest.raises(FocusedLoopError) as excinfo:
        join_receipt_to_strict_result_manifest(
            plan=plan,
            authority=authority,
            receipt=provisional,
            manifest_payload=payload,
            artifact_revisions=revisions,
            planned_runtime_versions=PLANNED_VERSIONS,
        )
    assert excinfo.value.category == "manifest_join_result_manifest_digest_mismatch"


def test_join_fails_for_an_authority_granted_over_a_different_plan() -> None:
    plan, _authority, _provisional, payload, revisions, _manifest, receipt = bound_case()
    other_authority = make_authority(make_plan(seed=4))
    with pytest.raises(FocusedLoopError) as excinfo:
        join_receipt_to_strict_result_manifest(
            plan=plan,
            authority=other_authority,
            receipt=receipt,
            manifest_payload=payload,
            artifact_revisions=revisions,
            planned_runtime_versions=PLANNED_VERSIONS,
        )
    assert excinfo.value.category == "manifest_join_authority_plan_digest_mismatch"


def test_join_fails_when_the_manifest_circuit_lineage_points_elsewhere() -> None:
    plan, authority, provisional, _payload, _revisions, _manifest, _receipt = bound_case()
    revisions = make_revisions(include_other=True)
    payload = make_payload(
        provisional,
        circuit_artifact_revision_id=OTHER_REVISION_ID,
        circuit_digest=OTHER_CIRCUIT_DIGEST,
    )
    manifest = normalize_through_strict_manifest_v3(payload, artifact_revisions=revisions)
    receipt = bind_receipt_to_result_manifest(
        receipt=provisional, manifest_digest=manifest["manifest_digest"]
    )
    with pytest.raises(FocusedLoopError) as excinfo:
        join_receipt_to_strict_result_manifest(
            plan=plan,
            authority=authority,
            receipt=receipt,
            manifest_payload=payload,
            artifact_revisions=revisions,
            planned_runtime_versions=PLANNED_VERSIONS,
        )
    assert excinfo.value.category == "manifest_join_circuit_digest_mismatch"


def test_join_fails_when_the_receipt_deviates_from_the_plan() -> None:
    plan = make_plan()
    authority = make_authority(plan)
    provisional = make_receipt(
        plan, authority, runtime_versions={**PLANNED_VERSIONS, "qiskit": "2.3.0"}
    )
    payload = make_payload(provisional)
    revisions = make_revisions()
    manifest = normalize_through_strict_manifest_v3(payload, artifact_revisions=revisions)
    receipt = bind_receipt_to_result_manifest(
        receipt=provisional, manifest_digest=manifest["manifest_digest"]
    )
    with pytest.raises(FocusedLoopError) as excinfo:
        join_receipt_to_strict_result_manifest(
            plan=plan,
            authority=authority,
            receipt=receipt,
            manifest_payload=payload,
            artifact_revisions=revisions,
            planned_runtime_versions=PLANNED_VERSIONS,
        )
    assert excinfo.value.category == "manifest_join_plan_deviation_detected"


def test_join_refuses_a_non_enrollable_receipt() -> None:
    plan = make_plan()
    authority = make_authority(plan)
    timed_out = make_receipt(
        plan,
        authority,
        status=STATUS_TIMEOUT,
        timing=censored_timing(started_at=0.0, censor_reason="executor_wall_time_exceeded"),
        result_manifest_digest=None,
        deviation={"detected": True, "fields": ["settings.shots"]},
        actual_settings={"shots": 0, "noise": "none", "seed": None},
    )
    with pytest.raises(FocusedLoopError) as join_error:
        join_receipt_to_strict_result_manifest(
            plan=plan,
            authority=authority,
            receipt=timed_out,
            manifest_payload=make_payload(make_receipt(plan, authority)),
            artifact_revisions=make_revisions(),
            planned_runtime_versions=PLANNED_VERSIONS,
        )
    assert join_error.value.category == "manifest_join_receipt_not_enrollable"

    with pytest.raises(FocusedLoopError) as payload_error:
        make_payload(timed_out)
    assert payload_error.value.category == "manifest_join_receipt_not_enrollable"


def test_v3_rejection_is_surfaced_as_a_bounded_category_not_worked_around() -> None:
    _plan, _authority, _provisional, payload, revisions, _manifest, _receipt = bound_case()
    contradictory = dict(payload)
    contradictory["observed_shots"] = 599
    contradictory["requested_shots"] = 599
    with pytest.raises(FocusedLoopError) as excinfo:
        normalize_through_strict_manifest_v3(contradictory, artifact_revisions=revisions)
    assert excinfo.value.category == "manifest_join_strict_manifest_rejected"
    assert excinfo.value.strict_manifest_category == (
        "result_manifest_observed_shots_contradiction"
    )


def test_v3_refuses_an_independent_verification_claim_and_we_do_not_override_it() -> None:
    _plan, _authority, _provisional, payload, revisions, _manifest, _receipt = bound_case()
    overreaching = dict(payload)
    overreaching["execution_observation"] = {
        **payload["execution_observation"],
        "qcoder_independently_verified_execution": True,
    }
    with pytest.raises(FocusedLoopError) as excinfo:
        normalize_through_strict_manifest_v3(overreaching, artifact_revisions=revisions)
    assert excinfo.value.category == "manifest_join_strict_manifest_rejected"
    assert excinfo.value.strict_manifest_category == (
        "result_manifest_qcoder_execution_verification_claim_invalid"
    )


def test_v3_refuses_a_false_circuit_lineage_binding() -> None:
    _plan, _authority, provisional, _payload, _revisions, _manifest, _receipt = bound_case()
    payload = make_payload(provisional, circuit_digest="8" * 64)
    with pytest.raises(FocusedLoopError) as excinfo:
        normalize_through_strict_manifest_v3(payload, artifact_revisions=make_revisions())
    assert excinfo.value.category == "manifest_join_strict_manifest_rejected"
    assert excinfo.value.strict_manifest_category == "result_manifest_false_circuit_lineage"


def test_the_bounded_outcome_shape_stays_inside_the_v3_outcome_cap() -> None:
    _plan, _authority, provisional, _payload, revisions, _manifest, _receipt = bound_case()
    wide_counts = {format(index, "012b"): 1 for index in range(63)}
    wide_counts["111111111111"] = FIXED_SHOTS - 63
    payload = make_payload(provisional, counts=wide_counts)
    manifest = normalize_through_strict_manifest_v3(payload, artifact_revisions=revisions)
    assert len(manifest["counts"]) == 64
    assert manifest["observed_shots"] == FIXED_SHOTS
