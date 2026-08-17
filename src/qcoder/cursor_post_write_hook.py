"""Cursor-native post-write completion for the active qCoder source action.

The hook is a configured client lifecycle seam, not a model tool. It consumes a
successful native ``Write`` event, registers only that exact path through the
existing Current Loop receipt boundary, and returns bounded context to the same
agent turn. Raw source, paths, receipts, and Cursor account metadata are never
returned or persisted by this adapter.
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

CURSOR_POST_WRITE_HOOK_SCHEMA_ID = "qcoder.current_loop.cursor_post_write_hook.v1"
CURSOR_POST_WRITE_HOOK_SCHEMA_VERSION = 1
CURSOR_POST_WRITE_TRANSPORT = "cursor_project_post_tool_use_hook"
CURSOR_POST_WRITE_HOOK_MAX_INPUT_BYTES = 1_048_576

_HOOK_SUBCOMMAND = "cursor-post-write-hook"
_INSTALL_SUBCOMMAND = "install-cursor-post-write-hook"
_SUCCESS_CONTEXT = (
    "qCoder completed the required exact registration for the successful native source write. "
    "Give the concise truthful final now and stop. Do not narrate registration, expose a command, "
    "export QASM, execute code, or close the resumable loop."
)


class CursorPostWriteHookError(ValueError):
    """One bounded Cursor hook configuration or event error."""

    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


def _digest_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _hook_command(executable: str | Path) -> str:
    argv = [
        str(Path(executable).expanduser().absolute()),
        "-m",
        "qcoder",
        "current-loop",
        _HOOK_SUBCOMMAND,
    ]
    return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


def cursor_post_write_hook_definition(*, executable: str | Path) -> dict[str, Any]:
    """Return the exact project hook entry for the configured qCoder runtime."""

    return {
        "command": _hook_command(executable),
        "matcher": "Write",
        "timeout": 30,
        "failClosed": True,
    }


def _hooks_path(workspace_root: str | Path) -> Path:
    return Path(workspace_root).expanduser().absolute() / ".cursor" / "hooks.json"


def cursor_post_write_hook_status(
    *, workspace_root: str | Path, executable: str | Path
) -> dict[str, Any]:
    """Verify the exact project-local hook without modifying the workspace."""

    path = _hooks_path(workspace_root)
    expected = cursor_post_write_hook_definition(executable=executable)
    result = {
        "schema_id": CURSOR_POST_WRITE_HOOK_SCHEMA_ID,
        "schema_version": CURSOR_POST_WRITE_HOOK_SCHEMA_VERSION,
        "transport": CURSOR_POST_WRITE_TRANSPORT,
        "configured": False,
        "exact_runtime_bound": False,
        "project_scope": True,
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
    entries = value.get("hooks", {}).get("postToolUse", []) if isinstance(value, dict) else []
    if not isinstance(entries, list):
        return result
    matching = [entry for entry in entries if isinstance(entry, dict) and entry == expected]
    result["configured"] = len(matching) == 1
    result["exact_runtime_bound"] = len(matching) == 1
    if result["configured"]:
        result["configuration_sha256"] = sha256(canonical_bytes(value)).hexdigest()
    return result


def install_cursor_post_write_hook(
    *, workspace_root: str | Path, executable: str | Path | None = None
) -> dict[str, Any]:
    """Install one exact project hook while preserving unrelated hook entries."""

    workspace = Path(workspace_root).expanduser().absolute()
    if not workspace.is_dir() or workspace.is_symlink():
        raise CursorPostWriteHookError("cursor_hook_workspace_invalid")
    path = _hooks_path(workspace)
    if path.is_symlink() or path.parent.is_symlink():
        raise CursorPostWriteHookError("cursor_hook_symlink_rejected")
    expected = cursor_post_write_hook_definition(executable=executable or sys.executable)
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
    entries = hooks.setdefault("postToolUse", [])
    if not isinstance(entries, list) or not all(isinstance(item, dict) for item in entries):
        raise CursorPostWriteHookError("cursor_hook_post_tool_use_invalid")
    stale = [
        item
        for item in entries
        if _HOOK_SUBCOMMAND in str(item.get("command", "")) and item != expected
    ]
    if stale:
        raise CursorPostWriteHookError("cursor_hook_stale_runtime_binding")
    if expected not in entries:
        entries.append(expected)
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
    status = cursor_post_write_hook_status(
        workspace_root=workspace,
        executable=executable or sys.executable,
    )
    if status.get("configured") is not True:
        raise CursorPostWriteHookError("cursor_hook_installation_verification_failed")
    return {
        **status,
        "ok": True,
        "result": "cursor_project_post_write_hook_ready",
        "existing_unrelated_hooks_preserved": True,
        "credentials_included": False,
        "customer_source_modified": False,
    }


def _event_object(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CursorPostWriteHookError("cursor_hook_event_object_required")
    event = dict(value)
    if event.get("hook_event_name") != "postToolUse" or event.get("tool_name") != "Write":
        raise CursorPostWriteHookError("cursor_hook_event_not_successful_native_write")
    for key in ("conversation_id", "generation_id", "tool_use_id"):
        if not isinstance(event.get(key), str) or not event[key]:
            raise CursorPostWriteHookError("cursor_hook_event_identity_missing")
    return event


def _tool_input(event: Mapping[str, Any]) -> dict[str, Any]:
    supplied = event.get("tool_input")
    if isinstance(supplied, str):
        try:
            supplied = json.loads(supplied)
        except json.JSONDecodeError as exc:
            raise CursorPostWriteHookError("cursor_hook_tool_input_invalid") from exc
    if not isinstance(supplied, Mapping):
        raise CursorPostWriteHookError("cursor_hook_tool_input_invalid")
    return dict(supplied)


def _exact_event_path(event: Mapping[str, Any], workspace: Path) -> Path:
    supplied = _tool_input(event)
    values = [supplied.get(key) for key in ("file_path", "path") if supplied.get(key) is not None]
    if len(values) != 1 or not isinstance(values[0], str) or not values[0]:
        raise CursorPostWriteHookError("cursor_hook_exact_path_missing")
    path = Path(values[0]).expanduser()
    if not path.is_absolute() or ".." in path.parts or path.is_symlink() or not path.is_file():
        raise CursorPostWriteHookError("cursor_hook_exact_path_invalid")
    path = path.absolute()
    try:
        path.resolve(strict=True).relative_to(workspace.resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise CursorPostWriteHookError("cursor_hook_exact_path_outside_workspace") from exc
    if ".qcoder" in path.parts or ".cursor" in path.parts:
        raise CursorPostWriteHookError("cursor_hook_internal_path_rejected")
    return path


def _event_binding(
    event: Mapping[str, Any], path: Path, state: Mapping[str, Any]
) -> dict[str, Any]:
    raw = path.read_bytes()
    coordinator = state["coordinator"]
    semantics = coordinator["current_request_semantics"]
    return {
        "schema_id": "qcoder.current_loop.native_client_write_event.v1",
        "schema_version": 1,
        "transport": CURSOR_POST_WRITE_TRANSPORT,
        "hook_event_name": "postToolUse",
        "tool_category": "native_write",
        "tool_succeeded_before_hook": True,
        "conversation_identity_sha256": _digest_text(str(event["conversation_id"])),
        "generation_identity_sha256": _digest_text(str(event["generation_id"])),
        "tool_use_identity_sha256": _digest_text(str(event["tool_use_id"])),
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
    }


def handle_cursor_post_write_event(*, workspace_root: str | Path, event: object) -> dict[str, Any]:
    """Complete one exact pending source write and return safe same-turn context."""

    workspace = Path(workspace_root).expanduser().absolute()
    parsed = _event_object(event)
    event_cwd = parsed.get("cwd")
    if isinstance(event_cwd, str) and Path(event_cwd).expanduser().absolute() != workspace:
        raise CursorPostWriteHookError("cursor_hook_workspace_mismatch")
    roots = parsed.get("workspace_roots")
    if isinstance(roots, list) and str(workspace) not in {
        str(Path(value).expanduser().absolute()) for value in roots if isinstance(value, str)
    }:
        raise CursorPostWriteHookError("cursor_hook_workspace_mismatch")
    state_path = workspace / ".qcoder" / "current-loop" / "state.json"
    if not state_path.is_file() or state_path.is_symlink():
        return {"output": {}, "disposition": "no_active_qcoder_write", "ok": True}
    coordinator = CurrentLoopCoordinator(
        workspace_root=workspace, runtime_executable=sys.executable
    )
    state = coordinator.store.read()
    coordinator_state = state.get("coordinator", {})
    semantics = coordinator_state.get("current_request_semantics", {})
    if (
        coordinator_state.get("phase") != "generation_ready"
        or coordinator_state.get("state_status") != "ready"
        or coordinator_state.get("current_step_substage") not in {None, "source"}
        or semantics.get("requested_operation")
        not in {"source_generation", "source_and_qasm_generation", "source_and_local_execution"}
    ):
        return {"output": {}, "disposition": "no_pending_qcoder_source_write", "ok": True}
    path = _exact_event_path(parsed, workspace)
    binding = _event_binding(parsed, path, state)
    result = coordinator.complete_native_action(
        allowed=True,
        explicit_user_action=True,
        candidates=(
            {
                "role": "source",
                "path": str(path),
                "provenance": "assistant_created",
                "explicit_external": False,
                "content_digest": binding["expected_artifact_sha256"],
            },
        ),
        native_client_event_binding=binding,
    )
    if result.get("ok") is True:
        return {
            "output": {"additional_context": _SUCCESS_CONTEXT},
            "disposition": "exact_registration_completed",
            "ok": True,
            "registration_completed": True,
            "second_native_approval_required": False,
            "shell_tool_invocation_required": False,
            "raw_path_returned": False,
            "raw_source_returned": False,
        }
    category = str(result.get("category") or "exact_registration_not_completed")
    return {
        "output": {
            "additional_context": (
                "qCoder did not complete exact registration after the native source write "
                f"(safe category: {category}). Do not give the final success response, do not "
                "broaden authority, and retain the current step for bounded recovery."
            )
        },
        "disposition": "registration_recovery_required",
        "ok": False,
        "registration_completed": False,
        "safe_error_category": category,
        "state_truth_retained": True,
        "raw_path_returned": False,
        "raw_source_returned": False,
    }


def run_cursor_post_write_hook(*, workspace_root: str | Path, raw_event: bytes) -> int:
    """CLI adapter: emit only Cursor's supported postToolUse output shape."""

    if len(raw_event) > CURSOR_POST_WRITE_HOOK_MAX_INPUT_BYTES:
        return 2
    try:
        event = json.loads(raw_event.decode("utf-8"))
        result = handle_cursor_post_write_event(workspace_root=workspace_root, event=event)
    except (
        CursorPostWriteHookError,
        CurrentLoopError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        return 2
    sys.stdout.write(json.dumps(result["output"], sort_keys=True) + "\n")
    return 0


__all__ = [
    "CURSOR_POST_WRITE_HOOK_SCHEMA_ID",
    "CURSOR_POST_WRITE_TRANSPORT",
    "CursorPostWriteHookError",
    "cursor_post_write_hook_definition",
    "cursor_post_write_hook_status",
    "handle_cursor_post_write_event",
    "install_cursor_post_write_hook",
    "run_cursor_post_write_hook",
]
