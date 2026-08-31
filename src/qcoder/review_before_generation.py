"""Deterministic review-before-generation validation and projection.

The connected assistant supplies the semantic interpretation and substantive
recommendations. qCoder owns request binding, fixed structure, attribution,
authority, projection safety, revision integrity, and confirmation boundaries.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import re
from typing import Any, Mapping, Sequence

from qcoder.core.share_safe import contains_local_path, contains_token_or_header


PROPOSAL_SCHEMA_ID = "qcoder.connected_assistant.review_before_generation_proposal.v2"
SEMANTICS_SCHEMA_ID = "qcoder.current_loop.review_before_generation_semantics.v1"
FIRST_VALUE_SCHEMA_ID = "qcoder.current_loop.review_before_generation_first_value.v2"
TRANSACTION_SCHEMA_ID = "qcoder.current_loop.review_before_generation_transaction.v2"
CONTRACT_SCHEMA_ID = "qcoder.current_loop.review_before_generation_contract.v2"

PROPOSAL_ATTRIBUTION = "connected_assistant"
CONNECTED_ASSISTANT_ATTRIBUTION = "connected_assistant_recommendation"
CUSTOMER_ATTRIBUTION = "customer_explicit_constraint"
QCODER_ATTRIBUTION = "qcoder_deterministic_boundary"
GROUPS = (
    ("goal_and_scope", "Goal and scope"),
    ("implementation", "Implementation"),
    ("output_and_authority", "Output and authority"),
)
CUSTOMER_ACTIONS = ("Use recommended choices", "Review or change choices")
TRANSACTION_KINDS = (
    "review_before_source_generation",
    "review_before_source_modification",
)
EXECUTION_REQUESTS = ("not_requested", "held_for_separate_authorization")

_PLACEHOLDERS = {
    "tbd",
    "todo",
    "unknown",
    "unspecified",
    "placeholder",
    "generic approach",
    "details not assumed",
    "remaining details are not assumed",
    "as requested",
    "a concrete option will be used",
    "a framework will be selected",
    "use an appropriate approach",
    "use a suitable implementation",
    "follow best practices",
    "implement as requested",
    "details will be determined",
    "a standard method will be used",
    "the remaining choices are not assumed",
}
_FORBIDDEN_FIELD_FRAGMENTS = (
    "token",
    "password",
    "secret",
    "credential",
    "authorization_header",
    "authentication",
    "profile_storage",
    "private_configuration",
    "reasoning_trace",
    "model_metadata",
    "raw_output",
    "raw_stream",
)
_CONSEQUENTIAL_VALUE = re.compile(
    r"\b(?:qiskit|quantumcircuit|cirq|pennylane|python|rust|javascript|openqasm|"
    r"circuit|register|qubit|classical bit|oracle|diffusion|ansatz|mixer|cost layer|"
    r"mapping|representation|measurement|measure|apply h|apply cx|cnot|conditional|"
    r"function|module|class|json|readable source)\b",
    re.IGNORECASE,
)
_PYTHON_SOURCE_PATTERNS = (
    re.compile(r"\bfrom\s+qiskit(?:\.[A-Za-z_][\w.]*)?\s+import\b", re.IGNORECASE),
    re.compile(r"\bimport\s+qiskit\b", re.IGNORECASE),
    re.compile(r"\bQuantumCircuit\s*\("),
    re.compile(r"\.(?:h|cx|measure|x|y|z|reset|barrier)\s*\("),
    re.compile(r"\bdef\s+[A-Za-z_]\w*\s*\([^)]*\)\s*:"),
    re.compile(r"\b[A-Za-z_]\w*\s*=\s*[A-Za-z_]\w*\s*\([^)]*\)"),
)
_QASM_SOURCE_PATTERNS = (
    re.compile(r"\bOPENQASM\s+\d", re.IGNORECASE),
    re.compile(r"\binclude\s+[\"'][^\"']+[\"']\s*;", re.IGNORECASE),
    re.compile(r"\b(?:qubit|bit)\s*\[[^\]]+\]\s+[A-Za-z_]\w*\s*;", re.IGNORECASE),
    re.compile(r"\b(?:measure|reset|barrier)\b[^\n;]*;", re.IGNORECASE),
    re.compile(r"\b(?:h|x|y|z|cx|cz|swap)\s+[A-Za-z_$][^\n;]*;", re.IGNORECASE),
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


def request_digest(exact_request: str) -> str:
    """Compute the authoritative digest from exact received UTF-8 request bytes."""

    return sha256(exact_request.encode("utf-8")).hexdigest()


def _strict_keys(value: Mapping[str, Any], expected: set[str], category: str) -> None:
    if set(value) != expected:
        raise ReviewBeforeGenerationError(category)


def _privacy_error(value: Any, *, key: str = "") -> bool:
    normalized_key = key.casefold().replace("-", "_")
    if any(fragment in normalized_key for fragment in _FORBIDDEN_FIELD_FRAGMENTS):
        return True
    if isinstance(value, Mapping):
        return any(_privacy_error(child, key=str(child_key)) for child_key, child in value.items())
    if isinstance(value, (list, tuple)):
        return any(_privacy_error(child, key=key) for child in value)
    if isinstance(value, str):
        return contains_local_path(value) or contains_token_or_header(value)
    return False


def _contains_source_or_qasm(value: str) -> bool:
    if "```" in value or "~~~" in value:
        return True
    return any(
        pattern.search(value) for pattern in (*_PYTHON_SOURCE_PATTERNS, *_QASM_SOURCE_PATTERNS)
    )


def _unsafe_projection_text(value: str) -> bool:
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return True
    if re.search(r"^\s*#{1,6}\s", value):
        return True
    if re.search(r"!?\[[^\]]+\]\([^)]*\)", value):
        return True
    if re.search(r"<\s*/?\s*(?:script|style|iframe|object|embed|button|form|a)\b", value, re.I):
        return True
    if re.search(r"\b(?:Use recommended choices|Review or change choices)\b", value):
        return True
    return bool(
        re.search(
            r"\b(?:tools/call|inputSchema|connected_assistant_proposal|customer_actions)\b",
            value,
            re.IGNORECASE,
        )
    )


def _bounded_plain_text(value: Any, *, category: str, maximum: int = 2_000) -> str:
    if not isinstance(value, str):
        raise ReviewBeforeGenerationError(category)
    result = value.strip()
    if not result or len(result.encode("utf-8")) > maximum:
        raise ReviewBeforeGenerationError(category)
    if result.casefold().rstrip(".") in _PLACEHOLDERS:
        raise ReviewBeforeGenerationError("review_proposal_not_substantive")
    if _unsafe_projection_text(result):
        raise ReviewBeforeGenerationError("review_proposal_unsafe_projection_text")
    if _contains_source_or_qasm(result):
        raise ReviewBeforeGenerationError("review_proposal_source_or_qasm_rejected")
    if contains_local_path(result) or contains_token_or_header(result):
        raise ReviewBeforeGenerationError("review_proposal_private_material_rejected")
    return result


def _markdown_escape(value: str) -> str:
    escaped = value.replace("\\", "\\\\")
    for character in ("`", "*", "_", "[", "]", "<", ">", "#", "|"):
        escaped = escaped.replace(character, "\\" + character)
    return escaped


def _unquoted_request(exact_request: str) -> str:
    return re.sub(r'(["“]).*?(["”])', " ", exact_request, flags=re.DOTALL)


def _semantic_axes(transaction_kind: str, execution_request: str) -> dict[str, str]:
    if transaction_kind == "review_before_source_generation":
        ultimate_outcome = "source_generation"
        immediate_interaction = "review_proposed_intent_and_implementation"
        temporal_order = "review_then_confirm_before_generation"
        review_object = "proposed_intent_and_implementation"
    elif transaction_kind == "review_before_source_modification":
        ultimate_outcome = "source_modification"
        immediate_interaction = "review_proposed_changes"
        temporal_order = "review_then_confirm_before_modification"
        review_object = "proposed_changes"
    else:
        raise ReviewBeforeGenerationError("review_proposal_transaction_kind_invalid")
    execution_authority = (
        "not_requested"
        if execution_request == "not_requested"
        else "explicitly_requested_requires_separate_authority"
    )
    return {
        "ultimate_outcome": ultimate_outcome,
        "immediate_interaction": immediate_interaction,
        "temporal_order": temporal_order,
        "review_object": review_object,
        "generation_authority": "held_for_exact_review_confirmation",
        "execution_authority": execution_authority,
    }


def _validate_request_authority(exact_request: str, axes: Mapping[str, str]) -> None:
    request = " ".join(_unquoted_request(exact_request).casefold().split())
    if re.search(r"\buse\s+qcoder\b", request) is None:
        raise ReviewBeforeGenerationError("review_request_does_not_activate_qcoder")
    if axes["generation_authority"] == "held_for_exact_review_confirmation" and re.search(
        r"\b(?:generate|write|create|modify|change)\b.{0,40}\b(?:now|immediately|before review)\b",
        request,
    ):
        raise ReviewBeforeGenerationError(
            "review_request_authority_contradiction",
            clarification="Should source be produced now, or only after you confirm the choices?",
        )
    execution_negated = bool(
        re.search(
            r"\b(?:do not|don't|never|without)\b.{0,48}\b(?:run|execute|simulate|execution)\b",
            request,
        )
        or re.search(r"\b(?:run|execute|execution)\b.{0,32}\b(?:later|deferred)\b", request)
    )
    if execution_negated and axes["execution_authority"] != "not_requested":
        raise ReviewBeforeGenerationError("review_proposal_execution_authority_broadened")


def _assistant_values_contradict_authority(values: Sequence[str], axes: Mapping[str, str]) -> bool:
    for value in values:
        text = " ".join(value.casefold().split())
        if axes["generation_authority"] == "held_for_exact_review_confirmation" and (
            re.search(r"\b(?:generate|create|write|modify)\b.{0,30}\b(?:now|immediately)\b", text)
            or re.search(
                r"\b(?:generation|source generation|file mutation)\b.{0,24}\b"
                r"(?:authorized|permitted|allowed)\b.{0,12}\bnow\b",
                text,
            )
            or re.search(
                r"\b(?:generate|create|write|modify)\b.{0,30}\bbefore confirmation\b", text
            )
        ):
            return True
        if re.search(
            r"\b(?:execute|run|simulate)\b.{0,24}\b(?:now|immediately|on hardware)\b",
            text,
        ):
            return True
        if re.search(r"\b(?:execution|simulation)\b.{0,20}\b(?:authorized|permitted)\b", text):
            if "not authorized" not in text and "separate authorization" not in text:
                return True
        if re.search(r"\b(?:submit|submission)\b.{0,20}\b(?:backend|hardware)\b", text):
            return True
        if re.search(r"\bconfirmation\b.{0,24}\b(?:grants|authorizes)\b.{0,16}\bexecution\b", text):
            return True
        if re.search(r"\bqcoder\b.{0,16}\b(?:executed|ran|submitted|simulated)\b", text):
            return True
    return False


def _is_consequential(value: str) -> bool:
    text = " ".join(value.casefold().split()).rstrip(".")
    if text in _PLACEHOLDERS:
        return False
    return bool(_CONSEQUENTIAL_VALUE.search(value))


def _assistant_item(label: str, value: str) -> dict[str, str]:
    return {"label": label, "value": value, "attribution": CONNECTED_ASSISTANT_ATTRIBUTION}


def _qcoder_item(label: str, value: str) -> dict[str, str]:
    return {"label": label, "value": value, "attribution": QCODER_ATTRIBUTION}


def _authority_items(axes: Mapping[str, str]) -> list[dict[str, str]]:
    generation = (
        "Source modification remains held until the stored displayed review is confirmed."
        if axes["ultimate_outcome"] == "source_modification"
        else "Python source is produced only after the stored displayed review is confirmed."
    )
    execution = (
        "Execution was not requested and is not authorized."
        if axes["execution_authority"] == "not_requested"
        else "Execution remains held for separate authorization and is not authorized by this review."
    )
    return [
        _qcoder_item("Generation authority", generation),
        _qcoder_item("Execution authority", execution),
        _qcoder_item(
            "Authority separation",
            "Confirmation of source generation does not authorize execution.",
        ),
    ]


def validate_connected_assistant_proposal(
    exact_request: str,
    proposal: Mapping[str, Any],
    *,
    selected_artifact_identities: Sequence[str] = (),
) -> dict[str, Any]:
    """Validate and normalize one assistant-authored semantic proposal."""

    if not isinstance(exact_request, str) or not exact_request or len(exact_request) > 20_000:
        raise ReviewBeforeGenerationError("review_exact_request_invalid")
    if not isinstance(proposal, Mapping):
        raise ReviewBeforeGenerationError("review_connected_assistant_proposal_required")
    expected = {
        "schema_id",
        "schema_version",
        "transaction_kind",
        "execution_request",
        "recommended_interpretation",
        "customer_constraints",
        "implementation_recommendations",
        "material_choices",
        "output_artifact",
        "deferred_choices",
        "limitations_nonclaims",
        "blocking_clarification",
    }
    _strict_keys(proposal, expected, "review_proposal_schema_invalid")
    if proposal.get("schema_id") != PROPOSAL_SCHEMA_ID or proposal.get("schema_version") != 2:
        raise ReviewBeforeGenerationError("review_proposal_contract_invalid")
    transaction_kind = str(proposal.get("transaction_kind") or "")
    execution_request = str(proposal.get("execution_request") or "")
    if transaction_kind not in TRANSACTION_KINDS or execution_request not in EXECUTION_REQUESTS:
        raise ReviewBeforeGenerationError("review_proposal_semantic_mode_invalid")
    axes = _semantic_axes(transaction_kind, execution_request)
    if transaction_kind == "review_before_source_modification" and not selected_artifact_identities:
        raise ReviewBeforeGenerationError(
            "review_source_modification_selection_required",
            clarification="Which exact source file should the proposed changes apply to?",
        )
    _validate_request_authority(exact_request, axes)

    interpretation = _bounded_plain_text(
        proposal.get("recommended_interpretation"),
        category="review_proposal_interpretation_invalid",
        maximum=4_000,
    )
    if (
        interpretation.casefold() == exact_request.strip().casefold()
        or len(interpretation.split()) < 7
    ):
        raise ReviewBeforeGenerationError("review_proposal_goal_restatement_only")

    constraint_values = proposal.get("customer_constraints")
    if (
        not isinstance(constraint_values, list)
        or not constraint_values
        or len(constraint_values) > 16
    ):
        raise ReviewBeforeGenerationError("review_proposal_customer_constraints_invalid")
    constraints: list[str] = []
    for value in constraint_values:
        excerpt = _bounded_plain_text(
            value, category="review_proposal_customer_constraint_invalid", maximum=500
        )
        if excerpt not in exact_request:
            raise ReviewBeforeGenerationError("review_proposal_customer_constraint_not_in_request")
        constraints.append(excerpt)
    if len(set(constraints)) != len(constraints):
        raise ReviewBeforeGenerationError("review_proposal_customer_constraint_duplicate")

    recommendation_values = proposal.get("implementation_recommendations")
    if (
        not isinstance(recommendation_values, list)
        or not recommendation_values
        or len(recommendation_values) > 24
    ):
        raise ReviewBeforeGenerationError("review_proposal_implementation_required")
    recommendations = [
        _bounded_plain_text(value, category="review_proposal_implementation_invalid")
        for value in recommendation_values
    ]
    if not any(_is_consequential(value) for value in recommendations):
        raise ReviewBeforeGenerationError("review_proposal_implementation_not_consequential")

    choices_value = proposal.get("material_choices")
    if not isinstance(choices_value, list) or not choices_value or len(choices_value) > 24:
        raise ReviewBeforeGenerationError("review_proposal_material_choices_required")
    choices: list[dict[str, str]] = []
    for value in choices_value:
        if not isinstance(value, Mapping):
            raise ReviewBeforeGenerationError("review_proposal_choice_invalid")
        _strict_keys(value, {"choice", "recommendation"}, "review_proposal_choice_invalid")
        choice = _bounded_plain_text(
            value.get("choice"), category="review_proposal_choice_invalid", maximum=160
        )
        recommendation = _bounded_plain_text(
            value.get("recommendation"), category="review_proposal_choice_invalid"
        )
        choices.append({"choice": choice, "recommendation": recommendation})
    if len({item["choice"].casefold() for item in choices}) != len(choices):
        raise ReviewBeforeGenerationError("review_proposal_choice_duplicate")

    output_artifact = _bounded_plain_text(
        proposal.get("output_artifact"), category="review_proposal_output_artifact_invalid"
    )
    if _assistant_values_contradict_authority([output_artifact], axes):
        raise ReviewBeforeGenerationError("review_proposal_authority_contradiction")
    if not re.search(
        r"\b(?:python|source|code|program|file|qasm|script|module)\b", output_artifact, re.I
    ):
        raise ReviewBeforeGenerationError("review_proposal_output_artifact_not_concrete")

    deferred_value = proposal.get("deferred_choices")
    limitations_value = proposal.get("limitations_nonclaims")
    if not isinstance(deferred_value, list) or len(deferred_value) > 24:
        raise ReviewBeforeGenerationError("review_proposal_deferred_choices_invalid")
    if (
        not isinstance(limitations_value, list)
        or not limitations_value
        or len(limitations_value) > 24
    ):
        raise ReviewBeforeGenerationError("review_proposal_limitations_required")
    deferred = [
        _bounded_plain_text(value, category="review_proposal_deferred_choice_invalid")
        for value in deferred_value
    ]
    limitations = [
        _bounded_plain_text(value, category="review_proposal_limitation_invalid")
        for value in limitations_value
    ]
    blocking = proposal.get("blocking_clarification")
    if blocking is not None:
        blocking = _bounded_plain_text(
            blocking, category="review_proposal_blocking_clarification_invalid", maximum=600
        )

    assistant_values = [
        interpretation,
        *recommendations,
        *(item["recommendation"] for item in choices),
        output_artifact,
        *deferred,
        *limitations,
        *([blocking] if isinstance(blocking, str) else []),
    ]
    if _assistant_values_contradict_authority(assistant_values, axes):
        raise ReviewBeforeGenerationError("review_proposal_authority_contradiction")

    goal_items = [_assistant_item("Recommended interpretation", interpretation)] + [
        {"label": "Customer constraint", "value": value, "attribution": CUSTOMER_ATTRIBUTION}
        for value in constraints
    ]
    implementation_items = [
        _assistant_item(f"Implementation recommendation {index}", value)
        for index, value in enumerate(recommendations, start=1)
    ]
    implementation_items.extend(
        [
            _qcoder_item("Dependency version", "No dependency version was selected silently."),
            _qcoder_item(
                "Execution environment", "No execution environment was selected silently."
            ),
        ]
    )
    output_items = [_assistant_item("Output artifact", output_artifact), *_authority_items(axes)]
    groups = [
        {"group_id": GROUPS[0][0], "label": GROUPS[0][1], "items": goal_items},
        {"group_id": GROUPS[1][0], "label": GROUPS[1][1], "items": implementation_items},
        {"group_id": GROUPS[2][0], "label": GROUPS[2][1], "items": output_items},
    ]
    normalized = {
        "schema_id": PROPOSAL_SCHEMA_ID,
        "schema_version": 2,
        "proposal_attribution": PROPOSAL_ATTRIBUTION,
        "exact_request_utf8_sha256": request_digest(exact_request),
        "transaction_kind": transaction_kind,
        "execution_request": execution_request,
        "semantic_axes": axes,
        "recommended_interpretation": interpretation,
        "customer_constraints": constraints,
        "implementation_recommendations": recommendations,
        "review_groups": groups,
        "material_choices": [
            {
                "label": item["choice"],
                "recommended_value": item["recommendation"],
                "attribution": CONNECTED_ASSISTANT_ATTRIBUTION,
            }
            for item in choices
        ],
        "output_artifact": output_artifact,
        "deferred_choices": [
            {
                "label": f"Deferred choice {index}",
                "deferred_value": value,
                "attribution": CONNECTED_ASSISTANT_ATTRIBUTION,
            }
            for index, value in enumerate(deferred, start=1)
        ],
        "limitations_nonclaims": [
            {"value": value, "attribution": CONNECTED_ASSISTANT_ATTRIBUTION}
            for value in limitations
        ],
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
        exact_request, proposal, selected_artifact_identities=selected_artifact_identities
    )
    result = {
        "schema_id": SEMANTICS_SCHEMA_ID,
        "schema_version": 1,
        "exact_request_utf8_sha256": request_digest(exact_request),
        "semantic_axes": deepcopy(validated["semantic_axes"]),
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
        "execution_performed": False,
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
        exact_request, proposal, selected_artifact_identities=selected_artifact_identities
    )
    return "review-revision-" + _digest(
        {
            "exact_request": exact_request,
            "exact_request_utf8_sha256": request_digest(exact_request),
            "connected_assistant_proposal": validated,
            "selected_artifact_identity_sha256": [
                sha256(value.encode("utf-8")).hexdigest()
                for value in sorted(selected_artifact_identities)
            ],
            "privacy_safe_projection": True,
        }
    )


def _displayed_text_values(value: Mapping[str, Any]) -> list[str]:
    values = [str(value.get("recommended_interpretation") or "")]
    for group in value.get("initial_decision_groups", ()):
        if isinstance(group, Mapping):
            for item in group.get("items", ()):
                if isinstance(item, Mapping):
                    values.append(str(item.get("value") or ""))
    for key, field in (
        ("material_choices", "recommended_value"),
        ("deferred_choices", "deferred_value"),
        ("limitations_nonclaims", "value"),
    ):
        for item in value.get(key, ()):
            if isinstance(item, Mapping):
                values.append(str(item.get(field) or ""))
    blocking = value.get("blocking_clarification")
    if isinstance(blocking, str):
        values.append(blocking)
    return values


def validate_first_value(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the customer projection and recompute its source/QASM invariant."""

    if not isinstance(value, Mapping):
        raise ReviewBeforeGenerationError("review_first_value_invalid")
    forbidden = {
        "review_revision",
        "exact_request_utf8_sha256",
        "prior_result_token",
        "schema_id",
        "schema_version",
        "semantic_axes",
    }
    if set(value).intersection(forbidden):
        raise ReviewBeforeGenerationError("review_first_value_internal_metadata_exposed")
    actual_source = any(_contains_source_or_qasm(item) for item in _displayed_text_values(value))
    if value.get("source_or_qasm_included") is not actual_source:
        raise ReviewBeforeGenerationError("review_first_value_source_invariant_mismatch")
    if actual_source or (value.get("confirmable") is True and actual_source):
        raise ReviewBeforeGenerationError("review_first_value_source_or_qasm_present")
    if value.get("initial_decision_group_count") != 3:
        raise ReviewBeforeGenerationError("review_first_value_group_count_invalid")
    if value.get("customer_actions") not in (list(CUSTOMER_ACTIONS), []):
        raise ReviewBeforeGenerationError("review_first_value_actions_invalid")
    return deepcopy(dict(value))


