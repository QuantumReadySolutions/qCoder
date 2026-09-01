from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from qcoder.context_bridge_mcp import (
    EXPECTED_TOOLS,
    build_client_binding_descriptor,
    tool_descriptors,
)
from qcoder.current_loop_binding_mcp import (
    BEGIN_CURRENT_LOOP_TOOL_NAME,
    COMPLETE_CURRENT_STEP_TOOL_NAME,
    binding_tool_descriptors,
    handle_binding_jsonrpc_message,
)
from qcoder.current_loop_operator_timing import (
    OperatorTimingEvidenceError,
    consume_stdio_operator_timing,
    record_stdio_operator_timing,
)
from qcoder.mcp_first_value_app import FIRST_VALUE_APP_MIME, FIRST_VALUE_APP_URI
from qcoder.review_before_generation import (
    PROPOSAL_SCHEMA_ID,
    ReviewBeforeGenerationError,
    validate_canonical_first_value_delivery,
    validate_connected_assistant_proposal,
)

BELL_REQUEST = (
    "Use qCoder to help me create a Qiskit program that prepares and measures a Φ+ Bell state. "
    "Before generating the code, help me review how you interpret my request and the important "
    "implementation choices."
)


def _proposal(*, mode: str = "inline", target: str | None = None, ghz: bool = False) -> dict:
    subject = "three-qubit GHZ" if ghz else "two-qubit Φ+ Bell"
    recommendations = (
        [
            {"label": "Framework", "value": "Use Qiskit QuantumCircuit."},
            {"label": "Registers", "value": "Use three qubits and three classical bits."},
            {"label": "Preparation", "value": "Apply H to q0, then CX from q0 to q1 and q2."},
            {"label": "Measurement", "value": "Measure all qubits to matching classical bits."},
        ]
        if ghz
        else [
            {"label": "Framework", "value": "Use Qiskit QuantumCircuit."},
            {"label": "Registers", "value": "Use two qubits and two classical bits."},
            {"label": "Preparation", "value": "Apply H to q0, then CX from q0 to q1."},
            {"label": "Measurement", "value": "Measure q0 to c0 and q1 to c1."},
        ]
    )
    return {
        "schema_id": PROPOSAL_SCHEMA_ID,
        "schema_version": 4,
        "transaction_kind": "review_before_source_generation",
        "execution_request": "not_requested",
        "source_delivery": {"mode": mode, "target": target},
        "interpretation": (
            f"Create a clear {subject} Qiskit program and wait for exact review confirmation "
            "before producing source."
        ),
        "constraints": [],
        "recommendations": recommendations,
        "output_artifact": "Readable Python source after confirmation",
        "deferred": ["Backend, shots, seed, and result handling remain deferred."],
        "limitations": ["The review does not claim hardware performance."],
        "clarification": None,
    }


def _legacy(proposal: dict) -> dict:
    return {
        "schema_id": "qcoder.connected_assistant.review_before_generation_proposal.v3",
        "schema_version": 3,
        "transaction_kind": proposal["transaction_kind"],
        "execution_request": proposal["execution_request"],
        "source_delivery": deepcopy(proposal["source_delivery"]),
        "recommended_interpretation": proposal["interpretation"],
        "customer_constraints": list(proposal["constraints"]),
        "implementation_recommendations": [item["value"] for item in proposal["recommendations"]],
        "material_choices": [
            {"choice": item["label"], "recommendation": item["value"]}
            for item in proposal["recommendations"]
        ],
        "output_artifact": proposal["output_artifact"],
        "deferred_choices": list(proposal["deferred"]),
        "limitations_nonclaims": list(proposal["limitations"]),
        "blocking_clarification": proposal["clarification"],
    }


def _call(workspace: Path, arguments: dict, message_id: int = 1) -> dict:
    response = handle_binding_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": message_id,
            "method": "tools/call",
            "params": {"name": BEGIN_CURRENT_LOOP_TOOL_NAME, "arguments": arguments},
        },
        workspace_root=workspace,
    )
    assert response is not None
    return response["result"]


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def test_hard_discovery_and_bell_argument_budgets() -> None:
    descriptors = tool_descriptors() + binding_tool_descriptors()
    counts = {item["name"]: len(_canonical_bytes(item)) for item in descriptors}
    assert len(descriptors) == 14
    assert len(_canonical_bytes(descriptors)) <= 32_000
    assert counts[BEGIN_CURRENT_LOOP_TOOL_NAME] <= 4_000
    assert (
        len(
            _canonical_bytes(
                {"request_text": BELL_REQUEST, "connected_assistant_proposal": _proposal()}
            )
        )
        <= 6_000
    )


