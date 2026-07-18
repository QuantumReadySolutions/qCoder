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
    "create_result_review_context_card",
    "create_next_check_plan",
    "create_single_loop_evidence_diff",
)
PROMPT_CONTEXT_MODES = frozenset(
    {
        "explain",
        "review",
        "revise",
        "troubleshoot",
        "plan_next_checks",
    }
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
    "provider_result",
    "result_payload",
    "raw_provider_result",
    "artifact_id",
    "stored_card_id",
    "prior_session_id",
    "session_id",
    "raw_source",
    "notebook",
    ".ipynb",
    "project memory",
    "prior run history",
    "multi-run comparison",
    "remember it",
    "compare with prior run",
    "backend selection",
    "rank backends",
    "optimize shots",
    "execute this",
    "edit code",
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


def validate_optional_payload(value: object) -> str:
    if value is None:
        return "ok"
    try:
        serialized = json.dumps(value, sort_keys=True)
    except TypeError:
        return "payload_not_json_serializable"
    if len(serialized) > MAX_ARTIFACT_TEXT_CHARS:
        return "artifact_text_too_large"
    lowered = serialized.lower()
    if any(marker in lowered for marker in FORBIDDEN_TEXT_MARKERS):
        return "forbidden_input_value"
    return "ok"


def _has_explicit_side(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(str(nested).strip() for nested in value.values())
    return False


def decode_json(raw: bytes) -> dict[str, Any]:
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except Exception:
        return {"ok": False, "error_category": "non_json_response"}
    return decoded if isinstance(decoded, dict) else {"ok": False, "error_category": "non_object_response"}


def _retry_after_category(value: object) -> str:
    retry_after = str(value or "").strip()
    if not retry_after:
        return "absent"
    if retry_after.isdigit():
        return "seconds"
    if "," in retry_after and ":" in retry_after:
        return "http_date"
    return "present_unparsed"


def post_context_bridge(
    *,
    base_url: str,
    token_file: str | Path,
    tool_name: str,
    artifact_text: object,
    artifact_kind: str = DEFAULT_ARTIFACT_KIND,
    client_context: dict[str, Any] | None = None,
    mode: str | None = None,
    current_goal: object | None = None,
    evidence_basis: object | None = None,
    share_safe_evidence_summary: object | None = None,
    open_questions: object | None = None,
    explicit_assumptions: object | None = None,
    current_card_context: object | None = None,
    before: object | None = None,
    after: object | None = None,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    if tool_name not in EXPECTED_TOOLS:
        return safe_error("unknown_tool")
    if mode is not None:
        if tool_name != "create_prompt_context":
            return safe_error("mode_not_supported_for_tool")
        if str(mode).strip() not in PROMPT_CONTEXT_MODES:
            return safe_error("invalid_prompt_context_mode")
    if tool_name == "create_single_loop_evidence_diff" and (not _has_explicit_side(before) or not _has_explicit_side(after)):
        return safe_error("missing_explicit_diff_side")
    if artifact_kind != DEFAULT_ARTIFACT_KIND:
        return safe_error("unsupported_artifact_kind")
    text_validation = validate_artifact_text(artifact_text)
    if text_validation != "ok":
        return safe_error(text_validation)
    optional_payloads = (
        current_goal,
        evidence_basis,
        share_safe_evidence_summary,
        open_questions,
        explicit_assumptions,
        current_card_context,
        before,
        after,
    )
    for payload in optional_payloads:
        payload_validation = validate_optional_payload(payload)
        if payload_validation != "ok":
            return safe_error(payload_validation)
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
    optional_fields = {
        "mode": mode,
        "current_goal": current_goal,
        "evidence_basis": evidence_basis,
        "share_safe_evidence_summary": share_safe_evidence_summary,
        "open_questions": open_questions,
        "explicit_assumptions": explicit_assumptions,
        "current_card_context": current_card_context,
        "before": before,
        "after": after,
    }
    body.update({key: value for key, value in optional_fields.items() if value is not None})
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
            retry_after = response.headers.get("Retry-After") if getattr(response, "headers", None) else None
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        payload = decode_json(exc.read())
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
    except Exception:
        return safe_error("context_bridge_unreachable", status_category="network_error")

    payload.setdefault("adapter_status_category", "success_2xx" if 200 <= status < 300 else f"http_{status}")
    payload.setdefault("token_printed", False)
    payload.setdefault("raw_payload_printed", False)
    payload.setdefault("raw_response_printed", False)
    if status == 429:
        payload.setdefault("retry_after_category", _retry_after_category(retry_after))
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
            "mode": {
                "type": "string",
                "enum": sorted(PROMPT_CONTEXT_MODES),
                "description": "Optional create_prompt_context handoff mode.",
            },
            "current_goal": {
                "type": "string",
                "description": "Optional bounded current workflow goal.",
            },
            "evidence_basis": {
                "type": "string",
                "description": "Optional share-safe evidence basis for current-request planning.",
            },
            "share_safe_evidence_summary": {
                "type": "string",
                "description": "Optional compact share-safe current evidence summary.",
            },
            "open_questions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional current-request questions without raw artifacts.",
            },
            "explicit_assumptions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional assumptions supplied by the user for this request.",
            },
            "current_card_context": {
                "type": "object",
                "additionalProperties": True,
                "description": "Optional current card/context payload without secrets, paths, or raw artifacts.",
            },
            "before": {
                "type": ["object", "string"],
                "description": (
                    "Explicit before context for Single-Loop Evidence Diff. Prefer an object with compact "
                    "share-safe keys such as goal, evidence, unresolved, assumptions, expectations, or limitations. "
                    "Preserve salient user-provided observations instead of replacing them with generic summaries."
                ),
                "properties": {
                    "goal": {"type": "string"},
                    "evidence": {"type": "string"},
                    "unresolved": {"type": "string"},
                    "assumptions": {"type": "string"},
                    "expectations": {"type": "string"},
                    "limitations": {"type": "string"},
                },
                "additionalProperties": True,
            },
            "after": {
                "type": ["object", "string"],
                "description": (
                    "Explicit after context for Single-Loop Evidence Diff. Prefer an object with compact "
                    "share-safe keys such as result_evidence, unresolved, assumptions, expectations, or limitations. "
                    "Keep salient user-reported result observations, for example a compact reported outcome pattern, "
                    "rather than reducing them to generic 'result evidence is present' wording."
                ),
                "properties": {
                    "result_evidence": {"type": "string"},
                    "evidence": {"type": "string"},
                    "unresolved": {"type": "string"},
                    "assumptions": {"type": "string"},
                    "expectations": {"type": "string"},
                    "limitations": {"type": "string"},
                },
                "additionalProperties": True,
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
        "create_result_review_context_card": "Create a bounded review card from share-safe user-provided result evidence.",
        "create_next_check_plan": "Create a bounded next-check plan from current-request evidence.",
        "create_single_loop_evidence_diff": (
            "Compare two explicitly supplied current-loop contexts without history or lookup. "
            "Use structured before/after fields and preserve salient user-provided result observations."
        ),
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
            mode=str(arguments.get("mode")) if arguments.get("mode") is not None else None,
            current_goal=arguments.get("current_goal"),
            evidence_basis=arguments.get("evidence_basis"),
            share_safe_evidence_summary=arguments.get("share_safe_evidence_summary"),
            open_questions=arguments.get("open_questions"),
            explicit_assumptions=arguments.get("explicit_assumptions"),
            current_card_context=arguments.get("current_card_context"),
            before=arguments.get("before"),
            after=arguments.get("after"),
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


def _write_content_length_response(response: dict[str, Any]) -> None:
    data = json.dumps(response, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def _read_mcp_headers(first_line: bytes) -> dict[str, str]:
    headers: dict[str, str] = {}
    line = first_line
    while line:
        stripped = line.strip()
        if not stripped:
            break
        if b":" in stripped:
            key, value = stripped.split(b":", 1)
            headers[key.decode("ascii", errors="ignore").lower()] = value.decode(
                "ascii", errors="ignore"
            ).strip()
        line = sys.stdin.buffer.readline()
    return headers


def serve_mcp_stdio(*, base_url: str, token_file: str | Path) -> int:
    stdin = sys.stdin.buffer
    while True:
        first_line = stdin.readline()
        if not first_line:
            break
        if not first_line.strip():
            continue
        if first_line.lstrip().startswith(b"{"):
            try:
                message = json.loads(first_line.decode("utf-8"))
            except json.JSONDecodeError:
                response = _jsonrpc_error(None, -32700, "parse_error")
            else:
                response = handle_jsonrpc_message(message, base_url=base_url, token_file=token_file)
            if response is not None:
                print(json.dumps(response, sort_keys=True), flush=True)
            continue

        headers = _read_mcp_headers(first_line)
        try:
            content_length = int(headers.get("content-length", "0"))
        except ValueError:
            _write_content_length_response(_jsonrpc_error(None, -32600, "invalid_content_length"))
            continue
        if content_length <= 0:
            _write_content_length_response(_jsonrpc_error(None, -32600, "missing_content_length"))
            continue
        raw = stdin.read(content_length)
        try:
            message = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            response = _jsonrpc_error(None, -32700, "parse_error")
        else:
            if not isinstance(message, dict):
                response = _jsonrpc_error(None, -32600, "invalid_request")
            else:
                response = handle_jsonrpc_message(message, base_url=base_url, token_file=token_file)
        if response is not None:
            _write_content_length_response(response)
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


def _run_full_smoke(*, base_url: str, token_file: str | Path) -> dict[str, Any]:
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
    prompt_context_payload = post_context_bridge(
        base_url=base_url,
        token_file=token_file,
        tool_name="create_prompt_context",
        artifact_text=safe_text,
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
            payload=prompt_context_payload,
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
        "result_review_context_card_allowed": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="create_result_review_context_card",
                artifact_text=safe_text,
            ),
            expected_success=True,
        ),
        "next_check_plan_allowed": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="create_next_check_plan",
                artifact_text=safe_text,
                current_goal="Choose the next bounded development check.",
                open_questions=["Which assumption should be clarified next?"],
                explicit_assumptions=["The evidence summary is share-safe and current-session only."],
            ),
            expected_success=True,
        ),
        "single_loop_evidence_diff_allowed": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="create_single_loop_evidence_diff",
                artifact_text=safe_text,
                before={"summary": "Before context: readiness card requested one bounded check."},
                after={"summary": "After context: user-provided result evidence was reviewed."},
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
        "invalid_prompt_mode_rejected": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="create_prompt_context",
                artifact_text=safe_text,
                mode="diagnose",
            ),
            expected_success=False,
        ),
        "diff_missing_side_rejected": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="create_single_loop_evidence_diff",
                artifact_text=safe_text,
                before={"summary": "before only"},
            ),
            expected_success=False,
        ),
    }
    prompt_mode_cases = (
        ("prompt_mode_explain_allowed", "explain"),
        ("prompt_mode_review_allowed", "review"),
        ("prompt_mode_revise_allowed", "revise"),
        ("prompt_mode_troubleshoot_allowed", "troubleshoot"),
        ("prompt_mode_plan_next_checks_allowed", "plan_next_checks"),
    )
    rate_limit_pause = (
        str(prompt_context_payload.get("adapter_status_category") or prompt_context_payload.get("status_category"))
        == "http_429"
    )
    retry_after_category = (
        str(prompt_context_payload.get("retry_after_category") or "absent") if rate_limit_pause else "absent"
    )
    if rate_limit_pause:
        for pending_name, _pending_mode in prompt_mode_cases:
            cases[pending_name] = {
                "expected_outcome_met": False,
                "ok_category": "missing",
                "status_category": "not_run_rate_limit_pause",
                "error_category": "",
                "tool_name_category": "create_prompt_context",
                "context_status_category": "missing",
                "retention_category": "process_and_discard",
                "retained_artifacts_empty_or_absent": True,
                "raw_payload_echo_absent": True,
                "token_printed": False,
                "raw_response_printed": False,
            }
    else:
        for index, (case_name, mode) in enumerate(prompt_mode_cases):
            payload = post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="create_prompt_context",
                artifact_text=safe_text,
                mode=mode,
            )
            cases[case_name] = _case_summary(payload=payload, expected_success=True)
            if str(payload.get("adapter_status_category") or payload.get("status_category")) == "http_429":
                rate_limit_pause = True
                retry_after_category = str(payload.get("retry_after_category") or "absent")
                for pending_name, _pending_mode in prompt_mode_cases[index + 1 :]:
                    cases[pending_name] = {
                        "expected_outcome_met": False,
                        "ok_category": "missing",
                        "status_category": "not_run_rate_limit_pause",
                        "error_category": "",
                        "tool_name_category": "create_prompt_context",
                        "context_status_category": "missing",
                        "retention_category": "process_and_discard",
                        "retained_artifacts_empty_or_absent": True,
                        "raw_payload_echo_absent": True,
                        "token_printed": False,
                        "raw_response_printed": False,
                    }
                break

    approved = [
        "guided_context_allowed",
        "prompt_context_allowed",
        "evidence_context_pack_allowed",
        "context_session_card_allowed",
        "run_readiness_card_allowed",
        "result_review_context_card_allowed",
        "next_check_plan_allowed",
        "single_loop_evidence_diff_allowed",
        "prompt_mode_explain_allowed",
        "prompt_mode_review_allowed",
        "prompt_mode_revise_allowed",
        "prompt_mode_troubleshoot_allowed",
        "prompt_mode_plan_next_checks_allowed",
    ]
    unsafe = [
        "raw_qasm_rejected",
        "repo_path_rejected",
        "artifact_lookup_rejected",
        "unknown_tool_rejected",
        "invalid_prompt_mode_rejected",
        "diff_missing_side_rejected",
    ]
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
        "diagnostic_mode": "full",
        "diagnostic_status_category": "rate_limit_pause_required" if rate_limit_pause else "complete",
        "retry_after_category": retry_after_category,
        "token_accepted": "yes",
        "token_onboarding_failure": False,
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


