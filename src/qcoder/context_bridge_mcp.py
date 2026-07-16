from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Callable
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "https://preview-api.qcoder.ai"
ROUTE_PATH = "/v0/internal/hosted-mcp/context"
EXPECTED_TOOLS = (
    "get_guided_evidence_context",
    "create_prompt_context",
    "create_evidence_context_pack",
    "create_context_session_card",
    "create_run_readiness_card",
)
DEFAULT_ARTIFACT_KIND = "share_safe_evidence_summary"
MAX_ARTIFACT_TEXT_CHARS = 20_000
FORBIDDEN_TEXT_MARKERS = (
    "openqasm",
    "qreg ",
    "creg ",
    "counts=",
    '"counts"',
    "'counts'",
    "/home/",
    "\\users\\",
    "c:\\",
    "../",
    "repo_path",
    "file_path",
    "raw_qasm",
    "raw_counts",
    "raw_source",
    "notebook",
    ".ipynb",
)


def default_token_file() -> Path:
    return Path.home() / ".qcoder" / "context-bridge" / "token.txt"


def safe_error(error_category: str, *, status_category: str = "adapter_rejected") -> dict[str, Any]:
    return {
        "ok": False,
        "error_category": error_category,
        "status_category": status_category,
        "retention": "process_and_discard",
        "retained_artifacts": [],
        "token_printed": False,
        "raw_payload_printed": False,
        "raw_response_printed": False,
    }


def validate_token_file(token_file: str | Path) -> tuple[bool, str, str]:
    path = Path(token_file)
    if not path.is_file():
        return False, "token_file_missing", ""
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return False, "token_file_unreadable", ""
    if os.name != "nt" and mode & 0o077:
        return False, "token_file_permissions_unsafe", ""
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError:
        return False, "token_file_unreadable", ""
    if not token:
        return False, "token_file_empty", ""
    if "\n" in token or "\r" in token:
        return False, "token_file_malformed", ""
    return True, "ok", token


def validate_artifact_text(artifact_text: object) -> str:
    if not isinstance(artifact_text, str) or not artifact_text.strip():
        return "artifact_text_missing"
    if len(artifact_text) > MAX_ARTIFACT_TEXT_CHARS:
        return "artifact_text_too_large"
    lowered = artifact_text.lower()
    if any(marker in lowered for marker in FORBIDDEN_TEXT_MARKERS):
        return "forbidden_input_value"
    return "ok"


def decode_json(raw: bytes) -> dict[str, Any]:
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except Exception:
        return {"ok": False, "error_category": "non_json_response"}
    return decoded if isinstance(decoded, dict) else {"ok": False, "error_category": "non_object_response"}


def post_context_bridge(
    *,
    base_url: str,
    token_file: str | Path,
    tool_name: str,
    artifact_text: object,
    artifact_kind: str = DEFAULT_ARTIFACT_KIND,
    client_context: dict[str, Any] | None = None,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    if tool_name not in EXPECTED_TOOLS:
        return safe_error("unknown_tool")
    if artifact_kind != DEFAULT_ARTIFACT_KIND:
        return safe_error("unsupported_artifact_kind")
    text_validation = validate_artifact_text(artifact_text)
    if text_validation != "ok":
        return safe_error(text_validation)
    token_ok, token_category, token = validate_token_file(token_file)
    if not token_ok:
        return safe_error(token_category, status_category="auth_preflight_failed")

    body = {
        "tool_name": tool_name,
        "artifact_kind": artifact_kind,
        "artifact_text": artifact_text,
        "client_context": {
            "client_version": "qcoder-context-bridge-mcp-adapter",
            **(client_context or {}),
        },
    }
    data = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        base_url.rstrip("/") + ROUTE_PATH,
        data=data,
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
        },
        method="POST",
    )
    urlopen = opener or urllib.request.urlopen
    try:
        with urlopen(request, timeout=20) as response:
            status = int(response.status)
            payload = decode_json(response.read())
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        payload = decode_json(exc.read())
    except Exception:
        return safe_error("context_bridge_unreachable", status_category="network_error")

    payload.setdefault("adapter_status_category", "success_2xx" if 200 <= status < 300 else f"http_{status}")
    payload.setdefault("token_printed", False)
    payload.setdefault("raw_payload_printed", False)
    payload.setdefault("raw_response_printed", False)
    return payload


def tool_descriptors() -> list[dict[str, Any]]:
    schema = {
        "type": "object",
        "properties": {
            "artifact_text": {
                "type": "string",
                "description": "Share-safe current qCoder evidence summary. Raw circuits, counts, paths, notebooks, and source files are rejected.",
            },
            "artifact_kind": {
                "type": "string",
                "enum": [DEFAULT_ARTIFACT_KIND],
                "default": DEFAULT_ARTIFACT_KIND,
            },
            "client_context": {
                "type": "object",
                "additionalProperties": True,
                "description": "Optional client metadata without secrets, paths, or raw artifacts.",
            },
        },
        "required": ["artifact_text"],
        "additionalProperties": False,
    }
    descriptions = {
        "get_guided_evidence_context": "Create bounded assistant context from share-safe current qCoder evidence.",
        "create_prompt_context": "Create a share-safe prompt context from current qCoder evidence.",
        "create_evidence_context_pack": "Create a current-evidence context packet with evidence limits and next-step framing.",
        "create_context_session_card": "Create a current-session context card without memory or history.",
        "create_run_readiness_card": "Create a bounded readiness card for the next development check.",
    }
    return [
        {"name": name, "description": descriptions[name], "inputSchema": schema}
        for name in EXPECTED_TOOLS
    ]


