"""Sanitized client-originated connection observation for qCoder's 12+2 topology.

Configuration and direct server preflight are deliberately insufficient here.  A
workspace is connected only after the configured client has initialized both
stdio servers, discovered their exact inventories, and completed one read-only
public qCoder request with process-and-discard retention.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import tempfile
import time
from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

CONNECTION_MANIFEST_SCHEMA_ID = "qcoder.context_bridge.connection_manifest.v1"
CONNECTION_RECEIPT_SCHEMA_ID = "qcoder.context_bridge.connection_receipt.v1"
CONNECTION_STATUS_SCHEMA_ID = "qcoder.customer_connection_verification.v1"
PUBLIC_SERVER_NAME = "qcoder-context-bridge"
PRIVATE_SERVER_NAME = "qcoder-current-loop"
SERVER_NAMES = (PUBLIC_SERVER_NAME, PRIVATE_SERVER_NAME)
PUBLIC_TOOL_NAMES = (
    "get_guided_evidence_context",
    "create_prompt_context",
    "create_evidence_context_pack",
    "create_context_session_card",
    "create_run_readiness_card",
    "create_result_review_context_card",
    "create_next_check_plan",
    "create_single_loop_evidence_diff",
    "create_algorithm_intent_card",
    "create_implementation_blueprint",
    "create_generation_context_pack",
    "create_source_blueprint_alignment_review",
)
PRIVATE_OPERATION_NAMES = ("begin_current_loop", "complete_current_step")
MAX_STATE_FILE_BYTES = 16_384
MAX_WAIT_SECONDS = 30.0
POLL_INTERVAL_SECONDS = 0.1
MAX_CROSS_SERVER_OBSERVATION_SECONDS = 120.0

_RECEIPT_FILENAMES = {
    PUBLIC_SERVER_NAME: "connection-public.json",
    PRIVATE_SERVER_NAME: "connection-private.json",
}
_RECEIPT_KEYS = {
    "schema_id",
    "schema_version",
    "setup_generation",
    "server_name",
    "client_identity_sha256",
    "initialized",
    "inventory_verified",
    "inventory_count",
    "inventory_sha256",
    "read_only_qcoder_request_verified",
    "qcoder_request_failed",
    "event_sequence",
    "raw_client_stream_retained",
    "raw_request_retained",
    "raw_response_retained",
    "secret_included",
}


class ConnectionObservationError(ValueError):
    """A bounded local connection-observation failure."""

    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


def connection_state_root(workspace_root: str | Path) -> Path:
    """Return the fixed project-local state root without creating it."""

    return Path(workspace_root).expanduser().absolute() / ".qcoder" / "context-bridge"


def connection_state_paths(workspace_root: str | Path) -> tuple[Path, ...]:
    """Return the manifest and both bounded receipt paths."""

    root = connection_state_root(workspace_root)
    return (
        root / "connection-manifest.json",
        root / _RECEIPT_FILENAMES[PUBLIC_SERVER_NAME],
        root / _RECEIPT_FILENAMES[PRIVATE_SERVER_NAME],
    )


def _chain_has_symlink(path: Path, *, stop: Path) -> bool:
    current = path
    while True:
        if current.is_symlink():
            return True
        if current == stop or current.parent == current:
            return False
        current = current.parent


def _validate_generation(value: object) -> str:
    generation = str(value or "")
    if len(generation) != 64 or any(
        character not in "0123456789abcdef" for character in generation
    ):
        raise ConnectionObservationError("connection_setup_generation_invalid")
    return generation


def _atomic_json_write(path: Path, value: Mapping[str, Any]) -> None:
    root = path.parent
    workspace = root.parent.parent
    if _chain_has_symlink(root, stop=workspace) or path.is_symlink():
        raise ConnectionObservationError("connection_state_symlink_rejected")
    root.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        root.chmod(0o700)
    encoded = (json.dumps(dict(value), sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    if len(encoded) > MAX_STATE_FILE_BYTES:
        raise ConnectionObservationError("connection_state_too_large")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=root)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            temporary_path.chmod(0o600)
        os.replace(temporary_path, path)
        if os.name != "nt":
            path.chmod(0o600)
    finally:
        temporary_path.unlink(missing_ok=True)


def prepare_connection_state(
    workspace_root: str | Path,
    *,
    client: str,
    configuration_verified: bool,
    credential_verified: bool,
    setup_generation: str | None = None,
) -> dict[str, Any]:
    """Start one fresh connection-observation generation for a configured workspace."""

    workspace = Path(workspace_root).expanduser().absolute()
    if not workspace.is_dir() or workspace.is_symlink():
        raise ConnectionObservationError("connection_workspace_invalid")
    generation = _validate_generation(setup_generation or secrets.token_hex(32))
    manifest = {
        "schema_id": CONNECTION_MANIFEST_SCHEMA_ID,
        "schema_version": 1,
        "setup_generation": generation,
        "client": str(client),
        "configured": bool(configuration_verified and credential_verified),
        "configuration_verified": bool(configuration_verified),
        "credential_verified": bool(credential_verified),
        "servers": list(SERVER_NAMES),
        "public_tool_count": len(PUBLIC_TOOL_NAMES),
        "private_operation_count": len(PRIVATE_OPERATION_NAMES),
        "direct_server_smoke_establishes_connection": False,
        "client_connection_verified": False,
        "secret_included": False,
        "raw_configuration_included": False,
    }
    manifest_path, public_path, private_path = connection_state_paths(workspace)
    _atomic_json_write(manifest_path, manifest)
    for receipt_path in (public_path, private_path):
        if receipt_path.is_symlink():
            raise ConnectionObservationError("connection_state_symlink_rejected")
        try:
            receipt_path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise ConnectionObservationError("connection_state_reset_failed") from exc
    return deepcopy(manifest)


def _safe_read_json(path: Path) -> tuple[dict[str, Any], os.stat_result]:
    if path.is_symlink() or not path.is_file():
        raise ConnectionObservationError("connection_state_invalid")
    try:
        info = path.stat()
        if info.st_size > MAX_STATE_FILE_BYTES:
            raise ConnectionObservationError("connection_state_invalid")
        if os.name != "nt" and stat.S_IMODE(info.st_mode) & 0o077:
            raise ConnectionObservationError("connection_state_invalid")
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConnectionObservationError("connection_state_invalid") from exc
    if not isinstance(value, dict):
        raise ConnectionObservationError("connection_state_invalid")
    return value, info


def _new_receipt(*, setup_generation: str, server_name: str) -> dict[str, Any]:
    return {
        "schema_id": CONNECTION_RECEIPT_SCHEMA_ID,
        "schema_version": 1,
        "setup_generation": setup_generation,
        "server_name": server_name,
        "client_identity_sha256": "",
        "initialized": False,
        "inventory_verified": False,
        "inventory_count": 0,
        "inventory_sha256": "",
        "read_only_qcoder_request_verified": False,
        "qcoder_request_failed": False,
        "event_sequence": 0,
        "raw_client_stream_retained": False,
        "raw_request_retained": False,
        "raw_response_retained": False,
        "secret_included": False,
    }


def _valid_receipt_shape(value: Mapping[str, Any], *, server_name: str) -> bool:
    return bool(
        set(value) == _RECEIPT_KEYS
        and value.get("schema_id") == CONNECTION_RECEIPT_SCHEMA_ID
        and value.get("schema_version") == 1
        and value.get("server_name") == server_name
        and isinstance(value.get("event_sequence"), int)
        and int(value.get("event_sequence", -1)) >= 0
        and all(
            value.get(key) is False
            for key in (
                "raw_client_stream_retained",
                "raw_request_retained",
                "raw_response_retained",
                "secret_included",
            )
        )
    )


def _load_receipt_for_update(
    path: Path, *, setup_generation: str, server_name: str
) -> dict[str, Any]:
    if not path.exists():
        return _new_receipt(setup_generation=setup_generation, server_name=server_name)
    try:
        value, _ = _safe_read_json(path)
    except ConnectionObservationError:
        return _new_receipt(setup_generation=setup_generation, server_name=server_name)
    if (
        not _valid_receipt_shape(value, server_name=server_name)
        or value.get("setup_generation") != setup_generation
    ):
        return _new_receipt(setup_generation=setup_generation, server_name=server_name)
    return value


def _client_identity_digest(request: Mapping[str, Any]) -> str:
    params = request.get("params")
    client_info = params.get("clientInfo") if isinstance(params, Mapping) else None
    if not isinstance(client_info, Mapping):
        return ""
    name = client_info.get("name")
    version = client_info.get("version")
    if not isinstance(name, str) or not name or not isinstance(version, str) or not version:
        return ""
    projected = {"name": name, "version": version}
    return hashlib.sha256(
        json.dumps(projected, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _response_result(response: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if not isinstance(response, Mapping) or "error" in response:
        return None
    result = response.get("result")
    return result if isinstance(result, Mapping) else None


def _inventory_projection(
    response: Mapping[str, Any] | None, *, expected_names: tuple[str, ...]
) -> tuple[bool, int, str]:
    result = _response_result(response)
    tools = result.get("tools") if isinstance(result, Mapping) else None
    if not isinstance(tools, list):
        return False, 0, ""
    names = [item.get("name") for item in tools if isinstance(item, Mapping)]
    valid = bool(
        len(names) == len(tools) == len(expected_names)
        and all(isinstance(name, str) for name in names)
        and sorted(names) == sorted(expected_names)
    )
    digest = (
        hashlib.sha256(json.dumps(sorted(names), separators=(",", ":")).encode("utf-8")).hexdigest()
        if valid
        else ""
    )
    return valid, len(names), digest


def _successful_read_only_call(
    request: Mapping[str, Any], response: Mapping[str, Any] | None
) -> bool:
    params = request.get("params")
    tool_name = params.get("name") if isinstance(params, Mapping) else None
    if tool_name not in PUBLIC_TOOL_NAMES:
        return False
    result = _response_result(response)
    if not isinstance(result, Mapping) or result.get("isError") is True:
        return False
    structured = result.get("structuredContent")
    return bool(
        isinstance(structured, Mapping)
        and structured.get("ok") is True
        and structured.get("retention") == "process_and_discard"
        and structured.get("retained_artifacts") == []
    )


def record_server_exchange(
    *,
    state_root: str | Path,
    setup_generation: str,
    server_name: str,
    request: Mapping[str, Any],
    response: Mapping[str, Any] | None,
) -> bool:
    """Project and retain only bounded facts from one real stdio exchange.

    This observer is deliberately best-effort.  Callers must never change an MCP
    response merely because local diagnostic evidence could not be written.
    """

    try:
        generation = _validate_generation(setup_generation)
        if server_name not in SERVER_NAMES or not isinstance(request, Mapping):
            return False
        root = Path(state_root).expanduser().absolute()
        filename = _RECEIPT_FILENAMES[server_name]
        receipt_path = root / filename
        receipt = _load_receipt_for_update(
            receipt_path,
            setup_generation=generation,
            server_name=server_name,
        )
        method = request.get("method")
        result = _response_result(response)
        changed = False
        if method == "initialize":
            digest = _client_identity_digest(request)
            server_info = result.get("serverInfo") if isinstance(result, Mapping) else None
            if (
                digest
                and isinstance(server_info, Mapping)
                and server_info.get("name") == server_name
            ):
                receipt = _new_receipt(setup_generation=generation, server_name=server_name)
                receipt["initialized"] = True
                receipt["client_identity_sha256"] = digest
                receipt["event_sequence"] = 1
                changed = True
        elif method == "tools/list" and receipt.get("initialized") is True:
            expected = (
                PUBLIC_TOOL_NAMES if server_name == PUBLIC_SERVER_NAME else PRIVATE_OPERATION_NAMES
            )
            exact, count, inventory_digest = _inventory_projection(
                response, expected_names=expected
            )
            receipt["inventory_verified"] = exact
            receipt["inventory_count"] = count
            receipt["inventory_sha256"] = inventory_digest
            receipt["event_sequence"] = int(receipt["event_sequence"]) + 1
            changed = True
        elif (
            method == "tools/call"
            and server_name == PUBLIC_SERVER_NAME
            and receipt.get("initialized") is True
            and receipt.get("inventory_verified") is True
        ):
            successful = _successful_read_only_call(request, response)
            receipt["read_only_qcoder_request_verified"] = successful
            receipt["qcoder_request_failed"] = not successful
            receipt["event_sequence"] = int(receipt["event_sequence"]) + 1
            changed = True
        if not changed:
            return False
        _atomic_json_write(receipt_path, receipt)
        return True
    except (ConnectionObservationError, OSError, TypeError, ValueError):
        return False


def _base_status(*, configured: bool, category: str) -> dict[str, Any]:
    return {
        "schema_id": CONNECTION_STATUS_SCHEMA_ID,
        "schema_version": 1,
        "ok": False,
        "configured": configured,
        "connected": False,
        "qualified": False,
        "connection_state": "configured" if configured else "not_configured",
        "customer_result": "qCoder configured" if configured else "qCoder not configured",
        "category": category,
        "client_connection_verified": False,
        "client_originated": False,
        "servers_initialized": [],
        "public_server_initialized": False,
        "private_server_initialized": False,
        "public_tool_inventory_verified": False,
        "private_operation_inventory_verified": False,
        "read_only_qcoder_request_verified": False,
        "public_tools_discovered": 0,
        "private_operations_discovered": 0,
        "direct_server_smoke_establishes_connection": False,
        "client_qualification_created": False,
        "support_claim_created": False,
        "secret_included": False,
        "raw_client_stream_retained": False,
        "raw_request_retained": False,
        "raw_response_retained": False,
    }


def _valid_manifest(value: Mapping[str, Any]) -> bool:
    try:
        _validate_generation(value.get("setup_generation"))
    except ConnectionObservationError:
        return False
    return bool(
        value.get("schema_id") == CONNECTION_MANIFEST_SCHEMA_ID
        and value.get("schema_version") == 1
        and value.get("configured") is True
        and value.get("configuration_verified") is True
        and value.get("credential_verified") is True
        and value.get("servers") == list(SERVER_NAMES)
        and value.get("public_tool_count") == len(PUBLIC_TOOL_NAMES)
        and value.get("private_operation_count") == len(PRIVATE_OPERATION_NAMES)
        and value.get("secret_included") is False
        and value.get("raw_configuration_included") is False
    )


def _evaluate_connection(workspace_root: Path) -> dict[str, Any]:
    manifest_path, public_path, private_path = connection_state_paths(workspace_root)
    if not manifest_path.exists() or manifest_path.is_symlink():
        return _base_status(configured=False, category="qcoder_not_configured")
    try:
        manifest, manifest_info = _safe_read_json(manifest_path)
    except ConnectionObservationError:
        return _base_status(configured=False, category="qcoder_not_configured")
    if not _valid_manifest(manifest):
        return _base_status(configured=False, category="qcoder_not_configured")
    status = _base_status(configured=True, category="client_mcp_initialization_not_observed")
    receipts: dict[str, tuple[dict[str, Any], os.stat_result]] = {}
    for server_name, path in (
        (PUBLIC_SERVER_NAME, public_path),
        (PRIVATE_SERVER_NAME, private_path),
    ):
        if not path.exists():
            continue
        try:
            receipt, info = _safe_read_json(path)
        except ConnectionObservationError:
            status["category"] = "connection_receipt_invalid_or_stale"
            return status
        if not _valid_receipt_shape(receipt, server_name=server_name):
            status["category"] = "connection_receipt_invalid_or_stale"
            return status
        if info.st_mtime + 1e-6 < manifest_info.st_mtime:
            status["category"] = "connection_receipt_invalid_or_stale"
            return status
        receipts[server_name] = (receipt, info)
    if set(receipts) != set(SERVER_NAMES):
        return status
    public, public_info = receipts[PUBLIC_SERVER_NAME]
    private, private_info = receipts[PRIVATE_SERVER_NAME]
    generation = manifest["setup_generation"]
    if (
        public.get("setup_generation") != generation
        or private.get("setup_generation") != generation
    ):
        status["category"] = "connection_receipt_generation_mismatch"
        return status
    status["public_server_initialized"] = public.get("initialized") is True
    status["private_server_initialized"] = private.get("initialized") is True
    status["servers_initialized"] = [
        server_name
        for server_name, initialized in (
            (PUBLIC_SERVER_NAME, status["public_server_initialized"]),
            (PRIVATE_SERVER_NAME, status["private_server_initialized"]),
        )
        if initialized
    ]
    if not status["public_server_initialized"] or not status["private_server_initialized"]:
        return status
    if public.get("client_identity_sha256") != private.get("client_identity_sha256"):
        status["category"] = "connection_receipt_client_mismatch"
        return status
    if (
        not public.get("client_identity_sha256")
        or abs(public_info.st_mtime - private_info.st_mtime) > MAX_CROSS_SERVER_OBSERVATION_SECONDS
    ):
        status["category"] = "connection_observation_window_mismatch"
        return status
    status["public_tool_inventory_verified"] = public.get("inventory_verified") is True
    status["public_tools_discovered"] = int(public.get("inventory_count") or 0)
    if not status["public_tool_inventory_verified"]:
        status["category"] = "public_tool_inventory_not_verified"
        return status
    status["private_operation_inventory_verified"] = private.get("inventory_verified") is True
    status["private_operations_discovered"] = int(private.get("inventory_count") or 0)
    if not status["private_operation_inventory_verified"]:
        status["category"] = "private_operation_inventory_not_verified"
        return status
    status["read_only_qcoder_request_verified"] = (
        public.get("read_only_qcoder_request_verified") is True
    )
    if not status["read_only_qcoder_request_verified"]:
        status["category"] = (
            "qcoder_request_failed"
            if public.get("qcoder_request_failed") is True
            else "read_only_qcoder_request_not_observed"
        )
        return status
    status.update(
        {
            "ok": True,
            "connected": True,
            "connection_state": "connected",
            "customer_result": "qCoder connected",
            "category": "connected",
            "client_connection_verified": True,
            "client_originated": True,
        }
    )
    return status


def connection_status(
    *,
    workspace_root: str | Path,
    wait_seconds: float = 0.0,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Return one bounded, privacy-safe configured/connected disposition."""

    try:
        wait = float(wait_seconds)
    except (TypeError, ValueError) as exc:
        raise ConnectionObservationError("connection_wait_invalid") from exc
    if not 0.0 <= wait <= MAX_WAIT_SECONDS:
        raise ConnectionObservationError("connection_wait_invalid")
    workspace = Path(workspace_root).expanduser().absolute()
    deadline = monotonic() + wait
    while True:
        result = _evaluate_connection(workspace)
        if result.get("connected") is True:
            return result
        remaining = deadline - monotonic()
        if remaining <= 0.0:
            return result
        sleeper(min(POLL_INTERVAL_SECONDS, remaining))


__all__ = [
    "CONNECTION_MANIFEST_SCHEMA_ID",
    "CONNECTION_RECEIPT_SCHEMA_ID",
    "CONNECTION_STATUS_SCHEMA_ID",
    "PRIVATE_OPERATION_NAMES",
    "PRIVATE_SERVER_NAME",
    "PUBLIC_SERVER_NAME",
    "PUBLIC_TOOL_NAMES",
    "ConnectionObservationError",
    "connection_state_paths",
    "connection_state_root",
    "connection_status",
    "prepare_connection_state",
    "record_server_exchange",
]
