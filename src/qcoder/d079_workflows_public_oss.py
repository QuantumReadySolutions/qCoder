"""D-079 connected-assistant workflow semantics.

This is an internal composition layer over the existing decision catalog,
local evidence engine, and Context Bridge tools.  It deliberately does not add
an MCP tool or grant file discovery, edit, run, or customer-decision authority.
"""

from __future__ import annotations

import base64
import json
import re
import secrets
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

from qcoder.blueprint_decisions_public_oss import (
    PROFILE_DECISION_CATALOG_ID,
    PROFILE_DECISION_CATALOG_VERSION,
    PROFILE_DECISION_ID_VERSION,
    build_decision_records,
    calculate_blueprint_readiness,
    catalog_entries,
)
from qcoder.connected_assistant_conformance import (
    CUSTOMER_TERMINAL_OUTCOME,
    NON_TERMINAL_PREPARATORY,
    evaluate_named_workflow_result,
    process_and_discard_retention_satisfied,
)
from qcoder.current_loop_request_semantics import classify_current_request
from qcoder.engines.review.local_evidence import (
    LocalEvidenceError,
    build_local_evidence_review,
    build_share_safe_local_evidence_review,
    resolve_explicit_files,
)

BLUEPRINT_PROPOSAL_SCHEMA_ID = "qcoder.connected_assistant.blueprint_proposal.v1"
CONFIRMED_BLUEPRINT_SCHEMA_ID = "qcoder.connected_assistant.confirmed_blueprint.v1"
EVIDENCE_WORKFLOW_SCHEMA_ID = "qcoder.connected_assistant.local_first_evidence_review.v1"
RECOVERY_SCHEMA_ID = "qcoder.connected_assistant.structured_recovery.v1"
INVOCATION_CONTRACT_SCHEMA_ID = "qcoder.connected_assistant.d079_local_invocation.v1"
DEFAULT_ROUTING_SCHEMA_ID = "qcoder.connected_assistant.default_workstyle_routing.v1"
DECISION_AWARE_PATH = "readiness_resolution_v1"
MAX_PROTECTED_EVIDENCE_BYTES = 131_072
MAX_SEMANTIC_DIFF_ENTRIES = 64

_TEMPORARY_CONTROL_PATTERNS = (
    re.compile(r"\bdo not edit(?:\s+anything)?(?:\s+yet)?\b", re.IGNORECASE),
    re.compile(r"\bdo not run(?:\s+anything)?(?:\s+yet)?\b", re.IGNORECASE),
    re.compile(
        r"\bdo not (?:edit\s+or\s+run|run\s+or\s+edit)(?:\s+anything)?(?:\s+yet)?\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bshow me the evidence and stop\b", re.IGNORECASE),
    re.compile(r"\bask before continuing\b", re.IGNORECASE),
)
_FORBIDDEN_PROTECTED_KEYS = {
    "customer_filename",
    "customer_path",
    "local_path",
    "path",
    "raw_counts",
    "raw_qasm",
    "raw_source",
    "selected_source",
    "source_code",
}
_PATH_TEXT = re.compile(r"(?:[A-Za-z]:\\|/(?:home|Users|mnt|tmp|var)/)")


class D079WorkflowError(ValueError):
    """Fail-closed error with a structured customer recovery projection."""

    def __init__(self, recovery: Mapping[str, Any]):
        self.recovery = deepcopy(dict(recovery))
        super().__init__(json.dumps(self.recovery, ensure_ascii=True, sort_keys=True))


def d079_orchestration_contract_snapshot(
    tool_inventory: Sequence[str], coordinator_prefix: Sequence[str] = ("python", "-m", "qcoder")
) -> dict[str, Any]:
    """Expose the binding-owned D-079 semantics without adding a public tool."""

    tools = tuple(str(item) for item in tool_inventory)
    if len(tools) != 12 or len(set(tools)) != 12:
        raise ValueError("d079_exact_twelve_tool_inventory_required")
    payload: dict[str, Any] = {
        "schema_id": "qcoder.connected_assistant.d079_orchestration.v1",
        "schema_version": 1,
        "public_tool_inventory": list(tools),
        "public_tool_count": 12,
        "new_customer_visible_tools": [],
        "default_routing": binding_default_routing_contract(),
        "binding_owned_local_invocation": connected_assistant_invocation_contract(
            coordinator_prefix=coordinator_prefix
        ),
        "blueprint_workflow": {
            "ordinary_customer_language": True,
            "decision_aware_by_default": True,
            "internal_decision_path": DECISION_AWARE_PATH,
            "customer_supplies_internal_flag": False,
            "canonical_decision_catalog_reused": PROFILE_DECISION_CATALOG_ID,
            "confirmation_is_exact_immutable_child_transition": True,
            "temporary_authority_separate_from_durable_intent": True,
            "assistant_proposal_is_confirmation": False,
        },
        "evidence_review_workflow": {
            "ordinary_customer_language": True,
            "selection": "exact_customer_selected_files_only",
            "repository_discovery": False,
            "local_canonical_evidence_first": True,
            "separate_share_safe_derivative": True,
            "protected_raw_or_path_ingestion": False,
            "automatic_same_workflow_continuation": True,
            "terminal_outcome": "Result Review",
        },
        "authority": {
            "conversation": "connected_assistant",
            "file_read": "native_client_customer_selection",
            "code_edit": "ide_or_customer",
            "run": "ide_or_customer",
        },
        "retention": "process_and_discard",
        "persistent_project_memory": False,
    }
    payload["contract_digest"] = _digest(payload)
    return payload


def binding_default_routing_contract() -> dict[str, Any]:
    """Return one authoritative precedence table for named and generic requests."""

    named_common = {
        "action": "execute_binding_owned_current_loop_operation",
        "operation": "connected_assistant_workflow",
        "subcommand": "connected-assistant-workflow",
        "operation_input_owner": "qcoder_connected_assistant_binding",
        "customer_constructs_operation_envelope": False,
        "raw_mcp_default_entrypoint": False,
        "raw_mcp_role": "composed_or_diagnostic_primitive",
        "activates_full_context_loop": False,
    }
    return {
        "schema_id": DEFAULT_ROUTING_SCHEMA_ID,
        "schema_version": 1,
        "deterministic_single_route": True,
        "dual_action_permitted": False,
        "recursive_routing_permitted": False,
        "selected_action_cardinality": "exactly_one",
        "decision_order": [
            "available_inactive",
            "supported_d080_concrete_current_request",
            "explicit_active_build",
            "supported_named_d079_workflow",
            "generic_single_capability_fallthrough",
        ],
        "named_workflow_precedence": {
            "precedes": "generic_single_capability_fallthrough",
            "falls_through_when_unmatched": True,
        },
        "d080_current_request": {
            "classifier": "canonical_compositional_current_request_semantics",
            "precedes": [
                "generic_single_capability_fallthrough",
                "planning_language_fallback",
            ],
            "action": "call_binding_owned_begin_current_loop",
            "operation": "begin_current_loop",
            "transport": "project_local_binding_mcp",
            "input_shape": {"request_text": "exact_current_customer_message"},
            "shell_or_stdin_construction": False,
            "exact_message_request_baseline": True,
            "one_structured_activation": True,
            "binding_constructs_typed_operation": True,
            "customer_constructs_operation_envelope": False,
            "stage_ceiling_is_temporary": True,
            "current_step_contract_is_canonical_projection": True,
            "compact_next_action_is_sole_procedural_source": True,
            "normal_path_native_action_handoff": {
                "sequence": [
                    "call_binding_owned_begin_current_loop",
                    "native_client_applies_its_own_controls",
                    "perform_exact_external_native_action",
                    "typed_complete_current_step_or_equivalent_optional_hook_adapter",
                    "present_concise_result_and_stop",
                ],
                "post_action_operation": "complete_current_step",
                "post_action_transport": "private_current_loop_binding",
                "hooks_required_for_correctness": False,
                "bounded_action_expectation_and_registration_composed": True,
                "native_client_permission_owner": "native_client",
                "native_client_permission_granted_or_observed_by_qcoder": False,
                "client_approval_telemetry_required": False,
                "qcoder_serial_control_cycles": 2,
                "separate_receipt_read_required": False,
                "separate_registration_discovery_required": False,
                "help_or_package_inspection_required": False,
            },
        },
        "named_workflows": {
            "algorithm_blueprint_generation_context": {
                **named_common,
                "classifier": "ordinary_language_planning_or_design_for_quantum_program",
                "workflow": "ide_first_blueprint_decision_and_confirmation",
                "native_client_selected_paths_required": False,
            },
            "selected_file_evidence_review": {
                **named_common,
                "classifier": "ordinary_language_review_of_exact_selected_files_with_qcoder",
                "workflow": "local_first_evidence_review",
                "native_client_selected_paths_required": True,
            },
        },
        "generic_single_capability_fallthrough": {
            "trigger": "explicit_bounded_capability_request_not_classified_as_named_d079_workflow",
            "action": "use_applicable_mcp_tool",
            "activates_context_loop": False,
        },
        "customer_inputs_exclude": [
            "qcoder_current_loop_command",
            "operation_input_json",
            "decision_loop_flag",
            "mcp_tool_name",
            "decision_id",
            "digest",
            "lineage_identity",
        ],
    }


