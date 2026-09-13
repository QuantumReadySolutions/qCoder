"""Sibling ``execution_receipt.v1`` conformance record and exact deviation detection.

The receipt is the conformance sibling of the inert plan: it states what actually ran,
observed in-process, and binds back to the plan digest, the single-use attempt
identity, and the exact result-manifest digest. Absence of a measurement is recorded as
absence -- a censored duration and a null resource observation are legitimate evidence
and are never replaced by a fabricated number. Any detected deviation from the plan
disqualifies the receipt from enrolment as current evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from qcoder.focused_loop.canonical import (
    MAX_LIST_ITEMS,
    FocusedLoopError,
    bounded_text,
    bounded_text_list,
    digest_excluding,
    digest_text,
    enum_value,
    strict_bool,
    strict_float,
    strict_int,
    strict_mapping,
)
from qcoder.focused_loop.identities import EXECUTION_RECEIPT_SCHEMA_ID
from qcoder.focused_loop.plan import validate_execution_plan

RECEIPT_DIGEST_FIELD = "receipt_digest"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_TIMEOUT = "timeout"
STATUS_CANCELLED = "cancelled"
STATUS_UNSUPPORTED = "unsupported"
RECEIPT_STATUSES = (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_TIMEOUT,
    STATUS_CANCELLED,
    STATUS_UNSUPPORTED,
)

MAX_RUNTIME_VERSION_ENTRIES = 32
MAX_MEMORY_OBSERVATION_BYTES = 1 << 60

RECEIPT_FIELDS = (
    "schema_id",
    "plan_digest",
    "authority_digest",
    "attempt_identity",
    "actual_method",
    "actual_settings",
    "actual_profile_digest",
    "runtime_versions",
    "timing",
    "resource_observation",
    "result_manifest_digest",
    "status",
    "deviation",
    "plan_match_verified_in_process",
    RECEIPT_DIGEST_FIELD,
)
TIMING_FIELDS = ("started_at", "ended_at", "elapsed_seconds", "censored", "censor_reason")
RESOURCE_FIELDS = ("peak_memory_bytes", "below_resolution")
SETTINGS_FIELDS = ("shots", "noise", "seed")
DEVIATION_FIELDS = ("detected", "fields")


def normalize_runtime_versions(value: object) -> dict[str, str]:
    """Validate a bounded mapping of runtime component name to exact version text."""
    if not isinstance(value, Mapping) or len(value) > MAX_RUNTIME_VERSION_ENTRIES:
        raise FocusedLoopError("execution_receipt_runtime_versions_invalid")
    versions: dict[str, str] = {}
    for key, item in value.items():
        name = bounded_text(key, category="execution_receipt_runtime_versions_invalid")
        versions[name] = bounded_text(
            item, category="execution_receipt_runtime_versions_invalid"
        )
    return dict(sorted(versions.items()))


def normalize_actual_settings(value: object) -> dict[str, Any]:
    """Validate the settings the executor actually applied (not the planned ones)."""
    settings = strict_mapping(
        value, required=SETTINGS_FIELDS, category="execution_receipt_settings_invalid"
    )
    seed = settings["seed"]
    if seed is not None:
        seed = strict_int(seed, category="execution_receipt_settings_invalid", minimum=0)
    return {
        "shots": strict_int(
            settings["shots"], category="execution_receipt_settings_invalid", minimum=0
        ),
        "noise": bounded_text(
            settings["noise"], category="execution_receipt_settings_invalid"
        ),
        "seed": seed,
    }


def _timing(value: object) -> dict[str, Any]:
    timing = strict_mapping(
        value, required=TIMING_FIELDS, category="execution_receipt_timing_invalid"
    )
    censored = strict_bool(timing["censored"], category="execution_receipt_timing_invalid")
    started = timing["started_at"]
    if started is not None:
        started = strict_float(started, category="execution_receipt_timing_invalid")
    if censored:
        if timing["ended_at"] is not None or timing["elapsed_seconds"] is not None:
            raise FocusedLoopError("execution_receipt_timing_invalid")
        reason = bounded_text(
            timing["censor_reason"], category="execution_receipt_timing_invalid"
        )
        return {
            "started_at": started,
            "ended_at": None,
            "elapsed_seconds": None,
            "censored": True,
            "censor_reason": reason,
        }
    if timing["censor_reason"] is not None:
        raise FocusedLoopError("execution_receipt_timing_invalid")
    if started is None:
        raise FocusedLoopError("execution_receipt_timing_invalid")
    ended = strict_float(timing["ended_at"], category="execution_receipt_timing_invalid")
    elapsed = strict_float(
        timing["elapsed_seconds"], category="execution_receipt_timing_invalid", minimum=0.0
    )
    if ended < started or abs(elapsed - (ended - started)) > 1e-6:
        raise FocusedLoopError("execution_receipt_timing_invalid")
    return {
        "started_at": started,
        "ended_at": ended,
        "elapsed_seconds": elapsed,
        "censored": False,
        "censor_reason": None,
    }


def _resource_observation(value: object) -> dict[str, Any]:
    observation = strict_mapping(
        value,
        required=RESOURCE_FIELDS,
        category="execution_receipt_resource_observation_invalid",
    )
    below_resolution = strict_bool(
        observation["below_resolution"],
        category="execution_receipt_resource_observation_invalid",
    )
    peak = observation["peak_memory_bytes"]
    if peak is None:
        if not below_resolution:
            raise FocusedLoopError("execution_receipt_resource_observation_invalid")
        return {"peak_memory_bytes": None, "below_resolution": True}
    if below_resolution:
        raise FocusedLoopError("execution_receipt_resource_observation_invalid")
    return {
        "peak_memory_bytes": strict_int(
            peak,
            category="execution_receipt_resource_observation_invalid",
            minimum=0,
            maximum=MAX_MEMORY_OBSERVATION_BYTES,
        ),
        "below_resolution": False,
    }


def _deviation(value: object) -> dict[str, Any]:
    deviation = strict_mapping(
        value, required=DEVIATION_FIELDS, category="execution_receipt_deviation_invalid"
    )
    detected = strict_bool(
        deviation["detected"], category="execution_receipt_deviation_invalid"
    )
    fields = bounded_text_list(
        deviation["fields"],
        category="execution_receipt_deviation_invalid",
        max_items=MAX_LIST_ITEMS,
    )
    if detected != bool(fields):
        raise FocusedLoopError("execution_receipt_deviation_invalid")
    return {"detected": detected, "fields": sorted(fields)}


def detect_plan_deviation(
    *,
    plan: Mapping[str, Any],
    actual_method: str,
    actual_settings: Mapping[str, Any],
    actual_profile_digest: str,
    runtime_versions: Mapping[str, Any],
    planned_runtime_versions: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare planned versus actual and list the exact differing field names."""
    validated_plan = validate_execution_plan(plan)
    settings = normalize_actual_settings(actual_settings)
    observed_versions = normalize_runtime_versions(runtime_versions)
    expected_versions = normalize_runtime_versions(planned_runtime_versions)
    fields: list[str] = []
    if actual_method != validated_plan["method_id"]:
        fields.append("method_id")
    for name in SETTINGS_FIELDS:
        if settings[name] != validated_plan["settings"][name]:
            fields.append(f"settings.{name}")
    if actual_profile_digest != validated_plan["profile_digest"]:
        fields.append("profile_digest")
    for name in sorted(set(expected_versions) | set(observed_versions)):
        if expected_versions.get(name) != observed_versions.get(name):
            fields.append(f"runtime_versions.{name}")
    return {"detected": bool(fields), "fields": sorted(fields)}


