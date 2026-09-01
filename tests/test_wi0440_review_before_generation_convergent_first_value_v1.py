from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from qcoder.context_bridge_mcp import (
    CLIENT_BINDING_CONTRACT_ID,
    CLIENT_BINDING_SCHEMA_VERSION,
    EXPECTED_TOOLS,
    build_client_binding_descriptor,
)
from qcoder.current_loop_binding_mcp import (
    BEGIN_CURRENT_LOOP_TOOL_NAME,
    binding_tool_descriptors,
    handle_binding_jsonrpc_message,
)
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.current_loop_request_semantics import classify_current_request
from qcoder.d079_workflows import classify_binding_default_route
from qcoder.review_before_generation import (
    CUSTOMER_ACTIONS,
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
MATRIX_FIXTURE = (
    Path(__file__).parents[1]
    / "src/qcoder/model_packs/wi0440_review_before_generation_class_matrix_v1.json"
)
GOLDEN_DIR = Path(__file__).parent / "fixtures/wi0440_review_before_generation_v1/goldens"


def bell_proposal() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def class_matrix() -> dict[str, object]:
    return json.loads(MATRIX_FIXTURE.read_text(encoding="utf-8"))


def proposal_for(
    request: str,
    *,
    algorithm: str = "Bell",
    construction: str | None = None,
) -> dict[str, object]:
    proposal = bell_proposal()
    proposal["customer_constraints"] = []
    if algorithm != "Bell":
        profile = class_matrix()["profiles"][algorithm]
        concrete = construction or profile["construction"]
        proposal["recommended_interpretation"] = profile["recommended_interpretation"]
        proposal["implementation_recommendations"] = [
            "Use Qiskit QuantumCircuit.",
            profile["quantum_scope"],
            concrete,
            profile["measurement_mapping"],
            profile["output_structure"],
        ]
        proposal["output_artifact"] = profile["intended_artifact"]
        proposal["material_choices"][1]["recommendation"] = concrete
        proposal["material_choices"][2]["recommendation"] = profile["measurement_mapping"]
        proposal["material_choices"][3]["recommendation"] = profile["output_structure"]
    return proposal


def binding_call(
    workspace: Path,
    request: str | None,
    proposal: dict[str, object] | None = None,
    **arguments: object,
) -> dict[str, object]:
    call_arguments: dict[str, object] = dict(arguments)
    if request is not None:
        call_arguments["request_text"] = request
    if proposal is not None:
        call_arguments["connected_assistant_proposal"] = proposal
    response = handle_binding_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": BEGIN_CURRENT_LOOP_TOOL_NAME, "arguments": call_arguments},
        },
        workspace_root=workspace,
    )
    assert response is not None
    return response["result"]["structuredContent"]


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
    assert "schema_id" not in first
    assert "review_revision" not in first
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
    proposal["implementation_recommendations"][0] = replacement
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
    proposal["recommended_interpretation"] = value
    with pytest.raises(ReviewBeforeGenerationError, match="private_material"):
        validate_connected_assistant_proposal(EXACT_BELL_REQUEST, proposal)


def test_caller_supplied_request_digest_is_rejected() -> None:
    proposal = bell_proposal()
    proposal["exact_request_utf8_sha256"] = "0" * 64
    with pytest.raises(ReviewBeforeGenerationError, match="schema_invalid"):
        validate_connected_assistant_proposal(EXACT_BELL_REQUEST, proposal)


def test_source_modification_requires_an_explicit_selected_artifact() -> None:
    proposal = bell_proposal()
    proposal["transaction_kind"] = "review_before_source_modification"
    modification_request = (
        "Use qCoder to review proposed Bell changes to the selected source before modifying it."
    )
    with pytest.raises(ReviewBeforeGenerationError, match="selection_required"):
        validate_connected_assistant_proposal(modification_request, proposal)


def test_blocking_clarification_withholds_confirmation_actions() -> None:
    proposal = bell_proposal()
    proposal["blocking_clarification"] = "Which required oracle should the generated source use?"
    first = build_first_value(EXACT_BELL_REQUEST, proposal)
    assert first["confirmable"] is False
    assert first["customer_actions"] == []


