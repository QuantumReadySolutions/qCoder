"""Cursor-native integration for structured activation and exact completion.

Two matcher-free project events, ``afterFileEdit`` and ``postToolUse``, feed one
idempotent bounded-action completion broker. Neither event name nor a generic
tool name carries product authority or proves native permission. qCoder validates
structured completion evidence, the absolute path, current bytes, active loop,
ceiling, and one-use expectation.

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
from qcoder.current_loop_binding_mcp import BINDING_MCP_SERVER_NAME
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.current_loop_evidence_processing import registration_format_outcome

CURSOR_POST_WRITE_HOOK_SCHEMA_ID = "qcoder.current_loop.cursor_native_edit_broker.v4"
CURSOR_POST_WRITE_HOOK_SCHEMA_VERSION = 4
CURSOR_POST_WRITE_TRANSPORT = "cursor_project_redundant_native_edit_hooks"
CURSOR_POST_WRITE_HOOK_MAX_INPUT_BYTES = 1_048_576

_AFTER_FILE_EDIT_SUBCOMMAND = "cursor-after-file-edit-hook"
_POST_TOOL_USE_SUBCOMMAND = "cursor-post-tool-use-hook"
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
    """Return one matcher-free semantic Agent file-edit signal."""

    return {
        "command": _hook_command(executable, _AFTER_FILE_EDIT_SUBCOMMAND),
        "timeout": 30,
        "failClosed": True,
    }


def cursor_post_tool_use_hook_definition(*, executable: str | Path) -> dict[str, Any]:
    """Return the unfiltered redundant generic-tool signal."""

    return {
        "command": _hook_command(executable, _POST_TOOL_USE_SUBCOMMAND),
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
    """Compatibility name for the semantic after-file-edit definition."""

    return cursor_after_file_edit_hook_definition(executable=executable)


def _hooks_path(workspace_root: str | Path) -> Path:
    return Path(workspace_root).expanduser().absolute() / ".cursor" / "hooks.json"


def _mcp_path(workspace_root: str | Path) -> Path:
    return Path(workspace_root).expanduser().absolute() / ".cursor" / "mcp.json"


def _recovery_marker_path(workspace_root: str | Path) -> Path:
    return (
        Path(workspace_root).expanduser().absolute()
        / ".qcoder"
        / "current-loop"
        / "native-edit-recovery.json"
    )


def _record_recovery_marker(
    *, workspace: Path, event: Mapping[str, Any], path: Path, state: Mapping[str, Any]
) -> None:
    marker = _recovery_marker_path(workspace)
    if marker.is_symlink() or marker.parent.is_symlink():
        return
    payload = {
        "schema_id": "qcoder.current_loop.native_edit_recovery_marker.v1",
        "hook_event_name": event.get("hook_event_name"),
        "conversation_identity_sha256": _digest_text(str(event.get("conversation_id"))),
        "generation_identity_sha256": _digest_text(str(event.get("generation_id"))),
        "exact_path_sha256": _digest_text(str(path)),
        "observed_state_revision": state.get("state_revision"),
        "raw_path_retained": False,
        "raw_source_retained": False,
    }
    marker.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix="native-edit.", suffix=".json", dir=marker.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_bytes(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, marker)
    finally:
        try:
            Path(temporary).unlink()
        except FileNotFoundError:
            pass


def _clear_recovery_marker(workspace: Path) -> None:
    marker = _recovery_marker_path(workspace)
    if marker.is_symlink():
        return
    try:
        marker.unlink()
    except FileNotFoundError:
        pass


def _recovery_marker_present(workspace: Path) -> bool:
    marker = _recovery_marker_path(workspace)
    if marker.is_symlink() or not marker.is_file():
        return False
    try:
        value = json.loads(marker.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return bool(
        isinstance(value, Mapping)
        and value.get("schema_id") == "qcoder.current_loop.native_edit_recovery_marker.v1"
        and value.get("raw_path_retained") is False
        and value.get("raw_source_retained") is False
    )


def cursor_binding_mcp_server_definition(
    *,
    executable: str | Path,
    workspace_root: str | Path,
    connection_state_root: str | Path | None = None,
    connection_generation: str | None = None,
) -> dict[str, Any]:
    """Return the project-local private structured-activation MCP server."""

    args = [
        "-m",
        "qcoder",
        "current-loop",
        "--workspace",
        str(Path(workspace_root).expanduser().absolute()),
    ]
    if connection_state_root is not None and connection_generation is not None:
        args.extend(
            [
                "--connection-state-root",
                str(Path(connection_state_root).expanduser().absolute()),
                "--connection-generation",
                connection_generation,
            ]
        )
    args.append("serve-binding-mcp")
    return {
        "command": str(Path(executable).expanduser().absolute()),
        "args": args,
    }


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
            _POST_TOOL_USE_SUBCOMMAND,
            _STOP_RECOVERY_SUBCOMMAND,
            _LEGACY_POST_TOOL_USE_SUBCOMMAND,
        )
    )


def cursor_post_write_hook_status(
    *,
    workspace_root: str | Path,
    executable: str | Path,
    connection_state_root: str | Path | None = None,
    connection_generation: str | None = None,
) -> dict[str, Any]:
    """Verify the exact project-local hooks without modifying the workspace."""

    path = _hooks_path(workspace_root)
    expected_edit = cursor_after_file_edit_hook_definition(executable=executable)
    expected_post = cursor_post_tool_use_hook_definition(executable=executable)
    expected_stop = cursor_stop_recovery_hook_definition(executable=executable)
    expected_binding = cursor_binding_mcp_server_definition(
        executable=executable,
        workspace_root=workspace_root,
        connection_state_root=connection_state_root,
        connection_generation=connection_generation,
    )
    result = {
        "schema_id": CURSOR_POST_WRITE_HOOK_SCHEMA_ID,
        "schema_version": CURSOR_POST_WRITE_HOOK_SCHEMA_VERSION,
        "transport": CURSOR_POST_WRITE_TRANSPORT,
        "configured": False,
        "exact_runtime_bound": False,
        "project_scope": True,
        "trusted_workspace_required": True,
        "authoritative_hook_events": ["afterFileEdit", "postToolUse"],
        "first_valid_event_wins": True,
        "single_event_dependency": False,
        "tool_name_matcher_required": False,
        "stop_recovery_configured": False,
        "unfiltered_post_tool_use_configured": False,
        "structured_activation_configured": False,
        "structured_activation_server": BINDING_MCP_SERVER_NAME,
        "model_invocation_required": False,
        "shell_tool_invocation_required": False,
        "second_native_approval_required": False,
        "native_client_permission_owner": "native_client",
        "native_client_permission_granted_by_qcoder": False,
        "native_client_permission_observed_by_qcoder": False,
        "user_approval_click_inferred": False,
        "qcoder_bounded_action_expectation_required": True,
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
    exact_post = [entry for entry in post_entries if entry == expected_post]
    exact_stop = [entry for entry in stop_entries if entry == expected_stop]
    stale_qcoder = [
        entry
        for entry in (*edit_entries, *stop_entries, *post_entries)
        if _is_qcoder_completion_command(entry)
        and entry not in (expected_edit, expected_post, expected_stop)
    ]
    mcp_path = _mcp_path(workspace_root)
    binding_exact = False
    if mcp_path.is_file() and not mcp_path.is_symlink():
        try:
            mcp_value = json.loads(mcp_path.read_bytes().decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            mcp_value = None
        servers = mcp_value.get("mcpServers") if isinstance(mcp_value, Mapping) else None
        binding_exact = bool(
            isinstance(servers, Mapping)
            and servers.get(BINDING_MCP_SERVER_NAME) == expected_binding
        )
    result["configured"] = bool(
        len(exact_edit) == 1
        and len(exact_post) == 1
        and len(exact_stop) == 1
        and not stale_qcoder
        and binding_exact
    )
    result["exact_runtime_bound"] = result["configured"]
    result["stop_recovery_configured"] = len(exact_stop) == 1
    result["unfiltered_post_tool_use_configured"] = len(exact_post) == 1
    result["structured_activation_configured"] = binding_exact
    result["legacy_tool_name_filtered_qcoder_hook_absent"] = not any(
        _is_qcoder_completion_command(entry) and entry != expected_post for entry in post_entries
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
    *,
    workspace_root: str | Path,
    executable: str | Path | None = None,
    connection_state_root: str | Path | None = None,
    connection_generation: str | None = None,
) -> dict[str, Any]:
    """Install structured activation, redundant edit signals, and bounded recovery."""

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
    expected_post = cursor_post_tool_use_hook_definition(executable=runtime)
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
    hooks["postToolUse"].append(expected_post)
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

    mcp_path = _mcp_path(workspace)
    if mcp_path.is_symlink() or mcp_path.parent.is_symlink():
        raise CursorPostWriteHookError("cursor_mcp_symlink_rejected")
    mcp_value: dict[str, Any] = {"mcpServers": {}}
    if mcp_path.exists():
        try:
            raw_mcp = mcp_path.read_bytes()
        except OSError as exc:
            raise CursorPostWriteHookError("cursor_mcp_configuration_unreadable") from exc
        if len(raw_mcp) > 65_536:
            raise CursorPostWriteHookError("cursor_mcp_configuration_too_large")
        try:
            supplied_mcp = json.loads(raw_mcp.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CursorPostWriteHookError("cursor_mcp_configuration_invalid") from exc
        if not isinstance(supplied_mcp, dict) or not isinstance(
            supplied_mcp.get("mcpServers"), dict
        ):
            raise CursorPostWriteHookError("cursor_mcp_configuration_invalid")
        mcp_value = deepcopy(supplied_mcp)
    mcp_servers = mcp_value["mcpServers"]
    expected_binding = cursor_binding_mcp_server_definition(
        executable=runtime,
        workspace_root=workspace,
        connection_state_root=connection_state_root,
        connection_generation=connection_generation,
    )
    existing_binding = mcp_servers.get(BINDING_MCP_SERVER_NAME)
    predecessor_binding = cursor_binding_mcp_server_definition(
        executable=runtime,
        workspace_root=workspace,
    )
    if existing_binding is not None and existing_binding not in (
        expected_binding,
        predecessor_binding,
    ):
        raise CursorPostWriteHookError("cursor_binding_mcp_name_conflict")
    mcp_servers[BINDING_MCP_SERVER_NAME] = expected_binding
    mcp_encoded = (json.dumps(mcp_value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    mcp_path.parent.mkdir(parents=True, exist_ok=True)
    mcp_descriptor, mcp_temporary = tempfile.mkstemp(
        prefix="mcp.", suffix=".json", dir=mcp_path.parent
    )
    try:
        with os.fdopen(mcp_descriptor, "wb") as handle:
            handle.write(mcp_encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(mcp_temporary, mcp_path)
    finally:
        try:
            Path(mcp_temporary).unlink()
        except FileNotFoundError:
            pass
    status = cursor_post_write_hook_status(
        workspace_root=workspace,
        executable=runtime,
        connection_state_root=connection_state_root,
        connection_generation=connection_generation,
    )
    if status.get("configured") is not True:
        raise CursorPostWriteHookError("cursor_hook_installation_verification_failed")
    return {
        **status,
        "ok": True,
        "result": "cursor_project_structured_activation_and_redundant_completion_ready",
        "existing_unrelated_hooks_preserved": True,
        "existing_unrelated_mcp_servers_preserved": True,
        "legacy_qcoder_tool_name_filtered_hook_removed": True,
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


def _validated_event_path(value: object, workspace: Path) -> Path | None:
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


def _after_file_edit_path(event: Mapping[str, Any], workspace: Path) -> Path | None:
    return _validated_event_path(event.get("file_path"), workspace)


def _mapping_path_values(value: Mapping[str, Any]) -> list[str]:
    return [
        str(value[key])
        for key in ("file_path", "path", "target_file", "target_path")
        if isinstance(value.get(key), str) and value[key]
    ]


def _structured_tool_output(event: Mapping[str, Any]) -> Mapping[str, Any] | None:
    value = event.get("tool_output")
    if isinstance(value, Mapping):
        return value
    if not isinstance(value, str) or len(value.encode("utf-8")) > 262_144:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, Mapping) else None


def _post_tool_use_path(
    event: Mapping[str, Any], workspace: Path
) -> tuple[Path | None, str | None]:
    """Return a path only when structured fields prove a successful mutation.

    No tool-name value participates. A path-only tool event is insufficient;
    it could be a read. Exact full-content evidence must match current bytes,
    or structured edit/write-success evidence must be present.
    """

    tool_input = event.get("tool_input")
    if not isinstance(tool_input, Mapping):
        return None, None
    output = _structured_tool_output(event)
    values = _mapping_path_values(tool_input)
    if isinstance(output, Mapping):
        values.extend(_mapping_path_values(output))
    normalized: dict[str, Path] = {}
    for value in values:
        try:
            candidate = _validated_event_path(value, workspace)
        except CursorPostWriteHookError:
            continue
        if candidate is not None:
            normalized[str(candidate)] = candidate
    if not normalized:
        return None, None
    if len(normalized) != 1:
        raise CursorPostWriteHookError("cursor_post_tool_use_path_ambiguous")
    path = next(iter(normalized.values()))
    raw = path.read_bytes()

    content_values = [
        tool_input[key]
        for key in ("content", "contents", "new_content", "code")
        if isinstance(tool_input.get(key), str)
    ]
    if content_values:
        if not any(value.encode("utf-8") == raw for value in content_values):
            raise CursorPostWriteHookError("cursor_post_tool_use_content_mismatch")
        return path, "assistant_created"

    edits = tool_input.get("edits")
    structured_edits = (
        isinstance(edits, list) and bool(edits) and all(isinstance(item, Mapping) for item in edits)
    )
    output_write_success = bool(
        isinstance(output, Mapping)
        and (
            output.get("written") is True
            or output.get("edit_applied") is True
            or output.get("file_updated") is True
            or (
                output.get("success") is True
                and isinstance(output.get("bytes_written"), int)
                and output["bytes_written"] == len(raw)
            )
        )
    )
    if not structured_edits and not output_write_success:
        return None, None
    return path, "assistant_modified" if structured_edits else "assistant_created"


def _pending_source_action(state: Mapping[str, Any]) -> bool:
    coordinator = state.get("coordinator")
    if not isinstance(coordinator, Mapping):
        return False
    semantics = coordinator.get("current_request_semantics")
    expectation_id = coordinator.get("current_step_bounded_action_expectation_id")
    expectation = (
        state.get("operation_receipts", {}).get(expectation_id)
        if isinstance(expectation_id, str)
        else None
    )
    authority_binding = (
        expectation.get("authority_binding") if isinstance(expectation, Mapping) else None
    )
    return bool(
        coordinator.get("phase") == "generation_ready"
        and coordinator.get("state_status") == "ready"
        and coordinator.get("current_step_status") == "awaiting_external_client_action"
        and coordinator.get("current_step_substage") in {None, "source", "qasm"}
        and isinstance(expectation_id, str)
        and isinstance(coordinator.get("current_step_bounded_action_expectation_digest"), str)
        and isinstance(semantics, Mapping)
        and semantics.get("requested_operation")
        in {
            "source_generation",
            "source_and_qasm_generation",
            "source_and_local_execution",
            "qasm_export",
        }
        and isinstance(authority_binding, Mapping)
        and authority_binding.get("authorized_artifact_role") in {"source", "circuit_qasm"}
        and authority_binding.get("authorized_artifact_cardinality") == "exactly_one"
    )


def _is_supported_file(path: Path, *, role: str) -> bool:
    try:
        outcome = registration_format_outcome(
            path=path,
            role=role,
            provenance="assistant_operation_receipt",
        )
    except (CurrentLoopError, OSError, ValueError):
        return False
    return outcome.get("automatic_registration_supported") is True


def _event_binding(
    event: Mapping[str, Any], path: Path, state: Mapping[str, Any], *, event_name: str
) -> dict[str, Any]:
    raw = path.read_bytes()
    coordinator = state["coordinator"]
    semantics = coordinator["current_request_semantics"]
    expectation = state["operation_receipts"][
        coordinator["current_step_bounded_action_expectation_id"]
    ]
    artifact_role = expectation["authority_binding"]["authorized_artifact_role"]
    return {
        "schema_id": "qcoder.current_loop.native_action_completion_handoff.v1",
        "schema_version": 1,
        "transport": "client_hook_adapter",
        "transport_event": event_name,
        "semantic_event": "native_file_edit_completed",
        "tool_name_match_required": False,
        "native_write_completed_before_handoff": True,
        "bounded_action_expectation_id": coordinator["current_step_bounded_action_expectation_id"],
        "bounded_action_expectation_digest": coordinator[
            "current_step_bounded_action_expectation_digest"
        ],
        "native_client_permission_owned_by_client": True,
        "native_client_permission_granted_by_qcoder": False,
        "native_client_permission_telemetry_required": False,
        "user_approval_click_inferred": False,
        "client_event_identity_sha256": _digest_text(
            f"{event_name}:{event['conversation_id']}:{event['generation_id']}"
        ),
        "exact_path_sha256": _digest_text(str(path)),
        "expected_artifact_sha256": sha256(raw).hexdigest(),
        "expected_artifact_bytes": len(raw),
        "bound_loop_identity_sha256": _digest_text(str(state["loop_ref"])),
        "bound_workspace_identity_sha256": _digest_text(str(state["workspace_root"])),
        "bound_state_revision": state["state_revision"],
        "current_request_identity_sha256": semantics["original_message_utf8_sha256"],
        "current_request_semantics_digest": semantics["semantics_digest"],
        "current_step_ceiling_digest": semantics["current_step_ceiling"]["ceiling_digest"],
        "artifact_role": artifact_role,
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


def handle_cursor_native_edit_event(
    *, workspace_root: str | Path, event: object, event_name: str
) -> dict[str, Any]:
    """Complete one exact pending source write from either native event signal."""

    workspace = Path(workspace_root).expanduser().absolute()
    if event_name not in {"afterFileEdit", "postToolUse"}:
        raise CursorPostWriteHookError("cursor_hook_event_name_invalid")
    parsed = _event_object(event, event_name=event_name)
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
    if event_name == "afterFileEdit":
        path = _after_file_edit_path(parsed, workspace)
        provenance = _event_provenance(parsed)
    else:
        path, provenance = _post_tool_use_path(parsed, workspace)
    expectation_id = state["coordinator"]["current_step_bounded_action_expectation_id"]
    role = state["operation_receipts"][expectation_id]["authority_binding"][
        "authorized_artifact_role"
    ]
    if path is None or not _is_supported_file(path, role=role):
        return {"output": {}, "disposition": "unrelated_native_event_ignored", "ok": True}
    result = coordinator.complete_current_step(
        current_action_handle=expectation_id,
        artifact_path=str(path),
        transport="client_hook_adapter",
        transport_event=event_name,
        artifact_disposition=provenance,
        client_event_identity_sha256=_digest_text(
            f"{event_name}:{parsed['conversation_id']}:{parsed['generation_id']}"
        ),
    )
    if result.get("ok") is True:
        _clear_recovery_marker(workspace)
        return {
            "output": {},
            "disposition": _SUCCESS_DISPOSITION,
            "ok": True,
            "registration_completed": True,
            "second_native_approval_required": False,
            "native_client_permission_owned_by_client": True,
            "native_client_permission_granted_by_qcoder": False,
            "user_approval_click_inferred": False,
            "shell_tool_invocation_required": False,
            "model_feedback_required_for_correctness": False,
            "raw_path_returned": False,
            "raw_source_returned": False,
        }
    current = coordinator.store.read()
    current_coordinator = current.get("coordinator", {})
    if current_coordinator.get(
        "current_step_status"
    ) == "complete_resumable" and not _pending_source_action(current):
        _clear_recovery_marker(workspace)
        return {
            "output": {},
            "disposition": "equivalent_native_event_already_completed",
            "ok": True,
            "registration_completed": True,
            "duplicate_delivery_noop": True,
        }
    _record_recovery_marker(workspace=workspace, event=parsed, path=path, state=current)
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


def handle_cursor_after_file_edit_event(
    *, workspace_root: str | Path, event: object
) -> dict[str, Any]:
    return handle_cursor_native_edit_event(
        workspace_root=workspace_root, event=event, event_name="afterFileEdit"
    )


def handle_cursor_post_tool_use_event(
    *, workspace_root: str | Path, event: object
) -> dict[str, Any]:
    return handle_cursor_native_edit_event(
        workspace_root=workspace_root, event=event, event_name="postToolUse"
    )


def handle_cursor_post_write_event(*, workspace_root: str | Path, event: object) -> dict[str, Any]:
    """Compatibility adapter for the afterFileEdit event."""

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
    if not pending or not _recovery_marker_present(workspace) or loop_count > 0:
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
    *,
    workspace_root: str | Path,
    raw_event: bytes | bytearray | memoryview | None,
    event_name: str,
) -> int:
    try:
        event = _decode_hook_input(raw_event)
        if event_name == "stop":
            result = handle_cursor_stop_event(workspace_root=workspace_root, event=event)
        else:
            result = handle_cursor_native_edit_event(
                workspace_root=workspace_root, event=event, event_name=event_name
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
    return _run_hook(workspace_root=workspace_root, raw_event=raw_event, event_name="afterFileEdit")


def run_cursor_post_tool_use_hook(
    *, workspace_root: str | Path, raw_event: bytes | bytearray | memoryview | None
) -> int:
    return _run_hook(workspace_root=workspace_root, raw_event=raw_event, event_name="postToolUse")


def run_cursor_stop_recovery_hook(
    *, workspace_root: str | Path, raw_event: bytes | bytearray | memoryview | None
) -> int:
    return _run_hook(workspace_root=workspace_root, raw_event=raw_event, event_name="stop")


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
    "cursor_binding_mcp_server_definition",
    "cursor_post_tool_use_hook_definition",
    "cursor_post_write_hook_definition",
    "cursor_post_write_hook_status",
    "cursor_stop_recovery_hook_definition",
    "handle_cursor_after_file_edit_event",
    "handle_cursor_native_edit_event",
    "handle_cursor_post_tool_use_event",
    "handle_cursor_post_write_event",
    "handle_cursor_stop_event",
    "install_cursor_post_write_hook",
    "run_cursor_after_file_edit_hook",
    "run_cursor_post_tool_use_hook",
    "run_cursor_post_write_hook",
    "run_cursor_stop_recovery_hook",
]
