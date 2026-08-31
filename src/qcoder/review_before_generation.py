"""Deterministic review-before-generation proposal validation and projection.

The connected assistant authors the semantic interpretation and substantive
recommendations.  qCoder only validates their exact request binding, authority
ceiling, share-safe structure, substantiveness, and deterministic revision.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import re
from typing import Any, Mapping, Sequence

from qcoder.core.share_safe import contains_local_path, contains_token_or_header


PROPOSAL_SCHEMA_ID = "qcoder.connected_assistant.review_before_generation_proposal.v1"
SEMANTICS_SCHEMA_ID = "qcoder.current_loop.review_before_generation_semantics.v1"
FIRST_VALUE_SCHEMA_ID = "qcoder.current_loop.review_before_generation_first_value.v1"
TRANSACTION_SCHEMA_ID = "qcoder.current_loop.review_before_generation_transaction.v1"
CONTRACT_SCHEMA_ID = "qcoder.current_loop.review_before_generation_contract.v1"

PROPOSAL_ATTRIBUTION = "connected_assistant"
ITEM_ATTRIBUTIONS = (
    "customer_explicit_constraint",
    "connected_assistant_recommendation",
    "qcoder_deterministic_boundary",
)
ULTIMATE_OUTCOMES = (
    "source_generation",
    "source_modification",
    "qasm_generation",
    "execution",
    "evidence_review",
    "selected_artifact_review",
    "informational_answer",
    "unsupported_capability",
)
IMMEDIATE_INTERACTIONS = (
    "review_proposed_intent_and_implementation",
    "review_proposed_changes",
    "produce_artifact",
    "review_selected_artifact",
    "review_selected_evidence",
    "answer",
    "bounded_limitation",
    "clarify_contradiction",
)
TEMPORAL_ORDERS = (
    "review_then_confirm_before_generation",
    "review_then_confirm_before_modification",
    "generate_now",
    "answer_now",
    "not_applicable",
)
REVIEW_OBJECTS = (
    "proposed_intent_and_implementation",
    "proposed_changes",
    "selected_artifact",
    "selected_evidence",
    "none",
)
GENERATION_AUTHORITIES = (
    "held_for_exact_review_confirmation",
    "granted_for_current_request",
    "not_requested",
)
EXECUTION_AUTHORITIES = (
    "not_requested",
    "separately_held",
    "explicitly_requested_requires_separate_authority",
)
GROUPS = (
    ("goal_and_scope", "Goal and scope"),
    ("implementation", "Implementation"),
    ("output_and_authority", "Output and authority"),
)
CUSTOMER_ACTIONS = ("Use recommended choices", "Review or change choices")

_PLACEHOLDERS = {
    "tbd",
    "todo",
    "unknown",
    "unspecified",
    "generic approach",
    "details not assumed",
    "remaining details are not assumed",
    "as requested",
}
_CONSEQUENTIAL_IMPLEMENTATION_TERMS = (
    "framework",
    "construction",
    "representation",
    "mapping",
    "operation",
    "circuit",
    "oracle",
    "diffusion",
    "ansatz",
    "correction",
)
_FORBIDDEN_FIELD_FRAGMENTS = (
    "token",
    "password",
    "secret",
    "credential",
    "authorization",
    "authentication",
    "profile",
    "configuration",
    "reasoning_trace",
    "model_metadata",
    "raw_output",
    "raw_stream",
)


class ReviewBeforeGenerationError(ValueError):
    """Bounded customer-safe proposal or transaction rejection."""

    def __init__(self, category: str, *, clarification: str | None = None):
        self.category = category
        self.clarification = clarification
        super().__init__(category)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_json(value: Any) -> str:
    """Return the product's stable human-readable JSON form."""

    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _digest(value: Any) -> str:
    return sha256(_canonical_bytes(value)).hexdigest()


def _request_digest(exact_request: str) -> str:
    return sha256(exact_request.encode("utf-8")).hexdigest()