def test_binding_returns_complete_bell_review_in_one_operation(tmp_path: Path) -> None:
    result = binding_call(tmp_path, EXACT_BELL_REQUEST, bell_proposal())
    review = result["review_before_generation"]
    assert result["ok"] is True
    assert "category" not in result
    assert "state_mutated" not in result
    assert "activation_acknowledgement" not in result
    assert review["initial_decision_group_count"] == 3
    assert [group["label"] for group in review["initial_decision_groups"]] == [
        "Goal and scope",
        "Implementation",
        "Output and authority",
    ]
    assert review["customer_actions"] == list(CUSTOMER_ACTIONS)
    assert review["one_qcoder_operation_before_useful_review"] is True
    assert result["source_or_qasm_created"] is False
    assert result["file_mutation_performed"] is False
    assert result["execution_performed"] is False
    assert result["protected_service_called"] is False


def test_duplicate_first_call_is_same_review_without_reactivation(tmp_path: Path) -> None:
    first = binding_call(tmp_path, EXACT_BELL_REQUEST, bell_proposal())
    duplicate = binding_call(tmp_path, EXACT_BELL_REQUEST, bell_proposal())
    assert "category" not in duplicate
    assert "state_mutated" not in duplicate
    assert "duplicate_call_idempotent" not in duplicate
    assert "activation_acknowledgement" not in duplicate
    assert duplicate["review_before_generation"] == first["review_before_generation"]
    state = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    assert state["coordinator"]["bootstrap_count"] == 1
    assert state["coordinator"]["request_baseline_count"] == 1


def test_exact_revision_confirmation_and_duplicate_are_idempotent(tmp_path: Path) -> None:
    first = binding_call(tmp_path, EXACT_BELL_REQUEST, bell_proposal())
    token = first["prior_result_token"]
    confirmation = binding_call(
        tmp_path,
        None,
        review_action="Use recommended choices",
        prior_result_token=token,
    )
    assert confirmation["category"] == "review_confirmation_generation_ready"
    assert confirmation["generation_authority"] == "source_generation_authorized_for_confirmed_plan"
    assert confirmation["execution_authority"] == "not_requested"
    assert confirmation["source_or_qasm_created"] is False
    duplicate = binding_call(
        tmp_path,
        None,
        review_action="Use recommended choices",
        prior_result_token=token,
    )
    assert duplicate["category"] == "review_confirmation_duplicate"
    assert duplicate["state_mutated"] is False
    assert duplicate["duplicate_confirmation_idempotent"] is True


def test_wrong_and_stale_tokens_do_not_mutate_state(tmp_path: Path) -> None:
    first = binding_call(tmp_path, EXACT_BELL_REQUEST, bell_proposal())
    state_before = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    rejected = binding_call(
        tmp_path,
        None,
        review_action="Use recommended choices",
        prior_result_token="review-result-" + "0" * 64,
    )
    assert rejected["ok"] is False
    assert rejected["category"] == "review_confirmation_stale_token"
    assert rejected["state_mutated"] is False
    assert CurrentLoopCoordinator(workspace_root=tmp_path).store.read() == state_before
    assert first["prior_result_token"] != ("review-result-" + "0" * 64)


def test_changed_material_choice_creates_new_revision(tmp_path: Path) -> None:
    first = binding_call(tmp_path, EXACT_BELL_REQUEST, bell_proposal())
    changed = bell_proposal()
    changed["implementation_recommendations"][5] = (
        "Direct readable Python with explicit register names"
    )
    changed["material_choices"][3]["recommendation"] = (
        "Direct readable Python with explicit register names"
    )
    revised = binding_call(
        tmp_path,
        EXACT_BELL_REQUEST,
        changed,
        prior_result_token=first["prior_result_token"],
    )
    assert "category" not in revised
    assert "prior_result_token_invalidated" not in revised
    assert revised["prior_result_token"] != first["prior_result_token"]
    stale = binding_call(
        tmp_path,
        None,
        review_action="Use recommended choices",
        prior_result_token=first["prior_result_token"],
    )
    assert stale["category"] == "review_confirmation_stale_token"
    assert stale["state_mutated"] is False


