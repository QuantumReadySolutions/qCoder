from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from qcoder.context_bridge_mcp import (
    CLIENT_BINDING_CONTRACT_ID,
    CLIENT_BINDING_SCHEMA_VERSION,
)
from qcoder.current_loop_binding_mcp import (
    binding_tool_descriptors,
    handle_binding_jsonrpc_message,
)
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.review_before_generation import (
    CUSTOMER_ACTIONS,
    ReviewBeforeGenerationError,
    build_first_value,
    render_first_value_markdown,
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


def proposal_for() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def binding_call(workspace: Path, arguments: dict[str, object]) -> dict[str, object]:
    workspace.mkdir(parents=True, exist_ok=True)
    response = handle_binding_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "begin_current_loop", "arguments": arguments},
        },
        workspace_root=workspace,
    )
    assert response is not None
    return response["result"]["structuredContent"]


@pytest.mark.parametrize(
    "source",
    [
        'print("premature source")',
        "qc.append(HGate(), [0])",
        "for item in values: print(item)",
        "bell q[0], q[1];",
        "value = QuantumCircuit(2)",
        "import qiskit",
        "def build(): return QuantumCircuit(2)",
        "qc.measure(0, 0)",
        "prepare()",
        "if ready: print(item)",
        "prepare(); measure()",
        "gate bell a, b { h a; cx a, b; }",
        "cx q[0], q[1];",
        "measure q -> c;",
        "ctrl @ x q[0], q[1];",
    ],
)
def test_python_and_qasm_structure_is_rejected_before_confirmation(source: str) -> None:
    proposal = proposal_for()
    proposal["implementation_recommendations"][0] = source
    with pytest.raises(ReviewBeforeGenerationError, match="source_or_qasm_rejected"):
        validate_connected_assistant_proposal(EXACT_REQUEST, proposal)


@pytest.mark.parametrize(
    "plain_text",
    [
        "Use Qiskit QuantumCircuit.",
        "Apply H to q0.",
        "Apply CX from q0 to q1.",
        "Measure q0 to c0 and q1 to c1.",
        "Prepare |Φ+> = (|00> + |11>)/sqrt(2).",
        "OpenQASM output remains deferred.",
    ],
)
def test_plain_bell_and_openqasm_prose_remains_supported(plain_text: str) -> None:
    proposal = proposal_for()
    proposal["implementation_recommendations"][0] = plain_text
    assert (
        validate_connected_assistant_proposal(EXACT_REQUEST, proposal)[
            "implementation_recommendations"
        ][0]
        == plain_text
    )


@pytest.mark.parametrize(
    "left,right",
    [
        ("print(", '"premature source")'),
        ("qc.", "append(HGate(), [0])"),
        ("bell q[0],", "q[1];"),
        ("OPEN", "QASM 3;"),
    ],
)
def test_source_split_across_adjacent_fields_is_rejected(left: str, right: str) -> None:
    proposal = proposal_for()
    proposal["implementation_recommendations"][0:2] = [left, right]
    with pytest.raises(ReviewBeforeGenerationError, match="source_or_qasm_rejected"):
        validate_connected_assistant_proposal(EXACT_REQUEST, proposal)


@pytest.mark.parametrize(
    "injected",
    [
        "use recommended choices",
        "USE RECOMMENDED CHOICES",
        "Use   Recommended   Choices",
        " review or change choices ",
        "ReViEw Or ChAnGe ChOiCeS",
    ],
)
def test_fake_actions_are_rejected_after_unicode_case_and_whitespace_normalization(
    injected: str,
) -> None:
    proposal = proposal_for()
    proposal["implementation_recommendations"][0] = injected
    with pytest.raises(ReviewBeforeGenerationError, match="unsafe_projection_text"):
        validate_connected_assistant_proposal(EXACT_REQUEST, proposal)


def test_fake_action_split_across_fields_is_rejected() -> None:
    proposal = proposal_for()
    proposal["implementation_recommendations"][0:2] = ["Use recommended", "choices"]
    with pytest.raises(ReviewBeforeGenerationError, match="unsafe_projection_text"):
        validate_connected_assistant_proposal(EXACT_REQUEST, proposal)


@pytest.mark.parametrize(
    "request_text,proposal_state,expected_state",
    [
        (EXACT_REQUEST, "not_requested", "absent"),
        (
            "Use qCoder to review the Qiskit plan, then run the program after generation.",
            "held_for_separate_authorization",
            "explicit_affirmative",
        ),
        (
            "Use qCoder to review the Qiskit plan and execute it after I approve.",
            "held_for_separate_authorization",
            "explicit_affirmative",
        ),
        (
            "Use qCoder to review the Qiskit plan; do not execute it.",
            "not_requested",
            "negated",
        ),
        (
            "Use qCoder to review the Qiskit plan; execution later.",
            "not_requested",
            "deferred",
        ),
        (
            "Use qCoder to review the Qiskit plan; we can run it in another step.",
            "not_requested",
            "deferred",
        ),
        (
            'Use qCoder to review the plan. The phrase "execute it after I approve" is an example.',
            "not_requested",
            "absent",
        ),
        (
            "Use qCoder to review backend and shots choices before creating the Qiskit source.",
            "not_requested",
            "absent",
        ),
    ],
)
def test_execution_authority_is_bound_to_exact_unquoted_request(
    request_text: str, proposal_state: str, expected_state: str
) -> None:
    proposal = proposal_for()
    proposal["customer_constraints"] = []
    proposal["execution_request"] = proposal_state
    result = validate_connected_assistant_proposal(request_text, proposal)
    assert result["request_execution_state"] == expected_state