def run_smoke(*, base_url: str, token_file: str | Path, full: bool = False) -> dict[str, Any]:
    if full:
        preflight = run_smoke(base_url=base_url, token_file=token_file)
        if not preflight.get("ok"):
            category = str(preflight.get("connection_status_category") or "connection_check_failed")
            return {
                **preflight,
                "diagnostic_mode": "full",
                "diagnostic_status_category": category,
                "token_onboarding_failure": category in {"token_file_not_ready", "token_rejected"},
            }
        return _run_full_smoke(base_url=base_url, token_file=token_file)

    token_ok, token_category, _ = validate_token_file(token_file)
    if not token_ok:
        return {
            "ok": False,
            "metadata_only": True,
            "connection_status_category": "token_file_not_ready",
            "token_file_category": token_category,
            "token_accepted": "no",
            "tools_visible": list(EXPECTED_TOOLS),
            "tools_exact": True,
            "tools_discovered": len(EXPECTED_TOOLS),
            "token_printed": False,
            "raw_token_printed": False,
            "instruction_category": "create_local_chmod_600_token_file",
        }

    safe_text = (
        "Share-safe current qCoder evidence summary for a harmless connection check. "
        "The user wants one bounded current-session context card. "
        "QCODER_CONTEXT_BRIDGE_SMOKE_MARKER"
    )
    bounded_payload = post_context_bridge(
        base_url=base_url,
        token_file=token_file,
        tool_name="create_context_session_card",
        artifact_text=safe_text,
    )
    bounded_case = _case_summary(payload=bounded_payload, expected_success=True)
    status_category = str(
        bounded_payload.get("adapter_status_category") or bounded_payload.get("status_category") or "missing"
    )
    rate_limited = status_category == "http_429"
    token_rejected = status_category in {"http_401", "http_403"}
    endpoint_reachable = status_category not in {"network_error", "missing"}
    unsafe_payload = post_context_bridge(
        base_url=base_url,
        token_file=token_file,
        tool_name="get_guided_evidence_context",
        artifact_text="OPENQASM 2.0; qreg q[1];",
    )
    unsafe_case = _case_summary(payload=unsafe_payload, expected_success=False)
    ready = bounded_case["expected_outcome_met"] and unsafe_case["expected_outcome_met"]
    return {
        "ok": bool(ready),
        "metadata_only": True,
        "connection_status_category": (
            "ready"
            if ready
            else "rate_limit_pause_required"
            if rate_limited
            else "token_rejected"
            if token_rejected
            else "connection_check_failed"
        ),
        "token_file_category": "present_safe",
        "token_accepted": "yes" if ready else "not_rejected" if rate_limited else "no" if token_rejected else "unknown",
        "endpoint_reachable": endpoint_reachable,
        "tools_visible": list(EXPECTED_TOOLS),
        "tools_exact": True,
        "tools_discovered": len(EXPECTED_TOOLS),
        "bounded_call_passed": bounded_case["expected_outcome_met"],
        "unsafe_input_rejected": unsafe_case["expected_outcome_met"],
        "retry_after_category": str(bounded_payload.get("retry_after_category") or "absent"),
        "token_printed": False,
        "raw_payload_echo": "no"
        if bounded_case["raw_payload_echo_absent"] and unsafe_case["raw_payload_echo_absent"]
        else "yes",
        "retention_category": "process_and_discard_or_rejected",
        "retained_artifacts_empty": "yes"
        if bounded_case["retained_artifacts_empty_or_absent"]
        and unsafe_case["retained_artifacts_empty_or_absent"]
        else "no",
        "payment_auth_billing_mutation": "no",
        "cases": {
            "context_session_card_allowed": bounded_case,
            "unsafe_input_rejected": unsafe_case,
        },
    }


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

    smoke = mcp_sub.add_parser("smoke", help="Check the Context Bridge connection safely.")
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
    smoke.add_argument(
        "--full",
        action="store_true",
        help="Run the exhaustive support/release diagnostic without automatic rate-limit retries.",
    )
    smoke.set_defaults(context_bridge_command="mcp", mcp_command="smoke")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.context_bridge_command is None or getattr(args, "mcp_command", None) is None:
        parser.print_help()
        return 0
    if args.mcp_command == "serve":
        return serve_mcp_stdio(base_url=args.base_url, token_file=args.token_file)
    if args.mcp_command == "smoke":
        result = run_smoke(base_url=args.base_url, token_file=args.token_file, full=args.full)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        elif args.full:
            print(f"Context Bridge full diagnostic: {result.get('diagnostic_status_category', 'check_required')}")
            print(f"Token onboarding failure: {'yes' if result.get('token_onboarding_failure') else 'no'}")
            print(f"Tools discovered: {len(result.get('tools_visible', []))}")
            if result.get("diagnostic_status_category") == "rate_limit_pause_required":
                print("Rate limit: pause before continuing the remaining diagnostic checks")
        else:
            status = "ready" if result.get("ok") else result.get("connection_status_category", "check required")
            print(f"Context Bridge connection: {status}")
            print(f"Token accepted: {result.get('token_accepted', 'unknown')}")
            print(f"Tools discovered: {result.get('tools_discovered', 0)}")
        if result.get("diagnostic_status_category") == "rate_limit_pause_required":
            return 2
        return 0 if result.get("ok") else 1
    parser.print_help()
    return 0
