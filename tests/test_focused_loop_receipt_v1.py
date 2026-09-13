"""Sibling execution receipt: exact deviation detection and enrolment refusal."""

from __future__ import annotations

from typing import Any

import pytest

from qcoder.focused_loop.canonical import FocusedLoopError
from qcoder.focused_loop.identities import EXECUTION_RECEIPT_SCHEMA_ID, FIXED_SHOTS
from qcoder.focused_loop.plan import PLAN_DIGEST_FIELD, build_execution_plan
from qcoder.focused_loop.receipt import (
    RECEIPT_DIGEST_FIELD,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_TIMEOUT,
    STATUS_UNSUPPORTED,
    build_execution_receipt,
    censored_timing,
    detect_plan_deviation,
    observed_timing,
    receipt_is_enrollable_as_current_evidence,
    require_enrollable_receipt,
    unmeasured_resource_observation,
    validate_execution_receipt,
)

OBJECTIVE_DIGEST = "1" * 64
CIRCUIT_DIGEST = "2" * 64
PROFILE_DIGEST = "3" * 64
AUTHORITY_DIGEST = "4" * 64
MANIFEST_DIGEST = "5" * 64
ATTEMPT_IDENTITY = "attempt-receipt-0001"
RUNTIME_VERSIONS = {"python": "3.14.3", "qiskit": "2.4.1", "qiskit_aer": "0.17.0"}


def make_plan(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "objective_digest": OBJECTIVE_DIGEST,
        "circuit_digest": CIRCUIT_DIGEST,
        "circuit_path": "circuits/nested_bell.qasm",
        "profile_digest": PROFILE_DIGEST,
        "seed": 11,
    }
    kwargs.update(overrides)
    return build_execution_plan(**kwargs)


def make_receipt(plan: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "plan_digest": plan[PLAN_DIGEST_FIELD],
        "authority_digest": AUTHORITY_DIGEST,
        "attempt_identity": ATTEMPT_IDENTITY,
        "actual_method": plan["method_id"],
        "actual_settings": dict(plan["settings"]),
        "actual_profile_digest": plan["profile_digest"],
        "runtime_versions": RUNTIME_VERSIONS,
        "timing": observed_timing(started_at=10.0, ended_at=10.5),
        "resource_observation": {"peak_memory_bytes": 4_096, "below_resolution": False},
        "status": STATUS_COMPLETED,
        "deviation": {"detected": False, "fields": []},
        "plan_match_verified_in_process": True,
        "result_manifest_digest": MANIFEST_DIGEST,
    }
    kwargs.update(overrides)
    return build_execution_receipt(**kwargs)


def test_conforming_receipt_is_self_digesting_and_enrollable() -> None:
    plan = make_plan()
    receipt = make_receipt(plan)
    assert receipt["schema_id"] == EXECUTION_RECEIPT_SCHEMA_ID
    assert receipt["actual_settings"]["shots"] == FIXED_SHOTS
    assert receipt["timing"]["elapsed_seconds"] == pytest.approx(0.5)
    assert receipt["timing"]["censored"] is False
    assert len(receipt[RECEIPT_DIGEST_FIELD]) == 64
    assert receipt_is_enrollable_as_current_evidence(receipt) is True
    assert require_enrollable_receipt(receipt) == dict(receipt)
    assert validate_execution_receipt(
        receipt,
        plan=plan,
        expected_attempt_identity=ATTEMPT_IDENTITY,
        expected_authority_digest=AUTHORITY_DIGEST,
        expected_runtime_versions=RUNTIME_VERSIONS,
        expected_result_manifest_digest=MANIFEST_DIGEST,
    ) == receipt


def test_deviation_detection_names_the_exact_differing_fields() -> None:
    plan = make_plan()
    deviation = detect_plan_deviation(
        plan=plan,
        actual_method="mps_exact",
        actual_settings={"shots": 1_024, "noise": "depolarizing", "seed": 12},
        actual_profile_digest="9" * 64,
        runtime_versions={**RUNTIME_VERSIONS, "qiskit": "2.3.0"},
        planned_runtime_versions=RUNTIME_VERSIONS,
    )
    assert deviation["detected"] is True
    assert deviation["fields"] == [
        "method_id",
        "profile_digest",
        "runtime_versions.qiskit",
        "settings.noise",
        "settings.seed",
        "settings.shots",
    ]


def test_deviation_detection_is_empty_for_an_exact_match() -> None:
    plan = make_plan()
    deviation = detect_plan_deviation(
        plan=plan,
        actual_method=plan["method_id"],
        actual_settings=dict(plan["settings"]),
        actual_profile_digest=plan["profile_digest"],
        runtime_versions=RUNTIME_VERSIONS,
        planned_runtime_versions=RUNTIME_VERSIONS,
    )
    assert deviation == {"detected": False, "fields": []}