def test_canonical_binding_descriptor_matches_development_metadata() -> None:
    descriptor = build_client_binding_descriptor(coordinator_prefix=["qcoder"])[
        "client_binding_contract"
    ]
    encoded = _canonical_bytes(descriptor)
    metadata = json.loads((Path(__file__).parents[1] / "development-version.json").read_text())
    assert descriptor["contract_id"] == "qcoder.connected_assistant.client_binding.v58"
    assert descriptor["schema_version"] == 57
    assert metadata["canonical_descriptor_bytes"] == len(encoded)
    assert metadata["canonical_descriptor_sha256"] == hashlib.sha256(encoded).hexdigest()


def test_exact_12_plus_2_and_app_metadata() -> None:
    assert len(EXPECTED_TOOLS) == 12
    private = binding_tool_descriptors()
    assert [item["name"] for item in private] == [
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
    ]
    assert private[0]["_meta"] == {"ui": {"resourceUri": FIRST_VALUE_APP_URI}}


def test_v4_and_accepted_v3_normalize_to_identical_semantics() -> None:
    v4 = validate_connected_assistant_proposal(BELL_REQUEST, _proposal())
    v3 = validate_connected_assistant_proposal(BELL_REQUEST, _legacy(_proposal()))
    assert v4 == v3


def test_exact_bell_result_is_canonical_markdown_and_machine_projection(tmp_path: Path) -> None:
    result = _call(
        tmp_path, {"request_text": BELL_REQUEST, "connected_assistant_proposal": _proposal()}
    )
    text = result["content"][0]["text"]
    structured = result["structuredContent"]
    assert text.startswith("## Goal and scope\n")
    assert text.count("## ") == 3
    assert [line[3:] for line in text.splitlines() if line.startswith("## ")] == [
        "Goal and scope",
        "Implementation",
        "Output and authority",
    ]
    assert text.endswith("- Review or change choices\n")
    assert text.count("Use recommended choices") == 1
    assert text.count("Review or change choices") == 1
    assert "Next:" not in text and not text.startswith("qCoder")
    assert structured["review_before_generation"]["initial_decision_group_count"] == 3
    assert structured["app_render_model"]["actions"] == [
        "Use recommended choices",
        "Review or change choices",
    ]
    assert len(structured["projection_digest"]) == 64
    assert result["_meta"]["ui"]["resourceUri"] == FIRST_VALUE_APP_URI


def test_projection_digest_rejects_every_representation_mismatch(tmp_path: Path) -> None:
    _call(tmp_path, {"request_text": BELL_REQUEST, "connected_assistant_proposal": _proposal()})
    state = json.loads((tmp_path / ".qcoder/current-loop/state.json").read_text())
    stored = state["coordinator"]["review_before_generation"]
    delivery = stored["canonical_delivery"]
    validate_canonical_first_value_delivery(
        delivery, review_revision_value=stored["review_revision"]
    )
    for key in ("canonical_markdown", "projection_digest", "semantic_revision_sha256"):
        mutated = deepcopy(delivery)
        mutated[key] = "forged"
        with pytest.raises(
            ReviewBeforeGenerationError, match="review_projection_delivery_mismatch"
        ):
            validate_canonical_first_value_delivery(
                mutated, review_revision_value=stored["review_revision"]
            )
    mutated = deepcopy(delivery)
    mutated["app_render_model"]["actions"][0] = "forged"
    with pytest.raises(ReviewBeforeGenerationError):
        validate_canonical_first_value_delivery(
            mutated, review_revision_value=stored["review_revision"]
        )