def build_first_value(
    exact_request: str,
    proposal: Mapping[str, Any],
    *,
    selected_artifact_identities: Sequence[str] = (),
) -> dict[str, Any]:
    validated = validate_connected_assistant_proposal(
        exact_request, proposal, selected_artifact_identities=selected_artifact_identities
    )
    confirmable = validated["blocking_clarification"] is None
    displayed_groups = deepcopy(validated["review_groups"])
    for group in displayed_groups:
        group.pop("group_id", None)
    result = {
        "recommended_interpretation": validated["recommended_interpretation"],
        "proposal_attribution": PROPOSAL_ATTRIBUTION,
        "initial_decision_groups": displayed_groups,
        "initial_decision_group_count": 3,
        "initial_decision_group_maximum": 3,
        "material_choices": deepcopy(validated["material_choices"]),
        "deferred_choices": deepcopy(validated["deferred_choices"]),
        "limitations_nonclaims": deepcopy(validated["limitations_nonclaims"]),
        "blocking_clarification": validated["blocking_clarification"],
        "confirmable": confirmable,
        "customer_actions": list(CUSTOMER_ACTIONS) if confirmable else [],
        "confirmation_state": "awaiting_customer_confirmation" if confirmable else "blocked",
        "one_qcoder_operation_before_useful_review": True,
        "source_or_qasm_included": False,
        "file_mutation_performed": False,
        "execution_permitted": False,
        "execution_performed": False,
        "protected_service_called": False,
        "qcoder_authored_recommendation": False,
        "retention": "current_loop_only_process_and_discard",
    }
    return validate_first_value(result)


