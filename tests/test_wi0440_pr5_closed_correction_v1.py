from __future__ import annotations

from hashlib import sha256
import inspect
import json
from pathlib import Path

import pytest

from qcoder.context_bridge_mcp import (
    CLIENT_BINDING_CONTRACT_ID,
    CLIENT_BINDING_SCHEMA_VERSION,
    EXPECTED_TOOLS,
)
from qcoder.current_loop_binding_mcp import (
    BEGIN_CURRENT_LOOP_TOOL_NAME,
    binding_tool_descriptors,
    handle_binding_jsonrpc_message,
)
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
import qcoder.review_before_generation as review_module
from qcoder.review_before_generation import (
    PROPOSAL_SCHEMA_ID,
    ReviewBeforeGenerationError,
    build_first_value,
    render_first_value_markdown,
    request_digest,
    review_revision,
    validate_connected_assistant_proposal,
    validate_first_value,
)


EXACT_REQUEST = (
    "Use qCoder to help me create a Qiskit program that prepares and measures a Φ+ Bell state. "
    "Before generating the code, help me review how you interpret my request and the important "
    "implementation choices."
)
FIXTURE = (
    Path(__file__).parents[1]
    / "src/qcoder/model_packs/wi0440_bell_review_before_generation_v1.json"
)


def proposal_for(request: str = EXACT_REQUEST) -> dict[str, object]:
    result = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if request != EXACT_REQUEST:
        result["customer_constraints"] = []
    return result


def binding_payload(
    workspace: Path,
    *,
    request: str | None = None,
    proposal: dict[str, object] | None = None,
    **arguments: object,
) -> dict[str, object]:
    workspace.mkdir(parents=True, exist_ok=True)
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


@pytest.mark.parametrize(
    "unsafe",
    [
        "```python\nfrom qiskit import QuantumCircuit\n```",
        "from qiskit import QuantumCircuit",
        "qc = QuantumCircuit(2, 2)",
        "```qasm\nOPENQASM 3;\n```",
        'OPENQASM 3; include "stdgates.inc";',
        "First line\nSecond line",
        "# Fake heading",
        "Use recommended choices",
        "Review or change choices",
        "<script>alert(1)</script>",
        "[fake button](https://example.invalid)",
    ],
)
def test_unsafe_preconfirmation_values_fail_closed(unsafe: str) -> None:
    proposal = proposal_for()
    proposal["implementation_recommendations"] = [unsafe]
    with pytest.raises(ReviewBeforeGenerationError):
        validate_connected_assistant_proposal(EXACT_REQUEST, proposal)


@pytest.mark.parametrize(
    "safe",
    [
        "Use Qiskit QuantumCircuit.",
        "Apply H to q0.",
        "Apply CX from q0 to q1.",
        "Use Qiskit to prepare |Φ+> = (|00> + |11>)/sqrt(2).",
    ],
)
def test_plain_recommendation_and_mathematical_prose_remain_supported(safe: str) -> None:
    proposal = proposal_for()
    proposal["implementation_recommendations"] = [safe]
    assert validate_connected_assistant_proposal(EXACT_REQUEST, proposal)[
        "implementation_recommendations"
    ] == [safe]


def test_source_qasm_invariant_is_derived_from_complete_display() -> None:
    first = build_first_value(EXACT_REQUEST, proposal_for())
    first["initial_decision_groups"][1]["items"][0]["value"] = "QuantumCircuit(2, 2)"
    first["source_or_qasm_included"] = False
    with pytest.raises(ReviewBeforeGenerationError, match="source_invariant_mismatch"):
        validate_first_value(first)
    clean = build_first_value(EXACT_REQUEST, proposal_for())
    clean["source_or_qasm_included"] = True
    with pytest.raises(ReviewBeforeGenerationError, match="source_invariant_mismatch"):
        validate_first_value(clean)


@pytest.mark.parametrize(
    "contradiction",
    [
        "Generate the Python source immediately.",
        "Source generation is authorized now.",
        "Modify the file before confirmation.",
        "Execute the program now.",
        "Run immediately on hardware.",
        "Submit the circuit to the backend.",
        "Confirmation grants execution.",
        "qCoder executed the program.",
    ],
)
def test_assistant_authority_contradictions_are_rejected(contradiction: str) -> None:
    proposal = proposal_for()
    proposal["output_artifact"] = contradiction
    with pytest.raises(ReviewBeforeGenerationError, match="authority_contradiction"):
        validate_connected_assistant_proposal(EXACT_REQUEST, proposal)