@pytest.mark.parametrize(
    "customer_request",
    [
        "Use qCoder to review my Bell implementation choices before creating the Qiskit source.",
        "Use qCoder to check the proposed Qiskit Bell construction, then generate source after confirmation.",
        "Use qCoder to validate my Qiskit Bell plan before writing code.",
        "Use qCoder to vet the Qiskit Bell implementation before creating the program.",
        "Use qCoder to sanity-check the Bell circuit choices before generating Qiskit code.",
        "Use qCoder to align on a Bell Qiskit implementation before writing the program.",
        "Use qCoder to walk through the Qiskit Bell choices before creating source.",
        "Use qCoder to explain assumptions for the Bell Qiskit program before generating code.",
        "Use qCoder to explain choices for Qiskit Bell source before creating it.",
        "Use qCoder to confirm the approach before generating the Qiskit Bell program.",
        "Before writing code, use qCoder to review the proposed Qiskit Bell implementation.",
        "Generate a Qiskit Bell program after you use qCoder to review the choices with me.",
        "Use qCoder: review the Qiskit Φ+ plan; create source only after confirmation; do not execute.",
        "The Qiskit Bell program must be source only. Use qCoder to check choices before generation.",
        "Use qCoder to review the choices before a Qiskit program is created for (|00> + |11>)/sqrt(2).",
    ],
)
def test_review_before_generation_paraphrases_converge_semantically(
    customer_request: str,
) -> None:
    result = build_review_before_generation_semantics(
        customer_request, proposal_for(customer_request)
    )
    assert (
        result["semantic_axes"]
        == build_review_before_generation_semantics(EXACT_BELL_REQUEST, bell_proposal())[
            "semantic_axes"
        ]
    )
    assert result["operation"] == "begin_current_loop"
    assert result["one_operation_before_useful_review"] is True
    assert result["execution_permitted"] is False
    assert review_revision(customer_request, proposal_for(customer_request)) != review_revision(
        EXACT_BELL_REQUEST, bell_proposal()
    )


@pytest.mark.parametrize(
    "algorithm,customer_request",
    [
        (
            "GHZ",
            "Use qCoder to review a concrete GHZ Qiskit construction before generating source.",
        ),
        (
            "Grover",
            "Use qCoder to review oracle and diffusion choices before creating a Grover Qiskit program.",
        ),
        (
            "Teleportation",
            "Use qCoder to check the teleportation circuit and correction choices before writing Qiskit code.",
        ),
        (
            "QAOA",
            "Use qCoder to review QAOA circuit and parameter choices before generating Qiskit source.",
        ),
    ],
)
def test_non_bell_proposals_are_concrete_without_correctness_or_execution_claims(
    algorithm: str, customer_request: str
) -> None:
    first = build_first_value(customer_request, proposal_for(customer_request, algorithm=algorithm))
    implementation = json.dumps(first["initial_decision_groups"][1], sort_keys=True)
    assert algorithm.casefold() in json.dumps(first, ensure_ascii=False).casefold()
    assert any(
        term in implementation.casefold()
        for term in ("circuit", "oracle", "diffusion", "ansatz", "correction")
    )
    assert first["confirmable"] is True
    assert first["execution_permitted"] is False
    assert first["source_or_qasm_included"] is False
    assert any(
        "correctness" in item["value"] for item in first["initial_decision_groups"][0]["items"]
    )


@pytest.mark.parametrize("case", class_matrix()["cases"], ids=lambda case: case["case_id"])
def test_non_bell_connected_assistant_class_matrix(case: dict[str, object]) -> None:
    proposal = proposal_for(str(case["request"]), algorithm=str(case["algorithm"]))
    proposal["blocking_clarification"] = case.get("blocking_clarification")
    first = build_first_value(str(case["request"]), proposal)
    assert first["source_or_qasm_included"] is False
    assert first["execution_performed"] is False
    assert first["qcoder_authored_recommendation"] is False
    assert "review_revision" not in first
    if case["variant"] == "material_blocker":
        assert first["confirmable"] is False
        assert first["customer_actions"] == []
        assert any(
            item["value"] == case["blocking_clarification"]
            for item in first["initial_decision_groups"][0]["items"]
        )
    else:
        assert first["confirmable"] is True
        assert first["customer_actions"] == list(CUSTOMER_ACTIONS)
        assert all(group["items"] for group in first["initial_decision_groups"])


def test_material_blocker_is_specific_and_has_no_actions() -> None:
    request = "Use qCoder to review the oracle choice before generating a Grover Qiskit program."
    proposal = proposal_for(request, algorithm="Grover")
    proposal["blocking_clarification"] = (
        "Which exact marked-state oracle must the requested source implement?"
    )
    first = build_first_value(request, proposal)
    assert first["confirmable"] is False
    assert first["customer_actions"] == []
    assert any(
        "oracle" in item["value"].casefold()
        for item in first["initial_decision_groups"][0]["items"]
    )


