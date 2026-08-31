from __future__ import annotations

from pathlib import Path

from qcoder.context_bridge_mcp import (
    CLIENT_BINDING_CONTRACT_ID,
    CLIENT_BINDING_SCHEMA_VERSION,
    EXPECTED_TOOLS,
)
from qcoder.current_loop_binding_mcp import (
    BEGIN_CURRENT_LOOP_TOOL_NAME,
    COMPLETE_CURRENT_STEP_TOOL_NAME,
    binding_tool_descriptors,
    handle_binding_jsonrpc_message,
)
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.current_step_contract import (
    CURRENT_STEP_CONTRACT_SCHEMA_ID,
    CURRENT_STEP_CONTRACT_SCHEMA_VERSION,
)
from qcoder.cursor_post_write_hook import (
    handle_cursor_after_file_edit_event,
    install_cursor_post_write_hook,
)


REQUEST = (
    "Use qCoder to write a Qiskit program that prepares a Bell state. "
    "Stop after generating the source."
)
SOURCE = (
    "from qiskit import QuantumCircuit\n"
    "circuit = QuantumCircuit(2)\n"
    "circuit.h(0)\n"
    "circuit.cx(0, 1)\n"
)


def _call(root: Path, name: str, arguments: dict[str, object]) -> dict[str, object]:
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


def _begin(root: Path) -> dict[str, object]:
    return _call(
        root,
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        {
            "request_text": REQUEST,
            "intended_artifact_paths": {"source": "bell.py"},
        },
    )


def _assert_one_source_registration(root: Path) -> None:
    state = CurrentLoopCoordinator(workspace_root=root).store.read()
    registry = state["evidence_registry"]
    assert list(registry["role_heads"]) == ["source"]
    assert len(registry["artifact_revisions"]) == 1
    assert len(state["activity_receipts"]) == 1
    assert (
        sum(
            receipt.get("status") == "consumed"
            and receipt.get("receipt_kind") == "qcoder_bounded_action_expectation"
            for receipt in state["operation_receipts"].values()
        )
        == 1
    )
    assert state["coordinator"]["current_step_status"] == "complete_resumable"
    assert state["coordinator"]["current_step_substage"] == "source"
    assert state["coordinator"]["bootstrap_count"] == 1
    assert state["coordinator"]["request_baseline_count"] == 1
    assert all(
        artifact.get("role") == "source"
        for receipt in state["activity_receipts"]
        for artifact in receipt.get("registered_artifacts", [])
    )
    assert '"results"' not in registry["role_heads"]


def test_hook_present_contract_selects_synchronous_terminal_closure(tmp_path: Path) -> None:
    install_cursor_post_write_hook(workspace_root=tmp_path)
    begun = _begin(tmp_path)
    contract = begun["current_step_contract"]
    assert contract["schema_id"] == CURRENT_STEP_CONTRACT_SCHEMA_ID
    assert contract["schema_version"] == CURRENT_STEP_CONTRACT_SCHEMA_VERSION
    assert contract["completion"]["mode"] == "synchronous_native_edit_event"
    assert contract["completion"]["required_arguments"] == []
    action = begun["compact_next_action"]
    assert action["qcoder_calls"] == 1
    assert action["post_source_generation_model_procedure_reentry_required"] is False
    assert action["post_action_trigger"] == (
        "first_valid_exact_native_edit_event_is_terminal_closure"
    )

    source = tmp_path / "bell.py"
    source.write_text(SOURCE, encoding="utf-8")
    completed = handle_cursor_after_file_edit_event(
        workspace_root=tmp_path,
        event={
            "hook_event_name": "afterFileEdit",
            "conversation_id": "bounded-conversation",
            "generation_id": "bounded-generation",
            "workspace_roots": [str(tmp_path)],
            "file_path": str(source),
            "edits": [{"old_string": "", "new_string": "not-retained"}],
        },
    )
    assert completed["disposition"] == "exact_registration_completed"
    assert completed["model_feedback_required_for_correctness"] is False
    assert completed["raw_path_returned"] is False
    assert completed["raw_source_returned"] is False
    _assert_one_source_registration(tmp_path)

    duplicate = _call(tmp_path, COMPLETE_CURRENT_STEP_TOOL_NAME, {})
    assert duplicate["category"] == "current_step_already_completed"
    assert duplicate["duplicate_delivery_noop"] is True
    assert duplicate["canonical_state_mutated"] is False
    _assert_one_source_registration(tmp_path)


def test_hook_absent_contract_preserves_typed_completion_equivalence(tmp_path: Path) -> None:
    begun = _begin(tmp_path)
    contract = begun["current_step_contract"]
    assert contract["completion"]["mode"] == "binding_owned_typed_completion"
    assert contract["completion"]["canonical_arguments"] == {}
    action = begun["compact_next_action"]
    assert action["qcoder_calls"] == 2
    assert action["post_source_generation_model_procedure_reentry_required"] is True

    source = tmp_path / "bell.py"
    source.write_text(SOURCE, encoding="utf-8")
    completed = _call(tmp_path, COMPLETE_CURRENT_STEP_TOOL_NAME, {})
    assert completed["ok"] is True
    assert completed["completion"]["exact_artifact_registered"] is True
    assert completed["customer_summary"] == (
        "The requested source artifact is ready; qCoder stopped at source."
    )
    _assert_one_source_registration(tmp_path)


def test_terminal_closure_identity_and_inventory_are_bounded() -> None:
    assert CLIENT_BINDING_CONTRACT_ID == "qcoder.connected_assistant.client_binding.v50"
    assert CLIENT_BINDING_SCHEMA_VERSION == 49
    assert CURRENT_STEP_CONTRACT_SCHEMA_ID == "qcoder.current_loop.current_step_contract.v11"
    assert CURRENT_STEP_CONTRACT_SCHEMA_VERSION == 11
    assert len(EXPECTED_TOOLS) == 12
    assert [item["name"] for item in binding_tool_descriptors()] == [
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
    ]


def test_contract_route_is_bound_at_issuance_and_not_reconstructed(tmp_path: Path) -> None:
    install_cursor_post_write_hook(workspace_root=tmp_path)
    begun = _begin(tmp_path)
    state = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    handle = begun["current_step_contract"]["permitted_native_action"]["current_action_handle"]
    receipt = state["operation_receipts"][handle]
    route = receipt["authority_binding"]["terminal_closure"]
    assert route["mode"] == "synchronous_native_edit_event"
    assert route["assistant_procedure_reentry_required_after_native_action"] is False
    assert route["native_client_permission_owner"] == "native_client"
    assert route["qcoder_mutates_customer_artifact"] is False
    assert route["qcoder_executes_customer_code"] is False
    assert route["duplicate_delivery_disposition"] == "idempotent_noop"
    assert state["coordinator"]["terminal_closure_route"] == route