def _normalize_receipt_body(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema_id") != EXECUTION_RECEIPT_SCHEMA_ID:
        raise FocusedLoopError("execution_receipt_schema_invalid")
    status = enum_value(
        value.get("status"),
        allowed=RECEIPT_STATUSES,
        category="execution_receipt_status_unsupported",
    )
    manifest_digest = value.get("result_manifest_digest")
    if status == STATUS_COMPLETED:
        manifest_digest = digest_text(
            manifest_digest, category="execution_receipt_result_manifest_digest_invalid"
        )
    elif manifest_digest is not None:
        raise FocusedLoopError("execution_receipt_result_manifest_digest_invalid")
    deviation = _deviation(value.get("deviation"))
    timing = _timing(value.get("timing"))
    if status == STATUS_COMPLETED and timing["censored"]:
        raise FocusedLoopError("execution_receipt_timing_invalid")
    if status in (STATUS_TIMEOUT, STATUS_CANCELLED) and not timing["censored"]:
        raise FocusedLoopError("execution_receipt_timing_invalid")
    return {
        "schema_id": EXECUTION_RECEIPT_SCHEMA_ID,
        "plan_digest": digest_text(
            value.get("plan_digest"), category="execution_receipt_plan_digest_invalid"
        ),
        "authority_digest": digest_text(
            value.get("authority_digest"),
            category="execution_receipt_authority_digest_invalid",
        ),
        "attempt_identity": bounded_text(
            value.get("attempt_identity"),
            category="execution_receipt_attempt_identity_invalid",
        ),
        "actual_method": bounded_text(
            value.get("actual_method"), category="execution_receipt_method_invalid"
        ),
        "actual_settings": normalize_actual_settings(value.get("actual_settings")),
        "actual_profile_digest": digest_text(
            value.get("actual_profile_digest"),
            category="execution_receipt_profile_digest_invalid",
        ),
        "runtime_versions": normalize_runtime_versions(value.get("runtime_versions")),
        "timing": timing,
        "resource_observation": _resource_observation(value.get("resource_observation")),
        "result_manifest_digest": manifest_digest,
        "status": status,
        "deviation": deviation,
        "plan_match_verified_in_process": strict_bool(
            value.get("plan_match_verified_in_process"),
            category="execution_receipt_plan_match_flag_invalid",
        ),
    }


def build_execution_receipt(
    *,
    plan_digest: str,
    authority_digest: str,
    attempt_identity: str,
    actual_method: str,
    actual_settings: Mapping[str, Any],
    actual_profile_digest: str,
    runtime_versions: Mapping[str, Any],
    timing: Mapping[str, Any],
    resource_observation: Mapping[str, Any],
    status: str,
    deviation: Mapping[str, Any],
    plan_match_verified_in_process: bool,
    result_manifest_digest: str | None = None,
) -> dict[str, Any]:
    """Return one self-digesting sibling execution receipt."""
    payload = {
        "schema_id": EXECUTION_RECEIPT_SCHEMA_ID,
        "plan_digest": plan_digest,
        "authority_digest": authority_digest,
        "attempt_identity": attempt_identity,
        "actual_method": actual_method,
        "actual_settings": dict(actual_settings),
        "actual_profile_digest": actual_profile_digest,
        "runtime_versions": dict(runtime_versions),
        "timing": dict(timing),
        "resource_observation": dict(resource_observation),
        "result_manifest_digest": result_manifest_digest,
        "status": status,
        "deviation": dict(deviation),
        "plan_match_verified_in_process": plan_match_verified_in_process,
    }
    normalized = _normalize_receipt_body(payload)
    normalized[RECEIPT_DIGEST_FIELD] = digest_excluding(normalized, field=RECEIPT_DIGEST_FIELD)
    return normalized


def censored_timing(*, started_at: float | None, censor_reason: str) -> dict[str, Any]:
    """Timing block for a run whose duration must not be asserted."""
    return {
        "started_at": started_at,
        "ended_at": None,
        "elapsed_seconds": None,
        "censored": True,
        "censor_reason": censor_reason,
    }


def observed_timing(*, started_at: float, ended_at: float) -> dict[str, Any]:
    return {
        "started_at": started_at,
        "ended_at": ended_at,
        "elapsed_seconds": ended_at - started_at,
        "censored": False,
        "censor_reason": None,
    }


def unmeasured_resource_observation() -> dict[str, Any]:
    """Below-resolution memory is evidence of absence, never a fabricated number."""
    return {"peak_memory_bytes": None, "below_resolution": True}


def validate_execution_receipt(
    payload: Mapping[str, Any],
    *,
    plan: Mapping[str, Any],
    expected_attempt_identity: str | None = None,
    expected_authority_digest: str | None = None,
    expected_profile_digest: str | None = None,
    expected_runtime_versions: Mapping[str, Any] | None = None,
    expected_result_manifest_digest: str | None = None,
) -> dict[str, Any]:
    """Validate a receipt against its plan, returning bounded rejection categories."""
    strict = strict_mapping(
        payload, required=RECEIPT_FIELDS, category="execution_receipt_schema_invalid"
    )
    normalized = _normalize_receipt_body(strict)
    expected_digest = digest_excluding(normalized, field=RECEIPT_DIGEST_FIELD)
    if strict.get(RECEIPT_DIGEST_FIELD) != expected_digest:
        raise FocusedLoopError("execution_receipt_digest_mismatch")
    normalized[RECEIPT_DIGEST_FIELD] = expected_digest

    validated_plan = validate_execution_plan(plan)
    if normalized["plan_digest"] != validated_plan["plan_digest"]:
        raise FocusedLoopError("execution_receipt_plan_digest_mismatch")
    if normalized["actual_method"] != validated_plan["method_id"]:
        raise FocusedLoopError("execution_receipt_method_mismatch")
    if normalized["actual_settings"]["shots"] != validated_plan["settings"]["shots"]:
        raise FocusedLoopError("execution_receipt_shots_mismatch")
    if normalized["actual_settings"]["noise"] != validated_plan["settings"]["noise"]:
        raise FocusedLoopError("execution_receipt_noise_mismatch")
    if normalized["actual_settings"]["seed"] != validated_plan["settings"]["seed"]:
        raise FocusedLoopError("execution_receipt_seed_mismatch")

    expected_profile = (
        validated_plan["profile_digest"]
        if expected_profile_digest is None
        else expected_profile_digest
    )
    if normalized["actual_profile_digest"] != expected_profile:
        raise FocusedLoopError("execution_receipt_profile_mismatch")
    if expected_runtime_versions is not None:
        if normalized["runtime_versions"] != normalize_runtime_versions(
            expected_runtime_versions
        ):
            raise FocusedLoopError("execution_receipt_runtime_version_mismatch")
    if expected_attempt_identity is not None:
        if normalized["attempt_identity"] != expected_attempt_identity:
            raise FocusedLoopError("execution_receipt_attempt_identity_mismatch")
    if expected_authority_digest is not None:
        if normalized["authority_digest"] != expected_authority_digest:
            raise FocusedLoopError("execution_receipt_authority_digest_mismatch")
    if expected_result_manifest_digest is not None:
        if normalized["result_manifest_digest"] != expected_result_manifest_digest:
            raise FocusedLoopError("execution_receipt_result_manifest_digest_mismatch")
    return normalized


def receipt_is_enrollable_as_current_evidence(receipt: Mapping[str, Any]) -> bool:
    """A receipt is enrollable only when it completed with zero detected deviation."""
    return bool(
        receipt.get("status") == STATUS_COMPLETED
        and receipt.get("plan_match_verified_in_process") is True
        and isinstance(receipt.get("deviation"), Mapping)
        and receipt["deviation"].get("detected") is False
        and not receipt["deviation"].get("fields")
        and receipt.get("result_manifest_digest") is not None
    )


def require_enrollable_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    if not receipt_is_enrollable_as_current_evidence(receipt):
        raise FocusedLoopError("execution_receipt_not_enrollable")
    return dict(receipt)


__all__ = [
    "RECEIPT_DIGEST_FIELD",
    "RECEIPT_FIELDS",
    "RECEIPT_STATUSES",
    "STATUS_CANCELLED",
    "STATUS_COMPLETED",
    "STATUS_FAILED",
    "STATUS_TIMEOUT",
    "STATUS_UNSUPPORTED",
    "build_execution_receipt",
    "censored_timing",
    "detect_plan_deviation",
    "normalize_actual_settings",
    "normalize_runtime_versions",
    "observed_timing",
    "receipt_is_enrollable_as_current_evidence",
    "require_enrollable_receipt",
    "unmeasured_resource_observation",
    "validate_execution_receipt",
]
