from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from qcoder.review_before_generation import (
    CUSTOMER_ACTIONS,
    FIRST_VALUE_SCHEMA_ID,
    PROPOSAL_SCHEMA_ID,
    ReviewBeforeGenerationError,
    build_first_value,
    build_review_before_generation_semantics,
    canonical_json,
    render_first_value_markdown,
    review_revision,
    validate_connected_assistant_proposal,
)


EXACT_BELL_REQUEST = (
    "Use qCoder to help me create a Qiskit program that prepares and measures a Φ+ Bell state. "
    "Before generating the code, help me review how you interpret my request and the important "
    "implementation choices."
)
FIXTURE = (
    Path(__file__).parents[1]
    / "src/qcoder/model_packs/wi0440_bell_review_before_generation_v1.json"
)


def bell_proposal() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_exact_bell_proposal_is_request_bound_and_substantive() -> None:
    proposal = validate_connected_assistant_proposal(EXACT_BELL_REQUEST, bell_proposal())
    assert proposal["schema_id"] == PROPOSAL_SCHEMA_ID
    assert proposal["proposal_attribution"] == "connected_assistant"
    assert [group["label"] for group in proposal["review_groups"]] == [
        "Goal and scope",
        "Implementation",
        "Output and authority",
    ]
    assert all(group["items"] for group in proposal["review_groups"])


def test_exact_bell_semantic_axes_remain_independent() -> None:
    semantics = build_review_before_generation_semantics(EXACT_BELL_REQUEST, bell_proposal())
    assert semantics["semantic_axes"] == {
        "ultimate_outcome": "source_generation",
        "immediate_interaction": "review_proposed_intent_and_implementation",
        "temporal_order": "review_then_confirm_before_generation",
        "review_object": "proposed_intent_and_implementation",
        "generation_authority": "held_for_exact_review_confirmation",
        "execution_authority": "not_requested",
    }
    assert semantics["one_operation_before_useful_review"] is True
    assert semantics["source_generation_permitted_before_confirmation"] is False
    assert semantics["execution_permitted"] is False


def test_first_value_is_deterministic_display_ready_and_source_free() -> None:
    first = build_first_value(EXACT_BELL_REQUEST, bell_proposal())
    second = build_first_value(EXACT_BELL_REQUEST, deepcopy(bell_proposal()))
    assert first == second
    assert canonical_json(first) == canonical_json(second)
    assert render_first_value_markdown(first) == render_first_value_markdown(second)
    assert first["schema_id"] == FIRST_VALUE_SCHEMA_ID
    assert first["customer_actions"] == list(CUSTOMER_ACTIONS)
    assert first["initial_decision_group_count"] == 3
    assert first["confirmable"] is True
    assert first["source_or_qasm_included"] is False
    assert first["file_mutation_performed"] is False
    assert first["execution_performed"] is False
    assert "QuantumCircuit(" not in canonical_json(first)


def test_same_request_and_proposal_have_stable_revision() -> None:
    assert review_revision(EXACT_BELL_REQUEST, bell_proposal()) == review_revision(
        EXACT_BELL_REQUEST, deepcopy(bell_proposal())
    )


@pytest.mark.parametrize(
    "replacement",
    ["", " ", "TBD", "TODO", "unknown", "unspecified", "generic approach", "as requested"],
)
def test_empty_and_generic_values_are_rejected(replacement: str) -> None:
    proposal = bell_proposal()
    proposal["review_groups"][1]["items"][0]["value"] = replacement
    with pytest.raises(ReviewBeforeGenerationError):
        validate_connected_assistant_proposal(EXACT_BELL_REQUEST, proposal)


@pytest.mark.parametrize(
    "field,value",
    [
        ("token", "fixture-secret-value"),
        ("authorization", "Bearer fixture-secret-value"),
        ("password", "fixture-password"),
        ("model_metadata", {"trace": "hidden"}),
    ],
)
def test_private_or_raw_fields_are_rejected(field: str, value: object) -> None:
    proposal = bell_proposal()
    proposal[field] = value
    with pytest.raises(ReviewBeforeGenerationError, match="review_proposal_schema_invalid"):
        validate_connected_assistant_proposal(EXACT_BELL_REQUEST, proposal)


@pytest.mark.parametrize(
    "value",
    [
        "Authorization: Bearer fixture-secret-value",
        r"C:\\Users\\Customer\\private\\bell.py",
        "/home/customer/private/bell.py",
        "project/private/bell.py",
    ],
)
def test_private_values_are_rejected(value: str) -> None:
    proposal = bell_proposal()
    proposal["review_groups"][0]["items"][0]["value"] = value
    with pytest.raises(ReviewBeforeGenerationError, match="private_material"):
        validate_connected_assistant_proposal(EXACT_BELL_REQUEST, proposal)


def test_wrong_exact_request_digest_is_rejected() -> None:
    with pytest.raises(ReviewBeforeGenerationError, match="request_digest_mismatch"):
        validate_connected_assistant_proposal(EXACT_BELL_REQUEST + " ", bell_proposal())


def test_source_modification_requires_an_explicit_selected_artifact() -> None:
    proposal = bell_proposal()
    proposal["semantic_axes"].update(
        {
            "ultimate_outcome": "source_modification",
            "immediate_interaction": "review_proposed_changes",
            "temporal_order": "review_then_confirm_before_modification",
            "review_object": "proposed_changes",
        }
    )
    with pytest.raises(ReviewBeforeGenerationError, match="selection_required"):
        validate_connected_assistant_proposal(EXACT_BELL_REQUEST, proposal)


def test_blocking_clarification_withholds_confirmation_actions() -> None:
    proposal = bell_proposal()
    proposal["blocking_clarification"] = "Which required oracle should the generated source use?"
    first = build_first_value(EXACT_BELL_REQUEST, proposal)
    assert first["confirmable"] is False
    assert first["customer_actions"] == []
    assert first["confirmation_state"] == "blocked"