def _bounded_text(value: Any, *, category: str, maximum: int = 2_000) -> str:
    if not isinstance(value, str):
        raise ReviewBeforeGenerationError(category)
    result = value.strip()
    if not result or len(result.encode("utf-8")) > maximum:
        raise ReviewBeforeGenerationError(category)
    if result.casefold() in _PLACEHOLDERS:
        raise ReviewBeforeGenerationError("review_proposal_not_substantive")
    return result


def _strict_keys(value: Mapping[str, Any], expected: set[str], category: str) -> None:
    if set(value) != expected:
        raise ReviewBeforeGenerationError(category)


def _privacy_error(value: Any, *, key: str = "") -> bool:
    if any(fragment in key.casefold().replace("-", "_") for fragment in _FORBIDDEN_FIELD_FRAGMENTS):
        return True
    if isinstance(value, Mapping):
        return any(_privacy_error(child, key=str(child_key)) for child_key, child in value.items())
    if isinstance(value, (list, tuple)):
        return any(_privacy_error(child, key=key) for child in value)
    if isinstance(value, str):
        return contains_local_path(value) or contains_token_or_header(value)
    return False


def _validate_item(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ReviewBeforeGenerationError("review_proposal_item_invalid")
    _strict_keys(
        value, {"item_id", "label", "value", "attribution"}, "review_proposal_item_invalid"
    )
    item = {
        "item_id": _bounded_text(
            value.get("item_id"), category="review_proposal_item_invalid", maximum=80
        ),
        "label": _bounded_text(
            value.get("label"), category="review_proposal_item_invalid", maximum=160
        ),
        "value": _bounded_text(value.get("value"), category="review_proposal_item_invalid"),
        "attribution": str(value.get("attribution") or ""),
    }
    if item["attribution"] not in ITEM_ATTRIBUTIONS:
        raise ReviewBeforeGenerationError("review_proposal_attribution_invalid")
    return item


def _validate_group(value: Any, expected_id: str, expected_label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ReviewBeforeGenerationError("review_proposal_group_invalid")
    _strict_keys(value, {"group_id", "label", "items"}, "review_proposal_group_invalid")
    if value.get("group_id") != expected_id or value.get("label") != expected_label:
        raise ReviewBeforeGenerationError("review_proposal_group_invalid")
    items_value = value.get("items")
    if not isinstance(items_value, list) or not items_value or len(items_value) > 24:
        raise ReviewBeforeGenerationError("review_proposal_group_not_substantive")
    items = [_validate_item(item) for item in items_value]
    if len({item["item_id"] for item in items}) != len(items):
        raise ReviewBeforeGenerationError("review_proposal_item_duplicate")
    return {"group_id": expected_id, "label": expected_label, "items": items}


def _validate_choice(value: Any, *, deferred: bool) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ReviewBeforeGenerationError("review_proposal_choice_invalid")
    value_key = "deferred_value" if deferred else "recommended_value"
    _strict_keys(
        value,
        {"choice_id", "label", value_key, "attribution"},
        "review_proposal_choice_invalid",
    )
    result = {
        "choice_id": _bounded_text(
            value.get("choice_id"), category="review_proposal_choice_invalid", maximum=80
        ),
        "label": _bounded_text(
            value.get("label"), category="review_proposal_choice_invalid", maximum=160
        ),
        value_key: _bounded_text(value.get(value_key), category="review_proposal_choice_invalid"),
        "attribution": str(value.get("attribution") or ""),
    }
    if result["attribution"] not in ITEM_ATTRIBUTIONS:
        raise ReviewBeforeGenerationError("review_proposal_attribution_invalid")
    return result


def _validate_limitation(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ReviewBeforeGenerationError("review_proposal_limitation_invalid")
    _strict_keys(value, {"item_id", "value", "attribution"}, "review_proposal_limitation_invalid")
    result = {
        "item_id": _bounded_text(
            value.get("item_id"), category="review_proposal_limitation_invalid", maximum=80
        ),
        "value": _bounded_text(value.get("value"), category="review_proposal_limitation_invalid"),
        "attribution": str(value.get("attribution") or ""),
    }
    if result["attribution"] not in ITEM_ATTRIBUTIONS:
        raise ReviewBeforeGenerationError("review_proposal_attribution_invalid")
    return result


def _unquoted_request(exact_request: str) -> str:
    return re.sub(r'(["“]).*?(["”])', " ", exact_request, flags=re.DOTALL)


def _validate_request_authority(exact_request: str, axes: Mapping[str, str]) -> None:
    request = " ".join(_unquoted_request(exact_request).casefold().split())
    if "qcoder" not in request:
        raise ReviewBeforeGenerationError("review_request_does_not_activate_qcoder")
    review_terms = (
        "review",
        "check",
        "validate",
        "vet",
        "sanity-check",
        "align on",
        "walk through",
        "explain assumptions",
        "explain choices",
        "confirm the approach",
    )
    source_terms = ("code", "program", "source", "file", "implementation", "qiskit", "qasm")
    if axes["immediate_interaction"] in {
        "review_proposed_intent_and_implementation",
        "review_proposed_changes",
    }:
        if not any(term in request for term in review_terms) or not any(
            term in request for term in source_terms
        ):
            raise ReviewBeforeGenerationError("review_proposal_request_semantics_mismatch")
    if axes["generation_authority"] == "held_for_exact_review_confirmation" and re.search(
        r"\b(?:generate|write|create|modify|change)\b.{0,40}\b(?:now|immediately|before review)\b",
        request,
    ):
        raise ReviewBeforeGenerationError(
            "review_request_authority_contradiction",
            clarification=(
                "Should source be produced now, or only after you confirm the proposed choices?"
            ),
        )
    execution_negated = bool(
        re.search(
            r"\b(?:do not|don't|never|without)\b.{0,48}\b(?:run|execute|simulate|execution)\b",
            request,
        )
        or re.search(r"\b(?:run|execute|execution)\b.{0,32}\b(?:later|deferred)\b", request)
    )
    if execution_negated and axes["execution_authority"] == (
        "explicitly_requested_requires_separate_authority"
    ):
        raise ReviewBeforeGenerationError("review_proposal_execution_authority_broadened")


def validate_connected_assistant_proposal(
    exact_request: str,
    proposal: Mapping[str, Any],
    *,
    selected_artifact_identities: Sequence[str] = (),
) -> dict[str, Any]:
    """Validate one exact-request-bound connected-assistant proposal."""

    if not isinstance(exact_request, str) or not exact_request or len(exact_request) > 20_000:
        raise ReviewBeforeGenerationError("review_exact_request_invalid")
    if not isinstance(proposal, Mapping):
        raise ReviewBeforeGenerationError("review_connected_assistant_proposal_required")
    expected = {
        "schema_id",
        "schema_version",
        "proposal_attribution",
        "exact_request_utf8_sha256",
        "semantic_axes",
        "recommended_interpretation",
        "review_groups",
        "material_choices",
        "deferred_choices",
        "limitations_nonclaims",
        "blocking_clarification",
        "retention",
    }
    _strict_keys(proposal, expected, "review_proposal_schema_invalid")
    if (
        proposal.get("schema_id") != PROPOSAL_SCHEMA_ID
        or proposal.get("schema_version") != 1
        or proposal.get("proposal_attribution") != PROPOSAL_ATTRIBUTION
        or proposal.get("retention") != "process_and_discard"
    ):
        raise ReviewBeforeGenerationError("review_proposal_contract_invalid")
    if proposal.get("exact_request_utf8_sha256") != _request_digest(exact_request):
        raise ReviewBeforeGenerationError("review_proposal_request_digest_mismatch")
    axes_value = proposal.get("semantic_axes")
    if not isinstance(axes_value, Mapping):
        raise ReviewBeforeGenerationError("review_proposal_semantic_axes_invalid")
    _strict_keys(
        axes_value,
        {
            "ultimate_outcome",
            "immediate_interaction",
            "temporal_order",
            "review_object",
            "generation_authority",
            "execution_authority",
        },
        "review_proposal_semantic_axes_invalid",
    )
    axes = {key: str(axes_value[key]) for key in axes_value}
    allowed = {
        "ultimate_outcome": ULTIMATE_OUTCOMES,
        "immediate_interaction": IMMEDIATE_INTERACTIONS,
        "temporal_order": TEMPORAL_ORDERS,
        "review_object": REVIEW_OBJECTS,
        "generation_authority": GENERATION_AUTHORITIES,
        "execution_authority": EXECUTION_AUTHORITIES,
    }
    if any(axes[key] not in allowed[key] for key in allowed):
        raise ReviewBeforeGenerationError("review_proposal_semantic_axes_invalid")
    review_pair = (
        axes["immediate_interaction"],
        axes["temporal_order"],
        axes["review_object"],
        axes["generation_authority"],
    )
    permitted_review_pairs = {
        (
            "review_proposed_intent_and_implementation",
            "review_then_confirm_before_generation",
            "proposed_intent_and_implementation",
            "held_for_exact_review_confirmation",
        ),
        (
            "review_proposed_changes",
            "review_then_confirm_before_modification",
            "proposed_changes",
            "held_for_exact_review_confirmation",
        ),
    }
    if review_pair not in permitted_review_pairs:
        raise ReviewBeforeGenerationError("review_proposal_route_not_review_before_generation")
    if axes["ultimate_outcome"] == "source_modification" and not selected_artifact_identities:
        raise ReviewBeforeGenerationError(
            "review_source_modification_selection_required",
            clarification="Which exact source file should the proposed changes apply to?",
        )
    if axes["review_object"] in {"selected_artifact", "selected_evidence"} and not (
        selected_artifact_identities
    ):
        raise ReviewBeforeGenerationError("review_selected_artifact_required")
    _validate_request_authority(exact_request, axes)

    interpretation = _bounded_text(
        proposal.get("recommended_interpretation"),
        category="review_proposal_interpretation_invalid",
        maximum=4_000,
    )
    if interpretation.casefold() == exact_request.strip().casefold():
        raise ReviewBeforeGenerationError("review_proposal_goal_restatement_only")
    groups_value = proposal.get("review_groups")
    if not isinstance(groups_value, list) or len(groups_value) != len(GROUPS):
        raise ReviewBeforeGenerationError("review_proposal_exact_three_groups_required")
    groups = [
        _validate_group(value, expected_id, expected_label)
        for value, (expected_id, expected_label) in zip(groups_value, GROUPS, strict=True)
    ]
    implementation_text = " ".join(
        f"{item['item_id']} {item['label']} {item['value']}" for item in groups[1]["items"]
    ).casefold()
    if not any(term in implementation_text for term in _CONSEQUENTIAL_IMPLEMENTATION_TERMS):
        raise ReviewBeforeGenerationError("review_proposal_implementation_not_consequential")
    output_item_ids = {item["item_id"] for item in groups[2]["items"]}
    if not {
        "artifact_after_confirmation",
        "generation_authority",
        "execution_authority",
    }.issubset(output_item_ids):
        raise ReviewBeforeGenerationError("review_proposal_output_authority_incomplete")

    choices_value = proposal.get("material_choices")
    deferred_value = proposal.get("deferred_choices")
    limitations_value = proposal.get("limitations_nonclaims")
    if not isinstance(choices_value, list) or not choices_value or len(choices_value) > 32:
        raise ReviewBeforeGenerationError("review_proposal_material_choices_required")
    if not isinstance(deferred_value, list) or len(deferred_value) > 32:
        raise ReviewBeforeGenerationError("review_proposal_deferred_choices_invalid")
    if (
        not isinstance(limitations_value, list)
        or not limitations_value
        or len(limitations_value) > 32
    ):
        raise ReviewBeforeGenerationError("review_proposal_limitations_required")
    choices = [_validate_choice(value, deferred=False) for value in choices_value]
    deferred = [_validate_choice(value, deferred=True) for value in deferred_value]
    limitations = [_validate_limitation(value) for value in limitations_value]
    all_choice_ids = [item["choice_id"] for item in [*choices, *deferred]]
    if len(all_choice_ids) != len(set(all_choice_ids)):
        raise ReviewBeforeGenerationError("review_proposal_choice_duplicate")
    blocking = proposal.get("blocking_clarification")
    if blocking is not None:
        blocking = _bounded_text(
            blocking,
            category="review_proposal_blocking_clarification_invalid",
            maximum=600,
        )
    normalized = {
        "schema_id": PROPOSAL_SCHEMA_ID,
        "schema_version": 1,
        "proposal_attribution": PROPOSAL_ATTRIBUTION,
        "exact_request_utf8_sha256": _request_digest(exact_request),
        "semantic_axes": axes,
        "recommended_interpretation": interpretation,
        "review_groups": groups,
        "material_choices": choices,
        "deferred_choices": deferred,
        "limitations_nonclaims": limitations,
        "blocking_clarification": blocking,
        "retention": "process_and_discard",
    }
    if _privacy_error(normalized):
        raise ReviewBeforeGenerationError("review_proposal_private_material_rejected")
    return normalized


def build_review_before_generation_semantics(
    exact_request: str,
    proposal: Mapping[str, Any],
    *,
    selected_artifact_identities: Sequence[str] = (),
) -> dict[str, Any]:
    validated = validate_connected_assistant_proposal(
        exact_request,
        proposal,
        selected_artifact_identities=selected_artifact_identities,
    )
    axes = deepcopy(validated["semantic_axes"])
    result = {
        "schema_id": SEMANTICS_SCHEMA_ID,
        "schema_version": 1,
        "exact_request_utf8_sha256": _request_digest(exact_request),
        "semantic_axes": axes,
        "selected_artifact_identity_sha256": [
            sha256(value.encode("utf-8")).hexdigest()
            for value in sorted(selected_artifact_identities)
        ],
        "route": "binding_owned_review_before_generation",
        "operation": "begin_current_loop",
        "one_operation_before_useful_review": True,
        "source_generation_permitted_before_confirmation": False,
        "source_modification_permitted_before_confirmation": False,
        "execution_permitted": False,
        "selected_file_review_inferred": False,
        "protected_service_required": False,
        "qcoder_authors_recommendations": False,
    }
    result["semantics_digest"] = _digest(result)
    return result


def review_revision(
    exact_request: str,
    proposal: Mapping[str, Any],
    *,
    selected_artifact_identities: Sequence[str] = (),
) -> str:
    validated = validate_connected_assistant_proposal(
        exact_request,
        proposal,
        selected_artifact_identities=selected_artifact_identities,
    )
    return "review-revision-" + _digest(
        {
            "exact_request": exact_request,
            "exact_request_utf8_sha256": _request_digest(exact_request),
            "connected_assistant_proposal": validated,
            "selected_artifact_identity_sha256": [
                sha256(value.encode("utf-8")).hexdigest()
                for value in sorted(selected_artifact_identities)
            ],
            "privacy_safe_projection": True,
        }
    )


def build_first_value(
    exact_request: str,
    proposal: Mapping[str, Any],
    *,
    selected_artifact_identities: Sequence[str] = (),
) -> dict[str, Any]:
    validated = validate_connected_assistant_proposal(
        exact_request,
        proposal,
        selected_artifact_identities=selected_artifact_identities,
    )
    semantics = build_review_before_generation_semantics(
        exact_request,
        validated,
        selected_artifact_identities=selected_artifact_identities,
    )
    revision = review_revision(
        exact_request,
        validated,
        selected_artifact_identities=selected_artifact_identities,
    )
    confirmable = validated["blocking_clarification"] is None
    return {
        "schema_id": FIRST_VALUE_SCHEMA_ID,
        "schema_version": 1,
        "recommended_interpretation": validated["recommended_interpretation"],
        "review_revision": revision,
        "exact_request_utf8_sha256": _request_digest(exact_request),
        "proposal_attribution": PROPOSAL_ATTRIBUTION,
        "semantic_axes": deepcopy(validated["semantic_axes"]),
        "initial_decision_groups": deepcopy(validated["review_groups"]),
        "initial_decision_group_count": 3,
        "initial_decision_group_maximum": 3,
        "material_choices": deepcopy(validated["material_choices"]),
        "deferred_choices": deepcopy(validated["deferred_choices"]),
        "limitations_nonclaims": deepcopy(validated["limitations_nonclaims"]),
        "blocking_clarification": validated["blocking_clarification"],
        "confirmable": confirmable,
        "customer_actions": list(CUSTOMER_ACTIONS) if confirmable else [],
        "confirmation_state": "awaiting_exact_review_confirmation" if confirmable else "blocked",
        "generation_authority": validated["semantic_axes"]["generation_authority"],
        "execution_authority": validated["semantic_axes"]["execution_authority"],
        "one_qcoder_operation_before_useful_review": True,
        "source_or_qasm_included": False,
        "file_mutation_performed": False,
        "execution_performed": False,
        "protected_service_called": False,
        "qcoder_authored_recommendation": False,
        "retention": "current_loop_only_process_and_discard",
        "semantics_digest": semantics["semantics_digest"],
    }


def render_first_value_markdown(value: Mapping[str, Any]) -> str:
    if value.get("schema_id") != FIRST_VALUE_SCHEMA_ID:
        raise ReviewBeforeGenerationError("review_first_value_invalid")
    lines = ["# Review before generation", "", str(value["recommended_interpretation"]), ""]
    for group in value["initial_decision_groups"]:
        lines.extend([f"## {group['label']}", ""])
        for item in group["items"]:
            lines.append(f"- **{item['label']}:** {item['value']}")
        lines.append("")
    if value["deferred_choices"]:
        lines.extend(["## Deferred choices", ""])
        for item in value["deferred_choices"]:
            lines.append(f"- **{item['label']}:** {item['deferred_value']}")
        lines.append("")
    lines.extend(["## Limitations and nonclaims", ""])
    for item in value["limitations_nonclaims"]:
        lines.append(f"- {item['value']}")
    lines.extend(["", f"Revision: `{value['review_revision']}`", ""])
    if value["customer_actions"]:
        lines.extend(["## Actions", ""])
        lines.extend(f"- {action}" for action in value["customer_actions"])
        lines.append("")
    elif value.get("blocking_clarification"):
        lines.extend(["## Clarification needed", "", str(value["blocking_clarification"]), ""])
    return "\n".join(lines)


def contract_snapshot() -> dict[str, Any]:
    return {
        "schema_id": CONTRACT_SCHEMA_ID,
        "schema_version": 1,
        "proposal_schema_id": PROPOSAL_SCHEMA_ID,
        "semantics_schema_id": SEMANTICS_SCHEMA_ID,
        "first_value_schema_id": FIRST_VALUE_SCHEMA_ID,
        "transaction_schema_id": TRANSACTION_SCHEMA_ID,
        "proposal_attribution": PROPOSAL_ATTRIBUTION,
        "semantic_axes": [
            "ultimate_outcome",
            "immediate_interaction",
            "temporal_order",
            "review_object",
            "generation_authority",
            "execution_authority",
        ],
        "initial_groups": [label for _, label in GROUPS],
        "customer_actions": list(CUSTOMER_ACTIONS),
        "one_operation_before_useful_review": True,
        "backward_compatible_optional_begin_input": True,
        "protected_service_required": False,
        "qcoder_authors_recommendations": False,
        "process_and_discard": True,
        "new_public_tool": False,
        "new_private_operation": False,
    }


def proposal_input_schema() -> dict[str, Any]:
    """Return the strict additive input schema carried by begin_current_loop."""

    item = {
        "type": "object",
        "properties": {
            "item_id": {"type": "string", "minLength": 1, "maxLength": 80},
            "label": {"type": "string", "minLength": 1, "maxLength": 160},
            "value": {"type": "string", "minLength": 1, "maxLength": 2000},
            "attribution": {"type": "string", "enum": list(ITEM_ATTRIBUTIONS)},
        },
        "required": ["item_id", "label", "value", "attribution"],
        "additionalProperties": False,
    }
    choice = {
        "type": "object",
        "properties": {
            "choice_id": {"type": "string", "minLength": 1, "maxLength": 80},
            "label": {"type": "string", "minLength": 1, "maxLength": 160},
            "recommended_value": {"type": "string", "minLength": 1, "maxLength": 2000},
            "attribution": {"type": "string", "enum": list(ITEM_ATTRIBUTIONS)},
        },
        "required": ["choice_id", "label", "recommended_value", "attribution"],
        "additionalProperties": False,
    }
    deferred = deepcopy(choice)
    deferred["properties"]["deferred_value"] = deferred["properties"].pop("recommended_value")
    deferred["required"] = ["choice_id", "label", "deferred_value", "attribution"]
    limitation = {
        "type": "object",
        "properties": {
            "item_id": {"type": "string", "minLength": 1, "maxLength": 80},
            "value": {"type": "string", "minLength": 1, "maxLength": 2000},
            "attribution": {"type": "string", "enum": list(ITEM_ATTRIBUTIONS)},
        },
        "required": ["item_id", "value", "attribution"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "schema_id": {"const": PROPOSAL_SCHEMA_ID},
            "schema_version": {"const": 1},
            "proposal_attribution": {"const": PROPOSAL_ATTRIBUTION},
            "exact_request_utf8_sha256": {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            },
            "semantic_axes": {
                "type": "object",
                "properties": {
                    "ultimate_outcome": {"type": "string", "enum": list(ULTIMATE_OUTCOMES)},
                    "immediate_interaction": {
                        "type": "string",
                        "enum": list(IMMEDIATE_INTERACTIONS),
                    },
                    "temporal_order": {"type": "string", "enum": list(TEMPORAL_ORDERS)},
                    "review_object": {"type": "string", "enum": list(REVIEW_OBJECTS)},
                    "generation_authority": {
                        "type": "string",
                        "enum": list(GENERATION_AUTHORITIES),
                    },
                    "execution_authority": {
                        "type": "string",
                        "enum": list(EXECUTION_AUTHORITIES),
                    },
                },
                "required": [
                    "ultimate_outcome",
                    "immediate_interaction",
                    "temporal_order",
                    "review_object",
                    "generation_authority",
                    "execution_authority",
                ],
                "additionalProperties": False,
            },
            "recommended_interpretation": {
                "type": "string",
                "minLength": 1,
                "maxLength": 4000,
            },
            "review_groups": {
                "type": "array",
                "minItems": 3,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "group_id": {"type": "string"},
                        "label": {"type": "string"},
                        "items": {"type": "array", "minItems": 1, "maxItems": 24, "items": item},
                    },
                    "required": ["group_id", "label", "items"],
                    "additionalProperties": False,
                },
            },
            "material_choices": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "items": choice,
            },
            "deferred_choices": {"type": "array", "maxItems": 32, "items": deferred},
            "limitations_nonclaims": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "items": limitation,
            },
            "blocking_clarification": {
                "type": ["string", "null"],
                "maxLength": 600,
            },
            "retention": {"const": "process_and_discard"},
        },
        "required": [
            "schema_id",
            "schema_version",
            "proposal_attribution",
            "exact_request_utf8_sha256",
            "semantic_axes",
            "recommended_interpretation",
            "review_groups",
            "material_choices",
            "deferred_choices",
            "limitations_nonclaims",
            "blocking_clarification",
            "retention",
        ],
        "additionalProperties": False,
    }


__all__ = [
    "CONTRACT_SCHEMA_ID",
    "CUSTOMER_ACTIONS",
    "FIRST_VALUE_SCHEMA_ID",
    "PROPOSAL_SCHEMA_ID",
    "ReviewBeforeGenerationError",
    "SEMANTICS_SCHEMA_ID",
    "TRANSACTION_SCHEMA_ID",
    "build_first_value",
    "build_review_before_generation_semantics",
    "canonical_json",
    "contract_snapshot",
    "proposal_input_schema",
    "render_first_value_markdown",
    "review_revision",
    "validate_connected_assistant_proposal",
]