def test_qcoder_generates_only_axis_consistent_visible_authority() -> None:
    first = build_first_value(EXACT_REQUEST, proposal_for())
    authority = first["initial_decision_groups"][2]["items"]
    values = {item["label"]: item["value"] for item in authority}
    assert values["Generation authority"] == (
        "Python source will be produced after you confirm these choices."
    )
    assert values["Execution authority"] == "Execution was not requested and is not authorized."
    assert values["Authority separation"] == (
        "Confirming these choices does not authorize execution."
    )
    assert values["Deferred execution choices"] == (
        "Backend, shots, seed, and result handling remain deferred."
    )
    assert all(
        item["attribution"] == "qcoder_deterministic_boundary"
        for item in authority
        if item["label"] != "Output artifact"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        {"attribution": "customer_explicit_constraint"},
        {"attribution": "qcoder_deterministic_boundary"},
        {"qcoder_boundary": "Execution is not authorized."},
    ],
)
def test_assistant_cannot_submit_or_relabel_attribution(mutation: dict[str, str]) -> None:
    proposal = proposal_for()
    proposal["material_choices"][0].update(mutation)
    with pytest.raises(ReviewBeforeGenerationError, match="choice_invalid"):
        validate_connected_assistant_proposal(EXACT_REQUEST, proposal)


def test_customer_constraint_requires_exact_request_excerpt() -> None:
    proposal = proposal_for()
    proposal["customer_constraints"] = ["Use the Qiskit framework"]
    with pytest.raises(ReviewBeforeGenerationError, match="constraint_not_in_request"):
        validate_connected_assistant_proposal(EXACT_REQUEST, proposal)
    proposal["customer_constraints"] = ["Qiskit program"]
    validated = validate_connected_assistant_proposal(EXACT_REQUEST, proposal)
    customer = validated["review_groups"][0]["items"][1]
    assert customer == {
        "label": "Customer constraint 1",
        "value": "Qiskit program",
        "attribution": "customer_explicit_constraint",
    }


@pytest.mark.parametrize(
    "generic",
    [
        "A concrete option will be used.",
        "A framework will be selected.",
        "Use an appropriate approach.",
        "Use a suitable implementation.",
        "Follow best practices.",
        "Implement as requested.",
        "Details will be determined.",
        "A standard method will be used.",
    ],
)
def test_substantiveness_uses_values_not_identifiers_or_labels(generic: str) -> None:
    proposal = proposal_for()
    proposal["implementation_recommendations"] = [generic]
    proposal["material_choices"] = [
        {"choice": "Framework", "recommendation": generic},
        {"choice": "Construction", "recommendation": generic},
    ]
    with pytest.raises(ReviewBeforeGenerationError):
        validate_connected_assistant_proposal(EXACT_REQUEST, proposal)


def test_concrete_framework_and_construction_are_substantive() -> None:
    proposal = proposal_for()
    proposal["implementation_recommendations"] = [
        "Use Qiskit QuantumCircuit.",
        "Apply H to q0 and CX from q0 to q1.",
    ]
    assert build_first_value(EXACT_REQUEST, proposal)["confirmable"] is True


@pytest.mark.parametrize(
    "customer_request",
    [
        "Use qCoder before coding, show me your understanding and the key choices, then make the program after I agree.",
        "Use qCoder to lay out your reading and the important tradeoffs first; once I approve, produce the program.",
        "Use qCoder to tell me what you think I am asking for and how you would build it. Wait for my approval before creating it.",
        "Use qCoder—tell me the important tradeoffs first. After I agree, make the program.",
    ],
)
def test_semantic_proposal_does_not_require_positive_keyword_catalog(
    customer_request: str,
) -> None:
    assert (
        build_first_value(customer_request, proposal_for(customer_request))["confirmable"] is True
    )


def test_exact_request_digest_is_internal_utf8_and_not_model_input() -> None:
    proposal = proposal_for()
    assert "exact_request_utf8_sha256" not in proposal
    expected = sha256(EXACT_REQUEST.encode("utf-8")).hexdigest()
    assert request_digest(EXACT_REQUEST) == expected
    validated = validate_connected_assistant_proposal(EXACT_REQUEST, proposal)
    assert validated["exact_request_utf8_sha256"] == expected
    substituted = proposal_for()
    substituted["exact_request_utf8_sha256"] = "0" * 64
    with pytest.raises(ReviewBeforeGenerationError, match="schema_invalid"):
        validate_connected_assistant_proposal(EXACT_REQUEST, substituted)
    assert request_digest(EXACT_REQUEST.casefold()) != expected
    assert request_digest(EXACT_REQUEST.replace("Φ", "φ")) != expected