def test_source_modification_preserves_explicit_selected_identity_without_mutation(
    tmp_path: Path,
) -> None:
    selected = tmp_path / "selected.py"
    selected.write_text("ORIGINAL\n", encoding="utf-8")
    request = (
        "Use qCoder to review proposed Qiskit implementation changes to selected.py before "
        "modifying the source."
    )
    proposal = proposal_for(request)
    proposal["transaction_kind"] = "review_before_source_modification"
    result = binding_call(
        tmp_path,
        request,
        proposal,
        selected_artifact_paths=["selected.py"],
    )
    assert result["ok"] is True
    state = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    stored = state["coordinator"]["review_before_generation"]["connected_assistant_proposal"]
    assert stored["semantic_axes"]["review_object"] == "proposed_changes"
    assert state["coordinator"]["review_before_generation"]["selected_artifact_identity_sha256"]
    assert selected.read_text(encoding="utf-8") == "ORIGINAL\n"
    assert list(tmp_path.glob("*.py")) == [selected]


def test_source_modification_without_selection_returns_specific_clarification(
    tmp_path: Path,
) -> None:
    request = (
        "Use qCoder to review proposed Qiskit implementation changes before modifying the source."
    )
    proposal = proposal_for(request)
    proposal["transaction_kind"] = "review_before_source_modification"
    result = binding_call(tmp_path, request, proposal)
    assert result["ok"] is False
    assert result["category"] == "review_source_modification_selection_required"
    assert result["customer_clarification"] == (
        "Which exact source file should the proposed changes apply to?"
    )
    assert result["state_mutated"] is False


def test_d079_generation_front_door_converges_to_binding_owned_transaction() -> None:
    route = classify_binding_default_route(
        customer_instruction=EXACT_BELL_REQUEST,
        connected_assistant_proposal=bell_proposal(),
    )
    assert route["action"] == "call_binding_owned_begin_current_loop"
    assert route["operation"] == "begin_current_loop"
    assert route["matched_named_workflow"] == "review_before_generation"
    assert route["one_operation_before_useful_review"] is True
    assert (
        route["request_semantics"]["semantic_axes"]
        == (
            build_review_before_generation_semantics(EXACT_BELL_REQUEST, bell_proposal())[
                "semantic_axes"
            ]
        )
    )


def test_direct_generation_and_selected_review_controls_keep_existing_meanings() -> None:
    direct = classify_current_request(
        "Use qCoder to create a Qiskit program in bell.py now.",
        active_loop=False,
        selected_paths=(),
    )
    assert direct["route"] == "active_build"
    assert direct["requested_operation"] == "source_generation"
    selected = classify_current_request(
        "Use qCoder to review selected.py.",
        active_loop=False,
        selected_paths=("selected.py",),
    )
    assert selected["requested_operation"] == "selected_artifact_review"
    assert selected["clarification_required"] is False
    evidence = classify_current_request(
        "Use qCoder to review evidence.json.",
        active_loop=False,
        selected_paths=("evidence.json",),
    )
    assert evidence["requested_operation"] == "selected_artifact_review"


def test_quoted_instruction_does_not_activate_review_transaction() -> None:
    request = 'The phrase "review before generating" appears in this documentation. Explain what it means.'
    semantics = classify_current_request(request, active_loop=False, selected_paths=())
    assert semantics["route"] == "available_inactive"
    assert semantics["requested_operation"] == "inactive"


def test_explicit_no_execution_cannot_be_broadened() -> None:
    request = (
        "Use qCoder to review a Qiskit Bell program before generating source; do not execute it."
    )
    proposal = proposal_for(request)
    proposal["execution_request"] = "held_for_separate_authorization"
    with pytest.raises(ReviewBeforeGenerationError, match="execution_authority_broadened"):
        validate_connected_assistant_proposal(request, proposal)


def test_mixed_generation_and_execution_keeps_authorities_separate() -> None:
    request = (
        "Use qCoder to review a Qiskit Bell program before generating it, then execute only after "
        "separate authorization."
    )
    proposal = proposal_for(request)
    proposal["execution_request"] = "held_for_separate_authorization"
    first = build_review_before_generation_semantics(request, proposal)
    assert first["semantic_axes"]["generation_authority"] == ("held_for_exact_review_confirmation")
    assert first["semantic_axes"]["execution_authority"] == (
        "explicitly_requested_requires_separate_authority"
    )
    assert first["execution_performed"] is False


def test_contradictory_generation_order_returns_one_specific_clarification() -> None:
    request = (
        "Use qCoder to create the Qiskit program now before review and also review it before "
        "generating code."
    )
    with pytest.raises(ReviewBeforeGenerationError) as caught:
        validate_connected_assistant_proposal(request, proposal_for(request))
    assert caught.value.category == "review_request_authority_contradiction"
    assert caught.value.clarification == (
        "Should source be produced now, or only after you confirm the choices?"
    )


