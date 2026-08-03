"""Explicit bounded recovery for the active-loop evidence spine."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from hashlib import sha256
from typing import Any

RECOVERY_SCHEMA_ID = "qcoder.current_loop.recovery.v5"
RECOVERY_SCHEMA_VERSION = 5

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


def runtime_recovery_action_inventory() -> dict[str, dict[str, Any]]:
    """Return the sole live action/handler inventory used by recovery emission."""

    return {
        action: deepcopy(dict(contract))
        for action, contract in sorted(_RUNTIME_ACTION_HANDLERS.items())
    }


def resolve_live_recovery_policy(
    *,
    category: str,
    presentation: Sequence[Any],
    receipt_context_present: bool,
    causal_continuation_eligible: bool,
    origin: str,
    deterministic: bool,
    active_loop_nonterminal: bool,
    requested_actions: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Resolve one authoritative live recovery policy row.

    Category presentation is data, while this resolver is the only authority for
    strategy, advertisement, executability, authority ceiling, continuation, and
    supported-next-action semantics.
    """

    if len(presentation) != 6:
        raise ValueError("recovery_presentation_invalid")
    summary, next_action, conversation, reauthorize, state_intact, certification = (
        presentation
    )
    strategy = recovery_strategy_for(
        category,
        receipt_context_present=receipt_context_present,
        causal_continuation_eligible=causal_continuation_eligible,
    )
    actions = advertised_recovery_actions(
        category=category,
        strategy=strategy,
        origin=origin,
        causal_continuation_eligible=causal_continuation_eligible,
        deterministic=deterministic,
        active_loop_nonterminal=active_loop_nonterminal,
        requested_actions=requested_actions,
    )
    action_contracts: list[dict[str, Any]] = []
    for action in actions:
        handler = recovery_action_handler(action)
        if handler is None:
            raise AssertionError(f"unbound recovery action: {action}")
        action_contracts.append(
            {
                "action": action,
                **handler,
                "executable_in_advertised_state": True,
                "availability": (
                    "conditional_hosted_service"
                    if action == "retry_hosted_enrichment"
                    else "local_bounded"
                ),
            }
        )
    causal = strategy == "causal_continuation" and causal_continuation_eligible
    return {
        "category": category,
        "strategy": strategy,
        "customer_safe_summary": (
            "Continue registering the same already-authorized build artifacts. No new files, "
            "execution, network access, hosted activity, or broader authority is requested."
            if causal
            else str(summary)
        ),
        "supported_next_action": (
            "continue_same_authorized_registration" if causal else str(next_action)
        ),
        "conversation_may_continue": bool(conversation),
        "reauthorization_required": False if causal else bool(reauthorize),
        "local_state_intact": bool(state_intact),
        "certification_fallback_available": bool(certification),
        "causal_continuation_eligible": causal,
        "authority_ceiling": (
            "exact_prior_action_only"
            if causal
            else "fresh_action_specific_authority_required"
            if reauthorize
            else "no_authority_broadening"
        ),
        "hosted_action_availability": (
            "conditional"
            if any(
                row["availability"] == "conditional_hosted_service"
                for row in action_contracts
            )
            else "not_advertised"
        ),
        "advertised_actions": list(actions),
        "action_contracts": action_contracts,
    }


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


def recovery_contract_snapshot() -> dict[str, Any]:
    payload = {
        "schema_id": RECOVERY_SCHEMA_ID,
        "schema_version": RECOVERY_SCHEMA_VERSION,
        "live_policy_source": "qcoder.current_loop_recovery.resolve_live_recovery_policy",
        "action_handler_inventory": runtime_recovery_action_inventory(),
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