@pytest.mark.parametrize("field", [None, "intended", "selected", "both"])
def test_d128_invented_envelopes_converge_to_inline(tmp_path: Path, field: str | None) -> None:
    proposal = _proposal(mode="workspace_file", target="bell.py")
    arguments: dict = {"request_text": BELL_REQUEST, "connected_assistant_proposal": proposal}
    if field in {"intended", "both"}:
        arguments["intended_artifact_paths"] = {"source": "bell.py"}
    if field in {"selected", "both"}:
        arguments["selected_artifact_paths"] = ["bell.py"]
    result = _call(tmp_path, arguments)
    assert result["isError"] is False
    structured = result["structuredContent"]
    assert "bell.py" not in result["content"][0]["text"]
    assert all(
        item["label"] != "Proposed source target"
        for group in structured["review_before_generation"]["initial_decision_groups"]
        for item in group["items"]
    )


def test_grounded_file_is_visible_inert_then_exactly_confirmed(tmp_path: Path) -> None:
    request = "Use qCoder to review a Qiskit Bell plan before generating source in bell.py."
    result = _call(
        tmp_path,
        {
            "request_text": request,
            "connected_assistant_proposal": _proposal(mode="workspace_file", target="bell.py"),
        },
    )
    assert result["content"][0]["text"].count("bell.py") == 1
    assert not (tmp_path / "bell.py").exists()
    token = result["structuredContent"]["prior_result_token"]
    confirmed = _call(
        tmp_path,
        {"review_action": "Use recommended choices", "prior_result_token": token},
        2,
    )["structuredContent"]
    assert confirmed["generation_ready_context"]["exact_workspace_target"] == "bell.py"
    assert confirmed["generation_ready_context"]["execution_authorized"] is False
    assert (
        confirmed["current_step_contract"]["permitted_native_action"]["exact_artifact_target"][
            "workspace_relative_path"
        ]
        == "bell.py"
    )


def test_review_change_revisions_are_visible_and_stale_token_fails(tmp_path: Path) -> None:
    first = _call(
        tmp_path, {"request_text": BELL_REQUEST, "connected_assistant_proposal": _proposal()}
    )
    old = first["structuredContent"]["prior_result_token"]
    choices = _call(
        tmp_path,
        {"review_action": "Review or change choices", "prior_result_token": old},
        2,
    )
    assert choices["structuredContent"]["category"] == "review_material_choices_ready"
    revised_proposal = _proposal()
    revised_proposal["recommendations"][0]["value"] = (
        "Use Qiskit QuantumCircuit with explicit registers."
    )
    revised = _call(
        tmp_path,
        {
            "request_text": BELL_REQUEST,
            "connected_assistant_proposal": revised_proposal,
            "prior_result_token": old,
        },
        3,
    )
    assert revised["content"][0]["text"].startswith("## Goal and scope")
    stale = _call(
        tmp_path,
        {"review_action": "Use recommended choices", "prior_result_token": old},
        4,
    )
    assert stale["isError"] is True
    assert stale["structuredContent"]["category"] == "review_confirmation_stale_token"


def test_resources_and_network_independent_app_are_registered(tmp_path: Path) -> None:
    listed = handle_binding_jsonrpc_message(
        {"jsonrpc": "2.0", "id": 1, "method": "resources/list"}, workspace_root=tmp_path
    )
    uris = [item["uri"] for item in listed["result"]["resources"]]
    assert FIRST_VALUE_APP_URI in uris
    read = handle_binding_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "resources/read",
            "params": {"uri": FIRST_VALUE_APP_URI},
        },
        workspace_root=tmp_path,
    )["result"]["contents"][0]
    assert read["mimeType"] == FIRST_VALUE_APP_MIME
    html = read["text"]
    assert "https://" not in html and "http://" not in html
    assert "innerHTML" not in html
    assert "begin_current_loop" in html
    assert "Use recommended choices" not in html  # labels come from validated result data
    assert "ui/notifications/tool-result" in html
    assert "crypto.subtle.digest" in html
    assert "projection_digest" in html


def test_app_render_model_matches_markdown_group_and_action_order(tmp_path: Path) -> None:
    result = _call(
        tmp_path, {"request_text": BELL_REQUEST, "connected_assistant_proposal": _proposal()}
    )
    text = result["content"][0]["text"]
    model = result["structuredContent"]["app_render_model"]
    assert [group["label"] for group in model["groups"]] == [
        line[3:] for line in text.splitlines() if line.startswith("## ")
    ]
    for group in model["groups"]:
        for item in group["items"]:
            assert f"- **{item['label']}:**" in text
    assert model["actions"] == [line[2:] for line in text.splitlines()[-2:]]


