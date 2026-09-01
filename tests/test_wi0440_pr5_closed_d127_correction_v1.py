from __future__ import annotations

import json
from pathlib import Path

import pytest

import qcoder.review_before_generation as review_module
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
    ReviewBeforeGenerationError,
    build_first_value,
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
PYTHON_REPRODUCTIONS = (
    "assert condition",
    "pass",
    "break",
    "continue",
    "global value",
    "nonlocal value",
    "type Alias = int",
    'f"{value}"',
    "value if ready else fallback",
)
QASM_REPRODUCTIONS = (
    "delay[100ns] q[0];",
    'defcalgrammar "openpulse";',
    "defcal x $0 { play(frame, waveform); }",
    "let alias = q[0:1];",
    "int[32] count = 0;",
    "box[1us] { delay[100ns] q[0]; }",
    "cal { play(frame, waveform); }",
    "extern foo(int[32]) -> bit;",
    "const int[32] n = 2;",
)


def proposal_for() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def binding_call(workspace: Path, arguments: dict[str, object]) -> dict[str, object]:
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


def assert_proposal_rejected(value: str) -> None:
    proposal = proposal_for()
    proposal["implementation_recommendations"][0] = value
    with pytest.raises(ReviewBeforeGenerationError) as rejected:
        validate_connected_assistant_proposal(EXACT_REQUEST, proposal)
    assert rejected.value.category in {
        "review_proposal_source_or_qasm_rejected",
        "review_proposal_unsafe_projection_text",
    }


def assert_projection_rejected(values: list[str]) -> None:
    projected = build_first_value(EXACT_REQUEST, proposal_for())
    items = projected["initial_decision_groups"][1]["items"]
    for index, value in enumerate(values):
        items[index]["value"] = value
    projected["source_or_qasm_included"] = False
    with pytest.raises(ReviewBeforeGenerationError):
        validate_first_value(projected)


@pytest.mark.parametrize("source", PYTHON_REPRODUCTIONS)
def test_every_d127_python_reproduction_rejects_at_proposal_intake(source: str) -> None:
    assert_proposal_rejected(source)


@pytest.mark.parametrize("source", PYTHON_REPRODUCTIONS)
def test_every_d127_python_reproduction_rejects_at_final_projection(source: str) -> None:
    assert_projection_rejected([source])


@pytest.mark.parametrize(
    "source",
    (
        'print("premature source")',
        "qc.append(HGate(), [0])",
        "for item in values: print(item)",
        "value = QuantumCircuit(2)",
        "import qiskit",
        "def build(): return QuantumCircuit(2)",
        "prepare()",
        "if ready: print(item)",
        "[prepare(item) for item in values]",
        "@decorate\ndef build(): pass",
        "prepare(); measure()",
    ),
)
def test_original_and_structural_python_source_remains_rejected(source: str) -> None:
    assert_proposal_rejected(source)
    assert_projection_rejected([source])


@pytest.mark.parametrize(
    "safe",
    (
        "Use Qiskit QuantumCircuit.",
        "Apply H to q0.",
        "Apply CX from q0 to q1.",
        "Measure q0 to c0 and q1 to c1.",
        "Prepare |Φ+> = (|00> + |11>)/sqrt(2).",
        "pi + tau / 2",
        "-(alpha ** 2) + 3 / 4",
        "Qiskit",
    ),
)
def test_positive_python_boundary_preserves_prose_and_harmless_math(safe: str) -> None:
    proposal = proposal_for()
    proposal["implementation_recommendations"][0] = safe
    validate_connected_assistant_proposal(EXACT_REQUEST, proposal)
    validate_first_value(build_first_value(EXACT_REQUEST, proposal))


