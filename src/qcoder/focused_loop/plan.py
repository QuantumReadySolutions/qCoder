"""Inert ``execution_plan.v1`` record for the first Explorer focused loop.

Committing a plan is never execution. Every function here is pure: building a plan
touches no file, no clock, no environment, and no backend. The plan is a frozen,
self-digesting description of exactly one bounded local stabilizer workload, and its
``plan_digest`` is the join key that the separate authority, the sibling execution
receipt, and the strict result manifest all bind to.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from qcoder.focused_loop.canonical import (
    FocusedLoopError,
    bounded_text,
    digest_excluding,
    digest_text,
    enum_value,
    strict_float,
    strict_int,
    strict_mapping,
)
from qcoder.focused_loop.identities import (
    EXECUTION_PLAN_SCHEMA_ID,
    EXECUTION_RECEIPT_SCHEMA_ID,
    FIXED_SHOTS,
    METHOD_STABILIZER,
    REGIME_ID,
    RESULT_PROTOCOL_SCHEMA_ID,
)

PLAN_DIGEST_FIELD = "plan_digest"
PLAN_STATE_INERT = "inert"
CIRCUIT_TRANSPORT_WORKSPACE_RELATIVE_QASM_PATH = "workspace_relative_qasm_path"

ALLOWED_CIRCUIT_TRANSPORTS = (CIRCUIT_TRANSPORT_WORKSPACE_RELATIVE_QASM_PATH,)
ALLOWED_METHOD_IDS = (METHOD_STABILIZER,)
ALLOWED_RESULT_PROTOCOL_IDS = (RESULT_PROTOCOL_SCHEMA_ID,)
ALLOWED_NOISE_SETTINGS = ("none",)
ALLOWED_PLAN_STATES = (PLAN_STATE_INERT,)
ALLOWED_RECEIPT_SCHEMA_IDS = (EXECUTION_RECEIPT_SCHEMA_ID,)

MAX_WALL_SECONDS_CEILING = 3_600.0
MAX_MEMORY_BYTES_CEILING = 64 * 1024**3
MAX_CIRCUIT_PATH_BYTES = 512
MAX_SEED = 2**63 - 1

PLAN_FIELDS = (
    "schema_id",
    "regime_id",
    "objective_digest",
    "circuit_digest",
    "circuit_transport",
    "circuit_path",
    "profile_digest",
    "method_id",
    "settings",
    "limits",
    "result_protocol_id",
    "expected_receipt_schema_id",
    "plan_state",
    PLAN_DIGEST_FIELD,
)
SETTINGS_FIELDS = ("shots", "noise", "seed")
LIMITS_FIELDS = ("max_wall_seconds", "max_memory_bytes")


def _settings(value: object) -> dict[str, Any]:
    settings = strict_mapping(
        value, required=SETTINGS_FIELDS, category="execution_plan_settings_invalid"
    )
    shots = strict_int(settings["shots"], category="execution_plan_shots_unsupported")
    if shots != FIXED_SHOTS:
        raise FocusedLoopError("execution_plan_shots_unsupported")
    noise = enum_value(
        settings["noise"],
        allowed=ALLOWED_NOISE_SETTINGS,
        category="execution_plan_noise_unsupported",
    )
    seed = settings["seed"]
    if seed is not None:
        seed = strict_int(
            seed, category="execution_plan_seed_invalid", minimum=0, maximum=MAX_SEED
        )
    return {"shots": shots, "noise": noise, "seed": seed}


def _limits(value: object) -> dict[str, Any]:
    limits = strict_mapping(
        value, required=LIMITS_FIELDS, category="execution_plan_limits_invalid"
    )
    return {
        "max_wall_seconds": strict_float(
            limits["max_wall_seconds"],
            category="execution_plan_limits_invalid",
            minimum=0.001,
            maximum=MAX_WALL_SECONDS_CEILING,
        ),
        "max_memory_bytes": strict_int(
            limits["max_memory_bytes"],
            category="execution_plan_limits_invalid",
            minimum=1,
            maximum=MAX_MEMORY_BYTES_CEILING,
        ),
    }


def _circuit_path(value: object) -> str:
    return bounded_text(
        value, category="execution_plan_circuit_path_invalid", max_bytes=MAX_CIRCUIT_PATH_BYTES
    )


def build_execution_plan(
    *,
    objective_digest: str,
    circuit_digest: str,
    circuit_path: str,
    profile_digest: str,
    seed: int | None = None,
    max_wall_seconds: float = 60.0,
    max_memory_bytes: int = 2 * 1024**3,
    method_id: str = METHOD_STABILIZER,
    shots: int = FIXED_SHOTS,
    noise: str = "none",
    circuit_transport: str = CIRCUIT_TRANSPORT_WORKSPACE_RELATIVE_QASM_PATH,
    result_protocol_id: str = RESULT_PROTOCOL_SCHEMA_ID,
    expected_receipt_schema_id: str = EXECUTION_RECEIPT_SCHEMA_ID,
    regime_id: str = REGIME_ID,
) -> dict[str, Any]:
    """Return one inert, self-digesting execution plan. This never executes anything."""
    payload: dict[str, Any] = {
        "schema_id": EXECUTION_PLAN_SCHEMA_ID,
        "regime_id": regime_id,
        "objective_digest": objective_digest,
        "circuit_digest": circuit_digest,
        "circuit_transport": circuit_transport,
        "circuit_path": circuit_path,
        "profile_digest": profile_digest,
        "method_id": method_id,
        "settings": {"shots": shots, "noise": noise, "seed": seed},
        "limits": {
            "max_wall_seconds": max_wall_seconds,
            "max_memory_bytes": max_memory_bytes,
        },
        "result_protocol_id": result_protocol_id,
        "expected_receipt_schema_id": expected_receipt_schema_id,
        "plan_state": PLAN_STATE_INERT,
    }
    normalized = _normalize_plan_body(payload)
    normalized[PLAN_DIGEST_FIELD] = digest_excluding(normalized, field=PLAN_DIGEST_FIELD)
    return normalized


def _normalize_plan_body(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema_id") != EXECUTION_PLAN_SCHEMA_ID:
        raise FocusedLoopError("execution_plan_schema_invalid")
    if value.get("regime_id") != REGIME_ID:
        raise FocusedLoopError("execution_plan_regime_unsupported")
    return {
        "schema_id": EXECUTION_PLAN_SCHEMA_ID,
        "regime_id": REGIME_ID,
        "objective_digest": digest_text(
            value.get("objective_digest"), category="execution_plan_objective_digest_invalid"
        ),
        "circuit_digest": digest_text(
            value.get("circuit_digest"), category="execution_plan_circuit_digest_invalid"
        ),
        "circuit_transport": enum_value(
            value.get("circuit_transport"),
            allowed=ALLOWED_CIRCUIT_TRANSPORTS,
            category="execution_plan_circuit_transport_unsupported",
        ),
        "circuit_path": _circuit_path(value.get("circuit_path")),
        "profile_digest": digest_text(
            value.get("profile_digest"), category="execution_plan_profile_digest_invalid"
        ),
        "method_id": enum_value(
            value.get("method_id"),
            allowed=ALLOWED_METHOD_IDS,
            category="execution_plan_method_unsupported",
        ),
        "settings": _settings(value.get("settings")),
        "limits": _limits(value.get("limits")),
        "result_protocol_id": enum_value(
            value.get("result_protocol_id"),
            allowed=ALLOWED_RESULT_PROTOCOL_IDS,
            category="execution_plan_result_protocol_unsupported",
        ),
        "expected_receipt_schema_id": enum_value(
            value.get("expected_receipt_schema_id"),
            allowed=ALLOWED_RECEIPT_SCHEMA_IDS,
            category="execution_plan_receipt_schema_unsupported",
        ),
        "plan_state": enum_value(
            value.get("plan_state"),
            allowed=ALLOWED_PLAN_STATES,
            category="execution_plan_state_not_inert",
        ),
    }


def validate_execution_plan(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an existing plan record, including its self-digest. Pure."""
    strict = strict_mapping(
        payload, required=PLAN_FIELDS, category="execution_plan_schema_invalid"
    )
    normalized = _normalize_plan_body(strict)
    expected = digest_excluding(normalized, field=PLAN_DIGEST_FIELD)
    if strict.get(PLAN_DIGEST_FIELD) != expected:
        raise FocusedLoopError("execution_plan_digest_mismatch")
    normalized[PLAN_DIGEST_FIELD] = expected
    return normalized


def plan_digest_of(payload: Mapping[str, Any]) -> str:
    """Return the validated join key of ``payload``."""
    return str(validate_execution_plan(payload)[PLAN_DIGEST_FIELD])


__all__ = [
    "ALLOWED_CIRCUIT_TRANSPORTS",
    "ALLOWED_METHOD_IDS",
    "ALLOWED_NOISE_SETTINGS",
    "ALLOWED_PLAN_STATES",
    "ALLOWED_RESULT_PROTOCOL_IDS",
    "CIRCUIT_TRANSPORT_WORKSPACE_RELATIVE_QASM_PATH",
    "PLAN_DIGEST_FIELD",
    "PLAN_FIELDS",
    "PLAN_STATE_INERT",
    "build_execution_plan",
    "plan_digest_of",
    "validate_execution_plan",
]