def test_missing_bell_recommendation_is_rejected_not_authored_by_qcoder() -> None:
    proposal = bell_proposal()
    proposal["implementation_recommendations"] = []
    proposal["material_choices"] = []
    with pytest.raises(ReviewBeforeGenerationError, match="implementation_required"):
        validate_connected_assistant_proposal(EXACT_BELL_REQUEST, proposal)


def test_review_change_action_exposes_only_ordinary_material_choices(tmp_path: Path) -> None:
    first = binding_call(tmp_path, EXACT_BELL_REQUEST, bell_proposal())
    result = binding_call(
        tmp_path,
        None,
        review_action="Review or change choices",
        prior_result_token=first["prior_result_token"],
    )
    assert result["category"] == "review_material_choices_ready"
    assert result["internal_identifiers_exposed"] is False
    assert {frozenset(item) for item in result["material_choices"]} == {
        frozenset({"label", "current_value"})
    }
    serialized = json.dumps(result, sort_keys=True)
    assert "eligibility" not in serialized
    assert "tool_name" not in serialized


def test_binding_descriptor_is_additive_and_inventory_remains_exact_12_plus_2() -> None:
    descriptor = build_client_binding_descriptor(coordinator_prefix=["qcoder"])[
        "client_binding_contract"
    ]
    assert CLIENT_BINDING_CONTRACT_ID == "qcoder.connected_assistant.client_binding.v54"
    assert CLIENT_BINDING_SCHEMA_VERSION == 53
    assert descriptor["review_before_generation_contract"]["new_public_tool"] is False
    assert descriptor["review_before_generation_contract"]["new_private_operation"] is False
    assert len(EXPECTED_TOOLS) == 12
    assert [item["name"] for item in binding_tool_descriptors()] == [
        "begin_current_loop",
        "complete_current_step",
    ]


def test_abandon_discards_transient_proposal_and_exact_request(tmp_path: Path) -> None:
    binding_call(tmp_path, EXACT_BELL_REQUEST, bell_proposal())
    state_file = tmp_path / ".qcoder/current-loop/state.json"
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["coordinator"]["review_before_generation"]["exact_request"] == EXACT_BELL_REQUEST
    result = CurrentLoopCoordinator(workspace_root=tmp_path).abandon(explicit_authority=True)
    assert result["ok"] is True
    assert result["phase"] == "abandoned"
    assert not state_file.exists()


def test_bell_json_and_markdown_match_deterministic_goldens() -> None:
    first = build_first_value(EXACT_BELL_REQUEST, bell_proposal())
    assert (
        canonical_json(first).encode("utf-8") == (GOLDEN_DIR / "bell-first-value.json").read_bytes()
    )
    assert (
        render_first_value_markdown(first).encode("utf-8")
        == (GOLDEN_DIR / "bell-first-value.md").read_bytes()
    )


def test_local_timing_acceptance_population_passes_without_network() -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    completed = subprocess.run(
        [
            sys.executable,
            str(
                Path(__file__).parents[1] / "scripts/wi0440-review-before-generation-acceptance.py"
            ),
            "--repetitions",
            "1",
        ],
        check=True,
        capture_output=True,
        env=environment,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert result["population_cases"] == 65
    assert result["samples"] == 65
    assert result["scenario_counts"] == {
        "review_first_value": 20,
        "confirmation_without_replay": 1,
        "duplicate_call": 1,
        "duplicate_confirmation": 1,
        "generic_proposal_rejection": 1,
        "source_modification": 1,
        "stale_token": 1,
        "unsafe_content_rejection": 23,
        "direct_generation_control": 1,
        "empty_customer_constraints": 1,
        "execution_authority_binding": 4,
        "fake_action_rejection": 2,
        "material_customer_constraints": 1,
        "irrelevant_target_convergence": 4,
        "negated_target_convergence": 4,
        "material_target_mode_mismatch_rejection": 1,
        "display_before_write_authority": 1,
        "quiet_projection": 1,
        "split_source_rejection": 3,
    }
    assert result["unsafe_content_rejection"]["maximum_seconds"] >= 0
    assert result["connected_assistant_model"] == "not_measured_fixture_driven_automation"
    assert result["protected_service_seconds"] == 0
    assert result["first_useful_interpretation_budget_pass"] is True
    assert result["first_material_decision_budget_pass"] is True
    assert result["customer_visible_end_to_end"] == (
        "pending_targeted_native_windows_cursor_repeat"
    )
