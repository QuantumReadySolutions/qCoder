from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import threading
import urllib.error
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from qcoder.cli import main
from qcoder.context_bridge_mcp import (
    EXPECTED_TOOLS,
    handle_jsonrpc_message,
    post_context_bridge,
    run_smoke,
    tool_descriptors,
    validate_token_file,
)
import qcoder.context_bridge_mcp as context_bridge_mcp


class _FakeResponse:
    status = 200

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(
            {
                "ok": True,
                "tool_name": "get_guided_evidence_context",
                "context_status": "assistant_context_ready",
                "retention": "process_and_discard",
                "retained_artifacts": [],
            }
        ).encode("utf-8")


def _write_token(path: Path, text: str = "ctxbridge-token-not-printed") -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)


def test_context_bridge_root_help_includes_command() -> None:
    out = io.StringIO()
    with redirect_stdout(out):
        rc = main(["--help"])
    assert rc == 0
    assert "context-bridge" in out.getvalue()


def test_context_bridge_help_includes_mcp_serve_and_smoke() -> None:
    out = io.StringIO()
    with redirect_stdout(out):
        try:
            rc = main(["context-bridge", "mcp", "--help"])
        except SystemExit as exc:
            rc = int(exc.code)
    assert rc == 0
    text = out.getvalue()
    assert "serve" in text
    assert "smoke" in text


def test_tool_descriptors_are_exact_public_context_bridge_tools() -> None:
    names = [tool["name"] for tool in tool_descriptors()]
    assert names == [
        "get_guided_evidence_context",
        "create_prompt_context",
        "create_evidence_context_pack",
        "create_context_session_card",
        "create_run_readiness_card",
        "create_result_review_context_card",
        "create_next_check_plan",
        "create_single_loop_evidence_diff",
    ]
    assert names == list(EXPECTED_TOOLS)
    assert "suggest_next_checks" not in names
    assert "apply_repo_edit" not in names
    result_review = next(tool for tool in tool_descriptors() if tool["name"] == "create_result_review_context_card")
    assert "user-provided result evidence" in result_review["description"]
    next_check = next(tool for tool in tool_descriptors() if tool["name"] == "create_next_check_plan")
    assert "current-request evidence" in next_check["description"]
    diff = next(tool for tool in tool_descriptors() if tool["name"] == "create_single_loop_evidence_diff")
    assert "without history or lookup" in diff["description"]
    assert "preserve salient user-provided result observations" in diff["description"]
    assert "result_evidence" in diff["inputSchema"]["properties"]["after"]["properties"]
    assert "Preserve salient user-provided observations" in diff["inputSchema"]["properties"]["before"]["description"]
    assert "generic 'result evidence is present'" in diff["inputSchema"]["properties"]["after"]["description"]


def test_token_file_validation_requires_private_local_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.txt"
    ok, category, token = validate_token_file(missing)
    assert (ok, category, token) == (False, "token_file_missing", "")

    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    ok, category, token = validate_token_file(token_file)
    assert ok is True
    assert category == "ok"
    assert token == "ctxbridge-token-not-printed"

    token_file.chmod(0o644)
    ok, category, token = validate_token_file(token_file)
    assert ok is False
    assert category == "token_file_permissions_unsafe"
    assert token == ""


def test_unsafe_inputs_rejected_before_network(tmp_path: Path) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)

    def fail_if_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("network should not be called")

    for text in (
        "OPENQASM 2.0; qreg q[1];",
        "counts={'00': 4}",
        "provider_result={raw backend payload}",
        "/home/example/project/file.py",
        "repo_path=src/example.py",
        "Please compare with prior run history and remember it.",
    ):
        payload = post_context_bridge(
            base_url="https://example.invalid",
            token_file=token_file,
            tool_name="get_guided_evidence_context",
            artifact_text=text,
            opener=fail_if_called,
        )
        assert payload["ok"] is False
        assert payload["error_category"] == "forbidden_input_value"


def test_unknown_tool_and_artifact_lookup_rejected(tmp_path: Path) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    payload = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="suggest_next_checks",
        artifact_text="share-safe evidence summary",
    )
    assert payload["ok"] is False
    assert payload["error_category"] == "unknown_tool"

    payload = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="get_guided_evidence_context",
        artifact_text="artifact id lookup",
        artifact_kind="server_artifact_id",
    )
    assert payload["ok"] is False
    assert payload["error_category"] == "unsupported_artifact_kind"


