from __future__ import annotations

import json
from pathlib import Path

from qcoder.context_bridge_mcp import (
    CLIENT_BINDING_CONTRACT_ID,
    EXPECTED_TOOLS,
    build_client_activation_instructions,
    build_client_binding_descriptor,
)
from qcoder.current_loop_binding_mcp import (
    BEGIN_CURRENT_LOOP_TOOL_NAME,
    COMPLETE_CURRENT_STEP_TOOL_NAME,
    binding_tool_descriptors,
    handle_binding_jsonrpc_message,
)


REQUEST = (
    "Use qCoder to write a Qiskit program that prepares a Φ+ Bell state. "
    "Stop after generating the code."
)
SOURCE = (
    "from qiskit import QuantumCircuit\n"
    "circuit = QuantumCircuit(2)\n"
    "circuit.h(0)\n"
    "circuit.cx(0, 1)\n"
)


def _call(root: Path, name: str, arguments: dict) -> dict:
    response = handle_binding_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        workspace_root=root,
    )
    assert response is not None
    return response["result"]["structuredContent"]


def _wire_bytes(value: object) -> int:
    return len(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    )


def test_binding_and_private_tools_encode_semantic_quiet_success(tmp_path: Path) -> None:
    descriptor = build_client_binding_descriptor(
        coordinator_prefix=["python", "-m", "qcoder", "current-loop"]
    )["client_binding_contract"]
    visibility = descriptor["surfaces"]["current_step_transaction"]["customer_visibility"]
    assert CLIENT_BINDING_CONTRACT_ID == "qcoder.connected_assistant.client_binding.v32"
    assert visibility["normal_success"] == "internal_transaction_silent"
    assert visibility["intermediate_customer_message_permitted"] is False
    assert visibility["final_response"] == "concise_task_outcome_only"
    assert set(visibility["surface_when"]) >= {
        "blocking_failure",
        "ambiguity",
        "bounded_recovery",
    }
    private = binding_tool_descriptors()
    assert [item["name"] for item in private] == [
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
    ]
    assert all(item["x-qcoder-customer-visibility"] == visibility for item in private)
    assert len(EXPECTED_TOOLS) == 12
    instructions = build_client_activation_instructions(
        base_url="https://example.invalid",
        token_file=tmp_path / "token.txt",
    )
    assert len(instructions.encode()) <= 50_000
    assert "Normal begin / native action / typed complete success is silent internal work" in (
        instructions
    )


def test_normal_begin_is_task_level_and_contract_stays_bounded(tmp_path: Path) -> None:
    begun = _call(tmp_path, BEGIN_CURRENT_LOOP_TOOL_NAME, {"request_text": REQUEST})
    contract = begun["current_step_contract"]
    assert _wire_bytes(contract) <= 2048
    assert contract["customer_visibility"] == {
        "policy": "quiet_current_step_v1",
        "normal_success": "task_only",
        "intermediate_message": False,
        "internal_procedure": False,
        "surface_non_success": True,
    }
    assert begun["customer_summary"] == "Proceed with the requested source task."
    assert begun["compact_next_action"]["normal_path_qcoder_serial_cycles_including_bootstrap"] == 2
    assert begun["compact_next_action"]["normal_path_expected_model_turns"] == 3


def test_normal_typed_completion_is_compact_task_only_and_final_ready(
    tmp_path: Path,
) -> None:
    begun = _call(tmp_path, BEGIN_CURRENT_LOOP_TOOL_NAME, {"request_text": REQUEST})
    source = tmp_path / "bell_phi_plus.py"
    source.write_text(SOURCE, encoding="utf-8")
    completed = _call(
        tmp_path,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
        {
            "current_action_handle": begun["current_step_contract"]["permitted_native_action"][
                "current_action_handle"
            ],
            "artifact_path": str(source),
        },
    )
    assert completed["schema_id"] == "qcoder.current_loop.typed_completion_result.v2"
    assert completed["current_step_status"] == "complete_resumable"
    assert completed["customer_summary"] == "The requested source artifact is ready."
    assert completed["customer_visibility"]["normal_success"] == ("internal_transaction_silent")
    assert completed["customer_visibility"]["intermediate_customer_message_permitted"] is False
    assert completed["final_response_permitted"] is True
    assert completed["internal_procedure_customer_visible"] is False
    assert completed["completion"]["exact_artifact_registered"] is True
    assert completed["completion"]["bounded_action_consumed"] is True
    assert completed["continuation"] == {
        "on_next_customer_instruction": "begin_current_loop",
        "transport": "private_current_loop_binding",
        "rebootstrap": False,
        "request_baseline_recreated": False,
    }
    assert "structured_argv" not in json.dumps(completed)
    assert str(tmp_path) not in json.dumps(completed)
    assert _wire_bytes(completed) <= 2500


def test_failure_remains_visible_and_fail_closed(tmp_path: Path) -> None:
    begun = _call(tmp_path, BEGIN_CURRENT_LOOP_TOOL_NAME, {"request_text": REQUEST})
    failed = _call(
        tmp_path,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
        {
            "current_action_handle": begun["current_step_contract"]["permitted_native_action"][
                "current_action_handle"
            ],
            "artifact_path": str(tmp_path / "missing.py"),
        },
    )
    assert failed["ok"] is False
    assert failed["customer_visibility"]["disposition"] == ("surface_bounded_recovery")
    assert failed["recovery"]["state_mutated"] is False
    assert failed["current_step_status"] == "awaiting_external_client_action"


def test_multi_stage_completion_returns_next_contract_without_customer_final(
    tmp_path: Path,
) -> None:
    request = "Use qCoder to write the source and export QASM, but do not run it."
    begun = _call(tmp_path, BEGIN_CURRENT_LOOP_TOOL_NAME, {"request_text": request})
    source = tmp_path / "circuit.py"
    source.write_text(SOURCE, encoding="utf-8")
    completed = _call(
        tmp_path,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
        {
            "current_action_handle": begun["current_step_contract"]["permitted_native_action"][
                "current_action_handle"
            ],
            "artifact_path": str(source),
        },
    )
    assert completed["current_step_status"] == "awaiting_external_client_action"
    assert completed["final_response_permitted"] is False
    assert (
        completed["current_step_contract"]["permitted_native_action"]["artifact_role"]
        == "circuit_qasm"
    )
    assert completed["continuation"]["rebootstrap"] is False
