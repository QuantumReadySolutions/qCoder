"""One bounded customer setup for qCoder's existing 12+2 local architecture."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Any, Callable, Mapping

from qcoder.context_bridge_connection import (
    connection_state_paths,
    connection_state_root,
    prepare_connection_state,
)
from qcoder.context_bridge_mcp import DEFAULT_BASE_URL, EXPECTED_TOOLS, run_smoke
from qcoder.context_bridge_profiles import CredentialProfileManager, SelectedCredential
from qcoder.current_loop_binding_mcp import (
    BEGIN_CURRENT_LOOP_TOOL_NAME,
    COMPLETE_CURRENT_STEP_TOOL_NAME,
    binding_tool_descriptors,
)
from qcoder.cursor_post_write_hook import (
    BINDING_MCP_SERVER_NAME,
    CursorPostWriteHookError,
    cursor_post_write_hook_status,
    install_cursor_post_write_hook,
)


SETUP_SCHEMA_ID = "qcoder.customer_managed_configuration.v2"
PUBLIC_SERVER_NAME = "qcoder-context-bridge"
SUPPORTED_CLIENT = "cursor"
MAX_CONFIGURATION_BYTES = 65_536


class ContextBridgeSetupError(ValueError):
    """A bounded nonsecret setup failure."""

    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


@dataclass(frozen=True)
class _FileSnapshot:
    path: Path
    existed: bool
    content: bytes
    mode: int | None


def _read_snapshot(path: Path) -> _FileSnapshot:
    if path.is_symlink() or path.parent.is_symlink():
        raise ContextBridgeSetupError("client_configuration_symlink_rejected")
    if not path.exists():
        return _FileSnapshot(path=path, existed=False, content=b"", mode=None)
    if not path.is_file():
        raise ContextBridgeSetupError("client_configuration_not_regular")
    try:
        info = path.stat()
        content = path.read_bytes()
    except OSError as exc:
        raise ContextBridgeSetupError("client_configuration_unreadable") from exc
    if len(content) > MAX_CONFIGURATION_BYTES:
        raise ContextBridgeSetupError("client_configuration_too_large")
    return _FileSnapshot(
        path=path,
        existed=True,
        content=content,
        mode=stat.S_IMODE(info.st_mode),
    )


def _atomic_write(path: Path, content: bytes, *, mode: int = 0o600) -> None:
    if path.is_symlink() or path.parent.is_symlink():
        raise ContextBridgeSetupError("client_configuration_symlink_rejected")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            temporary_path.chmod(mode)
        os.replace(temporary_path, path)
        if os.name != "nt":
            path.chmod(mode)
    finally:
        temporary_path.unlink(missing_ok=True)


def _restore(snapshots: tuple[_FileSnapshot, ...]) -> None:
    errors = []
    for snapshot in reversed(snapshots):
        try:
            if snapshot.existed:
                _atomic_write(snapshot.path, snapshot.content, mode=snapshot.mode or 0o600)
            elif snapshot.path.exists() and not snapshot.path.is_symlink():
                snapshot.path.unlink()
        except OSError:
            errors.append(snapshot.path.name)
    if errors:
        raise ContextBridgeSetupError("client_configuration_rollback_failed")


def _load_mcp(snapshot: _FileSnapshot) -> dict[str, Any]:
    if not snapshot.existed:
        return {"mcpServers": {}}
    try:
        value = json.loads(snapshot.content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContextBridgeSetupError("client_mcp_configuration_invalid") from exc
    if not isinstance(value, dict) or not isinstance(value.get("mcpServers"), dict):
        raise ContextBridgeSetupError("client_mcp_configuration_invalid")
    return value


def _is_lower_sha256(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def public_server_definition(
    *,
    executable: str | Path,
    selected: SelectedCredential,
    client_context: str,
    workspace_context: str,
    base_url: str,
    connection_state_root: str | Path | None = None,
    connection_generation: str | None = None,
    configured_client_session_sha256: str | None = None,
) -> dict[str, Any]:
    """Return one nonsecret explicit-profile definition for the public server."""

    arguments = [
        "-m",
        "qcoder",
        "context-bridge",
        "mcp",
        "serve",
        "--profile",
        selected.profile_id,
        "--client-context",
        client_context,
        "--workspace-context",
        workspace_context,
        "--base-url",
        base_url,
    ]
    observation_values = (
        connection_state_root,
        connection_generation,
        configured_client_session_sha256,
    )
    if any(value is not None for value in observation_values) and not all(
        value is not None for value in observation_values
    ):
        raise ContextBridgeSetupError("connection_observation_binding_incomplete")
    if all(value is not None for value in observation_values):
        if not _is_lower_sha256(connection_generation):
            raise ContextBridgeSetupError("connection_setup_generation_invalid")
        if not _is_lower_sha256(configured_client_session_sha256):
            raise ContextBridgeSetupError("connection_session_binding_invalid")
        arguments.extend(
            [
                "--connection-state-root",
                str(Path(connection_state_root).expanduser().absolute()),
                "--connection-generation",
                str(connection_generation),
                "--connection-session-sha256",
                str(configured_client_session_sha256),
            ]
        )
    return {
        "command": str(Path(executable).expanduser().absolute()),
        "args": arguments,
    }


def _validate_server_preflight(smoke: Mapping[str, Any]) -> None:
    private = [item.get("name") for item in binding_tool_descriptors()]
    if (
        smoke.get("ok") is not True
        or smoke.get("tools_exact") is not True
        or smoke.get("tools_visible") != list(EXPECTED_TOOLS)
        or smoke.get("tools_discovered") != len(EXPECTED_TOOLS)
    ):
        raise ContextBridgeSetupError(
            str(smoke.get("server_preflight_status_category") or "server_preflight_failed")
        )
    if private != [BEGIN_CURRENT_LOOP_TOOL_NAME, COMPLETE_CURRENT_STEP_TOOL_NAME]:
        raise ContextBridgeSetupError("current_loop_operation_inventory_mismatch")


def configure_cursor_workspace(
    *,
    workspace_root: str | Path,
    profile: str | None = None,
    client_context: str = SUPPORTED_CLIENT,
    workspace_context: str | None = None,
    executable: str | Path | None = None,
    base_url: str = DEFAULT_BASE_URL,
    manager: CredentialProfileManager | None = None,
    smoke_runner: Callable[..., dict[str, Any]] = run_smoke,
) -> dict[str, Any]:
    """Select, preflight, and configure Cursor without claiming client connection."""

    if client_context != SUPPORTED_CLIENT:
        raise ContextBridgeSetupError("client_setup_not_supported")
    workspace = Path(workspace_root).expanduser().absolute()
    if workspace.is_symlink() or not workspace.is_dir():
        raise ContextBridgeSetupError("client_workspace_invalid")
    selection_workspace = workspace_context or str(workspace)
    profile_manager = manager or CredentialProfileManager()
    selected = profile_manager.select(
        explicit_profile=profile,
        client_selector=client_context,
        workspace_selector=selection_workspace,
    )
    smoke = smoke_runner(base_url=base_url, token_file=selected)
    _validate_server_preflight(smoke)

    runtime = Path(executable or sys.executable).expanduser().absolute()
    cursor_root = workspace / ".cursor"
    mcp_path = cursor_root / "mcp.json"
    hooks_path = cursor_root / "hooks.json"
    state_paths = connection_state_paths(workspace)
    snapshots = (
        _read_snapshot(mcp_path),
        _read_snapshot(hooks_path),
        *(_read_snapshot(path) for path in state_paths),
    )
    existing_mcp = _load_mcp(snapshots[0])
    predecessor_public = public_server_definition(
        executable=runtime,
        selected=selected,
        client_context=client_context,
        workspace_context=selection_workspace,
        base_url=base_url,
    )

    try:
        manifest = prepare_connection_state(
            workspace,
            client=SUPPORTED_CLIENT,
            configuration_verified=True,
            credential_verified=True,
        )
        state_root = connection_state_root(workspace)
        generation = str(manifest["setup_generation"])
        session_digest = str(manifest["configured_client_session_sha256"])
        expected_public = public_server_definition(
            executable=runtime,
            selected=selected,
            client_context=client_context,
            workspace_context=selection_workspace,
            base_url=base_url,
            connection_state_root=state_root,
            connection_generation=generation,
            configured_client_session_sha256=session_digest,
        )
        current_public = existing_mcp["mcpServers"].get(PUBLIC_SERVER_NAME)
        if current_public is not None and current_public not in (
            predecessor_public,
            expected_public,
        ):
            raise ContextBridgeSetupError("context_bridge_mcp_name_conflict")
        install_cursor_post_write_hook(
            workspace_root=workspace,
            executable=runtime,
            connection_state_root=state_root,
            connection_generation=generation,
            configured_client_session_sha256=session_digest,
        )
        current = _read_snapshot(mcp_path)
        mcp_value = _load_mcp(current)
        mcp_value["mcpServers"][PUBLIC_SERVER_NAME] = expected_public
        encoded = (json.dumps(mcp_value, indent=2, sort_keys=True) + "\n").encode("utf-8")
        _atomic_write(mcp_path, encoded)
        status = cursor_post_write_hook_status(
            workspace_root=workspace,
            executable=runtime,
            connection_state_root=state_root,
            connection_generation=generation,
            configured_client_session_sha256=session_digest,
        )
        verified = _load_mcp(_read_snapshot(mcp_path))
        if (
            status.get("configured") is not True
            or verified["mcpServers"].get(PUBLIC_SERVER_NAME) != expected_public
            or set(name for name in (PUBLIC_SERVER_NAME, BINDING_MCP_SERVER_NAME))
            - set(verified["mcpServers"])
        ):
            raise ContextBridgeSetupError("client_configuration_verification_failed")
    except (ContextBridgeSetupError, CursorPostWriteHookError, OSError, ValueError) as exc:
        _restore(snapshots)
        if isinstance(exc, ContextBridgeSetupError):
            raise
        category = getattr(exc, "category", None) or "client_configuration_failed_restored"
        raise ContextBridgeSetupError(str(category)) from None

    return {
        "schema_id": SETUP_SCHEMA_ID,
        "schema_version": 2,
        "ok": True,
        "customer_result": "qCoder configured",
        "connection_state": "configured",
        "configured": True,
        "connected": False,
        "qualified": False,
        "client": SUPPORTED_CLIENT,
        "profile": {
            "profile_id": selected.profile_id,
            "label": selected.label,
            "selection_source": selected.selection_source,
            "legacy": selected.legacy,
            "secret_included": False,
        },
        "client_workspace_binding": {
            "client_context": client_context,
            "workspace_context_category": (
                "explicit_nonsecret_selector" if workspace_context else "exact_selected_workspace"
            ),
            "workspace_binding_present": True,
            "explicit_profile_bound": True,
        },
        "servers": [PUBLIC_SERVER_NAME, BINDING_MCP_SERVER_NAME],
        "public_tool_count": len(EXPECTED_TOOLS),
        "private_operation_count": 2,
        "declared_public_tool_count": len(EXPECTED_TOOLS),
        "declared_private_operation_count": 2,
        "private_operations": [
            BEGIN_CURRENT_LOOP_TOOL_NAME,
            COMPLETE_CURRENT_STEP_TOOL_NAME,
        ],
        "configuration_verified": True,
        "canonical_server_definitions_verified": True,
        "credential_verified": True,
        "credential_preflight_verified": True,
        "configured_client_session_sha256": session_digest,
        "configured_session_binding_scope": (
            "canonical_server_definitions_and_mcp_protocol_observations"
        ),
        "os_process_identity_established": False,
        "direct_server_smoke_verified": True,
        "client_originated_initialization_verified": False,
        "client_originated_inventory_verified": False,
        "client_originated_qcoder_request_verified": False,
        "client_connection_verified": False,
        "direct_server_smoke_establishes_connection": False,
        "direct_server_smoke_establishes_client_connection": False,
        "client_qualification_created": False,
        "support_claim_created": False,
        "safe_next_action": "reload_cursor_then_ask_use_qcoder_to_check_this_connection",
        "secret_included": False,
        "raw_configuration_included": False,
        "rollback_snapshot_retained": False,
    }


def setup_contract_snapshot() -> dict[str, Any]:
    """Return the stable truthful configured-versus-connected setup contract."""

    return {
        "schema_id": SETUP_SCHEMA_ID,
        "schema_version": 2,
        "customer_result": "qCoder configured",
        "configured": True,
        "connected": False,
        "qualified": False,
        "client_connection_verified": False,
        "connection_state_after_setup": "configured",
        "configured_meaning": (
            "credential selection and canonical server definitions are verified and ready"
        ),
        "connected_meaning": (
            "one client initialized both servers, discovered exact 12+2, and completed "
            "one read-only qCoder request"
        ),
        "supported_client": SUPPORTED_CLIENT,
        "server_entries": [PUBLIC_SERVER_NAME, BINDING_MCP_SERVER_NAME],
        "public_tool_count": len(EXPECTED_TOOLS),
        "private_operations": [BEGIN_CURRENT_LOOP_TOOL_NAME, COMPLETE_CURRENT_STEP_TOOL_NAME],
        "profile_model": "qcoder.context_bridge.credential_profiles.v1",
        "deterministic_selection_reused": True,
        "explicit_profile_pinned_after_selection": True,
        "selected_credential_failure_fallback": False,
        "configuration_transaction": "restore_exact_prior_files_on_failure",
        "client_originated_connection_verification": True,
        "configured_session_binding": "fresh_nonsecret_digest_in_both_server_definitions",
        "observed_protocol_identity_binding": "same_mcp_client_info_digest_across_both_servers",
        "os_process_identity_established": False,
        "direct_server_smoke_establishes_connection": False,
        "direct_server_smoke_establishes_client_connection": False,
        "connection_verification_command": "qcoder context-bridge verify-connection",
        "connection_check_customer_request": "Use qCoder to check this connection.",
        "client_qualification_created": False,
        "support_claim_created": False,
        "secret_in_configuration": False,
        "server_consolidation": False,
    }