def test_prompt_modes_and_diff_arguments_are_locally_validated(tmp_path: Path) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)

    def opener(request: object, timeout: int = 20) -> _FakeResponse:
        return _FakeResponse()

    for mode in ("explain", "review", "revise", "troubleshoot", "plan_next_checks"):
        payload = post_context_bridge(
            base_url="https://example.invalid",
            token_file=token_file,
            tool_name="create_prompt_context",
            artifact_text="Share-safe current evidence summary.",
            mode=mode,
            opener=opener,
        )
        assert payload["ok"] is True

    invalid = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="create_prompt_context",
        artifact_text="Share-safe current evidence summary.",
        mode="diagnose",
        opener=opener,
    )
    assert invalid["ok"] is False
    assert invalid["error_category"] == "invalid_prompt_context_mode"

    missing_side = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="create_single_loop_evidence_diff",
        artifact_text="Share-safe current evidence summary.",
        before={"summary": "before only"},
        opener=opener,
    )
    assert missing_side["ok"] is False
    assert missing_side["error_category"] == "missing_explicit_diff_side"

    diff = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="create_single_loop_evidence_diff",
        artifact_text="Share-safe current evidence summary.",
        before={"summary": "before current-loop context"},
        after={"summary": "after current-loop context"},
        opener=opener,
    )
    assert diff["ok"] is True

    next_check = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="create_next_check_plan",
        artifact_text="Share-safe current evidence summary.",
        current_goal="Choose a bounded next check.",
        opener=opener,
    )
    assert next_check["ok"] is True


def test_optional_payloads_reject_raw_or_history_values_before_network(tmp_path: Path) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)

    def fail_if_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("network should not be called")

    payload = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="create_single_loop_evidence_diff",
        artifact_text="Share-safe current evidence summary.",
        before={"summary": "before"},
        after={"raw_counts": {"00": 10}},
        opener=fail_if_called,
    )
    assert payload["ok"] is False
    assert payload["error_category"] == "forbidden_input_value"

    payload = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="create_next_check_plan",
        artifact_text="Share-safe current evidence summary.",
        current_goal="Compare with prior run history.",
        opener=fail_if_called,
    )
    assert payload["ok"] is False
    assert payload["error_category"] == "forbidden_input_value"


def test_approved_call_forwards_bearer_without_printing_token(tmp_path: Path) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file, "ctxbridge-secret-token")
    seen: dict[str, str] = {}

    def opener(request: object, timeout: int = 20) -> _FakeResponse:
        assert timeout == 20
        seen["authorization"] = request.headers["Authorization"]  # type: ignore[attr-defined]
        return _FakeResponse()

    payload = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="get_guided_evidence_context",
        artifact_text="Share-safe current evidence summary.",
        opener=opener,
    )
    assert payload["ok"] is True
    assert seen["authorization"] == "Bearer ctxbridge-secret-token"
    assert payload["token_printed"] is False
    assert "ctxbridge-secret-token" not in json.dumps(payload)


def test_jsonrpc_lists_exact_tools_and_calls_tool(tmp_path: Path) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)

    listed = handle_jsonrpc_message(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        base_url="https://example.invalid",
        token_file=token_file,
    )
    assert listed is not None
    assert [tool["name"] for tool in listed["result"]["tools"]] == list(EXPECTED_TOOLS)

    def opener(request: object, timeout: int = 20) -> _FakeResponse:
        return _FakeResponse()

    called = handle_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "get_guided_evidence_context",
                "arguments": {"artifact_text": "Share-safe current evidence summary."},
            },
        },
        base_url="https://example.invalid",
        token_file=token_file,
        opener=opener,
    )
    assert called is not None
    assert called["result"]["structuredContent"]["ok"] is True
    assert called["result"]["isError"] is False

    diff_called = handle_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "create_single_loop_evidence_diff",
                "arguments": {
                    "artifact_text": "Share-safe current evidence summary.",
                    "before": {"summary": "before current-loop context"},
                    "after": {"summary": "after current-loop context"},
                },
            },
        },
        base_url="https://example.invalid",
        token_file=token_file,
        opener=opener,
    )
    assert diff_called is not None
    assert diff_called["result"]["structuredContent"]["ok"] is True