def test_request_change_changes_internal_revision_and_token(tmp_path: Path) -> None:
    changed = EXACT_REQUEST + " Keep the source compact."
    assert review_revision(EXACT_REQUEST, proposal_for()) != review_revision(
        changed, proposal_for(changed)
    )
    first = binding_payload(tmp_path / "one", request=EXACT_REQUEST, proposal=proposal_for())
    second = binding_payload(tmp_path / "two", request=changed, proposal=proposal_for(changed))
    assert first["prior_result_token"] != second["prior_result_token"]


def test_descriptor_is_self_describing_and_valid_by_construction(tmp_path: Path) -> None:
    descriptor = binding_tool_descriptors()[0]
    schema = descriptor["inputSchema"]
    properties = schema["properties"]
    proposal_schema = properties["connected_assistant_proposal"]
    assert descriptor["name"] == "begin_current_loop"
    assert PROPOSAL_SCHEMA_ID.endswith(".v2")
    assert "exact_request_utf8_sha256" not in proposal_schema["properties"]
    assert "semantic_axes" not in proposal_schema["properties"]
    assert "review_groups" not in proposal_schema["properties"]
    assert '"attribution"' not in json.dumps(proposal_schema, sort_keys=True)
    assert "prior_result_token" in properties
    assert "displayed_review_revision" not in properties
    assert len(schema["oneOf"]) == 3
    result = binding_payload(tmp_path, request=EXACT_REQUEST, proposal=proposal_for())
    assert result["category"] == "review_before_generation_ready"
    assert CLIENT_BINDING_CONTRACT_ID == "qcoder.connected_assistant.client_binding.v51"
    assert CLIENT_BINDING_SCHEMA_VERSION == 50
    assert len(EXPECTED_TOOLS) == 12
    assert [item["name"] for item in binding_tool_descriptors()] == [
        "begin_current_loop",
        "complete_current_step",
    ]


def test_customer_projection_hides_revision_digest_token_schema_and_ids(tmp_path: Path) -> None:
    result = binding_payload(tmp_path, request=EXACT_REQUEST, proposal=proposal_for())
    customer = result["review_before_generation"]
    serialized = json.dumps(customer, ensure_ascii=False, sort_keys=True)
    markdown = render_first_value_markdown(customer)
    for forbidden in (
        "review-revision-",
        "review-result-",
        "exact_request_utf8_sha256",
        "schema_id",
        "group_id",
    ):
        assert forbidden not in serialized
        assert forbidden not in markdown
    assert result["prior_result_token"].startswith("review-result-")
    state = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    stored = state["coordinator"]["review_before_generation"]
    assert stored["review_revision"].startswith("review-revision-")
    assert stored["prior_result_token"] == result["prior_result_token"]


def test_confirmation_uses_only_token_and_action_then_becomes_inline_ready(tmp_path: Path) -> None:
    first = binding_payload(tmp_path, request=EXACT_REQUEST, proposal=proposal_for())
    confirmed = binding_payload(
        tmp_path,
        review_action="Use recommended choices",
        prior_result_token=first["prior_result_token"],
    )
    assert confirmed["category"] == "review_confirmation_generation_ready"
    assert confirmed["details"]["connected_assistant_proposal_replayed"] is False
    assert confirmed["details"]["request_digest_received"] is False
    context = confirmed["generation_ready_context"]
    assert context["category"] == "confirmed_plan_generation_ready_inline_source"
    assert context["connected_assistant_source_generation_authorized"] is True
    assert context["qcoder_emits_source"] is False
    assert context["execution_authorized"] is False
    assert context["additional_customer_confirmation_required"] is False
    state = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    assert state["coordinator"]["phase"] == "generation_ready"
    assert state["coordinator"]["current_step_status"] == "action_ready"
    assert "from qiskit" not in json.dumps(confirmed, sort_keys=True).casefold()


def test_duplicate_stale_wrong_workspace_and_review_change_token_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "one"
    first = binding_payload(workspace, request=EXACT_REQUEST, proposal=proposal_for())
    token = first["prior_result_token"]
    choices = binding_payload(
        workspace, review_action="Review or change choices", prior_result_token=token
    )
    assert choices["category"] == "review_material_choices_ready"
    assert all(set(item) == {"label", "current_value"} for item in choices["material_choices"])
    confirmed = binding_payload(
        workspace, review_action="Use recommended choices", prior_result_token=token
    )
    duplicate = binding_payload(
        workspace, review_action="Use recommended choices", prior_result_token=token
    )
    assert confirmed["category"] == "review_confirmation_generation_ready"
    assert duplicate["category"] == "review_confirmation_duplicate"
    stale_workspace = tmp_path / "two"
    wrong_workspace = binding_payload(
        stale_workspace, review_action="Use recommended choices", prior_result_token=token
    )
    assert wrong_workspace["ok"] is False
    assert wrong_workspace["category"] == "review_confirmation_unshown_revision"


