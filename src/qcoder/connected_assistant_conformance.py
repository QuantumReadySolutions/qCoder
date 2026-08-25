"""Client-neutral source contract for qCoder's existing connected workflow.

This module is inert contract and test architecture. It does not select a
client, launch a client, implement another workflow engine, or make a public
compatibility claim.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from hashlib import sha256
from typing import Any

from qcoder.algorithm_intent_recovery import build_atomic_clarification_continuation

CLIENT_CONFORMANCE_CONTRACT_SCHEMA_ID = "qcoder.connected_assistant.client_neutral_conformance.v1"
CLIENT_CONFORMANCE_CONTRACT_SCHEMA_VERSION = 1
CLIENT_CONFORMANCE_PROFILE_SCHEMA_ID = "qcoder.connected_assistant.conformance_profile.v1"
CLIENT_CONFORMANCE_PROFILE_SCHEMA_VERSION = 1
NAMED_WORKFLOW_COMPLETION_SCHEMA_ID = "qcoder.connected_assistant.named_workflow_completion.v1"
NAMED_WORKFLOW_COMPLETION_SCHEMA_VERSION = 1
RETENTION_EVIDENCE_SCHEMA_ID = "qcoder.connected_assistant.retention_evidence.v1"
RETENTION_EVIDENCE_SCHEMA_VERSION = 1

NON_TERMINAL_PREPARATORY = "NON_TERMINAL_PREPARATORY"
CUSTOMER_TERMINAL_OUTCOME = "CUSTOMER_TERMINAL_OUTCOME"
GENUINE_BLOCKER = "GENUINE_BLOCKER"
CUSTOMER_AUTHORITY_OR_DECISION_BOUNDARY = "CUSTOMER_AUTHORITY_OR_DECISION_BOUNDARY"

_EVIDENCE_REVIEW_WORKFLOW = {
    "workflow_name": "Evidence Review",
    "preparatory_states": [
        {
            "tool_name": "get_guided_evidence_context",
            "status_field": "context_status",
            "status_value": "assistant_context_ready",
            "classification": NON_TERMINAL_PREPARATORY,
            "continue_with_tool": "create_result_review_context_card",
        }
    ],
    "customer_terminal_outcomes": [
        {
            "tool_name": "create_result_review_context_card",
            "status_field": "context_status",
            "status_value": "result_review_context_card_ready",
            "classification": CUSTOMER_TERMINAL_OUTCOME,
        }
    ],
    "maximum_automatic_continuations": 1,
}
_ALGORITHM_BLUEPRINT_WORKFLOW = {
    "workflow_name": "Algorithm Blueprint / Generation Context",
    "preparatory_states": [
        {
            "tool_name": "create_algorithm_intent_card",
            "status_field": "context_status",
            "status_value": "algorithm_intent_card_ready",
            "classification": NON_TERMINAL_PREPARATORY,
            "continue_with_tool": "create_implementation_blueprint",
        },
        {
            "tool_name": "create_implementation_blueprint",
            "status_field": "context_status",
            "status_value": "implementation_blueprint_ready",
            "classification": NON_TERMINAL_PREPARATORY,
            "continue_with_tool": "create_generation_context_pack",
        },
    ],
    "customer_terminal_outcomes": [
        {
            "tool_name": "create_generation_context_pack",
            "status_field": "context_status",
            "status_value": "generation_context_pack_ready",
            "classification": CUSTOMER_TERMINAL_OUTCOME,
        }
    ],
    "maximum_automatic_continuations": 2,
}
_NAMED_WORKFLOWS = {
    "Evidence Review": _EVIDENCE_REVIEW_WORKFLOW,
    "Algorithm Blueprint / Generation Context": _ALGORITHM_BLUEPRINT_WORKFLOW,
}

_SHARED_ASSERTIONS = (
    "mcp_initialization",
    "exact_twelve_tool_discovery",
    "fresh_loop_activation",
    "canonical_structured_intent_first_submission",
    "original_request_and_provenance_preserved",
    "native_permission_separation",
    "bounded_write_and_run_authority",
    "pure_status_while_receipt_outstanding",
    "direct_registration_after_status",
    "current_evidence_snapshot",
    "current_run_summary",
    "same_loop_iteration",
    "distinct_retained_prior_evidence",
    "one_call_help",
    "truthful_authority_and_next_actions",
    "direct_completion",
    "named_workflow_completion",
    "clarification_atomic_continuation_available",
    "clarification_recovery_exact_card_revision_binding",
    "clarification_recovery_bounded_correction",
    "clarification_recovery_stale_cross_card_refusal",
    "clarification_recovery_safe_forbidden_diagnostic",
    "clarification_recovery_no_raw_value_echo",
    "project_files_preserved",
    "no_cross_loop_carryover",
)


def _digest(value: object) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def named_workflow_completion_contract(tool_inventory: Sequence[str]) -> dict[str, Any]:
    """Describe shared terminality using existing tool-result vocabulary."""

    tools = tuple(str(name) for name in tool_inventory)
    required_tools = {
        state["tool_name"]
        for workflow in _NAMED_WORKFLOWS.values()
        for category in ("preparatory_states", "customer_terminal_outcomes")
        for state in workflow[category]
    }
    required_tools.update(
        state["continue_with_tool"]
        for workflow in _NAMED_WORKFLOWS.values()
        for state in workflow["preparatory_states"]
    )
    if not required_tools.issubset(tools):
        raise ValueError("named_workflow_completion_tool_inventory_invalid")
    payload: dict[str, Any] = {
        "schema_id": NAMED_WORKFLOW_COMPLETION_SCHEMA_ID,
        "schema_version": NAMED_WORKFLOW_COMPLETION_SCHEMA_VERSION,
        "classifications": [
            NON_TERMINAL_PREPARATORY,
            CUSTOMER_TERMINAL_OUTCOME,
            GENUINE_BLOCKER,
            CUSTOMER_AUTHORITY_OR_DECISION_BOUNDARY,
        ],
        "canonical_status_source": "structured_tool_result",
        "workflow_selection_source": "customer_named_workflow",
        "preparatory_success_is_completion": False,
        "routine_continuation_customer_interaction_required": False,
        "automatic_continuation_scope": "already_selected_named_workflow_only",
        "stop_on_genuine_blocker": True,
        "stop_on_customer_authority_or_decision_boundary": True,
        "stop_on_unsupported_state": True,
        "customer_authority_may_be_inferred": False,
        "artifact_scope_may_be_broadened": False,
        "repository_discovery_permitted": False,
        "neighboring_file_access_permitted": False,
        "hidden_file_selection_permitted": False,
        "workflows": deepcopy(list(_NAMED_WORKFLOWS.values())),
    }
    payload["contract_digest"] = _digest(payload)
    return payload


def retention_evidence_contract() -> dict[str, Any]:
    """Define the canonical structured process-and-discard evidence semantic."""

    payload: dict[str, Any] = {
        "schema_id": RETENTION_EVIDENCE_SCHEMA_ID,
        "schema_version": RETENTION_EVIDENCE_SCHEMA_VERSION,
        "canonical_field": "retention",
        "canonical_value": "process_and_discard",
        "meaning": "no_customer_artifact_retained_for_this_operation",
        "literal_empty_retained_artifacts_required": False,
        "literal_empty_retained_artifacts_sufficient_when_present": True,
        "exact_operation_identity_required": True,
        "free_form_prose_sufficient": False,
        "absent_semantic_state_sufficient": False,
        "ambiguous_semantic_state_sufficient": False,
        "contradictory_semantic_state_sufficient": False,
    }
    payload["contract_digest"] = _digest(payload)
    return payload


def _result_is_success(result: Mapping[str, Any]) -> bool:
    status = result.get("adapter_status_category") or result.get("status_category")
    return result.get("ok") is True or status == "success_2xx"


def _result_requires_customer_authority(result: Mapping[str, Any]) -> bool:
    intent_card = result.get("algorithm_intent_card")
    return (
        isinstance(result.get("required_authority_input"), Mapping)
        or bool(result.get("awaiting_confirmation_fields"))
        or result.get("approval_required") is True
        or result.get("requires_explicit_customer_confirmation") is True
        or result.get("proposal_state") == "unconfirmed"
        or (
            isinstance(intent_card, Mapping)
            and intent_card.get("confirmation_state") in ("proposed", "needs_clarification")
        )
    )


def _clarification_continuation_is_exact(result: Mapping[str, Any]) -> bool:
    card = result.get("algorithm_intent_card")
    continuation = result.get("clarification_continuation")
    if not isinstance(card, Mapping) or card.get("confirmation_state") != "needs_clarification":
        return True
    if not isinstance(continuation, Mapping):
        return False
    try:
        return dict(continuation) == build_atomic_clarification_continuation(card)
    except ValueError:
        return False


def evaluate_named_workflow_result(
    *,
    workflow_name: str,
    tool_name: str,
    structured_result: Mapping[str, Any],
    prior_tool_names: Sequence[str] = (),
) -> dict[str, Any]:
    """Classify one structured result and return a bounded same-workflow continuation."""

    workflow = _NAMED_WORKFLOWS.get(workflow_name)
    if workflow is None:
        raise ValueError("named_workflow_unsupported")
    prepared = tuple(str(name) for name in prior_tool_names)
    allowed_tools = {
        state["tool_name"]
        for category in ("preparatory_states", "customer_terminal_outcomes")
        for state in workflow[category]
    }
    base: dict[str, Any] = {
        "workflow_name": workflow_name,
        "tool_name": tool_name,
        "next_tool_name": None,
        "automatic_continuation_allowed": False,
        "customer_interaction_required": False,
    }
    if structured_result.get("tool_name") != tool_name:
        return {
            **base,
            "classification": GENUINE_BLOCKER,
            "stop_reason": "structured_result_operation_identity_mismatch",
        }
    if tool_name not in allowed_tools:
        return {
            **base,
            "classification": GENUINE_BLOCKER,
            "stop_reason": "unrelated_workflow_operation",
        }
    if not _result_is_success(structured_result):
        return {
            **base,
            "classification": GENUINE_BLOCKER,
            "stop_reason": "qcoder_non_success_or_unsupported_state",
        }
    if not _clarification_continuation_is_exact(structured_result):
        return {
            **base,
            "classification": GENUINE_BLOCKER,
            "stop_reason": "clarification_continuation_missing_or_mismatched",
        }
    if _result_requires_customer_authority(structured_result):
        return {
            **base,
            "classification": CUSTOMER_AUTHORITY_OR_DECISION_BOUNDARY,
            "stop_reason": "canonical_customer_authority_required",
            "customer_interaction_required": True,
            "next_tool_name": (
                "create_algorithm_intent_card"
                if tool_name == "create_algorithm_intent_card"
                else None
            ),
            "clarification_continuation_available": (tool_name == "create_algorithm_intent_card"),
        }
    for state in workflow["customer_terminal_outcomes"]:
        if (
            tool_name == state["tool_name"]
            and structured_result.get(state["status_field"]) == state["status_value"]
        ):
            return {
                **base,
                "classification": CUSTOMER_TERMINAL_OUTCOME,
                "stop_reason": "named_customer_outcome_ready",
            }
    for state in workflow["preparatory_states"]:
        if (
            tool_name == state["tool_name"]
            and structured_result.get(state["status_field"]) == state["status_value"]
        ):
            if (
                tool_name in prepared
                or len(prepared) >= workflow["maximum_automatic_continuations"]
            ):
                return {
                    **base,
                    "classification": GENUINE_BLOCKER,
                    "stop_reason": "automatic_continuation_loop_or_budget_exhausted",
                }
            return {
                **base,
                "classification": NON_TERMINAL_PREPARATORY,
                "next_tool_name": state["continue_with_tool"],
                "automatic_continuation_allowed": True,
                "stop_reason": None,
            }
    return {
        **base,
        "classification": GENUINE_BLOCKER,
        "stop_reason": "qcoder_non_success_or_unsupported_state",
    }


def process_and_discard_retention_satisfied(
    *,
    structured_evidence: Mapping[str, Any],
    expected_tool_name: str,
) -> bool:
    """Fail closed unless exact-operation structured evidence proves no retention."""

    if not expected_tool_name or structured_evidence.get("tool_name") != expected_tool_name:
        return False
    if structured_evidence.get("retention") != "process_and_discard":
        return False
    if (
        "retained_artifacts" in structured_evidence
        and structured_evidence.get("retained_artifacts") != []
    ):
        return False
    if (
        "retained_artifact_count" in structured_evidence
        and structured_evidence.get("retained_artifact_count") != 0
    ):
        return False
    if (
        "process_and_discard" in structured_evidence
        and structured_evidence.get("process_and_discard") is not True
    ):
        return False
    if structured_evidence.get("artifact_retained") is True:
        return False
    if structured_evidence.get("customer_artifact_retained") is True:
        return False
    if "retained_artifacts_empty" in structured_evidence and structured_evidence.get(
        "retained_artifacts_empty"
    ) not in (True, "yes"):
        return False
    if (
        "retained_artifacts_empty_or_absent" in structured_evidence
        and structured_evidence.get("retained_artifacts_empty_or_absent") is not True
    ):
        return False
    if (
        "retention_category" in structured_evidence
        and structured_evidence.get("retention_category") != "process_and_discard"
    ):
        return False
    nested = structured_evidence.get("retention_state")
    if nested is not None:
        if not isinstance(nested, Mapping) or nested.get("state") != "process_and_discard":
            return False
        if "retained_artifacts" in nested and nested.get("retained_artifacts") != []:
            return False
    return True


def client_neutral_conformance_contract(tool_inventory: Sequence[str]) -> dict[str, Any]:
    """Return the shared contract bound to the existing twelve tools."""

    tools = tuple(str(name) for name in tool_inventory)
    if len(tools) != 12 or len(set(tools)) != 12:
        raise ValueError("client_conformance_tool_inventory_invalid")
    payload: dict[str, Any] = {
        "schema_id": CLIENT_CONFORMANCE_CONTRACT_SCHEMA_ID,
        "schema_version": CLIENT_CONFORMANCE_CONTRACT_SCHEMA_VERSION,
        "contract_kind": "internal_client_neutral_test_contract",
        "product_workflow_engine": "current_loop_coordinator",
        "second_workflow_engine_present": False,
        "public_client_selector_present": False,
        "generic_mcp_compatibility_claimed": False,
        "future_profile_template_enabled": False,
        "tool_inventory": list(tools),
        "tool_count": len(tools),
        "shared_assertions": list(_SHARED_ASSERTIONS),
        "client_specific_seams": [
            "installation_and_launch_setup",
            "native_permission_ui",
            "instruction_binding",
            "evidence_capture_fields",
            "configuration_restoration",
        ],
        "native_permission_auto_approval": False,
        "source_conformance_is_live_client_qualification": False,
    }
    payload["contract_digest"] = _digest(payload)
    return deepcopy(payload)


def cursor_desktop_reference_profile() -> dict[str, Any]:
    """Return the source-only reference profile for shared conformance tests."""

    payload: dict[str, Any] = {
        "schema_id": CLIENT_CONFORMANCE_PROFILE_SCHEMA_ID,
        "schema_version": CLIENT_CONFORMANCE_PROFILE_SCHEMA_VERSION,
        "profile_id": "cursor_desktop_reference",
        "reference_implementation": True,
        "source_conformance_enabled": True,
        "live_client_qualification": False,
        "native_permission_ui_separate": True,
        "automatic_native_permission_approval": False,
        "private_setup_contract": "native_cursor_absent_or_existing_exact_restore",
        "shared_assertions": list(_SHARED_ASSERTIONS),
    }
    payload["profile_digest"] = _digest(payload)
    return deepcopy(payload)


def validate_conformance_profile(profile: dict[str, Any]) -> None:
    """Fail closed when a profile attempts to weaken shared source assertions."""

    if profile.get("schema_id") != CLIENT_CONFORMANCE_PROFILE_SCHEMA_ID:
        raise ValueError("client_conformance_profile_schema_invalid")
    if profile.get("schema_version") != CLIENT_CONFORMANCE_PROFILE_SCHEMA_VERSION:
        raise ValueError("client_conformance_profile_version_invalid")
    if profile.get("source_conformance_enabled") is not True:
        raise ValueError("client_conformance_profile_inert")
    if tuple(profile.get("shared_assertions", ())) != _SHARED_ASSERTIONS:
        raise ValueError("client_conformance_shared_assertion_mismatch")
    if profile.get("automatic_native_permission_approval") is not False:
        raise ValueError("client_conformance_native_permission_boundary_invalid")


def evaluate_conformance_observations(
    *,
    profile: dict[str, Any],
    observations: dict[str, bool],
) -> dict[str, Any]:
    """Evaluate one client-specific observation set against shared assertions."""

    validate_conformance_profile(profile)
    required = tuple(str(value) for value in profile["shared_assertions"])
    unknown = sorted(set(observations) - set(required))
    missing = sorted(set(required) - set(observations))
    failed = sorted(name for name in required if observations.get(name) is not True)
    result: dict[str, Any] = {
        "schema_id": "qcoder.connected_assistant.conformance_result.v1",
        "schema_version": 1,
        "profile_id": profile["profile_id"],
        "required_assertion_count": len(required),
        "unknown_assertions": unknown,
        "missing_assertions": missing,
        "failed_assertions": failed,
        "passed": not unknown and not missing and not failed,
        "live_client_qualification_created": False,
    }
    result["result_digest"] = _digest(result)
    return result
