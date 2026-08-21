"""Durable, bounded completion checkpoints for external Current Step actions."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from typing import Any, Mapping

from qcoder.current_loop_event_receipts import (
    EventReceiptError,
    validate_operation_receipt_lifecycle,
)


PENDING_COMPLETION_CHECKPOINT_SCHEMA_ID = "qcoder.current_loop.pending_completion_checkpoint.v1"
PENDING_COMPLETION_CHECKPOINT_SCHEMA_VERSION = 1


class PendingCompletionError(ValueError):
    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return sha256(_canonical_bytes(value)).hexdigest()


def _identity(value: object) -> str:
    return sha256(str(value).encode("utf-8")).hexdigest()


def build_pending_completion_checkpoint(
    *,
    state: Mapping[str, Any],
    coordinator: Mapping[str, Any],
    receipt: Mapping[str, Any],
    current_step_contract_schema_id: str,
    current_step_contract_schema_version: int,
) -> dict[str, Any]:
    """Project one durable completion checkpoint from canonical state."""

    authority = receipt.get("authority_binding")
    semantics = coordinator.get("current_request_semantics")
    baseline = state.get("saved_artifacts", {}).get("request_baseline")
    if not isinstance(authority, Mapping) or not isinstance(semantics, Mapping):
        raise PendingCompletionError("pending_completion_binding_invalid")
    if not isinstance(baseline, Mapping):
        raise PendingCompletionError("pending_completion_request_baseline_missing")
    target = authority.get("exact_artifact_target")
    if (
        not isinstance(target, Mapping)
        or not isinstance(target.get("workspace_relative_path"), str)
        or not target["workspace_relative_path"]
        or not isinstance(target.get("exact_path_sha256"), str)
    ):
        raise PendingCompletionError("pending_completion_exact_target_required")
    role = authority.get("authorized_artifact_role")
    if role not in {"source", "circuit_qasm", "results"}:
        raise PendingCompletionError("pending_completion_role_invalid")
    action_handle = receipt.get("receipt_id")
    action_digest = receipt.get("receipt_digest")
    if not isinstance(action_handle, str) or not isinstance(action_digest, str):
        raise PendingCompletionError("pending_completion_action_invalid")
    requested_shots = authority.get("requested_shots") if role == "results" else None
    execution_attempt_identity = (
        authority.get("execution_attempt_identity") if role == "results" else None
    )
    if role == "results" and (
        not isinstance(execution_attempt_identity, str) or not execution_attempt_identity
    ):
        raise PendingCompletionError("pending_completion_execution_attempt_missing")
    checkpoint = {
        "schema_id": PENDING_COMPLETION_CHECKPOINT_SCHEMA_ID,
        "schema_version": PENDING_COMPLETION_CHECKPOINT_SCHEMA_VERSION,
        "status": "pending",
        "loop_identity_sha256": _identity(state.get("loop_ref")),
        "workspace_identity_sha256": _identity(state.get("workspace_root")),
        "request_baseline": {
            "artifact_reference": baseline.get("artifact_reference"),
            "artifact_digest": baseline.get("artifact_digest"),
        },
        "request_identity_sha256": authority.get("current_request_identity_sha256"),
        "request_semantics_digest": authority.get("current_request_semantics_digest"),
        "authority_state_revision": receipt.get("issued_state_revision"),
        "current_loop_contract_revision": receipt.get("issued_contract_revision"),
        "current_step_contract": {
            "schema_id": current_step_contract_schema_id,
            "schema_version": current_step_contract_schema_version,
        },
        "bounded_action": {
            "handle": action_handle,
            "digest": action_digest,
            "ceiling_digest": authority.get("current_step_ceiling_digest"),
            "single_use": True,
        },
        "artifact": {
            "role": role,
            "cardinality": "exactly_one",
            "workspace_relative_target": target.get("workspace_relative_path"),
            "exact_path_sha256": target.get("exact_path_sha256"),
        },
        "lineage": deepcopy(dict(authority.get("eligible_input_artifacts", {}))),
        "execution_attempt_identity": execution_attempt_identity,
        "requested_shots": requested_shots,
        "expected_result_manifest_schema": (
            "qcoder.current_loop.strict_result_manifest.v3" if role == "results" else None
        ),
        "completion_operation": "complete_current_step",
        "canonical_completion_arguments": {},
        "model_reproduces_qcoder_owned_identity": False,
        "external_execution_rerun_permitted": False,
        "expires_at_host_monotonic_seconds": receipt.get("expires_at"),
        "freshness_clock": "host_monotonic_same_boot",
        "stale_after_authoritative_state_revision_change": True,
        "mcp_server_restart_safe_on_same_host_boot": True,
        "workspace_discovery_permitted": False,
        "state_or_help_archaeology_permitted": False,
    }
    checkpoint["checkpoint_digest"] = _digest(checkpoint)
    return checkpoint


def validate_pending_completion_checkpoint(
    *,
    state: Mapping[str, Any],
    coordinator: Mapping[str, Any],
    current_time: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate and return the unique live pending checkpoint and receipt."""

    checkpoint = coordinator.get("pending_completion_checkpoint")
    if not isinstance(checkpoint, Mapping):
        raise PendingCompletionError("pending_completion_checkpoint_missing")
    value = deepcopy(dict(checkpoint))
    supplied_digest = value.pop("checkpoint_digest", None)
    if (
        checkpoint.get("schema_id") != PENDING_COMPLETION_CHECKPOINT_SCHEMA_ID
        or checkpoint.get("schema_version") != PENDING_COMPLETION_CHECKPOINT_SCHEMA_VERSION
        or checkpoint.get("status") != "pending"
        or supplied_digest != _digest(value)
    ):
        raise PendingCompletionError("pending_completion_checkpoint_invalid")
    action = checkpoint.get("bounded_action")
    artifact = checkpoint.get("artifact")
    baseline = checkpoint.get("request_baseline")
    semantics = coordinator.get("current_request_semantics")
    if not all(isinstance(item, Mapping) for item in (action, artifact, baseline, semantics)):
        raise PendingCompletionError("pending_completion_checkpoint_invalid")
    action_handle = action.get("handle")
    receipts = state.get("operation_receipts")
    if not isinstance(receipts, Mapping) or not isinstance(action_handle, str):
        raise PendingCompletionError("pending_completion_checkpoint_invalid")
    issued = [
        item
        for item in receipts.values()
        if isinstance(item, Mapping)
        and item.get("receipt_kind") == "qcoder_bounded_action_expectation"
        and item.get("status") == "issued"
    ]
    if len(issued) != 1:
        raise PendingCompletionError(
            "pending_completion_checkpoint_missing"
            if not issued
            else "pending_completion_checkpoint_ambiguous"
        )
    receipt = receipts.get(action_handle)
    if (
        not isinstance(receipt, Mapping)
        or receipt.get("receipt_id") != issued[0].get("receipt_id")
        or receipt.get("receipt_digest") != issued[0].get("receipt_digest")
    ):
        raise PendingCompletionError("pending_completion_checkpoint_action_mismatch")
    try:
        validate_operation_receipt_lifecycle(receipt, current_time=current_time)
    except EventReceiptError as exc:
        raise PendingCompletionError(exc.category) from exc
    authority = receipt.get("authority_binding")
    target = authority.get("exact_artifact_target") if isinstance(authority, Mapping) else None
    saved_baseline = state.get("saved_artifacts", {}).get("request_baseline")
    checks = {
        "loop_identity_sha256": _identity(state.get("loop_ref")),
        "workspace_identity_sha256": _identity(state.get("workspace_root")),
        "request_identity_sha256": semantics.get("original_message_utf8_sha256"),
        "request_semantics_digest": semantics.get("semantics_digest"),
        "authority_state_revision": state.get("state_revision"),
        "current_loop_contract_revision": state.get("current_loop_contract", {}).get(
            "contract_revision"
        ),
    }
    if any(checkpoint.get(key) != expected for key, expected in checks.items()):
        raise PendingCompletionError("pending_completion_checkpoint_stale")
    if (
        coordinator.get("current_step_status") != "awaiting_external_client_action"
        or coordinator.get("current_step_bounded_action_expectation_id") != action_handle
        or coordinator.get("current_step_bounded_action_expectation_digest") != action.get("digest")
        or receipt.get("receipt_digest") != action.get("digest")
        or not isinstance(saved_baseline, Mapping)
        or baseline.get("artifact_reference") != saved_baseline.get("artifact_reference")
        or baseline.get("artifact_digest") != saved_baseline.get("artifact_digest")
        or not isinstance(authority, Mapping)
        or not isinstance(target, Mapping)
        or artifact.get("role") != authority.get("authorized_artifact_role")
        or artifact.get("cardinality") != authority.get("authorized_artifact_cardinality")
        or artifact.get("workspace_relative_target") != target.get("workspace_relative_path")
        or artifact.get("exact_path_sha256") != target.get("exact_path_sha256")
        or checkpoint.get("lineage") != authority.get("eligible_input_artifacts", {})
    ):
        raise PendingCompletionError("pending_completion_checkpoint_binding_mismatch")
    if checkpoint.get("expires_at_host_monotonic_seconds") != receipt.get("expires_at"):
        raise PendingCompletionError("pending_completion_checkpoint_expiry_mismatch")
    return deepcopy(dict(checkpoint)), deepcopy(dict(receipt))


def completed_checkpoint(
    checkpoint: Mapping[str, Any],
    *,
    completed_state_revision: int,
    consumed_receipt_digest: str | None,
) -> dict[str, Any]:
    result = deepcopy(dict(checkpoint))
    result.pop("checkpoint_digest", None)
    result.update(
        {
            "status": "completed",
            "completed_state_revision": completed_state_revision,
            "consumed_receipt_digest": consumed_receipt_digest,
        }
    )
    result["checkpoint_digest"] = _digest(result)
    return result


__all__ = [
    "PENDING_COMPLETION_CHECKPOINT_SCHEMA_ID",
    "PENDING_COMPLETION_CHECKPOINT_SCHEMA_VERSION",
    "PendingCompletionError",
    "build_pending_completion_checkpoint",
    "completed_checkpoint",
    "validate_pending_completion_checkpoint",
]