def test_deviation_detection_reports_missing_and_extra_runtime_components() -> None:
    plan = make_plan()
    deviation = detect_plan_deviation(
        plan=plan,
        actual_method=plan["method_id"],
        actual_settings=dict(plan["settings"]),
        actual_profile_digest=plan["profile_digest"],
        runtime_versions={"python": "3.14.3", "qiskit": "2.4.1", "numpy": "2.4.2"},
        planned_runtime_versions=RUNTIME_VERSIONS,
    )
    assert deviation["fields"] == ["runtime_versions.numpy", "runtime_versions.qiskit_aer"]


def test_a_deviating_receipt_is_never_enrollable_as_current_evidence() -> None:
    plan = make_plan()
    receipt = make_receipt(
        plan,
        runtime_versions={**RUNTIME_VERSIONS, "qiskit": "2.3.0"},
        deviation={"detected": True, "fields": ["runtime_versions.qiskit"]},
    )
    assert receipt["deviation"]["fields"] == ["runtime_versions.qiskit"]
    assert receipt_is_enrollable_as_current_evidence(receipt) is False
    with pytest.raises(FocusedLoopError) as excinfo:
        require_enrollable_receipt(receipt)
    assert excinfo.value.category == "execution_receipt_not_enrollable"


def test_receipt_validator_rejects_a_wrong_plan_digest() -> None:
    plan = make_plan()
    other_plan = make_plan(circuit_digest="8" * 64)
    receipt = make_receipt(other_plan)
    with pytest.raises(FocusedLoopError) as excinfo:
        validate_execution_receipt(receipt, plan=plan)
    assert excinfo.value.category == "execution_receipt_plan_digest_mismatch"


@pytest.mark.parametrize(
    ("overrides", "category"),
    [
        ({"actual_method": "mps_exact"}, "execution_receipt_method_mismatch"),
        (
            {"actual_settings": {"shots": 597, "noise": "none", "seed": 11}},
            "execution_receipt_shots_mismatch",
        ),
        (
            {"actual_settings": {"shots": 1_024, "noise": "none", "seed": 11}},
            "execution_receipt_shots_mismatch",
        ),
        (
            {"actual_settings": {"shots": FIXED_SHOTS, "noise": "thermal", "seed": 11}},
            "execution_receipt_noise_mismatch",
        ),
        (
            {"actual_settings": {"shots": FIXED_SHOTS, "noise": "none", "seed": 99}},
            "execution_receipt_seed_mismatch",
        ),
        ({"actual_profile_digest": "a" * 64}, "execution_receipt_profile_mismatch"),
    ],
)
def test_receipt_validator_rejects_each_conformance_break(
    overrides: dict[str, Any], category: str
) -> None:
    plan = make_plan()
    receipt = make_receipt(plan, **overrides)
    with pytest.raises(FocusedLoopError) as excinfo:
        validate_execution_receipt(receipt, plan=plan)
    assert excinfo.value.category == category


def test_receipt_validator_rejects_a_wrong_runtime_version() -> None:
    plan = make_plan()
    receipt = make_receipt(plan, runtime_versions={**RUNTIME_VERSIONS, "qiskit": "2.3.0"})
    with pytest.raises(FocusedLoopError) as excinfo:
        validate_execution_receipt(receipt, plan=plan, expected_runtime_versions=RUNTIME_VERSIONS)
    assert excinfo.value.category == "execution_receipt_runtime_version_mismatch"


def test_receipt_validator_rejects_a_wrong_result_manifest_digest() -> None:
    plan = make_plan()
    receipt = make_receipt(plan)
    with pytest.raises(FocusedLoopError) as excinfo:
        validate_execution_receipt(
            receipt, plan=plan, expected_result_manifest_digest="b" * 64
        )
    assert excinfo.value.category == "execution_receipt_result_manifest_digest_mismatch"


def test_receipt_validator_rejects_a_wrong_attempt_identity_or_authority() -> None:
    plan = make_plan()
    receipt = make_receipt(plan)
    with pytest.raises(FocusedLoopError) as attempt_error:
        validate_execution_receipt(receipt, plan=plan, expected_attempt_identity="attempt-other")
    assert attempt_error.value.category == "execution_receipt_attempt_identity_mismatch"
    with pytest.raises(FocusedLoopError) as authority_error:
        validate_execution_receipt(receipt, plan=plan, expected_authority_digest="c" * 64)
    assert authority_error.value.category == "execution_receipt_authority_digest_mismatch"


def test_receipt_validator_rejects_a_forged_self_digest_and_unknown_fields() -> None:
    plan = make_plan()
    receipt = dict(make_receipt(plan))
    receipt["attempt_identity"] = "attempt-swapped"
    with pytest.raises(FocusedLoopError) as digest_error:
        validate_execution_receipt(receipt, plan=plan)
    assert digest_error.value.category == "execution_receipt_digest_mismatch"

    with_extra = dict(make_receipt(plan))
    with_extra["operator_note"] = "trust me"
    with pytest.raises(FocusedLoopError) as field_error:
        validate_execution_receipt(with_extra, plan=plan)
    assert field_error.value.category == "execution_receipt_schema_invalid"