def _content_length_message(message: dict[str, object]) -> bytes:
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


def _read_content_length_response(stdout: object) -> dict[str, object]:
    headers: dict[str, str] = {}
    while True:
        line = stdout.readline()  # type: ignore[attr-defined]
        assert line
        stripped = line.strip()
        if not stripped:
            break
        key, value = stripped.decode("ascii").split(":", 1)
        headers[key.lower()] = value.strip()
    body = stdout.read(int(headers["content-length"]))  # type: ignore[attr-defined]
    return json.loads(body.decode("utf-8"))


def test_mcp_stdio_content_length_lists_exact_tools(tmp_path: Path) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    env = {**os.environ, "PYTHONPATH": str(Path.cwd() / "src")}
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "qcoder",
            "context-bridge",
            "mcp",
            "serve",
            "--token-file",
            str(token_file),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        assert proc.stdin is not None
        assert proc.stdout is not None
        proc.stdin.write(
            _content_length_message(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0"},
                    },
                }
            )
        )
        proc.stdin.flush()
        initialized = _read_content_length_response(proc.stdout)
        assert initialized["result"]["serverInfo"]["name"] == "qcoder-context-bridge"

        proc.stdin.write(
            _content_length_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        )
        proc.stdin.flush()
        listed = _read_content_length_response(proc.stdout)
        assert [tool["name"] for tool in listed["result"]["tools"]] == list(EXPECTED_TOOLS)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)


def test_mcp_stdio_content_length_preserves_structured_diff_arguments(tmp_path: Path) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    captured: dict[str, object] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("content-length", "0"))
            body = self.rfile.read(length)
            payload = json.loads(body.decode("utf-8"))
            captured["payload"] = payload
            serialized = json.dumps(payload, sort_keys=True)
            response = {
                "ok": True,
                "tool_name": "create_single_loop_evidence_diff",
                "context_status": "single_loop_evidence_diff_ready",
                "retention": "process_and_discard",
                "retained_artifacts": [],
                "content_specific_delta": "dominant correlated outcomes" in serialized,
            }
            data = json.dumps(response).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = {**os.environ, "PYTHONPATH": str(Path.cwd() / "src")}
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "qcoder",
            "context-bridge",
            "mcp",
            "serve",
            "--token-file",
            str(token_file),
            "--base-url",
            f"http://127.0.0.1:{server.server_port}",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        assert proc.stdin is not None
        assert proc.stdout is not None
        proc.stdin.write(
            _content_length_message(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0"},
                    },
                }
            )
        )
        proc.stdin.flush()
        initialized = _read_content_length_response(proc.stdout)
        assert initialized["result"]["serverInfo"]["name"] == "qcoder-context-bridge"
        arguments = {
            "artifact_text": "Share-safe current evidence summary.",
            "before": {
                "goal": "verify whether the external result is consistent with the intended correlation pattern",
                "evidence": "circuit intent and readiness checks were documented",
                "unresolved": "no result evidence had yet been supplied",
                "assumptions": "external simulator configuration was appropriate",
            },
            "after": {
                "result_evidence": "user reports dominant correlated outcomes in a compact share-safe summary",
                "unresolved": "raw counts and independent execution verification were not supplied",
                "assumptions": "the compact result summary accurately reflects the external run",
            },
        }
        proc.stdin.write(
            _content_length_message(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "create_single_loop_evidence_diff",
                        "arguments": arguments,
                    },
                }
            )
        )
        proc.stdin.flush()
        called = _read_content_length_response(proc.stdout)
        structured = called["result"]["structuredContent"]
        assert structured["ok"] is True
        assert structured["content_specific_delta"] is True
        forwarded = captured["payload"]
        assert isinstance(forwarded, dict)
        assert isinstance(forwarded["before"], dict)
        assert isinstance(forwarded["after"], dict)
        assert forwarded["after"]["result_evidence"] == arguments["after"]["result_evidence"]
        assert forwarded["before"]["unresolved"] == arguments["before"]["unresolved"]
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
        server.shutdown()
        server.server_close()


def test_smoke_without_token_reports_sanitized_category(tmp_path: Path) -> None:
    result = run_smoke(base_url="https://example.invalid", token_file=tmp_path / "missing-token.txt")
    assert result["ok"] is False
    assert result["token_file_category"] == "token_file_missing"
    assert result["token_printed"] is False


