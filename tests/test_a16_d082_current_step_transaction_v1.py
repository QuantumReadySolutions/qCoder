from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from qcoder.context_bridge_mcp import EXPECTED_TOOLS
from qcoder.current_loop_binding_mcp import (
    BEGIN_CURRENT_LOOP_TOOL_NAME,
    COMPLETE_CURRENT_STEP_TOOL_NAME,
    binding_tool_descriptors,
    handle_binding_jsonrpc_message,
)
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.current_step_contract import (
    CURRENT_STEP_CONTRACT_SCHEMA_ID,
    derive_current_step_contract,
    validate_current_step_contract,
)
from qcoder.cursor_post_write_hook import (
    handle_cursor_after_file_edit_event,
    install_cursor_post_write_hook,
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


def _begin(root: Path) -> dict:
    result = _call(
        root,
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        {"request_text": REQUEST, "intended_artifact_paths": {"source": "phi_plus_bell.py"}},
    )
    assert result["ok"] is True
    return result


def _source(root: Path, name: str = "phi_plus_bell.py") -> Path:
    path = root / name
    path.write_text(SOURCE, encoding="utf-8")
    return path


def _authority_projection(state: dict) -> dict:
    receipt = next(iter(state["operation_receipts"].values()))
    head = state["evidence_registry"]["role_heads"].get("source")
    revision = state["evidence_registry"]["artifact_revisions"].get(head, {})
    activity = state["activity_receipts"][-1]
    evidence = activity["native_action_completion_evidence"]
    return {
        "current_step_status": state["coordinator"]["current_step_status"],
        "receipt_kind": receipt["receipt_kind"],
        "receipt_status": receipt["status"],
        "registered_artifact_count": receipt["registered_artifact_count"],
        "qcoder_granted_permission": receipt["native_client_permission_granted_by_qcoder"],
        "qcoder_inferred_click": receipt["user_approval_click_inferred"],
        "role_heads": sorted(state["evidence_registry"]["role_heads"]),
        "source_digest": revision.get("content_digest"),
        "artifact_role": evidence["artifact_role"],
        "artifact_cardinality": evidence["artifact_cardinality"],
        "raw_path_retained": evidence["raw_path_retained"],
        "raw_source_retained": evidence["raw_source_retained"],
    }


def test_begin_returns_small_canonical_current_step_contract(tmp_path: Path) -> None:
    result = _begin(tmp_path)
    contract = result["current_step_contract"]
    state = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    validate_current_step_contract(contract, state=state)
    assert contract["schema_id"] == CURRENT_STEP_CONTRACT_SCHEMA_ID
    assert contract["binding"]["state_revision"] == state["state_revision"]
    assert contract["current_customer_goal"] == REQUEST
    assert contract["permitted_native_action"]["artifact_role"] == "source"
    assert contract["permitted_native_action"]["cardinality"] == "exactly_one"
    assert set(contract["prohibited_current_actions"]) >= {
        "circuit_qasm",
        "execution",
        "results",
        "evidence_review",
    }
    assert contract["native_client_authority"]["owner"] == "native_client"
    assert contract["native_client_authority"]["qcoder_grants_permission"] is False
    assert contract["native_client_authority"]["qcoder_infers_approval_click"] is False
    assert contract["completion"]["operation"] == COMPLETE_CURRENT_STEP_TOOL_NAME
    assert contract == derive_current_step_contract(state)
    assert len(json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()) <= 2600


def test_private_inventory_is_begin_and_complete_while_public_remains_twelve() -> None:
    assert len(EXPECTED_TOOLS) == 12
    descriptors = binding_tool_descriptors()
    assert [item["name"] for item in descriptors] == [
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
    ]
    assert all(item["x-qcoder-public-context-bridge-tool"] is False for item in descriptors)
    completion = descriptors[1]
    assert completion["inputSchema"]["required"] == []
    assert completion["x-qcoder-normal-happy-path"] == {}
    assert "artifact_digest" not in completion["inputSchema"]["properties"]
    assert "approval" not in completion["inputSchema"]["properties"]
    assert "state_revision" not in completion["inputSchema"]["properties"]


def test_non_hook_typed_completion_registers_exact_source(tmp_path: Path) -> None:
    begun = _begin(tmp_path)
    assert not (tmp_path / ".cursor" / "hooks.json").exists()
    source = _source(tmp_path)
    handle = begun["current_step_contract"]["permitted_native_action"]["current_action_handle"]
    completed = _call(
        tmp_path,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
        {"current_action_handle": handle, "artifact_path": source.name},
    )
    assert completed["ok"] is True
    assert completed["operation"] == COMPLETE_CURRENT_STEP_TOOL_NAME
    assert completed["current_step_status"] == "complete_resumable"
    state = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    projection = _authority_projection(state)
    assert projection["role_heads"] == ["source"]
    assert projection["qcoder_granted_permission"] is False
    assert projection["qcoder_inferred_click"] is False


def test_hook_and_non_hook_have_equivalent_authority_state(tmp_path: Path) -> None:
    roots = {"typed": tmp_path / "typed", "hook": tmp_path / "hook"}
    for root in roots.values():
        root.mkdir()
    typed_begin = _begin(roots["typed"])
    typed_source = _source(roots["typed"])
    typed_handle = typed_begin["current_step_contract"]["permitted_native_action"][
        "current_action_handle"
    ]
    assert (
        _call(
            roots["typed"],
            COMPLETE_CURRENT_STEP_TOOL_NAME,
            {"current_action_handle": typed_handle, "artifact_path": typed_source.name},
        )["ok"]
        is True
    )

    install_cursor_post_write_hook(workspace_root=roots["hook"])
    _begin(roots["hook"])
    hook_source = _source(roots["hook"])
    hook_result = handle_cursor_after_file_edit_event(
        workspace_root=roots["hook"],
        event={
            "hook_event_name": "afterFileEdit",
            "conversation_id": "safe-conversation",
            "generation_id": "safe-generation",
            "workspace_roots": [str(roots["hook"])],
            "file_path": str(hook_source),
            "edits": [{"old_string": "", "new_string": "not-retained"}],
        },
    )
    assert hook_result["registration_completed"] is True

    typed_state = CurrentLoopCoordinator(workspace_root=roots["typed"]).store.read()
    hook_state = CurrentLoopCoordinator(workspace_root=roots["hook"]).store.read()
    assert _authority_projection(typed_state) == _authority_projection(hook_state)
    typed_transport = typed_state["activity_receipts"][-1]["native_action_completion_evidence"][
        "transport"
    ]
    hook_transport = hook_state["activity_receipts"][-1]["native_action_completion_evidence"][
        "transport"
    ]
    assert {typed_transport, hook_transport} == {
        "binding_owned_typed_completion",
        "client_hook_adapter",
    }


def test_hook_then_assistant_duplicate_is_idempotent(tmp_path: Path) -> None:
    install_cursor_post_write_hook(workspace_root=tmp_path)
    begun = _begin(tmp_path)
    source = _source(tmp_path)
    handle = begun["current_step_contract"]["permitted_native_action"]["current_action_handle"]
    event = {
        "hook_event_name": "afterFileEdit",
        "conversation_id": "safe-conversation",
        "generation_id": "safe-generation",
        "workspace_roots": [str(tmp_path)],
        "file_path": str(source),
        "edits": [{"old_string": "", "new_string": "not-retained"}],
    }
    assert (
        handle_cursor_after_file_edit_event(workspace_root=tmp_path, event=event)[
            "registration_completed"
        ]
        is True
    )
    before = deepcopy(CurrentLoopCoordinator(workspace_root=tmp_path).store.read())
    duplicate = _call(
        tmp_path,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
        {"current_action_handle": handle, "artifact_path": source.name},
    )
    assert duplicate["ok"] is True
    assert duplicate["category"] == "current_step_already_completed"
    assert duplicate["duplicate_delivery_noop"] is True
    assert CurrentLoopCoordinator(workspace_root=tmp_path).store.read() == before


def test_continuation_replaces_contract_without_rebootstrap(tmp_path: Path) -> None:
    begun = _begin(tmp_path)
    source = _source(tmp_path)
    handle = begun["current_step_contract"]["permitted_native_action"]["current_action_handle"]
    assert (
        _call(
            tmp_path,
            COMPLETE_CURRENT_STEP_TOOL_NAME,
            {"current_action_handle": handle, "artifact_path": source.name},
        )["ok"]
        is True
    )
    before = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    source_head = before["evidence_registry"]["role_heads"]["source"]
    continued = _call(
        tmp_path,
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        {
            "request_text": "Now export the circuit as QASM.",
            "intended_artifact_paths": {"circuit_qasm": "circuit.qasm"},
        },
    )
    assert continued["ok"] is True
    assert continued["details"]["active_loop_continuation"] is True
    assert continued["details"]["request_baseline_recreated"] is False
    assert continued["details"]["rebootstrap_performed"] is False
    assert continued["bootstrap_count"] == 1
    assert continued["request_baseline_count"] == 1
    replacement = continued["current_step_contract"]
    assert replacement["permitted_native_action"]["artifact_role"] == "circuit_qasm"
    assert replacement["contract_digest"] != begun["current_step_contract"]["contract_digest"]
    after = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    assert after["evidence_registry"]["role_heads"]["source"] == source_head


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ({"current_action_handle": "wrong-handle"}, "current_action_handle_not_active"),
        ({"artifact_path": "missing.py"}, "completed_artifact_path_not_bound_target"),
    ],
)
def test_typed_completion_wrong_action_or_path_fails_without_mutation(
    tmp_path: Path, mutation: dict, expected: str
) -> None:
    begun = _begin(tmp_path)
    source = _source(tmp_path)
    arguments = {
        "current_action_handle": begun["current_step_contract"]["permitted_native_action"][
            "current_action_handle"
        ],
        "artifact_path": source.name,
    }
    arguments.update(mutation)
    before = deepcopy(CurrentLoopCoordinator(workspace_root=tmp_path).store.read())
    result = _call(tmp_path, COMPLETE_CURRENT_STEP_TOOL_NAME, arguments)
    assert result["ok"] is False
    assert result["category"] == expected
    assert result["recovery"]["state_mutated"] is False
    assert CurrentLoopCoordinator(workspace_root=tmp_path).store.read() == before


