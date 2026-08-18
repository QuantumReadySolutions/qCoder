"""Project-local typed MCP transport for Current Step transactions.

This adapter is deliberately separate from the twelve-tool public Context
Bridge surface.  It exposes two binding-owned internal operations so a connected
assistant can begin and complete one exact Current Step without reconstructing
a local command, stdin pipeline, receipt, digest, or stage ceiling.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, Mapping

from qcoder import __version__
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.current_step_contract import quiet_customer_visibility_contract

BINDING_MCP_SCHEMA_ID = "qcoder.current_loop.binding_mcp.v2"
BINDING_MCP_SCHEMA_VERSION = 2
BINDING_MCP_SERVER_NAME = "qcoder-current-loop"
BEGIN_CURRENT_LOOP_TOOL_NAME = "begin_current_loop"
COMPLETE_CURRENT_STEP_TOOL_NAME = "complete_current_step"
MAX_REQUEST_BYTES = 65_536
MAX_PATH_BYTES = 16_384


def binding_tool_descriptors() -> list[dict[str, Any]]:
    """Return the two private operations in the client-neutral transaction."""

    return [
        {
            "name": BEGIN_CURRENT_LOOP_TOOL_NAME,
            "description": (
                "Begin qCoder's bounded Current Loop for the exact current customer request. "
                "Supply request_text exactly once as the complete unmodified customer message. "
                "This operation preserves the Request Baseline, classifies authority fail-closed, "
                "and grants no native write, execution, review, or governing authority."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request_text": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": MAX_REQUEST_BYTES,
                        "description": "Exact complete current customer message, unchanged.",
                    }
                },
                "required": ["request_text"],
                "additionalProperties": False,
            },
            "x-qcoder-binding-owned-internal-operation": True,
            "x-qcoder-public-context-bridge-tool": False,
            "x-qcoder-normal-happy-path": {"request_text": "<exact current customer message>"},
            "x-qcoder-customer-visibility": quiet_customer_visibility_contract(),
        },
        {
            "name": COMPLETE_CURRENT_STEP_TOOL_NAME,
            "description": (
                "Complete the exact active qCoder Current Step after the native client has "
                "performed its action under its own controls. Supply only the opaque action "
                "handle from the Current Step Contract and the resulting local artifact path. "
                "qCoder reads and validates the actual bytes; do not supply permission state, "
                "digests, loop revisions, receipt identities, roles, or stage ceilings."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "current_action_handle": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 256,
                        "description": "Opaque current-action handle from Current Step Contract.",
                    },
                    "artifact_path": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": MAX_PATH_BYTES,
                        "description": (
                            "Exact resulting local artifact path returned by the native action."
                        ),
                    },
                    "artifact_disposition": {
                        "type": "string",
                        "enum": ["assistant_created", "assistant_modified"],
                        "default": "assistant_created",
                    },
                },
                "required": ["current_action_handle", "artifact_path"],
                "additionalProperties": False,
            },
            "x-qcoder-binding-owned-internal-operation": True,
            "x-qcoder-public-context-bridge-tool": False,
            "x-qcoder-normal-happy-path": {
                "current_action_handle": "<from current_step_contract>",
                "artifact_path": "<exact path returned by native action>",
            },
            "x-qcoder-native-permission-owner": "native_client",
            "x-qcoder-hooks-required-for-correctness": False,
            "x-qcoder-customer-visibility": quiet_customer_visibility_contract(),
        },
    ]


def _result(message_id: object, value: Mapping[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": dict(value)}


def _error(message_id: object, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def _tool_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(payload)
    return {
        "content": [{"type": "text", "text": json.dumps(value, sort_keys=True)}],
        "structuredContent": value,
        "isError": value.get("ok") is not True,
    }


def handle_binding_jsonrpc_message(
    message: Mapping[str, Any], *, workspace_root: str | Path
) -> dict[str, Any] | None:
    """Handle one MCP request without accepting workspace or authority from the model."""

    method = message.get("method")
    message_id = message.get("id")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return _result(
            message_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": BINDING_MCP_SERVER_NAME, "version": __version__},
                "instructions": (
                    "NORMAL SUCCESS IS SILENT INTERNAL WORK. Do not send a customer-visible "
                    "message before begin_current_loop, between the native task and "
                    "complete_current_step, or to explain the transaction. Optional progress is "
                    "task-level only; after successful completion give one concise task outcome. "
                    "Surface qCoder mechanics only for a real blocker, ambiguity, bounded "
                    "recovery, meaningful authority broadening, or requested qCoder help. "
                    "This project-local qCoder binding exposes the two typed operations for one "
                    "Current Step transaction: begin_current_loop, then complete_current_step "
                    "after the native client action. Native permission remains client-owned. "
                    "Do not construct Shell commands, stdin pipelines, receipts, digests, loop "
                    "revisions, roles, or stage ceilings. The returned current_step_contract is "
                    "the only current-stage action source. Hooks may accelerate completion but "
                    "are never required for correctness."
                ),
            },
        )
    if method == "tools/list":
        return _result(message_id, {"tools": binding_tool_descriptors()})
    if method != "tools/call":
        return _error(message_id, -32601, "method_not_supported")

    params = message.get("params")
    if not isinstance(params, Mapping) or params.get("name") not in {
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
    }:
        return _error(message_id, -32602, "unknown_binding_operation")
    operation_name = str(params.get("name"))
    arguments = params.get("arguments")
    if operation_name == COMPLETE_CURRENT_STEP_TOOL_NAME:
        allowed = {"current_action_handle", "artifact_path", "artifact_disposition"}
        if (
            not isinstance(arguments, Mapping)
            or set(arguments).difference(allowed)
            or not {"current_action_handle", "artifact_path"}.issubset(arguments)
            or not isinstance(arguments.get("current_action_handle"), str)
            or not arguments["current_action_handle"]
            or len(arguments["current_action_handle"].encode("utf-8")) > 256
            or not isinstance(arguments.get("artifact_path"), str)
            or not arguments["artifact_path"]
            or len(arguments["artifact_path"].encode("utf-8")) > MAX_PATH_BYTES
            or arguments.get("artifact_disposition", "assistant_created")
            not in {"assistant_created", "assistant_modified"}
        ):
            return _result(
                message_id,
                _tool_result(
                    {
                        "schema_id": "qcoder.current_loop.typed_completion_rejection.v1",
                        "ok": False,
                        "category": "typed_completion_shape_invalid",
                        "expected_shape": {
                            "current_action_handle": "opaque nonempty string from contract",
                            "artifact_path": "nonempty exact local artifact path",
                            "artifact_disposition": "optional created-or-modified enum",
                        },
                        "state_mutated": False,
                        "raw_path_echoed": False,
                    }
                ),
            )
        coordinator = CurrentLoopCoordinator(
            workspace_root=Path(workspace_root).expanduser().absolute(),
            runtime_executable=sys.executable,
        )
        payload = coordinator.complete_current_step(
            current_action_handle=str(arguments["current_action_handle"]),
            artifact_path=str(arguments["artifact_path"]),
            artifact_disposition=str(arguments.get("artifact_disposition", "assistant_created")),
        )
        return _result(message_id, _tool_result(payload))

    if not isinstance(arguments, Mapping) or set(arguments) != {"request_text"}:
        return _result(
            message_id,
            _tool_result(
                {
                    "schema_id": "qcoder.current_loop.structured_activation_rejection.v1",
                    "ok": False,
                    "category": "exact_request_text_argument_required",
                    "expected_shape": {"request_text": "nonempty exact customer message"},
                    "state_mutated": False,
                    "raw_request_echoed": False,
                }
            ),
        )
    request_text = arguments.get("request_text")
    if (
        not isinstance(request_text, str)
        or not request_text
        or len(request_text.encode("utf-8")) > MAX_REQUEST_BYTES
    ):
        return _result(
            message_id,
            _tool_result(
                {
                    "schema_id": "qcoder.current_loop.structured_activation_rejection.v1",
                    "ok": False,
                    "category": "exact_request_text_invalid",
                    "state_mutated": False,
                    "raw_request_echoed": False,
                }
            ),
        )

    coordinator = CurrentLoopCoordinator(
        workspace_root=Path(workspace_root).expanduser().absolute(),
        runtime_executable=sys.executable,
    )
    state_path = coordinator.workspace_root / ".qcoder" / "current-loop" / "state.json"
    continuation = False
    if state_path.is_file() and not state_path.is_symlink():
        current = coordinator.store.read()
        current_status = current.get("coordinator", {}).get("current_step_status")
        continuation = current_status == "complete_resumable"
    payload = (
        coordinator.interpret_current_request(exact_message=request_text)
        if continuation
        else coordinator.activate(
            original_request=request_text,
            explicit_authority=True,
            capture_mode="exact_current_customer_message",
            request_transport="binding_owned_structured_mcp_argument",
        )
    )
    payload.setdefault("details", {}).update(
        {
            "structured_activation_transport": "project_local_binding_mcp",
            "request_text_argument_received_once": True,
            "shell_or_cli_transport_used": False,
            "stdin_transport_used": False,
            "public_context_bridge_tool": False,
            "active_loop_continuation": continuation,
            "request_baseline_recreated": False if continuation else None,
            "rebootstrap_performed": False if continuation else None,
        }
    )
    return _result(message_id, _tool_result(payload))


def _write_content_length_response(response: Mapping[str, Any]) -> None:
    data = json.dumps(dict(response), sort_keys=True, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def serve_binding_mcp_stdio(*, workspace_root: str | Path) -> int:
    """Serve the internal binding MCP over JSON-lines or Content-Length stdio."""

    stdin = sys.stdin.buffer
    while True:
        first = stdin.readline()
        if not first:
            break
        if not first.strip():
            continue
        framed = not first.lstrip().startswith(b"{")
        raw = first
        if framed:
            headers: dict[str, str] = {}
            line = first
            while line:
                stripped = line.strip()
                if not stripped:
                    break
                if b":" in stripped:
                    key, value = stripped.split(b":", 1)
                    headers[key.decode("ascii", "ignore").lower()] = value.decode(
                        "ascii", "ignore"
                    ).strip()
                line = stdin.readline()
            try:
                length = int(headers.get("content-length", "0"))
            except ValueError:
                length = 0
            if length <= 0 or length > 1_048_576:
                response = _error(None, -32600, "invalid_content_length")
                _write_content_length_response(response)
                continue
            raw = stdin.read(length)
        try:
            message = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            response = _error(None, -32700, "parse_error")
        else:
            response = (
                handle_binding_jsonrpc_message(message, workspace_root=workspace_root)
                if isinstance(message, Mapping)
                else _error(None, -32600, "invalid_request")
            )
        if response is None:
            continue
        if framed:
            _write_content_length_response(response)
        else:
            print(json.dumps(response, sort_keys=True), flush=True)
    return 0


__all__ = [
    "BEGIN_CURRENT_LOOP_TOOL_NAME",
    "COMPLETE_CURRENT_STEP_TOOL_NAME",
    "BINDING_MCP_SCHEMA_ID",
    "BINDING_MCP_SERVER_NAME",
    "binding_tool_descriptors",
    "handle_binding_jsonrpc_message",
    "serve_binding_mcp_stdio",
]
