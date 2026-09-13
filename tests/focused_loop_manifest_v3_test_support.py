"""Test-only compatibility proof between the Phase A sibling receipt and manifest v3.

This is *compatibility evidence, not production integration*. Roadmap and Strategic
permit proving now that a Phase A execution receipt can be projected into a valid
``qcoder.current_loop.strict_result_manifest.v3`` payload, but actual strict-manifest
composition is a Phase B responsibility after post-WI-0441 exact-head reconciliation.
Keeping this projection in test support is what lets the entire Phase A production
substrate carry no ``qcoder.current_loop_*`` dependency.

The real validator is imported and used unmodified. Nothing here edits, forks, copies,
subclasses, monkeypatches, relaxes, or reinterprets the accepted v3 contract, and no
stand-in validator is substituted: a payload that v3 rejects is rejected here too. The
generic plan/authority/receipt joins are not reimplemented either; they are taken from
the production module :mod:`qcoder.focused_loop.attempt_join`.

**On ``qcoder_independently_verified_execution: false``.** v3 requires that field to be
exactly ``False``, and this projection always emits ``False``. That is a client-reported
compatibility fact about the shape of a v3 manifest: v3's execution observation block is
defined as a client report, and within that block qCoder asserts no independent
verification. It is *not* a contradiction of the sibling receipt's
``plan_match_verified_in_process: true``, which is a strictly stronger, separate claim
living in a different object: the executor verified, in process, that the artifact it
loaded and the settings it applied matched the frozen plan. The two statements are about
different things, so both hold at once. The stronger claim belongs on the receipt; v3 is
left exactly as accepted.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from qcoder.current_loop_result_manifest import (
    STRICT_RESULT_MANIFEST_SCHEMA_ID,
    STRICT_RESULT_MANIFEST_SCHEMA_VERSION,
    StrictResultManifestError,
    normalize_strict_result_manifest,
)
from qcoder.focused_loop.attempt_join import join_attempt_records
from qcoder.focused_loop.canonical import (
    FocusedLoopError,
    bounded_text,
    digest_text,
    strict_mapping,
)
from qcoder.focused_loop.receipt import STATUS_COMPLETED

MANIFEST_LIMITATION_VERIFICATION_SCOPE = (
    "v3 execution_observation is a client-reported block; "
    "qcoder_independently_verified_execution=false does not contradict the sibling "
    "execution receipt field plan_match_verified_in_process=true."
)
MANIFEST_NON_CLAIM_INDEPENDENT_VERIFICATION = (
    "This manifest does not assert independent qCoder verification of execution."
)
CIRCUIT_LOGICAL_ROLE = "circuit_qasm"
DEFAULT_ORDERING_CONVENTION = "qiskit_little_endian"
DEFAULT_ENDIANNESS = "little"

#: The v3-specific joins this support module adds on top of the generic production ones.
MANIFEST_JOINS_VERIFIED = (
    "execution_attempt_id",
    "result_manifest_digest",
    "circuit_digest",
    "observed_shots",
    "execution_configuration_settings",
)


def circuit_artifact_revisions(
    *, artifact_revision_id: str, circuit_digest: str
) -> dict[str, Any]:
    """Minimal artifact-revision table that v3 can bind an exact circuit lineage to."""
    return {
        bounded_text(artifact_revision_id, category="manifest_join_artifact_revision_invalid"): {
            "logical_role": CIRCUIT_LOGICAL_ROLE,
            "content_digest": digest_text(
                circuit_digest, category="manifest_join_artifact_revision_invalid"
            ),
        }
    }


def build_strict_result_manifest_payload(
    *,
    receipt: Mapping[str, Any],
    counts: Mapping[str, int],
    circuit_artifact_revision_id: str,
    circuit_digest: str,
    backend_or_sampler: str,
    interface: str,
    execution_configuration_reference: str,
    bit_order: Sequence[str],
    register_order: Sequence[str],
    producer_kind: str = "native_local_executor",
    capture_kind: str = "executor_result_object",
    ordering_convention: str = DEFAULT_ORDERING_CONVENTION,
    endianness: str = DEFAULT_ENDIANNESS,
) -> dict[str, Any]:
    """Project a completed sibling receipt plus bounded counts into a v3 payload.

    The projection is mechanical: it adds no claim the receipt does not already carry,
    and the provenance kinds are sampling kinds so v3's sampled-shots provenance
    contradiction check passes honestly.
    """
    if receipt.get("status") != STATUS_COMPLETED:
        raise FocusedLoopError("manifest_join_receipt_not_enrollable")
    settings = strict_mapping(
        receipt.get("actual_settings"),
        required=("shots", "noise", "seed"),
        category="manifest_join_receipt_invalid",
    )
    observed_shots = sum(int(value) for value in counts.values())
    return {
        "schema_id": STRICT_RESULT_MANIFEST_SCHEMA_ID,
        "schema_version": STRICT_RESULT_MANIFEST_SCHEMA_VERSION,
        "manifestation": "exact_result",
        "counts": {str(key): int(value) for key, value in counts.items()},
        "requested_shots": observed_shots,
        "observed_shots": observed_shots,
        "circuit_lineage": {
            "status": "exact",
            "artifact_revision_id": circuit_artifact_revision_id,
            "content_digest": circuit_digest,
        },
        "source_lineage": {"status": "not_supplied"},
        "execution_configuration": {
            "status": "exact",
            "reference": execution_configuration_reference,
            "settings": {
                "backend": backend_or_sampler,
                "method": receipt.get("actual_method"),
                "noise": settings["noise"],
                "seed": settings["seed"],
                "shots": settings["shots"],
            },
        },
        "execution_method": {
            "kind": "sampled_shots",
            "interface": interface,
            "backend_or_sampler": backend_or_sampler,
        },
        "execution_observation": {
            "status": "client_reported_completed",
            "external_execution_attempt_count": 1,
            "dependency_installation_performed": False,
            "environment_mutated": False,
            "qcoder_independently_verified_execution": False,
        },
        "execution_attempt_id": receipt.get("attempt_identity"),
        "producer_provenance": {
            "kind": producer_kind,
            "method": interface,
            "identity": receipt.get("plan_digest"),
        },
        "capture_provenance": {
            "kind": capture_kind,
            "method": interface,
            "identity": receipt.get("attempt_identity"),
        },
        "bit_register_ordering": {
            "status": "known",
            "convention": ordering_convention,
            "endianness": endianness,
            "bit_order": list(bit_order),
            "register_order": list(register_order),
        },
        "warnings": [],
        "explicit_missingness": [],
        "limitations": [MANIFEST_LIMITATION_VERIFICATION_SCOPE],
        "non_claims": [MANIFEST_NON_CLAIM_INDEPENDENT_VERIFICATION],
        "raw_terminal_or_chat_evidence_used": False,
        "workspace_or_filename_lineage_inferred": False,
    }


def normalize_through_strict_manifest_v3(
    payload: Mapping[str, Any],
    *,
    artifact_revisions: Mapping[str, Any],
    expected_circuit_lineage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the REAL v3 validator, translating its rejection into a bounded category.

    The validator is called exactly as accepted. Its rejection category is preserved on
    the raised error so a v3 rejection stays a v3 rejection.
    """
    try:
        return normalize_strict_result_manifest(
            payload,
            artifact_revisions=artifact_revisions,
            expected_circuit_lineage=expected_circuit_lineage,
        )
    except StrictResultManifestError as exc:
        error = FocusedLoopError("manifest_join_strict_manifest_rejected")
        error.strict_manifest_category = exc.category
        raise error from exc


