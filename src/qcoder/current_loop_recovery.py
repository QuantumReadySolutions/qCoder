"""Explicit bounded recovery for the active-loop evidence spine."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from copy import deepcopy
from hashlib import sha256
from typing import Any

from qcoder.current_loop_invocation import build_operation_invocation
from qcoder.current_loop_vocabulary import recovery_actions_for

RECOVERY_SCHEMA_ID = "qcoder.current_loop.recovery.v5"
RECOVERY_SCHEMA_VERSION = 5

_ACTION_OPERATIONS = {
    "retry_registration": ("execute_recovery_action", "execute-recovery-action"),
    "correct_candidate": ("execute_recovery_action", "execute-recovery-action"),
    "retry_local_derivation": (
        "process_authorized_artifacts",
        "process-authorized-artifacts",
    ),
    "resume_pending_derivation": (
        "process_authorized_artifacts",
        "process-authorized-artifacts",
    ),
    "restore_evidence": ("execute_recovery_action", "execute-recovery-action"),
    "stop_loop": ("abandon", "abandon"),
}

RECEIPT_REBIND_CATEGORIES = frozenset(
    {
        "operation_receipt_invalid",
        "operation_receipt_digest_mismatch",
        "operation_receipt_revision_invalid",
        "operation_receipt_stale",
        "operation_receipt_contract_stale",
        "operation_receipt_role_not_authorized",
        "operation_receipt_format_not_authorized",
        "operation_receipt_sensitive_output_requires_selection",
        "artifact_candidate_provenance_conflict",
        "artifact_candidate_role_invalid",
        "artifact_candidate_file_required",
        "artifact_candidate_path_invalid",
    }
)
BOUNDED_ALTERNATIVE_CATEGORIES = frozenset(
    {
        "artifact_format_unsupported",
        "circuit_format_unsupported",
        "current_loop_contract_policy_prohibited",
        "governing_blueprint_unavailable",
        "canonical_parent_set_incomplete",
        "parent_reference_stale",
        "parent_digest_mismatch",
        "parent_artifact_missing",
        "unsupported_iteration_route",
        "unsupported_schema",
    }
)
RETURN_TO_ITERATION_CATEGORIES = frozenset(
    {
        "governing_blueprint_unavailable",
        "canonical_parent_set_incomplete",
        "parent_reference_stale",
        "parent_digest_mismatch",
        "parent_artifact_missing",
        "unsupported_iteration_route",
    }
)
QCODER_CORRECTS_CATEGORIES = frozenset(
    {
        "checkpoint_input_required_field_missing",
        "profile_id_missing",
        "classification_missing",
    }
)

# This is the executable handler inventory used by both runtime advertisement and
# the contract proof. An action absent here can never enter active_recovery.alternatives.
_RUNTIME_ACTION_HANDLERS: Mapping[str, Mapping[str, Any]] = {
    "retry_registration": {
        "handler": "CurrentLoopCoordinator.execute_recovery_action",
        "terminal": False,
        "ordinary_supported_next_step": "process_registered_evidence",
    },
    "retry_hosted_enrichment": {
        "handler": "CurrentLoopCoordinator.enrich_authorized_evidence",
        "terminal": False,
        "ordinary_supported_next_step": "review_local_evidence_or_skip_hosted_enrichment",
    },
    "skip_hosted_enrichment": {
        "handler": "CurrentLoopCoordinator.execute_recovery_action",
        "terminal": False,
        "ordinary_supported_next_step": "continue_with_local_evidence",
    },
    "provide_supported_circuit_artifact": {
        "handler": "CurrentLoopCoordinator.execute_recovery_action",
        "terminal": False,
        "ordinary_supported_next_step": "obtain_separate_ide_authority",
    },
    "continue_with_limitations": {
        "handler": "CurrentLoopCoordinator.execute_recovery_action",
        "terminal": False,
        "ordinary_supported_next_step": "continue_ordinary_iteration",
    },
    "skip_current_artifact_derivation": {
        "handler": "CurrentLoopCoordinator.execute_recovery_action",
        "terminal": False,
        "ordinary_supported_next_step": "continue_ordinary_iteration",
    },
    "abandon_step": {
        "handler": "CurrentLoopCoordinator.execute_recovery_action",
        "terminal": False,
        "ordinary_supported_next_step": "use_current_phase_supported_next_action",
    },
    "retry_local_derivation": {
        "handler": "CurrentLoopCoordinator.execute_recovery_action",
        "terminal": False,
        "ordinary_supported_next_step": "process_authorized_artifacts",
    },
    "decline_build_review": {
        "handler": "CurrentLoopCoordinator.decline_build_review",
        "terminal": False,
        "ordinary_supported_next_step": "continue_ordinary_iteration",
    },
    "return_to_iteration_ready": {
        "handler": "CurrentLoopCoordinator.execute_recovery_action",
        "terminal": False,
        "ordinary_supported_next_step": "continue_ordinary_iteration",
    },
    "stop_loop": {
        "handler": "CurrentLoopCoordinator.abandon",
        "terminal": True,
        "ordinary_supported_next_step": "none_terminal",
    },
}


def recovery_strategy_for(
    category: str,
    *,
    receipt_context_present: bool,
    causal_continuation_eligible: bool,
) -> str:
    """Classify one recovery category without advertising an action."""

    if category == "operation_receipt_stale" and causal_continuation_eligible:
        return "causal_continuation"
    if receipt_context_present and category in RECEIPT_REBIND_CATEGORIES:
        return "rebind_event_receipt"
    if category in QCODER_CORRECTS_CATEGORIES:
        return "qcoder_corrects"
    if category == "client_state_conflict":
        return "refresh_revision"
    if category in RECEIPT_REBIND_CATEGORIES:
        return "rebind_event_receipt"
    if category in BOUNDED_ALTERNATIVE_CATEGORIES:
        return "bounded_alternative"
    return "restage_with_construction"


def advertised_recovery_actions(
    *,
    category: str,
    strategy: str,
    origin: str,
    causal_continuation_eligible: bool,
    deterministic: bool,
    active_loop_nonterminal: bool,
    requested_actions: Sequence[str] | None = None,
) -> tuple[str, ...]:
    """Return only actions executable from the state in which they are advertised."""

    if not active_loop_nonterminal:
        return ()
    if strategy == "causal_continuation":
        candidates: Sequence[str] = ("retry_registration", "stop_loop")
    elif requested_actions is not None:
        candidates = requested_actions
    elif strategy == "rebind_event_receipt":
        # Material receipt/authority changes require a fresh ordinary authority path.
        # retry_registration is not a refresh-authority operation.
        candidates = ("stop_loop",)
    elif category in {"artifact_format_unsupported", "circuit_format_unsupported"}:
        candidates = (
            "continue_with_limitations",
            "provide_supported_circuit_artifact",
            "stop_loop",
        )
    elif origin in {"hosted_transport", "hosted_operation"}:
        candidates = ("retry_hosted_enrichment", "skip_hosted_enrichment", "stop_loop")
    elif category in RETURN_TO_ITERATION_CATEGORIES:
        candidates = ("return_to_iteration_ready", "stop_loop")
    else:
        candidates = ("abandon_step", "stop_loop")

    selected: list[str] = []
    for action in candidates:
        if action not in _RUNTIME_ACTION_HANDLERS:
            continue
        if action == "retry_registration" and not (
            category == "operation_receipt_stale"
            and strategy == "causal_continuation"
            and causal_continuation_eligible
        ):
            continue
        if action == "retry_local_derivation" and deterministic:
            continue
        if action == "stop_loop" and not active_loop_nonterminal:
            continue
        if action not in selected:
            selected.append(action)
    return tuple(selected)


def recovery_action_handler(action: str) -> dict[str, Any] | None:
    contract = _RUNTIME_ACTION_HANDLERS.get(action)
    return deepcopy(dict(contract)) if isinstance(contract, Mapping) else None


def runtime_recovery_action_contract_truthful() -> bool:
    """Derive the public truth bit from the same handler inventory used by emission."""

    representative_rows = (
        advertised_recovery_actions(
            category="operation_receipt_stale",
            strategy="causal_continuation",
            origin="contract_or_authority",
            causal_continuation_eligible=True,
            deterministic=True,
            active_loop_nonterminal=True,
        ),
        advertised_recovery_actions(
            category="operation_receipt_invalid",
            strategy="rebind_event_receipt",
            origin="contract_or_authority",
            causal_continuation_eligible=False,
            deterministic=True,
            active_loop_nonterminal=True,
        ),
        advertised_recovery_actions(
            category="circuit_format_unsupported",
            strategy="bounded_alternative",
            origin="local_circuit_derivation",
            causal_continuation_eligible=False,
            deterministic=True,
            active_loop_nonterminal=True,
        ),
        advertised_recovery_actions(
            category="protected_service_unavailable",
            strategy="restage_with_construction",
            origin="hosted_transport",
            causal_continuation_eligible=False,
            deterministic=False,
            active_loop_nonterminal=True,
        ),
        advertised_recovery_actions(
            category="unknown_local_internal",
            strategy="restage_with_construction",
            origin="unknown_local_internal",
            causal_continuation_eligible=False,
            deterministic=True,
            active_loop_nonterminal=True,
        ),
    )
    return all(
        recovery_action_handler(action) is not None
        for actions in representative_rows
        for action in actions
    )


def _digest(value: object) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def evidence_recovery(
    *,
    category: str,
    state: Mapping[str, Any],
    operation: str,
    safe_arguments: Mapping[str, Any] | None = None,
    allowed_actions: Sequence[str] | None = None,
    runtime_executable: str = sys.executable,
    checkpoint: str = "privacy_or_trust",
) -> dict[str, Any]:
    actions = tuple(allowed_actions or recovery_actions_for(category))
    generated = []
    for action in actions:
        target = _ACTION_OPERATIONS.get(action)
        if target is None:
            continue
        target_operation, subcommand = target
        fixed: dict[str, Any] = {}
        required: list[str] = []
        if subcommand == "abandon":
            required = ["--approve"]
            fixed = {"--approve": True}
        invocation_reference = (
            f"recovery-{_digest({'category': category, 'operation': operation})[:24]}"
        )
        if subcommand == "execute-recovery-action":
            required = [
                "--recovery-reference",
                "--action",
                "--expected-contract-revision",
            ]
            fixed = {
                "--recovery-reference": invocation_reference,
                "--action": action,
                "--expected-contract-revision": int(
                    state["current_loop_contract"]["contract_revision"]
                ),
            }
        invocation = build_operation_invocation(
            {
                "subcommand": subcommand,
                "required_flags": required,
                "fixed_argument_values": fixed,
            },
            executable=runtime_executable,
            workspace=str(state["workspace_root"]),
            base_url="",
            token_file="",
            state_revision=int(state["state_revision"]),
            loop_ref=str(state["loop_ref"]),
            checkpoint=checkpoint,
        )
        generated.append(
            {
                "action": action,
                "operation": target_operation,
                "invocation": invocation,
                "executable": True,
            }
        )
    result = {
        "schema_id": RECOVERY_SCHEMA_ID,
        "schema_version": RECOVERY_SCHEMA_VERSION,
        "category": category,
        "originating_operation": operation,
        "loop_ref": state["loop_ref"],
        "workspace_binding": state["workspace_root"],
        "state_revision": state["state_revision"],
        "contract_revision": state["current_loop_contract"]["contract_revision"],
        "actions": generated,
        "conversation_may_continue": bool(generated),
        "assistant_should_stop": not bool(generated),
        "primary_next_invocation": (deepcopy(generated[0]["invocation"]) if generated else None),
        "canonical_state_reconstructed_by_assistant": False,
        "substring_routing_used": False,
    }
    result["recovery_digest"] = _digest(result)
    return result


def recovery_contract_snapshot() -> dict[str, Any]:
    payload = {
        "schema_id": RECOVERY_SCHEMA_ID,
        "schema_version": RECOVERY_SCHEMA_VERSION,
        "category_mapping": "qcoder.current_loop.vocabulary.v1",
        "substring_routing_permitted": False,
        "every_advertised_action_executable": runtime_recovery_action_contract_truthful(),
        "assistant_reconstruction_permitted": False,
        "retry_registration_causal_continuation": {
            "same_action_binding_required": True,
            "one_attempt": True,
            "material_change_blocks": True,
            "second_customer_approval_for_stale_only_receipt": False,
            "native_ide_permission_separate": True,
            "internal_choreography_customer_visible": False,
        },
    }
    payload["contract_digest"] = _digest(payload)
    return payload