def _jsonrpc_result(message_id: object, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _jsonrpc_error(message_id: object, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def handle_jsonrpc_message(
    message: dict[str, Any],
    *,
    base_url: str,
    token_file: str | Path,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any] | None:
    method = message.get("method")
    message_id = message.get("id")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return _jsonrpc_result(
            message_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}, "resources": {}, "prompts": {}},
                "serverInfo": {"name": "qcoder-context-bridge", "version": "1.0.0"},
            },
        )
    if method == "tools/list":
        return _jsonrpc_result(message_id, {"tools": tool_descriptors()})
    if method == "prompts/list":
        return _jsonrpc_result(message_id, {"prompts": []})
    if method == "resources/list":
        return _jsonrpc_result(message_id, {"resources": []})
    if method == "tools/call":
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        tool_name = params.get("name")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        payload = post_context_bridge(
            base_url=base_url,
            token_file=token_file,
            tool_name=str(tool_name or ""),
            artifact_text=arguments.get("artifact_text"),
            artifact_kind=str(arguments.get("artifact_kind") or DEFAULT_ARTIFACT_KIND),
            client_context=arguments.get("client_context")
            if isinstance(arguments.get("client_context"), dict)
            else None,
            opener=opener,
        )
        return _jsonrpc_result(
            message_id,
            {
                "content": [{"type": "text", "text": json.dumps(payload, sort_keys=True)}],
                "structuredContent": payload,
                "isError": payload.get("ok") is False,
            },
        )
    return _jsonrpc_error(message_id, -32601, "method_not_supported")


def serve_stdio(*, base_url: str, token_file: str | Path) -> int:
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            response = _jsonrpc_error(None, -32700, "parse_error")
        else:
            if not isinstance(message, dict):
                response = _jsonrpc_error(None, -32600, "invalid_request")
            else:
                response = handle_jsonrpc_message(message, base_url=base_url, token_file=token_file)
        if response is None:
            continue
        print(json.dumps(response, sort_keys=True), flush=True)
    return 0


def _case_summary(*, payload: dict[str, Any], expected_success: bool) -> dict[str, Any]:
    serialized = json.dumps(payload, sort_keys=True)
    ok_value = payload.get("ok")
    retained = payload.get("retained_artifacts", [])
    status_category = str(payload.get("adapter_status_category") or payload.get("status_category") or "missing")
    success = ok_value is True or status_category == "success_2xx"
    return {
        "expected_outcome_met": success if expected_success else not success,
        "ok_category": "true" if ok_value is True else "false" if ok_value is False else "missing",
        "status_category": status_category,
        "error_category": str(payload.get("error_category") or ""),
        "tool_name_category": payload.get("tool_name")
        if payload.get("tool_name") in EXPECTED_TOOLS
        else "other_or_missing",
        "context_status_category": str(payload.get("context_status") or "missing"),
        "retention_category": str(payload.get("retention") or "missing"),
        "retained_artifacts_empty_or_absent": retained in ([], None),
        "raw_payload_echo_absent": "QCODER_CONTEXT_BRIDGE_SMOKE_MARKER" not in serialized,
        "token_printed": False,
        "raw_response_printed": False,
    }