def connected_assistant_invocation_contract(
    *, coordinator_prefix: Sequence[str] = ("python", "-m", "qcoder")
) -> dict[str, Any]:
    """Return the executable binding-owned route for the two ordinary workflows."""

    prefix = [str(item) for item in coordinator_prefix]
    if not prefix or prefix[-1] != "current-loop":
        prefix.append("current-loop")
    return {
        "schema_id": INVOCATION_CONTRACT_SCHEMA_ID,
        "schema_version": 1,
        "operation": "connected-assistant-workflow",
        "qcoder_owned_argv": [
            *prefix,
            "connected-assistant-workflow",
            "--operation-input-stdin",
        ],
        "input_transport": "binding_constructed_utf8_json_stdin",
        "customer_constructs_input_envelope": False,
        "input_envelope": {
            "required": ["customer_instruction"],
            "properties": {
                "customer_instruction": "verbatim ordinary customer language",
                "selected_paths": "exact native-client/customer-selected paths; local only",
                "blueprint_context": "assistant-attributed bounded structuring; never customer JSON",
                "proposal": "qCoder-produced exact reviewed proposal",
                "confirmation": "qCoder-produced binding plus explicit customer review assertion",
            },
            "maximum_utf8_bytes": 1_048_576,
        },
        "ordinary_language_router": {
            "algorithm_blueprint_generation_context": "ide_first_blueprint_decision_and_confirmation",
            "review_selected_files_with_qcoder": "local_first_evidence_review",
        },
        "default_route_precedence": binding_default_routing_contract(),
        "lower_level_mcp_tools": "diagnostic_or_composed_primitives_not_customer_choreography",
        "native_client_exact_file_selection_required": True,
        "repository_discovery": False,
        "public_mcp_tool_added": False,
        "retention": "process_and_discard",
    }


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()


def _digest(value: Any) -> str:
    return sha256(_canonical_bytes(value)).hexdigest()


def _opaque(prefix: str, material: str) -> str:
    token = base64.urlsafe_b64encode(sha256(material.encode()).digest()[:18]).decode().rstrip("=")
    return f"{prefix}-{token}"


def _recovery(
    reason: str,
    *,
    offending_class: str,
    field: str | None = None,
    affected_decision: str | None = None,
    category: str,
    wrong_layer: str | None = None,
    local_preprocessing: str | None = None,
    valid_portions_retained: bool = False,
    protected_safe_error_category: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "schema_id": RECOVERY_SCHEMA_ID,
        "schema_version": 1,
        "reason_category": reason,
        "offending_class": offending_class,
        "bounded_field": field,
        "affected_decision": affected_decision,
        "recovery_category": category,
        "wrong_artifact_layer": wrong_layer,
        "required_local_preprocessing": local_preprocessing,
        "valid_portions_may_be_retained": valid_portions_retained,
        "protected_safe_error_category": protected_safe_error_category,
        "fail_closed": True,
    }
    if details:
        result["details"] = deepcopy(dict(details))
    return result


def _lineage(value: str | None) -> str:
    if value is None:
        return "session-artifact-" + secrets.token_hex(16)
    if not re.fullmatch(r"session-artifact-[0-9a-f]{16,64}", value):
        raise D079WorkflowError(
            _recovery(
                "missing_or_invalid_lineage",
                offending_class="proposal_lineage",
                field="current_lineage_reference",
                category="start_new_reviewable_proposal",
            )
        )
    return value


def _catalog_lookup(
    profile_id: str,
) -> tuple[list[dict[str, Any]], dict[str, tuple[dict[str, Any], ...]]]:
    try:
        entries = catalog_entries(profile_id)
    except ValueError as exc:
        raise D079WorkflowError(
            _recovery(
                "unsupported_profile",
                offending_class="profile",
                field="profile_id",
                category="choose_supported_profile",
            )
        ) from exc
    candidates: dict[str, list[dict[str, Any]]] = {}
    for item in entries:
        aliases = {
            item["profile_decision_id"],
            item["profile_decision_id"].split(".", 1)[1],
            *item["intent_fields"],
            *item["blueprint_fields"],
        }
        for alias in aliases:
            candidates.setdefault(str(alias), []).append(item)
    lookup = {key: tuple(value) for key, value in candidates.items()}
    return entries, lookup


def _resolve_decision_key(
    key: str, lookup: Mapping[str, Sequence[dict[str, Any]]]
) -> dict[str, Any]:
    matches = lookup.get(key)
    if not matches:
        raise D079WorkflowError(
            _recovery(
                "unknown_decision_field",
                offending_class="decision_input",
                field=key,
                category="use_catalog_field_or_question",
                valid_portions_retained=True,
            )
        )
    canonical = {str(item["profile_decision_id"]): item for item in matches}
    if len(canonical) != 1:
        raise D079WorkflowError(
            _recovery(
                "ambiguous_decision_alias",
                offending_class="decision_input",
                field=key,
                category="resolve_through_canonical_decision_identity",
                valid_portions_retained=True,
                details={
                    "ambiguous_alias": key,
                    "colliding_profile_decision_ids": sorted(canonical),
                    "customer_must_supply_internal_identity": False,
                },
            )
        )
    return next(iter(canonical.values()))


def _stable_decision_refs(
    profile_id: str, lineage: str, entries: Sequence[Mapping[str, Any]]
) -> dict[str, str]:
    return {
        str(item["profile_decision_id"]): _opaque(
            "decision",
            f"{PROFILE_DECISION_CATALOG_ID}@{PROFILE_DECISION_CATALOG_VERSION}|{PROFILE_DECISION_ID_VERSION}|{profile_id}|{item['profile_decision_id']}|{lineage}",
        )
        for item in entries
    }


