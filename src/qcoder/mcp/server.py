from __future__ import annotations

import argparse
import json
import sys
from typing import Any, TextIO

from qcoder.mcp.tools import call_tool, list_tools


SERVER_INFO = {"name": "qcoder-local-read-only", "version": "0.1.0"}


def serve_stdio(*, stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    in_stream = stdin or sys.stdin
    out_stream = stdout or sys.stdout
    for raw_line in in_stream:
        line = raw_line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = handle_request(request)
        except Exception as exc:  # MCP server must answer JSON-RPC errors, not crash on bad input.
            response = _error_response(None, -32603, str(exc))
        if response is not None:
            out_stream.write(json.dumps(response, separators=(",", ":"), sort_keys=True) + "\n")
            out_stream.flush()
    return 0


def handle_request(request: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(request, dict):
        return _error_response(None, -32600, "request must be a JSON object")
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params") if isinstance(request.get("params"), dict) else {}

    if method == "initialize":
        return _result_response(
            request_id,
            {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
                "instructions": (
                    "Local read-only qCoder MCP. Uses explicit user-selected inputs only; "
                    "does not execute circuits, modify code, use tokens, or call live services."
                ),
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return _result_response(request_id, {"tools": list_tools()})
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments")
        if not isinstance(name, str):
            return _error_response(request_id, -32602, "tools/call requires a string tool name")
        if arguments is not None and not isinstance(arguments, dict):
            return _error_response(request_id, -32602, "tools/call arguments must be an object")
        try:
            return _result_response(request_id, call_tool(name, arguments or {}))
        except Exception as exc:
            return _error_response(request_id, -32000, str(exc))
    return _error_response(request_id, -32601, f"unknown method: {method}")


def _result_response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qcoder mcp serve")
    parser.add_argument("serve", nargs="?", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    _ = args
    return serve_stdio()


if __name__ == "__main__":
    raise SystemExit(main())