def test_type_alias_rejects_without_relying_on_runtime_ast_support(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = review_module.ast.parse

    def older_ast_parse(value: str, *args: object, mode: str = "exec", **kwargs: object) -> object:
        if value.startswith("type Alias"):
            raise SyntaxError("older supported Python")
        return original(value, *args, mode=mode, **kwargs)

    monkeypatch.setattr(review_module.ast, "parse", older_ast_parse)
    assert_proposal_rejected("type Alias = int")
    assert_projection_rejected(["type Alias = int"])


@pytest.mark.parametrize("source", QASM_REPRODUCTIONS)
def test_every_d127_qasm_reproduction_rejects_at_proposal_intake(source: str) -> None:
    assert_proposal_rejected(source)


@pytest.mark.parametrize("source", QASM_REPRODUCTIONS)
def test_every_d127_qasm_reproduction_rejects_at_final_projection(source: str) -> None:
    assert_projection_rejected([source])


@pytest.mark.parametrize(
    "source",
    (
        "bell q[0], q[1];",
        "cx q[0], q[1];",
        "measure q -> c;",
        "reset q[0];",
        "barrier q;",
        "ctrl @ x q[0], q[1];",
        "OPENQASM 3;",
        'include "stdgates.inc";',
        "qubit[2] q;",
        "gate bell a, b { h a; cx a, b; }",
    ),
)
def test_original_headerless_and_unknown_qasm_structure_remains_rejected(source: str) -> None:
    assert_proposal_rejected(source)
    assert_projection_rejected([source])


@pytest.mark.parametrize(
    "safe",
    (
        "OpenQASM output remains deferred.",
        "Discuss the OpenQASM representation in ordinary prose.",
        "Explain which gate construction is recommended.",
        "Describe how to measure both qubits.",
    ),
)
def test_structural_qasm_boundary_preserves_plain_technical_prose(safe: str) -> None:
    proposal = proposal_for()
    proposal["implementation_recommendations"][0] = safe
    validate_connected_assistant_proposal(EXACT_REQUEST, proposal)
    validate_first_value(build_first_value(EXACT_REQUEST, proposal))


SPLIT_REPRODUCTIONS = (
    ("source", ["print", "(", '"premature source")']),
    ("qasm", ["bell q[0]", ",", "q[1]", ";"]),
    ("qasm", ["OPEN", "QASM", "3", ";"]),
    ("action", ["Use", "recommended", "choices"]),
    ("action", ["Review", "or change", "choices"]),
)


@pytest.mark.parametrize("kind,parts", SPLIT_REPRODUCTIONS)
def test_every_d127_contiguous_split_rejects_before_projection(kind: str, parts: list[str]) -> None:
    proposal = proposal_for()
    proposal["implementation_recommendations"][0 : len(parts)] = parts
    expected = "unsafe_projection_text" if kind == "action" else "source_or_qasm_rejected"
    with pytest.raises(ReviewBeforeGenerationError, match=expected):
        validate_connected_assistant_proposal(EXACT_REQUEST, proposal)


@pytest.mark.parametrize("_kind,parts", SPLIT_REPRODUCTIONS)
def test_every_d127_contiguous_split_rejects_after_projection(_kind: str, parts: list[str]) -> None:
    assert_projection_rejected(parts)


def test_all_three_join_separators_and_all_contiguous_lengths_are_generated() -> None:
    variants = set(review_module._contiguous_projection_variants(["assert", "condition", "tail"]))
    assert "assertcondition" in variants
    assert "assert condition" in variants
    assert "assert\ncondition" in variants
    assert "assertconditiontail" in variants
    assert "assert condition tail" in variants
    assert "assert\ncondition\ntail" in variants


def test_labels_plus_values_projection_view_rejects_reconstructed_source() -> None:
    projected = build_first_value(EXACT_REQUEST, proposal_for())
    items = projected["initial_decision_groups"][1]["items"]
    items[0]["label"] = "print"
    items[0]["value"] = "("
    items[1]["label"] = '"premature source")'
    with pytest.raises(ReviewBeforeGenerationError):
        validate_first_value(projected)


def test_nonadjacent_fields_and_field_order_are_not_invented() -> None:
    proposal = proposal_for()
    proposal["implementation_recommendations"][0:5] = [
        "print",
        "Use Qiskit QuantumCircuit.",
        "(",
        "Apply H to q0.",
        '"premature source")',
    ]
    validate_connected_assistant_proposal(EXACT_REQUEST, proposal)
    validate_first_value(build_first_value(EXACT_REQUEST, proposal))


def test_contiguous_sequence_work_is_explicitly_bounded() -> None:
    with pytest.raises(ReviewBeforeGenerationError, match="aggregate_limit_exceeded"):
        list(review_module._contiguous_projection_variants(["safe"] * 257))


@pytest.mark.parametrize(
    "request_text,constraint",
    (
        (EXACT_REQUEST, "Before"),
        (EXACT_REQUEST, "create"),
        (EXACT_REQUEST, "review"),
        (f"{EXACT_REQUEST}  BEFORE  ", " BEFORE "),
        (f"{EXACT_REQUEST} Ｂｅｆｏｒｅ", "Ｂｅｆｏｒｅ"),
    ),
)
def test_lone_scaffolding_customer_constraints_reject(request_text: str, constraint: str) -> None:
    proposal = proposal_for()
    proposal["customer_constraints"] = [constraint]
    with pytest.raises(ReviewBeforeGenerationError, match="constraint_not_material"):
        validate_connected_assistant_proposal(request_text, proposal)


@pytest.mark.parametrize("material", ("Qiskit", "Python"))
def test_intrinsically_material_one_token_constraints_remain_valid(material: str) -> None:
    request = EXACT_REQUEST if material == "Qiskit" else f"{EXACT_REQUEST} Python"
    proposal = proposal_for()
    proposal["customer_constraints"] = [material]
    validated = validate_connected_assistant_proposal(request, proposal)
    assert validated["customer_constraints"] == [material]


@pytest.mark.parametrize(
    "constraints",
    ([], ["Qiskit program"], ["prepares and measures a Φ+ Bell state"]),
)
def test_empty_and_meaningful_multi_token_constraints_remain_valid(
    constraints: list[str],
) -> None:
    proposal = proposal_for()
    proposal["customer_constraints"] = constraints
    validate_connected_assistant_proposal(EXACT_REQUEST, proposal)


def test_model_facing_confirmation_removes_stored_review_mechanics(tmp_path: Path) -> None:
    first = binding_call(
        tmp_path,
        {"request_text": EXACT_REQUEST, "connected_assistant_proposal": proposal_for()},
    )
    token = first["prior_result_token"]
    confirmed = binding_call(
        tmp_path,
        {"review_action": "Use recommended choices", "prior_result_token": token},
    )
    serialized = json.dumps(confirmed, sort_keys=True)
    for forbidden in (
        "confirmed_stored_review",
        "review_revision_bound_internally",
        "confirmed_for_stored_displayed_review",
        "The stored review is confirmed",
    ):
        assert forbidden not in serialized
    ready = confirmed["generation_ready_context"]
    assert ready["category"] == "confirmed_plan_generation_ready_inline_source"
    assert ready["selected_review_action"] == "Use recommended choices"
    assert ready["plan_generation_ready"] is True
    assert ready["execution_authorized"] is False
    state = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    stored = state["coordinator"]["review_before_generation"]
    assert stored["review_revision"]
    assert stored["prior_result_token"] == token
    assert stored["confirmed_revision"] == stored["review_revision"]


def test_duplicate_and_stale_confirmation_preserve_internal_binding(tmp_path: Path) -> None:
    first = binding_call(
        tmp_path,
        {"request_text": EXACT_REQUEST, "connected_assistant_proposal": proposal_for()},
    )
    token = first["prior_result_token"]
    confirmed = binding_call(
        tmp_path,
        {"review_action": "Use recommended choices", "prior_result_token": token},
    )
    duplicate = binding_call(
        tmp_path,
        {"review_action": "Use recommended choices", "prior_result_token": token},
    )
    stale = binding_call(
        tmp_path,
        {
            "review_action": "Use recommended choices",
            "prior_result_token": "review-result-" + "0" * 64,
        },
    )
    assert confirmed["category"] == "review_confirmation_generation_ready"
    assert duplicate["category"] == "review_confirmation_duplicate"
    assert duplicate["state_mutated"] is False
    assert stale["category"] == "review_confirmation_stale_token"
    assert stale["ok"] is False


def test_contract_identity_advances_without_inventory_or_proposal_change() -> None:
    descriptors = binding_tool_descriptors()
    assert CLIENT_BINDING_CONTRACT_ID == "qcoder.connected_assistant.client_binding.v57"
    assert CLIENT_BINDING_SCHEMA_VERSION == 56
    assert [item["name"] for item in descriptors] == [
        "begin_current_loop",
        "complete_current_step",
    ]
    proposal_schema = descriptors[0]["inputSchema"]["properties"]["connected_assistant_proposal"]
    assert proposal_schema["properties"]["schema_id"]["const"].endswith(".v3")
