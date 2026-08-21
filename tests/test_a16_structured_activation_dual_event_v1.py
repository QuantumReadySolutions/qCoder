from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from qcoder.context_bridge_mcp import EXPECTED_TOOLS
from qcoder.context_bridge_mcp import build_inline_client_binding_descriptor
from qcoder.current_loop_binding_mcp import (
    BEGIN_CURRENT_LOOP_TOOL_NAME,
    COMPLETE_CURRENT_STEP_TOOL_NAME,
    binding_tool_descriptors,
    handle_binding_jsonrpc_message,
)
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.cursor_post_write_hook import (
    handle_cursor_after_file_edit_event,
    handle_cursor_post_tool_use_event,
    handle_cursor_stop_event,
    install_cursor_post_write_hook,
)

REQUEST = (
    "Use qCoder to write a Qiskit program that prepares a Φ+ Bell state. "
    "Stop after generating the code."
)


def _begin(workspace: Path, request: str = REQUEST) -> dict:
    response = handle_binding_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": BEGIN_CURRENT_LOOP_TOOL_NAME,
                "arguments": {
                    "request_text": request,
                    "intended_artifact_paths": {"source": "bell.py"},
                },
            },
        },
        workspace_root=workspace,
    )
    assert response is not None
    return response["result"]["structuredContent"]


def _after(workspace: Path, source: Path) -> dict:
    return {
        "hook_event_name": "afterFileEdit",
        "conversation_id": "conversation-safe",
        "generation_id": "generation-safe",
        "workspace_roots": [str(workspace)],
        "file_path": str(source),
        "edits": [{"old_string": "", "new_string": "not-retained"}],
    }


def _post(workspace: Path, source: Path, content: str, *, tool_name: str = "OtherEdit") -> dict:
    return {
        "hook_event_name": "postToolUse",
        "conversation_id": "conversation-safe",
        "generation_id": "generation-safe",
        "workspace_roots": [str(workspace)],
        "tool_name": tool_name,
        "tool_input": {"path": str(source), "content": content},
        "tool_output": json.dumps(
            {
                "success": True,
                "file_path": str(source),
                "bytes_written": len(content.encode("utf-8")),
            }
        ),
    }


def _stop(workspace: Path) -> dict:
    return {
        "hook_event_name": "stop",
        "conversation_id": "conversation-safe",
        "generation_id": "generation-safe",
        "workspace_roots": [str(workspace)],
        "status": "completed",
        "loop_count": 0,
    }


def test_structured_activation_requires_exact_typed_request_and_transports_it_once(
    tmp_path: Path,
) -> None:
    install_cursor_post_write_hook(workspace_root=tmp_path)
    missing = handle_binding_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": BEGIN_CURRENT_LOOP_TOOL_NAME, "arguments": {}},
        },
        workspace_root=tmp_path,
    )
    assert missing is not None
    rejected = missing["result"]["structuredContent"]
    assert rejected["ok"] is False
    assert rejected["state_mutated"] is False
    assert not (tmp_path / ".qcoder" / "current-loop" / "state.json").exists()

    activated = _begin(tmp_path)
    assert activated["ok"] is True
    assert activated["details"]["request_text_argument_received_once"] is True
    assert activated["details"]["shell_or_cli_transport_used"] is False
    assert activated["details"]["stdin_transport_used"] is False
    assert (
        activated["request_identity"]["original_message_utf8_sha256"]
        == sha256(REQUEST.encode("utf-8")).hexdigest()
    )
    baseline = json.loads(
        (tmp_path / ".qcoder" / "current-loop" / "artifacts" / "request-baseline.json").read_text(
            encoding="utf-8"
        )
    )
    assert baseline["original_request"] == REQUEST
    assert activated["bootstrap_count"] == 1


@pytest.mark.parametrize("winner", ["afterFileEdit", "postToolUse"])
def test_either_native_event_signal_alone_can_complete_exact_registration(
    tmp_path: Path, winner: str
) -> None:
    install_cursor_post_write_hook(workspace_root=tmp_path)
    activated = _begin(tmp_path)
    assert activated["compact_next_action"]["model_shell_invocation_required"] is False
    source = tmp_path / "bell.py"
    content = "from qiskit import QuantumCircuit\n"
    source.write_text(content, encoding="utf-8")
    event = (
        _after(tmp_path, source)
        if winner == "afterFileEdit"
        else _post(tmp_path, source, content, tool_name="NeverAssumeThisName")
    )
    completed = (
        handle_cursor_after_file_edit_event(workspace_root=tmp_path, event=event)
        if winner == "afterFileEdit"
        else handle_cursor_post_tool_use_event(workspace_root=tmp_path, event=event)
    )
    assert completed["ok"] is completed["registration_completed"] is True
    state = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    assert state["coordinator"]["current_step_status"] == "complete_resumable"
    assert len(state["operation_receipts"]) == 1
    assert next(iter(state["operation_receipts"].values()))["status"] == "consumed"


