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


SETUP_SCHEMA_ID = "qcoder.customer_managed_connection.v1"
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


def public_server_definition(
    *,
    executable: str | Path,
    selected: SelectedCredential,
    client_context: str,
    workspace_context: str,
    base_url: str,
) -> dict[str, Any]:
    """Return one nonsecret explicit-profile definition for the public server."""

    return {
        "command": str(Path(executable).expanduser().absolute()),
        "args": [
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
        ],
    }


def _validate_inventory(smoke: Mapping[str, Any]) -> None:
    private = [item.get("name") for item in binding_tool_descriptors()]
    if (
        smoke.get("ok") is not True
        or smoke.get("tools_exact") is not True
        or smoke.get("tools_visible") != list(EXPECTED_TOOLS)
        or smoke.get("tools_discovered") != len(EXPECTED_TOOLS)
    ):
        raise ContextBridgeSetupError(
            str(smoke.get("connection_status_category") or "context_bridge_verification_failed")
        )
    if private != [BEGIN_CURRENT_LOOP_TOOL_NAME, COMPLETE_CURRENT_STEP_TOOL_NAME]:
        raise ContextBridgeSetupError("current_loop_operation_inventory_mismatch")


def connect_cursor_workspace(
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
    """Select, verify, and atomically configure Cursor for the existing 12+2 servers."""

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
    _validate_inventory(smoke)

    runtime = Path(executable or sys.executable).expanduser().absolute()
    cursor_root = workspace / ".cursor"
    mcp_path = cursor_root / "mcp.json"
    hooks_path = cursor_root / "hooks.json"
    snapshots = (_read_snapshot(mcp_path), _read_snapshot(hooks_path))
    existing_mcp = _load_mcp(snapshots[0])
    expected_public = public_server_definition(
        executable=runtime,
        selected=selected,
        client_context=client_context,
        workspace_context=selection_workspace,
        base_url=base_url,
    )
    current_public = existing_mcp["mcpServers"].get(PUBLIC_SERVER_NAME)
    if current_public is not None and current_public != expected_public:
        raise ContextBridgeSetupError("context_bridge_mcp_name_conflict")

    try:
        install_cursor_post_write_hook(workspace_root=workspace, executable=runtime)
        current = _read_snapshot(mcp_path)
        mcp_value = _load_mcp(current)
        mcp_value["mcpServers"][PUBLIC_SERVER_NAME] = expected_public
        encoded = (json.dumps(mcp_value, indent=2, sort_keys=True) + "\n").encode("utf-8")
        _atomic_write(mcp_path, encoded)
        status = cursor_post_write_hook_status(workspace_root=workspace, executable=runtime)
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
        "schema_version": 1,
        "ok": True,
        "customer_result": "qCoder connected",
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
        "private_operations": [
            BEGIN_CURRENT_LOOP_TOOL_NAME,
            COMPLETE_CURRENT_STEP_TOOL_NAME,
        ],
        "configuration_verified": True,
        "credential_verified": True,
        "secret_included": False,
        "raw_configuration_included": False,
        "rollback_snapshot_retained": False,
    }


def setup_contract_snapshot() -> dict[str, Any]:
    """Return the stable nonsecret D-105 setup contract."""

    return {
        "schema_id": SETUP_SCHEMA_ID,
        "schema_version": 1,
        "customer_result": "qCoder connected",
        "supported_client": SUPPORTED_CLIENT,
        "server_entries": [PUBLIC_SERVER_NAME, BINDING_MCP_SERVER_NAME],
        "public_tool_count": len(EXPECTED_TOOLS),
        "private_operations": [BEGIN_CURRENT_LOOP_TOOL_NAME, COMPLETE_CURRENT_STEP_TOOL_NAME],
        "profile_model": "qcoder.context_bridge.credential_profiles.v1",
        "deterministic_selection_reused": True,
        "explicit_profile_pinned_after_selection": True,
        "selected_credential_failure_fallback": False,
        "configuration_transaction": "restore_exact_prior_files_on_failure",
        "secret_in_configuration": False,
        "server_consolidation": False,
    }