@pytest.mark.parametrize(
    ("filename", "contents"),
    [
        ("unexpected.qasm", "OPENQASM 3;\n"),
        ("results.json", '{"counts": {"00": 1}}\n'),
    ],
)
def test_prohibited_artifact_formats_fail_under_source_only_ceiling(
    tmp_path: Path, filename: str, contents: str
) -> None:
    begun = _begin(tmp_path)
    artifact = tmp_path / filename
    artifact.write_text(contents, encoding="utf-8")
    before = deepcopy(CurrentLoopCoordinator(workspace_root=tmp_path).store.read())
    result = _call(
        tmp_path,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
        {
            "current_action_handle": begun["current_step_contract"]["permitted_native_action"][
                "current_action_handle"
            ],
            "artifact_path": artifact.name,
        },
    )
    assert result["ok"] is False
    assert CurrentLoopCoordinator(workspace_root=tmp_path).store.read() == before


def test_ambiguous_completion_shape_and_unrelated_hook_are_safe(tmp_path: Path) -> None:
    begun = _begin(tmp_path)
    before = deepcopy(CurrentLoopCoordinator(workspace_root=tmp_path).store.read())
    malformed = _call(
        tmp_path,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
        {
            "current_action_handle": begun["current_step_contract"]["permitted_native_action"][
                "current_action_handle"
            ],
            "artifact_path": "one.py",
            "artifact_paths": [str(tmp_path / "one.py"), str(tmp_path / "two.py")],
        },
    )
    assert malformed["category"] == "typed_completion_shape_invalid"
    unrelated = tmp_path / "notes.txt"
    unrelated.write_text("notes\n", encoding="utf-8")
    event = {
        "hook_event_name": "afterFileEdit",
        "conversation_id": "safe-conversation",
        "generation_id": "safe-generation",
        "workspace_roots": [str(tmp_path)],
        "file_path": str(unrelated),
        "edits": [{"old_string": "", "new_string": "not-retained"}],
    }
    ignored = handle_cursor_after_file_edit_event(workspace_root=tmp_path, event=event)
    assert ignored["disposition"] == "unrelated_native_event_ignored"
    assert CurrentLoopCoordinator(workspace_root=tmp_path).store.read() == before
