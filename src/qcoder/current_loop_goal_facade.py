"""Private one-goal evidence facade for a bounded architecture experiment.

This module evaluates and reconciles one exact Run Evidence goal. It does not
execute customer code, write artifacts, discover files, or expose a CLI/MCP
operation.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
import json
from typing import Any

from qcoder.current_loop_evidence_reconciler import reconcile_current_evidence
from qcoder.current_loop_result_manifest import normalize_strict_result_manifest


GOAL_FACADE_SCHEMA_ID = "qcoder.current_loop.private_one_goal_facade.v1"


class GoalFacadeError(ValueError):
    pass


def _digest(value: object) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def evaluate_current_run_goal(
    *,
    state: Mapping[str, Any],
    requested_shots: int,
) -> dict[str, Any]:
    """Return one exact external-action boundary from canonical loop evidence."""

    if not isinstance(requested_shots, int) or requested_shots < 1:
        raise GoalFacadeError("goal_requested_shots_invalid")
    registry = state.get("evidence_registry")
    if not isinstance(registry, Mapping):
        raise GoalFacadeError("goal_evidence_registry_missing")
    heads = registry.get("role_heads")
    revisions = registry.get("artifact_revisions")
    if not isinstance(heads, Mapping) or not isinstance(revisions, Mapping):
        raise GoalFacadeError("goal_evidence_registry_invalid")
    circuit_id = heads.get("circuit_qasm")
    circuit = revisions.get(circuit_id) if isinstance(circuit_id, str) else None
    if not isinstance(circuit, Mapping):
        raise GoalFacadeError("goal_exact_circuit_required")
    source_id = heads.get("source")
    source = revisions.get(source_id) if isinstance(source_id, str) else None
    action = {
        "action_kind": "external_native_execution_and_result_capture",
        "native_execution_owner": "client_or_customer",
        "qcoder_executes_customer_code": False,
        "requested_shots": requested_shots,
        "exact_circuit": {
            "artifact_revision_id": circuit_id,
            "content_digest": circuit["content_digest"],
        },
        "exact_source": (
            {
                "artifact_revision_id": source_id,
                "content_digest": source["content_digest"],
            }
            if isinstance(source, Mapping)
            else None
        ),
        "completion_artifact_role": "results",
        "completion_contract_schema_id": "qcoder.current_loop.strict_result_manifest.v1",
        "rerun_on_uncertain_completion_permitted": False,
        "directory_or_repository_discovery_permitted": False,
    }
    action["bounded_action_handle"] = (
        "goal-action-"
        + _digest(
            {
                "loop_ref": state.get("loop_ref"),
                "state_revision": state.get("state_revision"),
                "action": action,
            }
        )[:32]
    )
    return {
        "schema_id": GOAL_FACADE_SCHEMA_ID,
        "goal": f"Establish current Run Evidence for {requested_shots:,} shots.",
        "state_revision": state.get("state_revision"),
        "current_evidence_references": {
            "source": source_id,
            "circuit_qasm": circuit_id,
        },
        "native_action_boundary": action,
        "eligible_pure_qcoder_followup": "validate_manifest_reconcile_and_project_run_summary",
        "model_constructs_qcoder_procedure": False,
        "public_operation_added": False,
        "public_cli_command_added": False,
    }


def reconcile_completed_goal(
    *,
    state: Mapping[str, Any],
    action: Mapping[str, Any],
    result_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one handed-off result and return pure reconciliation evidence."""

    registry = state.get("evidence_registry", {})
    revisions = registry.get("artifact_revisions", {})
    if not isinstance(revisions, Mapping):
        raise GoalFacadeError("goal_evidence_registry_invalid")
    expected = evaluate_current_run_goal(
        state=state,
        requested_shots=int(action.get("requested_shots", 0)),
    )["native_action_boundary"]
    if action.get("bounded_action_handle") != expected["bounded_action_handle"]:
        raise GoalFacadeError("goal_bounded_action_stale_or_mismatched")
    normalized = normalize_strict_result_manifest(
        result_manifest,
        artifact_revisions=revisions,
    )
    if normalized["observed_shots"] != action["requested_shots"]:
        raise GoalFacadeError("goal_result_shots_mismatch")
    result_revision_id = "artifact-revision-result-" + normalized["manifest_digest"][:24]
    combined = deepcopy(dict(revisions))
    combined[result_revision_id] = {
        "artifact_revision_id": result_revision_id,
        "logical_role": "results",
        "content_digest": normalized["manifest_digest"],
    }
    role_set = deepcopy(dict(registry.get("role_heads", {})))
    role_set["results"] = result_revision_id
    reconciliation = reconcile_current_evidence(
        role_revision_set=role_set,
        artifact_revisions=combined,
        normalized_result_manifest=normalized,
    )
    return {
        "schema_id": GOAL_FACADE_SCHEMA_ID,
        "bounded_action_handle": action["bounded_action_handle"],
        "result_manifest_digest": normalized["manifest_digest"],
        "reconciliation": reconciliation,
        "external_execution_rerun": False,
        "qcoder_computation_only": True,
        "raw_protected_transfer_performed": False,
    }


def goal_facade_contract_snapshot() -> dict[str, Any]:
    return {
        "schema_id": GOAL_FACADE_SCHEMA_ID,
        "one_semantic_goal_evaluation": True,
        "one_external_native_action_boundary": True,
        "one_exact_result_handoff": True,
        "eligible_pure_reconciliation": True,
        "general_task_runner": False,
        "arbitrary_execution_owned_by_qcoder": False,
        "public_cli_or_mcp_surface": False,
    }