def join_receipt_to_strict_result_manifest(
    *,
    plan: Mapping[str, Any],
    authority: Mapping[str, Any],
    receipt: Mapping[str, Any],
    manifest_payload: Mapping[str, Any],
    artifact_revisions: Mapping[str, Any],
    planned_runtime_versions: Mapping[str, Any],
    expected_circuit_lineage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Prove one sibling receipt and one real v3 manifest describe one attempt."""
    joined = join_attempt_records(
        plan=plan,
        authority=authority,
        receipt=receipt,
        planned_runtime_versions=planned_runtime_versions,
    )
    validated_plan = joined["plan"]

    manifest = normalize_through_strict_manifest_v3(
        manifest_payload,
        artifact_revisions=artifact_revisions,
        expected_circuit_lineage=expected_circuit_lineage,
    )
    if manifest["execution_attempt_id"] != receipt["attempt_identity"]:
        raise FocusedLoopError("manifest_join_execution_attempt_id_mismatch")
    if manifest["circuit_lineage"]["content_digest"] != validated_plan["circuit_digest"]:
        raise FocusedLoopError("manifest_join_circuit_digest_mismatch")
    if manifest["execution_method"]["kind"] != "sampled_shots":
        raise FocusedLoopError("manifest_join_execution_method_unsupported")
    if manifest["observed_shots"] != validated_plan["settings"]["shots"]:
        raise FocusedLoopError("manifest_join_shots_mismatch")
    configuration = manifest["execution_configuration"]["settings"]
    if (
        configuration.get("method") != validated_plan["method_id"]
        or configuration.get("shots") != validated_plan["settings"]["shots"]
        or configuration.get("noise") != validated_plan["settings"]["noise"]
        or configuration.get("seed") != validated_plan["settings"]["seed"]
    ):
        raise FocusedLoopError("manifest_join_execution_configuration_mismatch")
    if receipt["result_manifest_digest"] != manifest["manifest_digest"]:
        raise FocusedLoopError("manifest_join_result_manifest_digest_mismatch")

    return {
        "manifest": manifest,
        "manifest_digest": manifest["manifest_digest"],
        "outcome_digest": manifest["outcome_digest"],
        "plan_digest": joined["plan_digest"],
        "authority_digest": joined["authority_digest"],
        "attempt_identity": joined["attempt_identity"],
        "receipt_digest": joined["receipt_digest"],
        "deviation": joined["deviation"],
        "joins_verified": tuple(joined["joins_verified"]) + MANIFEST_JOINS_VERIFIED,
        "independent_verification_claimed": False,
        "plan_match_verified_in_process": joined["plan_match_verified_in_process"],
    }


__all__ = [
    "CIRCUIT_LOGICAL_ROLE",
    "MANIFEST_JOINS_VERIFIED",
    "MANIFEST_LIMITATION_VERIFICATION_SCOPE",
    "MANIFEST_NON_CLAIM_INDEPENDENT_VERIFICATION",
    "STRICT_RESULT_MANIFEST_SCHEMA_ID",
    "STRICT_RESULT_MANIFEST_SCHEMA_VERSION",
    "build_strict_result_manifest_payload",
    "circuit_artifact_revisions",
    "join_receipt_to_strict_result_manifest",
    "normalize_through_strict_manifest_v3",
]
