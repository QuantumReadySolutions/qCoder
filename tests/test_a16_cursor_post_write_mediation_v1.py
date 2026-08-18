from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from qcoder.context_bridge_mcp import EXPECTED_TOOLS, build_client_activation_instructions
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.current_loop_invocation import operation_transport_inventory
from qcoder.cursor_post_write_hook import (
    CURSOR_POST_WRITE_TRANSPORT,
    cursor_post_write_hook_status,
    handle_cursor_after_file_edit_event,
    handle_cursor_stop_event,
    install_cursor_post_write_hook,
    run_cursor_after_file_edit_hook,
)

REQUEST = (
    "Use qCoder to write a Qiskit program that prepares a Φ+ Bell state. "
    "Stop after generating the code."
)


def _activate(workspace: Path) -> tuple[CurrentLoopCoordinator, dict[str, object]]:
    install_cursor_post_write_hook(workspace_root=workspace)
    coordinator = CurrentLoopCoordinator(workspace_root=workspace)
    result = coordinator.activate(
        original_request=REQUEST,
        explicit_authority=True,
        capture_mode="exact_current_customer_message",
        request_transport="stdin",
    )
    assert result["ok"] is True
    return coordinator, result


def _edit_event(
    workspace: Path,
    path: Path,
    *,
    generation: str = "generation-safe",
    old_string: str = "",
) -> dict:
    return {
        "hook_event_name": "afterFileEdit",
        "conversation_id": "conversation-safe",
        "generation_id": generation,
        "cursor_version": "3.16.17",
        "workspace_roots": [str(workspace)],
        "file_path": str(path),
        "edits": [{"old_string": old_string, "new_string": "not-retained"}],
    }


def _stop_event(workspace: Path, *, loop_count: int = 0) -> dict:
    return {
        "hook_event_name": "stop",
        "conversation_id": "conversation-safe",
        "generation_id": "generation-safe",
        "workspace_roots": [str(workspace)],
        "status": "completed",
        "loop_count": loop_count,
    }


def _contains_cli(value: object) -> bool:
    text = json.dumps(value, sort_keys=True)
    return "complete-native-action" in text or "python -m qcoder" in text


def _sources(coordinator: CurrentLoopCoordinator) -> list[dict]:
    return [
        item
        for item in coordinator.store.read()["coordinator"]["artifact_candidates"]
        if item.get("role") == "source"
    ]


