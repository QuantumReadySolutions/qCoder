"""Project-local structured MCP transport for Current Loop activation.

This adapter is deliberately separate from the twelve-tool public Context
Bridge surface.  It exposes one binding-owned internal operation so a connected
assistant can transport the exact current customer message as a typed MCP
argument instead of reconstructing a local command or stdin pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, Mapping

from qcoder import __version__
from qcoder.current_loop_coordinator import CurrentLoopCoordinator

BINDING_MCP_SCHEMA_ID = "qcoder.current_loop.binding_mcp.v1"
BINDING_MCP_SCHEMA_VERSION = 1
BINDING_MCP_SERVER_NAME = "qcoder-current-loop"
BEGIN_CURRENT_LOOP_TOOL_NAME = "begin_current_loop"
MAX_REQUEST_BYTES = 65_536


def binding_tool_descriptors() -> list[dict[str, Any]]:
    """Return the one private, project-local activation operation."""

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
        }
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
                    "This project-local qCoder binding exposes one internal structured operation. "
                    "For a concrete explicit qCoder build request, call begin_current_loop once "
                    "with the exact complete customer message in request_text. Do not construct a "
                    "Shell command, stdin pipeline, CLI invocation, or customer-visible procedure. "
                    "After success, compact_next_action is the sole next-action source."
                ),
            },
        )
    if method == "tools/list":
        return _result(message_id, {"tools": binding_tool_descriptors()})
    if method != "tools/call":
        return _error(message_id, -32601, "method_not_supported")

    params = message.get("params")
    if not isinstance(params, Mapping) or params.get("name") != BEGIN_CURRENT_LOOP_TOOL_NAME:
        return _error(message_id, -32602, "unknown_binding_operation")
    arguments = params.get("arguments")
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
    payload = coordinator.activate(
        original_request=request_text,
        explicit_authority=True,
        capture_mode="exact_current_customer_message",
        request_transport="binding_owned_structured_mcp_argument",
    )
    payload.setdefault("details", {}).update(
        {
            "structured_activation_transport": "project_local_binding_mcp",
            "request_text_argument_received_once": True,
            "shell_or_cli_transport_used": False,
            "stdin_transport_used": False,
            "public_context_bridge_tool": False,
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
    "BINDING_MCP_SCHEMA_ID",
    "BINDING_MCP_SERVER_NAME",
    "binding_tool_descriptors",
    "handle_binding_jsonrpc_message",
    "serve_binding_mcp_stdio",
]