def _successful_smoke_payload(tool_name: str) -> dict[str, object]:
    statuses = {
        "get_guided_evidence_context": "assistant_context_ready",
        "create_prompt_context": "prompt_context_ready",
        "create_evidence_context_pack": "evidence_context_pack_ready",
        "create_context_session_card": "context_session_card_ready",
        "create_run_readiness_card": "run_readiness_card_ready",
        "create_result_review_context_card": "result_review_context_card_ready",
        "create_next_check_plan": "next_check_plan_ready",
        "create_single_loop_evidence_diff": "single_loop_evidence_diff_ready",
    }
    return {
        "ok": True,
        "adapter_status_category": "success_2xx",
        "tool_name": tool_name,
        "context_status": statuses[tool_name],
        "retention": "process_and_discard",
        "retained_artifacts": [],
    }


def test_default_smoke_is_concise_and_uses_one_bounded_network_call(
    monkeypatch, tmp_path: Path
) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    network_calls: list[str] = []

    def fake_post(**kwargs: object) -> dict[str, object]:
        tool_name = str(kwargs["tool_name"])
        if "OPENQASM" in str(kwargs["artifact_text"]):
            return context_bridge_mcp.safe_error("forbidden_input_value")
        network_calls.append(tool_name)
        return _successful_smoke_payload(tool_name)

    monkeypatch.setattr(context_bridge_mcp, "post_context_bridge", fake_post)
    result = run_smoke(base_url="https://example.invalid", token_file=token_file)

    assert result["ok"] is True
    assert result["connection_status_category"] == "ready"
    assert result["token_accepted"] == "yes"
    assert result["tools_discovered"] == 8
    assert result["tools_visible"] == list(EXPECTED_TOOLS)
    assert result["bounded_call_passed"] is True
    assert result["unsafe_input_rejected"] is True
    assert network_calls == ["create_context_session_card"]


def test_default_smoke_human_output_and_json_compatibility(monkeypatch, tmp_path: Path) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    result = {
        "ok": True,
        "connection_status_category": "ready",
        "token_accepted": "yes",
        "tools_discovered": 8,
        "metadata_only": True,
    }
    monkeypatch.setattr(context_bridge_mcp, "run_smoke", lambda **_kwargs: result)

    human = io.StringIO()
    with redirect_stdout(human):
        rc = context_bridge_mcp.main(["mcp", "smoke", "--token-file", str(token_file)])
    assert rc == 0
    assert human.getvalue().splitlines() == [
        "Context Bridge connection: ready",
        "Token accepted: yes",
        "Tools discovered: 8",
    ]

    structured = io.StringIO()
    with redirect_stdout(structured):
        rc = context_bridge_mcp.main(["mcp", "smoke", "--token-file", str(token_file), "--json"])
    assert rc == 0
    assert json.loads(structured.getvalue()) == result


def test_full_smoke_stops_prompt_matrix_on_rate_limit_without_retrying_or_rejecting_token(
    monkeypatch, tmp_path: Path
) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    prompt_modes_called: list[object] = []

    def fake_post(**kwargs: object) -> dict[str, object]:
        tool_name = str(kwargs["tool_name"])
        artifact_text = str(kwargs["artifact_text"])
        if tool_name not in EXPECTED_TOOLS:
            return context_bridge_mcp.safe_error("unknown_tool")
        if kwargs.get("artifact_kind") == "server_artifact_id":
            return context_bridge_mcp.safe_error("unsupported_artifact_kind")
        if kwargs.get("mode") == "diagnose":
            return context_bridge_mcp.safe_error("invalid_prompt_context_mode")
        if tool_name == "create_single_loop_evidence_diff" and kwargs.get("after") is None:
            return context_bridge_mcp.safe_error("missing_explicit_diff_side")
        if "OPENQASM" in artifact_text or artifact_text.startswith("/home/"):
            return context_bridge_mcp.safe_error("forbidden_input_value")
        if tool_name == "create_prompt_context":
            prompt_modes_called.append(kwargs.get("mode"))
            if len(prompt_modes_called) == 4:
                return {
                    "ok": False,
                    "adapter_status_category": "http_429",
                    "error_category": "rate_limited",
                    "retry_after_category": "seconds",
                    "retention": "process_and_discard",
                    "retained_artifacts": [],
                }
        return _successful_smoke_payload(tool_name)

    monkeypatch.setattr(context_bridge_mcp, "post_context_bridge", fake_post)
    result = run_smoke(base_url="https://example.invalid", token_file=token_file, full=True)

    assert result["ok"] is False
    assert result["diagnostic_status_category"] == "rate_limit_pause_required"
    assert result["retry_after_category"] == "seconds"
    assert result["token_onboarding_failure"] is False
    assert prompt_modes_called == [None, "explain", "review", "revise"]
    assert result["cases"]["prompt_mode_troubleshoot_allowed"]["status_category"] == (
        "not_run_rate_limit_pause"
    )
    assert result["cases"]["prompt_mode_plan_next_checks_allowed"]["status_category"] == (
        "not_run_rate_limit_pause"
    )


