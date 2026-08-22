from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
import os
from pathlib import Path
import stat
from typing import Any


def _append_event(path: Path, value: Mapping[str, Any], *, workspace: Path) -> None:
    destination = path.absolute()
    root = workspace.absolute()
    if destination == root or destination in root.parents or root in destination.parents:
        raise SystemExit("MCP evidence log must remain outside the Cursor workspace.")
    if not destination.parent.is_dir() or destination.parent.is_symlink():
        raise SystemExit("MCP evidence directory is unavailable or unsafe.")
    payload = json.dumps(dict(value), sort_keys=True, separators=(",", ":")).encode() + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(destination, flags, stat.S_IRUSR | stat.S_IWUSR)
    try:
        os.write(descriptor, payload)
    finally:
        os.close(descriptor)


def _safe_result(response: object) -> dict[str, Any]:
    if not isinstance(response, Mapping):
        return {"response": "none"}
    result = response.get("result")
    structured = result.get("structuredContent") if isinstance(result, Mapping) else None
    if not isinstance(structured, Mapping):
        return {"response": "protocol_only"}
    artifact = structured.get("artifact")
    return {
        "ok": structured.get("ok") is True,
        "category": structured.get("category"),
        "operation": structured.get("operation"),
        "state_revision": structured.get("state_revision"),
        "current_step_status": structured.get("current_step_status"),
        "artifact_role": artifact.get("role") if isinstance(artifact, Mapping) else None,
        "raw_arguments_retained": False,
        "raw_result_retained": False,
    }


def _instrument(handler, *, surface: str, event_log: Path, workspace: Path):
    def wrapped(message, **kwargs):
        response = handler(message, **kwargs)
        if isinstance(message, Mapping) and message.get("method") == "tools/call":
            params = message.get("params")
            name = params.get("name") if isinstance(params, Mapping) else None
            arguments = params.get("arguments") if isinstance(params, Mapping) else None
            _append_event(
                event_log,
                {
                    "schema_id": "qcoder.wi0435.bounded_mcp_event.v1",
                    "surface": surface,
                    "tool": str(name) if isinstance(name, str) else "unknown",
                    "argument_field_names": sorted(arguments)
                    if isinstance(arguments, Mapping)
                    else [],
                    "result": _safe_result(response),
                    "credential_retained": False,
                    "raw_request_retained": False,
                    "raw_artifact_retained": False,
                },
                workspace=workspace,
            )
        return response

    return wrapped


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("surface", choices=["public", "private"])
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--event-log", type=Path, required=True)
    parser.add_argument("--token-file", type=Path)
    args = parser.parse_args()
    workspace = args.workspace.absolute()
    event_log = args.event_log.absolute()
    if args.surface == "private":
        import qcoder.current_loop_binding_mcp as binding

        original = binding.handle_binding_jsonrpc_message
        binding.handle_binding_jsonrpc_message = _instrument(
            original, surface="private_current_loop", event_log=event_log, workspace=workspace
        )
        raise SystemExit(binding.serve_binding_mcp_stdio(workspace_root=workspace))
    if args.token_file is None or not args.token_file.is_file():
        raise SystemExit("The Context Bridge token-file path is required.")
    import qcoder.context_bridge_mcp as bridge

    original = bridge.handle_jsonrpc_message
    bridge.handle_jsonrpc_message = _instrument(
        original, surface="public_context_bridge", event_log=event_log, workspace=workspace
    )
    raise SystemExit(
        bridge.serve_mcp_stdio(base_url=bridge.DEFAULT_BASE_URL, token_file=args.token_file)
    )


if __name__ == "__main__":
    main()
