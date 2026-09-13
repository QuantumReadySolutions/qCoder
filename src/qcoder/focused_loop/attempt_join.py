"""Generic attempt-identity joins over one plan, one authority and one sibling receipt.

Nothing here knows about any result-manifest schema. These are the joins that hold
whenever a bounded execution attempt is reconciled against the plan that authorized it,
so they belong in the Phase A production substrate regardless of which manifest a later
phase composes with.

Result-manifest composition is deliberately absent. Projecting a receipt into the
Current Loop strict result manifest and running its real validator is *compatibility
evidence* rather than production behaviour, so it lives in test support until the
post-WI-0441 exact head is reconciled. Keeping it out of here is what allows the
focused-loop package to carry no ``qcoder.current_loop_*`` dependency at all.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from qcoder.focused_loop.canonical import FocusedLoopError, digest_text
from qcoder.focused_loop.plan import validate_execution_plan
from qcoder.focused_loop.receipt import (
    RECEIPT_DIGEST_FIELD,
    build_execution_receipt,
    detect_plan_deviation,
    receipt_is_enrollable_as_current_evidence,
)

#: The joins this module proves. A caller that composes a result manifest is expected to
#: extend this list with its own schema-specific joins rather than replace it.
GENERIC_JOINS_VERIFIED = (
    "plan_digest",
    "authority_plan_digest",
    "authority_digest",
    "attempt_identity",
    "method_settings_profile_versions",
)


def rebind_receipt_result_manifest_digest(
    *, receipt: Mapping[str, Any], result_manifest_digest: str
) -> dict[str, Any]:
    """Return ``receipt`` rebound to an exact result-manifest digest.

    The executor emits a provisional outcome digest because no result manifest exists
    yet at execution time. Rebinding is a separate, explicit step so the receipt never
    silently claims a binding it does not have, and it rebuilds the record through the
    normal constructor so the receipt digest is recomputed rather than patched.
    """
    return build_execution_receipt(
        plan_digest=receipt["plan_digest"],
        authority_digest=receipt["authority_digest"],
        attempt_identity=receipt["attempt_identity"],
        actual_method=receipt["actual_method"],
        actual_settings=receipt["actual_settings"],
        actual_profile_digest=receipt["actual_profile_digest"],
        runtime_versions=receipt["runtime_versions"],
        timing=receipt["timing"],
        resource_observation=receipt["resource_observation"],
        status=receipt["status"],
        deviation=receipt["deviation"],
        plan_match_verified_in_process=receipt["plan_match_verified_in_process"],
        result_manifest_digest=digest_text(
            result_manifest_digest, category="attempt_join_result_manifest_digest_invalid"
        ),
    )


def join_attempt_records(
    *,
    plan: Mapping[str, Any],
    authority: Mapping[str, Any],
    receipt: Mapping[str, Any],
    planned_runtime_versions: Mapping[str, Any],
) -> dict[str, Any]:
    """Prove that one plan, one authority and one receipt describe one single attempt.

    Expiry is not re-evaluated: this is a post-hoc join over an attempt that already
    happened, not a fresh grant of authority. Any identity disagreement is a bounded
    rejection and is never softened into a partial match.
    """
    validated_plan = validate_execution_plan(plan)
    if not receipt_is_enrollable_as_current_evidence(receipt):
        raise FocusedLoopError("attempt_join_receipt_not_enrollable")
    if authority.get("plan_digest") != validated_plan["plan_digest"]:
        raise FocusedLoopError("attempt_join_authority_plan_digest_mismatch")
    if receipt.get("plan_digest") != validated_plan["plan_digest"]:
        raise FocusedLoopError("attempt_join_plan_digest_mismatch")
    if receipt.get("authority_digest") != authority.get("authority_digest"):
        raise FocusedLoopError("attempt_join_authority_digest_mismatch")
    if receipt.get("attempt_identity") != authority.get("attempt_identity"):
        raise FocusedLoopError("attempt_join_attempt_identity_mismatch")

    deviation = detect_plan_deviation(
        plan=validated_plan,
        actual_method=receipt["actual_method"],
        actual_settings=receipt["actual_settings"],
        actual_profile_digest=receipt["actual_profile_digest"],
        runtime_versions=receipt["runtime_versions"],
        planned_runtime_versions=planned_runtime_versions,
    )
    if deviation["detected"]:
        raise FocusedLoopError("attempt_join_plan_deviation_detected")

    return {
        "plan": validated_plan,
        "plan_digest": validated_plan["plan_digest"],
        "authority_digest": authority["authority_digest"],
        "attempt_identity": receipt["attempt_identity"],
        "receipt_digest": receipt[RECEIPT_DIGEST_FIELD],
        "deviation": deviation,
        "joins_verified": GENERIC_JOINS_VERIFIED,
        # The loop never claims qCoder independently verified the execution. The
        # receipt's in-process plan conformance check is a separate, stronger claim
        # about a different thing, and is carried by the receipt itself.
        "independent_verification_claimed": False,
        "plan_match_verified_in_process": receipt["plan_match_verified_in_process"],
    }


__all__ = [
    "GENERIC_JOINS_VERIFIED",
    "join_attempt_records",
    "rebind_receipt_result_manifest_digest",
]
