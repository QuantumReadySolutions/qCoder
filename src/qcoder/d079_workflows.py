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

from qcoder.blueprint_decisions import (
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
DECISION_AWARE_PATH = "readiness_resolution_v1"
MAX_PROTECTED_EVIDENCE_BYTES = 131_072

_TEMPORARY_CONTROL_PATTERNS = (
    re.compile(r"\bdo not (?:edit|run)(?:\s+yet)?\b", re.IGNORECASE),
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


def d079_orchestration_contract_snapshot(tool_inventory: Sequence[str]) -> dict[str, Any]:
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
) -> dict[str, Any]:
    return {
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


def _catalog_lookup(profile_id: str) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
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
    lookup: dict[str, dict[str, Any]] = {}
    for item in entries:
        lookup[item["profile_decision_id"]] = item
        lookup[item["profile_decision_id"].split(".", 1)[1]] = item
        for name in item["intent_fields"] + item["blueprint_fields"]:
            lookup.setdefault(name, item)
    return entries, lookup


def _resolve_decision_key(key: str, lookup: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    entry = lookup.get(key)
    if entry is None:
        raise D079WorkflowError(
            _recovery(
                "unknown_decision_field",
                offending_class="decision_input",
                field=key,
                category="use_catalog_field_or_question",
                valid_portions_retained=True,
            )
        )
    return entry


def _stable_decision_refs(profile_id: str, lineage: str, entries: Sequence[Mapping[str, Any]]) -> dict[str, str]:
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
            {"profile_decision_id": decision_id, "decision_ref": refs[decision_id], "disposition": kind}
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
    promoted = {str(item) for item in explicitly_promoted_controls}
    durable = list(dict.fromkeys([str(item) for item in durable_constraints] + [x for x in temporary if x in promoted]))
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
            {"text": item, "recognized_current_step_control": _is_temporary_control(item), "promoted_to_durable": item in promoted}
            for item in temporary
        ],
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
    proposal_ref = _opaque("proposal", f"{lineage}|{proposal_digest}")
    proposal_body["artifact_identity"] = proposal_ref
    proposal_body["proposal_digest"] = proposal_digest
    proposal_body["confirmation_requirements"] = {
        "artifact_identity": proposal_ref,
        "artifact_revision": 1,
        "parent_lineage_identity": lineage,
        "proposal_digest": proposal_digest,
        "exact_proposal_reviewed": True,
    }
    entries_by_id = {str(item["profile_decision_id"]): item for item in entries}
    proposal_body["customer_confirmation_projection"] = {
        "what_you_said": customer_request,
        "facts_you_supplied": [
            {
                "field": entries_by_id[decision_id]["display_label"],
                "value": deepcopy(value),
            }
            for decision_id, value in facts.items()
        ],
        "how_your_request_was_structured": deepcopy(dict(assistant_structuring)),
        "proposed_implementation_choices": [
            {
                "field": entries_by_id[decision_id]["display_label"],
                "proposal": deepcopy(value),
            }
            for decision_id, value in proposals.items()
        ],
        "unresolved_or_delegated_choices": [
            {"question": entry["question"], "state": record["resolution_state"]}
            for entry, record in zip(entries, records)
            if record["resolution_state"] != "resolved"
            and (entry["generation_relevant"] or record["user_disposition"] != "not_supplied")
        ],
        "confirmation_will_change": "Create a new confirmed child artifact bound to this exact proposal.",
        "confirmation_will_not_change": "The reviewed proposal, current-step controls, file/edit/run authority, and original request.",
        "internal_identifiers_required_from_customer": False,
    }
    return proposal_body


def confirm_ide_first_blueprint(*, proposal: Mapping[str, Any], confirmation: Mapping[str, Any]) -> dict[str, Any]:
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
    required = proposal.get("confirmation_requirements")
    if not isinstance(required, Mapping):
        raise D079WorkflowError(
            _recovery(
                "missing_lineage",
                offending_class="proposal_integrity",
                field="confirmation_requirements",
                category="regenerate_reviewable_proposal",
            )
        )
    checks = (
        ("artifact_identity", "incorrect_confirmation_reference"),
        ("artifact_revision", "stale_revision"),
        ("parent_lineage_identity", "missing_or_stale_lineage"),
        ("proposal_digest", "digest_mismatch"),
    )
    for field, category in checks:
        if confirmation.get(field) != required.get(field):
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
    body_for_digest = {
        key: deepcopy(value)
        for key, value in proposal.items()
        if key not in {"artifact_identity", "proposal_digest", "confirmation_requirements", "customer_confirmation_projection"}
    }
    if _digest(body_for_digest) != required.get("proposal_digest"):
        raise D079WorkflowError(
            _recovery(
                "digest_mismatch",
                offending_class="proposal_integrity",
                field="proposal_digest",
                category="review_current_exact_proposal",
            )
        )
    readiness = proposal.get("readiness")
    if not isinstance(readiness, Mapping) or readiness.get("aggregate_readiness_result") == "blocked_pending_decisions":
        blocking = [] if not isinstance(readiness, Mapping) else list(readiness.get("blocking_decision_references") or [])
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
            "original_customer_request_verbatim": proposal["semantic_layers"]["original_customer_request_verbatim"],
            "explicit_user_facts": deepcopy(proposal["semantic_layers"]["explicit_user_facts"]),
            "durable_constraints": deepcopy(proposal["semantic_layers"]["durable_blueprint_constraints"]),
            "decision_records": deepcopy(proposal["decision_records"]),
        },
        "implementation_blueprint": {
            "assistant_structuring": deepcopy(proposal["semantic_layers"]["assistant_structuring"]),
            "implementation_choices": deepcopy(proposal["semantic_layers"]["assistant_implementation_proposals"]),
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
                "field_provenance": {
                    name: "connected_assistant" for name in structure
                }
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
        "coverage": "complete_for_supported_local_extractors" if report.get("status") == "completed" else "partial_or_limited",
        "artifacts": artifacts,
        "excluded": ["local_paths", "raw_python", "raw_qasm", "raw_counts", "notebooks", "repository_content"],
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
        raise D079WorkflowError(
            _recovery(
                category,
                offending_class="selected_artifact",
                category="correct_exact_selection_and_retry_local_processing",
                local_preprocessing="local_qcoder_evidence",
            )
        ) from exc
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
        "remained_local": ["paths", "raw_python", "raw_qasm", "raw_counts", "notebooks", "repository_content"],
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
                {"artifact_kind": "share_safe_evidence_summary", "artifact_text": json.dumps(projection, sort_keys=True)},
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
    for name, response in (("get_guided_evidence_context", guided), ("create_result_review_context_card", result_review)):
        if not process_and_discard_retention_satisfied(structured_evidence=response, expected_tool_name=name):
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
        "continuation": {"calls": calls, "automatic": True, "terminal": "Result Review", "unrelated_work_continued": False},
        "authority": {"native_client_read_authority": True, "qcoder_discovery_authority": False, "qcoder_edit_authority": False, "qcoder_run_authority": False},
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
