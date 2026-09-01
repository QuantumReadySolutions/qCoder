from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from copy import deepcopy
from pathlib import Path

import pytest

from qcoder.context_bridge_mcp import EXPECTED_TOOLS, tool_descriptors
from qcoder.current_loop_binding_mcp import (
    binding_tool_descriptors,
    handle_binding_jsonrpc_message,
)
from qcoder.current_loop_operator_timing import (
    MAX_BEGIN_ATTEMPTS,
    OperatorTimingEvidenceError,
    consume_begin_attempt_ledger,
    record_begin_attempt,
)
from qcoder.current_loop_reference_resources import resource_descriptors
from qcoder.review_before_generation import (
    ReviewBeforeGenerationError,
    validate_canonical_first_value_delivery,
    validate_review_content,
)

BELL_REQUEST = (
    "Use qCoder to help me create a Qiskit program that prepares and measures a Φ+ Bell state. "
    "Before generating the code, help me review how you interpret my request and the important "
    "implementation choices."
)
GHZ_REQUEST = (
    "Use qCoder to help me create a Qiskit program that prepares and measures a three-qubit GHZ "
    "state. Before generating the code, help me review how you interpret my request and the "
    "important implementation choices."
)


def _content(subject: str = "three-qubit GHZ") -> dict:
    if "Grover" in subject:
        recommendations = [
            {"label": "Framework", "value": "Use Qiskit QuantumCircuit."},
            {"label": "Oracle", "value": "Represent the marked state with a phase oracle."},
            {"label": "Amplification", "value": "Apply a diffusion circuit after the oracle."},
        ]
    elif "QAOA" in subject:
        recommendations = [
            {"label": "Framework", "value": "Use Qiskit QuantumCircuit."},
            {"label": "Ansatz", "value": "Use alternating cost and mixer circuit layers."},
            {"label": "Measurement", "value": "Measure the final qubits into classical bits."},
        ]
    elif "Bell" in subject:
        recommendations = [
            {"label": "Framework", "value": "Use Qiskit QuantumCircuit."},
            {"label": "Preparation", "value": "Apply H to q0, then CX from q0 to q1."},
            {"label": "Measurement", "value": "Measure both qubits into classical bits."},
        ]
    else:
        recommendations = [
            {"label": "Framework", "value": "Use Qiskit QuantumCircuit."},
            {
                "label": "Preparation",
                "value": "Apply H to q0, then CX from q0 to q1 and CX from q1 to q2.",
            },
            {
                "label": "Measurement",
                "value": "Measure all three qubits into matching classical bits.",
            },
        ]
    return {
        "interpretation": (
            f"Create a clear {subject} Qiskit program and review its implementation plan before "
            "producing source."
        ),
        "implementation_recommendations": recommendations,
        "output_artifact": "Readable Python source after confirmation",
        "limitations": ["The review does not claim hardware performance."],
    }


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def _call(workspace: Path, arguments: dict, *, message_id: int = 1) -> dict:
    workspace.mkdir(parents=True, exist_ok=True)
    response = handle_binding_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": message_id,
            "method": "tools/call",
            "params": {"name": "begin_current_loop", "arguments": arguments},
        },
        workspace_root=workspace,
    )
    assert response is not None
    return response["result"]


def _authority_value(result: dict, label: str) -> str:
    groups = result["structuredContent"]["review_before_generation"]["initial_decision_groups"]
    return next(item["value"] for item in groups[2]["items"] if item["label"] == label)


def test_semantic_only_schema_and_all_hard_budgets(tmp_path: Path) -> None:
    public = tool_descriptors()
    private = binding_tool_descriptors()
    descriptors = public + private
    assert len(public) == 12 and [item["name"] for item in public] == list(EXPECTED_TOOLS)
    assert [item["name"] for item in private] == ["begin_current_loop", "complete_current_step"]
    assert len(_canonical_bytes(descriptors)) <= 32_000
    assert len(_canonical_bytes(private[0])) <= 2_500
    init = handle_binding_jsonrpc_message(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        workspace_root=tmp_path,
    )
    assert init is not None
    assert len(init["result"]["instructions"].encode()) <= 1_500
    ghz_arguments = {"request_text": GHZ_REQUEST, "review_content": _content()}
    assert len(_canonical_bytes(ghz_arguments)) <= 4_000
    begin_text = json.dumps(private[0], sort_keys=True)
    forbidden = {
        "connected_assistant_proposal",
        "transaction_kind",
        "execution_request",
        "source_delivery",
        "customer_constraints",
        "deferred_choices",
        "review_revision",
        "ui://",
        "resourceUri",
    }
    assert all(value not in begin_text for value in forbidden)
    assert all(not item["uri"].startswith("ui://") for item in resource_descriptors())


