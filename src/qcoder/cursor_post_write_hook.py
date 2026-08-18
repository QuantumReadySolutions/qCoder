"""Cursor-native completion for an active qCoder source action.

The authoritative seam is Cursor's semantic ``afterFileEdit`` event.  It is a
configured client lifecycle hook, not a model tool and not a generic tool-name
matcher.  For the one pending source action it binds the absolute edited path
and current bytes to the existing Current Loop authority receipt, registers the
artifact, and consumes the receipt in one local process.

Cursor's ``stop`` hook is recovery-only.  It is silent when there is no pending
qCoder source action or registration already completed, and supplies one
bounded follow-up when the active request would otherwise stop incomplete.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

from qcoder.current_loop import CurrentLoopError, canonical_bytes
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.current_loop_evidence_processing import registration_format_outcome

CURSOR_POST_WRITE_HOOK_SCHEMA_ID = "qcoder.current_loop.cursor_after_file_edit_hook.v2"
CURSOR_POST_WRITE_HOOK_SCHEMA_VERSION = 2
CURSOR_POST_WRITE_TRANSPORT = "cursor_project_after_file_edit_hook"
CURSOR_POST_WRITE_HOOK_MAX_INPUT_BYTES = 1_048_576

_AFTER_FILE_EDIT_SUBCOMMAND = "cursor-after-file-edit-hook"
_STOP_RECOVERY_SUBCOMMAND = "cursor-stop-recovery-hook"
_LEGACY_POST_TOOL_USE_SUBCOMMAND = "cursor-post-write-hook"
_INSTALL_SUBCOMMAND = "install-cursor-post-write-hook"
_SUCCESS_DISPOSITION = "exact_registration_completed"
_RECOVERY_MESSAGE = (
    "qCoder's exact source registration is still incomplete. Do not claim completion, export "
    "QASM, run code, or broaden authority. Retain the already-written exact source and use only "
    "qCoder's bounded registration recovery for this active request."
)


class CursorPostWriteHookError(ValueError):
    """One bounded Cursor hook configuration or event error."""

    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


def _digest_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _hook_command(executable: str | Path, subcommand: str) -> str:
    argv = [
        str(Path(executable).expanduser().absolute()),
        "-m",
        "qcoder",
        "current-loop",
        subcommand,
    ]
    return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


def cursor_after_file_edit_hook_definition(*, executable: str | Path) -> dict[str, Any]:
    """Return the matcher-free authoritative Agent file-edit hook."""

    return {
        "command": _hook_command(executable, _AFTER_FILE_EDIT_SUBCOMMAND),
        "timeout": 30,
        "failClosed": True,
    }


def cursor_stop_recovery_hook_definition(*, executable: str | Path) -> dict[str, Any]:
    """Return the bounded stop guard; it may auto-follow-up at most once."""

    return {
        "command": _hook_command(executable, _STOP_RECOVERY_SUBCOMMAND),
        "timeout": 30,
        "loop_limit": 1,
        "failClosed": True,
    }


def cursor_post_write_hook_definition(*, executable: str | Path) -> dict[str, Any]:
    """Compatibility name for the authoritative after-file-edit definition."""

    return cursor_after_file_edit_hook_definition(executable=executable)


def _hooks_path(workspace_root: str | Path) -> Path:
    return Path(workspace_root).expanduser().absolute() / ".cursor" / "hooks.json"


def _hook_entries(value: object, event: str) -> list[object]:
    if not isinstance(value, Mapping):
        return []
    hooks = value.get("hooks")
    if not isinstance(hooks, Mapping):
        return []
    entries = hooks.get(event, [])
    return list(entries) if isinstance(entries, list) else []


def _is_qcoder_completion_command(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    command = str(value.get("command") or "")
    return any(
        marker in command
        for marker in (
            _AFTER_FILE_EDIT_SUBCOMMAND,
            _STOP_RECOVERY_SUBCOMMAND,
            _LEGACY_POST_TOOL_USE_SUBCOMMAND,
        )
    )


def cursor_post_write_hook_status(
    *, workspace_root: str | Path, executable: str | Path
) -> dict[str, Any]:
    """Verify the exact project-local hooks without modifying the workspace."""

    path = _hooks_path(workspace_root)
    expected_edit = cursor_after_file_edit_hook_definition(executable=executable)
    expected_stop = cursor_stop_recovery_hook_definition(executable=executable)
    result = {
        "schema_id": CURSOR_POST_WRITE_HOOK_SCHEMA_ID,
        "schema_version": CURSOR_POST_WRITE_HOOK_SCHEMA_VERSION,
        "transport": CURSOR_POST_WRITE_TRANSPORT,
        "configured": False,
        "exact_runtime_bound": False,
        "project_scope": True,
        "trusted_workspace_required": True,
        "authoritative_hook_event": "afterFileEdit",
        "tool_name_matcher_required": False,
        "stop_recovery_configured": False,
        "post_tool_use_required_for_correctness": False,
        "model_invocation_required": False,
        "shell_tool_invocation_required": False,
        "second_native_approval_required": False,
        "public_context_bridge_tool": False,
    }
    if path.is_symlink() or not path.is_file():
        return result
    try:
        raw = path.read_bytes()
    except OSError:
        return result
    if len(raw) > 65_536:
        return result
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return result
    edit_entries = _hook_entries(value, "afterFileEdit")
    stop_entries = _hook_entries(value, "stop")
    post_entries = _hook_entries(value, "postToolUse")
    exact_edit = [entry for entry in edit_entries if entry == expected_edit]
    exact_stop = [entry for entry in stop_entries if entry == expected_stop]
    stale_qcoder = [
        entry
        for entry in (*edit_entries, *stop_entries, *post_entries)
        if _is_qcoder_completion_command(entry) and entry not in (expected_edit, expected_stop)
    ]
    result["configured"] = len(exact_edit) == 1 and len(exact_stop) == 1 and not stale_qcoder
    result["exact_runtime_bound"] = result["configured"]
    result["stop_recovery_configured"] = len(exact_stop) == 1
    result["legacy_post_tool_use_qcoder_hook_absent"] = not any(
        _is_qcoder_completion_command(entry) for entry in post_entries
    )
    if result["configured"]:
        result["configuration_sha256"] = sha256(canonical_bytes(value)).hexdigest()
    return result


def _validated_hook_list(hooks: dict[str, Any], event: str) -> list[dict[str, Any]]:
    entries = hooks.setdefault(event, [])
    if not isinstance(entries, list) or not all(isinstance(item, dict) for item in entries):
        raise CursorPostWriteHookError(f"cursor_hook_{event}_invalid")
    return entries


def install_cursor_post_write_hook(
    *, workspace_root: str | Path, executable: str | Path | None = None
) -> dict[str, Any]:
    """Install matcher-free edit completion and stop recovery, preserving unrelated hooks."""

    workspace = Path(workspace_root).expanduser().absolute()
    if not workspace.is_dir() or workspace.is_symlink():
        raise CursorPostWriteHookError("cursor_hook_workspace_invalid")
    path = _hooks_path(workspace)
    if path.is_symlink() or path.parent.is_symlink():
        raise CursorPostWriteHookError("cursor_hook_symlink_rejected")
    runtime = executable or sys.executable
    if not isinstance(runtime, (str, Path)) or not str(runtime):
        raise CursorPostWriteHookError("cursor_hook_runtime_missing")
    expected_edit = cursor_after_file_edit_hook_definition(executable=runtime)
    expected_stop = cursor_stop_recovery_hook_definition(executable=runtime)
    value: dict[str, Any] = {"version": 1, "hooks": {}}
    if path.exists():
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise CursorPostWriteHookError("cursor_hook_configuration_unreadable") from exc
        if len(raw) > 65_536:
            raise CursorPostWriteHookError("cursor_hook_configuration_too_large")
        try:
            supplied = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CursorPostWriteHookError("cursor_hook_configuration_invalid") from exc
        if (
            not isinstance(supplied, dict)
            or supplied.get("version") != 1
            or not isinstance(supplied.get("hooks"), dict)
        ):
            raise CursorPostWriteHookError("cursor_hook_configuration_invalid")
        value = deepcopy(supplied)
    hooks = value.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise CursorPostWriteHookError("cursor_hook_configuration_invalid")

    # This is an intentional in-place upgrade of qCoder's own v27 hook only.
    # Entries belonging to other tools are preserved byte-semantically.
    for event in ("postToolUse", "afterFileEdit", "stop"):
        entries = _validated_hook_list(hooks, event)
        entries[:] = [item for item in entries if not _is_qcoder_completion_command(item)]
    hooks["afterFileEdit"].append(expected_edit)
    hooks["stop"].append(expected_stop)

    encoded = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="hooks.", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            Path(temporary).unlink()
        except FileNotFoundError:
            pass
    status = cursor_post_write_hook_status(workspace_root=workspace, executable=runtime)
    if status.get("configured") is not True:
        raise CursorPostWriteHookError("cursor_hook_installation_verification_failed")
    return {
        **status,
        "ok": True,
        "result": "cursor_project_after_file_edit_completion_ready",
        "existing_unrelated_hooks_preserved": True,
        "legacy_qcoder_post_tool_use_hook_removed": True,
        "workspace_trust_must_be_established_before_use": True,
        "credentials_included": False,
        "customer_source_modified": False,
    }


def _event_object(value: object, *, event_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CursorPostWriteHookError("cursor_hook_event_object_required")
    event = dict(value)
    if event.get("hook_event_name") != event_name:
        raise CursorPostWriteHookError("cursor_hook_event_name_invalid")
    for key in ("conversation_id", "generation_id"):
        if not isinstance(event.get(key), str) or not event[key]:
            raise CursorPostWriteHookError("cursor_hook_event_identity_missing")
    return event


def _workspace_matches_event(event: Mapping[str, Any], workspace: Path) -> bool:
    roots = event.get("workspace_roots")
    if not isinstance(roots, list):
        return False
    normalized = {
        str(Path(value).expanduser().absolute()) for value in roots if isinstance(value, str)
    }
    return str(workspace) in normalized


def _event_path(event: Mapping[str, Any], workspace: Path) -> Path | None:
    value = event.get("file_path")
    if not isinstance(value, str) or not value:
        raise CursorPostWriteHookError("cursor_hook_exact_path_missing")
    path = Path(value).expanduser()
    if not path.is_absolute() or ".." in path.parts or path.is_symlink() or not path.is_file():
        raise CursorPostWriteHookError("cursor_hook_exact_path_invalid")
    path = path.absolute()
    try:
        path.resolve(strict=True).relative_to(workspace.resolve(strict=True))
    except (OSError, RuntimeError, ValueError):
        return None
    if ".qcoder" in path.parts or ".cursor" in path.parts:
        return None
    return path


def _pending_source_action(state: Mapping[str, Any]) -> bool:
    coordinator = state.get("coordinator")
    if not isinstance(coordinator, Mapping):
        return False
    semantics = coordinator.get("current_request_semantics")
    return bool(
        coordinator.get("phase") == "generation_ready"
        and coordinator.get("state_status") == "ready"
        and coordinator.get("current_step_status") == "awaiting_native_permission"
        and coordinator.get("current_step_substage") in {None, "source"}
        and isinstance(semantics, Mapping)
        and semantics.get("requested_operation")
        in {"source_generation", "source_and_qasm_generation", "source_and_local_execution"}
        and tuple(semantics.get("current_step_ceiling", {}).get("allowed_artifact_roles", ()))
        == ("source",)
    )


def _is_supported_source_file(path: Path) -> bool:
    try:
        outcome = registration_format_outcome(
            path=path,
            role="source",
            provenance="assistant_operation_receipt",
        )
    except (CurrentLoopError, OSError, ValueError):
        return False
    return outcome.get("automatic_registration_supported") is True


def _event_binding(
    event: Mapping[str, Any], path: Path, state: Mapping[str, Any]
) -> dict[str, Any]:
    raw = path.read_bytes()
    coordinator = state["coordinator"]
    semantics = coordinator["current_request_semantics"]
    return {
        "schema_id": "qcoder.current_loop.native_client_write_event.v2",
        "schema_version": 2,
        "transport": CURSOR_POST_WRITE_TRANSPORT,
        "hook_event_name": "afterFileEdit",
        "semantic_event": "agent_file_edit_completed",
        "tool_name_match_required": False,
        "native_write_completed_before_hook": True,
        "conversation_identity_sha256": _digest_text(str(event["conversation_id"])),
        "generation_identity_sha256": _digest_text(str(event["generation_id"])),
        "exact_path_sha256": _digest_text(str(path)),
        "expected_artifact_sha256": sha256(raw).hexdigest(),
        "expected_artifact_bytes": len(raw),
        "bound_loop_identity_sha256": _digest_text(str(state["loop_ref"])),
        "bound_state_revision": state["state_revision"],
        "current_request_semantics_digest": semantics["semantics_digest"],
        "current_step_ceiling_digest": semantics["current_step_ceiling"]["ceiling_digest"],
        "artifact_role": "source",
        "artifact_cardinality": "exactly_one",
        "source_bytes_returned": False,
        "cursor_account_fields_retained": False,
        "transcript_fields_retained": False,
        "edit_payload_retained": False,
    }


def _event_provenance(event: Mapping[str, Any]) -> str:
    edits = event.get("edits")
    if isinstance(edits, list) and any(
        isinstance(item, Mapping)
        and isinstance(item.get("old_string"), str)
        and bool(item["old_string"])
        for item in edits
    ):
        return "assistant_modified"
    return "assistant_created"


def handle_cursor_after_file_edit_event(
    *, workspace_root: str | Path, event: object
) -> dict[str, Any]:
    """Complete one exact pending source write; unrelated edits are no-ops."""

    workspace = Path(workspace_root).expanduser().absolute()
    parsed = _event_object(event, event_name="afterFileEdit")
    if not _workspace_matches_event(parsed, workspace):
        return {"output": {}, "disposition": "unrelated_workspace_edit_ignored", "ok": True}
    state_path = workspace / ".qcoder" / "current-loop" / "state.json"
    if not state_path.is_file() or state_path.is_symlink():
        return {"output": {}, "disposition": "no_active_qcoder_write", "ok": True}
    coordinator = CurrentLoopCoordinator(
        workspace_root=workspace, runtime_executable=sys.executable
    )
    state = coordinator.store.read()
    if not _pending_source_action(state):
        return {"output": {}, "disposition": "no_pending_qcoder_source_write", "ok": True}
    path = _event_path(parsed, workspace)
    if path is None or not _is_supported_source_file(path):
        return {"output": {}, "disposition": "unrelated_file_edit_ignored", "ok": True}
    binding = _event_binding(parsed, path, state)
    result = coordinator.complete_native_action(
        allowed=True,
        explicit_user_action=True,
        candidates=(
            {
                "role": "source",
                "path": str(path),
                "provenance": _event_provenance(parsed),
                "explicit_external": False,
                "content_digest": binding["expected_artifact_sha256"],
            },
        ),
        native_client_event_binding=binding,
    )
    if result.get("ok") is True:
        return {
            "output": {},
            "disposition": _SUCCESS_DISPOSITION,
            "ok": True,
            "registration_completed": True,
            "second_native_approval_required": False,
            "shell_tool_invocation_required": False,
            "model_feedback_required_for_correctness": False,
            "raw_path_returned": False,
            "raw_source_returned": False,
        }
    return {
        "output": {},
        "disposition": "registration_recovery_required",
        "ok": False,
        "registration_completed": False,
        "safe_error_category": str(result.get("category") or "exact_registration_not_completed"),
        "state_truth_retained": True,
        "raw_path_returned": False,
        "raw_source_returned": False,
    }


def handle_cursor_post_write_event(*, workspace_root: str | Path, event: object) -> dict[str, Any]:
    """Compatibility adapter; only the semantic afterFileEdit event is accepted."""

    return handle_cursor_after_file_edit_event(workspace_root=workspace_root, event=event)


def handle_cursor_stop_event(*, workspace_root: str | Path, event: object) -> dict[str, Any]:
    """Return one recovery follow-up only when the active source step is incomplete."""

    workspace = Path(workspace_root).expanduser().absolute()
    parsed = _event_object(event, event_name="stop")
    if not _workspace_matches_event(parsed, workspace):
        return {"output": {}, "disposition": "unrelated_workspace_stop_ignored", "ok": True}
    if parsed.get("status") != "completed":
        return {"output": {}, "disposition": "noncompleted_stop_observed", "ok": True}
    loop_count = parsed.get("loop_count", 0)
    if not isinstance(loop_count, int) or loop_count < 0:
        raise CursorPostWriteHookError("cursor_stop_loop_count_invalid")
    state_path = workspace / ".qcoder" / "current-loop" / "state.json"
    if not state_path.is_file() or state_path.is_symlink():
        return {"output": {}, "disposition": "no_active_qcoder_request", "ok": True}
    state = CurrentLoopCoordinator(
        workspace_root=workspace, runtime_executable=sys.executable
    ).store.read()
    coordinator = state.get("coordinator", {})
    if coordinator.get("current_step_status") == "complete_resumable":
        return {"output": {}, "disposition": "registration_already_complete", "ok": True}
    pending = _pending_source_action(state) or bool(
        coordinator.get("phase") == "awaiting_local_artifacts"
        and coordinator.get("current_step_status") == "awaiting_artifact_registration"
        and isinstance(coordinator.get("current_step_operation_receipt_id"), str)
        and isinstance(coordinator.get("current_request_semantics"), Mapping)
        and coordinator["current_request_semantics"].get("requested_operation")
        in {"source_generation", "source_and_qasm_generation", "source_and_local_execution"}
        and coordinator.get("current_step_substage") in {None, "source"}
    )
    if not pending or loop_count > 0:
        return {"output": {}, "disposition": "no_recovery_followup_required", "ok": True}
    return {
        "output": {"followup_message": _RECOVERY_MESSAGE},
        "disposition": "bounded_registration_recovery_followup",
        "ok": True,
        "registration_incomplete": True,
        "authority_broadened": False,
        "raw_path_returned": False,
        "raw_source_returned": False,
    }


def _decode_hook_input(raw_event: bytes | bytearray | memoryview | None) -> object:
    """Decode bounded hook stdin and classify absent payload without a Python traceback."""

    if raw_event is None:
        raise CursorPostWriteHookError("cursor_hook_stdin_payload_absent")
    try:
        bounded = bytes(raw_event)
    except TypeError as exc:
        raise CursorPostWriteHookError("cursor_hook_stdin_payload_not_bytes") from exc
    if not bounded:
        raise CursorPostWriteHookError("cursor_hook_stdin_payload_empty")
    if len(bounded) > CURSOR_POST_WRITE_HOOK_MAX_INPUT_BYTES:
        raise CursorPostWriteHookError("cursor_hook_stdin_payload_too_large")
    try:
        return json.loads(bounded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CursorPostWriteHookError("cursor_hook_stdin_payload_invalid") from exc


def _run_hook(
    *, workspace_root: str | Path, raw_event: bytes | bytearray | memoryview | None, stop: bool
) -> int:
    try:
        event = _decode_hook_input(raw_event)
        result = (
            handle_cursor_stop_event(workspace_root=workspace_root, event=event)
            if stop
            else handle_cursor_after_file_edit_event(workspace_root=workspace_root, event=event)
        )
    except (
        CursorPostWriteHookError,
        CurrentLoopError,
        OSError,
        TypeError,
        ValueError,
    ):
        return 2
    sys.stdout.write(json.dumps(result["output"], sort_keys=True) + "\n")
    return 0 if result.get("ok") is True else 2


def run_cursor_after_file_edit_hook(
    *, workspace_root: str | Path, raw_event: bytes | bytearray | memoryview | None
) -> int:
    return _run_hook(workspace_root=workspace_root, raw_event=raw_event, stop=False)


def run_cursor_stop_recovery_hook(
    *, workspace_root: str | Path, raw_event: bytes | bytearray | memoryview | None
) -> int:
    return _run_hook(workspace_root=workspace_root, raw_event=raw_event, stop=True)


def run_cursor_post_write_hook(
    *, workspace_root: str | Path, raw_event: bytes | bytearray | memoryview | None
) -> int:
    """Compatibility name for the authoritative afterFileEdit CLI adapter."""

    return run_cursor_after_file_edit_hook(workspace_root=workspace_root, raw_event=raw_event)


__all__ = [
    "CURSOR_POST_WRITE_HOOK_SCHEMA_ID",
    "CURSOR_POST_WRITE_TRANSPORT",
    "CursorPostWriteHookError",
    "cursor_after_file_edit_hook_definition",
    "cursor_post_write_hook_definition",
    "cursor_post_write_hook_status",
    "cursor_stop_recovery_hook_definition",
    "handle_cursor_after_file_edit_event",
    "handle_cursor_post_write_event",
    "handle_cursor_stop_event",
    "install_cursor_post_write_hook",
    "run_cursor_after_file_edit_hook",
    "run_cursor_post_write_hook",
    "run_cursor_stop_recovery_hook",
]
