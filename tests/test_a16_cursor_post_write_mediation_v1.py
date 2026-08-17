from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from qcoder.context_bridge_mcp import EXPECTED_TOOLS, build_client_activation_instructions
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.current_loop_invocation import operation_transport_inventory
from qcoder.cursor_post_write_hook import (
    CURSOR_POST_WRITE_TRANSPORT,
    cursor_post_write_hook_status,
    handle_cursor_post_write_event,
    install_cursor_post_write_hook,
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


def _write_event(workspace: Path, path: Path) -> dict[str, object]:
    return {
        "hook_event_name": "postToolUse",
        "tool_name": "Write",
        "conversation_id": "conversation-safe-fixture",
        "generation_id": "generation-safe-fixture",
        "tool_use_id": "write-safe-fixture",
        "cwd": str(workspace),
        "workspace_roots": [str(workspace)],
        "tool_input": {"file_path": str(path)},
    }


def _contains_cli(value: object) -> bool:
    text = json.dumps(value, sort_keys=True)
    return "complete-native-action" in text or "python -m qcoder" in text


def test_cursor_hook_is_project_scoped_exact_runtime_bound_and_not_public_tool(
    tmp_path: Path,
) -> None:
    unrelated = tmp_path / ".cursor" / "hooks.json"
    unrelated.parent.mkdir()
    unrelated.write_text(
        json.dumps(
            {
                "version": 1,
                "hooks": {
                    "postToolUse": [
                        {"command": "existing-safe-hook", "matcher": "Read", "timeout": 5}
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
    config = json.loads(unrelated.read_text(encoding="utf-8"))
    assert len(config["hooks"]["postToolUse"]) == 2
    hook = next(item for item in config["hooks"]["postToolUse"] if item["matcher"] == "Write")
    assert hook["failClosed"] is True
    assert hook["timeout"] == 30
    assert len(EXPECTED_TOOLS) == 12
    inventory = {item["operation"]: item for item in operation_transport_inventory()["operations"]}
    assert inventory["cursor_post_write_hook"]["transport"] == "cursor_project_hook"
    assert inventory["cursor_post_write_hook"]["public_context_bridge_tool"] is False


def test_successful_native_write_completes_exact_registration_without_shell_or_second_approval(
    tmp_path: Path,
) -> None:
    coordinator, activation = _activate(tmp_path)
    action = activation["compact_next_action"]
    assert action["post_action_transport"] == CURSOR_POST_WRITE_TRANSPORT
    assert action["post_action_trigger"] == "successful_native_write_postToolUse"
    assert action["model_shell_invocation_required"] is False
    assert action["second_native_approval_required"] is False
    assert action["normal_path_expected_model_turns"] == 3
    assert action["normal_path_qcoder_serial_cycles_including_bootstrap"] == 2
    assert not _contains_cli(activation)

    source = tmp_path / "bell_state.py"
    exact_bytes = b"from qiskit import QuantumCircuit\n"
    source.write_bytes(exact_bytes)
    completed = handle_cursor_post_write_event(
        workspace_root=tmp_path,
        event=_write_event(tmp_path, source),
    )
    assert completed["ok"] is completed["registration_completed"] is True
    assert completed["second_native_approval_required"] is False
    assert completed["shell_tool_invocation_required"] is False
    assert not _contains_cli(completed)
    assert str(source) not in json.dumps(completed)
    assert "concise truthful final" in completed["output"]["additional_context"]
    state = coordinator.store.read()
    assert len(state["operation_receipts"]) == 1
    receipt = next(iter(state["operation_receipts"].values()))
    assert receipt["status"] == "consumed"
    assert receipt["authority_evidence_source"] == "cursor_successful_native_write_event"
    assert len(receipt["native_client_event_binding_digest"]) == 64
    sources = [
        item for item in state["coordinator"]["artifact_candidates"] if item.get("role") == "source"
    ]
    assert len(sources) == 1


def test_failed_write_and_mismatched_write_event_fail_closed_without_registration(
    tmp_path: Path,
) -> None:
    coordinator, _ = _activate(tmp_path)
    before = deepcopy(coordinator.store.read())
    try:
        handle_cursor_post_write_event(
            workspace_root=tmp_path,
            event=_write_event(tmp_path, tmp_path / "missing.py"),
        )
    except ValueError as exc:
        assert str(exc) == "cursor_hook_exact_path_invalid"
    else:
        raise AssertionError("a failed write must not be registered")
    assert coordinator.store.read() == before

    source = tmp_path / "bell.py"
    source.write_text("print('safe')\n", encoding="utf-8")
    outside = tmp_path.parent / "outside-a16-hook.py"
    outside.write_text("print('outside')\n", encoding="utf-8")
    try:
        failed = handle_cursor_post_write_event(
            workspace_root=tmp_path,
            event=_write_event(tmp_path, outside),
        )
    except ValueError as exc:
        assert str(exc) == "cursor_hook_exact_path_outside_workspace"
    else:
        assert failed["ok"] is False
    assert coordinator.store.read() == before


def test_hook_failure_context_blocks_final_and_retains_recoverable_truth(
    tmp_path: Path, monkeypatch
) -> None:
    coordinator, _ = _activate(tmp_path)
    source = tmp_path / "bell.py"
    source.write_text("print('safe')\n", encoding="utf-8")

    def fail_registration(self, **kwargs):
        return {
            "ok": False,
            "category": "safe_registration_failure_fixture",
            "details": {},
        }

    monkeypatch.setattr(CurrentLoopCoordinator, "register_artifacts", fail_registration)
    result = handle_cursor_post_write_event(
        workspace_root=tmp_path,
        event=_write_event(tmp_path, source),
    )
    assert result["ok"] is False
    assert result["state_truth_retained"] is True
    assert "Do not give the final success response" in result["output"]["additional_context"]
    assert next(iter(coordinator.store.read()["operation_receipts"].values()))["status"] == "issued"


def test_binding_declares_structural_same_turn_cursor_transport_and_retains_size_target(
    tmp_path: Path,
) -> None:
    instructions = build_client_activation_instructions(
        base_url="https://example.invalid",
        token_file=tmp_path / "token.txt",
    )
    assert len(instructions.encode("utf-8")) <= 50_000
    normalized = " ".join(instructions.split())
    assert "project-scoped postToolUse hook" in normalized
    assert "Do not issue or expose a Shell/CLI completion command" in normalized
    assert '"model_shell_invocation": false' in instructions
    assert '"second_native_approval": false' in instructions


def test_lenovo_raw_shell_second_approval_path_is_not_needed_on_supported_cursor_path(
    tmp_path: Path,
) -> None:
    legacy_workspace = tmp_path / "legacy-v26-shape"
    legacy_workspace.mkdir()
    legacy = CurrentLoopCoordinator(workspace_root=legacy_workspace).activate(
        original_request=REQUEST,
        explicit_authority=True,
        capture_mode="exact_current_customer_message",
        request_transport="stdin",
    )
    assert _contains_cli(legacy)
    assert legacy["compact_next_action"]["post_action_transport"] == "local_command"

    corrected_workspace = tmp_path / "cursor-v27-shape"
    corrected_workspace.mkdir()
    _, corrected = _activate(corrected_workspace)
    assert not _contains_cli(corrected)
    assert corrected["compact_next_action"]["post_action_transport"] == (
        CURSOR_POST_WRITE_TRANSPORT
    )
    assert corrected["compact_next_action"]["second_native_approval_required"] is False