def test_retry_after_is_categorized_without_automatic_retry(tmp_path: Path) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    calls = 0

    def rate_limited(_request: object, timeout: int = 20) -> object:
        nonlocal calls
        calls += 1
        body = io.BytesIO(json.dumps({"ok": False, "error_category": "rate_limited"}).encode("utf-8"))
        raise urllib.error.HTTPError(
            "https://example.invalid",
            429,
            "Too Many Requests",
            {"Retry-After": "30"},
            body,
        )

    payload = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="create_prompt_context",
        artifact_text="Share-safe current evidence summary.",
        opener=rate_limited,
    )

    assert calls == 1
    assert payload["adapter_status_category"] == "http_429"
    assert payload["retry_after_category"] == "seconds"


def test_full_smoke_does_not_call_prompt_modes_when_default_prompt_is_rate_limited(
    monkeypatch, tmp_path: Path
) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    prompt_calls: list[object] = []
    context_session_calls = 0

    def fake_post(**kwargs: object) -> dict[str, object]:
        nonlocal context_session_calls
        tool_name = str(kwargs["tool_name"])
        artifact_text = str(kwargs["artifact_text"])
        if tool_name not in EXPECTED_TOOLS:
            return context_bridge_mcp.safe_error("unknown_tool")
        if kwargs.get("artifact_kind") == "server_artifact_id":
            return context_bridge_mcp.safe_error("unsupported_artifact_kind")
        if kwargs.get("mode") == "diagnose":
            return context_bridge_mcp.safe_error("invalid_prompt_context_mode")
        if tool_name == "create_single_loop_evidence_diff" and kwargs.get("after") is None:
            return context_bridge_mcp.safe_error("missing_explicit_diff_side")
        if "OPENQASM" in artifact_text or artifact_text.startswith("/home/"):
            return context_bridge_mcp.safe_error("forbidden_input_value")
        if tool_name == "create_context_session_card":
            context_session_calls += 1
        if tool_name == "create_prompt_context":
            prompt_calls.append(kwargs.get("mode"))
            return {
                "ok": False,
                "adapter_status_category": "http_429",
                "error_category": "rate_limited",
                "retry_after_category": "http_date",
                "retention": "process_and_discard",
                "retained_artifacts": [],
            }
        return _successful_smoke_payload(tool_name)

    monkeypatch.setattr(context_bridge_mcp, "post_context_bridge", fake_post)
    result = run_smoke(base_url="https://example.invalid", token_file=token_file, full=True)

    assert context_session_calls == 2
    assert prompt_calls == [None]
    assert result["diagnostic_status_category"] == "rate_limit_pause_required"
    assert result["retry_after_category"] == "http_date"
    assert result["token_onboarding_failure"] is False


def test_full_smoke_stops_on_hard_token_rejection(monkeypatch, tmp_path: Path) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    calls = 0

    def rejected(**kwargs: object) -> dict[str, object]:
        nonlocal calls
        if "OPENQASM" in str(kwargs["artifact_text"]):
            return context_bridge_mcp.safe_error("forbidden_input_value")
        calls += 1
        return {
            "ok": False,
            "adapter_status_category": "http_401",
            "error_category": "token_rejected",
            "retention": "process_and_discard",
            "retained_artifacts": [],
        }

    monkeypatch.setattr(context_bridge_mcp, "post_context_bridge", rejected)
    result = run_smoke(base_url="https://example.invalid", token_file=token_file, full=True)

    assert calls == 1
    assert result["diagnostic_status_category"] == "token_rejected"
    assert result["token_onboarding_failure"] is True
    assert result["token_accepted"] == "no"