def _disposition(
    *, entry: Mapping[str, Any], kind: str, value: Any, bounds: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    if kind == "resolved_from_explicit_evidence":
        return {
            "resolution_state": "resolved",
            "user_disposition": "selected_choice",
            "generation_effect": "non_blocking",
            "selected_value": deepcopy(value),
            "blueprint_representation_state": "represented",
            "choice_origin": "human_specified",
            "evidence_confidence": "User-provided",
            "alignment_status": "appears_aligned",
            "provenance_entries": [{"kind": kind, "source": "explicit_customer_fact"}],
        }
    if kind == "accepted_assistant_proposal":
        return {
            "resolution_state": "resolved",
            "user_disposition": "selected_choice",
            "generation_effect": "non_blocking",
            "selected_value": deepcopy(value),
            "blueprint_representation_state": "represented",
            "choice_origin": "blueprint_confirmed",
            "evidence_confidence": "User-provided",
            "alignment_status": "appears_aligned",
            "provenance_entries": [
                {"kind": "assistant_proposal", "confirmed_by": "explicit_customer_disposition"}
            ],
        }
    if kind == "explicitly_bounded_or_delegated":
        if not entry["bounded_delegation_eligible"] or not isinstance(bounds, Mapping):
            raise D079WorkflowError(
                _recovery(
                    "unbounded_or_ineligible_delegation",
                    offending_class="decision_disposition",
                    affected_decision=str(entry["profile_decision_id"]),
                    category="supply_catalog_bounded_delegation",
                    valid_portions_retained=True,
                )
            )
        return {
            "resolution_state": "resolved",
            "user_disposition": (
                "bounded_alternatives"
                if bounds.get("bound_type") == "finite_alternative_set"
                else "bounded_value_range"
            ),
            "generation_effect": "bounded_discretion",
            "blueprint_representation_state": "represented",
            "choice_origin": "human_specified",
            "evidence_confidence": "User-provided",
            "alignment_status": "appears_aligned",
            "user_approved_bounds": deepcopy(dict(bounds)),
            "provenance_entries": [{"kind": kind, "scope": "this_decision_only"}],
        }
    if kind == "deliberately_unresolved":
        return {
            "resolution_state": "unresolved",
            "user_disposition": "left_unresolved",
            "generation_effect": entry["default_generation_effect"],
            "blueprint_representation_state": "not_represented",
            "choice_origin": "human_specified",
            "evidence_confidence": "User-provided",
            "alignment_status": "not_applicable",
            "unresolved_questions": [entry["question"]],
        }
    raise D079WorkflowError(
        _recovery(
            "unsupported_decision_disposition",
            offending_class="decision_disposition",
            affected_decision=str(entry["profile_decision_id"]),
            category="choose_canonical_disposition",
            valid_portions_retained=True,
        )
    )


def _is_temporary_control(value: str) -> bool:
    return any(pattern.search(value) for pattern in _TEMPORARY_CONTROL_PATTERNS)


def _temporary_authority_actions(value: str) -> tuple[str, ...]:
    normalized = value.casefold()
    actions: list[str] = []
    if re.search(r"\bdo not\s+(?:edit|run\s+or\s+edit|edit\s+or\s+run)\b", normalized):
        actions.append("edit")
    if re.search(r"\bdo not\s+(?:run|edit\s+or\s+run|run\s+or\s+edit)\b", normalized):
        actions.append("run")
    if "show me the evidence and stop" in normalized:
        actions.append("stop_after_evidence")
    if "ask before continuing" in normalized:
        actions.append("ask_before_continuing")
    return tuple(dict.fromkeys(actions))


def _expected_artifact_identity(lineage: str, proposal_digest: str) -> str:
    return _opaque("proposal", f"{lineage}|{proposal_digest}")


def _canonical_confirmation_requirements(
    *, artifact_identity: str, artifact_revision: int, lineage: str, proposal_digest: str
) -> dict[str, Any]:
    return {
        "artifact_identity": artifact_identity,
        "artifact_revision": artifact_revision,
        "parent_lineage_identity": lineage,
        "proposal_digest": proposal_digest,
        "exact_proposal_reviewed": True,
    }


def _canonical_confirmation_projection(proposal: Mapping[str, Any]) -> dict[str, Any]:
    layers = proposal.get("semantic_layers")
    if not isinstance(layers, Mapping):
        raise D079WorkflowError(
            _recovery(
                "malformed_proposal",
                offending_class="proposal_integrity",
                field="semantic_layers",
                category="regenerate_reviewable_proposal",
            )
        )
    entries, _lookup = _catalog_lookup(str(proposal.get("profile_id") or ""))
    entries_by_id = {str(item["profile_decision_id"]): item for item in entries}
    facts = layers.get("explicit_user_facts")
    proposals = layers.get("assistant_implementation_proposals")
    records = proposal.get("decision_records")
    if (
        not isinstance(facts, Mapping)
        or not isinstance(proposals, Mapping)
        or not isinstance(records, list)
    ):
        raise D079WorkflowError(
            _recovery(
                "malformed_proposal",
                offending_class="proposal_integrity",
                field="semantic_layers",
                category="regenerate_reviewable_proposal",
            )
        )
    return {
        "what_you_said": layers.get("original_customer_request_verbatim"),
        "facts_you_supplied": [
            {"field": entries_by_id[str(decision_id)]["display_label"], "value": deepcopy(value)}
            for decision_id, value in facts.items()
        ],
        "how_your_request_was_structured": deepcopy(layers.get("assistant_structuring")),
        "proposed_implementation_choices": [
            {"field": entries_by_id[str(decision_id)]["display_label"], "proposal": deepcopy(value)}
            for decision_id, value in proposals.items()
        ],
        "unresolved_or_delegated_choices": [
            {"question": entry["question"], "state": record["resolution_state"]}
            for entry, record in zip(entries, records)
            if record.get("resolution_state") != "resolved"
            and (entry["generation_relevant"] or record.get("user_disposition") != "not_supplied")
        ],
        "confirmation_will_change": "Create a new confirmed child artifact bound to this exact proposal.",
        "confirmation_will_not_change": "The reviewed proposal, current-step controls, file/edit/run authority, and original request.",
        "internal_identifiers_required_from_customer": False,
    }


def _proposal_body_for_digest(proposal: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(value)
        for key, value in proposal.items()
        if key
        not in {
            "artifact_identity",
            "proposal_digest",
            "confirmation_requirements",
            "customer_confirmation_projection",
        }
    }


def prepare_ide_first_blueprint(
    *,
    customer_request: str,
    explicit_user_facts: Mapping[str, Any],
    assistant_structuring: Mapping[str, Any],
    assistant_implementation_proposals: Mapping[str, Any],
    customer_dispositions: Mapping[str, Mapping[str, Any]],
    current_step_controls: Sequence[str] = (),
    durable_constraints: Sequence[str] = (),
    explicitly_promoted_controls: Sequence[str] = (),
    profile_id: str = "generic_qiskit",
    current_lineage_reference: str | None = None,
) -> dict[str, Any]:
    """Prepare, but never implicitly confirm, one decision-aware proposal."""

    if not isinstance(customer_request, str) or not customer_request.strip():
        raise D079WorkflowError(
            _recovery(
                "malformed_proposal",
                offending_class="customer_request",
                field="customer_request",
                category="supply_nonempty_customer_request",
            )
        )
    lineage = _lineage(current_lineage_reference)
    entries, lookup = _catalog_lookup(profile_id)
    refs = _stable_decision_refs(profile_id, lineage, entries)
    facts: dict[str, Any] = {}
    proposals: dict[str, Any] = {}
    dispositions: dict[str, dict[str, Any]] = {}

    for key, value in explicit_user_facts.items():
        entry = _resolve_decision_key(str(key), lookup)
        decision_id = str(entry["profile_decision_id"])
        facts[decision_id] = deepcopy(value)
        dispositions[decision_id] = _disposition(
            entry=entry, kind="resolved_from_explicit_evidence", value=value
        )
    for key, value in assistant_implementation_proposals.items():
        entry = _resolve_decision_key(str(key), lookup)
        proposals[str(entry["profile_decision_id"])] = deepcopy(value)
    disposition_views: list[dict[str, Any]] = []
    for key, supplied in customer_dispositions.items():
        entry = _resolve_decision_key(str(key), lookup)
        decision_id = str(entry["profile_decision_id"])
        kind = str(supplied.get("disposition") or "")
        selected = supplied.get("value", proposals.get(decision_id))
        dispositions[decision_id] = _disposition(
            entry=entry,
            kind=kind,
            value=selected,
            bounds=supplied.get("bounds") if isinstance(supplied.get("bounds"), Mapping) else None,
        )
        disposition_views.append(
            {
                "profile_decision_id": decision_id,
                "decision_ref": refs[decision_id],
                "disposition": kind,
            }
        )

    parent = {
        "artifact_type": "request_baseline",
        "artifact_ref": lineage,
        "artifact_digest": sha256(customer_request.encode()).hexdigest(),
    }
    try:
        records = build_decision_records(
            profile_id=profile_id,
            current_lineage_reference=lineage,
            parent_artifact_references=[parent],
            dispositions=dispositions,
            decision_references=refs,
        )
    except ValueError as exc:
        raise D079WorkflowError(
            _recovery(
                str(exc),
                offending_class="decision_record",
                category="correct_bounded_decision_input",
                valid_portions_retained=True,
            )
        ) from exc
    readiness = calculate_blueprint_readiness(profile_id=profile_id, decision_records=records)
    temporary = list(dict.fromkeys(str(item) for item in current_step_controls))
    for pattern in _TEMPORARY_CONTROL_PATTERNS:
        for match in pattern.finditer(customer_request):
            text = match.group(0)
            if text not in temporary:
                temporary.append(text)
    observed_actions = {
        action for item in temporary for action in _temporary_authority_actions(item)
    }
    authority_actions = [
        action
        for action in ("edit", "run", "stop_after_evidence", "ask_before_continuing")
        if action in observed_actions
    ]
    promoted = {str(item) for item in explicitly_promoted_controls}
    durable = list(
        dict.fromkeys(
            [str(item) for item in durable_constraints] + [x for x in temporary if x in promoted]
        )
    )
    proposal_body: dict[str, Any] = {
        "schema_id": BLUEPRINT_PROPOSAL_SCHEMA_ID,
        "schema_version": 1,
        "artifact_revision": 1,
        "current_lineage_reference": lineage,
        "parent_artifact": parent,
        "profile_id": profile_id,
        "decision_catalog": f"{PROFILE_DECISION_CATALOG_ID}@{PROFILE_DECISION_CATALOG_VERSION}",
        "decision_aware_path": DECISION_AWARE_PATH,
        "customer_choreography_required": False,
        "semantic_layers": {
            "original_customer_request_verbatim": customer_request,
            "explicit_user_facts": facts,
            "assistant_structuring": deepcopy(dict(assistant_structuring)),
            "assistant_implementation_proposals": proposals,
            "qcoder_derived_classifications": {
                "profile": profile_id,
                "readiness": readiness,
            },
            "customer_confirmation": "not_yet_confirmed",
            "current_step_authority_controls": temporary,
            "durable_blueprint_constraints": durable,
        },
        "temporary_control_classification": [
            {
                "text": item,
                "recognized_current_step_control": _is_temporary_control(item),
                "authority_actions": list(_temporary_authority_actions(item)),
                "promoted_to_durable": item in promoted,
            }
            for item in temporary
        ],
        "temporary_authority_actions": authority_actions,
        "decision_records": records,
        "decision_dispositions": disposition_views,
        "readiness": readiness,
        "authority": {
            "assistant_conversation": True,
            "native_client_file_read": "customer_selected_only",
            "qcoder_edit_authority": False,
            "qcoder_run_authority": False,
            "confirmation_grants_edit_or_run": False,
        },
        "retention": "process_and_discard",
        "persistent": False,
    }
    proposal_digest = _digest(proposal_body)
    proposal_ref = _expected_artifact_identity(lineage, proposal_digest)
    proposal_body["artifact_identity"] = proposal_ref
    proposal_body["proposal_digest"] = proposal_digest
    proposal_body["confirmation_requirements"] = _canonical_confirmation_requirements(
        artifact_identity=proposal_ref,
        artifact_revision=1,
        lineage=lineage,
        proposal_digest=proposal_digest,
    )
    proposal_body["customer_confirmation_projection"] = _canonical_confirmation_projection(
        proposal_body
    )
    return proposal_body


def confirm_ide_first_blueprint(
    *, proposal: Mapping[str, Any], confirmation: Mapping[str, Any]
) -> dict[str, Any]:
    """Confirm an exact reviewed proposal and create an immutable child artifact."""

    original = deepcopy(dict(proposal))
    if proposal.get("schema_id") != BLUEPRINT_PROPOSAL_SCHEMA_ID:
        raise D079WorkflowError(
            _recovery(
                "wrong_artifact_layer",
                offending_class="confirmation_target",
                field="schema_id",
                category="confirm_blueprint_proposal",
                wrong_layer=str(proposal.get("schema_id") or "missing"),
            )
        )
    stored_requirements = proposal.get("confirmation_requirements")
    if not isinstance(stored_requirements, Mapping):
        raise D079WorkflowError(
            _recovery(
                "missing_lineage",
                offending_class="proposal_integrity",
                field="confirmation_requirements",
                category="regenerate_reviewable_proposal",
            )
        )
    body_for_digest = _proposal_body_for_digest(proposal)
    computed_digest = _digest(body_for_digest)
    lineage = proposal.get("current_lineage_reference")
    revision = proposal.get("artifact_revision")
    if not isinstance(lineage, str) or not isinstance(revision, int):
        raise D079WorkflowError(
            _recovery(
                "missing_lineage",
                offending_class="proposal_integrity",
                field="current_lineage_reference",
                category="regenerate_reviewable_proposal",
            )
        )
    expected_identity = _expected_artifact_identity(lineage, computed_digest)
    expected_requirements = _canonical_confirmation_requirements(
        artifact_identity=expected_identity,
        artifact_revision=revision,
        lineage=lineage,
        proposal_digest=computed_digest,
    )
    if proposal.get("proposal_digest") != computed_digest:
        raise D079WorkflowError(
            _recovery(
                "digest_mismatch",
                offending_class="proposal_integrity",
                field="proposal_digest",
                category="review_current_exact_proposal",
            )
        )
    if proposal.get("artifact_identity") != expected_identity:
        raise D079WorkflowError(
            _recovery(
                "artifact_identity_mismatch",
                offending_class="proposal_identity_envelope",
                field="artifact_identity",
                category="regenerate_identity_from_canonical_lineage_and_digest",
            )
        )
    expected_projection = _canonical_confirmation_projection(proposal)
    if proposal.get("customer_confirmation_projection") != expected_projection:
        raise D079WorkflowError(
            _recovery(
                "confirmation_projection_mismatch",
                offending_class="proposal_presentation_envelope",
                field="customer_confirmation_projection",
                category="regenerate_projection_from_canonical_proposal",
            )
        )
    for field, expected in expected_requirements.items():
        if stored_requirements.get(field) != expected:
            raise D079WorkflowError(
                _recovery(
                    "confirmation_requirements_mismatch",
                    offending_class="proposal_identity_envelope",
                    field=field,
                    category="regenerate_requirements_from_canonical_proposal",
                )
            )
    checks = (
        ("artifact_identity", "incorrect_confirmation_reference"),
        ("artifact_revision", "stale_revision"),
        ("parent_lineage_identity", "missing_or_stale_lineage"),
        ("proposal_digest", "digest_mismatch"),
    )
    for field, category in checks:
        if confirmation.get(field) != expected_requirements.get(field):
            raise D079WorkflowError(
                _recovery(
                    category,
                    offending_class="confirmation_binding",
                    field=field,
                    category="review_current_exact_proposal",
                )
            )
    if confirmation.get("exact_proposal_reviewed") is not True:
        raise D079WorkflowError(
            _recovery(
                "missing_review_assertion",
                offending_class="confirmation_binding",
                field="exact_proposal_reviewed",
                category="review_and_explicitly_assert_exact_proposal",
            )
        )
    readiness = proposal.get("readiness")
    if (
        not isinstance(readiness, Mapping)
        or readiness.get("aggregate_readiness_result") == "blocked_pending_decisions"
    ):
        blocking = (
            []
            if not isinstance(readiness, Mapping)
            else list(readiness.get("blocking_decision_references") or [])
        )
        raise D079WorkflowError(
            _recovery(
                "unresolved_blocking_decision",
                offending_class="decision_readiness",
                affected_decision=str(blocking[0]) if blocking else None,
                category="resolve_bound_or_deliberately_stop",
                valid_portions_retained=True,
            )
        )
    child_body = {
        "schema_id": CONFIRMED_BLUEPRINT_SCHEMA_ID,
        "schema_version": 1,
        "artifact_revision": int(proposal["artifact_revision"]) + 1,
        "parent_artifact_identity": proposal["artifact_identity"],
        "parent_artifact_digest": proposal["proposal_digest"],
        "current_lineage_reference": proposal["current_lineage_reference"],
        "confirmation": {
            "exact_proposal_reviewed": True,
            "binding_validated_immediately_before_materialization": True,
        },
        "intent_card": {
            "original_customer_request_verbatim": proposal["semantic_layers"][
                "original_customer_request_verbatim"
            ],
            "explicit_user_facts": deepcopy(proposal["semantic_layers"]["explicit_user_facts"]),
            "durable_constraints": deepcopy(
                proposal["semantic_layers"]["durable_blueprint_constraints"]
            ),
            "decision_records": deepcopy(proposal["decision_records"]),
        },
        "implementation_blueprint": {
            "assistant_structuring": deepcopy(proposal["semantic_layers"]["assistant_structuring"]),
            "implementation_choices": deepcopy(
                proposal["semantic_layers"]["assistant_implementation_proposals"]
            ),
            "layer": "implementation_blueprint",
        },
        "generation_context": {
            "readiness": deepcopy(proposal["readiness"]),
            "output_artifact_set": "customer_or_ide_selected",
            "generation_ready": True,
            "layer": "generation_context",
        },
        "authority": deepcopy(proposal["authority"]),
        "retention": "process_and_discard",
        "persistent": False,
        "parent_mutated": False,
    }
    child_body["artifact_digest"] = _digest(child_body)
    child_body["artifact_identity"] = _opaque(
        "derived", f"{proposal['artifact_identity']}|{child_body['artifact_digest']}"
    )
    if dict(proposal) != original:
        raise RuntimeError("confirmation_mutated_parent")
    return child_body


def revise_ide_first_blueprint(
    *, proposal: Mapping[str, Any], semantic_changes: Mapping[str, Any]
) -> dict[str, Any]:
    """Derive revision N+1 with exact parent lineage and a bounded semantic diff."""

    # Reuse confirmation's envelope validator without granting confirmation authority.
    canonical_requirements = proposal.get("confirmation_requirements")
    if not isinstance(canonical_requirements, Mapping):
        raise D079WorkflowError(
            _recovery(
                "missing_lineage",
                offending_class="proposal_revision",
                field="confirmation_requirements",
                category="regenerate_reviewable_proposal",
            )
        )
    validation_probe = deepcopy(dict(canonical_requirements))
    validation_probe["exact_proposal_reviewed"] = False
    try:
        confirm_ide_first_blueprint(proposal=proposal, confirmation=validation_probe)
    except D079WorkflowError as exc:
        if exc.recovery.get("reason_category") != "missing_review_assertion":
            raise
    else:  # pragma: no cover - the false assertion must never authorize confirmation
        raise RuntimeError("proposal_revision_validation_probe_unexpectedly_confirmed")
    original = deepcopy(dict(proposal))
    revised = deepcopy(dict(proposal))
    allowed = {
        "assistant_structuring",
        "assistant_implementation_proposals",
        "durable_blueprint_constraints",
    }
    unsupported = sorted(set(str(key) for key in semantic_changes) - allowed)
    if unsupported:
        raise D079WorkflowError(
            _recovery(
                "wrong_artifact_layer",
                offending_class="proposal_revision",
                field=unsupported[0],
                category="revise_supported_semantic_layer_only",
                wrong_layer="current_step_authority_or_unsupported_layer",
                valid_portions_retained=True,
            )
        )
    layers = revised.get("semantic_layers")
    if not isinstance(layers, dict):
        raise D079WorkflowError(
            _recovery(
                "malformed_proposal",
                offending_class="proposal_revision",
                field="semantic_layers",
                category="regenerate_reviewable_proposal",
            )
        )
    changes: list[dict[str, Any]] = []
    for field, supplied in semantic_changes.items():
        layer_field = str(field)
        value = deepcopy(supplied)
        if layer_field == "assistant_implementation_proposals":
            if not isinstance(value, Mapping):
                raise D079WorkflowError(
                    _recovery(
                        "malformed_proposal",
                        offending_class="proposal_revision",
                        field=layer_field,
                        category="supply_bounded_semantic_mapping",
                    )
                )
            _entries, lookup = _catalog_lookup(str(proposal.get("profile_id") or ""))
            value = {
                str(_resolve_decision_key(str(key), lookup)["profile_decision_id"]): deepcopy(item)
                for key, item in value.items()
            }
        elif layer_field == "assistant_structuring" and not isinstance(value, Mapping):
            raise D079WorkflowError(
                _recovery(
                    "malformed_proposal",
                    offending_class="proposal_revision",
                    field=layer_field,
                    category="supply_bounded_semantic_mapping",
                )
            )
        elif layer_field == "durable_blueprint_constraints" and (
            not isinstance(value, Sequence) or isinstance(value, (str, bytes))
        ):
            raise D079WorkflowError(
                _recovery(
                    "malformed_proposal",
                    offending_class="proposal_revision",
                    field=layer_field,
                    category="supply_bounded_semantic_sequence",
                )
            )
        before = layers.get(layer_field)
        if before == value:
            continue
        changes.append(
            {
                "bounded_field": f"semantic_layers.{layer_field}",
                "change_category": "semantic_value_changed",
                "before_digest": _digest(before),
                "after_digest": _digest(value),
            }
        )
        layers[layer_field] = value
    if not changes:
        return {
            "status": "unchanged_no_material_revision",
            "material_revision_created": False,
            "proposal": original,
            "semantic_diff": [],
            "fresh_confirmation_required": False,
        }
    if len(changes) > MAX_SEMANTIC_DIFF_ENTRIES:
        raise D079WorkflowError(
            _recovery(
                "semantic_diff_limit_exceeded",
                offending_class="proposal_revision",
                category="split_revision_into_bounded_reviewable_changes",
                valid_portions_retained=True,
            )
        )
    parent_identity = str(proposal.get("artifact_identity") or "")
    parent_digest = str(proposal.get("proposal_digest") or "")
    revised["artifact_revision"] = int(proposal.get("artifact_revision") or 0) + 1
    revised["parent_artifact"] = {
        "artifact_type": "blueprint_proposal",
        "artifact_ref": parent_identity,
        "artifact_digest": parent_digest,
        "artifact_revision": int(proposal.get("artifact_revision") or 0),
    }
    revised["revision_semantic_diff"] = changes
    revised["fresh_confirmation_required"] = True
    for field in (
        "artifact_identity",
        "proposal_digest",
        "confirmation_requirements",
        "customer_confirmation_projection",
    ):
        revised.pop(field, None)
    proposal_digest = _digest(revised)
    lineage = str(revised["current_lineage_reference"])
    artifact_identity = _expected_artifact_identity(lineage, proposal_digest)
    revised["proposal_digest"] = proposal_digest
    revised["artifact_identity"] = artifact_identity
    revised["confirmation_requirements"] = _canonical_confirmation_requirements(
        artifact_identity=artifact_identity,
        artifact_revision=int(revised["artifact_revision"]),
        lineage=lineage,
        proposal_digest=proposal_digest,
    )
    revised["customer_confirmation_projection"] = _canonical_confirmation_projection(revised)
    if dict(proposal) != original:
        raise RuntimeError("revision_mutated_parent")
    return {
        "status": "revised_proposal_ready_for_review",
        "material_revision_created": True,
        "proposal": revised,
        "semantic_diff": changes,
        "parent_artifact_identity": parent_identity,
        "fresh_confirmation_required": True,
    }


def classify_ordinary_customer_workflow(
    *, customer_instruction: str, selected_paths: Sequence[str]
) -> str:
    """Select one D-079 workflow from ordinary language without an internal flag."""

    normalized = " ".join(customer_instruction.casefold().split())
    evidence_language = "review" in normalized and (
        "selected file" in normalized or "these files" in normalized or "this file" in normalized
    )
    if evidence_language:
        if not selected_paths:
            raise D079WorkflowError(
                _recovery(
                    "selected_artifact_required",
                    offending_class="ordinary_language_invocation",
                    field="selected_paths",
                    category="retain_instruction_and_request_exact_native_client_selection",
                    local_preprocessing="native_client_exact_file_selection",
                )
            )
        return "local_first_evidence_review"
    planning_language = any(
        token in normalized
        for token in (
            "algorithm blueprint",
            "generation context",
            "design a",
            "design the",
            "build a",
            "create a",
            "plan a",
        )
    )
    quantum_program_subject = any(
        token in normalized
        for token in ("quantum program", "quantum circuit", "circuit", "qiskit", "bell-state")
    )
    blueprint_language = (
        "algorithm blueprint" in normalized
        or "generation context" in normalized
        or (planning_language and quantum_program_subject)
    )
    if blueprint_language:
        return "ide_first_blueprint_decision_and_confirmation"
    raise D079WorkflowError(
        _recovery(
            "ordinary_language_workflow_not_identified",
            offending_class="ordinary_language_invocation",
            field="customer_instruction",
            category="ask_one_bounded_workflow_clarification",
            valid_portions_retained=True,
        )
    )


def classify_binding_default_route(
    *, customer_instruction: str, selected_paths: Sequence[str] = ()
) -> dict[str, Any]:
    """Apply the binding's authoritative workstyle precedence to one request."""

    normalized = " ".join(customer_instruction.casefold().split())
    contract = binding_default_routing_contract()
    if not normalized:
        selected_route = "available_inactive"
        return {
            "schema_id": "qcoder.connected_assistant.route_decision.v1",
            "selected_route": selected_route,
            "action": "none",
            "matched_named_workflow": None,
            "named_d079_route_preceded_generic_single_capability": False,
            "deterministic_single_route": True,
            "raw_mcp_default_entrypoint": False,
            "routing_contract": contract["schema_id"],
        }
    request_semantics = classify_current_request(
        customer_instruction,
        active_loop=False,
        selected_paths=selected_paths,
    )
    workflow: str | None = None
    if request_semantics["requested_operation"] == "selected_artifact_review":
        if request_semantics["clarification_required"]:
            raise D079WorkflowError(
                _recovery(
                    "selected_artifact_required",
                    offending_class="ordinary_language_invocation",
                    field="selected_paths",
                    category="retain_instruction_and_request_exact_native_client_selection",
                    local_preprocessing="native_client_exact_file_selection",
                )
            )
        workflow = "local_first_evidence_review"
    if request_semantics["route"] == "active_build":
        return {
            "schema_id": "qcoder.connected_assistant.route_decision.v1",
            "selected_route": "active_build",
            "action": "call_binding_owned_begin_current_loop",
            "operation": "begin_current_loop",
            "matched_named_workflow": "d080_current_request_semantics",
            "request_semantics": request_semantics,
            "named_d079_route_preceded_generic_single_capability": True,
            "customer_constructs_operation_envelope": False,
            "deterministic_single_route": True,
            "raw_mcp_default_entrypoint": False,
            "routing_contract": contract["schema_id"],
        }
    if request_semantics["requested_operation"] in {"informational", "setup_guidance"}:
        return {
            "schema_id": "qcoder.connected_assistant.route_decision.v1",
            "selected_route": "available_inactive",
            "action": "none",
            "matched_named_workflow": None,
            "request_semantics": request_semantics,
            "named_d079_route_preceded_generic_single_capability": False,
            "deterministic_single_route": True,
            "raw_mcp_default_entrypoint": False,
            "routing_contract": contract["schema_id"],
        }
    if request_semantics["route"] == "clarification_required":
        return {
            "schema_id": "qcoder.connected_assistant.route_decision.v1",
            "selected_route": "clarification_required",
            "action": "ask_one_concise_stage_clarification",
            "matched_named_workflow": "d080_current_request_semantics",
            "request_semantics": request_semantics,
            "named_d079_route_preceded_generic_single_capability": True,
            "deterministic_single_route": True,
            "raw_mcp_default_entrypoint": False,
            "routing_contract": contract["schema_id"],
        }
    if workflow is None:
        try:
            workflow = classify_ordinary_customer_workflow(
                customer_instruction=customer_instruction,
                selected_paths=selected_paths,
            )
        except D079WorkflowError as exc:
            if exc.recovery.get("reason_category") == "selected_artifact_required":
                raise
            workflow = None
    if workflow is None and request_semantics["route"] == "available_inactive":
        return {
            "schema_id": "qcoder.connected_assistant.route_decision.v1",
            "selected_route": "available_inactive",
            "action": "none",
            "matched_named_workflow": None,
            "request_semantics": request_semantics,
            "named_d079_route_preceded_generic_single_capability": False,
            "deterministic_single_route": True,
            "raw_mcp_default_entrypoint": False,
            "routing_contract": contract["schema_id"],
        }
    if workflow is not None:
        route_id = (
            "algorithm_blueprint_generation_context"
            if workflow == "ide_first_blueprint_decision_and_confirmation"
            else "selected_file_evidence_review"
        )
        named = contract["named_workflows"][route_id]
        return {
            "schema_id": "qcoder.connected_assistant.route_decision.v1",
            "selected_route": "named_d079_workflow",
            "action": named["action"],
            "operation": named["operation"],
            "subcommand": named["subcommand"],
            "matched_named_workflow": route_id,
            "workflow": workflow,
            "named_d079_route_preceded_generic_single_capability": True,
            "customer_constructs_operation_envelope": False,
            "raw_mcp_default_entrypoint": False,
            "deterministic_single_route": True,
            "routing_contract": contract["schema_id"],
        }
    return {
        "schema_id": "qcoder.connected_assistant.route_decision.v1",
        "selected_route": "single_capability",
        "action": "use_applicable_mcp_tool",
        "matched_named_workflow": None,
        "named_d079_route_preceded_generic_single_capability": False,
        "raw_mcp_default_entrypoint": True,
        "deterministic_single_route": True,
        "routing_contract": contract["schema_id"],
    }


def execute_ordinary_connected_assistant_workflow(
    *,
    customer_instruction: str,
    selected_paths: Sequence[str],
    blueprint_context: Mapping[str, Any] | None,
    protected_call: ProtectedCall,
    proposal: Mapping[str, Any] | None = None,
    confirmation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute the binding-owned route selected from the customer's ordinary words."""

    route_decision = classify_binding_default_route(
        customer_instruction=customer_instruction,
        selected_paths=selected_paths,
    )
    if route_decision.get("selected_route") != "named_d079_workflow":
        raise D079WorkflowError(
            _recovery(
                "binding_owned_operation_route_mismatch",
                offending_class="ordinary_language_invocation",
                field="customer_instruction",
                category="apply_authoritative_default_route_fallthrough",
                valid_portions_retained=True,
            )
        )
    selected_workflow = str(route_decision["workflow"])
    common = {
        "schema_id": "qcoder.connected_assistant.d079_execution.v1",
        "ok": True,
        "selected_workflow": selected_workflow,
        "route_source": "ordinary_customer_language",
        "machine_readable_route_decision": route_decision,
        "binding_owned_local_invocation": True,
        "customer_internal_choreography_required": False,
        "public_mcp_tool_added": False,
        "retention": "process_and_discard",
        "persistent": False,
    }
    if selected_workflow == "local_first_evidence_review":
        result = review_selected_files_with_qcoder(
            selected_paths=selected_paths,
            protected_call=protected_call,
        )
        return {**common, "workflow_result": result, "terminal_state": "Result Review"}
    if proposal is not None or confirmation is not None:
        if proposal is None or confirmation is None:
            raise D079WorkflowError(
                _recovery(
                    "incomplete_confirmation_invocation",
                    offending_class="ordinary_language_invocation",
                    category="retain_reviewed_proposal_and_request_exact_customer_confirmation",
                    valid_portions_retained=True,
                )
            )
        child = confirm_ide_first_blueprint(proposal=proposal, confirmation=confirmation)
        materialized = materialize_confirmed_blueprint_workflow(
            proposal=proposal,
            confirmed_child=child,
            protected_call=protected_call,
        )
        return {
            **common,
            "workflow_result": materialized,
            "terminal_state": "Generation Context",
        }
    if not isinstance(blueprint_context, Mapping):
        raise D079WorkflowError(
            _recovery(
                "assistant_structuring_required",
                offending_class="ordinary_language_invocation",
                field="blueprint_context",
                category="assistant_structure_request_without_claiming_customer_provenance",
                valid_portions_retained=True,
            )
        )
    prepared = prepare_ide_first_blueprint(
        customer_request=customer_instruction,
        explicit_user_facts=blueprint_context.get("explicit_user_facts", {}),
        assistant_structuring=blueprint_context.get("assistant_structuring", {}),
        assistant_implementation_proposals=blueprint_context.get(
            "assistant_implementation_proposals", {}
        ),
        customer_dispositions=blueprint_context.get("customer_dispositions", {}),
        current_step_controls=blueprint_context.get("current_step_controls", ()),
        durable_constraints=blueprint_context.get("durable_constraints", ()),
        explicitly_promoted_controls=blueprint_context.get("explicitly_promoted_controls", ()),
        profile_id=str(blueprint_context.get("profile_id") or "generic_qiskit"),
        current_lineage_reference=blueprint_context.get("current_lineage_reference"),
    )
    return {
        **common,
        "workflow_result": prepared,
        "terminal_state": "Customer confirmation required",
    }


def materialize_confirmed_blueprint_workflow(
    *,
    proposal: Mapping[str, Any],
    confirmed_child: Mapping[str, Any],
    protected_call: ProtectedCall,
) -> dict[str, Any]:
    """Materialize canonical Intent/Blueprint/Generation artifacts after confirmation."""

    structure = proposal.get("semantic_layers", {}).get("assistant_structuring")
    if not isinstance(structure, Mapping):
        raise D079WorkflowError(
            _recovery(
                "malformed_proposal",
                offending_class="assistant_structuring",
                field="semantic_layers.assistant_structuring",
                category="retain_valid_proposal_and_complete_missing_structure",
                valid_portions_retained=True,
            )
        )
    required = (
        "normalized_goal",
        "problem_size_meaning",
        "framework_requirement",
        "measurement_plan",
        "execution_intent",
        "desired_output",
    )
    missing = [name for name in required if not structure.get(name)]
    if missing:
        raise D079WorkflowError(
            _recovery(
                "malformed_proposal",
                offending_class="assistant_structuring",
                field=missing[0],
                category="retain_valid_proposal_and_complete_missing_structure",
                valid_portions_retained=True,
            )
        )
    records = proposal.get("decision_records")
    if not isinstance(records, list) or not records:
        raise D079WorkflowError(
            _recovery(
                "missing_decision_records",
                offending_class="proposal_integrity",
                field="decision_records",
                category="regenerate_reviewable_proposal",
            )
        )
    decision_references = {
        str(item["profile_decision_id"]): str(item["decision_ref"])
        for item in records
        if isinstance(item, Mapping)
    }
    common = {
        "artifact_kind": "share_safe_evidence_summary",
        "decision_loop": DECISION_AWARE_PATH,
        "profile_decision_catalog_version": PROFILE_DECISION_CATALOG_VERSION,
        "current_lineage_reference": proposal["current_lineage_reference"],
    }
    intent_response = dict(
        protected_call(
            "create_algorithm_intent_card",
            {
                "original_user_intent": proposal["semantic_layers"][
                    "original_customer_request_verbatim"
                ],
                "profile_id": proposal["profile_id"],
                "proposed_interpretation": deepcopy(dict(structure)),
                "requirements": [],
                "constraints": deepcopy(
                    proposal["semantic_layers"]["durable_blueprint_constraints"]
                ),
                "non_goals": [],
                "field_provenance": {name: "connected_assistant" for name in structure}
                | {"original_user_intent": "user"},
                "requested_confirmation_state": "confirmed",
                "confirmation_assertion": {"user_reviewed": True},
                "decision_dispositions": deepcopy(records),
                "decision_references": decision_references,
                **common,
            },
        )
    )
    if (
        intent_response.get("ok") is not True
        or intent_response.get("context_status") != "algorithm_intent_card_ready"
        or not process_and_discard_retention_satisfied(
            structured_evidence=intent_response,
            expected_tool_name="create_algorithm_intent_card",
        )
    ):
        raise D079WorkflowError(
            _recovery(
                "canonical_intent_materialization_failed",
                offending_class="protected_blueprint_workflow",
                category="retain_confirmed_child_and_retry_same_exact_proposal",
                valid_portions_retained=True,
                protected_safe_error_category=str(
                    intent_response.get("error_category") or "structured_contract_failure"
                ),
            )
        )
    intent_card = intent_response.get("algorithm_intent_card")
    if not isinstance(intent_card, Mapping) or intent_card.get("confirmation_state") != "confirmed":
        raise D079WorkflowError(
            _recovery(
                "canonical_intent_not_confirmed",
                offending_class="protected_blueprint_workflow",
                category="retain_confirmed_child_and_return_customer_boundary",
                valid_portions_retained=True,
            )
        )
    blueprint_response = dict(
        protected_call(
            "create_implementation_blueprint",
            {
                "algorithm_intent_card": deepcopy(dict(intent_card)),
                "intent_relationship": {
                    "relationship_type": "represented_by",
                    "parent_artifact_digest": intent_card["artifact_digest"],
                },
                **common,
            },
        )
    )
    if (
        blueprint_response.get("ok") is not True
        or blueprint_response.get("context_status") != "implementation_blueprint_ready"
        or not process_and_discard_retention_satisfied(
            structured_evidence=blueprint_response,
            expected_tool_name="create_implementation_blueprint",
        )
    ):
        raise D079WorkflowError(
            _recovery(
                "canonical_blueprint_materialization_failed",
                offending_class="protected_blueprint_workflow",
                category="retain_confirmed_child_and_retry_same_exact_proposal",
                valid_portions_retained=True,
            )
        )
    blueprint = blueprint_response.get("implementation_blueprint")
    output_contract = blueprint_response.get("output_evidence_contract")
    if not isinstance(blueprint, Mapping) or not isinstance(output_contract, Mapping):
        raise D079WorkflowError(
            _recovery(
                "canonical_blueprint_response_malformed",
                offending_class="protected_blueprint_workflow",
                category="retain_confirmed_child_and_fail_closed",
                valid_portions_retained=True,
            )
        )
    generation_response = dict(
        protected_call(
            "create_generation_context_pack",
            {
                "implementation_blueprint": deepcopy(dict(blueprint)),
                "output_evidence_contract": deepcopy(dict(output_contract)),
                **common,
            },
        )
    )
    if (
        generation_response.get("ok") is not True
        or generation_response.get("context_status") != "generation_context_pack_ready"
        or generation_response.get("generation_context_pack_produced") is not True
        or not process_and_discard_retention_satisfied(
            structured_evidence=generation_response,
            expected_tool_name="create_generation_context_pack",
        )
    ):
        raise D079WorkflowError(
            _recovery(
                "canonical_generation_context_failed",
                offending_class="protected_blueprint_workflow",
                category="retain_confirmed_child_and_retry_same_exact_proposal",
                valid_portions_retained=True,
            )
        )
    return {
        "confirmed_semantic_child": deepcopy(dict(confirmed_child)),
        "algorithm_intent_card": deepcopy(dict(intent_card)),
        "implementation_blueprint": deepcopy(dict(blueprint)),
        "output_evidence_contract": deepcopy(dict(output_contract)),
        "generation_context_pack": deepcopy(generation_response["generation_context_pack"]),
        "protected_call_sequence": [
            "create_algorithm_intent_card",
            "create_implementation_blueprint",
            "create_generation_context_pack",
        ],
        "automatic_same_workflow_continuation": True,
        "customer_internal_choreography_required": False,
        "retention": "process_and_discard",
        "persistent": False,
    }


def _safe_artifact_identity(item: Mapping[str, Any]) -> dict[str, Any]:
    value = item.get("input") if isinstance(item.get("input"), Mapping) else {}
    return {
        "position": item.get("position"),
        "kind": value.get("kind"),
        "selection": "explicit_customer_selected_artifact",
        "content_identity": _digest(
            {
                "canonical_artifacts": item.get("canonical_artifacts", []),
                "status": item.get("status"),
            }
        ),
    }


def _protected_projection(report: Mapping[str, Any], safe: Mapping[str, Any]) -> dict[str, Any]:
    artifacts = []
    for item in safe.get("artifacts", []):
        if not isinstance(item, Mapping):
            continue
        artifacts.append(
            {
                "position": item.get("position"),
                "status": item.get("status"),
                "input_kind": (
                    item.get("input", {}).get("kind")
                    if isinstance(item.get("input"), Mapping)
                    else None
                ),
                "established": deepcopy(item.get("established", [])),
                "not_established": deepcopy(item.get("not_established", [])),
                "limitations": deepcopy(item.get("limitations", [])),
            }
        )
    return {
        "schema_id": "qcoder.connected_assistant.protected_evidence_projection.v1",
        "status": report.get("status"),
        "coverage": "complete_for_supported_local_extractors"
        if report.get("status") == "completed"
        else "partial_or_limited",
        "artifacts": artifacts,
        "excluded": [
            "local_paths",
            "raw_python",
            "raw_qasm",
            "raw_counts",
            "notebooks",
            "repository_content",
        ],
        "retention": "process_and_discard",
    }


def _assert_protected_projection(value: Any) -> None:
    def walk(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                if str(key).casefold() in _FORBIDDEN_PROTECTED_KEYS:
                    raise D079WorkflowError(
                        _recovery(
                            "raw_or_path_protected_misroute",
                            offending_class="protected_payload",
                            field=str(key),
                            category="process_locally_then_send_share_safe_projection",
                            local_preprocessing="local_qcoder_evidence_and_share_safe_derivation",
                            valid_portions_retained=True,
                        )
                    )
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)
        elif isinstance(item, str) and _PATH_TEXT.search(item):
            raise D079WorkflowError(
                _recovery(
                    "local_path_protected_misroute",
                    offending_class="protected_payload",
                    category="process_locally_then_send_share_safe_projection",
                    local_preprocessing="local_qcoder_evidence_and_share_safe_derivation",
                    valid_portions_retained=True,
                )
            )

    walk(value)
    if len(_canonical_bytes(value)) > MAX_PROTECTED_EVIDENCE_BYTES:
        raise D079WorkflowError(
            _recovery(
                "protected_projection_limit_exceeded",
                offending_class="protected_payload",
                category="reduce_share_safe_semantic_coverage_with_explicit_omission_receipt",
                valid_portions_retained=True,
            )
        )


ProtectedCall = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]


def review_selected_files_with_qcoder(
    *,
    selected_paths: Sequence[str],
    protected_call: ProtectedCall,
    python_profile: str = "generic_qiskit",
) -> dict[str, Any]:
    """Run exact-selection local processing and continue only to Result Review."""

    resolved: list[Path] = []
    try:
        resolved = resolve_explicit_files(selected_paths)
        report = build_local_evidence_review(selected_paths, python_profile=python_profile)
        safe = build_share_safe_local_evidence_review(report, selected_paths, opt_ins={})
    except LocalEvidenceError as exc:
        message = str(exc)
        category = (
            "selected_artifact_limit"
            if "limit" in message
            else "unsupported_or_invalid_selected_artifact"
        )
        recovery = _recovery(
            category,
            offending_class="selected_artifact",
            category="correct_exact_selection_and_retry_local_processing",
            local_preprocessing="local_qcoder_evidence",
        )
        if category == "selected_artifact_limit" and resolved:
            safe_selected = []
            for position, path in enumerate(resolved, start=1):
                digest = sha256()
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                safe_selected.append(
                    {
                        "position": position,
                        "selection": "exact_customer_selected_artifact",
                        "content_identity": digest.hexdigest(),
                        "raw_artifact_bytes": path.stat().st_size,
                    }
                )
            recovery["limit_receipt"] = {
                "schema_id": "qcoder.connected_assistant.selected_artifact_limit.v1",
                "coverage_status": "LIMITED",
                "local_processing_result": "supported_selected_artifact_size_limit",
                "selected_artifacts": safe_selected,
                "selected_artifact_count": len(safe_selected),
                "raw_artifact_remained_local": True,
                "protected_request_bytes": 0,
                "protected_transfer_performed": False,
                "silent_truncation": False,
                "downstream_complete_status_permitted": False,
                "recovery": "Segment into explicitly selected supported artifacts and retry the same local-first workflow.",
            }
        raise D079WorkflowError(recovery) from exc
    projection = _protected_projection(report, safe)
    _assert_protected_projection(projection)
    receipt = {
        "selected_artifact_identities": [
            _safe_artifact_identity(item)
            for item in report.get("artifacts", [])
            if isinstance(item, Mapping)
        ],
        "selected_artifact_count": len(resolved),
        "selection_authority": "exact_customer_selected_files_only",
        "local_processing_occurred": True,
        "canonical_local_evidence_created": True,
        "share_safe_derivative_created": True,
        "protected_content_class": "bounded_share_safe_semantic_evidence",
        "remained_local": [
            "paths",
            "raw_python",
            "raw_qasm",
            "raw_counts",
            "notebooks",
            "repository_content",
        ],
        "coverage": projection["coverage"],
        "omissions": deepcopy(projection["excluded"]),
        "repository_discovery_performed": False,
        "neighboring_file_inspection_performed": False,
    }
    calls: list[str] = []
    try:
        guided = dict(
            protected_call(
                "get_guided_evidence_context",
                {
                    "artifact_kind": "share_safe_evidence_summary",
                    "artifact_text": json.dumps(projection, sort_keys=True),
                },
            )
        )
    except Exception as exc:
        raise D079WorkflowError(
            _recovery(
                "protected_rejection_or_transport_failure",
                offending_class="protected_enrichment",
                category="retain_local_evidence_and_retry_or_skip_enrichment",
                valid_portions_retained=True,
            )
        ) from exc
    calls.append("get_guided_evidence_context")
    first = evaluate_named_workflow_result(
        workflow_name="Evidence Review",
        tool_name="get_guided_evidence_context",
        structured_result=guided,
    )
    if first["classification"] != NON_TERMINAL_PREPARATORY:
        raise D079WorkflowError(
            _recovery(
                "continuation_failure",
                offending_class="workflow_continuation",
                category="retain_local_evidence_and_return_genuine_blocker",
                valid_portions_retained=True,
            )
        )
    result_review = dict(
        protected_call(
            str(first["next_tool_name"]),
            {
                "artifact_kind": "share_safe_evidence_summary",
                "share_safe_evidence_summary": projection,
                "evidence_basis": "local_canonical_plus_share_safe_projection",
            },
        )
    )
    calls.append(str(first["next_tool_name"]))
    final = evaluate_named_workflow_result(
        workflow_name="Evidence Review",
        tool_name="create_result_review_context_card",
        structured_result=result_review,
        prior_tool_names=calls[:-1],
    )
    if final["classification"] != CUSTOMER_TERMINAL_OUTCOME:
        raise D079WorkflowError(
            _recovery(
                "result_review_not_ready",
                offending_class="workflow_terminality",
                category="return_genuine_blocker_without_broadening_scope",
                valid_portions_retained=True,
            )
        )
    for name, response in (
        ("get_guided_evidence_context", guided),
        ("create_result_review_context_card", result_review),
    ):
        if not process_and_discard_retention_satisfied(
            structured_evidence=response, expected_tool_name=name
        ):
            raise D079WorkflowError(
                _recovery(
                    "retention_evidence_missing",
                    offending_class="protected_response",
                    category="fail_closed_on_retention_contract",
                    valid_portions_retained=True,
                )
            )
    return {
        "schema_id": EVIDENCE_WORKFLOW_SCHEMA_ID,
        "schema_version": 1,
        "status": "result_review_ready",
        "local_canonical_evidence": report,
        "share_safe_derivative": safe,
        "protected_projection": projection,
        "local_processing_receipt": receipt,
        "protected_result_review": result_review,
        "continuation": {
            "calls": calls,
            "automatic": True,
            "terminal": "Result Review",
            "unrelated_work_continued": False,
        },
        "authority": {
            "native_client_read_authority": True,
            "qcoder_discovery_authority": False,
            "qcoder_edit_authority": False,
            "qcoder_run_authority": False,
        },
        "retention": "process_and_discard",
        "persistent": False,
    }


def scale_limit_receipt(*, selected_path: str, effective_gate_magnitude: int) -> dict[str, Any]:
    """Return a truthful structured limit outcome without reading beyond the exact file."""

    path = Path(selected_path).expanduser().absolute()
    if not path.is_file() or path.is_symlink():
        raise D079WorkflowError(
            _recovery(
                "invalid_scale_fixture",
                offending_class="selected_artifact",
                category="select_exact_regular_file",
            )
        )
    size = path.stat().st_size
    outcome = {
        "schema_id": "qcoder.connected_assistant.large_artifact_limit.v1",
        "selected_artifact_identity": sha256(path.read_bytes()).hexdigest(),
        "raw_artifact_bytes": size,
        "effective_gate_magnitude": int(effective_gate_magnitude),
        "coverage_status": "limited",
        "local_processing_result": "structured_limit_before_full_parse",
        "omitted": ["per_gate_expansion", "full_canonical_circuit_manifestation"],
        "silent_truncation": False,
        "raw_artifact_remained_local": True,
        "protected_request_bytes": 0,
        "protected_transfer_performed": False,
        "recovery": "segment into explicitly selected supported artifacts or use a supported bounded envelope",
        "retention": "process_and_discard",
    }
    outcome["receipt_bytes"] = len(_canonical_bytes(outcome))
    return outcome