def test_first_valid_event_wins_and_duplicate_delivery_is_an_idempotent_noop(
    tmp_path: Path,
) -> None:
    install_cursor_post_write_hook(workspace_root=tmp_path)
    _begin(tmp_path)
    source = tmp_path / "bell.py"
    content = "print('bell')\n"
    source.write_text(content, encoding="utf-8")
    first = handle_cursor_post_tool_use_event(
        workspace_root=tmp_path, event=_post(tmp_path, source, content)
    )
    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path)
    after_first = deepcopy(coordinator.store.read())
    second = handle_cursor_after_file_edit_event(
        workspace_root=tmp_path, event=_after(tmp_path, source)
    )
    assert first["registration_completed"] is True
    assert second["disposition"] == "no_pending_qcoder_source_write"
    assert coordinator.store.read() == after_first
    assert len(after_first["operation_receipts"]) == 1


def test_unrelated_and_mismatched_post_tool_events_fail_without_registration(
    tmp_path: Path,
) -> None:
    install_cursor_post_write_hook(workspace_root=tmp_path)
    _begin(tmp_path)
    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path)
    source = tmp_path / "bell.py"
    source.write_text("print('actual')\n", encoding="utf-8")
    before = deepcopy(coordinator.store.read())
    unrelated = _post(tmp_path, source, "print('actual')\n", tool_name="ReadLike")
    unrelated["tool_input"] = {"file_path": str(source)}
    unrelated["tool_output"] = json.dumps({"success": True})
    ignored = handle_cursor_post_tool_use_event(workspace_root=tmp_path, event=unrelated)
    assert ignored["disposition"] == "unrelated_native_event_ignored"
    assert coordinator.store.read() == before

    mismatched = _post(tmp_path, source, "print('not-current')\n")
    with pytest.raises(ValueError, match="cursor_post_tool_use_content_mismatch"):
        handle_cursor_post_tool_use_event(workspace_root=tmp_path, event=mismatched)
    assert coordinator.store.read() == before


def test_stop_recovery_is_exceptional_and_success_adds_no_followup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_cursor_post_write_hook(workspace_root=tmp_path)
    _begin(tmp_path)
    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path)
    assert handle_cursor_stop_event(workspace_root=tmp_path, event=_stop(tmp_path))["output"] == {}
    source = tmp_path / "bell.py"
    source.write_text("print('bell')\n", encoding="utf-8")

    def fail_registration(self, **kwargs):
        return {"ok": False, "category": "safe_registration_failure", "details": {}}

    monkeypatch.setattr(CurrentLoopCoordinator, "register_artifacts", fail_registration)
    failed = handle_cursor_after_file_edit_event(
        workspace_root=tmp_path, event=_after(tmp_path, source)
    )
    assert failed["ok"] is False
    recovery = handle_cursor_stop_event(workspace_root=tmp_path, event=_stop(tmp_path))
    assert recovery["disposition"] == "bounded_registration_recovery_followup"
    assert "followup_message" in recovery["output"]
    assert coordinator.store.read()["coordinator"]["current_step_status"] != "complete_resumable"


def test_private_binding_operation_does_not_expand_public_context_bridge_inventory() -> None:
    descriptors = binding_tool_descriptors()
    assert [item["name"] for item in descriptors] == [
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
    ]
    assert all(item["x-qcoder-public-context-bridge-tool"] is False for item in descriptors)
    assert len(EXPECTED_TOOLS) == 12
    assert BEGIN_CURRENT_LOOP_TOOL_NAME not in EXPECTED_TOOLS
    assert COMPLETE_CURRENT_STEP_TOOL_NAME not in EXPECTED_TOOLS
    inline = build_inline_client_binding_descriptor(
        coordinator_prefix=["python", "-m", "qcoder", "current-loop"]
    )["client_binding_contract"]
    assert "bootstrap_invocation_contract" not in inline
    assert inline["workstyle_routes"]["active_build"]["action"] == (
        "call_binding_owned_begin_current_loop"
    )
