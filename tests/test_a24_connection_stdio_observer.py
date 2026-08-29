from __future__ import annotations

import io
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from qcoder import context_bridge_mcp, current_loop_binding_mcp
from qcoder.context_bridge_connection import (
    PRIVATE_SERVER_NAME,
    PUBLIC_SERVER_NAME,
    connection_state_paths,
    connection_status,
    prepare_connection_state,
)

SETUP_GENERATION = "a" * 64
CLIENT_INFO = {"name": "cursor-vscode", "version": "1.7.0"}
TOKEN_SENTINEL = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
REQUEST_SENTINEL = "PRIVATE_CUSTOMER_REQUEST_MUST_NOT_BE_RETAINED_43091"


def _initialize(message_id: int) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": dict(CLIENT_INFO),
        },
    }


def _tools_list(message_id: int) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "method": "tools/list", "params": {}}


def _public_call(message_id: int) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "method": "tools/call",
        "params": {
            "name": "get_guided_evidence_context",
            "arguments": {
                "artifact_text": REQUEST_SENTINEL,
                "artifact_kind": "share_safe_summary",
            },
        },
    }


def _write_token(path: Path) -> None:
    path.write_text(TOKEN_SENTINEL, encoding="utf-8")
    path.chmod(0o600)


def _successful_public_call(**kwargs: object) -> dict[str, object]:
    return {
        "ok": True,
        "tool_name": str(kwargs["tool_name"]),
        "context_status": "assistant_context_ready",
        "retention": "process_and_discard",
        "retained_artifacts": [],
    }


def _run_json_lines(
    monkeypatch,
    runner: Callable[..., int],
    requests: list[dict[str, Any]],
    **runner_kwargs: object,
) -> tuple[int, list[dict[str, Any]]]:
    input_bytes = "".join(json.dumps(value) + "\n" for value in requests).encode("utf-8")
    raw_input = io.BytesIO(input_bytes)
    raw_output = io.BytesIO()
    stdin = io.TextIOWrapper(raw_input, encoding="utf-8")
    stdout = io.TextIOWrapper(raw_output, encoding="utf-8", write_through=True)
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)

    result = runner(**runner_kwargs)
    stdout.flush()
    output = raw_output.getvalue().decode("utf-8")
    stdin.detach()
    stdout.detach()
    responses = [json.loads(line) for line in output.splitlines() if line.strip()]
    return result, responses


def _public_expected(requests: list[dict[str, Any]], *, token_file: Path) -> list[dict[str, Any]]:
    responses: list[dict[str, Any]] = []
    for request in requests:
        response = context_bridge_mcp.handle_jsonrpc_message(
            request,
            base_url="https://example.invalid",
            token_file=token_file,
        )
        assert isinstance(response, dict)
        responses.append(response)
    return responses


def _private_expected(
    requests: list[dict[str, Any]], *, workspace_root: Path
) -> list[dict[str, Any]]:
    responses: list[dict[str, Any]] = []
    for request in requests:
        response = current_loop_binding_mcp.handle_binding_jsonrpc_message(
            request,
            workspace_root=workspace_root,
        )
        assert isinstance(response, dict)
        responses.append(response)
    return responses