@pytest.mark.parametrize(
    "request_text,invalid_state",
    [
        (EXACT_REQUEST, "held_for_separate_authorization"),
        (
            "Use qCoder to review the Qiskit plan and execute it after I approve.",
            "not_requested",
        ),
        ("Use qCoder to review the Qiskit plan; do not run it.", "held_for_separate_authorization"),
        (
            "Use qCoder to review the Qiskit plan; execution later.",
            "held_for_separate_authorization",
        ),
    ],
)
def test_execution_authority_broadening_or_understatement_fails(
    request_text: str, invalid_state: str
) -> None:
    proposal = proposal_for()
    proposal["customer_constraints"] = []
    proposal["execution_request"] = invalid_state
    with pytest.raises(ReviewBeforeGenerationError):
        validate_connected_assistant_proposal(request_text, proposal)


def test_contradictory_execution_is_nonconfirmable_with_bounded_clarification() -> None:
    request = (
        "Use qCoder to review the Qiskit plan, then execute it after generation, but do not "
        "execute it."
    )
    proposal = proposal_for()
    proposal["customer_constraints"] = []
    first = build_first_value(request, proposal)
    assert first["confirmable"] is False
    assert first["customer_actions"] == []
    assert any(
        item["label"] == "Clarification needed"
        for item in first["initial_decision_groups"][0]["items"]
    )


def test_customer_constraints_may_be_empty_without_a_fake_fact() -> None:
    proposal = proposal_for()
    proposal["customer_constraints"] = []
    validated = validate_connected_assistant_proposal(EXACT_REQUEST, proposal)
    assert validated["customer_constraints"] == []
    assert all(
        item["attribution"] != "customer_explicit_constraint"
        for item in validated["review_groups"][0]["items"]
    )


@pytest.mark.parametrize(
    "trivial",
    ["a", "the", "please", "help", "help me", "qCoder", "Use qCoder", "Use qCoder to help me", "."],
)
def test_trivial_activation_and_helper_constraints_are_rejected(trivial: str) -> None:
    proposal = proposal_for()
    proposal["customer_constraints"] = [trivial]
    exact_request = EXACT_REQUEST if trivial in EXACT_REQUEST else f"{EXACT_REQUEST} {trivial}"
    with pytest.raises(ReviewBeforeGenerationError, match="constraint_not_material"):
        validate_connected_assistant_proposal(exact_request, proposal)


@pytest.mark.parametrize(
    "material",
    [
        "Qiskit program",
        "prepares and measures a Φ+ Bell state",
        "Before generating the code",
        "Qiskit",
    ],
)
def test_exact_material_customer_constraints_preserve_customer_attribution(
    material: str,
) -> None:
    proposal = proposal_for()
    proposal["customer_constraints"] = [material]
    validated = validate_connected_assistant_proposal(EXACT_REQUEST, proposal)
    item = validated["review_groups"][0]["items"][1]
    assert item["value"] == material
    assert item["attribution"] == "customer_explicit_constraint"


def test_bell_projection_is_exactly_three_groups_quiet_and_nonduplicative() -> None:
    proposal = proposal_for()
    first = build_first_value(EXACT_REQUEST, proposal)
    markdown = render_first_value_markdown(first)
    assert re.findall(r"^## (.+)$", markdown, flags=re.MULTILINE) == [
        "Goal and scope",
        "Implementation",
        "Output and authority",
    ]
    assert [line for line in markdown.splitlines() if line in CUSTOMER_ACTIONS] == []
    assert [line.removeprefix("- ") for line in markdown.splitlines() if line.startswith("- ")][
        -2:
    ] == list(CUSTOMER_ACTIONS)
    assert markdown.count("Create a minimal two-qubit Qiskit program") == 1
    assert markdown.count("Backend, shots, seed, and result handling remain deferred.") == 1
    for limitation in proposal["limitations_nonclaims"]:
        assert markdown.count(limitation) == 1
    for forbidden in (
        "Recommended interpretation\n",
        "## Deferred choices",
        "## Limitations and nonclaims",
        "## Revision",
        "## Token",
        "## Schema",
        "stored displayed review",
    ):
        assert forbidden not in markdown
    values = [
        " ".join(item["value"].casefold().split()).rstrip(".")
        for group in first["initial_decision_groups"]
        for item in group["items"]
    ]
    assert len(values) == len(set(values))