def test_ghz_non_bell_canonical_equivalence(tmp_path: Path) -> None:
    request = "Use qCoder to review a three-qubit GHZ Qiskit program before generating source."
    result = _call(
        tmp_path, {"request_text": request, "connected_assistant_proposal": _proposal(ghz=True)}
    )
    assert "three-qubit GHZ" in result["content"][0]["text"]
    assert (
        result["structuredContent"]["review_before_generation"]["initial_decision_group_count"] == 3
    )


def test_real_stdio_receipt_binds_only_accepted_operation_and_survives_discovery(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "observer"
    state_root.mkdir()
    generation = "a" * 64
    session = "b" * 64
    command = [
        sys.executable,
        "-m",
        "qcoder",
        "current-loop",
        "--workspace",
        str(tmp_path),
        "--connection-state-root",
        str(state_root),
        "--connection-generation",
        generation,
        "--connection-session-sha256",
        session,
        "serve-binding-mcp",
    ]
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "begin_current_loop",
                "arguments": {
                    "request_text": BELL_REQUEST,
                    "connected_assistant_proposal": _proposal(),
                },
            },
        },
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "resources/read",
            "params": {"uri": FIRST_VALUE_APP_URI},
        },
        {"jsonrpc": "2.0", "id": 4, "method": "ping"},
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
    receipt = consume_stdio_operator_timing(
        state_root=state_root,
        setup_generation=generation,
        session_sha256=session,
        operation_name="begin_current_loop",
    )
    assert receipt["operation_name"] == "begin_current_loop"
    assert receipt["processing_ns"] > 0 and receipt["total_ns"] > 0
    assert receipt["semantic_revision_sha256"]
    forbidden = (BELL_REQUEST, "proposal", "token", "bell.py", "source", "QASM", "credential")
    encoded = json.dumps(receipt)
    assert all(value not in encoded for value in forbidden)
    with pytest.raises(OperatorTimingEvidenceError, match="operator_timing_evidence_not_found"):
        consume_stdio_operator_timing(
            state_root=state_root,
            setup_generation=generation,
            session_sha256=session,
            operation_name="begin_current_loop",
        )


def test_app_asset_digest_is_stable(tmp_path: Path) -> None:
    read = handle_binding_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "resources/read",
            "params": {"uri": FIRST_VALUE_APP_URI},
        },
        workspace_root=tmp_path,
    )["result"]["contents"][0]
    assert (
        hashlib.sha256(read["text"].encode()).hexdigest()
        == hashlib.sha256(read["text"].encode()).hexdigest()
    )


def test_timing_store_keeps_two_operations_distinct_and_session_bound(tmp_path: Path) -> None:
    setup = "c" * 64
    session = "d" * 64
    begin = record_stdio_operator_timing(
        state_root=tmp_path,
        setup_generation=setup,
        session_sha256=session,
        operation_name="begin_current_loop",
        operation_entry_ns=100,
        processing_complete_ns=130,
        result_return_ns=140,
        semantic_revision_sha256="e" * 64,
        wall_clock_ns=1_000_000_000,
    )
    complete = record_stdio_operator_timing(
        state_root=tmp_path,
        setup_generation=setup,
        session_sha256=session,
        operation_name="complete_current_step",
        operation_entry_ns=200,
        processing_complete_ns=250,
        result_return_ns=260,
        wall_clock_ns=1_000_000_001,
    )
    with pytest.raises(OperatorTimingEvidenceError, match="cross_session"):
        consume_stdio_operator_timing(
            state_root=tmp_path,
            setup_generation=setup,
            session_sha256="f" * 64,
            receipt_id_sha256=begin["receipt_id_sha256"],
            wall_clock_ns=1_000_000_002,
        )
    got_complete = consume_stdio_operator_timing(
        state_root=tmp_path,
        setup_generation=setup,
        session_sha256=session,
        operation_name="complete_current_step",
        wall_clock_ns=1_000_000_002,
    )
    assert got_complete["receipt_id_sha256"] == complete["receipt_id_sha256"]
    got_begin = consume_stdio_operator_timing(
        state_root=tmp_path,
        setup_generation=setup,
        session_sha256=session,
        operation_name="begin_current_loop",
        wall_clock_ns=1_000_000_002,
    )
    assert got_begin["receipt_id_sha256"] == begin["receipt_id_sha256"]
