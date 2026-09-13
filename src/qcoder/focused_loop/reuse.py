"""Currentness and reuse primitives driven by exact identities only.

Reuse is decided from digests, never from narrative. Chat history, prior turns, the
name of a file, directory adjacency, modification time, and "we ran something like this
earlier" are not inputs here and cannot be. An accepted result is reusable only when
every one of the exact identities below matches and the accepted record is still
current; anything stale or cross-revision is rejected rather than reused.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from qcoder.focused_loop.authority import (
    AttemptLedger,
    attempt_identity_text,
    consumed_identities,
)
from qcoder.focused_loop.canonical import (
    FocusedLoopError,
    bounded_text,
    canonical_digest,
    digest_text,
    enum_value,
    strict_mapping,
)
from qcoder.focused_loop.identities import RESULT_PROTOCOL_SCHEMA_ID
from qcoder.focused_loop.receipt import normalize_runtime_versions

ACTION_REUSE_EXISTING_RESULT = "reuse_existing_result"
ACTION_REQUIRE_NEW_EXECUTION = "require_new_execution"
REUSE_ACTIONS = (ACTION_REUSE_EXISTING_RESULT, ACTION_REQUIRE_NEW_EXECUTION)

CURRENTNESS_CURRENT = "current"
CURRENTNESS_STALE = "stale"
CURRENTNESS_SUPERSEDED = "superseded"
CURRENTNESS_UNKNOWN = "unknown"
CURRENTNESS_STATES = (
    CURRENTNESS_CURRENT,
    CURRENTNESS_STALE,
    CURRENTNESS_SUPERSEDED,
    CURRENTNESS_UNKNOWN,
)

IDENTITY_FIELDS = (
    "objective_digest",
    "circuit_digest",
    "plan_digest",
    "result_protocol_id",
    "profile_digest",
    "runtime_versions",
)
ACCEPTED_RECORD_FIELDS = (
    "identity",
    "currentness",
    "result_manifest_digest",
    "receipt_digest",
    "attempt_identity",
)

_IDENTITY_MISMATCH_CATEGORIES = {
    "objective_digest": "reuse_objective_digest_mismatch",
    "circuit_digest": "reuse_circuit_digest_mismatch",
    "plan_digest": "reuse_plan_digest_mismatch",
    "result_protocol_id": "reuse_result_protocol_mismatch",
    "profile_digest": "reuse_profile_digest_mismatch",
    "runtime_versions": "reuse_runtime_version_mismatch",
}


def build_reuse_identity(
    *,
    objective_digest: str,
    circuit_digest: str,
    plan_digest: str,
    profile_digest: str,
    runtime_versions: Mapping[str, Any],
    result_protocol_id: str = RESULT_PROTOCOL_SCHEMA_ID,
) -> dict[str, Any]:
    """Return the exact identity tuple that alone decides reuse."""
    return {
        "objective_digest": digest_text(objective_digest, category="reuse_identity_invalid"),
        "circuit_digest": digest_text(circuit_digest, category="reuse_identity_invalid"),
        "plan_digest": digest_text(plan_digest, category="reuse_identity_invalid"),
        "result_protocol_id": enum_value(
            result_protocol_id,
            allowed=(RESULT_PROTOCOL_SCHEMA_ID,),
            category="reuse_result_protocol_unsupported",
        ),
        "profile_digest": digest_text(profile_digest, category="reuse_identity_invalid"),
        "runtime_versions": normalize_runtime_versions(runtime_versions),
    }


def normalize_reuse_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    strict = strict_mapping(value, required=IDENTITY_FIELDS, category="reuse_identity_invalid")
    return build_reuse_identity(
        objective_digest=strict["objective_digest"],
        circuit_digest=strict["circuit_digest"],
        plan_digest=strict["plan_digest"],
        profile_digest=strict["profile_digest"],
        runtime_versions=strict["runtime_versions"],
        result_protocol_id=strict["result_protocol_id"],
    )


def reuse_identity_digest(identity: Mapping[str, Any]) -> str:
    return canonical_digest(normalize_reuse_identity(identity))


def normalize_accepted_result(value: Mapping[str, Any]) -> dict[str, Any]:
    strict = strict_mapping(
        value, required=ACCEPTED_RECORD_FIELDS, category="reuse_accepted_result_invalid"
    )
    return {
        "identity": normalize_reuse_identity(strict["identity"]),
        "currentness": enum_value(
            strict["currentness"],
            allowed=CURRENTNESS_STATES,
            category="reuse_accepted_result_invalid",
        ),
        "result_manifest_digest": digest_text(
            strict["result_manifest_digest"], category="reuse_accepted_result_invalid"
        ),
        "receipt_digest": digest_text(
            strict["receipt_digest"], category="reuse_accepted_result_invalid"
        ),
        "attempt_identity": attempt_identity_text(strict["attempt_identity"]),
    }


def decide_result_reuse(
    *,
    request_identity: Mapping[str, Any],
    accepted_result: Mapping[str, Any],
) -> dict[str, Any]:
    """Decide reuse from exact identities alone.

    An equivalent, accepted, still-current request yields ``reuse_existing_result`` and
    requires zero new execution attempts. Any identity difference or any non-current
    accepted result is rejected with its own bounded category; it is never softened
    into a "probably the same" reuse.
    """
    requested = normalize_reuse_identity(request_identity)
    accepted = normalize_accepted_result(accepted_result)
    for name in IDENTITY_FIELDS:
        if requested[name] != accepted["identity"][name]:
            raise FocusedLoopError(_IDENTITY_MISMATCH_CATEGORIES[name])
    if accepted["currentness"] != CURRENTNESS_CURRENT:
        raise FocusedLoopError("reuse_accepted_result_not_current")
    return {
        "action": ACTION_REUSE_EXISTING_RESULT,
        "identity_digest": reuse_identity_digest(requested),
        "result_manifest_digest": accepted["result_manifest_digest"],
        "receipt_digest": accepted["receipt_digest"],
        "reused_attempt_identity": accepted["attempt_identity"],
        "new_execution_attempts_required": 0,
        "evidence_basis": "exact_identity_match",
    }


def require_new_execution(*, reason: str) -> dict[str, Any]:
    """The explicit non-reuse decision: a fresh plan and a fresh authority are needed."""
    return {
        "action": ACTION_REQUIRE_NEW_EXECUTION,
        "reason": bounded_text(reason, category="reuse_reason_invalid"),
        "new_execution_attempts_required": 1,
        "evidence_basis": "no_exact_identity_match",
    }


def refuse_duplicate_execution_attempt(
    *,
    attempt_identity: str,
    consumed: AttemptLedger | Iterable[str] | None,
) -> str:
    """Refuse a second execution under an already-consumed attempt identity."""
    identity = attempt_identity_text(attempt_identity)
    if identity in consumed_identities(consumed):
        raise FocusedLoopError("execution_attempt_identity_already_consumed")
    return identity


__all__ = [
    "ACCEPTED_RECORD_FIELDS",
    "ACTION_REQUIRE_NEW_EXECUTION",
    "ACTION_REUSE_EXISTING_RESULT",
    "CURRENTNESS_CURRENT",
    "CURRENTNESS_STALE",
    "CURRENTNESS_STATES",
    "CURRENTNESS_SUPERSEDED",
    "CURRENTNESS_UNKNOWN",
    "IDENTITY_FIELDS",
    "REUSE_ACTIONS",
    "build_reuse_identity",
    "decide_result_reuse",
    "normalize_accepted_result",
    "normalize_reuse_identity",
    "refuse_duplicate_execution_attempt",
    "require_new_execution",
    "reuse_identity_digest",
]
