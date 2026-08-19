from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from qcoder.context_bridge_mcp import (
    CLIENT_BINDING_CONTRACT_ID,
    EXPECTED_TOOLS,
    build_client_activation_instructions,
)
from qcoder.current_loop_binding_mcp import (
    BEGIN_CURRENT_LOOP_TOOL_NAME,
    COMPLETE_CURRENT_STEP_TOOL_NAME,
    binding_tool_descriptors,
    handle_binding_jsonrpc_message,
)
from qcoder.current_loop_coordinator import CurrentLoopCoordinator


SOURCE_REQUEST = (
    "Use qCoder to write a Qiskit program that prepares a Φ+ Bell state. "
    "Stop after generating the code."
)
SOURCE = (
    "from qiskit import QuantumCircuit\n"
    "circuit = QuantumCircuit(2)\n"
    "circuit.h(0)\n"
    "circuit.cx(0, 1)\n"
)
QASM = 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\nh q[0];\ncx q[0],q[1];\n'


def _call(root: Path, operation: str, arguments: dict) -> dict:
    response = handle_binding_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": operation, "arguments": arguments},
        },
        workspace_root=root,
    )
    assert response is not None
    return response["result"]["structuredContent"]


def _bytes(value: object) -> int:
    return len(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    )


def _completed_source(root: Path) -> tuple[dict, dict]:
    begun = _call(root, BEGIN_CURRENT_LOOP_TOOL_NAME, {"request_text": SOURCE_REQUEST})
    source = root / "bell_phi_plus.py"
    source.write_text(SOURCE, encoding="utf-8")
    completed = _call(
        root,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
        {
            "current_action_handle": begun["current_step_contract"]["permitted_native_action"][
                "current_action_handle"
            ],
            "artifact_path": str(source),
        },
    )
    return begun, completed


def test_qasm_continuation_returns_only_compact_replacement_contract(tmp_path: Path) -> None:
    begun, completed = _completed_source(tmp_path)
    assert completed["current_step_status"] == "complete_resumable"
    continued = _call(
        tmp_path,
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        {"request_text": "Now export the circuit as QASM."},
    )
    assert continued["ok"] is True
    assert continued["operation"] == "interpret_current_request"
    assert continued["schema_id"] == "qcoder.current_loop.coordinator_result.v20"
    assert continued["projection_schema_id"] == ("qcoder.current_loop.normal_success_projection.v2")
    assert continued["customer_summary"] == "Proceed with the requested QASM task."
    assert continued["current_step_contract_is_sole_action_source"] is True
    assert continued["active_loop_transition"] == {
        "rebootstrap_performed": False,
        "request_baseline_recreated": False,
        "prior_canonical_evidence_preserved": True,
        "customer_visible_procedure": False,
    }
    assert continued["bootstrap_count"] == 1
    assert continued["request_baseline_count"] == 1
    assert "compact_next_action" not in continued
    assert continued["current_request_semantics"] == {
        "projection": "active_loop_requested_operation_only",
        "requested_operation": "qasm_export",
        "semantics_digest": continued["request_identity"]["semantics_digest"],
    }
    assert "bounded_contract_controls" not in continued
    assert "bounded_control_catalog" not in continued
    assert "customer_interaction" not in continued
    assert "customer_envelope" not in continued
    assert "next_invocation" not in continued
    contract = continued["current_step_contract"]
    assert contract["permitted_native_action"]["artifact_role"] == "circuit_qasm"
    assert [row["role"] for row in contract["authoritative_evidence_references"]] == ["source"]
    assert contract["customer_visibility"]["mechanics"] == "silent"
    assert _bytes(contract) <= 2_500
    assert _bytes(continued) <= 5_000
    assert _bytes(begun) <= 13_000


def test_qasm_continuation_completes_without_rebootstrap_or_results(tmp_path: Path) -> None:
    _completed_source(tmp_path)
    source_state = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    source_head = source_state["evidence_registry"]["role_heads"]["source"]
    continued = _call(
        tmp_path,
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        {"request_text": "Now export the circuit as QASM."},
    )
    qasm = tmp_path / "bell_phi_plus.qasm"
    qasm.write_text(QASM, encoding="utf-8")
    completed = _call(
        tmp_path,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
        {
            "current_action_handle": continued["current_step_contract"]["permitted_native_action"][
                "current_action_handle"
            ],
            "artifact_path": str(qasm),
        },
    )
    assert completed["ok"] is True
    assert completed["current_step_status"] == "complete_resumable"
    assert completed["artifact"]["role"] == "circuit_qasm"
    state = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    coordinator = state["coordinator"]
    assert coordinator["bootstrap_count"] == 1
    assert coordinator["request_baseline_count"] == 1
    assert state["evidence_registry"]["role_heads"]["source"] == source_head
    assert "circuit_qasm" in state["evidence_registry"]["role_heads"]
    assert "results" not in state["evidence_registry"]["role_heads"]


def test_continuation_binding_is_direct_quiet_and_keeps_two_private_tools(
    tmp_path: Path,
) -> None:
    assert CLIENT_BINDING_CONTRACT_ID == "qcoder.connected_assistant.client_binding.v34"
    assert len(EXPECTED_TOOLS) == 12
    descriptors = binding_tool_descriptors()
    assert [row["name"] for row in descriptors] == [
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
    ]
    continuation = descriptors[0]["x-qcoder-active-loop-continuation"]
    assert continuation["reuse_active_loop"] is True
    assert continuation["rebootstrap"] is False
    assert continuation["pre_contract_procedure_reasoning"] is False
    assert continuation["customer_visible_transition_narration"] is False
    instructions = build_client_activation_instructions(
        base_url="https://example.invalid",
        token_file=tmp_path / "token.txt",
    )
    assert len(instructions.encode()) <= 50_000


def test_ambiguous_continuation_stays_full_fail_closed_without_mutation(
    tmp_path: Path,
) -> None:
    _completed_source(tmp_path)
    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path)
    before = deepcopy(coordinator.store.read())
    result = coordinator.interpret_current_request(exact_message="Don’t run it yet.")
    assert result["ok"] is False
    assert result["category"] == "active_loop_continuation_ambiguous"
    assert result["state_mutated"] is False
    assert result["recovery"]["fail_closed"] is True
    assert coordinator.store.read() == before