@pytest.mark.parametrize("status", [STATUS_TIMEOUT, STATUS_CANCELLED])
def test_censored_timing_is_required_for_timeout_and_cancel(status: str) -> None:
    plan = make_plan()
    receipt = make_receipt(
        plan,
        status=status,
        timing=censored_timing(started_at=10.0, censor_reason="executor_wall_time_exceeded"),
        resource_observation=unmeasured_resource_observation(),
        result_manifest_digest=None,
        deviation={"detected": True, "fields": ["settings.shots"]},
        actual_settings={"shots": 0, "noise": "none", "seed": None},
    )
    assert receipt["timing"]["censored"] is True
    assert receipt["timing"]["elapsed_seconds"] is None
    assert receipt["timing"]["ended_at"] is None
    assert receipt["result_manifest_digest"] is None
    assert receipt_is_enrollable_as_current_evidence(receipt) is False

    with pytest.raises(FocusedLoopError) as excinfo:
        make_receipt(
            plan,
            status=status,
            timing=observed_timing(started_at=10.0, ended_at=10.5),
            result_manifest_digest=None,
            deviation={"detected": True, "fields": ["settings.shots"]},
        )
    assert excinfo.value.category == "execution_receipt_timing_invalid"


def test_a_completed_receipt_may_not_carry_censored_timing() -> None:
    plan = make_plan()
    with pytest.raises(FocusedLoopError) as excinfo:
        make_receipt(
            plan,
            timing=censored_timing(started_at=1.0, censor_reason="executor_cancelled"),
        )
    assert excinfo.value.category == "execution_receipt_timing_invalid"


def test_only_a_completed_receipt_may_bind_a_result_manifest_digest() -> None:
    plan = make_plan()
    with pytest.raises(FocusedLoopError) as failure_error:
        make_receipt(
            plan,
            status=STATUS_FAILED,
            timing=censored_timing(started_at=1.0, censor_reason="executor_backend_failed"),
            result_manifest_digest=MANIFEST_DIGEST,
        )
    assert failure_error.value.category == "execution_receipt_result_manifest_digest_invalid"

    with pytest.raises(FocusedLoopError) as completed_error:
        make_receipt(plan, result_manifest_digest=None)
    assert completed_error.value.category == "execution_receipt_result_manifest_digest_invalid"


def test_unsupported_status_receipt_records_absence_without_fabrication() -> None:
    plan = make_plan()
    receipt = make_receipt(
        plan,
        status=STATUS_UNSUPPORTED,
        timing=censored_timing(started_at=None, censor_reason="executor_backend_unavailable"),
        resource_observation=unmeasured_resource_observation(),
        result_manifest_digest=None,
        deviation={"detected": True, "fields": ["settings.shots"]},
        actual_settings={"shots": 0, "noise": "none", "seed": None},
    )
    assert receipt["timing"] == {
        "started_at": None,
        "ended_at": None,
        "elapsed_seconds": None,
        "censored": True,
        "censor_reason": "executor_backend_unavailable",
    }
    assert receipt["resource_observation"] == {
        "peak_memory_bytes": None,
        "below_resolution": True,
    }


def test_resource_observation_may_not_claim_a_number_and_below_resolution() -> None:
    plan = make_plan()
    with pytest.raises(FocusedLoopError) as both_error:
        make_receipt(
            plan, resource_observation={"peak_memory_bytes": 1_024, "below_resolution": True}
        )
    assert both_error.value.category == "execution_receipt_resource_observation_invalid"
    with pytest.raises(FocusedLoopError) as neither_error:
        make_receipt(
            plan, resource_observation={"peak_memory_bytes": None, "below_resolution": False}
        )
    assert neither_error.value.category == "execution_receipt_resource_observation_invalid"


def test_deviation_block_must_be_internally_consistent() -> None:
    plan = make_plan()
    with pytest.raises(FocusedLoopError) as empty_error:
        make_receipt(plan, deviation={"detected": True, "fields": []})
    assert empty_error.value.category == "execution_receipt_deviation_invalid"
    with pytest.raises(FocusedLoopError) as listed_error:
        make_receipt(plan, deviation={"detected": False, "fields": ["settings.shots"]})
    assert listed_error.value.category == "execution_receipt_deviation_invalid"


def test_unsupported_status_value_is_refused() -> None:
    plan = make_plan()
    with pytest.raises(FocusedLoopError) as excinfo:
        make_receipt(plan, status="probably_fine")
    assert excinfo.value.category == "execution_receipt_status_unsupported"
