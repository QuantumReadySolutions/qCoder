"""Compact stage-specific projection of canonical Current Loop state."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from typing import Any, Mapping

from qcoder.current_loop_result_manifest import result_manifest_contract_snapshot


CURRENT_STEP_CONTRACT_SCHEMA_ID = "qcoder.current_loop.current_step_contract.v10"
CURRENT_STEP_CONTRACT_SCHEMA_VERSION = 10
COMPLETE_CURRENT_STEP_OPERATION = "complete_current_step"


def quiet_customer_visibility_contract() -> dict[str, Any]:
    """Return the semantic visibility policy for one clean Current Step."""

    return {
        "normal_success": "internal_transaction_silent",
        "progress": "none_or_task_level_only",
        "intermediate_customer_message_permitted": False,
        "final_response": "concise_task_outcome_only",
        "internal_mechanics_customer_visible": False,
        "normal_success_event_policy": {
            "before_begin": "no_customer_message",
            "before_native_action": "none_or_one_task_level_progress_message",
            "between_native_action_and_completion": "no_customer_message",
            "after_validated_completion": "one_concise_task_outcome",
        },
        "prohibited_normal_success_meaning": [
            "announce_qcoder_activation_or_loop_transition",
            "explain_current_step_contract_or_bounded_authority",
            "announce_typed_completion_or_artifact_registration",
            "explain_receipts_state_revisions_hooks_or_evidence_bookkeeping",
        ],
        "native_permission_explanation": {
            "maximum_customer_messages": 1,
            "only_when_native_client_actually_requires_permission": True,
            "action_specific": True,
            "qcoder_mechanics_explanation": False,
        },
        "surface_when": [
            "blocking_failure",
            "ambiguity",
            "bounded_recovery",
            "meaningful_authority_broadening",
            "customer_requested_qcoder_help",
        ],
    }


def quiet_customer_visibility_projection() -> dict[str, Any]:
    """Return the bounded Current Step projection of the visibility policy."""

    return {
        "policy": "quiet_current_step_v2",
        "events": "optional_task_progress_then_task_outcome",
        "mechanics": "silent",
        "native_permission": "only_if_required_once",
    }


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def _digest_text(value: object) -> str:
    return sha256(str(value).encode("utf-8")).hexdigest()


def _evidence_references(state: Mapping[str, Any], *, active_role: str) -> list[dict[str, Any]]:
    """Project only canonical evidence needed by the current artifact stage."""

    references: list[dict[str, Any]] = []
    baseline = state.get("saved_artifacts", {}).get("request_baseline")
    if active_role == "source" and isinstance(baseline, Mapping):
        references.append(
            {
                "role": "request_baseline",
                "identity": baseline.get("artifact_reference"),
                "digest": baseline.get("artifact_digest"),
            }
        )
    registry = state.get("evidence_registry")
    if not isinstance(registry, Mapping):
        return references
    heads = registry.get("role_heads")
    revisions = registry.get("artifact_revisions")
    if not isinstance(heads, Mapping) or not isinstance(revisions, Mapping):
        return references
    relevant_roles = {
        "source": set(),
        "circuit_qasm": {"source"},
        "results": {"source", "circuit_qasm"},
    }.get(active_role, set())
    for role, revision_id in sorted(heads.items()):
        if str(role) not in relevant_roles:
            continue
        revision = revisions.get(revision_id)
        if isinstance(revision, Mapping):
            references.append(
                {
                    "role": str(role),
                    "identity": str(revision_id),
                    "digest": revision.get("content_digest"),
                }
            )
    return references


def derive_current_step_contract(state: Mapping[str, Any]) -> dict[str, Any]:
    """Derive the only assistant-facing current-stage contract from canonical state."""

    coordinator = state.get("coordinator")
    if not isinstance(coordinator, Mapping):
        raise ValueError("current_step_contract_coordinator_required")
    semantics = coordinator.get("current_request_semantics")
    if not isinstance(semantics, Mapping):
        raise ValueError("current_step_contract_semantics_required")
    handle = coordinator.get("current_step_bounded_action_expectation_id")
    receipt = state.get("operation_receipts", {}).get(handle) if isinstance(handle, str) else None
    if not isinstance(receipt, Mapping) or receipt.get("status") != "issued":
        raise ValueError("current_step_contract_active_action_required")
    binding = receipt.get("authority_binding")
    if not isinstance(binding, Mapping):
        raise ValueError("current_step_contract_action_binding_required")
    role = str(binding.get("authorized_artifact_role"))
    operation = str(binding.get("requested_operation"))
    prohibited_roles = list(binding.get("prohibited_artifact_roles", ()))
    prohibited_actions = [
        value
        for value in ("circuit_qasm", "execution", "results", "evidence_review")
        if value != role and value not in prohibited_roles
    ]
    prohibited_actions = sorted(set(prohibited_roles + prohibited_actions))
    target = binding.get("exact_artifact_target")
    if not isinstance(target, Mapping):
        raise ValueError("current_step_contract_exact_artifact_target_required")
    pending = coordinator.get("pending_completion_checkpoint")
    durable_pending = isinstance(pending, Mapping)
    preexisting_satisfaction = bool(
        semantics.get("preexisting_exact_source_satisfaction_requested")
    )
    contract = {
        "schema_id": CURRENT_STEP_CONTRACT_SCHEMA_ID,
        "schema_version": CURRENT_STEP_CONTRACT_SCHEMA_VERSION,
        "binding": {
            "loop_identity_sha256": _digest_text(state.get("loop_ref")),
            "workspace_identity_sha256": _digest_text(state.get("workspace_root")),
            "request_identity_sha256": semantics.get("original_message_utf8_sha256"),
            "state_revision": state.get("state_revision"),
            "stage": coordinator.get("current_step_substage") or role,
            "fresh_until_host_monotonic_seconds": receipt.get("expires_at"),
            "freshness_clock": "host_monotonic_same_boot",
        },
        "current_customer_goal": semantics.get("exact_original_message"),
        "authoritative_evidence_references": _evidence_references(state, active_role=role),
        "permitted_native_action": {
            "current_action_handle": handle,
            "operation": operation,
            "artifact_role": role,
            "cardinality": "exactly_one",
            "exact_artifact_target": {
                "workspace_relative_path": target.get("workspace_relative_path"),
                "selection": (
                    "registered_current_role_head_no_discovery"
                    if target.get("binding_mode") == "registered_current_role_head_exact_target"
                    else "bound_before_action_no_discovery"
                    if isinstance(target.get("exact_path_sha256"), str)
                    else "legacy_completion_path_handoff"
                ),
                **(
                    {"replacement_target_model_selection_required": False}
                    if target.get("binding_mode") == "registered_current_role_head_exact_target"
                    else {}
                ),
            },
            **(
                {
                    "native_write_required": False,
                    "preexisting_exact_artifact_satisfaction": True,
                }
                if preexisting_satisfaction
                else {}
            ),
        },
        "prohibited_current_actions": prohibited_actions,
        "native_client_authority": {
            "owner": "native_client",
            "qcoder_grants_permission": False,
            "qcoder_infers_approval_click": False,
        },
        "completion": {
            "operation": COMPLETE_CURRENT_STEP_OPERATION,
            "required_arguments": (
                [] if durable_pending else ["current_action_handle", "artifact_path"]
            ),
            "canonical_arguments": {} if durable_pending else None,
            **(
                {"artifact_disposition_derived_by_qcoder": "pre_existing_exact_artifact"}
                if preexisting_satisfaction
                else {}
            ),
            "qcoder_resolves_bound_action_and_target": durable_pending,
            "artifact_path": target.get("workspace_relative_path"),
            "artifact_path_form": "workspace_relative_bound_target",
            "qcoder_computes_artifact_digest": True,
            "condition": "validated_exact_postcondition",
            "success_state": "complete_resumable",
            "pending_checkpoint": pending.get("checkpoint_digest") if durable_pending else None,
            "survives_later_turn_and_same_host_restart": durable_pending,
            "external_execution_rerun_permitted": False if durable_pending else None,
        },
        "customer_visibility": quiet_customer_visibility_projection(),
        "recovery": {
            "policy": "fail_closed",
            "mismatch": "retain_for_exact_retry",
            "duplicate": "idempotent_existing_completion",
            "clarification": semantics.get("customer_clarification"),
        },
        "privacy": {
            "raw_artifact_or_absolute_path_inline": False,
            "process_and_discard": True,
        },
    }
    if role == "results":
        external_execution_contract = {
            "execution_owner": "native_client",
            "runtime": "already_prepared_and_prevalidated",
            "dependency_installation_permitted": False,
            "environment_mutation_permitted": False,
            "external_execution_attempts": "exactly_one",
            "required_method": "sampled_shots",
            "analytic_probability_substitution_permitted": False,
            "missing_runtime_disposition": "surface_blocker_without_execution",
            "qcoder_executes_customer_code": False,
        }
        if durable_pending:
            external_execution_contract.update(
                {
                    "execution_attempt_identity": pending.get("execution_attempt_identity"),
                    "requested_shots": pending.get("requested_shots"),
                }
            )
        contract["permitted_native_action"]["external_execution_contract"] = (
            external_execution_contract
        )
        contract["completion"]["artifact_contract"] = {
            "required_format": "strict_result_manifest",
            "contract": result_manifest_contract_snapshot(),
            "transport": "exact_artifact_path",
            "current_step_contract_circuit_lineage_status_supported": True,
            "unknown_lineage_supported_as_non_current_evidence": True,
            "bare_counts_current_evidence_permitted": False,
            "client_reports_producer_method_backend_and_capture_provenance": True,
            "requested_and_observed_shots_required_to_agree": True,
            "qcoder_independently_verifies_external_execution": False,
            "routine_success_customer_outcome": "canonical_current_run_summary",
        }
    contract["contract_digest"] = sha256(_canonical_bytes(contract)).hexdigest()
    return contract


def validate_current_step_contract(
    contract: Mapping[str, Any], *, state: Mapping[str, Any]
) -> None:
    expected = derive_current_step_contract(state)
    if deepcopy(dict(contract)) != expected:
        raise ValueError("current_step_contract_mismatch")


def current_step_contract_snapshot() -> dict[str, Any]:
    return {
        "schema_id": CURRENT_STEP_CONTRACT_SCHEMA_ID,
        "schema_version": CURRENT_STEP_CONTRACT_SCHEMA_VERSION,
        "projection_source": "canonical_current_loop_state",
        "completion_operation": COMPLETE_CURRENT_STEP_OPERATION,
        "bounded_independent_of_artifact_size": True,
        "native_permission_owner": "native_client",
        "hooks_optional_accelerators": True,
        "exact_artifact_target_required": True,
        "preexisting_exact_source_satisfaction_without_write": True,
        "workspace_discovery_permitted": False,
        "external_execution_runtime_prepared_before_step": True,
        "dependency_installation_or_environment_mutation_authorized_by_step": False,
        "qcoder_external_execution_owner": False,
        "normal_success_customer_visibility": quiet_customer_visibility_contract(),
        "fail_closed": True,
    }


__all__ = [
    "COMPLETE_CURRENT_STEP_OPERATION",
    "CURRENT_STEP_CONTRACT_SCHEMA_ID",
    "CURRENT_STEP_CONTRACT_SCHEMA_VERSION",
    "current_step_contract_snapshot",
    "derive_current_step_contract",
    "quiet_customer_visibility_contract",
    "quiet_customer_visibility_projection",
    "validate_current_step_contract",
]