def render_first_value_markdown(value: Mapping[str, Any]) -> str:
    validated = validate_first_value(value)
    lines = [
        "# Review before generation",
        "",
        _markdown_escape(validated["recommended_interpretation"]),
        "",
    ]
    for group in validated["initial_decision_groups"]:
        lines.extend([f"## {group['label']}", ""])
        for item in group["items"]:
            lines.append(
                f"- **{_markdown_escape(item['label'])}:** {_markdown_escape(item['value'])}"
            )
        lines.append("")
    if validated["deferred_choices"]:
        lines.extend(["## Deferred choices", ""])
        for item in validated["deferred_choices"]:
            lines.append(
                f"- **{_markdown_escape(item['label'])}:** "
                f"{_markdown_escape(item['deferred_value'])}"
            )
        lines.append("")
    lines.extend(["## Limitations and nonclaims", ""])
    for item in validated["limitations_nonclaims"]:
        lines.append(f"- {_markdown_escape(item['value'])}")
    lines.append("")
    if validated["customer_actions"]:
        lines.extend(["## Actions", ""])
        lines.extend(f"- {action}" for action in validated["customer_actions"])
        lines.append("")
    elif validated.get("blocking_clarification"):
        lines.extend(
            [
                "## Clarification needed",
                "",
                _markdown_escape(validated["blocking_clarification"]),
                "",
            ]
        )
    return "\n".join(lines)