def test_stdio_loops_observe_real_12_plus_2_and_successful_public_call(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest = prepare_connection_state(
        workspace,
        client="cursor",
        configuration_verified=True,
        credential_verified=True,
        setup_generation=SETUP_GENERATION,
    )
    state_root = connection_state_paths(workspace)[0].parent
    token_file = tmp_path / "context-bridge-token.txt"
    _write_token(token_file)
    monkeypatch.setattr(context_bridge_mcp, "post_context_bridge", _successful_public_call)

    public_requests = [_initialize(1), _tools_list(2), _public_call(3)]
    public_expected = _public_expected(public_requests, token_file=token_file)
    public_rc, public_responses = _run_json_lines(
        monkeypatch,
        context_bridge_mcp.serve_mcp_stdio,
        public_requests,
        base_url="https://example.invalid",
        token_file=token_file,
        connection_state_root=state_root,
        connection_generation=SETUP_GENERATION,
    )

    private_requests = [_initialize(4), _tools_list(5)]
    private_expected = _private_expected(private_requests, workspace_root=workspace)
    private_rc, private_responses = _run_json_lines(
        monkeypatch,
        current_loop_binding_mcp.serve_binding_mcp_stdio,
        private_requests,
        workspace_root=workspace,
        connection_state_root=state_root,
        connection_generation=SETUP_GENERATION,
    )

    assert public_rc == private_rc == 0
    assert public_responses == public_expected
    assert private_responses == private_expected

    status = connection_status(workspace_root=workspace)
    assert manifest["configured"] is True
    assert status["ok"] is True
    assert status["connected"] is True
    assert status["category"] == "connected"
    assert status["public_tools_discovered"] == 12
    assert status["private_operations_discovered"] == 2
    assert status["read_only_qcoder_request_verified"] is True
    assert status["qualified"] is False
    assert status["client_qualification_created"] is False

    _, public_receipt_path, private_receipt_path = connection_state_paths(workspace)
    public_receipt = json.loads(public_receipt_path.read_text(encoding="utf-8"))
    private_receipt = json.loads(private_receipt_path.read_text(encoding="utf-8"))
    assert public_receipt["server_name"] == PUBLIC_SERVER_NAME
    assert public_receipt["initialized"] is True
    assert public_receipt["inventory_verified"] is True
    assert public_receipt["read_only_qcoder_request_verified"] is True
    assert private_receipt["server_name"] == PRIVATE_SERVER_NAME
    assert private_receipt["initialized"] is True
    assert private_receipt["inventory_verified"] is True
    assert private_receipt["read_only_qcoder_request_verified"] is False

    retained = "\n".join(
        path.read_text(encoding="utf-8") for path in connection_state_paths(workspace)
    )
    assert REQUEST_SENTINEL not in retained
    assert TOKEN_SENTINEL not in retained
    assert CLIENT_INFO["name"] not in retained
    assert CLIENT_INFO["version"] not in retained
    assert "artifact_text" not in retained
    assert 'raw_request_retained":false' in retained
    assert 'raw_response_retained":false' in retained
    assert 'raw_client_stream_retained":false' in retained


def test_observer_write_failure_never_changes_public_or_private_stdio_responses(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "unwritable-observer-state"
    token_file = tmp_path / "context-bridge-token.txt"
    _write_token(token_file)
    monkeypatch.setattr(context_bridge_mcp, "post_context_bridge", _successful_public_call)

    public_requests = [_initialize(10), _tools_list(11), _public_call(12)]
    private_requests = [_initialize(20), _tools_list(21)]
    public_expected = _public_expected(public_requests, token_file=token_file)
    private_expected = _private_expected(private_requests, workspace_root=workspace)

    def fail_observer(**_kwargs: object) -> bool:
        raise OSError("simulated observer write failure")

    monkeypatch.setattr(context_bridge_mcp, "record_server_exchange", fail_observer)
    public_rc, public_responses = _run_json_lines(
        monkeypatch,
        context_bridge_mcp.serve_mcp_stdio,
        public_requests,
        base_url="https://example.invalid",
        token_file=token_file,
        connection_state_root=state_root,
        connection_generation=SETUP_GENERATION,
    )

    monkeypatch.setattr(current_loop_binding_mcp, "record_server_exchange", fail_observer)
    private_rc, private_responses = _run_json_lines(
        monkeypatch,
        current_loop_binding_mcp.serve_binding_mcp_stdio,
        private_requests,
        workspace_root=workspace,
        connection_state_root=state_root,
        connection_generation=SETUP_GENERATION,
    )

    assert public_rc == private_rc == 0
    assert public_responses == public_expected
    assert private_responses == private_expected
    assert not state_root.exists()