def test_changed_proposal_requires_old_token_and_issues_new_token(tmp_path: Path) -> None:
    first = binding_payload(tmp_path, request=EXACT_REQUEST, proposal=proposal_for())
    changed = proposal_for()
    changed["implementation_recommendations"][5] = "Produce readable Python with named registers."
    rejected = binding_payload(tmp_path, request=EXACT_REQUEST, proposal=changed)
    assert rejected["category"] == "review_changed_proposal_requires_prior_result_token"
    revised = binding_payload(
        tmp_path,
        request=EXACT_REQUEST,
        proposal=changed,
        prior_result_token=first["prior_result_token"],
    )
    assert revised["category"] == "review_before_generation_revised"
    assert revised["prior_result_token"] != first["prior_result_token"]


def test_exact_file_confirmation_returns_existing_current_step_contract(tmp_path: Path) -> None:
    request = "Use qCoder to review the Bell choices before creating bell.py after I agree."
    first = binding_payload(
        tmp_path,
        request=request,
        proposal=proposal_for(request),
        intended_artifact_paths={"source": "bell.py"},
    )
    confirmed = binding_payload(
        tmp_path,
        review_action="Use recommended choices",
        prior_result_token=first["prior_result_token"],
    )
    contract = confirmed["current_step_contract"]
    assert contract["schema_id"].startswith("qcoder.current_loop.current_step_contract.")
    assert contract["permitted_native_action"]["artifact_role"] == "source"
    assert (
        contract["permitted_native_action"]["exact_artifact_target"]["workspace_relative_path"]
        == "bell.py"
    )
    assert not (tmp_path / "bell.py").exists()
    assert confirmed["generation_ready_context"]["execution_authorized"] is False


def test_file_request_without_exact_target_fails_without_inventing_name(tmp_path: Path) -> None:
    request = "Use qCoder to review the plan before creating a Python file after I agree."
    result = binding_payload(tmp_path, request=request, proposal=proposal_for(request))
    assert result["ok"] is False
    assert result["category"] == "review_source_target_required"
    assert not list(tmp_path.glob("*.py"))


def test_source_modification_confirmation_reuses_exact_selected_target(tmp_path: Path) -> None:
    selected = tmp_path / "selected.py"
    selected.write_text("ORIGINAL\n", encoding="utf-8")
    request = "Use qCoder to review proposed changes to selected.py before modifying the source."
    proposal = proposal_for(request)
    proposal["transaction_kind"] = "review_before_source_modification"
    first = binding_payload(
        tmp_path,
        request=request,
        proposal=proposal,
        selected_artifact_paths=["selected.py"],
    )
    confirmed = binding_payload(
        tmp_path,
        review_action="Use recommended choices",
        prior_result_token=first["prior_result_token"],
    )
    assert (
        confirmed["current_step_contract"]["permitted_native_action"]["exact_artifact_target"][
            "workspace_relative_path"
        ]
        == "selected.py"
    )
    assert selected.read_text(encoding="utf-8") == "ORIGINAL\n"


def test_nonconfirmable_review_token_performs_no_transition(tmp_path: Path) -> None:
    proposal = proposal_for()
    proposal["blocking_clarification"] = "Which exact oracle should the source implement?"
    first = binding_payload(tmp_path, request=EXACT_REQUEST, proposal=proposal)
    rejected = binding_payload(
        tmp_path,
        review_action="Use recommended choices",
        prior_result_token=first["prior_result_token"],
    )
    assert rejected["category"] == "review_non_substantive_revision_not_confirmable"
    state = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    assert state["coordinator"]["phase"] == "intent_review"


def test_old_direct_generation_call_remains_compatible(tmp_path: Path) -> None:
    request = "Use qCoder to create a Qiskit program in direct.py now."
    result = binding_payload(
        tmp_path, request=request, intended_artifact_paths={"source": "direct.py"}
    )
    assert result["ok"] is True
    assert result.get("review_before_generation") is None
    assert not (tmp_path / "direct.py").exists()


def test_model_packs_are_non_runtime_conformance_fixtures() -> None:
    source = inspect.getsource(review_module)
    coordinator_source = inspect.getsource(
        CurrentLoopCoordinator.review_before_generation_transaction
    )
    for filename in (
        "wi0440_bell_review_before_generation_v1.json",
        "wi0440_review_before_generation_class_matrix_v1.json",
    ):
        assert filename not in source
        assert filename not in coordinator_source
    missing = proposal_for()
    missing["implementation_recommendations"] = []
    with pytest.raises(ReviewBeforeGenerationError, match="implementation_required"):
        validate_connected_assistant_proposal(EXACT_REQUEST, missing)