def test_d136_repository_goldens_are_current_and_repeatable() -> None:
    command = [sys.executable, "scripts/generate-wi0440-d136-goldens.py", "--check"]
    first = subprocess.run(command, check=False, capture_output=True, text=True)
    second = subprocess.run(command, check=False, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr


@pytest.mark.parametrize(
    ("request_text", "subject"),
    [
        (BELL_REQUEST, "two-qubit Bell"),
        (GHZ_REQUEST, "three-qubit GHZ"),
        (
            "Use qCoder to create a Qiskit Grover program. Review the algorithm and implementation choices before generating source.",
            "Grover search",
        ),
        (
            "Use qCoder to create a Qiskit QAOA program. Review the ansatz and implementation choices before generating source.",
            "QAOA optimization",
        ),
    ],
)
def test_class_matrix_success_is_one_terminal_review(
    tmp_path: Path, request_text: str, subject: str
) -> None:
    result = _call(tmp_path, {"request_text": request_text, "review_content": _content(subject)})
    assert result["isError"] is False
    text = result["content"][0]["text"]
    assert text.startswith("## Goal and scope\n")
    assert text.count("\n## ") == 2
    assert text.endswith("- Review or change choices\n")
    assert "retry" not in text.casefold() and "contract" not in text.casefold()


def test_canonical_markdown_structured_revision_and_digest_are_equivalent(tmp_path: Path) -> None:
    result = _call(tmp_path, {"request_text": GHZ_REQUEST, "review_content": _content()})
    structured = result["structuredContent"]
    projection = structured["review_before_generation"]
    assert projection["initial_decision_group_count"] == 3
    assert projection["customer_actions"] == [
        "Use recommended choices",
        "Review or change choices",
    ]
    state = json.loads((tmp_path / ".qcoder/current-loop/state.json").read_text())
    review = state["coordinator"]["review_before_generation"]
    delivery = validate_canonical_first_value_delivery(
        review["canonical_delivery"], review_revision_value=review["review_revision"]
    )
    assert delivery["canonical_markdown"] == result["content"][0]["text"]
    assert delivery["machine_projection"] == projection
    assert delivery["projection_digest"] == structured["projection_digest"]
    assert "app_render_model" not in delivery and "_meta" not in result
    mutated = deepcopy(delivery)
    mutated["canonical_markdown"] += "changed"
    with pytest.raises(ReviewBeforeGenerationError, match="review_projection_delivery_mismatch"):
        validate_canonical_first_value_delivery(
            mutated, review_revision_value=review["review_revision"]
        )


@pytest.mark.parametrize(
    ("request_text", "expected"),
    [
        (GHZ_REQUEST, "Execution was not requested and is not authorized."),
        (
            GHZ_REQUEST + " Do not execute the program.",
            "Execution was explicitly declined and is not authorized.",
        ),
        (
            GHZ_REQUEST + " Run the program after generation.",
            "Execution remains held for separate authorization.",
        ),
        (
            GHZ_REQUEST + ' The phrase "run the program" is only an example.',
            "Execution was not requested and is not authorized.",
        ),
    ],
)
def test_qcoder_derives_execution_authority(
    tmp_path: Path, request_text: str, expected: str
) -> None:
    content = _content()
    content.update(
        {
            "execution_request": "held_for_separate_authorization",
            "generation_authorized": True,
            "execution_authorized": True,
            "source_delivery": {"mode": "workspace_file", "target": "invented.py"},
        }
    )
    result = _call(tmp_path, {"request_text": request_text, "review_content": content})
    assert result["isError"] is False
    assert _authority_value(result, "Execution authority") == expected
    assert _authority_value(result, "Source delivery") == "Inline after confirmation."


def test_material_blocker_and_safe_contradiction_are_terminal_without_repair(tmp_path: Path) -> None:
    blocker = _content()
    blocker["blocking_question"] = "Which oracle should the Grover circuit use?"
    result = _call(tmp_path / "blocker", {"request_text": GHZ_REQUEST, "review_content": blocker})
    assert result["isError"] is False
    assert result["content"] == [{"type": "text", "text": blocker["blocking_question"]}]
    assert result["structuredContent"]["terminal_for_turn"] is True
    assert "retry" not in result["content"][0]["text"].casefold()
    contradictory = _content()
    contradictory["implementation_recommendations"].append(
        {"label": "Execution", "value": "Execute the program immediately on hardware."}
    )
    complete = _call(
        tmp_path / "contradiction",
        {"request_text": GHZ_REQUEST, "review_content": contradictory},
    )
    assert complete["isError"] is False
    assert "Execute the program immediately" not in complete["content"][0]["text"]
    assert complete["content"][0]["text"].endswith("- Review or change choices\n")


@pytest.mark.parametrize(
    "unsafe",
    [
        'print("premature source")',
        "OPENQASM 3;",
        "bell q[0], q[1];",
        "Use recommended choices",
        "line one\nline two",
    ],
)
def test_unsafe_semantic_payload_fails_closed_terminally_without_choreography(
    tmp_path: Path, unsafe: str
) -> None:
    content = _content()
    content["interpretation"] = unsafe
    result = _call(tmp_path, {"request_text": GHZ_REQUEST, "review_content": content})
    assert result["isError"] is True
    assert result["content"][0]["text"] == "qCoder could not safely display this review content."
    encoded = json.dumps(result)
    assert unsafe not in encoded
    assert all(word not in result["content"][0]["text"].casefold() for word in ("retry", "schema", "resource", "field"))
    assert not (tmp_path / ".qcoder/current-loop/state.json").exists()


def test_target_convergence_confirmation_and_duplicate_idempotency(tmp_path: Path) -> None:
    invented = _content()
    invented["proposed_source_target"] = "invented.py"
    clean = _call(tmp_path / "inline", {"request_text": GHZ_REQUEST, "review_content": _content()})
    converged = _call(
        tmp_path / "invented", {"request_text": GHZ_REQUEST, "review_content": invented}
    )
    assert clean["content"] == converged["content"]
    assert "invented.py" not in json.dumps(converged)
    file_request = GHZ_REQUEST + " Save the source in ghz.py."
    file_content = _content()
    file_content["proposed_source_target"] = "ghz.py"
    first = _call(tmp_path / "file", {"request_text": file_request, "review_content": file_content})
    assert first["content"][0]["text"].count("ghz.py") == 1
    token = first["structuredContent"]["prior_result_token"]
    confirmed = _call(
        tmp_path / "file",
        {"review_action": "Use recommended choices", "prior_result_token": token},
        message_id=2,
    )
    ready = confirmed["structuredContent"]["generation_ready_context"]
    assert ready["exact_workspace_target"] == "ghz.py"
    assert ready["next_permitted_client_native_step"] == "write_exact_workspace_source"
    assert ready["execution_authorized"] is False
    duplicate = _call(
        tmp_path / "file",
        {"review_action": "Use recommended choices", "prior_result_token": token},
        message_id=3,
    )
    assert duplicate["structuredContent"]["duplicate_confirmation_idempotent"] is True


@pytest.mark.parametrize("target", ["/tmp/escape.py", "../escape.py", "missing.py"])
def test_unsafe_or_ungrounded_targets_converge_inline(tmp_path: Path, target: str) -> None:
    content = _content()
    content["proposed_source_target"] = target
    result = _call(tmp_path, {"request_text": GHZ_REQUEST, "review_content": content})
    assert result["isError"] is False
    assert _authority_value(result, "Source delivery") == "Inline after confirmation."
    assert target not in json.dumps(result)


def test_duplicate_semantic_call_and_changed_revision_stale_token(tmp_path: Path) -> None:
    arguments = {"request_text": GHZ_REQUEST, "review_content": _content()}
    first = _call(tmp_path, arguments)
    duplicate = _call(tmp_path, arguments, message_id=2)
    assert duplicate["structuredContent"]["duplicate_call_idempotent"] is True
    assert duplicate["structuredContent"]["prior_result_token"] == first["structuredContent"]["prior_result_token"]
    assert duplicate["structuredContent"]["projection_digest"] == first["structuredContent"]["projection_digest"]
    revised = _content()
    revised["implementation_recommendations"][1]["value"] = (
        "Apply H to q0, then entangle q0 with q1 and q2 using two CX circuit operations."
    )
    changed = _call(
        tmp_path,
        {
            "request_text": GHZ_REQUEST,
            "review_content": revised,
            "prior_result_token": first["structuredContent"]["prior_result_token"],
        },
        message_id=3,
    )
    assert changed["isError"] is False
    old = _call(
        tmp_path,
        {
            "review_action": "Use recommended choices",
            "prior_result_token": first["structuredContent"]["prior_result_token"],
        },
        message_id=4,
    )
    assert old["isError"] is True
    assert old["structuredContent"]["category"] == "review_confirmation_stale_token"


def test_selected_source_modification_is_strict_and_terminal(tmp_path: Path) -> None:
    request = "Use qCoder to review proposed Qiskit changes to the selected source before modifying it."
    no_selection = _call(
        tmp_path / "none", {"request_text": request, "review_content": _content("Bell changes")}
    )
    assert no_selection["isError"] is False
    assert no_selection["structuredContent"]["terminal_for_turn"] is True
    selected_workspace = tmp_path / "selected"
    selected_workspace.mkdir()
    (selected_workspace / "selected.py").write_text("# selected customer source\n", encoding="utf-8")
    selected = _call(
        selected_workspace,
        {
            "request_text": request,
            "review_content": _content("Bell changes"),
            "selected_artifact_paths": ["selected.py"],
        },
    )
    assert selected["isError"] is False
    assert selected["content"][0]["text"].count("selected.py") == 1
    assert selected["structuredContent"]["generation_authority"] == "held_for_exact_review_confirmation"


def test_attempt_ledger_records_accept_reject_bounds_privacy_and_consume_once(tmp_path: Path) -> None:
    generation = "a" * 64
    session = "b" * 64
    now = time.time_ns()
    for index in range(MAX_BEGIN_ATTEMPTS + 2):
        record_begin_attempt(
            state_root=tmp_path,
            setup_generation=generation,
            session_sha256=session,
            status="accepted" if index % 2 == 0 else "terminal_rejected",
            category="review_before_generation_ready" if index % 2 == 0 else "review_content_rejected",
            operation_entry_ns=10,
            processing_complete_ns=20 + index,
            result_return_ns=25 + index,
            semantic_revision_sha256="c" * 64 if index % 2 == 0 else None,
            wall_clock_ns=now,
        )
    with pytest.raises(OperatorTimingEvidenceError, match="cross_session"):
        consume_begin_attempt_ledger(
            state_root=tmp_path,
            setup_generation=generation,
            session_sha256="d" * 64,
            wall_clock_ns=now,
        )
    ledger = consume_begin_attempt_ledger(
        state_root=tmp_path,
        setup_generation=generation,
        session_sha256=session,
        wall_clock_ns=now,
    )
    assert len(ledger["attempts"]) == MAX_BEGIN_ATTEMPTS
    assert all(item["operation_name"] == "begin_current_loop" for item in ledger["attempts"])
    assert all(item["processing_ns"] > 0 and item["total_ns"] > 0 for item in ledger["attempts"])
    forbidden = (GHZ_REQUEST, "interpretation", "target path", "QASM", "token", "credential")
    assert all(item not in json.dumps(ledger) for item in forbidden)
    with pytest.raises(OperatorTimingEvidenceError, match="not_found"):
        consume_begin_attempt_ledger(
            state_root=tmp_path,
            setup_generation=generation,
            session_sha256=session,
            wall_clock_ns=now,
        )


def test_real_stdio_ledger_survives_discovery_and_contains_one_accepted_attempt(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "observer"
    state_root.mkdir()
    (tmp_path / "workspace").mkdir()
    generation = "a" * 64
    session = "b" * 64
    command = [
        sys.executable,
        "-m",
        "qcoder",
        "current-loop",
        "--workspace",
        str(tmp_path / "workspace"),
        "--connection-state-root",
        str(state_root),
        "--connection-generation",
        generation,
        "--connection-session-sha256",
        session,
        "serve-binding-mcp",
    ]
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "begin_current_loop",
                "arguments": {"request_text": GHZ_REQUEST, "review_content": _content()},
            },
        },
        {"jsonrpc": "2.0", "id": 4, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 5, "method": "resources/list"},
        {"jsonrpc": "2.0", "id": 6, "method": "ping"},
    ]
    completed = subprocess.run(
        command,
        input="".join(json.dumps(item) + "\n" for item in messages),
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")},
    )
    assert completed.returncode == 0, completed.stderr
    ledger = consume_begin_attempt_ledger(
        state_root=state_root,
        setup_generation=generation,
        session_sha256=session,
    )
    assert len(ledger["attempts"]) == 1
    attempt = ledger["attempts"][0]
    assert attempt["status"] == "accepted"
    assert attempt["semantic_revision_sha256"]
    assert attempt["processing_ns"] > 0 and attempt["total_ns"] > 0
    assert GHZ_REQUEST not in json.dumps(ledger)
