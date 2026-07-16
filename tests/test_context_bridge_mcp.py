from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
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
    assert names == list(EXPECTED_TOOLS)
    assert "suggest_next_checks" not in names
    assert "apply_repo_edit" not in names


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
        "/home/example/project/file.py",
        "repo_path=src/example.py",
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


def test_smoke_without_token_reports_sanitized_category(tmp_path: Path) -> None:
    result = run_smoke(base_url="https://example.invalid", token_file=tmp_path / "missing-token.txt")
    assert result["ok"] is False
    assert result["token_file_category"] == "token_file_missing"
    assert result["token_printed"] is False