def contract_snapshot() -> dict[str, Any]:
    return {
        "schema_id": CONTRACT_SCHEMA_ID,
        "schema_version": 2,
        "proposal_schema_id": PROPOSAL_SCHEMA_ID,
        "semantics_schema_id": SEMANTICS_SCHEMA_ID,
        "first_value_schema_id": FIRST_VALUE_SCHEMA_ID,
        "transaction_schema_id": TRANSACTION_SCHEMA_ID,
        "proposal_attribution": PROPOSAL_ATTRIBUTION,
        "transaction_kinds": list(TRANSACTION_KINDS),
        "execution_requests": list(EXECUTION_REQUESTS),
        "initial_groups": [label for _, label in GROUPS],
        "customer_actions": list(CUSTOMER_ACTIONS),
        "request_digest_computed_by_qcoder": True,
        "customer_projection_excludes_revision_and_token": True,
        "one_operation_before_useful_review": True,
        "backward_compatible_optional_begin_input": True,
        "protected_service_required": False,
        "qcoder_authors_recommendations": False,
        "process_and_discard": True,
        "new_public_tool": False,
        "new_private_operation": False,
    }


def proposal_input_schema() -> dict[str, Any]:
    """Return the valid-by-construction v2 proposal schema."""

    plain_text = {
        "type": "string",
        "minLength": 1,
        "maxLength": 2000,
        "description": (
            "One bounded plain-text value. Do not include Markdown, source code, QASM, customer "
            "action labels, qCoder boundary text, schema mechanics, or multiline content."
        ),
    }
    return {
        "type": "object",
        "description": (
            "Use only when the exact customer request asks to review proposed generation or "
            "modification choices before source is created. Supply concrete connected-assistant "
            "recommendations; qCoder supplies groups, labels, attribution, authority, revision, "
            "and actions."
        ),
        "properties": {
            "schema_id": {"const": PROPOSAL_SCHEMA_ID},
            "schema_version": {"const": 2},
            "transaction_kind": {
                "type": "string",
                "enum": list(TRANSACTION_KINDS),
                "description": (
                    "Select review before new source generation or review before changes to an "
                    "explicitly selected source artifact."
                ),
            },
            "execution_request": {
                "type": "string",
                "enum": list(EXECUTION_REQUESTS),
                "description": (
                    "Use not_requested unless execution was explicitly requested; even then it "
                    "remains held for separate authorization."
                ),
            },
            "recommended_interpretation": {
                **plain_text,
                "maxLength": 4000,
                "description": (
                    "Concrete reading of the customer's goal and scope. Do not include source, "
                    "QASM, Markdown, or an action label."
                ),
            },
            "customer_constraints": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "uniqueItems": True,
                "items": {
                    **plain_text,
                    "maxLength": 500,
                    "description": "Exact nonempty excerpt copied from request_text.",
                },
                "description": (
                    "Only exact excerpts from unchanged request_text; do not paraphrase customer facts."
                ),
            },
            "implementation_recommendations": {
                "type": "array",
                "minItems": 1,
                "maxItems": 24,
                "items": plain_text,
                "description": (
                    "Concrete framework, construction, representation, mapping, operation, or "
                    "output-structure recommendations. Plain prose only; no source or QASM."
                ),
            },
            "material_choices": {
                "type": "array",
                "minItems": 1,
                "maxItems": 24,
                "items": {
                    "type": "object",
                    "properties": {"choice": plain_text, "recommendation": plain_text},
                    "required": ["choice", "recommendation"],
                    "additionalProperties": False,
                },
                "description": "Ordinary-language material choices and concrete recommendations.",
            },
            "output_artifact": {
                **plain_text,
                "description": "Concrete source artifact form proposed after confirmation.",
            },
            "deferred_choices": {
                "type": "array",
                "maxItems": 24,
                "items": plain_text,
                "description": (
                    "Material choices deliberately deferred. Defer execution-only choices when "
                    "execution was not requested."
                ),
            },
            "limitations_nonclaims": {
                "type": "array",
                "minItems": 1,
                "maxItems": 24,
                "items": plain_text,
                "description": "Truthful limitations and nonclaims; no qCoder boundary attribution.",
            },
            "blocking_clarification": {
                "type": ["string", "null"],
                "maxLength": 600,
                "description": (
                    "One genuinely material unresolved question, or null when the concrete "
                    "recommendation is confirmable."
                ),
            },
        },
        "required": [
            "schema_id",
            "schema_version",
            "transaction_kind",
            "execution_request",
            "recommended_interpretation",
            "customer_constraints",
            "implementation_recommendations",
            "material_choices",
            "output_artifact",
            "deferred_choices",
            "limitations_nonclaims",
            "blocking_clarification",
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
    "request_digest",
    "review_revision",
    "validate_connected_assistant_proposal",
    "validate_first_value",
]