def test_installer_upgrades_v27_to_matcher_free_after_file_edit_and_stop_guard(
    tmp_path: Path,
) -> None:
    hooks_path = tmp_path / ".cursor" / "hooks.json"
    hooks_path.parent.mkdir()
    hooks_path.write_text(
        json.dumps(
            {
                "version": 1,
                "hooks": {
                    "postToolUse": [
                        {"command": "existing-safe-hook", "matcher": "Read", "timeout": 5},
                        {
                            "command": "python -m qcoder current-loop cursor-post-write-hook",
                            "matcher": "Write",
                            "timeout": 30,
                            "failClosed": True,
                        },
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    installed = install_cursor_post_write_hook(workspace_root=tmp_path)
    status = cursor_post_write_hook_status(
        workspace_root=tmp_path, executable=Path(__import__("sys").executable)
    )
    assert installed["ok"] is status["configured"] is status["exact_runtime_bound"] is True
    assert status["authoritative_hook_event"] == "afterFileEdit"
    assert status["tool_name_matcher_required"] is False
    assert status["trusted_workspace_required"] is True
    assert status["legacy_post_tool_use_qcoder_hook_absent"] is True
    config = json.loads(hooks_path.read_text(encoding="utf-8"))
    assert config["hooks"]["postToolUse"] == [
        {"command": "existing-safe-hook", "matcher": "Read", "timeout": 5}
    ]
    assert len(config["hooks"]["afterFileEdit"]) == 1
    assert "matcher" not in config["hooks"]["afterFileEdit"][0]
    assert config["hooks"]["afterFileEdit"][0]["failClosed"] is True
    assert config["hooks"]["stop"][0]["loop_limit"] == 1
    inventory = {item["operation"]: item for item in operation_transport_inventory()["operations"]}
    assert inventory["cursor_after_file_edit_hook"]["public_context_bridge_tool"] is False
    assert inventory["cursor_stop_recovery_hook"]["public_context_bridge_tool"] is False
    assert len(EXPECTED_TOOLS) == 12


@pytest.mark.parametrize("existing", [False, True])
def test_semantic_after_file_edit_registers_fresh_or_existing_authorized_source(
    tmp_path: Path, existing: bool
) -> None:
    source = tmp_path / "bell_state.py"
    if existing:
        source.write_text("# existing\n", encoding="utf-8")
    coordinator, activation = _activate(tmp_path)
    action = activation["compact_next_action"]
    assert action["post_action_transport"] == CURSOR_POST_WRITE_TRANSPORT
    assert action["post_action_trigger"] == "semantic_afterFileEdit_event"
    assert action["tool_name_matcher_required"] is False
    assert action["model_shell_invocation_required"] is False
    assert action["second_native_approval_required"] is False
    assert not _contains_cli(activation)

    source.write_text("from qiskit import QuantumCircuit\n", encoding="utf-8")
    completed = handle_cursor_after_file_edit_event(
        workspace_root=tmp_path,
        event=_edit_event(
            tmp_path,
            source,
            old_string="# existing\n" if existing else "",
        ),
    )
    assert completed["ok"] is completed["registration_completed"] is True
    assert completed["output"] == {}
    assert completed["model_feedback_required_for_correctness"] is False
    assert not _contains_cli(completed)
    state = coordinator.store.read()
    assert state["coordinator"]["current_step_status"] == "complete_resumable"
    assert len(state["operation_receipts"]) == 1
    receipt = next(iter(state["operation_receipts"].values()))
    assert receipt["status"] == "consumed"
    assert receipt["authority_evidence_source"] == "cursor_after_file_edit_event"
    assert len(_sources(coordinator)) == 1
    assert _sources(coordinator)[0]["event_disposition"] == ("modified" if existing else "created")


def test_unrelated_file_edits_and_no_active_request_are_silent_noops(tmp_path: Path) -> None:
    unrelated = tmp_path / "notes.txt"
    unrelated.write_text("unrelated\n", encoding="utf-8")
    no_active = handle_cursor_after_file_edit_event(
        workspace_root=tmp_path, event=_edit_event(tmp_path, unrelated)
    )
    assert no_active == {"output": {}, "disposition": "no_active_qcoder_write", "ok": True}

    coordinator, _ = _activate(tmp_path)
    before = deepcopy(coordinator.store.read())
    ignored = handle_cursor_after_file_edit_event(
        workspace_root=tmp_path, event=_edit_event(tmp_path, unrelated)
    )
    assert ignored == {"output": {}, "disposition": "unrelated_file_edit_ignored", "ok": True}
    assert coordinator.store.read() == before


def test_duplicate_after_file_edit_delivery_cannot_double_consume(tmp_path: Path) -> None:
    coordinator, _ = _activate(tmp_path)
    source = tmp_path / "bell.py"
    source.write_text("print('safe')\n", encoding="utf-8")
    event = _edit_event(tmp_path, source)
    first = handle_cursor_after_file_edit_event(workspace_root=tmp_path, event=event)
    after_first = deepcopy(coordinator.store.read())
    second = handle_cursor_after_file_edit_event(workspace_root=tmp_path, event=event)
    assert first["registration_completed"] is True
    assert second == {"output": {}, "disposition": "no_pending_qcoder_source_write", "ok": True}
    assert coordinator.store.read() == after_first
    assert len(after_first["operation_receipts"]) == 1


def test_mismatched_path_or_changed_bytes_fail_closed_without_false_completion(
    tmp_path: Path, monkeypatch
) -> None:
    coordinator, _ = _activate(tmp_path)
    before = deepcopy(coordinator.store.read())
    outside = tmp_path.parent / "outside-hook-fixture.py"
    outside.write_text("print('outside')\n", encoding="utf-8")
    ignored = handle_cursor_after_file_edit_event(
        workspace_root=tmp_path, event=_edit_event(tmp_path, outside)
    )
    assert ignored["disposition"] == "unrelated_file_edit_ignored"
    assert coordinator.store.read() == before

    source = tmp_path / "bell.py"
    source.write_text("print('before')\n", encoding="utf-8")
    original = CurrentLoopCoordinator.complete_native_action

    def mutate_before_verification(self, **kwargs):
        source.write_text("print('changed')\n", encoding="utf-8")
        return original(self, **kwargs)

    monkeypatch.setattr(
        CurrentLoopCoordinator, "complete_native_action", mutate_before_verification
    )
    failed = handle_cursor_after_file_edit_event(
        workspace_root=tmp_path, event=_edit_event(tmp_path, source)
    )
    assert failed["ok"] is failed["registration_completed"] is False
    assert failed["safe_error_category"] == "native_client_write_event_artifact_mismatch"
    assert coordinator.store.read() == before


def test_stop_recovery_only_follows_up_for_incomplete_registration(tmp_path: Path) -> None:
    no_active = handle_cursor_stop_event(workspace_root=tmp_path, event=_stop_event(tmp_path))
    assert no_active["output"] == {}

    coordinator, _ = _activate(tmp_path)
    pending = handle_cursor_stop_event(workspace_root=tmp_path, event=_stop_event(tmp_path))
    assert pending["disposition"] == "bounded_registration_recovery_followup"
    assert "followup_message" in pending["output"]
    assert pending["authority_broadened"] is False
    repeated = handle_cursor_stop_event(
        workspace_root=tmp_path, event=_stop_event(tmp_path, loop_count=1)
    )
    assert repeated["output"] == {}

    source = tmp_path / "bell.py"
    source.write_text("print('complete')\n", encoding="utf-8")
    assert (
        handle_cursor_after_file_edit_event(
            workspace_root=tmp_path, event=_edit_event(tmp_path, source)
        )["ok"]
        is True
    )
    complete_state = deepcopy(coordinator.store.read())
    completed = handle_cursor_stop_event(workspace_root=tmp_path, event=_stop_event(tmp_path))
    assert completed == {"output": {}, "disposition": "registration_already_complete", "ok": True}
    assert coordinator.store.read() == complete_state


def test_registration_failure_is_recoverable_and_stop_guard_blocks_false_final(
    tmp_path: Path, monkeypatch
) -> None:
    coordinator, _ = _activate(tmp_path)
    source = tmp_path / "bell.py"
    source.write_text("print('safe')\n", encoding="utf-8")

    def fail_registration(self, **kwargs):
        return {"ok": False, "category": "safe_registration_failure_fixture", "details": {}}

    monkeypatch.setattr(CurrentLoopCoordinator, "register_artifacts", fail_registration)
    failed = handle_cursor_after_file_edit_event(
        workspace_root=tmp_path, event=_edit_event(tmp_path, source)
    )
    assert failed["ok"] is False
    receipt = next(iter(coordinator.store.read()["operation_receipts"].values()))
    assert receipt["status"] == "issued"
    recovery = handle_cursor_stop_event(workspace_root=tmp_path, event=_stop_event(tmp_path))
    assert recovery["disposition"] == "bounded_registration_recovery_followup"


def test_absent_hook_stdin_is_bounded_without_nontype_traceback(tmp_path: Path, capsys) -> None:
    # The Lenovo traceback is reproducible at a bytes sink when the payload is None.
    with pytest.raises(TypeError, match="a bytes-like object is required, not 'NoneType'"):
        (tmp_path / "legacy-payload.bin").write_bytes(None)  # type: ignore[arg-type]
    # The actual qCoder hook adapter now classifies that same absent-payload boundary.
    assert run_cursor_after_file_edit_hook(workspace_root=tmp_path, raw_event=None) == 2
    assert "Traceback" not in capsys.readouterr().err


def test_binding_declares_authoritative_semantic_hook_and_retains_size_target(
    tmp_path: Path,
) -> None:
    instructions = build_client_activation_instructions(
        base_url="https://example.invalid", token_file=tmp_path / "token.txt"
    )
    assert len(instructions.encode("utf-8")) <= 50_000
    normalized = " ".join(instructions.split())
    assert "matcher-free afterFileEdit hook" in normalized
    assert "Hook output is not required for correctness" in normalized
    assert "Do not issue or expose a Shell/CLI completion command" in normalized
    assert '"model_shell_invocation": false' in instructions
    assert '"second_native_approval": false' in instructions
    assert len(EXPECTED_TOOLS) == 12


def test_v27_tool_name_matcher_failure_fixture_is_obsolete_on_v28(tmp_path: Path) -> None:
    workspace = tmp_path / "cursor-v28-shape"
    workspace.mkdir()
    _, corrected = _activate(workspace)
    action = corrected["compact_next_action"]
    assert action["post_action_transport"] == CURSOR_POST_WRITE_TRANSPORT
    assert action["post_action_trigger"] == "semantic_afterFileEdit_event"
    assert action["tool_name_matcher_required"] is False
    assert not _contains_cli(corrected)
    config = json.loads((workspace / ".cursor" / "hooks.json").read_text(encoding="utf-8"))
    assert not any(
        "qcoder" in str(item.get("command", "")) for item in config["hooks"].get("postToolUse", [])
    )