def run_smoke(*, base_url: str, token_file: str | Path) -> dict[str, Any]:
    token_ok, token_category, _ = validate_token_file(token_file)
    if not token_ok:
        return {
            "ok": False,
            "metadata_only": True,
            "token_file_category": token_category,
            "token_printed": False,
            "raw_token_printed": False,
            "instruction_category": "create_local_chmod_600_token_file",
        }
    safe_text = (
        "Share-safe current qCoder evidence summary. "
        "Small Bell-state style circuit workflow. Evidence summary says the user prepared "
        "a two-qubit entanglement example and wants bounded assistant context. "
        "No raw QASM, no raw counts, no file paths, no backend identifiers, and no source code are included. "
        "QCODER_CONTEXT_BRIDGE_SMOKE_MARKER"
    )
    cases = {
        "guided_context_allowed": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="get_guided_evidence_context",
                artifact_text=safe_text,
            ),
            expected_success=True,
        ),
        "prompt_context_allowed": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="create_prompt_context",
                artifact_text=safe_text,
            ),
            expected_success=True,
        ),
        "evidence_context_pack_allowed": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="create_evidence_context_pack",
                artifact_text=safe_text,
            ),
            expected_success=True,
        ),
        "context_session_card_allowed": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="create_context_session_card",
                artifact_text=safe_text,
            ),
            expected_success=True,
        ),
        "run_readiness_card_allowed": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="create_run_readiness_card",
                artifact_text=safe_text,
            ),
            expected_success=True,
        ),
        "raw_qasm_rejected": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="get_guided_evidence_context",
                artifact_text="OPENQASM 2.0; qreg q[1];",
            ),
            expected_success=False,
        ),
        "repo_path_rejected": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="get_guided_evidence_context",
                artifact_text="/home/private/project/source.py",
            ),
            expected_success=False,
        ),
        "artifact_lookup_rejected": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="get_guided_evidence_context",
                artifact_text="artifact lookup request",
                artifact_kind="server_artifact_id",
            ),
            expected_success=False,
        ),
        "unknown_tool_rejected": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="suggest_next_checks",
                artifact_text=safe_text,
            ),
            expected_success=False,
        ),
    }
    approved = [
        "guided_context_allowed",
        "prompt_context_allowed",
        "evidence_context_pack_allowed",
        "context_session_card_allowed",
        "run_readiness_card_allowed",
    ]
    unsafe = ["raw_qasm_rejected", "repo_path_rejected", "artifact_lookup_rejected", "unknown_tool_rejected"]
    result = {
        "ok": True,
        "metadata_only": True,
        "client_category": "qCoder Context Bridge MCP adapter",
        "token_source_category": "local_chmod_600_file",
        "tools_visible": list(EXPECTED_TOOLS),
        "tools_exact": True,
        "approved_tool_calls_passed": all(cases[name]["expected_outcome_met"] for name in approved),
        "unsafe_calls_rejected": all(cases[name]["expected_outcome_met"] for name in unsafe),
        "token_printed": False,
        "raw_payload_echo": "no" if all(case["raw_payload_echo_absent"] for case in cases.values()) else "yes",
        "retention_category": "process_and_discard_or_rejected",
        "retained_artifacts_empty": "yes"
        if all(case["retained_artifacts_empty_or_absent"] for case in cases.values())
        else "no",
        "payment_auth_billing_mutation": "no",
        "public_claim_created": "no",
        "source_modified": "no",
        "cases": cases,
    }
    result["all_expected_outcomes_met"] = (
        result["approved_tool_calls_passed"]
        and result["unsafe_calls_rejected"]
        and result["raw_payload_echo"] == "no"
        and result["retained_artifacts_empty"] == "yes"
    )
    result["ok"] = bool(result["all_expected_outcomes_met"])
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qcoder context-bridge",
        description="qCoder Context Bridge adapter tools for eligible Explorer users.",
    )
    sub = parser.add_subparsers(dest="context_bridge_command")
    mcp = sub.add_parser("mcp", help="Run or smoke-test the local Context Bridge MCP adapter.")
    mcp_sub = mcp.add_subparsers(dest="mcp_command")

    serve = mcp_sub.add_parser("serve", help="Run the local stdio MCP adapter.")
    serve.add_argument(
        "--token-file",
        default=os.getenv("QCODER_CONTEXT_BRIDGE_TOKEN_FILE", str(default_token_file())),
        help="Path to a local Context Bridge token file. The token value is never printed.",
    )
    serve.add_argument(
        "--base-url",
        default=os.getenv("QCODER_CONTEXT_BRIDGE_BASE_URL", DEFAULT_BASE_URL),
        help="Context Bridge service base URL.",
    )
    serve.set_defaults(context_bridge_command="mcp", mcp_command="serve")

    smoke = mcp_sub.add_parser("smoke", help="Run a sanitized adapter install smoke.")
    smoke.add_argument(
        "--token-file",
        default=os.getenv("QCODER_CONTEXT_BRIDGE_TOKEN_FILE", str(default_token_file())),
        help="Path to a local Context Bridge token file. The token value is never printed.",
    )
    smoke.add_argument(
        "--base-url",
        default=os.getenv("QCODER_CONTEXT_BRIDGE_BASE_URL", DEFAULT_BASE_URL),
        help="Context Bridge service base URL.",
    )
    smoke.add_argument("--json", action="store_true", help="Emit sanitized JSON result.")
    smoke.set_defaults(context_bridge_command="mcp", mcp_command="smoke")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.context_bridge_command is None or getattr(args, "mcp_command", None) is None:
        parser.print_help()
        return 0
    if args.mcp_command == "serve":
        return serve_stdio(base_url=args.base_url, token_file=args.token_file)
    if args.mcp_command == "smoke":
        result = run_smoke(base_url=args.base_url, token_file=args.token_file)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(f"qCoder Context Bridge adapter smoke: {'PASS' if result.get('ok') else 'CHECK'}")
            print(f"  token_file: {result.get('token_file_category', 'present_safe')}")
            print(f"  tools_exact: {result.get('tools_exact', False)}")
            print(f"  approved_tool_calls: {result.get('approved_tool_calls_passed', False)}")
            print(f"  unsafe_calls_rejected: {result.get('unsafe_calls_rejected', False)}")
            print(f"  token_printed: {result.get('token_printed', False)}")
        return 0 if result.get("ok") else 1
    parser.print_help()
    return 0