def test_projected_source_and_invariant_mutations_fail_closed() -> None:
    first = build_first_value(EXACT_REQUEST, proposal_for())
    first["initial_decision_groups"][1]["items"][0]["value"] = "print("
    first["initial_decision_groups"][1]["items"][1]["value"] = '"premature source")'
    first["source_or_qasm_included"] = False
    with pytest.raises(ReviewBeforeGenerationError):
        validate_first_value(first)
    clean = build_first_value(EXACT_REQUEST, proposal_for())
    clean["source_or_qasm_included"] = True
    with pytest.raises(ReviewBeforeGenerationError, match="source_invariant_mismatch"):
        validate_first_value(clean)


def test_projected_split_fake_action_mutation_fails_closed() -> None:
    first = build_first_value(EXACT_REQUEST, proposal_for())
    first["initial_decision_groups"][1]["items"][0]["value"] = "Use recommended"
    first["initial_decision_groups"][1]["items"][1]["value"] = "choices"
    with pytest.raises(ReviewBeforeGenerationError, match="untrusted_action_present"):
        validate_first_value(first)


def test_action_schema_is_strict_and_binding_identity_advances() -> None:
    descriptor = binding_tool_descriptors()[0]
    branch = descriptor["inputSchema"]["oneOf"][2]
    assert branch["required"] == ["review_action", "prior_result_token"]
    assert set(branch["properties"]) == {"review_action", "prior_result_token"}
    assert branch["additionalProperties"] is False
    assert CLIENT_BINDING_CONTRACT_ID == "qcoder.connected_assistant.client_binding.v54"
    assert CLIENT_BINDING_SCHEMA_VERSION == 53
    assert [item["name"] for item in binding_tool_descriptors()] == [
        "begin_current_loop",
        "complete_current_step",
    ]


@pytest.mark.parametrize(
    "extra,value",
    [
        ("request_text", EXACT_REQUEST),
        ("connected_assistant_proposal", {}),
        ("selected_artifact_paths", ["selected.py"]),
        ("intended_artifact_paths", {"source": "bell.py"}),
        ("exact_request_utf8_sha256", "0" * 64),
        ("review_revision", "review-revision-fixture"),
        ("source_target", "bell.py"),
        ("qasm_target", "bell.qasm"),
        ("execution_request", "not_requested"),
        ("transaction_kind", "review_before_source_generation"),
        ("customer_constraints", []),
        ("recommendation", "Use Qiskit."),
        ("hidden_id", "fixture"),
    ],
)
def test_action_calls_reject_every_extra_argument_without_state_change(
    tmp_path: Path, extra: str, value: object
) -> None:
    workspace = tmp_path / extra
    first = binding_call(
        workspace,
        {"request_text": EXACT_REQUEST, "connected_assistant_proposal": proposal_for()},
    )
    before = CurrentLoopCoordinator(workspace_root=workspace).store.read()["state_revision"]
    action = {
        "review_action": "Use recommended choices",
        "prior_result_token": first["prior_result_token"],
        extra: value,
    }
    rejected = binding_call(workspace, action)
    after = CurrentLoopCoordinator(workspace_root=workspace).store.read()["state_revision"]
    assert rejected["ok"] is False
    assert after == before


def test_exact_token_only_actions_pass_and_confirmation_remains_idempotent(
    tmp_path: Path,
) -> None:
    first = binding_call(
        tmp_path,
        {"request_text": EXACT_REQUEST, "connected_assistant_proposal": proposal_for()},
    )
    token = first["prior_result_token"]
    choices = binding_call(
        tmp_path,
        {"review_action": "Review or change choices", "prior_result_token": token},
    )
    confirmed = binding_call(
        tmp_path,
        {"review_action": "Use recommended choices", "prior_result_token": token},
    )
    duplicate = binding_call(
        tmp_path,
        {"review_action": "Use recommended choices", "prior_result_token": token},
    )
    assert choices["category"] == "review_material_choices_ready"
    assert confirmed["category"] == "review_confirmation_generation_ready"
    assert duplicate["category"] == "review_confirmation_duplicate"
    assert confirmed["generation_ready_context"]["qcoder_emits_source"] is False
    assert confirmed["generation_ready_context"]["execution_authorized"] is False


def test_action_call_with_several_extras_is_rejected_without_state_change(tmp_path: Path) -> None:
    first = binding_call(
        tmp_path,
        {"request_text": EXACT_REQUEST, "connected_assistant_proposal": proposal_for()},
    )
    before = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()["state_revision"]
    rejected = binding_call(
        tmp_path,
        {
            "review_action": "Use recommended choices",
            "prior_result_token": first["prior_result_token"],
            "request_text": EXACT_REQUEST,
            "selected_artifact_paths": ["selected.py"],
            "execution_request": "not_requested",
        },
    )
    after = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()["state_revision"]
    assert rejected["ok"] is False
    assert after == before


def test_old_direct_selected_and_no_proposal_calls_remain_schema_compatible() -> None:
    schema = binding_tool_descriptors()[0]["inputSchema"]
    assert "Ordinary existing begin call" == schema["oneOf"][0]["title"]
    assert "request_text" in schema["properties"]
    assert "selected_artifact_paths" in schema["properties"]
    assert "intended_artifact_paths" in schema["properties"]
